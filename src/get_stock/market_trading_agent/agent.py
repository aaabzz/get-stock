from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from get_stock.agent_config import MARKET_TRADING_STATE_KEYS
from get_stock.market_trading_agent.catalog import (
    FRESHNESS_DAYS,
    MIN_RECORDS,
    TOPIC_DATASETS,
    TOPIC_LABELS,
)
from get_stock.market_trading_agent.loaders import (
    MarketTradingDataAccessError,
    StructuredMarketTradingDataLoader,
)
from get_stock.market_trading_agent.metrics import ANALYZERS, MarketAnalysisContext
from get_stock.market_trading_agent.reasoner import (
    MarketTradingReasoner,
    deterministic_reasoner,
)
from get_stock.market_trading_agent.schemas import (
    MarketTradingAnalysisResult,
    MarketTradingAnalysisTask,
    MarketTradingLLMAnalysis,
    MissingMarketData,
)
from get_stock.market_trading_agent.verifier import verify_market_trading_analysis

AGENT_VERSION = "1.0"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
BASE_LIMITATIONS = (
    "仅使用本地结构化市场与交易数据，不访问新闻、公告或PDF",
    "历史关系不代表因果关系，也不构成未来价格预测",
    "不提供目标价或投资建议",
)


class MarketTradingAnalysisError(RuntimeError):
    pass


class MarketTradingAnalysisAgent:
    def __init__(self, data_dir: Path, *, reasoner: MarketTradingReasoner | None = None) -> None:
        self.data_dir = data_dir.resolve()
        self.reasoner = reasoner

    def analyze(
        self, task: MarketTradingAnalysisTask | dict[str, Any]
    ) -> MarketTradingAnalysisResult:
        prepared = self.prepare(task)
        llm_analysis, llm_used = self.reason(prepared)
        return self.finalize(prepared, llm_analysis, llm_used=llm_used)

    def prepare(self, task: MarketTradingAnalysisTask | dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = (
                task
                if isinstance(task, MarketTradingAnalysisTask)
                else MarketTradingAnalysisTask.model_validate(task)
            )
            normalized.constraints.assert_supported()
            loader = StructuredMarketTradingDataLoader(self.data_dir, normalized.stock_code)
            bundle = loader.load_many(set(normalized.dataset_names))
            states = loader.load_states()
        except (ValidationError, ValueError, MarketTradingDataAccessError) as exc:
            raise MarketTradingAnalysisError(str(exc)) from exc

        as_of_date = normalized.as_of_date or date.today()
        successful_empty = self._successful_empty_datasets(states, bundle)
        context = MarketAnalysisContext(
            lookback_sessions=normalized.lookback_sessions,
            as_of_date=as_of_date,
            period_from=normalized.period_from,
            period_to=normalized.period_to,
            successful_empty_datasets=successful_empty,
        )
        freshness = self._assess_freshness(bundle, as_of_date)
        missing_data = self._check_data_sufficiency(
            normalized,
            bundle,
            states,
            freshness,
            successful_empty,
        )
        dimensions: dict[str, dict[str, Any]] = {}
        unavailable_topics: list[str] = []
        for topic in normalized.topics:
            dimension = ANALYZERS[topic](bundle, context)
            if dimension is None or not dimension["findings"]:
                unavailable_topics.append(topic)
            else:
                dimensions[topic] = dimension
        for topic in unavailable_topics:
            missing_data.append(
                MissingMarketData(
                    topic=topic,
                    dataset=None,
                    reason_code="required_field_missing",
                    reason=f"现有字段不足以完成{TOPIC_LABELS[topic]}分析",
                    blocking=True,
                    recommended_action=self._topic_action(topic),
                )
            )
        missing_data = self._deduplicate_missing_data(missing_data)
        completed_count = len(dimensions)
        requested_count = len(normalized.topics)
        status = (
            "insufficient_data"
            if completed_count == 0
            else (
                "completed"
                if completed_count == requested_count and not missing_data
                else "partial"
            )
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
        coverage = min(1.0, self._record_coverage(bundle, normalized))
        confidence = (
            0.0
            if requested_count == 0
            else round(0.9 * completed_count / requested_count * coverage, 2)
        )
        return {
            "task": normalized,
            "as_of_date": as_of_date,
            "profile": profile,
            "status": status,
            "periods": periods,
            "dimensions": dimensions,
            "evidence": context.evidence,
            "missing_data": missing_data,
            "data_freshness": freshness,
            "accessed_datasets": sorted(
                dataset for dataset, value in bundle.items() if value or dataset in successful_empty
            ),
            "deterministic_summary": self._build_summary(dimensions, unavailable_topics),
            "limitations": list(BASE_LIMITATIONS),
            "base_confidence": confidence,
        }

    def reason(self, prepared: dict[str, Any]) -> tuple[MarketTradingLLMAnalysis, bool]:
        task: MarketTradingAnalysisTask = prepared["task"]
        fact_packet = self._fact_packet(prepared)
        if prepared["status"] == "insufficient_data":
            return deterministic_reasoner(fact_packet), False
        if self.reasoner is None:
            if task.constraints.require_llm:
                raise MarketTradingAnalysisError(
                    "task requires an LLM but no reasoner was injected"
                )
            return deterministic_reasoner(fact_packet), False
        try:
            analysis = self.reasoner(fact_packet)
            analysis = (
                analysis
                if isinstance(analysis, MarketTradingLLMAnalysis)
                else MarketTradingLLMAnalysis.model_validate(analysis)
            )
            verify_market_trading_analysis(analysis, prepared["evidence"], task)
        except Exception as exc:  # retain deterministic evidence when the LLM output is invalid
            fallback = deterministic_reasoner(fact_packet)
            fallback.limitations.append(
                "市场交易 LLM 输出未通过校验，已降级为确定性分析：" + str(exc)
            )
            return fallback, False
        return analysis, True

    def finalize(
        self,
        prepared: dict[str, Any],
        analysis: MarketTradingLLMAnalysis,
        *,
        llm_used: bool,
    ) -> MarketTradingAnalysisResult:
        task: MarketTradingAnalysisTask = prepared["task"]
        profile: dict[str, Any] = prepared["profile"]
        periods: list[str] = prepared["periods"]
        return MarketTradingAnalysisResult(
            agent_version=AGENT_VERSION,
            task_id=task.task_id,
            status=prepared["status"],
            llm_used=llm_used,
            stock_code=task.stock_code,
            stock_name=profile.get("stock_name"),
            industry_name=profile.get("industry_name"),
            analysis_scope={
                "topics": list(task.topics),
                "lookback_sessions": task.lookback_sessions,
                "as_of_date": prepared["as_of_date"].isoformat(),
                "from": periods[0]
                if periods
                else (task.period_from.isoformat() if task.period_from else None),
                "to": periods[-1]
                if periods
                else (task.period_to.isoformat() if task.period_to else None),
            },
            data_freshness=prepared["data_freshness"],
            accessed_datasets=prepared["accessed_datasets"],
            summary=analysis.market_state_summary,
            dimensions=prepared["dimensions"],
            notable_activity=analysis.notable_activity,
            risk_signals=analysis.risk_signals,
            trend_assessments=analysis.trend_assessments,
            evidence=prepared["evidence"],
            missing_data=prepared["missing_data"],
            limitations=list(dict.fromkeys([*prepared["limitations"], *analysis.limitations])),
            confidence=prepared["base_confidence"],
            generated_at=datetime.now(CHINA_TZ).isoformat(),
        )

    @staticmethod
    def _fact_packet(prepared: dict[str, Any]) -> dict[str, Any]:
        task: MarketTradingAnalysisTask = prepared["task"]
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
                "lookback_sessions": task.lookback_sessions,
                "as_of_date": prepared["as_of_date"].isoformat(),
            },
            "allowed_topics": sorted(TOPIC_DATASETS),
            "requested_topics": list(task.topics),
            "status": prepared["status"],
            "data_freshness": prepared["data_freshness"],
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
        successful: set[str] = set()
        for dataset, (state_name, state_key) in MARKET_TRADING_STATE_KEYS.items():
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
        binding = MARKET_TRADING_STATE_KEYS.get(dataset)
        if not binding:
            return None
        state_name, state_key = binding
        failure = states.get(state_name, {}).get("failed_datasets", {}).get(state_key)
        return str(failure) if failure else None

    @staticmethod
    def _latest_date(dataset: str, value: Any) -> str | None:
        if dataset == "market_snapshot" and isinstance(value, dict):
            raw = str(value.get("quote_time") or "")
            return raw[:10] if len(raw) >= 10 else None
        if isinstance(value, list):
            dates = [str(item.get("trade_date")) for item in value if item.get("trade_date")]
            return max(dates) if dates else None
        return None

    @classmethod
    def _assess_freshness(
        cls, bundle: dict[str, Any], as_of_date: date
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for dataset, threshold in FRESHNESS_DAYS.items():
            latest = cls._latest_date(dataset, bundle.get(dataset))
            if not latest:
                result[dataset] = {"latest_date": None, "status": "missing"}
                continue
            try:
                age_days = (as_of_date - date.fromisoformat(latest)).days
            except ValueError:
                result[dataset] = {"latest_date": latest, "status": "unknown"}
                continue
            result[dataset] = {
                "latest_date": latest,
                "as_of_date": as_of_date.isoformat(),
                "age_days": age_days,
                "status": "fresh" if age_days <= threshold else "stale",
            }
        return result

    def _check_data_sufficiency(
        self,
        task: MarketTradingAnalysisTask,
        bundle: dict[str, Any],
        states: dict[str, dict[str, Any]],
        freshness: dict[str, dict[str, Any]],
        successful_empty: set[str],
    ) -> list[MissingMarketData]:
        missing: list[MissingMarketData] = []
        for topic in task.topics:
            for dataset in TOPIC_DATASETS[topic]["required"]:
                failure = self._dataset_failure(dataset, states)
                if failure:
                    missing.append(
                        MissingMarketData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="crawl_failed",
                            reason=f"{dataset}最近一次采集失败：{failure}",
                            blocking=True,
                            recommended_action=self._dataset_action(dataset),
                        )
                    )
                    continue
                value = bundle.get(dataset)
                if not value and dataset not in successful_empty:
                    missing.append(
                        MissingMarketData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="dataset_missing",
                            reason=f"Supervisor未提供或本地缺少{dataset}",
                            blocking=True,
                            recommended_action=self._dataset_action(dataset),
                        )
                    )
                    continue
                minimum = MIN_RECORDS.get(dataset)
                if minimum and isinstance(value, list) and len(value) < minimum:
                    missing.append(
                        MissingMarketData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="insufficient_periods",
                            reason=f"{dataset}至少需要{minimum}条，当前只有{len(value)}条",
                            blocking=True,
                            recommended_action=self._dataset_action(dataset),
                            expected=minimum,
                            actual=len(value),
                        )
                    )
                if dataset in {"market_history", "margin_trading"} and isinstance(value, list):
                    available = min(len(value), task.lookback_sessions)
                    if available < task.lookback_sessions and available >= (minimum or 1):
                        missing.append(
                            MissingMarketData(
                                topic=topic,
                                dataset=dataset,
                                reason_code="insufficient_periods",
                                reason=(
                                    f"请求{task.lookback_sessions}个交易日，"
                                    f"当前最多有{available}条有效记录"
                                ),
                                blocking=False,
                                recommended_action=self._dataset_action(dataset),
                                expected=task.lookback_sessions,
                                actual=available,
                            )
                        )
                if freshness.get(dataset, {}).get("status") == "stale":
                    missing.append(
                        MissingMarketData(
                            topic=topic,
                            dataset=dataset,
                            reason_code="dataset_stale",
                            reason=f"{dataset}最新数据早于分析日期超过允许范围",
                            blocking=False,
                            recommended_action=self._dataset_action(dataset),
                            expected=freshness[dataset].get("as_of_date"),
                            actual=freshness[dataset].get("latest_date"),
                        )
                    )
            cross_dataset = {
                "margin_activity": "market_history",
                "block_trades": "market_history",
            }.get(topic)
            if (
                cross_dataset
                and bundle.get(TOPIC_DATASETS[topic]["required"][0])
                and not bundle.get(cross_dataset)
            ):
                purpose = "融资余额与价格关系" if topic == "margin_activity" else "大宗交易折溢价率"
                missing.append(
                    MissingMarketData(
                        topic=topic,
                        dataset=cross_dataset,
                        reason_code="cross_dataset_mismatch",
                        reason=f"缺少{cross_dataset}，无法计算{purpose}",
                        blocking=False,
                        recommended_action="crawl_market",
                    )
                )
        return missing

    @staticmethod
    def _record_coverage(bundle: dict[str, Any], task: MarketTradingAnalysisTask) -> float:
        required_series = {
            dataset
            for topic in task.topics
            for dataset in TOPIC_DATASETS[topic]["required"]
            if dataset in {"market_history", "margin_trading"}
        }
        if not required_series:
            return 1.0
        ratios = [
            min(1.0, len(bundle.get(dataset, [])) / task.lookback_sessions)
            for dataset in required_series
        ]
        return sum(ratios) / len(ratios)

    @staticmethod
    def _dataset_action(dataset: str) -> str:
        return "crawl_market" if dataset.startswith("market_") else "crawl_trading"

    @staticmethod
    def _topic_action(topic: str) -> str:
        return "crawl_trading" if topic in {"margin_activity", "block_trades"} else "crawl_market"

    @staticmethod
    def _deduplicate_missing_data(records: list[MissingMarketData]) -> list[MissingMarketData]:
        unique: list[MissingMarketData] = []
        seen: set[tuple[Any, ...]] = set()
        for record in records:
            key = (record.topic, record.dataset, record.reason_code, record.reason)
            if key not in seen:
                seen.add(key)
                unique.append(record)
        return unique

    @staticmethod
    def _build_summary(dimensions: dict[str, dict[str, Any]], unavailable_topics: list[str]) -> str:
        if not dimensions:
            return "现有结构化市场交易数据不足，无法完成请求的分析。"
        summary = (
            "；".join(
                f"{dimension['label']}：{dimension['state']}" for dimension in dimensions.values()
            )
            + "。"
        )
        if unavailable_topics:
            labels = "、".join(TOPIC_LABELS[topic] for topic in unavailable_topics)
            summary += f" {labels}因数据不足未生成结论。"
        return summary
