from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from get_stock.agent_config import (
    FINANCIAL_DATASET_FILES,
    MARKET_TRADING_DATASET_FILES,
    SHAREHOLDER_DATASET_FILES,
)
from get_stock.agent_config.topic_maps import (
    FINANCIAL_TOPIC_MAP,
    MARKET_TOPIC_MAP,
    REPORT_TOPIC_MAP,
    SHAREHOLDER_TOPIC_MAP,
)
from get_stock.agent_plugins.registry import AgentTypeRegistry
from get_stock.agent_plugins.spec import AgentTypeSpec
from get_stock.financial_agent import (
    FinancialAnalysisAgent,
    FinancialAnalysisResult,
    FinancialAnalysisTask,
    FinancialTaskConstraints,
)
from get_stock.financial_agent.catalog import TOPIC_DATASETS as FINANCIAL_DATASETS
from get_stock.financial_agent.intent import TOPIC_KEYWORDS as FINANCIAL_KEYWORDS
from get_stock.market_trading_agent import (
    MarketTradingAnalysisAgent,
    MarketTradingAnalysisResult,
    MarketTradingAnalysisTask,
    MarketTradingTaskConstraints,
)
from get_stock.market_trading_agent.catalog import TOPIC_DATASETS as MARKET_DATASETS
from get_stock.market_trading_agent.intent import TOPIC_KEYWORDS as MARKET_KEYWORDS
from get_stock.report_agent import (
    ReportAnalysisAgent,
    ReportAnalysisResult,
    ReportAnalysisTask,
    ReportRequirement,
    ReportTaskConstraints,
)
from get_stock.report_agent.intent import TOPIC_KEYWORDS as REPORT_KEYWORDS
from get_stock.shareholder_agent import (
    ShareholderAnalysisAgent,
    ShareholderAnalysisResult,
    ShareholderAnalysisTask,
    ShareholderTaskConstraints,
)
from get_stock.shareholder_agent.catalog import TOPIC_DATASETS as SHAREHOLDER_DATASETS
from get_stock.shareholder_agent.intent import TOPIC_KEYWORDS as SHAREHOLDER_KEYWORDS


def _datasets_for(topics: tuple[str, ...], catalog: Mapping[str, Mapping]) -> tuple[str, ...]:
    datasets = {"company_profile"}
    for topic in topics:
        datasets.update(catalog[topic]["required"])
        datasets.update(catalog[topic]["optional"])
    return tuple(sorted(datasets))


def _financial_task(task, plan, topics: tuple[str, ...], _context: Mapping[str, Any]):
    return FinancialAnalysisTask(
        task_id=f"{task.task_id}-financial",
        stock_code=plan.stock_code,
        topics=topics,
        report_type=plan.report_type,
        max_periods=plan.financial_years,
        period_from=task.period_from.isoformat() if task.period_from else None,
        period_to=task.period_to.isoformat() if task.period_to else None,
        dataset_names=_datasets_for(topics, FINANCIAL_DATASETS),
        constraints=FinancialTaskConstraints(require_llm=task.require_llm),
    )


def _market_task(task, plan, topics: tuple[str, ...], _context: Mapping[str, Any]):
    return MarketTradingAnalysisTask(
        task_id=f"{task.task_id}-market",
        stock_code=plan.stock_code,
        topics=topics,
        as_of_date=task.as_of_date,
        lookback_sessions=plan.market_sessions,
        period_from=task.period_from,
        period_to=task.period_to,
        dataset_names=_datasets_for(topics, MARKET_DATASETS),
        constraints=MarketTradingTaskConstraints(require_llm=task.require_llm),
    )


def _shareholder_task(task, plan, topics: tuple[str, ...], _context: Mapping[str, Any]):
    return ShareholderAnalysisTask(
        task_id=f"{task.task_id}-shareholders",
        stock_code=plan.stock_code,
        topics=topics,
        as_of_date=task.as_of_date,
        max_periods=plan.shareholder_periods,
        period_from=task.period_from,
        period_to=task.period_to,
        dataset_names=_datasets_for(topics, SHAREHOLDER_DATASETS),
        constraints=ShareholderTaskConstraints(require_llm=task.require_llm),
    )


def _report_task(task, plan, topics: tuple[str, ...], context: Mapping[str, Any]):
    reports = tuple(context.get("reports", ()))
    if not reports:
        return None
    topic_set = set(topics)
    requirements = tuple(
        ReportRequirement(
            requirement_id=requirement.requirement_id,
            topic=next(
                specialist
                for specialist, synthesis in REPORT_TOPIC_MAP.items()
                if synthesis == requirement.topic
            ),
            question=requirement.question,
        )
        for requirement in plan.requirements
        if requirement.topic in topic_set
    )
    return ReportAnalysisTask(
        task_id=f"{task.task_id}-report",
        parent_task_id=task.task_id,
        mode="supplement",
        stock_code=plan.stock_code,
        question=task.question,
        requirements=requirements,
        reports=reports,
        constraints=ReportTaskConstraints(require_llm=task.require_llm),
    )


def _factory(agent_class):
    def build(data_dir: Path, reasoner: Any):
        return agent_class(data_dir, reasoner=reasoner)

    return build


def build_builtin_agent_types() -> AgentTypeRegistry:
    return AgentTypeRegistry(
        (
            AgentTypeSpec(
                name="financial_analysis",
                version="1.1",
                label="财务分析 Agent",
                topic_map=FINANCIAL_TOPIC_MAP,
                task_builder=_financial_task,
                agent_factory=_factory(FinancialAnalysisAgent),
                result_model=FinancialAnalysisResult,
                claim_fields=(
                    ("key_strengths", "strength"),
                    ("key_risks", "risk"),
                    ("trend_assessments", "trend"),
                ),
                intent_keywords=FINANCIAL_KEYWORDS,
                data_catalog=FINANCIAL_DATASETS,
                dataset_files=FINANCIAL_DATASET_FILES,
                topic_strategy="financial_dimensions",
            ),
            AgentTypeSpec(
                name="market_trading",
                version="1.1",
                label="市场交易 Agent",
                topic_map=MARKET_TOPIC_MAP,
                task_builder=_market_task,
                agent_factory=_factory(MarketTradingAnalysisAgent),
                result_model=MarketTradingAnalysisResult,
                claim_fields=(
                    ("notable_activity", "activity"),
                    ("risk_signals", "risk"),
                    ("trend_assessments", "trend"),
                ),
                intent_keywords=MARKET_KEYWORDS,
                data_catalog=MARKET_DATASETS,
                dataset_files=MARKET_TRADING_DATASET_FILES,
            ),
            AgentTypeSpec(
                name="shareholder_analysis",
                version="1.1",
                label="股东分析 Agent",
                topic_map=SHAREHOLDER_TOPIC_MAP,
                task_builder=_shareholder_task,
                agent_factory=_factory(ShareholderAnalysisAgent),
                result_model=ShareholderAnalysisResult,
                claim_fields=(
                    ("concentration_assessments", "claim"),
                    ("notable_holder_changes", "activity"),
                    ("risk_events", "risk"),
                    ("trend_assessments", "trend"),
                ),
                intent_keywords=SHAREHOLDER_KEYWORDS,
                data_catalog=SHAREHOLDER_DATASETS,
                dataset_files=SHAREHOLDER_DATASET_FILES,
            ),
            AgentTypeSpec(
                name="financial_report_analysis",
                version="1.0",
                label="财报定性分析 Agent",
                topic_map=REPORT_TOPIC_MAP,
                task_builder=_report_task,
                agent_factory=_factory(ReportAnalysisAgent),
                result_model=ReportAnalysisResult,
                claim_fields=(("claims", "claim"),),
                intent_keywords=REPORT_KEYWORDS,
                kind="document",
                role="supplement",
                priority=200,
                source_weight=0.75,
            ),
        )
    )
