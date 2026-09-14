from __future__ import annotations

from get_stock.financial_agent.schemas import FinancialLLMAnalysis


def verify_llm_analysis(
    analysis: FinancialLLMAnalysis,
    evidence: list[dict],
) -> None:
    """Reject LLM claims that cite nonexistent evidence or omit evidence without abstaining."""
    valid_ids = {item["evidence_id"] for item in evidence}
    for claim in analysis.key_strengths + analysis.key_risks + analysis.trend_assessments:
        unknown = set(claim.evidence_ids) - valid_ids
        if unknown:
            raise ValueError(f"LLM claim references unknown evidence IDs: {sorted(unknown)}")
        if claim.assessment != "not_determinable" and not claim.evidence_ids:
            raise ValueError("supported LLM claims must contain at least one evidence_id")
