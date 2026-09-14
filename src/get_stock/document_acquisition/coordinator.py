from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from get_stock.document_acquisition.runner import DocumentCrawlerRunner
from get_stock.document_acquisition.schemas import (
    DocumentRecoveryRequest,
    DocumentRecoveryResult,
)
from get_stock.documents import process_report
from get_stock.documents.heading_reasoner import HeadingReasoner
from get_stock.storage import iter_json_lines


class DocumentRecoveryCoordinator:
    """Recover allowlisted full-report PDFs and chunks without accepting commands from an LLM."""

    def __init__(
        self,
        data_dir: Path,
        *,
        runner: Callable[[DocumentRecoveryRequest, Path], None] | None = None,
        heading_reasoner: HeadingReasoner | None = None,
        heading_reasoner_id: str | None = None,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.runner = runner or DocumentCrawlerRunner()
        self.heading_reasoner = heading_reasoner
        self.heading_reasoner_id = heading_reasoner_id

    def recover(self, request: DocumentRecoveryRequest) -> DocumentRecoveryResult:
        ready = self._ready(request)
        if len(ready) >= request.target_count:
            return DocumentRecoveryResult(
                status="skipped",
                request=request.model_dump(mode="json"),
                ready_announcement_ids=[item.announcement_id for item in ready],
            )

        processed, warnings = self._process_local(request, ready)
        ready = self._ready(request)
        crawl_attempted = False
        crawl_error = None
        if len(ready) < request.target_count:
            crawl_attempted = True
            crawl_request = request.model_copy(
                update={"target_count": request.target_count - len(ready)}
            )
            try:
                self.runner(crawl_request, self.data_dir)
            except Exception as exc:
                crawl_error = str(exc)
                warnings.append(crawl_error)
            more_processed, more_warnings = self._process_local(request, ready)
            processed.extend(more_processed)
            warnings.extend(more_warnings)
            ready = self._ready(request)

        remaining = max(0, request.target_count - len(ready))
        status = (
            "completed"
            if remaining == 0
            else ("partial" if ready else "failed")
        )
        return DocumentRecoveryResult(
            status=status,
            request=request.model_dump(mode="json"),
            crawl_attempted=crawl_attempted,
            rounds_used=1 if crawl_attempted else 0,
            processed=processed,
            ready_announcement_ids=[item.announcement_id for item in ready],
            remaining_count=remaining,
            warnings=list(dict.fromkeys(warnings)),
            error=(
                crawl_error or "requested full reports remain unavailable"
                if status == "failed"
                else None
            ),
        )

    def _ready(self, request: DocumentRecoveryRequest):
        from get_stock.supervisor.report_selector import select_processed_reports

        return select_processed_reports(
            self.data_dir,
            request.stock_code,
            report_type=request.report_type,
            period_from=request.report_period_from,
            period_to=request.report_period_to,
            limit=request.target_count,
        )

    def _process_local(self, request, ready) -> tuple[list[dict[str, Any]], list[str]]:
        ready_ids = {item.announcement_id for item in ready}
        processed: list[dict[str, Any]] = []
        warnings: list[str] = []
        for record in self._local_candidates(request):
            announcement_id = str(record.get("announcement_id") or "")
            if not announcement_id or announcement_id in ready_ids:
                continue
            try:
                result = process_report(
                    self.data_dir,
                    request.stock_code,
                    announcement_id,
                    heading_mode=request.heading_mode,
                    heading_reasoner=self.heading_reasoner,
                    heading_reasoner_id=self.heading_reasoner_id,
                )
                processed.append(
                    {
                        "announcement_id": announcement_id,
                        "status": result["status"],
                        "cache_hit": result["cache_hit"],
                        "output_dir": result["output_dir"],
                    }
                )
                ready_ids.add(announcement_id)
            except Exception as exc:
                warnings.append(f"failed to process report {announcement_id}: {exc}")
            if len(ready_ids) >= request.target_count:
                break
        return processed, warnings

    def _local_candidates(self, request: DocumentRecoveryRequest) -> list[dict[str, Any]]:
        registry = (
            self.data_dir / "stocks" / request.stock_code / "cleaned" / "announcements.jsonl"
        )
        if not registry.is_file():
            return []
        candidates: list[tuple[date, dict[str, Any]]] = []
        for record in iter_json_lines(registry):
            if record.get("document_role") != "full_report":
                continue
            if record.get("report_type") != request.report_type or not record.get("local_path"):
                continue
            try:
                period = date.fromisoformat(str(record.get("report_period"))[:10])
            except ValueError:
                continue
            if request.report_period_from <= period <= request.report_period_to:
                candidates.append((period, dict(record)))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in candidates]
