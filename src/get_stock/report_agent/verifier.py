from get_stock.report_agent.catalog import DENIED_SECTION_TYPES
from get_stock.report_agent.schemas import ReportAnalysisTask, ReportLLMAnalysis


def verify_report_analysis(
    analysis: ReportLLMAnalysis,
    evidence: list[dict],
    task: ReportAnalysisTask,
) -> None:
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    requested_topics = {item.topic for item in task.requirements}
    authorized_reports = {item.announcement_id for item in task.reports}
    for claim in analysis.claims:
        if claim.topic not in requested_topics:
            raise ValueError(f"LLM returned an unrequested report topic: {claim.topic}")
        unknown = set(claim.evidence_ids) - set(evidence_by_id)
        if unknown:
            raise ValueError(f"LLM claim references unknown evidence IDs: {sorted(unknown)}")
        if claim.assessment != "not_determinable" and not claim.evidence_ids:
            raise ValueError("supported LLM claims must contain at least one evidence_id")
        for evidence_id in claim.evidence_ids:
            item = evidence_by_id[evidence_id]
            if item["announcement_id"] not in authorized_reports:
                raise ValueError(f"evidence {evidence_id} comes from an unauthorized report")
            if item["section_type"] in DENIED_SECTION_TYPES:
                raise ValueError(f"evidence {evidence_id} comes from a denied report section")
            if claim.topic not in item.get("allowed_claim_types", []):
                raise ValueError(f"evidence {evidence_id} cannot support claim topic {claim.topic}")
