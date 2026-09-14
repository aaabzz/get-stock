from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

SECTION_GROUPS = (
    ("管理层讨论与分析", "经营情况讨论与分析"),
    ("公司治理",),
    ("重要事项",),
    ("股份变动及股东情况", "股份变动和股东情况"),
    ("财务报告", "财务报表"),
)
REPORT_LABELS = {
    "annual": "年度报告",
    "semiannual": "半年度报告",
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def validate_full_report_pdf(
    path: Path,
    *,
    stock_name: str,
    report_type: str,
    report_period: str,
    primary_pages: int = 10,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Validate a full report progressively, expanding from 10 to at most 20 pages."""
    validation_page_limit = max(1, int(max_pages))
    primary_page_limit = min(validation_page_limit, max(1, int(primary_pages)))
    errors: list[str] = []
    try:
        reader = PdfReader(path, strict=False)
        page_count = len(reader.pages)
        if reader.is_encrypted:
            errors.append("encrypted_pdf")
        page_texts: list[str] = []
        compact_text = ""
        compact_cover = ""
        matched_sections: list[str] = []
        validated_pages = 0
        scan_limit = min(page_count, primary_page_limit)
        hard_limit = min(page_count, validation_page_limit)
        expected_year = report_period[:4]
        expected_label = REPORT_LABELS.get(report_type)

        while validated_pages < scan_limit:
            page = reader.pages[validated_pages]
            try:
                page_texts.append(page.extract_text() or "")
            except Exception:
                page_texts.append("")
            validated_pages += 1

            compact_text = _compact("\n".join(page_texts))
            compact_cover = _compact("\n".join(page_texts[:3]))
            matched_sections = _find_sections(compact_text)
            identity_matches = (
                expected_label is not None
                and expected_year in compact_cover
                and expected_label in compact_cover
            )
            has_enough_evidence = (
                validated_pages >= min(3, hard_limit)
                and len(compact_text) >= 500
                and "报告摘要" not in compact_cover
                and (not stock_name or _compact(stock_name) in compact_text)
                and identity_matches
                and len(matched_sections) >= 3
                and not errors
            )
            if has_enough_evidence:
                break
            if validated_pages == scan_limit and scan_limit < hard_limit:
                scan_limit = hard_limit
    except Exception as exc:
        return {
            "content_validation_status": "failed",
            "analysis_eligible": False,
            "page_count": None,
            "requires_ocr": None,
            "validation_page_limit": validation_page_limit,
            "validated_pages": 0,
            "matched_sections": [],
            "validation_errors": [f"pdf_read_error:{type(exc).__name__}"],
        }

    compact_text = _compact("\n".join(page_texts))
    compact_cover = _compact("\n".join(page_texts[:3]))
    requires_ocr = len(compact_text) < 500
    if page_count == 0:
        errors.append("empty_pdf")
    if requires_ocr:
        errors.append("insufficient_extractable_text")
    if "报告摘要" in compact_cover:
        errors.append("summary_detected")
    if stock_name and _compact(stock_name) not in compact_text:
        errors.append("stock_name_not_found")

    if (
        expected_label is None
        or expected_year not in compact_cover
        or expected_label not in compact_cover
    ):
        errors.append("report_identity_not_found")

    if len(matched_sections) < 3:
        errors.append("insufficient_full_report_sections")

    passed = not errors
    return {
        "content_validation_status": "passed" if passed else "failed",
        "analysis_eligible": passed,
        "page_count": page_count,
        "requires_ocr": requires_ocr,
        "validation_page_limit": validation_page_limit,
        "validated_pages": validated_pages,
        "matched_sections": matched_sections,
        "validation_errors": errors,
    }


def _find_sections(compact_text: str) -> list[str]:
    matched_sections: list[str] = []
    for alternatives in SECTION_GROUPS:
        matched = next((name for name in alternatives if name in compact_text), None)
        if matched:
            matched_sections.append(matched)
    return matched_sections
