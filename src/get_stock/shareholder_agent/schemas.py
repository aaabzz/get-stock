from __future__ import annotations

from datetime import date
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from get_stock.agent_config import SHAREHOLDER_DATASET_FILES
from get_stock.shareholder_agent.catalog import TOPIC_DATASETS

ShareholderTopic: TypeAlias = Literal[
    "ownership_structure",
    "shareholder_concentration",
    "major_holder_changes",
    "shareholder_count",
    "fund_holdings",
    "restricted_unlocks",
    "equity_pledges",
]


class ShareholderTaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_data_only: bool = True
    allow_pdf: bool = False
    allow_network: bool = False
    allow_crawler: bool = False
    allow_identity_inference: bool = False
    allow_investment_advice: bool = False
    require_llm: bool = True

    def assert_supported(self) -> None:
        if not self.structured_data_only:
            raise ValueError("shareholder agent requires structured_data_only=true")
        if self.allow_pdf or self.allow_network or self.allow_crawler:
            raise ValueError("shareholder agent cannot access PDF, network or crawler")
        if self.allow_identity_inference or self.allow_investment_advice:
            raise ValueError("shareholder agent cannot infer identities or give advice")


class ShareholderAnalysisTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    stock_code: str = Field(pattern=r"^\d{6}$")
    topics: tuple[str, ...] = Field(min_length=1)
    as_of_date: date | None = None
    max_periods: int = Field(default=4, ge=1, le=20)
    period_from: date | None = None
    period_to: date | None = None
    dataset_names: tuple[str, ...] = Field(min_length=1)
    constraints: ShareholderTaskConstraints = Field(default_factory=ShareholderTaskConstraints)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(TOPIC_DATASETS))
        if unknown:
            raise ValueError(f"unsupported shareholder topics: {unknown}")
        return tuple(dict.fromkeys(value))

    @field_validator("dataset_names")
    @classmethod
    def validate_dataset_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(SHAREHOLDER_DATASET_FILES))
        if unknown:
            raise ValueError(f"datasets are not allowed: {unknown}")
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_period(self) -> ShareholderAnalysisTask:
        if self.period_from and self.period_to and self.period_from > self.period_to:
            raise ValueError("period_from cannot be later than period_to")
        return self


class MissingShareholderData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    dataset: str | None
    reason_code: Literal[
        "dataset_missing",
        "crawl_failed",
        "insufficient_periods",
        "required_field_missing",
        "period_not_covered",
        "unit_unknown",
        "cross_dataset_mismatch",
    ]
    reason: str
    blocking: bool
    recoverable: bool = True
    recommended_action: str | None = None
    expected: Any | None = None
    actual: Any | None = None


class ShareholderClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    topic: ShareholderTopic
    assessment: Literal["positive", "neutral", "watch", "risk", "not_determinable"]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class ShareholderLLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ownership_summary: str = Field(min_length=1)
    concentration_assessments: list[ShareholderClaim] = Field(default_factory=list)
    notable_holder_changes: list[ShareholderClaim] = Field(default_factory=list)
    risk_events: list[ShareholderClaim] = Field(default_factory=list)
    trend_assessments: list[ShareholderClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ShareholderAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    agent: Literal["shareholder_analysis"] = "shareholder_analysis"
    agent_version: str
    task_id: str
    status: Literal["completed", "partial", "insufficient_data"]
    data_scope: Literal["structured_data_only"] = "structured_data_only"
    llm_used: bool
    stock_code: str
    stock_name: str | None = None
    industry_name: str | None = None
    analysis_scope: dict[str, Any]
    accessed_datasets: list[str]
    summary: str
    dimensions: dict[str, dict[str, Any]]
    concentration_assessments: list[ShareholderClaim]
    notable_holder_changes: list[ShareholderClaim]
    risk_events: list[ShareholderClaim]
    trend_assessments: list[ShareholderClaim]
    evidence: list[dict[str, Any]]
    missing_data: list[MissingShareholderData]
    limitations: list[str]
    confidence: float = Field(ge=0, le=1)
    generated_at: str
