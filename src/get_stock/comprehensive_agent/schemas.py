from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SpecialistAgentName: TypeAlias = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
SynthesisTopic: TypeAlias = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]


class ComprehensiveTaskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consume_specialist_results_only: bool = True
    allow_local_source_data: bool = False
    allow_pdf: bool = False
    allow_network: bool = False
    allow_crawler: bool = False
    allow_agent_dispatch: bool = False
    allow_recalculation: bool = False
    allow_investment_advice: bool = False
    write_markdown: bool = True
    require_llm: bool = True

    def assert_supported(self) -> None:
        if not self.consume_specialist_results_only or not self.write_markdown:
            raise ValueError(
                "comprehensive agent requires specialist-only input and Markdown output"
            )
        if any(
            (
                self.allow_local_source_data,
                self.allow_pdf,
                self.allow_network,
                self.allow_crawler,
                self.allow_agent_dispatch,
                self.allow_recalculation,
                self.allow_investment_advice,
            )
        ):
            raise ValueError("comprehensive agent constraints exceed its synthesis boundary")


class ComprehensiveRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=100)
    topic: SynthesisTopic
    question: str = Field(min_length=1)
    required_agents: tuple[SpecialistAgentName, ...] = ()


class SpecialistResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: SpecialistAgentName
    result: dict[str, Any]


class ComprehensiveAnalysisTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=100)
    parent_task_id: str | None = None
    stock_code: str = Field(pattern=r"^\d{6}$")
    question: str = Field(min_length=1)
    requirements: tuple[ComprehensiveRequirement, ...] = Field(min_length=1)
    expected_agents: tuple[SpecialistAgentName, ...] = Field(min_length=1)
    agent_results: tuple[SpecialistResultEnvelope, ...]
    constraints: ComprehensiveTaskConstraints = Field(default_factory=ComprehensiveTaskConstraints)

    @field_validator("requirements")
    @classmethod
    def unique_requirements(
        cls, value: tuple[ComprehensiveRequirement, ...]
    ) -> tuple[ComprehensiveRequirement, ...]:
        identifiers = [item.requirement_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("requirement_id values must be unique")
        return value

    @field_validator("expected_agents")
    @classmethod
    def unique_expected_agents(
        cls, value: tuple[SpecialistAgentName, ...]
    ) -> tuple[SpecialistAgentName, ...]:
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_results(self) -> ComprehensiveAnalysisTask:
        names = [item.agent for item in self.agent_results]
        if len(names) != len(set(names)):
            raise ValueError("agent_results may contain at most one result per agent")
        unexpected = set(names) - set(self.expected_agents)
        if unexpected:
            raise ValueError(f"received unexpected agent results: {sorted(unexpected)}")
        for requirement in self.requirements:
            if set(requirement.required_agents) - set(self.expected_agents):
                raise ValueError(
                    f"requirement {requirement.requirement_id} references an unexpected agent"
                )
        return self


class EvidenceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_agent: SpecialistAgentName
    source_evidence_id: str
    payload: dict[str, Any]


class FindingEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    source_agent: SpecialistAgentName
    source_task_id: str
    topics: list[SynthesisTopic]
    category: Literal["strength", "risk", "trend", "activity", "claim"]
    claim: str
    assessment: Literal["positive", "neutral", "watch", "risk", "not_determinable"]
    report_periods: list[str]
    confidence: float = Field(ge=0, le=1)
    source_evidence_ids: list[str]
    limitations: list[str] = Field(default_factory=list)


class RequirementCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    topic: SynthesisTopic
    status: Literal["answered", "partially_answered", "unanswered", "conflicted"]
    supporting_finding_ids: list[str]
    missing_agents: list[SpecialistAgentName] = Field(default_factory=list)
    reason: str | None = None


class SynthesisConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_id: str
    conflict_type: Literal["quantitative_value_mismatch"]
    topic: SynthesisTopic
    finding_ids: list[str]
    evidence_ids: list[str]
    description: str
    resolution: str


class SynthesisClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    topic: SynthesisTopic
    assessment: Literal[
        "positive",
        "positive_with_limitations",
        "neutral",
        "watch",
        "risk",
        "conflicted",
        "not_determinable",
    ]
    finding_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class ComprehensiveLLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    key_strengths: list[SynthesisClaim] = Field(default_factory=list)
    key_risks: list[SynthesisClaim] = Field(default_factory=list)
    trend_assessments: list[SynthesisClaim] = Field(default_factory=list)
    other_findings: list[SynthesisClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AnalysisArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_json: str
    markdown: str
    state: str


class ComprehensiveAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    agent: Literal["comprehensive_analysis"] = "comprehensive_analysis"
    agent_version: str
    task_id: str
    parent_task_id: str | None = None
    status: Literal["completed", "partial", "insufficient_data"]
    llm_used: bool
    stock_code: str
    stock_name: str | None = None
    industry_name: str | None = None
    question: str
    agent_statuses: dict[str, str]
    agent_summaries: dict[str, str]
    requirement_coverage: list[RequirementCoverage]
    summary: str
    key_strengths: list[SynthesisClaim]
    key_risks: list[SynthesisClaim]
    trend_assessments: list[SynthesisClaim]
    other_findings: list[SynthesisClaim]
    conflicts: list[SynthesisConflict]
    findings: list[FindingEnvelope]
    evidence: list[EvidenceEnvelope]
    missing_data: list[dict[str, Any]]
    limitations: list[str]
    confidence: float = Field(ge=0, le=1)
    generated_at: str
    artifacts: AnalysisArtifacts
