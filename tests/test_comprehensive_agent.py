import json
from pathlib import Path

import pytest

from get_stock.comprehensive_agent import (
    ComprehensiveAnalysisAgent,
    ComprehensiveAnalysisError,
    ComprehensiveAnalysisTask,
    ComprehensiveRequirement,
    ComprehensiveTaskConstraints,
    SpecialistResultEnvelope,
    build_comprehensive_graph,
)
from get_stock.comprehensive_agent.schemas import (
    ComprehensiveLLMAnalysis,
    SynthesisClaim,
)


def _financial_result() -> dict:
    return {
        "schema_version": "1.0",
        "agent": "financial_analysis",
        "agent_version": "1.1",
        "task_id": "financial-task-1",
        "status": "completed",
        "data_scope": "structured_data_only",
        "llm_used": False,
        "stock_code": "000001",
        "stock_name": "平安银行",
        "industry_name": "货币金融服务",
        "analysis_scope": {
            "topics": ["earnings_quality"],
            "report_type": "annual",
            "max_periods": 1,
        },
        "accessed_datasets": ["income_statements", "cash_flow_statements"],
        "summary": "经营现金流对利润形成支持。",
        "dimensions": {
            "earnings_quality": {
                "topic": "earnings_quality",
                "findings": [
                    {
                        "message": "经营现金流净额/归母净利润为1.2",
                        "severity": "positive",
                        "evidence_ids": ["e0001"],
                    }
                ],
            }
        },
        "key_strengths": [
            {
                "claim": "经营现金流净额/归母净利润为1.2",
                "assessment": "positive",
                "evidence_ids": ["e0001"],
                "confidence": 0.9,
            }
        ],
        "key_risks": [],
        "trend_assessments": [],
        "evidence": [
            {
                "evidence_id": "e0001",
                "dataset": "calculated",
                "report_period": "2025-12-31",
                "field": "operating_cash_flow_to_net_profit",
                "value": 1.2,
                "unit": "ratio",
            }
        ],
        "missing_data": [],
        "limitations": ["仅覆盖一个报告期"],
        "confidence": 0.9,
        "generated_at": "2026-09-11T10:00:00+08:00",
    }


def _report_result() -> dict:
    return {
        "schema_version": "1.0",
        "agent": "financial_report_analysis",
        "agent_version": "1.0",
        "task_id": "report-task-1",
        "parent_task_id": "supervisor-task-1",
        "mode": "supplement",
        "status": "completed",
        "data_scope": "report_chunks_only",
        "llm_used": False,
        "stock_code": "000001",
        "analysis_scope": {
            "requested_topics": ["technology_advantage"],
            "report_ids": ["report-2025"],
        },
        "accessed_reports": ["report-2025"],
        "scanned_chunk_count": 20,
        "selected_chunk_count": 1,
        "summary": "公司财报披露了数字化平台能力。",
        "claims": [
            {
                "claim": "公司在财报中披露数字化平台为核心能力之一",
                "topic": "technology_advantage",
                "assessment": "positive",
                "evidence_ids": ["re0001"],
                "confidence": 0.8,
            }
        ],
        "evidence": [
            {
                "evidence_id": "re0001",
                "announcement_id": "report-2025",
                "report_period": "2025-12-31",
                "report_type": "annual",
                "chunk_id": "section-02-chunk-0001",
                "section_id": "section-02",
                "section_type": "company_profile",
                "heading": "第一章 公司简介",
                "start_page": 10,
                "end_page": 11,
                "text_excerpt": "公司持续建设数字化平台。",
                "relevance_score": 15.0,
                "matched_keywords": ["数字化"],
                "selection_reasons": ["heading_match", "content_keyword_match"],
                "allowed_claim_types": ["technology_advantage"],
            }
        ],
        "missing_data": [],
        "limitations": ["公司披露未经外部验证"],
        "confidence": 0.8,
        "generated_at": "2026-09-11T10:01:00+08:00",
    }


def _task(*, require_llm=False, include_results=True, task_id="synthesis-task-1"):
    results = (
        (
            SpecialistResultEnvelope(
                agent="financial_analysis",
                result=_financial_result(),
            ),
            SpecialistResultEnvelope(
                agent="financial_report_analysis",
                result=_report_result(),
            ),
        )
        if include_results
        else ()
    )
    return ComprehensiveAnalysisTask(
        task_id=task_id,
        parent_task_id="supervisor-task-1",
        stock_code="000001",
        question="综合分析盈利质量和技术优势",
        requirements=(
            ComprehensiveRequirement(
                requirement_id="req-financial",
                topic="earnings_quality",
                question="盈利质量如何？",
                required_agents=("financial_analysis",),
            ),
            ComprehensiveRequirement(
                requirement_id="req-technology",
                topic="technology_advantage",
                question="技术优势是什么？",
                required_agents=("financial_report_analysis",),
            ),
        ),
        expected_agents=("financial_analysis", "financial_report_analysis"),
        agent_results=results,
        constraints=ComprehensiveTaskConstraints(require_llm=require_llm),
    )


def test_comprehensive_agent_normalizes_evidence_and_writes_all_artifacts(tmp_path):
    data_dir = tmp_path / "data"

    result = ComprehensiveAnalysisAgent(data_dir).analyze(_task())

    assert result.status == "completed"
    assert result.llm_used is False
    assert {item.evidence_id for item in result.evidence} == {
        "financial_analysis:e0001",
        "financial_report_analysis:re0001",
    }
    assert {item.topic for item in result.requirement_coverage} == {
        "earnings_quality",
        "technology_advantage",
    }
    assert all(item.status == "answered" for item in result.requirement_coverage)
    assert Path(result.artifacts.result_json).is_file()
    assert Path(result.artifacts.markdown).is_file()
    assert Path(result.artifacts.state).is_file()

    markdown = Path(result.artifacts.markdown).read_text(encoding="utf-8")
    assert "# 000001 平安银行综合分析报告" in markdown
    assert "## 三、主要优势" in markdown
    assert "financial_analysis:e0001" in markdown
    state = json.loads(Path(result.artifacts.state).read_text(encoding="utf-8"))
    assert state["status"] == "completed"


def test_comprehensive_agent_does_not_treat_unexpected_agents_as_missing(tmp_path):
    task = _task()
    task.expected_agents = (
        "financial_analysis",
        "financial_report_analysis",
        "market_trading",
    )

    result = ComprehensiveAnalysisAgent(tmp_path / "data").analyze(task)

    assert result.status == "completed"
    assert result.agent_statuses["market_trading"] == "not_run"
    assert all("market_trading" not in item.missing_agents for item in result.requirement_coverage)


def test_insufficient_results_skip_llm_and_still_write_markdown(tmp_path):
    called = False

    def reasoner(_packet):
        nonlocal called
        called = True
        raise AssertionError("LLM must not run without specialist findings")

    result = ComprehensiveAnalysisAgent(tmp_path / "data", reasoner=reasoner).analyze(
        _task(require_llm=True, include_results=False, task_id="insufficient-task")
    )

    assert result.status == "insufficient_data"
    assert result.llm_used is False
    assert called is False
    assert Path(result.artifacts.markdown).is_file()
    markdown = Path(result.artifacts.markdown).read_text(encoding="utf-8")
    assert "数据不足" in markdown
    assert "## 九、缺失数据" in markdown


def test_default_llm_requirement_rejects_missing_reasoner_when_findings_exist(tmp_path):
    with pytest.raises(ComprehensiveAnalysisError, match="requires an LLM"):
        ComprehensiveAnalysisAgent(tmp_path / "data").analyze(_task(require_llm=True))


def test_comprehensive_llm_output_is_verified(tmp_path):
    def reasoner(packet):
        financial_finding = next(
            item for item in packet["findings"] if "earnings_quality" in item["topics"]
        )
        return ComprehensiveLLMAnalysis(
            summary="盈利质量有证据支持，技术优势属于公司披露。",
            key_strengths=[
                SynthesisClaim(
                    claim="经营现金流对利润形成支持",
                    topic="earnings_quality",
                    assessment="positive",
                    finding_ids=[financial_finding["finding_id"]],
                    confidence=0.85,
                )
            ],
        )

    result = ComprehensiveAnalysisAgent(tmp_path / "data", reasoner=reasoner).analyze(
        _task(require_llm=True, task_id="llm-task")
    )

    assert result.llm_used is True
    assert result.key_strengths[0].finding_ids == ["financial_analysis:f0001"]


def test_comprehensive_agent_falls_back_when_llm_references_unknown_finding(tmp_path):
    def reasoner(_packet):
        return ComprehensiveLLMAnalysis(
            summary="无效证据引用",
            key_strengths=[
                SynthesisClaim(
                    claim="没有来源的结论",
                    topic="earnings_quality",
                    assessment="positive",
                    finding_ids=["financial_analysis:f9999"],
                    confidence=0.9,
                )
            ],
        )

    result = ComprehensiveAnalysisAgent(tmp_path / "data", reasoner=reasoner).analyze(
        _task(require_llm=True, task_id="invalid-llm-task")
    )

    assert result.status == "completed"
    assert result.llm_used is False
    assert Path(result.artifacts.markdown).is_file()
    assert any("已降级为确定性综合" in item for item in result.limitations)


def test_comprehensive_graph_runs_and_writes_markdown(tmp_path):
    pytest.importorskip("langgraph")
    data_dir = tmp_path / "data"
    graph = build_comprehensive_graph(ComprehensiveAnalysisAgent(data_dir))

    state = graph.invoke({"task": _task(task_id="graph-task").model_dump(mode="json")})

    assert state["result"]["agent"] == "comprehensive_analysis"
    assert Path(state["result"]["artifacts"]["markdown"]).is_file()


def test_comprehensive_result_json_matches_returned_result(tmp_path):
    result = ComprehensiveAnalysisAgent(tmp_path / "data").analyze(_task(task_id="json-match-task"))

    stored = json.loads(Path(result.artifacts.result_json).read_text(encoding="utf-8"))
    assert stored == result.model_dump(mode="json")
