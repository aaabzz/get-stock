from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

from get_stock.report_agent.catalog import (
    ALLOWED_SECTION_TYPES,
    DENIED_HEADING_ALIASES,
    DENIED_SECTION_TYPES,
    REPORT_TOPIC_CATALOG,
)
from get_stock.report_agent.schemas import ReportAnalysisTask, ReportRequirement

SECTION_PREFIX = re.compile(r"^第[一二三四五六七八九十百零0-9]+[章节部分]")


def normalize_heading(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = SECTION_PREFIX.sub("", normalized)
    return normalized.strip(":-—：")


def _heading_allowed(chunk: dict[str, Any]) -> bool:
    section_type = str(chunk.get("section_type") or "")
    heading = normalize_heading(str(chunk.get("heading") or ""))
    if section_type in DENIED_SECTION_TYPES or section_type not in ALLOWED_SECTION_TYPES:
        return False
    denied = {normalize_heading(alias) for alias in DENIED_HEADING_ALIASES}
    if any(alias in heading for alias in denied):
        return False
    # Older section output can leave the next top-level heading at the end of
    # the previous chunk. Reject that whole chunk rather than expose an
    # unprocessed financial table to the report reasoner.
    text_headings = {
        normalize_heading(line)
        for line in str(chunk.get("text") or "").splitlines()
        if len(line.strip()) <= 50
    }
    return denied.isdisjoint(text_headings)


def _heading_matches(chunk: dict[str, Any], requirement: ReportRequirement) -> tuple[bool, int]:
    policy = REPORT_TOPIC_CATALOG[requirement.topic]
    heading = normalize_heading(str(chunk.get("heading") or ""))
    aliases = tuple(policy["heading_aliases"]) + requirement.preferred_headings
    heading_score = 0
    for alias in aliases:
        expected = normalize_heading(alias)
        if not expected:
            continue
        if heading == expected:
            heading_score = max(heading_score, 10)
        elif expected in heading or heading in expected:
            heading_score = max(heading_score, 7)
    if heading_score and str(chunk.get("section_type") or "") in policy["preferred_sections"]:
        heading_score += 5
    return heading_score > 0, heading_score


def _score_chunk(
    chunk: dict[str, Any], requirement: ReportRequirement
) -> tuple[float, list[str], list[str]]:
    matched_heading, score = _heading_matches(chunk, requirement)
    if not matched_heading:
        return 0.0, [], []
    policy = REPORT_TOPIC_CATALOG[requirement.topic]
    heading = normalize_heading(str(chunk.get("heading") or ""))
    text = str(chunk.get("text") or "")
    matched_keywords: list[str] = []
    for keyword in policy["keywords"]:
        if keyword in text:
            matched_keywords.append(keyword)
            score += 1 + min(text.count(keyword), 3) * 0.25
        if keyword in heading:
            score += 3
    if not matched_keywords:
        return 0.0, [], []
    reasons = ["heading_match", "content_keyword_match"]
    return round(float(score), 2), matched_keywords, reasons


def retrieve_report_chunks(
    task: ReportAnalysisTask,
    chunks_by_report: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    eligible = {
        report_id: [chunk for chunk in chunks if _heading_allowed(chunk)]
        for report_id, chunks in chunks_by_report.items()
    }
    candidates_by_requirement: dict[str, list[dict[str, Any]]] = {}
    heading_hits: dict[str, int] = {}
    for requirement in task.requirements:
        candidates: list[dict[str, Any]] = []
        headings = 0
        for report_id, chunks in eligible.items():
            for chunk in chunks:
                matched, _ = _heading_matches(chunk, requirement)
                headings += int(matched)
                score, keywords, reasons = _score_chunk(chunk, requirement)
                if score <= 0:
                    continue
                candidates.append(
                    {
                        **chunk,
                        "_score": score,
                        "_matched_keywords": keywords,
                        "_selection_reasons": reasons,
                        "_topic": requirement.topic,
                        "_requirement_id": requirement.requirement_id,
                        "_report_id": report_id,
                    }
                )
        candidates.sort(
            key=lambda item: (
                item["_score"],
                item.get("report_period") or "",
                item["chunk_id"],
            ),
            reverse=True,
        )
        candidates_by_requirement[requirement.requirement_id] = candidates[: task.retrieval.top_k]
        heading_hits[requirement.requirement_id] = headings

    chunk_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    section_order: dict[tuple[str, str], list[str]] = defaultdict(list)
    for report_id, chunks in eligible.items():
        for chunk in chunks:
            key = (report_id, str(chunk["chunk_id"]))
            chunk_lookup[key] = chunk
            section_order[(report_id, str(chunk["section_id"]))].append(str(chunk["chunk_id"]))

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    selection_order: list[tuple[str, str]] = []

    def add_selected(
        chunk: dict[str, Any], requirement: ReportRequirement, *, adjacent: bool = False
    ) -> None:
        key = (str(chunk["announcement_id"]), str(chunk["chunk_id"]))
        if key not in selected:
            selected[key] = {
                **chunk,
                "_score": float(chunk.get("_score", 0.0)),
                "_matched_keywords": list(chunk.get("_matched_keywords", [])),
                "_selection_reasons": list(chunk.get("_selection_reasons", [])),
                "_topics": [],
                "_requirement_ids": [],
            }
            selection_order.append(key)
        item = selected[key]
        item["_score"] = max(float(item["_score"]), float(chunk.get("_score", 0.0)))
        for keyword in chunk.get("_matched_keywords", []):
            if keyword not in item["_matched_keywords"]:
                item["_matched_keywords"].append(keyword)
        for reason in chunk.get("_selection_reasons", []):
            if reason not in item["_selection_reasons"]:
                item["_selection_reasons"].append(reason)
        if requirement.topic not in item["_topics"]:
            item["_topics"].append(requirement.topic)
        if requirement.requirement_id not in item["_requirement_ids"]:
            item["_requirement_ids"].append(requirement.requirement_id)
        if adjacent and "adjacent_context" not in item["_selection_reasons"]:
            item["_selection_reasons"].append("adjacent_context")

    # Preserve at least one candidate per requirement before adding lower-ranked results.
    for requirement in task.requirements:
        candidates = candidates_by_requirement[requirement.requirement_id]
        if candidates:
            add_selected(candidates[0], requirement)
    for requirement in task.requirements:
        for candidate in candidates_by_requirement[requirement.requirement_id][1:]:
            add_selected(candidate, requirement)

    primary_keys = list(selection_order)
    if task.retrieval.adjacent_window:
        requirements_by_id = {item.requirement_id: item for item in task.requirements}
        for key in primary_keys:
            item = selected[key]
            order = section_order[(key[0], str(item["section_id"]))]
            position = order.index(key[1])
            start = max(0, position - task.retrieval.adjacent_window)
            end = min(len(order), position + task.retrieval.adjacent_window + 1)
            for chunk_id in order[start:end]:
                neighbor = chunk_lookup[(key[0], chunk_id)]
                for requirement_id in list(item["_requirement_ids"]):
                    add_selected(neighbor, requirements_by_id[requirement_id], adjacent=True)

    retained: list[dict[str, Any]] = []
    character_count = 0
    for key in selection_order:
        item = selected[key]
        length = len(str(item.get("text") or ""))
        if retained and character_count + length > task.retrieval.max_context_characters:
            continue
        retained.append(item)
        character_count += length

    return {
        "selected": retained,
        "candidates_by_requirement": candidates_by_requirement,
        "heading_hits": heading_hits,
        "eligible_chunk_count": sum(len(chunks) for chunks in eligible.values()),
        "context_character_count": character_count,
    }
