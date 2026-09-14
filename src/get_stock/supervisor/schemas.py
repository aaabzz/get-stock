from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from get_stock.comprehensive_agent.schemas import SpecialistAgentName, SynthesisTopic


class TimeIntent(BaseModel):
    """Semantic time request; it never grants access to data or executable tools."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal[
        "unspecified",
        "latest",
        "recent_years",
        "recent_periods",
        "recent_sessions",
        "absolute_range",
    ] = "unspecified"
    raw_expression: str | None = Field(default=None, max_length=100)
    count: int | None = Field(default=None, ge=1, le=500)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_mode_fields(self) -> TimeIntent:
        if self.mode in {"recent_years", "recent_periods", "recent_sessions"}:
            if self.count is None:
                raise ValueError(f"count is required for time mode {self.mode}")
        elif self.count is not None:
            raise ValueError(f"count is not valid for time mode {self.mode}")
        if self.mode == "absolute_range":
            if self.start_date is None and self.end_date is None:
                raise ValueError("absolute_range requires start_date or end_date")
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError(f"dates are not valid for time mode {self.mode}")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date cannot be later than end_date")
        return self


class DocumentIntent(BaseModel):
    """Document needs inferred from the question, without selecting concrete files."""

    model_config = ConfigDict(extra="forbid")

    needs_full_report: bool = False
    needs_announcements: bool = False
    explicitly_requested: bool = False


class SupervisorTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=70)
    question: str = Field(min_length=1)
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    as_of_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    auto_crawl: bool = False
    auto_documents: bool = False
    allow_report_fallback: bool = True
    require_llm: bool = True
    heading_mode: Literal["rules", "auto", "llm"] = "auto"
    max_documents: int = Field(default=3, ge=1, le=6)
    max_analysis_rounds: int = Field(default=2, ge=1, le=2)
    max_crawl_rounds: int = Field(default=1, ge=0, le=1)
    max_document_rounds: int = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def validate_period(self) -> SupervisorTask:
        if self.period_from and self.period_to and self.period_from > self.period_to:
            raise ValueError("period_from cannot be later than period_to")
        if self.auto_documents and self.heading_mode == "llm" and not self.require_llm:
            raise ValueError("heading_mode='llm' requires LLM to be enabled")
        return self


class SupervisorRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=100)
    topic: SynthesisTopic
    question: str = Field(min_length=1)
    required_agents: tuple[SpecialistAgentName, ...] = Field(min_length=1)
    priority: Literal["required", "optional"] = "required"


class SupervisorPlanDraft(BaseModel):
    """Schema-constrained semantic fields that the planning LLM may return."""

    model_config = ConfigDict(extra="forbid")

    topics: tuple[SynthesisTopic, ...] = Field(min_length=1, max_length=32)
    financial_years: int = Field(default=3, ge=1, le=10)
    shareholder_periods: int = Field(default=4, ge=1, le=20)
    market_sessions: int = Field(default=60, ge=2, le=500)
    report_type: Literal["annual", "semiannual", "first_quarter", "third_quarter"] = "annual"
    time_intent: TimeIntent = Field(default_factory=TimeIntent)
    document_intent: DocumentIntent = Field(default_factory=DocumentIntent)

    @field_validator("topics")
    @classmethod
    def unique_topics(cls, value: tuple[SynthesisTopic, ...]) -> tuple[SynthesisTopic, ...]:
        return tuple(dict.fromkeys(value))


class QuestionUnderstanding(BaseModel):
    """Validated semantic interpretation produced before analysis planning."""

    model_config = ConfigDict(extra="forbid")

    stock_code: str = Field(pattern=r"^\d{6}$")
    topics: tuple[SynthesisTopic, ...] = Field(min_length=1, max_length=32)
    financial_years: int = Field(default=3, ge=1, le=10)
    shareholder_periods: int = Field(default=4, ge=1, le=20)
    market_sessions: int = Field(default=60, ge=2, le=500)
    report_type: Literal["annual", "semiannual", "first_quarter", "third_quarter"] = "annual"
    time_intent: TimeIntent = Field(default_factory=TimeIntent)
    document_intent: DocumentIntent = Field(default_factory=DocumentIntent)
    interpreter_mode: Literal["deterministic", "deepseek", "deterministic_fallback"]
    llm_used: bool = False
    warnings: tuple[str, ...] = ()

    @field_validator("topics")
    @classmethod
    def unique_topics(cls, value: tuple[SynthesisTopic, ...]) -> tuple[SynthesisTopic, ...]:
        return tuple(dict.fromkeys(value))


class SupervisorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_code: str = Field(pattern=r"^\d{6}$")
    requirements: tuple[SupervisorRequirement, ...] = Field(min_length=1)
    expected_agents: tuple[SpecialistAgentName, ...] = Field(min_length=1)
    financial_years: int = Field(default=3, ge=1, le=10)
    shareholder_periods: int = Field(default=4, ge=1, le=20)
    market_sessions: int = Field(default=60, ge=2, le=500)
    report_type: Literal["annual", "semiannual", "first_quarter", "third_quarter"] = "annual"
    time_intent: TimeIntent = Field(default_factory=TimeIntent)
    document_intent: DocumentIntent = Field(default_factory=DocumentIntent)
    planner_mode: Literal["deterministic", "deepseek", "deterministic_fallback"] = "deterministic"
    planning_llm_used: bool = False
    warnings: tuple[str, ...] = ()

    @field_validator("expected_agents")
    @classmethod
    def unique_agents(
        cls, value: tuple[SpecialistAgentName, ...]
    ) -> tuple[SpecialistAgentName, ...]:
        return tuple(dict.fromkeys(value))


class DatasetAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: SpecialistAgentName
    dataset: str
    path: str
    exists: bool
    record_count: int | None = None


class ResolvedTimeScope(BaseModel):
    """Deterministically resolved report and disclosure dates."""

    model_config = ConfigDict(extra="forbid")

    as_of_date: date
    report_period_from: date | None = None
    report_period_to: date | None = None
    disclosure_search_from: date | None = None
    disclosure_search_to: date | None = None
    resolution_source: Literal["explicit", "relative", "default", "not_required"]
    warnings: tuple[str, ...] = ()


class AgentExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: SpecialistAgentName
    task_id: str
    status: Literal["completed", "partial", "insufficient_data", "failed", "not_run"]
    error: str | None = None


class SupervisorArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str
    understanding: str
    resolved_dates: str
    plan: str
    cache_snapshot: str
    acquisition: str
    document_acquisition: str
    specialist_results: str
    result: str
    state: str
    comprehensive_result: str | None = None
    markdown: str | None = None


class SupervisorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    supervisor_version: str
    task_id: str
    status: Literal["completed", "partial", "insufficient_data", "failed"]
    stock_code: str
    question: str
    llm_requested: bool
    expected_agents: list[SpecialistAgentName]
    executions: list[AgentExecution]
    acquisition: dict[str, Any]
    document_acquisition: dict[str, Any]
    missing_data: list[dict[str, Any]]
    recommended_actions: list[dict[str, Any]]
    comprehensive_result: dict[str, Any] | None
    artifacts: SupervisorArtifacts
    generated_at: str
