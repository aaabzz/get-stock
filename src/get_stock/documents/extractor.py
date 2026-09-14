from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader


def extract_pages(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract a PDF page by page while retaining recoverable page-level failures."""
    reader = PdfReader(path, strict=False)
    records: list[dict[str, Any]] = []
    failed_pages: list[int] = []

    for page_number, page in enumerate(reader.pages, start=1):
        error: str | None = None
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # a corrupt page should not discard the whole report
            text = ""
            error = f"{type(exc).__name__}: {exc}"
            failed_pages.append(page_number)
        records.append(
            {
                "page_number": page_number,
                "text": text,
                "character_count": len(text),
                "extraction_status": (
                    "failed" if error else ("empty" if not text.strip() else "passed")
                ),
                "error": error,
            }
        )

    metadata = {
        "page_count": len(reader.pages),
        "is_encrypted": bool(reader.is_encrypted),
        "failed_pages": failed_pages,
        "extraction_method": "pypdf",
    }
    return records, metadata
