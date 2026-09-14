from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.comprehensive_agent.adapters import (
    SpecialistResultError,
    adapt_specialist_results,
)
from get_stock.comprehensive_agent.artifacts import artifact_paths, write_analysis_artifacts
from get_stock.comprehensive_agent.conflicts import detect_conflicts
from get_stock.comprehensive_agent.coverage import assess_coverage, calculate_confidence
from get_stock.comprehensive_agent.markdown_renderer import render_markdown
from get_stock.comprehensive_agent.reasoner import (
    ComprehensiveReasoner,
    deterministic_reasoner,
)
from get_stock.comprehensive_agent.schemas import (
    AnalysisArtifacts,
    ComprehensiveAnalysisResult,
    ComprehensiveAnalysisTask,
    ComprehensiveLLMAnalysis,
)
from get_stock.comprehensive_agent.verifier import verify_comprehensive_analysis

AGENT_VERSION = "1.0"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
BASE_LIMITATIONS = (
    "综合分析仅消费专业Agent结果，不直接读取股票原始数据、PDF或财报chunk",
    "综合分析不重新计算或覆盖专业Agent提供的数值",
    "未调用的非必要Agent不视为数据缺失",
    "不访问网络、爬虫，不预测股价，也不提供投资建议",
)


class ComprehensiveAnalysisError(RuntimeError):
    pass


class ComprehensiveAnalysisAgent:
    def __init__(
        self,
        data_dir: Path,
        *,
        reasoner: ComprehensiveReasoner | None = None,
        agent_types: AgentTypeRegistry | None = None,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.reasoner = reasoner
        self.agent_types = agent_types or build_builtin_agent_types()

    def analyze(
        self, task: ComprehensiveAnalysisTask | dict[str, Any]
    ) -> ComprehensiveAnalysisResult:
        prepared = self.prepare(task)
        analysis, llm_used = self.reason(prepared)
        return self.finalize(prepared, analysis, llm_used=llm_used)

    def prepare(self, task: ComprehensiveAnalysisTask | dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = (
                task
                if isinstance(task, ComprehensiveAnalysisTask)
                else ComprehensiveAnalysisTask.model_validate(task)
            )
            normalized.constraints.assert_supported()
            adapted = adapt_specialist_results(normalized, self.agent_types)
        except (ValidationError, ValueError, SpecialistResultError) as exc:
            raise ComprehensiveAnalysisError(str(exc)) from exc

        requested_topics = {item.topic for item in normalized.requirements}
        findings = [
            item for item in adapted["findings"] if requested_topics.intersection(item.topics)
        ]
        referenced_evidence = {
            evidence_id for item in findings for evidence_id in item.source_evidence_ids
        }
        evidence = [item for item in adapted["evidence"] if item.evidence_id in referenced_evidence]
        conflicts = detect_conflicts(findings, evidence)
        coverage = assess_coverage(
            normalized,
            findings,
            conflicts,
            adapted["agent_statuses"],
        )
        answered = sum(item.status == "answered" for item in coverage)
        status = (
            "insufficient_data"
            if answered == 0 and not any(item.supporting_finding_ids for item in coverage)
            else "completed"
            if answered == len(coverage) and not conflicts
            else "partial"
        )
        missing_data = [
            item
            for item in adapted["missing_data"]
            if not item.get("synthesis_topic") or item["synthesis_topic"] in requested_topics
        ]
        for item in coverage:
            if item.status != "answered":
                missing_data.append(
                    {
                        "source_agent": "supervisor",
                        "requirement_id": item.requirement_id,
                        "topic": item.topic,
                        "reason_code": f"requirement_{item.status}",
                        "reason": item.reason or "该分析要求尚未得到完整支持",
                        "blocking": item.status in {"unanswered", "conflicted"},
                    }
                )
        return {
            "task": normalized,
            **adapted,
            "findings": findings,
            "evidence": evidence,
            "conflicts": conflicts,
            "coverage": coverage,
            "status": status,
            "missing_data": missing_data,
            "confidence": calculate_confidence(
                coverage,
                findings,
                conflicts,
                self.agent_types.source_weights(),
            ),
            "limitations": list(dict.fromkeys([*BASE_LIMITATIONS, *adapted["limitations"]])),
        }

    def reason(self, prepared: dict[str, Any]) -> tuple[ComprehensiveLLMAnalysis, bool]:
        task: ComprehensiveAnalysisTask = prepared["task"]
        packet = self._synthesis_packet(prepared)
        if prepared["status"] == "insufficient_data":
            return deterministic_reasoner(packet), False
        if self.reasoner is None:
            if task.constraints.require_llm:
                raise ComprehensiveAnalysisError(
                    "task requires an LLM but no reasoner was injected"
                )
            return deterministic_reasoner(packet), False
        try:
            analysis = self.reasoner(packet)
            analysis = (
                analysis
                if isinstance(analysis, ComprehensiveLLMAnalysis)
                else ComprehensiveLLMAnalysis.model_validate(analysis)
            )
            verify_comprehensive_analysis(analysis, prepared["findings"], task)
        except Exception as exc:  # preserve verified local findings when the LLM path fails
            fallback = deterministic_reasoner(packet)
            fallback.limitations.append(
                "综合分析 LLM 输出未通过校验，已降级为确定性综合：" + str(exc)
            )
            return fallback, False
        return analysis, True

    def finalize(
        self,
        prepared: dict[str, Any],
        analysis: ComprehensiveLLMAnalysis,
        *,
        llm_used: bool,
    ) -> ComprehensiveAnalysisResult:
        task: ComprehensiveAnalysisTask = prepared["task"]
        paths = artifact_paths(self.data_dir, task.stock_code, task.task_id)
        result = ComprehensiveAnalysisResult(
            agent_version=AGENT_VERSION,
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
            status=prepared["status"],
            llm_used=llm_used,
            stock_code=task.stock_code,
            stock_name=prepared["stock_name"],
            industry_name=prepared["industry_name"],
            question=task.question,
            agent_statuses=prepared["agent_statuses"],
            agent_summaries=prepared["summaries"],
            requirement_coverage=prepared["coverage"],
            summary=analysis.summary,
            key_strengths=analysis.key_strengths,
            key_risks=analysis.key_risks,
            trend_assessments=analysis.trend_assessments,
            other_findings=analysis.other_findings,
            conflicts=prepared["conflicts"],
            findings=prepared["findings"],
            evidence=prepared["evidence"],
            missing_data=prepared["missing_data"],
            limitations=list(dict.fromkeys([*prepared["limitations"], *analysis.limitations])),
            confidence=prepared["confidence"],
            generated_at=datetime.now(CHINA_TZ).isoformat(),
            artifacts=AnalysisArtifacts(**{key: str(value) for key, value in paths.items()}),
        )
        markdown = render_markdown(result, source_labels=self.agent_types.labels())
        write_analysis_artifacts(result, markdown, paths)
        return result

    @staticmethod
    def _synthesis_packet(prepared: dict[str, Any]) -> dict[str, Any]:
        task: ComprehensiveAnalysisTask = prepared["task"]
        return {
            "task_id": task.task_id,
            "stock_code": task.stock_code,
            "question": task.question,
            "requested_topics": [item.topic for item in task.requirements],
            "requirements": [item.model_dump(mode="json") for item in task.requirements],
            "agent_statuses": prepared["agent_statuses"],
            "agent_summaries": prepared["summaries"],
            "requirement_coverage": [item.model_dump(mode="json") for item in prepared["coverage"]],
            "findings": [item.model_dump(mode="json") for item in prepared["findings"]],
            "evidence": [item.model_dump(mode="json") for item in prepared["evidence"]],
            "conflicts": [item.model_dump(mode="json") for item in prepared["conflicts"]],
            "missing_data": prepared["missing_data"],
            "limitations": prepared["limitations"],
        }
