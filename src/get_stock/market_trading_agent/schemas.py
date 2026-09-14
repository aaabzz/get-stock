from __future__ import annotations

from datetime import date
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from get_stock.agent_config import MARKET_TRADING_DATASET_FILES
from get_stock.market_trading_agent.catalog import TOPIC_DATASETS

MarketTradingTopic: TypeAlias = Literal[
    "price_trend",
    "volatility",
    "liquidity",
    "price_volume",
    "valuation",
    "margin_activity",
    "block_trades",
]


class MarketTradingTaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_data_only: bool = True
    allow_pdf: bool = False
    allow_network: bool = False
    allow_crawler: bool = False
    allow_price_prediction: bool = False
    allow_investment_advice: bool = False
    require_llm: bool = True

    def assert_supported(self) -> None:
        if not self.structured_data_only:
            raise ValueError("market trading agent requires structured_data_only=true")
        if self.allow_pdf or self.allow_network or self.allow_crawler:
            raise ValueError("market trading agent cannot access PDF, network or crawler")
        if self.allow_price_prediction or self.allow_investment_advice:
            raise ValueError("market trading agent cannot predict prices or give advice")


class MarketTradingAnalysisTask(BaseModel):
    """Normalized task produced by a Supervisor."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    stock_code: str = Field(pattern=r"^\d{6}$")
    topics: tuple[str, ...] = Field(min_length=1)
    as_of_date: date | None = None
    lookback_sessions: int = Field(default=60, ge=2, le=500)
    period_from: date | None = None
    period_to: date | None = None
    dataset_names: tuple[str, ...] = Field(min_length=1)
    constraints: MarketTradingTaskConstraints = Field(default_factory=MarketTradingTaskConstraints)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(TOPIC_DATASETS))
        if unknown:
            raise ValueError(f"unsupported market trading topics: {unknown}")
        return tuple(dict.fromkeys(value))

    @field_validator("dataset_names")
    @classmethod
    def validate_dataset_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(MARKET_TRADING_DATASET_FILES))
        if unknown:
            raise ValueError(f"datasets are not allowed: {unknown}")
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_period(self) -> MarketTradingAnalysisTask:
        if self.period_from and self.period_to and self.period_from > self.period_to:
            raise ValueError("period_from cannot be later than period_to")
        return self


class MissingMarketData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    dataset: str | None
    reason_code: Literal[
        "dataset_missing",
        "crawl_failed",
        "dataset_stale",
        "insufficient_periods",
        "required_field_missing",
        "date_not_covered",
        "cross_dataset_mismatch",
    ]
    reason: str
    blocking: bool
    recoverable: bool = True
    recommended_action: str | None = None
    expected: Any | None = None
    actual: Any | None = None


class MarketTradingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    topic: MarketTradingTopic
    assessment: Literal["positive", "neutral", "watch", "risk", "not_determinable"]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class MarketTradingLLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_state_summary: str = Field(min_length=1)
    notable_activity: list[MarketTradingClaim] = Field(default_factory=list)
    risk_signals: list[MarketTradingClaim] = Field(default_factory=list)
    trend_assessments: list[MarketTradingClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MarketTradingAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    agent: Literal["market_trading"] = "market_trading"
    agent_version: str
    task_id: str
    status: Literal["completed", "partial", "insufficient_data"]
    data_scope: Literal["structured_data_only"] = "structured_data_only"
    llm_used: bool
    stock_code: str
    stock_name: str | None = None
    industry_name: str | None = None
    analysis_scope: dict[str, Any]
    data_freshness: dict[str, dict[str, Any]]
    accessed_datasets: list[str]
    summary: str
    dimensions: dict[str, dict[str, Any]]
    notable_activity: list[MarketTradingClaim]
    risk_signals: list[MarketTradingClaim]
    trend_assessments: list[MarketTradingClaim]
    evidence: list[dict[str, Any]]
    missing_data: list[MissingMarketData]
    limitations: list[str]
    confidence: float = Field(ge=0, le=1)
    generated_at: str
