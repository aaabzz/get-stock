from __future__ import annotations

from pathlib import Path
from typing import Any

from get_stock.agent_config import REPORT_AGENT_ALLOWED_FILENAME
from get_stock.report_agent.schemas import ReportReference
from get_stock.storage import iter_json_lines


class ReportChunkAccessError(RuntimeError):
    pass


class ReportChunkLoader:
    """Read only the allowlisted chunks artifact for supervisor-authorized reports."""

    def __init__(self, data_dir: Path, stock_code: str) -> None:
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise ReportChunkAccessError("stock_code must contain exactly six digits")
        self.stock_code = stock_code
        self.reports_dir = (
            data_dir.resolve() / "stocks" / stock_code / "processed" / "reports"
        ).resolve()

    def path_for(self, report: ReportReference) -> Path:
        path = (self.reports_dir / report.announcement_id / REPORT_AGENT_ALLOWED_FILENAME).resolve()
        if not path.is_relative_to(self.reports_dir):
            raise ReportChunkAccessError("report path escapes the authorized reports directory")
        if path.name != REPORT_AGENT_ALLOWED_FILENAME:
            raise ReportChunkAccessError("report agent may only read chunks.jsonl")
        return path

    def load(self, report: ReportReference) -> list[dict[str, Any]]:
        path = self.path_for(report)
        if not path.is_file():
            raise ReportChunkAccessError(
                f"chunks file is missing for report {report.announcement_id}"
            )
        try:
            records = list(iter_json_lines(path))
        except ValueError as exc:
            raise ReportChunkAccessError(
                f"invalid chunks JSONL for report {report.announcement_id}"
            ) from exc

        result: list[dict[str, Any]] = []
        required = {
            "chunk_id",
            "section_id",
            "section_type",
            "heading",
            "start_page",
            "end_page",
            "text",
        }
        for index, record in enumerate(records, start=1):
            if not required.issubset(record):
                missing = sorted(required - set(record))
                raise ReportChunkAccessError(
                    f"report {report.announcement_id} chunk {index} misses fields: {missing}"
                )
            record_id = str(record.get("announcement_id") or report.announcement_id)
            if record_id != report.announcement_id:
                raise ReportChunkAccessError(
                    f"report {report.announcement_id} contains a chunk from {record_id}"
                )
            result.append(
                {
                    **record,
                    "announcement_id": report.announcement_id,
                    "report_period": report.report_period.isoformat()
                    if report.report_period
                    else None,
                    "report_type": report.report_type,
                }
            )
        return result
