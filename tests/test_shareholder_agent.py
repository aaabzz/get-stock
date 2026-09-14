import json
from datetime import date
from pathlib import Path

import pytest

from get_stock.agent_config import SHAREHOLDER_DATASET_FILES
from get_stock.financial_agent.schemas import FinancialTaskConstraints
from get_stock.market_trading_agent.schemas import MarketTradingTaskConstraints
from get_stock.shareholder_agent import (
    ShareholderAnalysisAgent,
    ShareholderAnalysisError,
    ShareholderAnalysisTask,
    ShareholderTaskConstraints,
    build_shareholder_graph,
)
from get_stock.shareholder_agent.catalog import TOPIC_DATASETS as SHAREHOLDER_TOPICS
from get_stock.shareholder_agent.intent import parse_shareholder_intent
from get_stock.shareholder_agent.loaders import (
    ShareholderDataAccessError,
    StructuredShareholderDataLoader,
)
from get_stock.shareholder_agent.normalizers import normalize_shareholder_name
from get_stock.shareholder_agent.schemas import ShareholderClaim, ShareholderLLMAnalysis
from get_stock.storage import atomic_write_json, atomic_write_json_lines


def _write_fixture(data_dir: Path, *, empty_events: bool = False) -> None:
    stock_dir = data_dir / "stocks" / "000001"
    cleaned = stock_dir / "cleaned"
    state = stock_dir / "state"
    atomic_write_json(
        cleaned / "company_profile.json",
        {
            "stock_code": "000001",
            "stock_name": "示例公司",
            "industry_name": "示例行业",
        },
    )
    atomic_write_json_lines(
        cleaned / "stock_structure.jsonl",
        [
            {
                "stock_code": "000001",
                "change_date": "2025-06-30",
                "total_shares_10k": 10000,
                "circulating_shares_10k": 8000,
                "restricted_shares_10k": 2000,
            },
            {
                "stock_code": "000001",
                "change_date": "2026-06-30",
                "total_shares_10k": 11000,
                "circulating_shares_10k": 9000,
                "restricted_shares_10k": 2000,
            },
        ],
    )
    atomic_write_json_lines(
        cleaned / "shareholder_counts.jsonl",
        [
            {
                "stock_code": "000001",
                "report_date": "2025-06-30",
                "shareholder_count": 100000,
            },
            {
                "stock_code": "000001",
                "report_date": "2026-06-30",
                "shareholder_count": 90000,
            },
        ],
    )
    atomic_write_json_lines(
        cleaned / "fund_holdings.jsonl",
        [
            {
                "stock_code": "000001",
                "report_date": "2025-06-30",
                "fund_count": 20,
                "total_shares_held": 1000,
            },
            {
                "stock_code": "000001",
                "report_date": "2026-06-30",
                "fund_count": 25,
                "total_shares_held": 1200,
            },
        ],
    )
    for filename in ("top_ten_shareholders.jsonl", "top_ten_float_shareholders.jsonl"):
        atomic_write_json_lines(
            cleaned / filename,
            [
                {
                    "stock_code": "000001",
                    "report_date": "2025-06-30",
                    "rank": 1,
                    "shareholder_name": "股东甲",
                    "shares_held_10k": 3000,
                    "holding_percent": 30,
                },
                {
                    "stock_code": "000001",
                    "report_date": "2025-06-30",
                    "rank": 2,
                    "shareholder_name": "股东乙",
                    "shares_held_10k": 1000,
                    "holding_percent": 10,
                },
                {
                    "stock_code": "000001",
                    "report_date": "2026-06-30",
                    "rank": 1,
                    "shareholder_name": "股东甲",
                    "shares_held_10k": 3200,
                    "holding_percent": 32,
                },
                {
                    "stock_code": "000001",
                    "report_date": "2026-06-30",
                    "rank": 2,
                    "shareholder_name": "股东丙",
                    "shares_held_10k": 900,
                    "holding_percent": 9,
                },
            ],
        )
    unlocks = (
        []
        if empty_events
        else [
            {
                "stock_code": "000001",
                "unlock_date": "2026-12-31",
                "unlocked_shares_10k": 500,
                "unlocked_percent": 4.5,
            }
        ]
    )
    pledges = (
        []
        if empty_events
        else [
            {
                "stock_code": "000001",
                "announcement_date": "2026-08-01",
                "pledgor": "股东甲",
                "pledgee": "示例机构",
                "pledged_shares_10k": 100,
                "total_share_percent": 0.9,
            }
        ]
    )
    atomic_write_json_lines(cleaned / "restricted_unlocks.jsonl", unlocks)
    atomic_write_json_lines(cleaned / "equity_pledges.jsonl", pledges)
    atomic_write_json(
        state / "shareholder_crawl_state.json",
        {
            "stock_code": "000001",
            "completed_datasets": [
                "stock_structure",
                "shareholder_counts",
                "fund_holdings",
                "top_ten",
                "top_ten_float",
                "restricted_unlocks",
                "equity_pledges",
            ],
            "failed_datasets": {},
            "record_counts": {
                "stock_structure": 2,
                "shareholder_counts": 2,
                "fund_holdings": 2,
                "top_ten": 4,
                "top_ten_float": 4,
                "restricted_unlocks": len(unlocks),
                "equity_pledges": len(pledges),
            },
        },
    )


def _task(
    *,
    topics: tuple[str, ...] = (
        "ownership_structure",
        "shareholder_concentration",
        "major_holder_changes",
        "shareholder_count",
        "fund_holdings",
        "restricted_unlocks",
        "equity_pledges",
    ),
    datasets: tuple[str, ...] | None = None,
    require_llm: bool = False,
) -> ShareholderAnalysisTask:
    return ShareholderAnalysisTask(
        task_id="shareholder-task-1",
        stock_code="000001",
        topics=topics,
        as_of_date=date(2026, 9, 10),
        max_periods=2,
        dataset_names=datasets or tuple(SHAREHOLDER_DATASET_FILES),
        constraints=ShareholderTaskConstraints(require_llm=require_llm),
    )


def test_all_specialist_constraints_require_llm_by_default() -> None:
    assert FinancialTaskConstraints().require_llm is True
    assert MarketTradingTaskConstraints().require_llm is True
    assert ShareholderTaskConstraints().require_llm is True


def test_shareholder_loader_rejects_non_whitelisted_dataset(tmp_path) -> None:
    loader = StructuredShareholderDataLoader(tmp_path, "000001")

    with pytest.raises(ShareholderDataAccessError, match="not allowed"):
        loader.load("market_history")


def test_shareholder_intent_is_a_supervisor_adapter() -> None:
    intent = parse_shareholder_intent("分析000001最近2期的股东人数、十大股东和基金持股")

    assert intent.stock_code == "000001"
    assert intent.max_periods == 2
    assert intent.topics == (
        "shareholder_concentration",
        "shareholder_count",
        "fund_holdings",
    )


def test_shareholder_agent_returns_all_dimensions(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_fixture(data_dir)

    result = ShareholderAnalysisAgent(data_dir).analyze(_task())

    assert result.status == "completed"
    assert result.llm_used is False
    assert set(result.dimensions) == set(_task().topics)
    assert result.dimensions["major_holder_changes"]["state"] == "changed"
    assert result.dimensions["restricted_unlocks"]["state"] == "future_events"
    assert result.confidence == 0.9


def test_successful_empty_event_datasets_are_valid_facts(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_fixture(data_dir, empty_events=True)

    result = ShareholderAnalysisAgent(data_dir).analyze(
        _task(
            topics=("restricted_unlocks", "equity_pledges"),
            datasets=("company_profile", "restricted_unlocks", "equity_pledges"),
        )
    )

    assert result.status == "completed"
    assert result.dimensions["restricted_unlocks"]["state"] == "no_events_returned"
    assert result.dimensions["equity_pledges"]["state"] == "no_events_returned"


def test_insufficient_shareholder_data_skips_llm_even_when_required(tmp_path) -> None:
    called = False

    def reasoner(_packet):
        nonlocal called
        called = True
        raise AssertionError("LLM must not run without evidence")

    result = ShareholderAnalysisAgent(tmp_path / "data", reasoner=reasoner).analyze(
        _task(
            topics=("shareholder_count",),
            datasets=("company_profile", "shareholder_counts"),
            require_llm=True,
        )
    )

    assert result.status == "insufficient_data"
    assert result.llm_used is False
    assert called is False
    assert result.missing_data[0].recommended_action == "crawl_shareholders"


def test_default_llm_requirement_rejects_missing_reasoner_when_data_exists(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_fixture(data_dir)
    task = _task(topics=("shareholder_count",))
    task.constraints.require_llm = True

    with pytest.raises(ShareholderAnalysisError, match="requires an LLM"):
        ShareholderAnalysisAgent(data_dir).analyze(task)


def test_shareholder_llm_cross_topic_evidence_uses_deterministic_fallback(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_fixture(data_dir)

    def reasoner(packet):
        concentration_evidence = next(
            item
            for item in packet["evidence"]
            if "shareholder_concentration" in item["allowed_claim_types"]
        )
        return ShareholderLLMAnalysis(
            ownership_summary="无效的跨主题证据引用",
            trend_assessments=[
                ShareholderClaim(
                    claim="股东人数下降",
                    topic="shareholder_count",
                    assessment="neutral",
                    evidence_ids=[concentration_evidence["evidence_id"]],
                    confidence=0.8,
                )
            ],
        )

    result = ShareholderAnalysisAgent(data_dir, reasoner=reasoner).analyze(
        _task(
            topics=("shareholder_concentration", "shareholder_count"),
            require_llm=True,
        )
    )

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.evidence
    assert any("已降级为确定性分析" in item for item in result.limitations)


def test_shareholder_claim_schema_exposes_topic_enum_to_function_calling() -> None:
    schema = ShareholderLLMAnalysis.model_json_schema()

    topic_schema = schema["$defs"]["ShareholderClaim"]["properties"]["topic"]
    assert set(topic_schema["enum"]) == set(SHAREHOLDER_TOPICS)


def test_nonstandard_shareholder_topic_from_llm_uses_deterministic_fallback(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_fixture(data_dir)

    def reasoner(_packet):
        return {
            "ownership_summary": "invalid model output",
            "concentration_assessments": [
                {
                    "claim": "invalid alias",
                    "topic": "concentration",
                    "assessment": "neutral",
                    "evidence_ids": [],
                    "confidence": 0.5,
                }
            ],
        }

    result = ShareholderAnalysisAgent(data_dir, reasoner=reasoner).analyze(
        _task(topics=("major_holder_changes",), require_llm=True)
    )

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.notable_holder_changes
    assert any("concentration" in item for item in result.limitations)


def test_shareholder_graph_runs(tmp_path) -> None:
    pytest.importorskip("langgraph")
    data_dir = tmp_path / "data"
    _write_fixture(data_dir)
    graph = build_shareholder_graph(ShareholderAnalysisAgent(data_dir))

    state = graph.invoke({"task": _task(topics=("shareholder_count",)).model_dump(mode="json")})

    assert state["result"]["agent"] == "shareholder_analysis"


def test_name_normalization_is_conservative() -> None:
    assert normalize_shareholder_name("  股东（甲）  ") == "股东(甲)"


def test_shareholder_result_is_json_serializable(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_fixture(data_dir)
    result = ShareholderAnalysisAgent(data_dir).analyze(
        _task(topics=("shareholder_count", "fund_holdings"))
    )

    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
