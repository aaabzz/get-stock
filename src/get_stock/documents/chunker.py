from __future__ import annotations

import re
from typing import Any

PARAGRAPH_SPLIT = re.compile(r"\n+")
BREAK_MARKS = ("。", "；", "！", "？", ".", ";", "，", ",")


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + chunk_size)
        end = hard_end
        if hard_end < len(text):
            floor = start + int(chunk_size * 0.6)
            candidates = [text.rfind(mark, floor, hard_end) for mark in BREAK_MARKS]
            best = max(candidates)
            if best >= floor:
                end = best + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [part for part in parts if part]


def _append_chunk(
    chunks: list[dict[str, Any]],
    section: dict[str, Any],
    buffer: list[tuple[int, str]],
    local_index: int,
) -> None:
    text = "\n".join(value for _, value in buffer)
    chunks.append(
        {
            "chunk_id": f"{section['section_id']}-chunk-{local_index:04d}",
            "section_id": section["section_id"],
            "section_type": section["section_type"],
            "heading": section["heading"],
            "start_page": buffer[0][0],
            "end_page": buffer[-1][0],
            "text": text,
            "character_count": len(text),
        }
    )


def chunk_sections(
    sections: list[dict[str, Any]],
    *,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    """Create section-bounded chunks with deterministic page citations."""
    if chunk_size < 200:
        raise ValueError("chunk_size must be at least 200")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")

    chunks: list[dict[str, Any]] = []
    for section in sections:
        units: list[tuple[int, str]] = []
        for page in section["page_texts"]:
            page_number = int(page["page_number"])
            paragraphs = [
                part.strip()
                for part in PARAGRAPH_SPLIT.split(page["text"])
                if part.strip()
            ]
            for paragraph in paragraphs:
                units.extend(
                    (page_number, part)
                    for part in _split_long_text(paragraph, chunk_size, chunk_overlap)
                )

        local_index = 0
        buffer: list[tuple[int, str]] = []

        for unit in units:
            current_length = sum(len(value) for _, value in buffer) + max(0, len(buffer) - 1)
            if buffer and current_length + 1 + len(unit[1]) > chunk_size:
                local_index += 1
                _append_chunk(chunks, section, buffer, local_index)
                overlap_units: list[tuple[int, str]] = []
                overlap_length = 0
                for previous in reversed(buffer):
                    next_length = overlap_length + len(previous[1])
                    if next_length > chunk_overlap:
                        break
                    overlap_units.insert(0, previous)
                    overlap_length = next_length
                buffer = overlap_units
                retained_length = sum(len(value) for _, value in buffer) + max(0, len(buffer) - 1)
                if retained_length + (1 if buffer else 0) + len(unit[1]) > chunk_size:
                    buffer = []
            buffer.append(unit)
        if buffer:
            local_index += 1
            _append_chunk(chunks, section, buffer, local_index)
    return chunks
