from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from get_stock.document_acquisition.schemas import DocumentRecoveryRequest


class DocumentCrawlerRunner:
    """Run the allowlisted announcement command in a fresh process/reactor."""

    def __call__(self, request: DocumentRecoveryRequest, data_dir: Path) -> None:
        command = [
            sys.executable,
            "-m",
            "get_stock",
            "crawl",
            "announcements",
            request.stock_code,
            "--start",
            request.disclosure_search_from.isoformat(),
            "--end",
            request.disclosure_search_to.isoformat(),
            "--max-pages",
            str(request.max_pages),
            "--max-documents",
            str(request.target_count),
            "--download-pdf",
            "--reports",
            "--no-regular-announcements",
            "--report-scope",
            "full",
            "--no-save-raw",
            "--pretty-json",
            "--data-dir",
            str(data_dir.resolve()),
        ]
        completed = subprocess.run(
            command,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=1800,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(f"document crawl failed with code {completed.returncode}: {detail}")
