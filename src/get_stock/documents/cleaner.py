from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

STANDALONE_PAGE_NUMBER = re.compile(r"^(?:第\s*)?[—–-]?\s*\d+\s*[—–-]?(?:\s*页)?$")


def _clean_line(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\x00", "").replace("\ufeff", "")
    return re.sub(r"[ \t\u3000]+", " ", value).strip()


def _edge_line(lines: list[str], *, first: bool) -> str | None:
    values = lines if first else reversed(lines)
    return next((line for line in values if line), None)


def clean_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize text and remove obvious repeated headers, footers and page numbers."""
    normalized: list[list[str]] = []
    for page in pages:
        normalized.append([_clean_line(line) for line in str(page.get("text") or "").splitlines()])

    threshold = max(3, math.ceil(len(pages) * 0.3))
    edge_counts: Counter[str] = Counter()
    for lines in normalized:
        for candidate in (_edge_line(lines, first=True), _edge_line(lines, first=False)):
            if candidate and len(candidate) <= 100:
                edge_counts[candidate] += 1
    repeated_edges = {line for line, count in edge_counts.items() if count >= threshold}

    cleaned: list[dict[str, Any]] = []
    for source, lines in zip(pages, normalized, strict=True):
        retained = [
            line
            for line in lines
            if line and line not in repeated_edges and not STANDALONE_PAGE_NUMBER.fullmatch(line)
        ]
        text = "\n".join(retained)
        cleaned.append(
            {
                "page_number": int(source["page_number"]),
                "text": text,
                "character_count": len(text),
                "extraction_status": source.get("extraction_status", "passed"),
                "error": source.get("error"),
            }
        )
    return cleaned
