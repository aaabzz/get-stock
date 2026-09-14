from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from get_stock.agent_config import FINANCIAL_DATASET_FILES
from get_stock.storage import iter_json_lines


class StructuredDataAccessError(RuntimeError):
    """Raised when a whitelisted structured dataset cannot be read safely."""


class StructuredFinancialDataLoader:
    """Read only known cleaned JSON datasets; arbitrary paths are intentionally unsupported."""

    def __init__(self, data_dir: Path, stock_code: str) -> None:
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise StructuredDataAccessError("stock_code must contain exactly six digits")
        self.stock_code = stock_code
        self.stock_dir = data_dir.resolve() / "stocks" / stock_code
        self.cleaned_dir = self.stock_dir / "cleaned"

    def exists(self, dataset: str) -> bool:
        return self._path(dataset).is_file()

    def load(self, dataset: str) -> dict[str, Any] | list[dict[str, Any]]:
        path = self._path(dataset)
        if not path.is_file():
            return {} if path.suffix == ".json" else []
        if path.suffix == ".jsonl":
            records = list(iter_json_lines(path))
            return [record for record in records if self._belongs_to_stock(record)]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StructuredDataAccessError(f"invalid JSON dataset: {dataset}") from exc
        if not isinstance(value, dict):
            raise StructuredDataAccessError(f"dataset must contain a JSON object: {dataset}")
        return value if self._belongs_to_stock(value) else {}

    def load_many(self, datasets: set[str]) -> dict[str, Any]:
        return {dataset: self.load(dataset) for dataset in sorted(datasets)}

    def _path(self, dataset: str) -> Path:
        try:
            filename = FINANCIAL_DATASET_FILES[dataset]
        except KeyError as exc:
            raise StructuredDataAccessError(f"dataset is not allowed: {dataset}") from exc
        return self.cleaned_dir / filename

    def _belongs_to_stock(self, record: dict[str, Any]) -> bool:
        value = record.get("stock_code")
        return value in (None, "", self.stock_code)
