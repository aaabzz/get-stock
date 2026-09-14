from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SectionType = Literal[
    "company_profile",
    "financial_indicators",
    "business_overview",
    "management_discussion",
    "corporate_governance",
    "environment_social",
    "important_matters",
    "shareholders",
    "bonds",
    "financial_report",
    "unclassified",
]


class HeadingClassification(BaseModel):
    """Schema-constrained classification for one source-backed heading candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^candidate-\d{4}$")
    section_type: SectionType
    normalized_heading: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)


class HeadingLLMAnalysis(BaseModel):
    """Bounded LLM output; page numbers and source text are intentionally excluded."""

    model_config = ConfigDict(extra="forbid")

    classifications: tuple[HeadingClassification, ...] = Field(max_length=64)

    @field_validator("classifications")
    @classmethod
    def unique_candidates(
        cls, value: tuple[HeadingClassification, ...]
    ) -> tuple[HeadingClassification, ...]:
        identifiers = [item.candidate_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("heading candidate IDs must be unique")
        return value
