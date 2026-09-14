from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from get_stock.financial_agent.catalog import TOPIC_DATASETS, TOPIC_LABELS
from get_stock.financial_agent.loaders import (
    StructuredDataAccessError,
    StructuredFinancialDataLoader,
)
from get_stock.financial_agent.metrics import ANALYZERS, AnalysisContext
from get_stock.financial_agent.reasoner import FinancialReasoner, deterministic_reasoner
from get_stock.financial_agent.schemas import (
    FinancialAnalysisResult,
    FinancialAnalysisTask,
    FinancialLLMAnalysis,
)
from get_stock.financial_agent.verifier import verify_llm_analysis

AGENT_VERSION = "1.1"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
BASE_LIMITATIONS = (
    "未使用PDF，不能确认管理层对财务变化的解释",
    "三张财务报表当前未显式保存金额单位，绝对值保留原报表单位",
    "不访问网络、不调用爬虫，也不提供投资建议",
)


class FinancialAnalysisError(RuntimeError):
    """Raised when a financial specialist task or its evidence is invalid."""


class FinancialAnalysisAgent:
    """Specialist invoked by a Supervisor with a normalized task contract."""

    def __init__(self, data_dir: Path, *, reasoner: FinancialReasoner | None = None) -> None:
        self.data_dir = data_dir.resolve()
        self.reasoner = reasoner

    def analyze(self, task: FinancialAnalysisTask | dict[str, Any]) -> FinancialAnalysisResult:
        prepared = self.prepare(task)
        llm_analysis, llm_used = self.reason(prepared)
        return self.finalize(prepared, llm_analysis, llm_used=llm_used)

    def prepare(self, task: FinancialAnalysisTask | dict[str, Any]) -> dict[str, Any]:
        """Validate the Supervisor task and build a bounded financial fact packet."""
        try:
            normalized_task = (
                task
                if isinstance(task, FinancialAnalysisTask)
                else FinancialAnalysisTask.model_validate(task)
            )
            normalized_task.constraints.assert_supported()
            loader = StructuredFinancialDataLoader(self.data_dir, normalized_task.stock_code)
            bundle = loader.load_many(set(normalized_task.dataset_names))
        except (ValidationError, ValueError, StructuredDataAccessError) as exc:
            raise FinancialAnalysisError(str(exc)) from exc

        profile = bundle.get("company_profile")
        profile = profile if isinstance(profile, dict) else {}
        context = AnalysisContext(
            report_type=normalized_task.report_type,
            years=normalized_task.max_periods,
            period_from=normalized_task.period_from,
            period_to=normalized_task.period_to,
            is_financial_company=self._is_financial_company(profile),
        )
        missing_data = self._check_data_sufficiency(normalized_task, bundle)
        dimensions: dict[str, dict[str, Any]] = {}
        unavailable_topics: list[str] = []
        for topic in normalized_task.topics:
            result = ANALYZERS[topic](bundle, context)
            if result is None or not result["findings"]:
                unavailable_topics.append(topic)
            else:
                dimensions[topic] = result
        for topic in unavailable_topics:
            missing_data.append(
                {
                    "topic": topic,
                    "dataset": None,
                    "reason": f"现有字段不足以完成{TOPIC_LABELS[topic]}分析",
                    "blocking": True,
                }
            )

        self._verify_deterministic_evidence(dimensions, context.evidence)
        requested_count = len(normalized_task.topics)
        completed_count = len(dimensions)
        missing_data = self._deduplicate_missing_data(missing_data)
        status = (
            "insufficient_data"
            if completed_count == 0
            else (
                "completed"
                if completed_count == requested_count and not missing_data
                else "partial"
            )
        )
        periods = sorted(
            {str(item["report_period"]) for item in context.evidence if item.get("report_period")}
        )
        deterministic_summary = self._build_summary(dimensions, unavailable_topics)
        return {
            "task": normalized_task,
            "profile": profile,
            "status": status,
            "periods": periods,
            "dimensions": dimensions,
            "evidence": context.evidence,
            "missing_data": missing_data,
            "accessed_datasets": sorted(dataset for dataset, value in bundle.items() if value),
            "deterministic_summary": deterministic_summary,
            "limitations": list(BASE_LIMITATIONS),
            "base_confidence": round(
                0.9 * completed_count / requested_count if requested_count else 0.0,
                2,
            ),
        }

    def reason(self, prepared: dict[str, Any]) -> tuple[FinancialLLMAnalysis, bool]:
        """Run one bounded LLM call, or an explicit deterministic offline fallback."""
        task: FinancialAnalysisTask = prepared["task"]
        fact_packet = self._fact_packet(prepared)
        if prepared["status"] == "insufficient_data":
            return deterministic_reasoner(fact_packet), False
        if self.reasoner is None:
            if task.constraints.require_llm:
                raise FinancialAnalysisError("task requires an LLM but no reasoner was injected")
            return deterministic_reasoner(fact_packet), False
        try:
            analysis = self.reasoner(fact_packet)
            analysis = (
                analysis
                if isinstance(analysis, FinancialLLMAnalysis)
                else FinancialLLMAnalysis.model_validate(analysis)
            )
            verify_llm_analysis(analysis, prepared["evidence"])
        except Exception as exc:  # retain deterministic evidence when the LLM output is invalid
            fallback = deterministic_reasoner(fact_packet)
            fallback.limitations.append(
                "财务分析 LLM 输出未通过校验，已降级为确定性分析：" + str(exc)
            )
            return fallback, False
        return analysis, True

    def finalize(
        self,
        prepared: dict[str, Any],
        analysis: FinancialLLMAnalysis,
        *,
        llm_used: bool,
    ) -> FinancialAnalysisResult:
        """Build the stable specialist result consumed by the comprehensive agent."""
        task: FinancialAnalysisTask = prepared["task"]
        profile: dict[str, Any] = prepared["profile"]
        periods: list[str] = prepared["periods"]
        limitations = list(dict.fromkeys([*prepared["limitations"], *analysis.limitations]))
        return FinancialAnalysisResult(
            agent_version=AGENT_VERSION,
            task_id=task.task_id,
            status=prepared["status"],
            llm_used=llm_used,
            stock_code=task.stock_code,
            stock_name=profile.get("stock_name"),
            industry_name=profile.get("industry_name"),
            analysis_scope={
                "topics": list(task.topics),
                "report_type": task.report_type,
                "max_periods": task.max_periods,
                "from": periods[0] if periods else task.period_from,
                "to": periods[-1] if periods else task.period_to,
            },
            accessed_datasets=prepared["accessed_datasets"],
            summary=analysis.overall_assessment,
            dimensions=prepared["dimensions"],
            key_strengths=analysis.key_strengths,
            key_risks=analysis.key_risks,
            trend_assessments=analysis.trend_assessments,
            evidence=prepared["evidence"],
            missing_data=prepared["missing_data"],
            limitations=limitations,
            confidence=prepared["base_confidence"],
            generated_at=datetime.now(CHINA_TZ).isoformat(),
        )

    @staticmethod
    def _fact_packet(prepared: dict[str, Any]) -> dict[str, Any]:
        task: FinancialAnalysisTask = prepared["task"]
        profile: dict[str, Any] = prepared["profile"]
        return {
            "task_id": task.task_id,
            "company": {
                "stock_code": task.stock_code,
                "stock_name": profile.get("stock_name"),
                "industry_name": profile.get("industry_name"),
            },
            "analysis_scope": {
                "topics": list(task.topics),
                "report_type": task.report_type,
                "max_periods": task.max_periods,
            },
            "status": prepared["status"],
            "dimensions": prepared["dimensions"],
            "evidence": prepared["evidence"],
            "missing_data": prepared["missing_data"],
            "deterministic_summary": prepared["deterministic_summary"],
            "limitations": prepared["limitations"],
        }

    @staticmethod
    def _is_financial_company(profile: dict[str, Any]) -> bool:
        text = " ".join(
            str(profile.get(field) or "")
            for field in ("industry_name", "main_business", "company_name")
        )
        return any(keyword in text for keyword in ("银行", "保险", "证券", "金融服务"))

    @staticmethod
    def _check_data_sufficiency(
        task: FinancialAnalysisTask, bundle: dict[str, Any]
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for topic in task.topics:
            for dataset in TOPIC_DATASETS[topic]["required"]:
                value = bundle.get(dataset)
                if not value:
                    missing.append(
                        {
                            "topic": topic,
                            "dataset": dataset,
                            "reason": f"Supervisor未提供或本地缺少{dataset}",
                            "blocking": True,
                        }
                    )
                    continue
                if dataset in {
                    "financial_indicators",
                    "balance_sheets",
                    "income_statements",
                    "cash_flow_statements",
                }:
                    matching = [
                        record
                        for record in value
                        if record.get("report_type") == task.report_type
                        and FinancialAnalysisAgent._inside_period(record, task)
                    ]
                    if not matching:
                        missing.append(
                            {
                                "topic": topic,
                                "dataset": dataset,
                                "reason": f"缺少report_type={task.report_type}的目标期数据",
                                "blocking": True,
                            }
                        )
                    elif len(matching) < task.max_periods:
                        missing.append(
                            {
                                "topic": topic,
                                "dataset": dataset,
                                "reason": (
                                    f"请求{task.max_periods}期，当前只有{len(matching)}期"
                                    f"report_type={task.report_type}的数据"
                                ),
                                "blocking": False,
                            }
                        )
        return missing

    @staticmethod
    def _inside_period(record: dict[str, Any], task: FinancialAnalysisTask) -> bool:
        report_date = str(record.get("report_date") or "")
        return not (
            (task.period_from and report_date < task.period_from)
            or (task.period_to and report_date > task.period_to)
        )

    @staticmethod
    def _verify_deterministic_evidence(
        dimensions: dict[str, dict[str, Any]], evidence: list[dict[str, Any]]
    ) -> None:
        valid_ids = {item["evidence_id"] for item in evidence}
        referenced_ids = {
            evidence_id
            for dimension in dimensions.values()
            for finding in dimension["findings"]
            for evidence_id in finding["evidence_ids"]
        }
        missing_ids = referenced_ids - valid_ids
        if missing_ids:
            raise FinancialAnalysisError(
                f"analysis contains unresolved evidence IDs: {sorted(missing_ids)}"
            )

    @staticmethod
    def _build_summary(dimensions: dict[str, dict[str, Any]], unavailable_topics: list[str]) -> str:
        if not dimensions:
            return "现有结构化数据不足，无法完成请求的财务分析。"
        summary = (
            "；".join(f"{value['label']}：{value['rating']}" for value in dimensions.values())
            + "。"
        )
        if unavailable_topics:
            labels = "、".join(TOPIC_LABELS[topic] for topic in unavailable_topics)
            summary += f" {labels}因字段不足未生成结论。"
        return summary

    @staticmethod
    def _deduplicate_missing_data(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for record in records:
            key = (record.get("topic"), record.get("dataset"), record.get("reason"))
            if key not in seen:
                seen.add(key)
                unique.append(record)
        return unique
