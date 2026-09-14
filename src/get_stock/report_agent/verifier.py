from get_stock.report_agent.catalog import DENIED_SECTION_TYPES
from get_stock.report_agent.schemas import (
    ReportAnalysisTask,
    ReportClaim,
    ReportClaimValidationIssue,
    ReportLLMAnalysis,
)


class ReportClaimValidationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def verify_report_claim(
    claim: ReportClaim,
    evidence: list[dict],
    task: ReportAnalysisTask,
) -> None:
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    requested_topics = {item.topic for item in task.requirements}
    authorized_reports = {item.announcement_id for item in task.reports}
    if claim.topic not in requested_topics:
        raise ReportClaimValidationError(
            "unrequested_topic", f"LLM returned an unrequested report topic: {claim.topic}"
        )
    unknown = set(claim.evidence_ids) - set(evidence_by_id)
    if unknown:
        raise ReportClaimValidationError(
            "unknown_evidence",
            f"LLM claim references unknown evidence IDs: {sorted(unknown)}",
        )
    if claim.assessment != "not_determinable" and not claim.evidence_ids:
        raise ReportClaimValidationError(
            "missing_evidence", "supported LLM claims must contain at least one evidence_id"
        )
    for evidence_id in claim.evidence_ids:
        item = evidence_by_id[evidence_id]
        if item["announcement_id"] not in authorized_reports:
            raise ReportClaimValidationError(
                "unauthorized_report",
                f"evidence {evidence_id} comes from an unauthorized report",
            )
        if item["section_type"] in DENIED_SECTION_TYPES:
            raise ReportClaimValidationError(
                "denied_section",
                f"evidence {evidence_id} comes from a denied report section",
            )
        if claim.topic not in item.get("allowed_claim_types", []):
            raise ReportClaimValidationError(
                "evidence_topic_mismatch",
                f"evidence {evidence_id} cannot support claim topic {claim.topic}",
            )


def isolate_invalid_report_claims(
    analysis: ReportLLMAnalysis,
    evidence: list[dict],
    task: ReportAnalysisTask,
) -> tuple[list[ReportClaim], list[ReportClaimValidationIssue]]:
    valid_claims: list[ReportClaim] = []
    issues: list[ReportClaimValidationIssue] = []
    for index, claim in enumerate(analysis.claims):
        try:
            verify_report_claim(claim, evidence, task)
        except ReportClaimValidationError as exc:
            issues.append(
                ReportClaimValidationIssue(
                    claim_index=index,
                    topic=claim.topic,
                    evidence_ids=list(claim.evidence_ids),
                    reason_code=exc.reason_code,
                    reason=str(exc),
                )
            )
        else:
            valid_claims.append(claim)
    return valid_claims, issues


def verify_report_analysis(
    analysis: ReportLLMAnalysis,
    evidence: list[dict],
    task: ReportAnalysisTask,
) -> None:
    for claim in analysis.claims:
        verify_report_claim(claim, evidence, task)
