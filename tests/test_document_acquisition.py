from pathlib import Path
from types import SimpleNamespace

import get_stock.document_acquisition.coordinator as coordinator_module
import get_stock.document_acquisition.runner as runner_module
from get_stock.document_acquisition import (
    DocumentRecoveryCoordinator,
    DocumentRecoveryRequest,
)
from get_stock.document_acquisition.runner import DocumentCrawlerRunner
from get_stock.storage import atomic_write_json_lines


def _request() -> DocumentRecoveryRequest:
    return DocumentRecoveryRequest(
        stock_code="000001",
        report_type="annual",
        report_period_from="2025-12-31",
        report_period_to="2025-12-31",
        disclosure_search_from="2026-01-01",
        disclosure_search_to="2026-09-12",
        target_count=1,
    )


def test_document_recovery_crawls_processes_and_then_hits_cache(tmp_path, monkeypatch) -> None:
    crawl_calls = 0

    def runner(request, data_dir):
        nonlocal crawl_calls
        crawl_calls += 1
        stock_dir = data_dir / "stocks" / request.stock_code
        atomic_write_json_lines(
            stock_dir / "cleaned" / "announcements.jsonl",
            [
                {
                    "announcement_id": "full-2025",
                    "document_role": "full_report",
                    "report_type": "annual",
                    "report_period": "2025-12-31",
                    "local_path": str(stock_dir / "documents" / "full-2025.pdf"),
                }
            ],
        )

    def process_report(data_dir, stock_code, announcement_id, **_kwargs):
        output = data_dir / "stocks" / stock_code / "processed" / "reports" / announcement_id
        atomic_write_json_lines(output / "chunks.jsonl", [{}])
        return {
            "announcement_id": announcement_id,
            "status": "success",
            "cache_hit": False,
            "output_dir": str(output),
        }

    monkeypatch.setattr(coordinator_module, "process_report", process_report)
    coordinator = DocumentRecoveryCoordinator(tmp_path, runner=runner)

    first = coordinator.recover(_request())
    second = coordinator.recover(_request())

    assert first.status == "completed"
    assert first.crawl_attempted is True
    assert first.ready_announcement_ids == ["full-2025"]
    assert second.status == "skipped"
    assert crawl_calls == 1


def test_document_runner_builds_fixed_non_shell_command(tmp_path, monkeypatch) -> None:
    captured = None

    def fake_run(command, **kwargs):
        nonlocal captured
        captured = (command, kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    DocumentCrawlerRunner()(_request(), tmp_path)

    command, kwargs = captured
    assert isinstance(command, list)
    assert command[1:5] == ["-m", "get_stock", "crawl", "announcements"]
    assert "--download-pdf" in command
    assert "--no-regular-announcements" in command
    assert kwargs["check"] is False
    assert "shell" not in kwargs
    assert Path(kwargs["cwd"]).resolve() == Path.cwd().resolve()
