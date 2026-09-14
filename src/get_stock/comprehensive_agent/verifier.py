from __future__ import annotations

from get_stock.comprehensive_agent.schemas import (
    ComprehensiveAnalysisTask,
    ComprehensiveLLMAnalysis,
    FindingEnvelope,
)

FORBIDDEN_ADVICE_PHRASES = (
    "建议买入",
    "建议卖出",
    "应当买入",
    "应当卖出",
    "目标价",
)


def verify_comprehensive_analysis(
    analysis: ComprehensiveLLMAnalysis,
    findings: list[FindingEnvelope],
    task: ComprehensiveAnalysisTask,
) -> None:
    findings_by_id = {item.finding_id: item for item in findings}
    requested_topics = {item.topic for item in task.requirements}
    claims = (
        analysis.key_strengths
        + analysis.key_risks
        + analysis.trend_assessments
        + analysis.other_findings
    )
    texts = [analysis.summary, *(claim.claim for claim in claims)]
    if any(phrase in text for phrase in FORBIDDEN_ADVICE_PHRASES for text in texts):
        raise ValueError("comprehensive analysis contains forbidden investment advice")
    for claim in claims:
        if claim.topic not in requested_topics:
            raise ValueError(f"LLM returned an unrequested synthesis topic: {claim.topic}")
        unknown = set(claim.finding_ids) - set(findings_by_id)
        if unknown:
            raise ValueError(f"LLM claim references unknown finding IDs: {sorted(unknown)}")
        if claim.assessment != "not_determinable" and not claim.finding_ids:
            raise ValueError("supported synthesis claims must contain at least one finding_id")
        for finding_id in claim.finding_ids:
            finding = findings_by_id[finding_id]
            if claim.topic not in finding.topics:
                raise ValueError(
                    f"finding {finding_id} cannot support synthesis topic {claim.topic}"
                )
            if claim.assessment != "not_determinable" and not finding.source_evidence_ids:
                raise ValueError(f"finding {finding_id} has no specialist evidence lineage")
