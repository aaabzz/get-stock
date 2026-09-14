from __future__ import annotations

from datetime import date
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from get_stock.report_agent.catalog import REPORT_TOPIC_CATALOG

ReportTopic: TypeAlias = Literal[
    "business_overview",
    "industry_position",
    "market_share_disclosure",
    "competitive_advantage",
    "technology_advantage",
    "research_and_development",
    "growth_drivers",
    "management_explanation",
    "business_risks",
    "customer_supplier_dependency",
    "development_strategy",
]


class ReportTaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks_only: bool = True
    exclude_financial_report_section: bool = True
    allow_pdf: bool = False
    allow_pages: bool = False
    allow_sections: bool = False
    allow_network: bool = False
    allow_crawler: bool = False
    allow_financial_table_analysis: bool = False
    allow_investment_advice: bool = False
    require_llm: bool = True

    def assert_supported(self) -> None:
        if not self.chunks_only or not self.exclude_financial_report_section:
            raise ValueError(
                "report agent requires chunks-only access with financial sections excluded"
            )
        if any(
            (
                self.allow_pdf,
                self.allow_pages,
                self.allow_sections,
                self.allow_network,
                self.allow_crawler,
                self.allow_financial_table_analysis,
                self.allow_investment_advice,
            )
        ):
            raise ValueError(
                "report agent constraints exceed its first-version capability boundary"
            )


class ReportReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    announcement_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=100)
    report_period: date | None = None
    report_type: str | None = None
    document_role: Literal["full_report"] = "full_report"


class ReportRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1)
    topic: ReportTopic
    question: str = Field(min_length=1)
    preferred_headings: tuple[str, ...] = ()


class ReportRetrievalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=8, ge=1, le=20)
    adjacent_window: int = Field(default=1, ge=0, le=2)
    max_context_characters: int = Field(default=16000, ge=1000, le=50000)


class ReportAnalysisTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    parent_task_id: str | None = None
    mode: Literal["supplement", "direct"] = "supplement"
    stock_code: str = Field(pattern=r"^\d{6}$")
    question: str = Field(min_length=1)
    requirements: tuple[ReportRequirement, ...] = Field(min_length=1)
    reports: tuple[ReportReference, ...] = Field(min_length=1)
    existing_findings: tuple[dict[str, Any], ...] = ()
    retrieval: ReportRetrievalOptions = Field(default_factory=ReportRetrievalOptions)
    constraints: ReportTaskConstraints = Field(default_factory=ReportTaskConstraints)

    @field_validator("requirements")
    @classmethod
    def unique_requirements(
        cls, value: tuple[ReportRequirement, ...]
    ) -> tuple[ReportRequirement, ...]:
        identifiers = [item.requirement_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("requirement_id values must be unique")
        return value

    @field_validator("reports")
    @classmethod
    def unique_reports(cls, value: tuple[ReportReference, ...]) -> tuple[ReportReference, ...]:
        identifiers = [item.announcement_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("announcement_id values must be unique")
        return value

    @model_validator(mode="after")
    def validate_catalog_alignment(self) -> ReportAnalysisTask:
        unknown = {item.topic for item in self.requirements} - set(REPORT_TOPIC_CATALOG)
        if unknown:
            raise ValueError(f"unsupported report topics: {sorted(unknown)}")
        return self


class MissingReportData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    topic: ReportTopic
    announcement_id: str | None = None
    reason_code: Literal[
        "chunks_missing",
        "chunks_invalid",
        "heading_not_found",
        "relevant_content_not_found",
        "context_budget_exceeded",
    ]
    reason: str
    blocking: bool = True
    recoverable: bool = True
    recommended_action: str | None = None


class ReportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    topic: ReportTopic
    assessment: Literal["positive", "neutral", "watch", "risk", "not_determinable"]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class ReportLLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    claims: list[ReportClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ReportEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    announcement_id: str
    report_period: str | None = None
    report_type: str | None = None
    chunk_id: str
    section_id: str
    section_type: str
    heading: str
    start_page: int
    end_page: int
    text_excerpt: str
    relevance_score: float
    matched_keywords: list[str]
    selection_reasons: list[str]
    allowed_claim_types: list[ReportTopic]


class ReportAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    agent: Literal["financial_report_analysis"] = "financial_report_analysis"
    agent_version: str
    task_id: str
    parent_task_id: str | None = None
    mode: Literal["supplement", "direct"]
    status: Literal["completed", "partial", "insufficient_data"]
    data_scope: Literal["report_chunks_only"] = "report_chunks_only"
    llm_used: bool
    stock_code: str
    analysis_scope: dict[str, Any]
    accessed_reports: list[str]
    scanned_chunk_count: int
    selected_chunk_count: int
    summary: str
    claims: list[ReportClaim]
    evidence: list[ReportEvidence]
    missing_data: list[MissingReportData]
    limitations: list[str]
    confidence: float = Field(ge=0, le=1)
    generated_at: str
