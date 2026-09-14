import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_ENABLED = os.environ.get("RUN_LIVE_CNINFO") == "1"


def run_cli(arguments: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_announcement_crawl_writes_jsonl_and_pdf(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "announcements",
            "000001",
            "--start",
            "2026-08-22",
            "--end",
            "2026-08-22",
            "--max-pages",
            "1",
            "--download-pdf",
            "--save-raw",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    stock_dir = tmp_path / "stocks" / "000001"
    cleaned_dir = stock_dir / "cleaned"
    pretty_dir = stock_dir / "pretty"
    security = json.loads((cleaned_dir / "security.json").read_text(encoding="utf-8"))
    announcements = (cleaned_dir / "announcements.jsonl").read_text(encoding="utf-8").splitlines()
    readable_announcements = json.loads(
        (pretty_dir / "announcements.json").read_text(encoding="utf-8")
    )
    state = json.loads((stock_dir / "state" / "crawl_state.json").read_text(encoding="utf-8"))
    pdf_files = list((stock_dir / "documents").rglob("*.pdf"))

    assert security["stock_name"] == "平安银行"
    assert announcements
    assert len(readable_announcements) == len(announcements)
    assert state["written"] > 0
    assert pdf_files
    assert pdf_files[0].read_bytes().startswith(b"%PDF-")


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_report_only_crawl_filters_regular_announcements(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "announcements",
            "000001",
            "--start",
            "2026-08-15",
            "--end",
            "2026-08-15",
            "--max-pages",
            "1",
            "--reports",
            "--no-regular-announcements",
            "--report-scope",
            "full",
            "--download-pdf",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    stock_dir = tmp_path / "stocks" / "000001"
    announcements = [
        json.loads(line)
        for line in (stock_dir / "cleaned" / "announcements.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    state = json.loads((stock_dir / "state" / "crawl_state.json").read_text(encoding="utf-8"))

    assert announcements
    assert all(item["document_type"] == "financial_report" for item in announcements)
    assert all(item["document_role"] == "full_report" for item in announcements)
    assert all(item["content_validation_status"] == "passed" for item in announcements)
    assert all(item["analysis_eligible"] is True for item in announcements)
    assert {item["report_type"] for item in announcements} == {"semiannual"}
    assert state["reports_enabled"] is True
    assert state["report_scope"] == "full"
    assert state["regular_announcements_enabled"] is False
    assert state["filtered_regular_announcements"] > 0


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
@pytest.mark.parametrize(
    ("stock_code", "start_date", "end_date"),
    [
        ("600519", "2026-04-17", "2026-04-17"),
        ("600519", "2026-08-15", "2026-08-15"),
        ("300750", "2026-07-20", "2026-07-31"),
    ],
)
def test_live_report_suffix_classification_across_markets(
    tmp_path, stock_code, start_date, end_date
) -> None:
    result = run_cli(
        [
            "crawl",
            "announcements",
            stock_code,
            "--start",
            start_date,
            "--end",
            end_date,
            "--max-pages",
            "1",
            "--reports",
            "--no-regular-announcements",
            "--report-scope",
            "full",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    announcements = [
        json.loads(line)
        for line in (tmp_path / "stocks" / stock_code / "cleaned" / "announcements.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert announcements
    assert all(item["document_role"] == "full_report" for item in announcements)
    assert all(item["is_full_report"] is True for item in announcements)


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_company_crawl_writes_three_datasets(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "company",
            "000001",
            "--save-raw",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    stock_dir = tmp_path / "stocks" / "000001"
    cleaned_dir = stock_dir / "cleaned"
    pretty_dir = stock_dir / "pretty"
    profile = json.loads((cleaned_dir / "company_profile.json").read_text(encoding="utf-8"))
    executives = (cleaned_dir / "executives.jsonl").read_text(encoding="utf-8").splitlines()
    dividends = (cleaned_dir / "dividends.jsonl").read_text(encoding="utf-8").splitlines()
    readable_executives = json.loads((pretty_dir / "executives.json").read_text(encoding="utf-8"))
    readable_dividends = json.loads((pretty_dir / "dividends.json").read_text(encoding="utf-8"))
    state = json.loads(
        (stock_dir / "state" / "company_crawl_state.json").read_text(encoding="utf-8")
    )

    assert profile["company_name"] == "平安银行股份有限公司"
    assert executives
    assert dividends
    assert len(readable_executives) == len(executives)
    assert len(readable_dividends) == len(dividends)
    assert state["completed_datasets"] == ["dividends", "executives", "profile"]


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_financial_crawl_writes_summary_and_statements(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "financials",
            "000001",
            "--save-raw",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    stock_dir = tmp_path / "stocks" / "000001"
    cleaned_dir = stock_dir / "cleaned"
    summary = json.loads((cleaned_dir / "financial_summary.json").read_text(encoding="utf-8"))
    indicators = (cleaned_dir / "financial_indicators.jsonl").read_text(encoding="utf-8")
    state = json.loads(
        (stock_dir / "state" / "financial_crawl_state.json").read_text(encoding="utf-8")
    )

    assert summary["stock_code"] == "000001"
    assert summary["total_shares"] > 0
    assert indicators
    assert state["completed_datasets"] == [
        "balance_sheets",
        "cash_flow_statements",
        "income_statements",
        "indicators",
        "summary",
    ]
    assert state["failed_datasets"] == {}


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_shareholder_crawl_writes_seven_datasets(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "shareholders",
            "000001",
            "--save-raw",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    stock_dir = tmp_path / "stocks" / "000001"
    cleaned_dir = stock_dir / "cleaned"
    structure = (cleaned_dir / "stock_structure.jsonl").read_text(encoding="utf-8")
    counts = (cleaned_dir / "shareholder_counts.jsonl").read_text(encoding="utf-8")
    top_ten = (cleaned_dir / "top_ten_shareholders.jsonl").read_text(encoding="utf-8")
    fund_holdings = (cleaned_dir / "fund_holdings.jsonl").read_text(encoding="utf-8")
    state = json.loads(
        (stock_dir / "state" / "shareholder_crawl_state.json").read_text(encoding="utf-8")
    )

    assert structure
    assert counts
    assert top_ten
    assert fund_holdings
    assert state["completed_datasets"] == [
        "equity_pledges",
        "fund_holdings",
        "restricted_unlocks",
        "shareholder_counts",
        "stock_structure",
        "top_ten",
        "top_ten_float",
    ]
    assert state["failed_datasets"] == {}


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_crawl_all_with_company_selection_writes_summary(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "all",
            "000001",
            "--no-announcements",
            "--no-market",
            "--no-financials",
            "--no-shareholders",
            "--no-trading",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(
        (tmp_path / "stocks" / "000001" / "state" / "crawl_all_state.json").read_text(
            encoding="utf-8"
        )
    )

    assert state["status"] == "success"
    assert state["spiders"]["company"]["status"] == "success"
    assert set(state["spiders"]) == {"company"}


@pytest.mark.live
@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set RUN_LIVE_CNINFO=1 to enable the low-frequency CNINFO smoke test",
)
def test_live_trading_crawl_writes_two_datasets(tmp_path) -> None:
    result = run_cli(
        [
            "crawl",
            "trading",
            "000001",
            "--save-raw",
            "--data-dir",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    stock_dir = tmp_path / "stocks" / "000001"
    cleaned_dir = stock_dir / "cleaned"
    margin = (cleaned_dir / "margin_trading.jsonl").read_text(encoding="utf-8")
    block = (cleaned_dir / "block_trades.jsonl").read_text(encoding="utf-8")
    state = json.loads(
        (stock_dir / "state" / "trading_crawl_state.json").read_text(encoding="utf-8")
    )

    assert margin
    assert block
    assert state["completed_datasets"] == ["block_trades", "margin_trading"]
    assert state["failed_datasets"] == {}
