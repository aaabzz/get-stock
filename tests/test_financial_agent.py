import json
from pathlib import Path

import pytest

from get_stock.financial_agent import (
    FinancialAnalysisAgent,
    FinancialAnalysisError,
    FinancialAnalysisTask,
    FinancialTaskConstraints,
    build_financial_graph,
)
from get_stock.financial_agent.intent import parse_financial_intent
from get_stock.financial_agent.loaders import (
    StructuredDataAccessError,
    StructuredFinancialDataLoader,
)
from get_stock.financial_agent.schemas import (
    FinancialClaim,
    FinancialLLMAnalysis,
)
from get_stock.storage import atomic_write_json, atomic_write_json_lines


def _write_financial_fixture(data_dir: Path, *, financial_company: bool = False) -> None:
    cleaned = data_dir / "stocks" / "000001" / "cleaned"
    atomic_write_json(
        cleaned / "company_profile.json",
        {
            "stock_code": "000001",
            "stock_name": "示例公司",
            "company_name": "示例公司股份有限公司",
            "industry_name": "货币金融服务" if financial_company else "制造业",
        },
    )
    dates = ["2025-12-31", "2024-12-31", "2023-12-31"]
    atomic_write_json_lines(
        cleaned / "financial_indicators.jsonl",
        [
            {
                "stock_code": "000001",
                "report_date": report_date,
                "report_type": "annual",
                "revenue_growth_percent": 12.0 - index,
                "net_profit_growth_percent": 15.0 - index,
                "weighted_roe_percent": 11.0,
                "return_on_total_assets_percent": 6.0,
                "gross_margin_percent": 30.0,
                "net_profit_margin_percent": 12.0,
                "debt_ratio_percent": 55.0,
                "current_ratio": 1.8,
                "quick_ratio": 1.4,
                "receivables_turnover": 5.0,
                "inventory_turnover": 4.0,
                "total_assets_turnover": 0.8,
            }
            for index, report_date in enumerate(dates)
        ],
    )
    atomic_write_json_lines(
        cleaned / "income_statements.jsonl",
        [
            {
                "stock_code": "000001",
                "report_date": report_date,
                "report_type": "annual",
                "items": {
                    "营业收入": 1000.0 - index * 100,
                    "营业利润": 160.0 - index * 10,
                    "归属母公司净利润": 120.0 - index * 10,
                },
            }
            for index, report_date in enumerate(dates)
        ],
    )
    atomic_write_json_lines(
        cleaned / "balance_sheets.jsonl",
        [
            {
                "stock_code": "000001",
                "report_date": report_date,
                "report_type": "annual",
                "items": {"总资产": 2000.0, "总负债": 1100.0, "所有者权益": 900.0},
            }
            for report_date in dates
        ],
    )
    atomic_write_json_lines(
        cleaned / "cash_flow_statements.jsonl",
        [
            {
                "stock_code": "000001",
                "report_date": report_date,
                "report_type": "annual",
                "items": {
                    "经营活动产生的现金流量净额": 150.0 - index * 10,
                    "投资活动产生的现金流量净额": -80.0,
                    "筹资活动产生的现金流量净额": -30.0,
                },
            }
            for index, report_date in enumerate(dates)
        ],
    )


def _task(
    *,
    topics: tuple[str, ...] = ("growth", "profitability", "earnings_quality"),
    datasets: tuple[str, ...] | None = None,
    require_llm: bool = False,
) -> FinancialAnalysisTask:
    return FinancialAnalysisTask(
        task_id="supervisor-task-1",
        stock_code="000001",
        topics=topics,
        report_type="annual",
        max_periods=3,
        dataset_names=datasets
        or (
            "company_profile",
            "financial_indicators",
            "income_statements",
            "balance_sheets",
            "cash_flow_statements",
        ),
        constraints=FinancialTaskConstraints(require_llm=require_llm),
    )


def test_intent_parser_is_available_only_for_supervisor_adapter() -> None:
    intent = parse_financial_intent("分析000001最近三年半年报的盈利质量和现金流")

    assert intent.stock_code == "000001"
    assert intent.topics == ("earnings_quality", "cash_flow")
    assert intent.years == 3
    assert intent.report_type == "semiannual"


def test_loader_rejects_non_whitelisted_dataset(tmp_path) -> None:
    loader = StructuredFinancialDataLoader(tmp_path / "data", "000001")

    with pytest.raises(StructuredDataAccessError, match="not allowed"):
        loader.load("pages")


def test_agent_accepts_supervisor_task_and_returns_specialist_contract(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir)
    pdf = data_dir / "stocks" / "000001" / "documents" / "ignored.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"this is intentionally not a valid PDF")

    result = FinancialAnalysisAgent(data_dir).analyze(_task())
    payload = result.model_dump(mode="json")

    assert payload["agent"] == "financial_analysis"
    assert payload["task_id"] == "supervisor-task-1"
    assert payload["status"] == "completed"
    assert payload["data_scope"] == "structured_data_only"
    assert payload["llm_used"] is False
    assert set(payload["dimensions"]) == {
        "growth",
        "profitability",
        "earnings_quality",
    }
    assert payload["evidence"]
    assert all("page" not in evidence for evidence in payload["evidence"])


def test_agent_does_not_accept_a_raw_user_question(tmp_path) -> None:
    with pytest.raises(FinancialAnalysisError):
        FinancialAnalysisAgent(tmp_path / "data").analyze("分析000001财务情况")


def test_agent_returns_missing_data_without_crawling(tmp_path) -> None:
    data_dir = tmp_path / "data"
    atomic_write_json(
        data_dir / "stocks" / "000001" / "cleaned" / "company_profile.json",
        {"stock_code": "000001", "stock_name": "示例公司"},
    )
    result = FinancialAnalysisAgent(data_dir).analyze(
        _task(
            topics=("earnings_quality",),
            datasets=("company_profile", "income_statements", "cash_flow_statements"),
        )
    )

    assert result.status == "insufficient_data"
    assert {item["dataset"] for item in result.missing_data} >= {
        "income_statements",
        "cash_flow_statements",
    }
    assert result.dimensions == {}


def test_financial_industry_does_not_apply_generic_debt_warning(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir, financial_company=True)
    result = FinancialAnalysisAgent(data_dir).analyze(_task(topics=("balance_sheet", "solvency")))

    assert result.dimensions["balance_sheet"]["rating"] == "industry_context_required"
    assert result.dimensions["solvency"]["rating"] == "industry_context_required"


def test_injected_llm_reasoner_produces_validated_structured_output(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir)

    def fake_reasoner(fact_packet):
        evidence_id = fact_packet["evidence"][0]["evidence_id"]
        return FinancialLLMAnalysis(
            overall_assessment="结构化财务表现总体稳定。",
            key_strengths=[
                FinancialClaim(
                    claim="收入保持增长",
                    assessment="positive",
                    evidence_ids=[evidence_id],
                    confidence=0.9,
                )
            ],
        )

    result = FinancialAnalysisAgent(data_dir, reasoner=fake_reasoner).analyze(
        _task(require_llm=True)
    )

    assert result.llm_used is True
    assert result.summary == "结构化财务表现总体稳定。"
    assert result.key_strengths[0].evidence_ids == ["e0001"]


def test_llm_claim_with_unknown_evidence_uses_deterministic_fallback(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir)

    def bad_reasoner(_fact_packet):
        return FinancialLLMAnalysis(
            overall_assessment="无效输出",
            key_risks=[
                FinancialClaim(
                    claim="没有证据的风险",
                    assessment="risk",
                    evidence_ids=["missing"],
                    confidence=0.9,
                )
            ],
        )

    result = FinancialAnalysisAgent(data_dir, reasoner=bad_reasoner).analyze(_task())

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.evidence
    assert any("已降级为确定性分析" in item for item in result.limitations)


def test_task_can_require_an_llm(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir)

    with pytest.raises(FinancialAnalysisError, match="requires an LLM"):
        FinancialAnalysisAgent(data_dir).analyze(_task(require_llm=True))


def test_task_rejects_pdf_or_network_permissions() -> None:
    with pytest.raises(ValueError, match="cannot access"):
        constraints = FinancialTaskConstraints(allow_pdf=True)
        constraints.assert_supported()


def test_langgraph_subgraph_runs_when_dependency_is_installed(tmp_path) -> None:
    pytest.importorskip("langgraph")
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir)
    graph = build_financial_graph(FinancialAnalysisAgent(data_dir))

    state = graph.invoke({"task": _task().model_dump(mode="json")})

    assert state["result"]["agent"] == "financial_analysis"
    assert state["result"]["status"] == "completed"


def test_result_is_json_serializable(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_financial_fixture(data_dir)

    result = FinancialAnalysisAgent(data_dir).analyze(_task(topics=("cash_flow",)))

    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
