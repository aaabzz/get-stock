from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from get_stock.report_agent.schemas import ReportReference
from get_stock.storage import iter_json_lines


def select_processed_reports(
    data_dir: Path,
    stock_code: str,
    *,
    report_type: str | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    limit: int = 3,
) -> tuple[ReportReference, ...]:
    """Select only registry-authorized full reports with a processed chunks file."""
    stock_dir = data_dir.resolve() / "stocks" / stock_code
    registry = stock_dir / "cleaned" / "announcements.jsonl"
    if not registry.is_file():
        return ()
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for record in iter_json_lines(registry):
        if record.get("document_role") != "full_report":
            continue
        announcement_id = str(record.get("announcement_id") or "")
        if not announcement_id:
            continue
        chunks = stock_dir / "processed" / "reports" / announcement_id / "chunks.jsonl"
        if not chunks.is_file() or chunks.stat().st_size == 0:
            continue
        candidate_type = str(record.get("report_type") or "") or None
        if report_type and candidate_type and candidate_type != report_type:
            continue
        period = _parse_date(record.get("report_period"))
        if period_from and period and period < period_from:
            continue
        if period_to and period and period > period_to:
            continue
        sort_period = period.isoformat() if period else str(record.get("published_at") or "")
        candidates.append((sort_period, announcement_id, record))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return tuple(
        ReportReference(
            announcement_id=announcement_id,
            report_period=_parse_date(record.get("report_period")),
            report_type=str(record.get("report_type") or "") or None,
        )
        for _, announcement_id, record in candidates[:limit]
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
