from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path

from get_stock.acquisition.catalog import CRAWLER_REGISTRY, DATASET_ACTIONS
from get_stock.acquisition.runner import ScrapyBatchRunner
from get_stock.acquisition.schemas import AcquisitionJob, AcquisitionRequest, AcquisitionResult
from get_stock.agent_config import (
    FINANCIAL_DATASET_FILES,
    MARKET_TRADING_DATASET_FILES,
    SHAREHOLDER_DATASET_FILES,
)

DATASET_FILES = {
    **FINANCIAL_DATASET_FILES,
    **MARKET_TRADING_DATASET_FILES,
    **SHAREHOLDER_DATASET_FILES,
}


class DataAcquisitionCoordinator:
    """Translate dataset gaps into allowlisted crawler jobs; never accepts commands."""

    def __init__(
        self,
        data_dir: Path,
        *,
        runner: Callable[[Sequence[AcquisitionJob], Path], None] | None = None,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.runner = runner or ScrapyBatchRunner()

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        jobs = self.plan(request)
        requested = list(request.datasets)
        try:
            self.runner(jobs, self.data_dir)
        except Exception as exc:
            return AcquisitionResult(
                status="failed",
                requested_datasets=requested,
                remaining_datasets=requested,
                jobs=jobs,
                rounds_used=1,
                error=str(exc),
            )

        verified = [dataset for dataset in requested if self._dataset_has_records(request, dataset)]
        remaining = [dataset for dataset in requested if dataset not in verified]
        status = "completed" if not remaining else ("partial" if verified else "failed")
        return AcquisitionResult(
            status=status,
            requested_datasets=requested,
            verified_datasets=verified,
            remaining_datasets=remaining,
            jobs=jobs,
            rounds_used=1,
            error=None if not remaining else "one or more requested datasets remain unavailable",
        )

    def plan(self, request: AcquisitionRequest) -> list[AcquisitionJob]:
        unsupported = sorted(set(request.datasets) - set(DATASET_ACTIONS))
        if unsupported:
            raise ValueError(f"datasets are not authorized for automatic crawling: {unsupported}")
        grouped: dict[str, list[str]] = defaultdict(list)
        for dataset in request.datasets:
            grouped[DATASET_ACTIONS[dataset]].append(dataset)

        jobs: list[AcquisitionJob] = []
        for action in CRAWLER_REGISTRY:
            datasets = tuple(grouped.get(action, ()))
            if not datasets:
                continue
            kwargs = {
                "stock_code": request.stock_code,
                "save_raw": request.save_raw,
                "pretty_json": request.pretty_json,
            }
            if action == "crawl_market":
                kwargs.update(
                    snapshot="market_snapshot" in datasets,
                    history="market_history" in datasets,
                )
            jobs.append(AcquisitionJob(action=action, datasets=datasets, kwargs=kwargs))
        return jobs

    def _dataset_has_records(self, request: AcquisitionRequest, dataset: str) -> bool:
        path = self.data_dir / "stocks" / request.stock_code / "cleaned" / DATASET_FILES[dataset]
        if not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            if path.suffix == ".jsonl":
                return any(line.strip() for line in path.read_text(encoding="utf-8").splitlines())
            payload = json.loads(path.read_text(encoding="utf-8"))
            return bool(payload)
        except (OSError, json.JSONDecodeError):
            return False
