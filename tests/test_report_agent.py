import json

import pytest

from get_stock.report_agent import (
    ReportAnalysisAgent,
    ReportAnalysisError,
    ReportAnalysisTask,
    ReportReference,
    ReportRequirement,
    ReportRetrievalOptions,
    ReportTaskConstraints,
    build_report_graph,
)
from get_stock.report_agent.intent import parse_report_intent
from get_stock.report_agent.loaders import ReportChunkLoader
from get_stock.report_agent.schemas import ReportClaim, ReportLLMAnalysis
from get_stock.storage import atomic_write_json_lines


def _write_chunks(data_dir, *, report_id="report-2025"):
    path = data_dir / "stocks" / "000001" / "processed" / "reports" / report_id / "chunks.jsonl"
    atomic_write_json_lines(
        path,
        [
            {
                "announcement_id": report_id,
                "chunk_id": "section-01-chunk-0001",
                "section_id": "section-01",
                "section_type": "front_matter",
                "heading": "报告前置内容",
                "start_page": 1,
                "end_page": 2,
                "text": "目录包含核心技术和财务报告。",
            },
            {
                "announcement_id": report_id,
                "chunk_id": "section-02-chunk-0001",
                "section_id": "section-02",
                "section_type": "company_profile",
                "heading": "第一章 公司简介",
                "start_page": 5,
                "end_page": 5,
                "text": "本公司从事银行服务和财富管理业务。",
            },
            {
                "announcement_id": report_id,
                "chunk_id": "section-02-chunk-0002",
                "section_id": "section-02",
                "section_type": "company_profile",
                "heading": "第一章 公司简介",
                "start_page": 6,
                "end_page": 7,
                "text": "公司持续推动科技赋能和数字化平台建设，形成差异化竞争优势。",
            },
            {
                "announcement_id": report_id,
                "chunk_id": "section-02-chunk-0003",
                "section_id": "section-02",
                "section_type": "company_profile",
                "heading": "第一章 公司简介",
                "start_page": 8,
                "end_page": 9,
                "text": "上一章节结尾。\n第二章 会计数据和财务指标\n核心技术收入 100。",
            },
            {
                "announcement_id": report_id,
                "chunk_id": "section-08-chunk-0001",
                "section_id": "section-08",
                "section_type": "financial_report",
                "heading": "第八章 财务报告",
                "start_page": 80,
                "end_page": 81,
                "text": "财务报表中包含核心技术、研发和风险等词语。",
            },
        ],
    )
    return path


def _task(*, topic="technology_advantage", require_llm=False):
    return ReportAnalysisTask(
        task_id="report-task-1",
        parent_task_id="supervisor-task-1",
        mode="supplement",
        stock_code="000001",
        question="分析公司的技术优势",
        requirements=(
            ReportRequirement(
                requirement_id="req-1",
                topic=topic,
                question="财报披露了哪些技术优势？",
            ),
        ),
        reports=(ReportReference(announcement_id="report-2025"),),
        retrieval=ReportRetrievalOptions(top_k=2, adjacent_window=1),
        constraints=ReportTaskConstraints(require_llm=require_llm),
    )


def test_report_claim_topic_is_exposed_as_json_schema_enum():
    schema = ReportLLMAnalysis.model_json_schema()
    topic_schema = schema["$defs"]["ReportClaim"]["properties"]["topic"]

    assert "technology_advantage" in topic_schema["enum"]
    assert "risk_events" not in topic_schema["enum"]


def test_report_loader_only_resolves_allowlisted_chunks_file(tmp_path):
    data_dir = tmp_path / "data"
    path = _write_chunks(data_dir)
    loader = ReportChunkLoader(data_dir, "000001")

    assert loader.path_for(ReportReference(announcement_id="report-2025")) == path.resolve()
    with pytest.raises(ValueError, match="string_pattern_mismatch"):
        ReportReference(announcement_id="../cleaned")


def test_report_agent_uses_heading_gate_and_excludes_financial_text(tmp_path):
    data_dir = tmp_path / "data"
    _write_chunks(data_dir)

    result = ReportAnalysisAgent(data_dir).analyze(_task())

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.scanned_chunk_count == 5
    assert result.selected_chunk_count < result.scanned_chunk_count
    assert result.evidence
    assert all(item.section_type != "financial_report" for item in result.evidence)
    assert all("会计数据和财务指标" not in item.text_excerpt for item in result.evidence)
    assert {claim.topic for claim in result.claims} == {"technology_advantage"}


def test_heading_miss_returns_insufficient_without_calling_llm(tmp_path):
    data_dir = tmp_path / "data"
    _write_chunks(data_dir)
    called = False

    def reasoner(_packet):
        nonlocal called
        called = True
        raise AssertionError("LLM must not run without heading-gated evidence")

    result = ReportAnalysisAgent(data_dir, reasoner=reasoner).analyze(
        _task(topic="research_and_development", require_llm=True)
    )

    assert result.status == "insufficient_data"
    assert result.llm_used is False
    assert called is False
    assert result.missing_data[0].reason_code == "heading_not_found"


def test_report_agent_requires_injected_llm_when_evidence_exists(tmp_path):
    data_dir = tmp_path / "data"
    _write_chunks(data_dir)

    with pytest.raises(ReportAnalysisError, match="requires an LLM"):
        ReportAnalysisAgent(data_dir).analyze(_task(require_llm=True))


def test_report_agent_falls_back_on_cross_topic_llm_claim(tmp_path):
    data_dir = tmp_path / "data"
    _write_chunks(data_dir)

    def reasoner(packet):
        evidence_id = packet["selected_evidence"][0]["evidence_id"]
        return ReportLLMAnalysis(
            summary="错误地扩展到了未请求主题",
            claims=[
                ReportClaim(
                    claim="公司披露了行业地位",
                    topic="industry_position",
                    assessment="neutral",
                    evidence_ids=[evidence_id],
                    confidence=0.7,
                )
            ],
        )

    result = ReportAnalysisAgent(data_dir, reasoner=reasoner).analyze(_task(require_llm=True))

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.evidence
    assert any("已降级为确定性分析" in item for item in result.limitations)


def test_missing_chunks_returns_supervisor_action(tmp_path):
    result = ReportAnalysisAgent(tmp_path / "data").analyze(_task(require_llm=True))

    assert result.status == "insufficient_data"
    assert result.llm_used is False
    assert result.missing_data[0].reason_code == "chunks_missing"
    assert result.missing_data[0].recommended_action == "process_full_report_pdf"


def test_report_intent_is_only_a_supervisor_cli_adapter():
    intent = parse_report_intent("分析000001的行业地位、技术优势和经营风险")

    assert intent.stock_code == "000001"
    assert intent.topics == (
        "industry_position",
        "technology_advantage",
        "business_risks",
    )


def test_report_graph_runs(tmp_path):
    pytest.importorskip("langgraph")
    data_dir = tmp_path / "data"
    _write_chunks(data_dir)
    graph = build_report_graph(ReportAnalysisAgent(data_dir))

    state = graph.invoke({"task": _task().model_dump(mode="json")})

    assert state["result"]["agent"] == "financial_report_analysis"
    assert state["result"]["data_scope"] == "report_chunks_only"


def test_report_result_is_json_serializable(tmp_path):
    data_dir = tmp_path / "data"
    _write_chunks(data_dir)
    result = ReportAnalysisAgent(data_dir).analyze(_task())

    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
