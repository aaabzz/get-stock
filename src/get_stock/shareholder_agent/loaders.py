from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from get_stock.agent_config import SHAREHOLDER_DATASET_FILES, SHAREHOLDER_STATE_FILES
from get_stock.storage import iter_json_lines


class ShareholderDataAccessError(RuntimeError):
    pass


class StructuredShareholderDataLoader:
    def __init__(self, data_dir: Path, stock_code: str) -> None:
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise ShareholderDataAccessError("stock_code must contain exactly six digits")
        self.stock_code = stock_code
        stock_dir = data_dir.resolve() / "stocks" / stock_code
        self.cleaned_dir = stock_dir / "cleaned"
        self.state_dir = stock_dir / "state"

    def load(self, dataset: str) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            filename = SHAREHOLDER_DATASET_FILES[dataset]
        except KeyError as exc:
            raise ShareholderDataAccessError(f"dataset is not allowed: {dataset}") from exc
        path = self.cleaned_dir / filename
        if not path.is_file():
            return {} if path.suffix == ".json" else []
        if path.suffix == ".jsonl":
            try:
                records = list(iter_json_lines(path))
            except ValueError as exc:
                raise ShareholderDataAccessError(f"invalid JSONL dataset: {dataset}") from exc
            return [record for record in records if self._belongs_to_stock(record)]
        value = self._load_json(path, f"dataset: {dataset}")
        if not isinstance(value, dict):
            raise ShareholderDataAccessError(f"dataset must be a JSON object: {dataset}")
        return value if self._belongs_to_stock(value) else {}

    def load_many(self, datasets: set[str]) -> dict[str, Any]:
        return {dataset: self.load(dataset) for dataset in sorted(datasets)}

    def load_states(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, filename in SHAREHOLDER_STATE_FILES.items():
            path = self.state_dir / filename
            if not path.is_file():
                result[name] = {}
                continue
            value = self._load_json(path, f"state: {name}")
            if not isinstance(value, dict):
                raise ShareholderDataAccessError(f"state must be a JSON object: {name}")
            result[name] = value if self._belongs_to_stock(value) else {}
        return result

    @staticmethod
    def _load_json(path: Path, label: str) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ShareholderDataAccessError(f"invalid JSON {label}") from exc

    def _belongs_to_stock(self, record: dict[str, Any]) -> bool:
        return record.get("stock_code") in (None, "", self.stock_code)
