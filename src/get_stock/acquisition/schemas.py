from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_code: str = Field(pattern=r"^\d{6}$")
    datasets: tuple[str, ...] = Field(min_length=1)
    reason: str = "blocking_analysis_requirement"
    save_raw: bool = False
    pretty_json: bool = True

    @field_validator("datasets")
    @classmethod
    def unique_datasets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))


class AcquisitionJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "crawl_company",
        "crawl_financials",
        "crawl_market",
        "crawl_shareholders",
        "crawl_trading",
    ]
    datasets: tuple[str, ...] = Field(min_length=1)
    kwargs: dict[str, Any]


class AcquisitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_requested", "skipped", "completed", "partial", "failed"]
    requested_datasets: list[str] = Field(default_factory=list)
    verified_datasets: list[str] = Field(default_factory=list)
    remaining_datasets: list[str] = Field(default_factory=list)
    jobs: list[AcquisitionJob] = Field(default_factory=list)
    rounds_used: int = 0
    error: str | None = None
