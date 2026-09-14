from __future__ import annotations

from get_stock.comprehensive_agent.schemas import (
    ComprehensiveAnalysisTask,
    FindingEnvelope,
    RequirementCoverage,
    SynthesisConflict,
)


def assess_coverage(
    task: ComprehensiveAnalysisTask,
    findings: list[FindingEnvelope],
    conflicts: list[SynthesisConflict],
    agent_statuses: dict[str, str],
) -> list[RequirementCoverage]:
    conflicted_topics = {item.topic for item in conflicts}
    coverage: list[RequirementCoverage] = []
    for requirement in task.requirements:
        matching = [item for item in findings if requirement.topic in item.topics]
        supported = [
            item
            for item in matching
            if item.assessment != "not_determinable" and item.source_evidence_ids
        ]
        missing_agents = [
            agent
            for agent in requirement.required_agents
            if agent_statuses.get(agent) in {None, "not_run", "insufficient_data"}
        ]
        if requirement.topic in conflicted_topics:
            status = "conflicted"
            reason = "不同专业结果中存在尚未解决的同口径数值冲突"
        elif supported and not missing_agents:
            status = "answered"
            reason = None
        elif matching or supported:
            status = "partially_answered"
            reason = "仅有部分证据，或必要专业Agent未提供有效结果"
        else:
            status = "unanswered"
            reason = "没有专业Agent提供可验证的相关Finding"
        coverage.append(
            RequirementCoverage(
                requirement_id=requirement.requirement_id,
                topic=requirement.topic,
                status=status,
                supporting_finding_ids=[item.finding_id for item in supported],
                missing_agents=missing_agents,
                reason=reason,
            )
        )
    return coverage


def calculate_confidence(
    coverage: list[RequirementCoverage],
    findings: list[FindingEnvelope],
    conflicts: list[SynthesisConflict],
    source_weights: dict[str, float] | None = None,
) -> float:
    if not coverage:
        return 0.0
    by_id = {item.finding_id: item for item in findings}
    source_weights = source_weights or {}
    requirement_scores: list[float] = []
    for item in coverage:
        scores = [
            by_id[finding_id].confidence * source_weights.get(by_id[finding_id].source_agent, 0.75)
            for finding_id in item.supporting_finding_ids
            if finding_id in by_id
        ]
        requirement_scores.append(max(scores, default=0.0))
    conflict_penalty = 0.8 if conflicts else 1.0
    return round(0.9 * sum(requirement_scores) / len(coverage) * conflict_penalty, 2)
