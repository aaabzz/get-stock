from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from get_stock.financial_agent.catalog import REPORT_TYPES, TOPIC_DATASETS


class FinancialTaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_data_only: bool = True
    allow_pdf: bool = False
    allow_network: bool = False
    allow_crawler: bool = False
    allow_investment_advice: bool = False
    require_llm: bool = True

    def assert_supported(self) -> None:
        if not self.structured_data_only:
            raise ValueError("financial agent requires structured_data_only=true")
        if self.allow_pdf or self.allow_network or self.allow_crawler:
            raise ValueError("financial agent cannot access PDF, network or crawler")
        if self.allow_investment_advice:
            raise ValueError("financial agent cannot provide investment advice")


class FinancialAnalysisTask(BaseModel):
    """Task contract produced by the Supervisor, not by the financial agent."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    stock_code: str = Field(pattern=r"^\d{6}$")
    topics: tuple[str, ...] = Field(min_length=1)
    report_type: str = "annual"
    max_periods: int = Field(default=3, ge=1, le=10)
    period_from: str | None = None
    period_to: str | None = None
    dataset_names: tuple[str, ...] = Field(min_length=1)
    constraints: FinancialTaskConstraints = Field(default_factory=FinancialTaskConstraints)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(TOPIC_DATASETS))
        if unknown:
            raise ValueError(f"unsupported financial topics: {unknown}")
        return tuple(dict.fromkeys(value))

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, value: str) -> str:
        if value not in REPORT_TYPES:
            raise ValueError(f"unsupported report_type: {value}")
        return value

    @field_validator("dataset_names")
    @classmethod
    def validate_dataset_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from get_stock.agent_config import FINANCIAL_DATASET_FILES

        unknown = sorted(set(value) - set(FINANCIAL_DATASET_FILES))
        if unknown:
            raise ValueError(f"datasets are not allowed: {unknown}")
        return tuple(dict.fromkeys(value))


class FinancialClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    assessment: Literal["positive", "neutral", "watch", "risk", "not_determinable"]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class FinancialLLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_assessment: str = Field(min_length=1)
    key_strengths: list[FinancialClaim] = Field(default_factory=list)
    key_risks: list[FinancialClaim] = Field(default_factory=list)
    trend_assessments: list[FinancialClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FinancialAnalysisResult(BaseModel):
    """Stable specialist output consumed by the comprehensive analysis agent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    agent: Literal["financial_analysis"] = "financial_analysis"
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
    key_strengths: list[FinancialClaim]
    key_risks: list[FinancialClaim]
    trend_assessments: list[FinancialClaim]
    evidence: list[dict[str, Any]]
    missing_data: list[dict[str, Any]]
    limitations: list[str]
    confidence: float = Field(ge=0, le=1)
    generated_at: str
