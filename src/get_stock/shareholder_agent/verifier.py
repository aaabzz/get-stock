from get_stock.shareholder_agent.schemas import ShareholderAnalysisTask, ShareholderLLMAnalysis


def verify_shareholder_analysis(
    analysis: ShareholderLLMAnalysis,
    evidence: list[dict],
    task: ShareholderAnalysisTask,
) -> None:
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    requested_topics = set(task.topics)
    claims = (
        analysis.concentration_assessments
        + analysis.notable_holder_changes
        + analysis.risk_events
        + analysis.trend_assessments
    )
    for claim in claims:
        if claim.topic not in requested_topics:
            raise ValueError(f"LLM returned an unrequested shareholder topic: {claim.topic}")
        unknown = set(claim.evidence_ids) - set(evidence_by_id)
        if unknown:
            raise ValueError(f"LLM claim references unknown evidence IDs: {sorted(unknown)}")
        if claim.assessment != "not_determinable" and not claim.evidence_ids:
            raise ValueError("supported LLM claims must contain at least one evidence_id")
        for evidence_id in claim.evidence_ids:
            allowed = evidence_by_id[evidence_id].get("allowed_claim_types", [])
            if claim.topic not in allowed:
                raise ValueError(f"evidence {evidence_id} cannot support claim topic {claim.topic}")
