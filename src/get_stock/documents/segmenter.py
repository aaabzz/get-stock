from __future__ import annotations

import re
from typing import Any, Literal

from get_stock.documents.heading_reasoner import HeadingReasoner
from get_stock.documents.heading_schemas import HeadingLLMAnalysis

SECTION_ALIASES = (
    ("company_profile", ("公司简介和主要财务指标", "公司简介", "公司基本情况")),
    (
        "financial_indicators",
        ("会计数据和财务指标", "主要会计数据和财务指标", "主要财务数据和财务指标"),
    ),
    ("business_overview", ("公司业务概要", "公司业务概述", "公司主要业务")),
    ("management_discussion", ("管理层讨论与分析", "经营情况讨论与分析")),
    ("corporate_governance", ("公司治理",)),
    ("environment_social", ("公司治理、环境和社会", "环境与社会责任", "社会责任")),
    ("important_matters", ("重要事项",)),
    ("shareholders", ("股份变动及股东情况", "股份变动和股东情况")),
    ("bonds", ("债券相关情况", "公司债券")),
    ("financial_report", ("财务报告", "财务报表")),
)
HEADING_PATTERN = re.compile(
    r"^第(?P<number>[一二三四五六七八九十百零0-9]+)(?P<marker>[章节])(?P<title>.+)$"
)
HEADING_MODES = {"rules", "auto", "llm"}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _semantic_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()


def _classify_title(title: str) -> str | None:
    for section_type, aliases in SECTION_ALIASES:
        if any(title == alias or title.startswith(f"{alias}(") for alias in aliases):
            return section_type
    return None


def _heading_ordinal(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9}
    if "百" in value:
        hundreds, _, remainder = value.partition("百")
        tail = _heading_ordinal(remainder) if remainder else 0
        return digits.get(hundreds, 1) * 100 + (tail or 0)
    if "十" in value:
        tens, _, ones = value.partition("十")
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    return digits.get(value)


def _heading_candidate(line: str, *, page_index: int, page_number: int) -> dict[str, Any] | None:
    compact = _compact(line)
    if not compact or len(compact) > 100:
        return None
    match = HEADING_PATTERN.fullmatch(compact)
    if not match:
        return None
    section_type = _classify_title(match.group("title"))
    return {
        "page_index": page_index,
        "page_number": page_number,
        "chapter_number": match.group("number"),
        "chapter_marker": match.group("marker"),
        "raw_heading": line.strip(),
        "normalized_heading": compact,
        "section_type": section_type or "unclassified",
        "classification_method": "rule_alias" if section_type else "unclassified",
        "confidence": 1.0 if section_type else 0.0,
    }


def _toc_end_page(pages: list[dict[str, Any]]) -> int:
    """Estimate the table-of-contents tail without requiring known section aliases."""
    toc_end = 0
    for page_index, page in enumerate(pages[:10]):
        page_number = int(page["page_number"])
        text = str(page.get("text") or "")
        matches = sum(
            _heading_candidate(
                line,
                page_index=page_index,
                page_number=page_number,
            )
            is not None
            for line in text.splitlines()
        )
        if "目录" in text or matches >= 3:
            toc_end = page_number
    return toc_end


def detect_rule_headings(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect source-backed boundaries before attempting semantic classification."""
    toc_end = _toc_end_page(pages)
    headings: list[dict[str, Any]] = []
    last_key: tuple[str, str, str] | None = None
    for page_index, page in enumerate(pages):
        page_number = int(page["page_number"])
        if page_number <= toc_end:
            continue
        candidates = [
            value
            for line in str(page.get("text") or "").splitlines()[:12]
            if (
                value := _heading_candidate(
                    line,
                    page_index=page_index,
                    page_number=page_number,
                )
            )
        ]
        candidate_with_key = None
        for candidate in candidates:
            key = (
                candidate["chapter_number"],
                candidate["chapter_marker"],
                _semantic_key(candidate["raw_heading"]),
            )
            if key == last_key:
                continue
            is_known = candidate["section_type"] != "unclassified"
            is_unknown_chapter = candidate["chapter_marker"] == "章"
            follows_top_level_section = False
            if headings and candidate["chapter_marker"] == "节":
                previous = headings[-1]
                current_number = _heading_ordinal(candidate["chapter_number"])
                previous_number = _heading_ordinal(previous["chapter_number"])
                follows_top_level_section = (
                    previous["chapter_marker"] == "节"
                    and current_number is not None
                    and previous_number is not None
                    and current_number == previous_number + 1
                )
            if is_known or is_unknown_chapter or follows_top_level_section:
                candidate_with_key = candidate, key
                break
        if candidate_with_key is None:
            continue
        candidate, key = candidate_with_key
        candidate["candidate_id"] = f"candidate-{len(headings) + 1:04d}"
        candidate["heading_id"] = f"heading-{len(headings) + 1:04d}"
        headings.append(candidate)
        last_key = key
    return headings


def resolve_headings(
    pages: list[dict[str, Any]],
    *,
    mode: Literal["rules", "auto", "llm"] = "rules",
    reasoner: HeadingReasoner | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Resolve headings with rules first and an optional schema-constrained LLM classifier."""
    if mode not in HEADING_MODES:
        raise ValueError(f"invalid heading mode: {mode}")
    headings = detect_rule_headings(pages)
    targets = (
        headings
        if mode == "llm"
        else [item for item in headings if item["section_type"] == "unclassified"]
    )
    diagnostics: dict[str, Any] = {
        "mode": mode,
        "llm_used": False,
        "candidate_count": len(headings),
        "llm_candidate_count": len(targets),
        "unclassified_count": sum(
            item["section_type"] == "unclassified" for item in headings
        ),
        "warnings": [],
    }
    if mode == "rules" or not targets:
        return headings, diagnostics
    if reasoner is None:
        diagnostics["warnings"].append(
            "heading LLM was requested but no reasoner was configured; rule results used"
        )
        return headings, diagnostics

    selected = targets[:64]
    packet = {
        "allowed_section_types": sorted(
            {section_type for section_type, _ in SECTION_ALIASES} | {"unclassified"}
        ),
        "candidates": [
            {
                "candidate_id": item["candidate_id"],
                "raw_heading": item["raw_heading"],
                "chapter_number": item["chapter_number"],
                "chapter_marker": item["chapter_marker"],
                "page_number": item["page_number"],
                "rule_section_type": item["section_type"],
            }
            for item in selected
        ],
    }
    by_id = {item["candidate_id"]: item for item in selected}
    try:
        response = reasoner(packet)
        analysis = (
            response
            if isinstance(response, HeadingLLMAnalysis)
            else HeadingLLMAnalysis.model_validate(response)
        )
        diagnostics["llm_used"] = True
        for classification in analysis.classifications:
            target = by_id.get(classification.candidate_id)
            if target is None:
                diagnostics["warnings"].append(
                    f"LLM returned unauthorized candidate: {classification.candidate_id}"
                )
                continue
            if _semantic_key(classification.normalized_heading) != _semantic_key(
                target["raw_heading"]
            ):
                diagnostics["warnings"].append(
                    f"LLM changed source heading meaning: {classification.candidate_id}"
                )
                continue
            if classification.confidence < 0.65:
                diagnostics["warnings"].append(
                    f"LLM heading confidence below threshold: {classification.candidate_id}"
                )
                continue
            target["normalized_heading"] = classification.normalized_heading
            target["section_type"] = classification.section_type
            target["classification_method"] = "llm"
            target["confidence"] = classification.confidence
    except Exception as exc:
        diagnostics["warnings"].append(f"heading LLM failed; rule results used: {exc}")

    diagnostics["unclassified_count"] = sum(
        item["section_type"] == "unclassified" for item in headings
    )
    return headings, diagnostics


def segment_sections(
    pages: list[dict[str, Any]],
    *,
    headings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Split cleaned pages at validated headings without dropping unknown chapters."""
    if not pages:
        return []
    if headings is None:
        headings = detect_rule_headings(pages)

    boundaries = [
        (
            int(item["page_index"]),
            str(item["section_type"]),
            str(item["raw_heading"]),
            item,
        )
        for item in headings
    ]
    if not boundaries:
        boundaries = [(0, "unclassified", "未识别章节", {})]
    elif boundaries[0][0] > 0:
        boundaries.insert(0, (0, "front_matter", "报告前置内容", {}))

    sections: list[dict[str, Any]] = []
    for section_index, (start, section_type, heading, metadata) in enumerate(boundaries):
        end = (
            boundaries[section_index + 1][0]
            if section_index + 1 < len(boundaries)
            else len(pages)
        )
        section_pages = pages[start:end]
        if not section_pages:
            continue
        text = "\n\n".join(str(page.get("text") or "") for page in section_pages).strip()
        sections.append(
            {
                "section_id": f"section-{section_index + 1:02d}",
                "section_type": section_type,
                "heading": heading,
                "normalized_heading": metadata.get("normalized_heading", heading),
                "chapter_number": metadata.get("chapter_number"),
                "classification_method": metadata.get("classification_method", "synthetic"),
                "classification_confidence": metadata.get("confidence", 1.0),
                "start_page": int(section_pages[0]["page_number"]),
                "end_page": int(section_pages[-1]["page_number"]),
                "text": text,
                "character_count": len(text),
                "page_texts": [
                    {
                        "page_number": int(page["page_number"]),
                        "text": str(page.get("text") or ""),
                    }
                    for page in section_pages
                ],
            }
        )
    return sections
