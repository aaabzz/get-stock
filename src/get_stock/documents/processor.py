from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from get_stock.documents.chunker import chunk_sections
from get_stock.documents.cleaner import clean_pages
from get_stock.documents.extractor import extract_pages
from get_stock.documents.heading_reasoner import HeadingReasoner
from get_stock.documents.segmenter import HEADING_MODES, resolve_headings, segment_sections
from get_stock.parsers import classify_announcement_document
from get_stock.pdf_validation import validate_full_report_pdf
from get_stock.storage import atomic_write_json, atomic_write_json_lines, iter_json_lines

PROCESSOR_VERSION = "1.1"
CLEANER_VERSION = "1.0"
SEGMENTER_VERSION = "1.1"
CHUNKER_VERSION = "1.0"
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class ReportProcessingError(RuntimeError):
    """Raised when a report cannot safely enter the PDF processing pipeline."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stock_dir(data_dir: Path, stock_code: str) -> Path:
    normalized = stock_code.strip()
    if not normalized.isdigit() or len(normalized) != 6:
        raise ReportProcessingError("stock_code must contain exactly six digits")
    return data_dir.resolve() / "stocks" / normalized


def _announcement_path(stock_dir: Path) -> Path:
    return stock_dir / "cleaned" / "announcements.jsonl"


def _load_announcement(stock_dir: Path, announcement_id: str) -> dict[str, Any]:
    path = _announcement_path(stock_dir)
    if not path.is_file():
        raise ReportProcessingError(f"announcement registry does not exist: {path}")
    matches = [
        record
        for record in iter_json_lines(path)
        if str(record.get("announcement_id") or "") == announcement_id
    ]
    if not matches:
        raise ReportProcessingError(f"announcement_id {announcement_id} was not found")
    return dict(matches[-1])


def _normalize_classification(record: dict[str, Any]) -> dict[str, Any]:
    classification = classify_announcement_document(
        str(record.get("title") or ""), str(record.get("category") or "")
    )
    normalized = dict(record)
    for key, value in classification.items():
        if key not in normalized or normalized[key] in (None, ""):
            normalized[key] = value
    return normalized


def _resolve_pdf_path(data_dir: Path, stock_dir: Path, value: Any) -> Path:
    if not value:
        raise ReportProcessingError("the announcement has no downloaded PDF path")
    supplied = Path(str(value))
    candidates = [supplied] if supplied.is_absolute() else [
        Path.cwd() / supplied,
        data_dir.parent / supplied,
        data_dir / supplied,
        stock_dir / supplied,
    ]
    resolved = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if resolved is None:
        raise ReportProcessingError(f"downloaded PDF does not exist: {supplied}")
    documents_dir = (stock_dir / "documents").resolve()
    if not resolved.is_relative_to(documents_dir):
        raise ReportProcessingError("the PDF path is outside the stock documents directory")
    if resolved.suffix.lower() != ".pdf":
        raise ReportProcessingError("the downloaded document is not a PDF")
    return resolved


def _ensure_eligible(record: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
    if record.get("document_role") != "full_report":
        raise ReportProcessingError("only document_role=full_report can be processed")

    status = record.get("content_validation_status")
    eligible = record.get("analysis_eligible") is True
    if status == "passed" and eligible:
        return record
    if status not in (None, "", "pending"):
        raise ReportProcessingError(
            f"full report validation has not passed: {status or 'unknown'}"
        )

    # Compatibility for records crawled before document-role validation was introduced.
    validation = validate_full_report_pdf(
        pdf_path,
        stock_name=str(record.get("stock_name") or ""),
        report_type=str(record.get("report_type") or ""),
        report_period=str(record.get("report_period") or ""),
    )
    normalized = {**record, **validation}
    if not normalized.get("analysis_eligible"):
        errors = ", ".join(normalized.get("validation_errors") or ["unknown validation error"])
        raise ReportProcessingError(f"full report validation failed: {errors}")
    return normalized


def _manifest_matches(
    manifest: dict[str, Any],
    *,
    source_sha256: str,
    chunk_size: int,
    chunk_overlap: int,
    heading_mode: str,
    heading_reasoner_id: str | None,
) -> bool:
    return (
        manifest.get("source_sha256") == source_sha256
        and manifest.get("processor_version") == PROCESSOR_VERSION
        and manifest.get("cleaner_version") == CLEANER_VERSION
        and manifest.get("segmenter_version") == SEGMENTER_VERSION
        and manifest.get("chunker_version") == CHUNKER_VERSION
        and manifest.get("chunk_size") == chunk_size
        and manifest.get("chunk_overlap") == chunk_overlap
        and manifest.get("heading_mode") == heading_mode
        and manifest.get("heading_reasoner_id") == heading_reasoner_id
        and manifest.get("status") in {"success", "partial", "requires_ocr"}
    )


def _quality_summary(
    pages: list[dict[str, Any]], sections: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> dict[str, Any]:
    nonempty_pages = sum(bool(page.get("text", "").strip()) for page in pages)
    failed_pages = [
        int(page["page_number"])
        for page in pages
        if page.get("extraction_status") == "failed"
    ]
    total_chars = sum(int(page.get("character_count") or 0) for page in pages)
    recognized = sum(
        section["section_type"] not in {"front_matter", "unclassified"}
        for section in sections
    )
    ratio = nonempty_pages / len(pages) if pages else 0.0

    if not pages or total_chars < 500:
        status = "requires_ocr"
    elif ratio < 0.8 or failed_pages or recognized == 0:
        status = "partial"
    else:
        status = "success"
    return {
        "status": status,
        "page_count": len(pages),
        "nonempty_page_count": nonempty_pages,
        "nonempty_page_ratio": round(ratio, 4),
        "failed_pages": failed_pages,
        "extracted_character_count": total_chars,
        "section_count": len(sections),
        "recognized_section_count": recognized,
        "chunk_count": len(chunks),
    }


def list_processable_reports(data_dir: Path, stock_code: str) -> list[dict[str, Any]]:
    """List full-report records; final content eligibility is checked during processing."""
    stock_dir = _stock_dir(data_dir, stock_code)
    path = _announcement_path(stock_dir)
    if not path.is_file():
        return []
    reports: list[dict[str, Any]] = []
    for source in iter_json_lines(path):
        record = _normalize_classification(dict(source))
        if record.get("document_role") == "full_report" and record.get("local_path"):
            reports.append(record)
    return reports


def process_report(
    data_dir: Path,
    stock_code: str,
    announcement_id: str,
    *,
    force: bool = False,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
    heading_mode: str = "rules",
    heading_reasoner: HeadingReasoner | None = None,
    heading_reasoner_id: str | None = None,
) -> dict[str, Any]:
    """Process one downloaded full report into page, section and chunk JSONL files."""
    if chunk_size < 200 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ReportProcessingError(
            "chunk_size must be >= 200 and chunk_overlap must be >= 0 and smaller than chunk_size"
        )
    normalized_heading_mode = heading_mode.strip().lower()
    if normalized_heading_mode not in HEADING_MODES:
        choices = ", ".join(sorted(HEADING_MODES))
        raise ReportProcessingError(
            f"invalid heading_mode {heading_mode!r}; expected one of: {choices}"
        )
    if normalized_heading_mode == "llm" and heading_reasoner is None:
        raise ReportProcessingError("heading_mode='llm' requires a configured heading reasoner")
    effective_reasoner_id = (
        (heading_reasoner_id or type(heading_reasoner).__name__)
        if normalized_heading_mode != "rules" and heading_reasoner
        else None
    )
    stock_dir = _stock_dir(data_dir, stock_code)
    record = _normalize_classification(_load_announcement(stock_dir, str(announcement_id)))
    pdf_path = _resolve_pdf_path(data_dir.resolve(), stock_dir, record.get("local_path"))
    record = _ensure_eligible(record, pdf_path)

    output_dir = stock_dir / "processed" / "reports" / str(announcement_id)
    manifest_path = output_dir / "manifest.json"
    source_sha256 = _sha256(pdf_path)
    if manifest_path.is_file() and not force:
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _manifest_matches(
            manifest,
            source_sha256=source_sha256,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            heading_mode=normalized_heading_mode,
            heading_reasoner_id=effective_reasoner_id,
        ):
            return {**manifest, "cache_hit": True, "output_dir": str(output_dir)}

    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".processing.lock"
    try:
        with lock_path.open("x", encoding="utf-8") as stream:
            stream.write(str(datetime.now(CHINA_TZ).isoformat()))
    except FileExistsError as exc:
        raise ReportProcessingError(
            f"report is already being processed: {announcement_id}"
        ) from exc

    try:
        extracted_pages, pdf_metadata = extract_pages(pdf_path)
        pages = clean_pages(extracted_pages)
        headings, heading_diagnostics = resolve_headings(
            pages,
            mode=normalized_heading_mode,
            reasoner=heading_reasoner,
        )
        sections = segment_sections(pages, headings=headings)
        chunks = chunk_sections(
            sections, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        quality = _quality_summary(pages, sections, chunks)

        page_records = [
            {"announcement_id": str(announcement_id), **page} for page in pages
        ]
        section_records = [
            {
                "announcement_id": str(announcement_id),
                **{key: value for key, value in section.items() if key != "page_texts"},
            }
            for section in sections
        ]
        heading_records = [
            {
                "announcement_id": str(announcement_id),
                **{
                    key: value
                    for key, value in heading.items()
                    if key != "page_index"
                },
            }
            for heading in headings
        ]
        chunk_records = [
            {"announcement_id": str(announcement_id), **chunk} for chunk in chunks
        ]
        atomic_write_json_lines(output_dir / "pages.jsonl", page_records)
        atomic_write_json_lines(output_dir / "headings.jsonl", heading_records)
        atomic_write_json_lines(output_dir / "sections.jsonl", section_records)
        atomic_write_json_lines(output_dir / "chunks.jsonl", chunk_records)

        manifest = {
            "schema_version": "1.0",
            "processor_version": PROCESSOR_VERSION,
            "cleaner_version": CLEANER_VERSION,
            "segmenter_version": SEGMENTER_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "status": quality["status"],
            "stock_code": stock_code,
            "stock_name": record.get("stock_name"),
            "announcement_id": str(announcement_id),
            "title": record.get("title"),
            "document_role": record.get("document_role"),
            "report_type": record.get("report_type"),
            "report_period": record.get("report_period"),
            "source_pdf": str(pdf_path),
            "source_sha256": source_sha256,
            "pdf_metadata": pdf_metadata,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "heading_mode": normalized_heading_mode,
            "heading_reasoner_id": effective_reasoner_id,
            "heading_detection": heading_diagnostics,
            "quality": quality,
            "outputs": {
                "pages": "pages.jsonl",
                "headings": "headings.jsonl",
                "sections": "sections.jsonl",
                "chunks": "chunks.jsonl",
            },
            "processed_at": datetime.now(CHINA_TZ).isoformat(),
        }
        atomic_write_json(manifest_path, manifest)
        return {**manifest, "cache_hit": False, "output_dir": str(output_dir)}
    finally:
        lock_path.unlink(missing_ok=True)
