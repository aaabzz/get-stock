import json
from pathlib import Path

from typer.testing import CliRunner

from get_stock.acquisition import AcquisitionRequest, AcquisitionResult, DataAcquisitionCoordinator
from get_stock.cli import app
from get_stock.document_acquisition import DocumentRecoveryResult
from get_stock.storage import atomic_write_json_lines
from get_stock.supervisor import (
    DocumentIntent,
    StockAnalysisSupervisor,
    SupervisorPlanDraft,
    SupervisorTask,
    TimeIntent,
    build_supervisor_plan,
    resolve_time_scope,
    understand_supervisor_question,
)
from get_stock.supervisor.report_selector import select_processed_reports


def test_planner_routes_mixed_question_to_allowlisted_agents() -> None:
    plan = build_supervisor_plan(
        SupervisorTask(
            task_id="supervisor-test-plan",
            question="分析000001的ROE、PE和基金持股",
            require_llm=False,
        )
    )

    topics = {item.topic for item in plan.requirements}
    assert {"profitability", "valuation", "fund_holdings"} <= topics
    assert set(plan.expected_agents) == {
        "financial_analysis",
        "market_trading",
        "shareholder_analysis",
    }


def test_question_understanding_is_separate_from_allowlisted_planning() -> None:
    understanding = understand_supervisor_question(
        SupervisorTask(
            task_id="supervisor-understanding",
            question="分析000001最近3年的盈利和估值",
            require_llm=False,
        )
    )

    assert understanding.stock_code == "000001"
    assert understanding.financial_years == 3
    assert set(understanding.topics) == {"profitability", "valuation"}
    assert understanding.interpreter_mode == "deterministic"


def test_date_resolver_separates_report_period_from_disclosure_search() -> None:
    task = SupervisorTask(
        task_id="supervisor-report-dates",
        question="分析000001最近三年的竞争优势",
        as_of_date="2026-09-12",
        require_llm=False,
    )
    understanding = understand_supervisor_question(task)

    resolved = resolve_time_scope(task, understanding)

    assert resolved.report_period_from.isoformat() == "2023-12-31"
    assert resolved.report_period_to.isoformat() == "2025-12-31"
    assert resolved.disclosure_search_from.isoformat() == "2024-01-01"
    assert resolved.disclosure_search_to.isoformat() == "2026-09-12"


def test_acquisition_coordinator_only_plans_required_market_dataset(tmp_path: Path) -> None:
    coordinator = DataAcquisitionCoordinator(tmp_path, runner=lambda _jobs, _data_dir: None)

    jobs = coordinator.plan(AcquisitionRequest(stock_code="000001", datasets=("market_snapshot",)))

    assert len(jobs) == 1
    assert jobs[0].action == "crawl_market"
    assert jobs[0].kwargs["snapshot"] is True
    assert jobs[0].kwargs["history"] is False


def test_supervisor_auto_crawls_blocking_gap_before_specialists(tmp_path: Path) -> None:
    class FakeCoordinator:
        request = None

        def acquire(self, request):
            self.request = request
            return AcquisitionResult(
                status="completed",
                requested_datasets=list(request.datasets),
                verified_datasets=list(request.datasets),
                rounds_used=1,
            )

    coordinator = FakeCoordinator()
    result = StockAnalysisSupervisor(tmp_path, acquisition_coordinator=coordinator).analyze(
        SupervisorTask(
            task_id="supervisor-auto-crawl",
            question="分析000001的PE估值",
            require_llm=False,
            auto_crawl=True,
        )
    )

    assert coordinator.request is not None
    assert coordinator.request.datasets == ("market_snapshot",)
    assert result.acquisition["status"] == "completed"


def test_supervisor_recovers_report_chunks_before_report_agent(tmp_path: Path) -> None:
    class FakeDocumentCoordinator:
        request = None

        def recover(self, request):
            self.request = request
            stock_dir = tmp_path / "stocks" / request.stock_code
            atomic_write_json_lines(
                stock_dir / "cleaned" / "announcements.jsonl",
                [
                    {
                        "announcement_id": "full-2025",
                        "document_role": "full_report",
                        "report_type": "annual",
                        "report_period": "2025-12-31",
                    }
                ],
            )
            atomic_write_json_lines(
                stock_dir / "processed" / "reports" / "full-2025" / "chunks.jsonl",
                [
                    {
                        "announcement_id": "full-2025",
                        "chunk_id": "section-01-chunk-0001",
                        "section_id": "section-01",
                        "section_type": "company_profile",
                        "heading": "第一章 公司简介",
                        "start_page": 1,
                        "end_page": 1,
                        "text": "公司披露其核心竞争力来自综合金融与科技能力。",
                    }
                ],
            )
            return DocumentRecoveryResult(
                status="completed",
                request=request.model_dump(mode="json"),
                ready_announcement_ids=["full-2025"],
            )

    coordinator = FakeDocumentCoordinator()
    result = StockAnalysisSupervisor(
        tmp_path,
        document_coordinator=coordinator,
    ).analyze(
        SupervisorTask(
            task_id="supervisor-auto-documents",
            question="分析000001最近一年的竞争优势",
            as_of_date="2026-09-12",
            require_llm=False,
            auto_documents=True,
            max_documents=1,
        )
    )

    assert coordinator.request is not None
    assert coordinator.request.report_period_from.isoformat() == "2025-12-31"
    assert result.document_acquisition["status"] == "completed"
    report_execution = next(
        item for item in result.executions if item.agent == "financial_report_analysis"
    )
    assert report_execution.status in {"completed", "partial"}
    assert Path(result.artifacts.resolved_dates).is_file()
    assert Path(result.artifacts.document_acquisition).is_file()


def test_planner_uses_schema_constrained_llm_for_composite_question() -> None:
    received = None

    def reasoner(packet):
        nonlocal received
        received = packet
        return SupervisorPlanDraft(
            topics=("profitability", "valuation", "holder_changes"),
            financial_years=3,
            shareholder_periods=4,
            market_sessions=60,
        )

    task = SupervisorTask(
        task_id="supervisor-llm-plan",
        question="综合分析000001最近三年的盈利、估值和股东变化",
        require_llm=True,
    )
    plan = build_supervisor_plan(task, reasoner=reasoner)

    assert received is not None
    assert plan.planner_mode == "deepseek"
    assert plan.planning_llm_used is True
    assert {item.topic for item in plan.requirements} == {
        "profitability",
        "valuation",
        "holder_changes",
    }
    assert set(plan.expected_agents) == {
        "financial_analysis",
        "market_trading",
        "shareholder_analysis",
    }


def test_planner_uses_llm_for_simple_question_when_enabled() -> None:
    received = None

    def reasoner(packet):
        nonlocal received
        received = packet
        return SupervisorPlanDraft(
            topics=("valuation",),
            time_intent=TimeIntent(mode="latest", raw_expression="当前"),
        )

    understanding = understand_supervisor_question(
        SupervisorTask(
            task_id="supervisor-llm-simple",
            question="分析000001当前估值",
            require_llm=True,
        ),
        reasoner=reasoner,
    )

    assert received is not None
    assert understanding.interpreter_mode == "deepseek"
    assert understanding.llm_used is True
    assert understanding.time_intent.mode == "latest"


def test_llm_intents_are_schema_constrained_and_report_topic_requires_full_report() -> None:
    def reasoner(_packet):
        return SupervisorPlanDraft(
            topics=("competitive_advantage",),
            financial_years=2,
            time_intent=TimeIntent(
                mode="recent_years",
                raw_expression="最近五年",
                count=5,
            ),
            document_intent=DocumentIntent(
                needs_full_report=False,
                explicitly_requested=True,
            ),
        )

    understanding = understand_supervisor_question(
        SupervisorTask(
            task_id="supervisor-llm-intents",
            question="分析000001最近五年的竞争优势",
        ),
        reasoner=reasoner,
    )

    assert understanding.financial_years == 5
    assert understanding.time_intent.count == 5
    assert understanding.document_intent.needs_full_report is True


def test_missing_llm_reasoner_is_recorded_as_deterministic_fallback() -> None:
    understanding = understand_supervisor_question(
        SupervisorTask(
            task_id="supervisor-no-reasoner",
            question="分析000001的盈利质量",
            require_llm=True,
        )
    )

    assert understanding.interpreter_mode == "deterministic_fallback"
    assert understanding.llm_used is False
    assert "no planning reasoner" in understanding.warnings[0]


def test_explicit_cli_period_overrides_llm_time_intent() -> None:
    def reasoner(_packet):
        return SupervisorPlanDraft(
            topics=("profitability",),
            time_intent=TimeIntent(mode="recent_years", count=3),
        )

    understanding = understand_supervisor_question(
        SupervisorTask(
            task_id="supervisor-explicit-period",
            question="分析000001盈利",
            period_from="2024-01-01",
            period_to="2025-12-31",
        ),
        reasoner=reasoner,
    )

    assert understanding.time_intent.mode == "absolute_range"
    assert understanding.time_intent.start_date.isoformat() == "2024-01-01"
    assert understanding.time_intent.end_date.isoformat() == "2025-12-31"


def test_planner_falls_back_and_still_recognizes_generic_profitability() -> None:
    def reasoner(_packet):
        raise RuntimeError("model unavailable")

    task = SupervisorTask(
        task_id="supervisor-plan-fallback",
        question="综合分析000001最近三年的盈利、估值和股东变化",
        require_llm=True,
    )
    plan = build_supervisor_plan(task, reasoner=reasoner)

    assert plan.planner_mode == "deterministic_fallback"
    assert plan.planning_llm_used is False
    assert "profitability" in {item.topic for item in plan.requirements}
    assert "financial_analysis" in plan.expected_agents


def test_runtime_topic_rejection_discards_the_entire_llm_draft() -> None:
    def reasoner(_packet):
        return SupervisorPlanDraft(
            topics=("model_invented_topic",),
            financial_years=10,
            time_intent=TimeIntent(mode="recent_years", count=10),
        )

    understanding = understand_supervisor_question(
        SupervisorTask(
            task_id="supervisor-invalid-runtime-topic",
            question="分析000001最近三年的盈利",
        ),
        reasoner=reasoner,
    )

    assert understanding.interpreter_mode == "deterministic_fallback"
    assert understanding.topics == ("profitability",)
    assert understanding.financial_years == 3
    assert understanding.time_intent.count == 3


def test_report_selector_only_authorizes_processed_full_reports(tmp_path: Path) -> None:
    stock_dir = tmp_path / "stocks" / "000001"
    registry = stock_dir / "cleaned" / "announcements.jsonl"
    registry.parent.mkdir(parents=True)
    records = [
        {
            "announcement_id": "full-2025",
            "document_role": "full_report",
            "report_type": "annual",
            "report_period": "2025-12-31",
        },
        {
            "announcement_id": "summary-2025",
            "document_role": "report_summary",
            "report_type": "annual",
            "report_period": "2025-12-31",
        },
        {
            "announcement_id": "full-unprocessed",
            "document_role": "full_report",
            "report_type": "annual",
            "report_period": "2024-12-31",
        },
    ]
    registry.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    chunks = stock_dir / "processed" / "reports" / "full-2025" / "chunks.jsonl"
    chunks.parent.mkdir(parents=True)
    chunks.write_text("{}\n", encoding="utf-8")

    selected = select_processed_reports(tmp_path, "000001", report_type="annual")

    assert [item.announcement_id for item in selected] == ["full-2025"]


def test_supervisor_runs_locally_and_writes_auditable_artifacts(tmp_path: Path) -> None:
    result = StockAnalysisSupervisor(tmp_path).analyze(
        SupervisorTask(
            task_id="supervisor-local-smoke",
            question="分析000001的盈利质量",
            require_llm=False,
        )
    )

    assert result.status == "insufficient_data"
    assert result.expected_agents == ["financial_analysis"]
    assert result.comprehensive_result is not None
    assert Path(result.artifacts.result).is_file()
    assert Path(result.artifacts.state).is_file()
    assert Path(result.artifacts.markdown).is_file()
    assert Path(result.artifacts.understanding).is_file()
    assert Path(result.artifacts.acquisition).is_file()
    plan = json.loads(Path(result.artifacts.plan).read_text(encoding="utf-8"))
    assert plan["requirements"][0]["topic"] == "earnings_quality"


def test_analyze_stock_cli_does_not_require_synthesis_task_file(tmp_path: Path) -> None:
    runner = CliRunner()
    response = runner.invoke(
        app,
        [
            "analyze",
            "stock",
            "分析000001的PE估值",
            "--no-llm",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert response.exit_code == 0, response.output
    payload = json.loads(response.output)
    assert payload["stock_code"] == "000001"
    assert payload["expected_agents"] == ["market_trading"]
    assert Path(payload["artifacts"]["result"]).is_file()
