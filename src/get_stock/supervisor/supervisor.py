from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from get_stock.acquisition import (
    AcquisitionRequest,
    AcquisitionResult,
    DataAcquisitionCoordinator,
)
from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.document_acquisition import (
    DocumentRecoveryCoordinator,
    DocumentRecoveryRequest,
    DocumentRecoveryResult,
)
from get_stock.supervisor.agent_registry import AgentRegistry
from get_stock.supervisor.artifacts import (
    build_artifact_manifest,
    supervisor_artifact_paths,
    write_supervisor_artifacts,
)
from get_stock.supervisor.cache_inspector import find_blocking_cache_gaps, inspect_local_cache
from get_stock.supervisor.catalog import REPORT_AGENT
from get_stock.supervisor.date_resolver import resolve_time_scope
from get_stock.supervisor.planner import build_plan_from_understanding
from get_stock.supervisor.query_understanding import understand_supervisor_question
from get_stock.supervisor.reasoner import SupervisorPlanningReasoner
from get_stock.supervisor.report_selector import select_processed_reports
from get_stock.supervisor.result_inspector import collect_missing_data, recommend_actions
from get_stock.supervisor.schemas import (
    AgentExecution,
    SupervisorPlan,
    SupervisorResult,
    SupervisorTask,
)
from get_stock.supervisor.task_factory import (
    build_comprehensive_task,
    build_specialist_tasks,
)

SUPERVISOR_VERSION = "1.4"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class SupervisorError(RuntimeError):
    pass


class StockAnalysisSupervisor:
    """Coordinate bounded specialist agents and the final synthesis agent."""

    def __init__(
        self,
        data_dir: Path,
        *,
        registry: AgentRegistry | None = None,
        planning_reasoner: SupervisorPlanningReasoner | None = None,
        acquisition_coordinator: DataAcquisitionCoordinator | None = None,
        document_coordinator: DocumentRecoveryCoordinator | None = None,
        agent_types: AgentTypeRegistry | None = None,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.agent_types = (
            agent_types
            or (registry.agent_types if registry is not None else None)
            or build_builtin_agent_types()
        )
        self.registry = registry or AgentRegistry(self.data_dir, agent_types=self.agent_types)
        self.planning_reasoner = planning_reasoner
        self.acquisition_coordinator = acquisition_coordinator
        self.document_coordinator = document_coordinator

    def analyze(self, task: SupervisorTask | dict[str, Any]) -> SupervisorResult:
        understood = self.understand(task)
        prepared = self.plan(understood)
        recovered = self.recover(prepared)
        documents_recovered = self.recover_documents(recovered)
        executed = self.execute(documents_recovered)
        synthesized = self.synthesize(executed)
        return self.finalize(synthesized)

    def prepare(self, task: SupervisorTask | dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible convenience wrapper for understanding plus planning."""
        return self.plan(self.understand(task))

    def understand(self, task: SupervisorTask | dict[str, Any]) -> dict[str, Any]:
        """Convert user text to a validated semantic request without touching data or spiders."""
        try:
            normalized = (
                task if isinstance(task, SupervisorTask) else SupervisorTask.model_validate(task)
            )
            understanding = understand_supervisor_question(
                normalized,
                reasoner=self.planning_reasoner,
                agent_types=self.agent_types,
            )
            resolved_dates = resolve_time_scope(normalized, understanding)
        except (ValidationError, ValueError) as exc:
            raise SupervisorError(str(exc)) from exc
        return {
            "task": normalized,
            "understanding": understanding,
            "resolved_dates": resolved_dates,
        }

    def plan(self, understood: dict[str, Any]) -> dict[str, Any]:
        """Create the allowlisted analysis plan, specialist tasks, and cache snapshot."""
        normalized: SupervisorTask = understood["task"]
        understanding = understood["understanding"]
        try:
            plan = build_plan_from_understanding(
                normalized, understanding, agent_types=self.agent_types
            )
            reports = ()
            if REPORT_AGENT in plan.expected_agents and normalized.allow_report_fallback:
                resolved_dates = understood["resolved_dates"]
                reports = select_processed_reports(
                    self.data_dir,
                    plan.stock_code,
                    report_type=plan.report_type,
                    period_from=resolved_dates.report_period_from,
                    period_to=resolved_dates.report_period_to,
                    limit=plan.financial_years,
                )
            specialist_tasks = build_specialist_tasks(
                normalized,
                plan,
                reports=reports,
                agent_types=self.agent_types,
            )
            cache_snapshot = inspect_local_cache(
                self.data_dir, plan, specialist_tasks, agent_types=self.agent_types
            )
        except (ValidationError, ValueError) as exc:
            raise SupervisorError(str(exc)) from exc
        return {
            **understood,
            "plan": plan,
            "cache_snapshot": cache_snapshot,
            "reports": reports,
            "specialist_tasks": specialist_tasks,
        }

    def recover(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Optionally fill blocking structured-data gaps before specialist execution."""
        task: SupervisorTask = prepared["task"]
        gaps = find_blocking_cache_gaps(
            prepared["plan"],
            prepared["specialist_tasks"],
            prepared["cache_snapshot"],
            agent_types=self.agent_types,
        )
        if not task.auto_crawl or task.max_crawl_rounds == 0:
            acquisition = AcquisitionResult(
                status="not_requested",
                requested_datasets=gaps,
                remaining_datasets=gaps,
            )
            return {**prepared, "acquisition": acquisition}
        if not gaps:
            return {
                **prepared,
                "acquisition": AcquisitionResult(status="skipped"),
            }

        coordinator = self.acquisition_coordinator or DataAcquisitionCoordinator(self.data_dir)
        acquisition = coordinator.acquire(
            AcquisitionRequest(stock_code=prepared["plan"].stock_code, datasets=tuple(gaps))
        )
        refreshed = inspect_local_cache(
            self.data_dir,
            prepared["plan"],
            prepared["specialist_tasks"],
            agent_types=self.agent_types,
        )
        return {**prepared, "cache_snapshot": refreshed, "acquisition": acquisition}

    def recover_documents(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Recover full-report PDFs and chunks, then rebuild document-bound tasks."""
        task: SupervisorTask = prepared["task"]
        plan: SupervisorPlan = prepared["plan"]
        if REPORT_AGENT not in plan.expected_agents or not plan.document_intent.needs_full_report:
            result = DocumentRecoveryResult(status="skipped")
            return {**prepared, "document_acquisition": result}
        if (
            not task.auto_documents
            or task.max_document_rounds == 0
            or not task.allow_report_fallback
        ):
            result = DocumentRecoveryResult(status="not_requested")
            return {**prepared, "document_acquisition": result}

        dates = prepared["resolved_dates"]
        if (
            plan.report_type not in {"annual", "semiannual"}
            or dates.report_period_from is None
            or dates.report_period_to is None
            or dates.disclosure_search_from is None
            or dates.disclosure_search_to is None
        ):
            result = DocumentRecoveryResult(
                status="failed",
                warnings=list(dates.warnings),
                error="automatic recovery requires a supported full-report type and date range",
            )
            return {**prepared, "document_acquisition": result}

        coordinator = self.document_coordinator or DocumentRecoveryCoordinator(self.data_dir)
        try:
            request = DocumentRecoveryRequest(
                stock_code=plan.stock_code,
                report_type=plan.report_type,
                report_period_from=dates.report_period_from,
                report_period_to=dates.report_period_to,
                disclosure_search_from=dates.disclosure_search_from,
                disclosure_search_to=dates.disclosure_search_to,
                target_count=min(plan.financial_years, task.max_documents),
                heading_mode=task.heading_mode,
            )
            result = coordinator.recover(request)
        except Exception as exc:
            result = DocumentRecoveryResult(
                status="failed",
                error=f"document recovery failed: {exc}",
            )
        reports = select_processed_reports(
            self.data_dir,
            plan.stock_code,
            report_type=plan.report_type,
            period_from=dates.report_period_from,
            period_to=dates.report_period_to,
            limit=min(plan.financial_years, task.max_documents),
        )
        specialist_tasks = build_specialist_tasks(
            task,
            plan,
            reports=reports,
            agent_types=self.agent_types,
        )
        cache_snapshot = inspect_local_cache(
            self.data_dir,
            plan,
            specialist_tasks,
            agent_types=self.agent_types,
        )
        return {
            **prepared,
            "document_acquisition": result,
            "reports": reports,
            "specialist_tasks": specialist_tasks,
            "cache_snapshot": cache_snapshot,
        }

    def execute(self, prepared: dict[str, Any]) -> dict[str, Any]:
        task: SupervisorTask = prepared["task"]
        plan: SupervisorPlan = prepared["plan"]
        specialist_tasks: dict[str, object] = prepared["specialist_tasks"]
        results: dict[str, dict[str, Any]] = {}
        executions: list[AgentExecution] = []
        failures: dict[str, str] = {}
        extra_missing: list[dict[str, Any]] = []

        for agent in plan.expected_agents:
            agent_task = specialist_tasks.get(agent)
            child_task_id = f"{task.task_id}-{_agent_suffix(agent)}"
            if agent_task is None:
                reason = (
                    "report fallback is disabled"
                    if agent == REPORT_AGENT and not task.allow_report_fallback
                    else "no processed full-report chunks are available"
                )
                executions.append(
                    AgentExecution(
                        agent=agent,
                        task_id=child_task_id,
                        status="not_run",
                        error=reason,
                    )
                )
                extra_missing.append(
                    {
                        "source_agent": agent,
                        "topic": None,
                        "dataset": "chunks.jsonl" if agent == REPORT_AGENT else None,
                        "reason_code": "report_not_available",
                        "reason": reason,
                        "blocking": True,
                        "recoverable": agent == REPORT_AGENT,
                        "recommended_action": (
                            "process_full_report_pdf" if agent == REPORT_AGENT else None
                        ),
                    }
                )
                continue
            try:
                result = self.registry.run(agent, agent_task)
                payload = (
                    result.model_dump(mode="json")
                    if hasattr(result, "model_dump")
                    else dict(result)
                )
                results[agent] = payload
                executions.append(
                    AgentExecution(
                        agent=agent,
                        task_id=str(payload.get("task_id") or child_task_id),
                        status=str(payload.get("status") or "failed"),
                    )
                )
            except Exception as exc:  # isolate one specialist without losing other evidence
                failures[agent] = str(exc)
                executions.append(
                    AgentExecution(
                        agent=agent,
                        task_id=child_task_id,
                        status="failed",
                        error=str(exc),
                    )
                )
        return {
            **prepared,
            "specialist_results": results,
            "executions": executions,
            "failures": failures,
            "extra_missing": extra_missing,
        }

    def synthesize(self, executed: dict[str, Any]) -> dict[str, Any]:
        task: SupervisorTask = executed["task"]
        plan: SupervisorPlan = executed["plan"]
        comprehensive_result = None
        comprehensive_error = None
        try:
            comprehensive_task = build_comprehensive_task(
                task,
                plan,
                executed["specialist_results"],
            )
            result = self.registry.run("comprehensive_analysis", comprehensive_task)
            comprehensive_result = (
                result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
            )
        except Exception as exc:
            comprehensive_error = str(exc)
        return {
            **executed,
            "comprehensive_result": comprehensive_result,
            "comprehensive_error": comprehensive_error,
        }

    def finalize(self, state: dict[str, Any]) -> SupervisorResult:
        task: SupervisorTask = state["task"]
        plan: SupervisorPlan = state["plan"]
        comprehensive = state["comprehensive_result"]
        missing = [
            *collect_missing_data(state["specialist_results"]),
            *state["extra_missing"],
        ]
        failures = dict(state["failures"])
        if state["comprehensive_error"]:
            failures["comprehensive_analysis"] = state["comprehensive_error"]
        actions = recommend_actions(
            missing,
            failures,
            auto_crawl_requested=task.auto_crawl,
            auto_documents_requested=task.auto_documents,
        )
        status = "failed" if comprehensive is None else str(comprehensive["status"])
        paths = supervisor_artifact_paths(self.data_dir, plan.stock_code, task.task_id)
        artifacts = build_artifact_manifest(paths, comprehensive)
        result = SupervisorResult(
            supervisor_version=SUPERVISOR_VERSION,
            task_id=task.task_id,
            status=status,
            stock_code=plan.stock_code,
            question=task.question,
            llm_requested=task.require_llm,
            expected_agents=list(plan.expected_agents),
            executions=state["executions"],
            acquisition=state["acquisition"].model_dump(mode="json"),
            document_acquisition=state["document_acquisition"].model_dump(mode="json"),
            missing_data=missing,
            recommended_actions=actions,
            comprehensive_result=comprehensive,
            artifacts=artifacts,
            generated_at=datetime.now(CHINA_TZ).isoformat(),
        )
        write_supervisor_artifacts(
            request=task.model_dump(mode="json"),
            understanding=state["understanding"].model_dump(mode="json"),
            resolved_dates=state["resolved_dates"].model_dump(mode="json"),
            plan=plan.model_dump(mode="json"),
            cache_snapshot=[item.model_dump(mode="json") for item in state["cache_snapshot"]],
            acquisition=state["acquisition"].model_dump(mode="json"),
            document_acquisition=state["document_acquisition"].model_dump(mode="json"),
            specialist_results=state["specialist_results"],
            result=result,
            paths=paths,
        )
        return result


def _agent_suffix(agent: str) -> str:
    return {
        "financial_analysis": "financial",
        "market_trading": "market",
        "shareholder_analysis": "shareholders",
        "financial_report_analysis": "report",
    }.get(agent, agent)
