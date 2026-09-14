import inspect
import json
from types import SimpleNamespace

from twisted.internet.defer import Deferred
from typer.testing import CliRunner

import get_stock.cli as cli_module
from get_stock.cli import app

runner = CliRunner()


def test_cli_exposes_crawl_subcommand() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "crawl" in result.stdout
    assert "pdf" in result.stdout
    assert "analyze" in result.stdout


def test_pdf_group_exposes_processing_commands() -> None:
    result = runner.invoke(app, ["pdf", "--help"])

    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "process" in result.stdout
    assert "process-all" in result.stdout


def test_analyze_group_exposes_financial_command() -> None:
    result = runner.invoke(app, ["analyze", "--help"])

    assert result.exit_code == 0
    assert "financial" in result.stdout
    assert "comprehensive" in result.stdout
    assert "market" in result.stdout
    assert "report" in result.stdout
    assert "shareholders" in result.stdout

    command = runner.invoke(
        app,
        ["analyze", "financial", "--help"],
        env={"COLUMNS": "220"},
        terminal_width=220,
    )
    assert command.exit_code == 0
    assert "--llm" in command.stdout
    assert "--no-llm" in command.stdout
    assert "--model" not in command.stdout


def test_financial_cli_prompts_for_deepseek_key_without_persisting_it(monkeypatch) -> None:
    captured = {}

    class FakeResult:
        def model_dump(self, *, mode):
            assert mode == "json"
            return {"status": "completed", "llm_used": True}

    class FakeAgent:
        def __init__(self, _data_dir, *, reasoner):
            assert reasoner == "reasoner"

        def analyze(self, _task):
            return FakeResult()

    def fake_prompt(label, *, hide_input):
        captured["prompt"] = (label, hide_input)
        return "manual-test-key"

    def fake_builder(**kwargs):
        captured["builder"] = kwargs
        return "reasoner"

    monkeypatch.setattr(cli_module.app_settings, "deepseek_api_key", None)
    monkeypatch.setattr(
        cli_module,
        "parse_financial_intent",
        lambda *_args, **_kwargs: SimpleNamespace(
            stock_code="000001",
            topics=("growth",),
            report_type="annual",
            years=3,
        ),
    )
    monkeypatch.setattr(cli_module.typer, "prompt", fake_prompt)
    monkeypatch.setattr(cli_module, "build_deepseek_reasoner", fake_builder)
    monkeypatch.setattr(cli_module, "FinancialAnalysisAgent", FakeAgent)

    result = runner.invoke(app, ["analyze", "financial", "分析000001", "--llm"])

    assert result.exit_code == 0
    assert captured["prompt"] == ("DeepSeek API key", True)
    assert captured["builder"]["api_key"] == "manual-test-key"
    assert "manual-test-key" not in result.stdout


def test_market_cli_prompts_for_deepseek_key_without_persisting_it(monkeypatch) -> None:
    captured = {}

    class FakeResult:
        def model_dump(self, *, mode):
            assert mode == "json"
            return {"status": "completed", "llm_used": True}

    class FakeAgent:
        def __init__(self, _data_dir, *, reasoner):
            assert reasoner == "market-reasoner"

        def analyze(self, _task):
            return FakeResult()

    def fake_prompt(label, *, hide_input):
        captured["prompt"] = (label, hide_input)
        return "manual-market-key"

    def fake_builder(**kwargs):
        captured["builder"] = kwargs
        return "market-reasoner"

    monkeypatch.setattr(cli_module.app_settings, "deepseek_api_key", None)
    monkeypatch.setattr(
        cli_module,
        "parse_market_trading_intent",
        lambda *_args, **_kwargs: SimpleNamespace(
            stock_code="000001",
            topics=("price_trend",),
            lookback_sessions=20,
        ),
    )
    monkeypatch.setattr(cli_module.typer, "prompt", fake_prompt)
    monkeypatch.setattr(cli_module, "build_deepseek_market_reasoner", fake_builder)
    monkeypatch.setattr(cli_module, "MarketTradingAnalysisAgent", FakeAgent)

    result = runner.invoke(app, ["analyze", "market", "分析000001", "--llm"])

    assert result.exit_code == 0
    assert captured["prompt"] == ("DeepSeek API key", True)
    assert captured["builder"]["api_key"] == "manual-market-key"
    assert "manual-market-key" not in result.stdout


def test_all_analysis_cli_commands_enable_llm_by_default() -> None:
    assert inspect.signature(cli_module.analyze_financial_data).parameters["llm"].default is True
    assert (
        inspect.signature(cli_module.analyze_market_trading_data).parameters["llm"].default is True
    )
    assert inspect.signature(cli_module.analyze_shareholder_data).parameters["llm"].default is True
    assert inspect.signature(cli_module.analyze_financial_report).parameters["llm"].default is True
    assert (
        inspect.signature(cli_module.analyze_comprehensive_results).parameters["llm"].default
        is True
    )


def test_report_cli_exposes_supervisor_authorization_and_mode_switches() -> None:
    command = runner.invoke(
        app,
        ["analyze", "report", "--help"],
        env={"COLUMNS": "240"},
        terminal_width=240,
    )

    assert command.exit_code == 0
    assert "--report-id" in command.stdout
    assert "--supplement" in command.stdout
    assert "--direct" in command.stdout
    assert "--no-llm" in command.stdout


def test_comprehensive_cli_requires_a_supervisor_task_file() -> None:
    command = runner.invoke(
        app,
        ["analyze", "comprehensive", "--help"],
        env={"COLUMNS": "220"},
        terminal_width=220,
    )

    assert command.exit_code == 0
    assert "task_file" in command.stdout
    assert "--no-llm" in command.stdout


def test_financial_cli_renders_agent_errors_without_private_click_api(monkeypatch) -> None:
    class FailingAgent:
        def __init__(self, _data_dir, *, reasoner):
            assert reasoner is None

        def analyze(self, _task):
            raise cli_module.FinancialAnalysisError("structured data is unavailable")

    monkeypatch.setattr(
        cli_module,
        "parse_financial_intent",
        lambda *_args, **_kwargs: SimpleNamespace(
            stock_code="000001",
            topics=("growth",),
            report_type="annual",
            years=3,
        ),
    )
    monkeypatch.setattr(cli_module, "FinancialAnalysisAgent", FailingAgent)

    result = runner.invoke(
        app,
        ["analyze", "financial", "analyze 000001", "--no-llm"],
    )

    assert result.exit_code == 1
    assert "Error: structured data is unavailable" in result.output
    assert "AttributeError" not in result.output


def test_shareholder_cli_uses_deepseek_by_default(monkeypatch) -> None:
    captured = {}

    class FakeResult:
        def model_dump(self, *, mode):
            assert mode == "json"
            return {"status": "completed", "llm_used": True}

    class FakeAgent:
        def __init__(self, _data_dir, *, reasoner):
            assert reasoner == "shareholder-reasoner"

        def analyze(self, _task):
            return FakeResult()

    def fake_prompt(label, *, hide_input):
        captured["prompt"] = (label, hide_input)
        return "manual-shareholder-key"

    def fake_builder(**kwargs):
        captured["builder"] = kwargs
        return "shareholder-reasoner"

    monkeypatch.setattr(cli_module.app_settings, "deepseek_api_key", None)
    monkeypatch.setattr(
        cli_module,
        "parse_shareholder_intent",
        lambda *_args, **_kwargs: SimpleNamespace(
            stock_code="000001",
            topics=("shareholder_count",),
            max_periods=2,
        ),
    )
    monkeypatch.setattr(cli_module.typer, "prompt", fake_prompt)
    monkeypatch.setattr(cli_module, "build_deepseek_shareholder_reasoner", fake_builder)
    monkeypatch.setattr(cli_module, "ShareholderAnalysisAgent", FakeAgent)

    result = runner.invoke(app, ["analyze", "shareholders", "分析000001股东人数"])

    assert result.exit_code == 0
    assert captured["prompt"] == ("DeepSeek API key", True)
    assert captured["builder"]["api_key"] == "manual-shareholder-key"
    assert "manual-shareholder-key" not in result.stdout


def test_crawl_group_exposes_domain_commands() -> None:
    result = runner.invoke(app, ["crawl", "--help"])

    assert result.exit_code == 0
    assert "announcements" in result.stdout
    assert "company" in result.stdout
    assert "market" in result.stdout
    assert "financials" in result.stdout
    assert "shareholders" in result.stdout
    assert "trading" in result.stdout
    assert "all" in result.stdout


def test_both_crawl_commands_expose_pretty_json_switch() -> None:
    for command in (
        "announcements",
        "company",
        "market",
        "financials",
        "shareholders",
        "trading",
    ):
        result = runner.invoke(
            app,
            ["crawl", command, "--help"],
            env={"COLUMNS": "220"},
            terminal_width=220,
        )

        assert result.exit_code == 0
        assert "--pretty-json" in result.stdout
        assert "--no-pretty-json" in result.stdout


def test_announcement_commands_expose_document_type_switches() -> None:
    for command in ("announcements", "all"):
        result = runner.invoke(
            app,
            ["crawl", command, "--help"],
            env={"COLUMNS": "220"},
            terminal_width=220,
        )

        assert result.exit_code == 0
        assert "--reports" in result.stdout
        assert "--no-reports" in result.stdout
        assert "--regular-announcements" in result.stdout
        assert "--no-regular-announcements" in result.stdout
        assert "--report-scope" in result.stdout


def test_announcement_command_rejects_disabling_both_document_types() -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "announcements",
            "000001",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-31",
            "--no-reports",
            "--no-regular-announcements",
        ],
        env={"COLUMNS": "220"},
        terminal_width=220,
    )

    assert result.exit_code != 0
    assert "cannot both be disabled" in result.output


def test_announcement_command_rejects_invalid_report_scope() -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "announcements",
            "000001",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-31",
            "--report-scope",
            "unknown",
        ],
        env={"COLUMNS": "220"},
        terminal_width=220,
    )

    assert result.exit_code != 0
    assert "--report-scope must be one of" in result.output


def test_crawl_all_requires_dates_when_announcements_are_enabled() -> None:
    result = runner.invoke(app, ["crawl", "all", "000001"])

    assert result.exit_code != 0
    assert "--start and --end are required" in result.output


def test_crawl_all_registers_selected_spiders_and_writes_summary(monkeypatch, tmp_path) -> None:
    captured_jobs = []

    def fake_run_spiders(jobs, data_dir):
        captured_jobs.extend(jobs)
        stock_dir = data_dir.resolve() / "stocks" / "000001"
        state_dir = stock_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        for job in jobs:
            state = {
                "completed_datasets": list(job.expected_datasets),
                "failed_datasets": {},
            }
            (state_dir / job.state_filename).write_text(
                json.dumps(state),
                encoding="utf-8",
            )
        return data_dir.resolve()

    monkeypatch.setattr(cli_module, "_run_spiders", fake_run_spiders)
    result = runner.invoke(
        app,
        [
            "crawl",
            "all",
            "000001",
            "--no-announcements",
            "--no-market",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert [job.name for job in captured_jobs] == [
        "company",
        "financials",
        "shareholders",
        "trading",
    ]
    summary = json.loads(
        (tmp_path / "stocks" / "000001" / "state" / "crawl_all_state.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["status"] == "success"
    assert set(summary["spiders"]) == {
        "company",
        "financials",
        "shareholders",
        "trading",
    }


def test_crawl_all_rejects_disabling_every_spider(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "all",
            "000001",
            "--no-announcements",
            "--no-company",
            "--no-market",
            "--no-financials",
            "--no-shareholders",
            "--no-trading",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "at least one spider must be enabled" in result.output


def test_all_state_marks_incomplete_dataset_as_partial_success(tmp_path) -> None:
    state_path = tmp_path / "financial_crawl_state.json"
    state_path.write_text(
        json.dumps(
            {
                "completed_datasets": ["summary"],
                "failed_datasets": {"indicators": "invalid response"},
            }
        ),
        encoding="utf-8",
    )

    summary = cli_module._summarize_spider_state(
        state_path,
        previous_version=None,
        expected_datasets=("summary", "indicators", "balance_sheets"),
    )

    assert summary["status"] == "partial_success"
    assert summary["missing_datasets"] == ["balance_sheets", "indicators"]


def test_run_spiders_schedules_next_spider_only_after_previous_finishes(
    monkeypatch,
    tmp_path,
) -> None:
    class FirstSpider:
        pass

    class SecondSpider:
        pass

    class FakeProcess:
        def __init__(self, settings):
            self.calls = []
            self.pending = []
            self.calls_before_start = []

        def crawl(self, spider_class, **kwargs):
            self.calls.append(spider_class)
            deferred = Deferred()
            self.pending.append(deferred)
            return deferred

        def start(self):
            self.calls_before_start = self.calls.copy()
            while self.pending:
                self.pending.pop(0).callback(None)

    fake_process = FakeProcess(None)
    monkeypatch.setattr(cli_module, "CrawlerProcess", lambda settings: fake_process)
    jobs = [
        cli_module.SpiderJob("first", FirstSpider, {}, "first.json"),
        cli_module.SpiderJob("second", SecondSpider, {}, "second.json"),
    ]

    cli_module._run_spiders(jobs, tmp_path)

    assert fake_process.calls_before_start == [FirstSpider]
    assert fake_process.calls == [FirstSpider, SecondSpider]
