from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_code: str = Field(pattern=r"^\d{6}$")
    report_type: Literal["annual", "semiannual"]
    report_period_from: date
    report_period_to: date
    disclosure_search_from: date
    disclosure_search_to: date
    target_count: int = Field(ge=1, le=6)
    max_pages: int = Field(default=20, ge=1, le=50)
    heading_mode: Literal["rules", "auto", "llm"] = "auto"

    @model_validator(mode="after")
    def validate_ranges(self) -> DocumentRecoveryRequest:
        if self.report_period_from > self.report_period_to:
            raise ValueError("report period range is reversed")
        if self.disclosure_search_from > self.disclosure_search_to:
            raise ValueError("disclosure search range is reversed")
        return self


class DocumentRecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_requested", "skipped", "completed", "partial", "failed"]
    request: dict[str, Any] | None = None
    crawl_attempted: bool = False
    rounds_used: int = Field(default=0, ge=0, le=1)
    processed: list[dict[str, Any]] = Field(default_factory=list)
    ready_announcement_ids: list[str] = Field(default_factory=list)
    remaining_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
