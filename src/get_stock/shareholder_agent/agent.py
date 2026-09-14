from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from get_stock.agent_config import SHAREHOLDER_STATE_KEYS
from get_stock.shareholder_agent.catalog import EVENT_DATASETS, TOPIC_DATASETS, TOPIC_LABELS
from get_stock.shareholder_agent.loaders import (
    ShareholderDataAccessError,
    StructuredShareholderDataLoader,
)
from get_stock.shareholder_agent.metrics import ANALYZERS, ShareholderAnalysisContext
from get_stock.shareholder_agent.reasoner import ShareholderReasoner, deterministic_reasoner
from get_stock.shareholder_agent.schemas import (
    MissingShareholderData,
    ShareholderAnalysisResult,
    ShareholderAnalysisTask,
    ShareholderLLMAnalysis,
)
from get_stock.shareholder_agent.verifier import verify_shareholder_analysis

AGENT_VERSION = "1.0"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
BASE_LIMITATIONS = (
    "仅使用本地结构化股东数据，不访问公告原文、PDF或网络",
    "股东名单变化不代表实际控制关系或一致行动关系",
    "股东人数、基金持股、解禁和质押事件不构成价格预测或投资建议",
    "质押记录按事件分析，不能据此重建实时质押余额",
)


class ShareholderAnalysisError(RuntimeError):
    pass


class ShareholderAnalysisAgent:
    def __init__(self, data_dir: Path, *, reasoner: ShareholderReasoner | None = None) -> None:
        self.data_dir = data_dir.resolve()
        self.reasoner = reasoner

    def analyze(self, task: ShareholderAnalysisTask | dict[str, Any]) -> ShareholderAnalysisResult:
        prepared = self.prepare(task)
        analysis, llm_used = self.reason(prepared)
        return self.finalize(prepared, analysis, llm_used=llm_used)

    def prepare(self, task: ShareholderAnalysisTask | dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = (
                task
                if isinstance(task, ShareholderAnalysisTask)
                else ShareholderAnalysisTask.model_validate(task)
            )
            normalized.constraints.assert_supported()
            loader = StructuredShareholderDataLoader(self.data_dir, normalized.stock_code)
            bundle = loader.load_many(set(normalized.dataset_names))
            states = loader.load_states()
        except (ValidationError, ValueError, ShareholderDataAccessError) as exc:
            raise ShareholderAnalysisError(str(exc)) from exc

        as_of_date = normalized.as_of_date or datetime.now(CHINA_TZ).date()
        successful_empty = self._successful_empty_datasets(states, bundle)
        context = ShareholderAnalysisContext(
            max_periods=normalized.max_periods,
            as_of_date=as_of_date,
            period_from=normalized.period_from,
            period_to=normalized.period_to,
            successful_empty_datasets=successful_empty,
        )
        missing = self._check_data_sufficiency(
            normalized,
            bundle,
            states,
            successful_empty,
        )
        dimensions: dict[str, dict[str, Any]] = {}
        unavailable: list[str] = []
        for topic in normalized.topics:
            dimension = ANALYZERS[topic](bundle, context)
            if dimension is None or not dimension["findings"]:
                unavailable.append(topic)
            else:
                dimensions[topic] = dimension
        for topic in unavailable:
            missing.append(
                MissingShareholderData(
                    topic=topic,
                    dataset=None,
                    reason_code="required_field_missing",
                    reason=f"现有字段不足以完成{TOPIC_LABELS[topic]}分析",
                    blocking=True,
                    recommended_action="crawl_shareholders",
                )
            )
        missing = self._deduplicate_missing_data(missing)
        completed = len(dimensions)
        requested = len(normalized.topics)
        status = (
            "insufficient_data"
            if completed == 0
            else "completed"
            if completed == requested and not missing
            else "partial"
        )
        profile = bundle.get("company_profile")
        profile = profile if isinstance(profile, dict) else {}
        periods = sorted(
            {
                period
                for dimension in dimensions.values()
                for period in dimension.get("periods", [])
                if period
            }
        )
        coverage = self._period_coverage(bundle, normalized)
        return {
            "task": normalized,
            "as_of_date": as_of_date,
            "profile": profile,
            "status": status,
            "periods": periods,
            "dimensions": dimensions,
            "evidence": context.evidence,
            "missing_data": missing,
            "accessed_datasets": sorted(
                name for name, value in bundle.items() if value or name in successful_empty
            ),
            "deterministic_summary": self._build_summary(dimensions, unavailable),
            "limitations": list(BASE_LIMITATIONS),
            "base_confidence": round(
                0.9 * completed / requested * coverage if requested else 0.0,
                2,
            ),
        }

    def reason(self, prepared: dict[str, Any]) -> tuple[ShareholderLLMAnalysis, bool]:
        task: ShareholderAnalysisTask = prepared["task"]
        fact_packet = self._fact_packet(prepared)
        if prepared["status"] == "insufficient_data":
            return deterministic_reasoner(fact_packet), False
        if self.reasoner is None:
            if task.constraints.require_llm:
                raise ShareholderAnalysisError("task requires an LLM but no reasoner was injected")
            return deterministic_reasoner(fact_packet), False
        try:
            analysis = self.reasoner(fact_packet)
            analysis = (
                analysis
                if isinstance(analysis, ShareholderLLMAnalysis)
                else ShareholderLLMAnalysis.model_validate(analysis)
            )
            verify_shareholder_analysis(analysis, prepared["evidence"], task)
        except Exception as exc:  # retain deterministic evidence when the LLM output is invalid
            fallback = deterministic_reasoner(fact_packet)
            fallback.limitations.append(
                "股东分析 LLM 输出未通过校验，已降级为确定性分析：" + str(exc)
            )
            return fallback, False
        return analysis, True

    def finalize(
        self,
        prepared: dict[str, Any],
        analysis: ShareholderLLMAnalysis,
        *,
        llm_used: bool,
    ) -> ShareholderAnalysisResult:
        task: ShareholderAnalysisTask = prepared["task"]
        profile: dict[str, Any] = prepared["profile"]
        periods: list[str] = prepared["periods"]
        return ShareholderAnalysisResult(
            agent_version=AGENT_VERSION,
            task_id=task.task_id,
            status=prepared["status"],
            llm_used=llm_used,
            stock_code=task.stock_code,
            stock_name=profile.get("stock_name"),
            industry_name=profile.get("industry_name"),
            analysis_scope={
                "topics": list(task.topics),
                "max_periods": task.max_periods,
                "as_of_date": prepared["as_of_date"].isoformat(),
                "from": periods[0]
                if periods
                else (task.period_from.isoformat() if task.period_from else None),
                "to": periods[-1]
                if periods
                else (task.period_to.isoformat() if task.period_to else None),
            },
            accessed_datasets=prepared["accessed_datasets"],
            summary=analysis.ownership_summary,
            dimensions=prepared["dimensions"],
            concentration_assessments=analysis.concentration_assessments,
            notable_holder_changes=analysis.notable_holder_changes,
            risk_events=analysis.risk_events,
            trend_assessments=analysis.trend_assessments,
            evidence=prepared["evidence"],
            missing_data=prepared["missing_data"],
            limitations=list(dict.fromkeys([*prepared["limitations"], *analysis.limitations])),
            confidence=prepared["base_confidence"],
            generated_at=datetime.now(CHINA_TZ).isoformat(),
        )

    @staticmethod
    def _fact_packet(prepared: dict[str, Any]) -> dict[str, Any]:
        task: ShareholderAnalysisTask = prepared["task"]
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
                "max_periods": task.max_periods,
                "as_of_date": prepared["as_of_date"].isoformat(),
            },
            "allowed_topics": sorted(TOPIC_DATASETS),
            "requested_topics": list(task.topics),
            "status": prepared["status"],
            "dimensions": prepared["dimensions"],
            "evidence": prepared["evidence"],
            "missing_data": [item.model_dump(mode="json") for item in prepared["missing_data"]],
            "deterministic_summary": prepared["deterministic_summary"],
            "limitations": prepared["limitations"],
        }

    @staticmethod
    def _successful_empty_datasets(
        states: dict[str, dict[str, Any]], bundle: dict[str, Any]
    ) -> set[str]:
        successful = set()
        for dataset in EVENT_DATASETS:
            state_name, state_key = SHAREHOLDER_STATE_KEYS[dataset]
            state = states.get(state_name, {})
            if (
                not bundle.get(dataset)
                and state_key in state.get("completed_datasets", [])
                and state.get("record_counts", {}).get(state_key) == 0
            ):
                successful.add(dataset)
        return successful

    @staticmethod
    def _dataset_failure(dataset: str, states: dict[str, dict[str, Any]]) -> str | None:
        binding = SHAREHOLDER_STATE_KEYS.get(dataset)
        if not binding:
            return None
        state_name, state_key = binding
        failure = states.get(state_name, {}).get("failed_datasets", {}).get(state_key)
        return str(failure) if failure else None

    def _check_data_sufficiency(
        self,
        task: ShareholderAnalysisTask,
        bundle: dict[str, Any],
        states: dict[str, dict[str, Any]],
        successful_empty: set[str],
    ) -> list[MissingShareholderData]:
        missing: list[MissingShareholderData] = []
        for topic in task.topics:
            for dataset in TOPIC_DATASETS[topic]["required"]:
                failure = self._dataset_failure(dataset, states)
                if failure:
                    missing.append(
                        MissingShareholderData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="crawl_failed",
                            reason=f"{dataset}最近一次采集失败：{failure}",
                            blocking=True,
                            recommended_action="crawl_shareholders",
                        )
                    )
                    continue
                value = bundle.get(dataset)
                if not value and dataset not in successful_empty:
                    missing.append(
                        MissingShareholderData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="dataset_missing",
                            reason=f"Supervisor未提供或本地缺少{dataset}",
                            blocking=True,
                            recommended_action="crawl_shareholders",
                        )
                    )
                    continue
                period_count = self._period_count(dataset, value)
                minimum = 2 if topic == "major_holder_changes" else 1
                if period_count < minimum and dataset not in successful_empty:
                    missing.append(
                        MissingShareholderData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="insufficient_periods",
                            reason=f"{dataset}至少需要{minimum}个报告期，当前为{period_count}期",
                            blocking=True,
                            recommended_action="crawl_shareholders",
                            expected=minimum,
                            actual=period_count,
                        )
                    )
                elif (
                    dataset not in EVENT_DATASETS
                    and period_count < task.max_periods
                    and period_count >= minimum
                ):
                    missing.append(
                        MissingShareholderData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="insufficient_periods",
                            reason=f"请求{task.max_periods}期，当前只有{period_count}期",
                            blocking=False,
                            recommended_action="crawl_shareholders",
                            expected=task.max_periods,
                            actual=period_count,
                        )
                    )
        return missing

    @staticmethod
    def _period_count(dataset: str, value: Any) -> int:
        if not isinstance(value, list):
            return 1 if value else 0
        date_field = {
            "stock_structure": "change_date",
            "shareholder_counts": "report_date",
            "fund_holdings": "report_date",
            "top_ten_shareholders": "report_date",
            "top_ten_float_shareholders": "report_date",
            "restricted_unlocks": "unlock_date",
            "equity_pledges": "announcement_date",
        }.get(dataset)
        return len({item.get(date_field) for item in value if date_field and item.get(date_field)})

    @classmethod
    def _period_coverage(cls, bundle: dict[str, Any], task: ShareholderAnalysisTask) -> float:
        datasets = {
            dataset
            for topic in task.topics
            for dataset in TOPIC_DATASETS[topic]["required"]
            if dataset not in EVENT_DATASETS
        }
        if not datasets:
            return 1.0
        ratios = [
            min(1.0, cls._period_count(dataset, bundle.get(dataset)) / task.max_periods)
            for dataset in datasets
        ]
        return sum(ratios) / len(ratios)

    @staticmethod
    def _deduplicate_missing_data(
        records: list[MissingShareholderData],
    ) -> list[MissingShareholderData]:
        result = []
        seen = set()
        for record in records:
            key = (record.topic, record.dataset, record.reason_code, record.reason)
            if key not in seen:
                seen.add(key)
                result.append(record)
        return result

    @staticmethod
    def _build_summary(dimensions: dict[str, dict[str, Any]], unavailable: list[str]) -> str:
        if not dimensions:
            return "现有结构化股东数据不足，无法完成请求的分析。"
        summary = (
            "；".join(f"{item['label']}：{item['state']}" for item in dimensions.values()) + "。"
        )
        if unavailable:
            labels = "、".join(TOPIC_LABELS[topic] for topic in unavailable)
            summary += f" {labels}因数据不足未生成结论。"
        return summary
