from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from get_stock.agent_config import (
    MARKET_TRADING_DATASET_FILES,
    MARKET_TRADING_STATE_FILES,
)
from get_stock.storage import iter_json_lines


class MarketTradingDataAccessError(RuntimeError):
    """Raised when an allowlisted market dataset cannot be read safely."""


class StructuredMarketTradingDataLoader:
    def __init__(self, data_dir: Path, stock_code: str) -> None:
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise MarketTradingDataAccessError("stock_code must contain exactly six digits")
        self.stock_code = stock_code
        self.stock_dir = data_dir.resolve() / "stocks" / stock_code
        self.cleaned_dir = self.stock_dir / "cleaned"
        self.state_dir = self.stock_dir / "state"

    def load(self, dataset: str) -> dict[str, Any] | list[dict[str, Any]]:
        path = self._dataset_path(dataset)
        if not path.is_file():
            return {} if path.suffix == ".json" else []
        if path.suffix == ".jsonl":
            try:
                records = list(iter_json_lines(path))
            except ValueError as exc:
                raise MarketTradingDataAccessError(f"invalid JSONL dataset: {dataset}") from exc
            return [record for record in records if self._belongs_to_stock(record)]
        value = self._load_json(path, f"dataset: {dataset}")
        if not isinstance(value, dict):
            raise MarketTradingDataAccessError(f"dataset must be a JSON object: {dataset}")
        return value if self._belongs_to_stock(value) else {}

    def load_many(self, datasets: set[str]) -> dict[str, Any]:
        return {dataset: self.load(dataset) for dataset in sorted(datasets)}

    def load_states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for state_name, filename in MARKET_TRADING_STATE_FILES.items():
            path = self.state_dir / filename
            if not path.is_file():
                states[state_name] = {}
                continue
            value = self._load_json(path, f"state: {state_name}")
            if not isinstance(value, dict):
                raise MarketTradingDataAccessError(
                    f"state must contain a JSON object: {state_name}"
                )
            states[state_name] = value if self._belongs_to_stock(value) else {}
        return states

    def _dataset_path(self, dataset: str) -> Path:
        try:
            filename = MARKET_TRADING_DATASET_FILES[dataset]
        except KeyError as exc:
            raise MarketTradingDataAccessError(f"dataset is not allowed: {dataset}") from exc
        return self.cleaned_dir / filename

    @staticmethod
    def _load_json(path: Path, label: str) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MarketTradingDataAccessError(f"invalid JSON {label}") from exc

    def _belongs_to_stock(self, record: dict[str, Any]) -> bool:
        return record.get("stock_code") in (None, "", self.stock_code)
