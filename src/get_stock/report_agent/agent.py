from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from get_stock.report_agent.catalog import TOPIC_LABELS
from get_stock.report_agent.loaders import ReportChunkAccessError, ReportChunkLoader
from get_stock.report_agent.reasoner import ReportReasoner, deterministic_reasoner
from get_stock.report_agent.retriever import retrieve_report_chunks
from get_stock.report_agent.schemas import (
    MissingReportData,
    ReportAnalysisResult,
    ReportAnalysisTask,
    ReportClaimValidationIssue,
    ReportEvidence,
    ReportLLMAnalysis,
)
from get_stock.report_agent.verifier import isolate_invalid_report_claims

AGENT_VERSION = "1.1"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
BASE_LIMITATIONS = (
    "仅使用上游授权完整财报的 chunks.jsonl，不读取PDF、页面文件或章节文件",
    "排除财务报告、财务报表、审计报告及财务报表附注章节",
    "行业地位、市场份额和竞争优势属于公司财报披露，未经过外部数据独立验证",
    "不重新提取或计算财务指标，不访问网络、爬虫，也不提供投资建议",
)


class ReportAnalysisError(RuntimeError):
    pass


class ReportAnalysisAgent:
    """Standby specialist invoked by a supervisor for report-text supplementation."""

    def __init__(self, data_dir: Path, *, reasoner: ReportReasoner | None = None) -> None:
        self.data_dir = data_dir.resolve()
        self.reasoner = reasoner

    def analyze(self, task: ReportAnalysisTask | dict[str, Any]) -> ReportAnalysisResult:
        prepared = self.prepare(task)
        retrieved = self.retrieve(prepared)
        analysis, llm_used, validation_issues = self.reason(retrieved)
        return self.finalize(
            retrieved,
            analysis,
            llm_used=llm_used,
            validation_issues=validation_issues,
        )

    def prepare(self, task: ReportAnalysisTask | dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = (
                task
                if isinstance(task, ReportAnalysisTask)
                else ReportAnalysisTask.model_validate(task)
            )
            normalized.constraints.assert_supported()
            loader = ReportChunkLoader(self.data_dir, normalized.stock_code)
        except (ValidationError, ValueError, ReportChunkAccessError) as exc:
            raise ReportAnalysisError(str(exc)) from exc

        chunks_by_report: dict[str, list[dict[str, Any]]] = {}
        load_errors: dict[str, str] = {}
        for report in normalized.reports:
            try:
                chunks_by_report[report.announcement_id] = loader.load(report)
            except ReportChunkAccessError as exc:
                load_errors[report.announcement_id] = str(exc)
        return {
            "task": normalized,
            "chunks_by_report": chunks_by_report,
            "load_errors": load_errors,
            "scanned_chunk_count": sum(len(items) for items in chunks_by_report.values()),
        }

    def retrieve(self, prepared: dict[str, Any]) -> dict[str, Any]:
        task: ReportAnalysisTask = prepared["task"]
        retrieval = retrieve_report_chunks(task, prepared["chunks_by_report"])
        evidence: list[dict[str, Any]] = []
        for index, chunk in enumerate(retrieval["selected"], start=1):
            evidence.append(
                ReportEvidence(
                    evidence_id=f"re{index:04d}",
                    announcement_id=str(chunk["announcement_id"]),
                    report_period=chunk.get("report_period"),
                    report_type=chunk.get("report_type"),
                    chunk_id=str(chunk["chunk_id"]),
                    section_id=str(chunk["section_id"]),
                    section_type=str(chunk["section_type"]),
                    heading=str(chunk["heading"]),
                    start_page=int(chunk["start_page"]),
                    end_page=int(chunk["end_page"]),
                    text_excerpt=str(chunk.get("text") or "")[:500],
                    relevance_score=float(chunk.get("_score", 0.0)),
                    matched_keywords=list(chunk.get("_matched_keywords", [])),
                    selection_reasons=list(chunk.get("_selection_reasons", [])),
                    allowed_claim_types=list(chunk.get("_topics", [])),
                    authorization_details=dict(chunk.get("_topic_authorizations", {})),
                ).model_dump(mode="json")
                | {"text": str(chunk.get("text") or "")}
            )

        missing: list[MissingReportData] = []
        for report_id, reason in prepared["load_errors"].items():
            for requirement in task.requirements:
                missing.append(
                    MissingReportData(
                        requirement_id=requirement.requirement_id,
                        topic=requirement.topic,
                        announcement_id=report_id,
                        reason_code="chunks_missing",
                        reason=reason,
                        recommended_action="process_full_report_pdf",
                    )
                )
        available_topics = {
            topic for item in evidence for topic in item.get("allowed_claim_types", [])
        }
        for requirement in task.requirements:
            if requirement.topic in available_topics:
                continue
            if prepared["load_errors"] and not prepared["chunks_by_report"]:
                continue
            if retrieval["heading_hits"][requirement.requirement_id] == 0:
                missing.append(
                    MissingReportData(
                        requirement_id=requirement.requirement_id,
                        topic=requirement.topic,
                        reason_code="heading_not_found",
                        reason=f"授权报告中未命中{TOPIC_LABELS[requirement.topic]}候选章节标题",
                        recommended_action="review_report_heading_rules",
                    )
                )
            else:
                missing.append(
                    MissingReportData(
                        requirement_id=requirement.requirement_id,
                        topic=requirement.topic,
                        reason_code="relevant_content_not_found",
                        reason=f"命中候选章节，但未找到{TOPIC_LABELS[requirement.topic]}相关正文",
                        recommended_action="review_report_retrieval_keywords",
                    )
                )

        completed = len({item.topic for item in task.requirements} & available_topics)
        requested = len({item.topic for item in task.requirements})
        status = (
            "insufficient_data"
            if completed == 0
            else "completed"
            if completed == requested and not missing
            else "partial"
        )
        return {
            **prepared,
            "retrieval": retrieval,
            "evidence": evidence,
            "missing_data": missing,
            "status": status,
            "completed_topic_count": completed,
            "requested_topic_count": requested,
        }

    def reason(
        self, retrieved: dict[str, Any]
    ) -> tuple[ReportLLMAnalysis, bool, list[ReportClaimValidationIssue]]:
        task: ReportAnalysisTask = retrieved["task"]
        packet = self._evidence_packet(retrieved)
        if retrieved["status"] == "insufficient_data":
            return deterministic_reasoner(packet), False, []
        if self.reasoner is None:
            if task.constraints.require_llm:
                raise ReportAnalysisError("task requires an LLM but no reasoner was injected")
            return deterministic_reasoner(packet), False, []
        try:
            analysis = self.reasoner(packet)
            analysis = (
                analysis
                if isinstance(analysis, ReportLLMAnalysis)
                else ReportLLMAnalysis.model_validate(analysis)
            )
            valid_claims, validation_issues = isolate_invalid_report_claims(
                analysis, retrieved["evidence"], task
            )
        except Exception as exc:  # retain retrieved report evidence when the LLM output is invalid
            fallback = deterministic_reasoner(packet)
            fallback.limitations.append(
                "财报分析 LLM 输出未通过校验，已降级为确定性分析：" + str(exc)
            )
            return fallback, False, []
        if validation_issues and not valid_claims:
            fallback = deterministic_reasoner(packet)
            fallback.limitations.append(
                f"财报分析 LLM 的 {len(validation_issues)} 条结论均未通过证据校验，"
                "已降级为确定性分析"
            )
            return fallback, False, validation_issues
        if validation_issues:
            safe_summary = (
                f"财报分析 LLM 有 {len(valid_claims)} 条结论通过证据校验，"
                f"另有 {len(validation_issues)} 条不合规结论已隔离。"
            )
            if valid_claims:
                safe_summary += " " + "；".join(claim.claim for claim in valid_claims)
            analysis = ReportLLMAnalysis(
                summary=safe_summary,
                claims=valid_claims,
                limitations=[
                    *analysis.limitations,
                    f"已隔离 {len(validation_issues)} 条未通过逐条证据校验的 LLM 结论",
                ],
            )
        return analysis, True, validation_issues

    def finalize(
        self,
        retrieved: dict[str, Any],
        analysis: ReportLLMAnalysis,
        *,
        llm_used: bool,
        validation_issues: list[ReportClaimValidationIssue] | None = None,
    ) -> ReportAnalysisResult:
        task: ReportAnalysisTask = retrieved["task"]
        public_evidence = [
            {key: value for key, value in item.items() if key != "text"}
            for item in retrieved["evidence"]
        ]
        requested = max(1, retrieved["requested_topic_count"])
        confidence = round(0.85 * retrieved["completed_topic_count"] / requested, 2)
        return ReportAnalysisResult(
            agent_version=AGENT_VERSION,
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
            mode=task.mode,
            status=retrieved["status"],
            llm_used=llm_used,
            stock_code=task.stock_code,
            analysis_scope={
                "requested_topics": list(dict.fromkeys(item.topic for item in task.requirements)),
                "report_ids": [item.announcement_id for item in task.reports],
                "excluded_section_types": [
                    "financial_indicators",
                    "financial_report",
                    "front_matter",
                    "unclassified",
                ],
                "top_k": task.retrieval.top_k,
                "adjacent_window": task.retrieval.adjacent_window,
                "max_context_characters": task.retrieval.max_context_characters,
            },
            accessed_reports=sorted(retrieved["chunks_by_report"]),
            scanned_chunk_count=retrieved["scanned_chunk_count"],
            selected_chunk_count=len(public_evidence),
            summary=analysis.summary,
            claims=analysis.claims,
            dropped_claim_count=len(validation_issues or []),
            claim_validation_issues=validation_issues or [],
            evidence=[ReportEvidence.model_validate(item) for item in public_evidence],
            missing_data=retrieved["missing_data"],
            limitations=list(dict.fromkeys([*BASE_LIMITATIONS, *analysis.limitations])),
            confidence=confidence,
            generated_at=datetime.now(CHINA_TZ).isoformat(),
        )

    @staticmethod
    def _evidence_packet(retrieved: dict[str, Any]) -> dict[str, Any]:
        task: ReportAnalysisTask = retrieved["task"]
        return {
            "task_id": task.task_id,
            "mode": task.mode,
            "stock_code": task.stock_code,
            "question": task.question,
            "requested_topics": list(dict.fromkeys(item.topic for item in task.requirements)),
            "requirements": [item.model_dump(mode="json") for item in task.requirements],
            "existing_findings": list(task.existing_findings),
            "selected_evidence": retrieved["evidence"],
            "missing_data": [item.model_dump(mode="json") for item in retrieved["missing_data"]],
            "limitations": list(BASE_LIMITATIONS),
        }
