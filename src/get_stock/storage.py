from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def cleaned_data_path(stock_dir: Path, filename: str) -> Path:
    """Return the canonical path for parsed, machine-readable stock data."""
    return stock_dir / "cleaned" / filename


def pretty_data_path(stock_dir: Path, source: Path) -> Path:
    """Return the human-readable JSON path corresponding to a cleaned source."""
    return stock_dir / "pretty" / f"{source.stem}.json"


def state_data_path(stock_dir: Path, filename: str) -> Path:
    """Return the canonical path for crawler state and run summaries."""
    return stock_dir / "state" / filename


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def append_json_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        stream.write("\n")


def atomic_write_json_lines(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    temporary.replace(path)


def iter_json_lines(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            if isinstance(value, dict):
                yield value


def jsonl_to_pretty_json(source: Path, destination: Path | None = None) -> Path:
    """Convert a JSONL file to an indented JSON array without changing the source."""
    if not source.is_file():
        raise FileNotFoundError(source)

    output_path = destination or source.with_suffix(".pretty.json")
    if output_path.resolve() == source.resolve():
        raise ValueError("destination must be different from the JSONL source")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write("[")
            wrote_record = False
            for record in iter_json_lines(source):
                if wrote_record:
                    stream.write(",")
                stream.write("\n")
                rendered = json.dumps(record, ensure_ascii=False, indent=2)
                stream.write("\n".join(f"  {line}" for line in rendered.splitlines()))
                wrote_record = True
            stream.write("\n]\n" if wrote_record else "]\n")
        temporary.replace(output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return output_path


def sync_pretty_json(source: Path, destination: Path) -> Path:
    """Mirror cleaned JSON or JSONL data as indented JSON for human inspection."""
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.resolve() == source.resolve():
        raise ValueError("destination must be different from the cleaned source")
    if source.suffix == ".jsonl":
        return jsonl_to_pretty_json(source, destination)
    if source.suffix == ".json":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {source}") from exc
        atomic_write_json(destination, payload)
        return destination
    raise ValueError(f"unsupported cleaned data format: {source.suffix}")


def load_announcement_ids(path: Path) -> set[str]:
    return {
        str(record["announcement_id"])
        for record in iter_json_lines(path)
        if record.get("announcement_id")
    }
