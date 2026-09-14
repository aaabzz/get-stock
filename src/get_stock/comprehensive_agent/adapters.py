from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from get_stock.agent_plugins import AgentTypeRegistry, AgentTypeSpec, build_builtin_agent_types
from get_stock.comprehensive_agent.schemas import (
    ComprehensiveAnalysisTask,
    EvidenceEnvelope,
    FindingEnvelope,
    SynthesisTopic,
)


class SpecialistResultError(RuntimeError):
    pass


def adapt_specialist_results(
    task: ComprehensiveAnalysisTask,
    agent_types: AgentTypeRegistry | None = None,
) -> dict[str, Any]:
    agent_types = agent_types or build_builtin_agent_types()
    findings: list[FindingEnvelope] = []
    evidence: list[EvidenceEnvelope] = []
    missing_data: list[dict[str, Any]] = []
    limitations: list[str] = []
    summaries: dict[str, str] = {}
    statuses: dict[str, str] = {agent: "not_run" for agent in task.expected_agents}
    stock_name: str | None = None
    industry_name: str | None = None

    for envelope in task.agent_results:
        try:
            spec = agent_types.get(envelope.agent)
        except ValueError as exc:
            raise SpecialistResultError(str(exc)) from exc
        model_class = spec.result_model
        try:
            result = model_class.model_validate(envelope.result)
        except ValidationError as exc:
            raise SpecialistResultError(f"invalid {envelope.agent} result: {exc}") from exc
        if result.agent != envelope.agent:
            raise SpecialistResultError(
                f"result agent mismatch: expected {envelope.agent}, got {result.agent}"
            )
        if result.stock_code != task.stock_code:
            raise SpecialistResultError(
                f"{envelope.agent} result belongs to stock {result.stock_code}"
            )

        payload = result.model_dump(mode="json")
        statuses[envelope.agent] = result.status
        summaries[envelope.agent] = result.summary
        stock_name = stock_name or payload.get("stock_name")
        industry_name = industry_name or payload.get("industry_name")
        limitations.extend(str(item) for item in payload.get("limitations", []))
        for item in payload.get("missing_data", []):
            normalized_missing = {"source_agent": envelope.agent, **item}
            if item.get("topic") in spec.topic_map:
                normalized_missing["synthesis_topic"] = spec.topic_map[item["topic"]]
            missing_data.append(normalized_missing)

        evidence_by_original_id: dict[str, dict[str, Any]] = {}
        for item in payload.get("evidence", []):
            original_id = str(item.get("evidence_id") or "")
            if not original_id:
                raise SpecialistResultError(f"{envelope.agent} contains evidence without an ID")
            if original_id in evidence_by_original_id:
                raise SpecialistResultError(
                    f"{envelope.agent} contains duplicate evidence ID: {original_id}"
                )
            evidence_by_original_id[original_id] = item
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=f"{envelope.agent}:{original_id}",
                    source_agent=envelope.agent,
                    source_evidence_id=original_id,
                    payload={key: value for key, value in item.items() if key != "evidence_id"},
                )
            )

        financial_evidence_topics = (
            _financial_evidence_topics(payload, spec)
            if spec.topic_strategy == "financial_dimensions"
            else {}
        )
        mapped_scope_topics = _mapped_scope_topics(spec, payload)
        finding_index = 0
        for field_name, category in spec.claim_fields:
            for claim in payload.get(field_name, []):
                original_ids = [str(value) for value in claim.get("evidence_ids", [])]
                unknown = set(original_ids) - set(evidence_by_original_id)
                if unknown:
                    raise SpecialistResultError(
                        f"{envelope.agent} claim references unknown evidence IDs: {sorted(unknown)}"
                    )
                topics = _claim_topics(
                    spec,
                    claim,
                    original_ids,
                    financial_evidence_topics,
                    mapped_scope_topics,
                )
                if not topics:
                    continue
                finding_index += 1
                periods = sorted(
                    {
                        period
                        for evidence_id in original_ids
                        if (period := _evidence_period(evidence_by_original_id[evidence_id]))
                    }
                )
                findings.append(
                    FindingEnvelope(
                        finding_id=f"{envelope.agent}:f{finding_index:04d}",
                        source_agent=envelope.agent,
                        source_task_id=result.task_id,
                        topics=topics,
                        category=category,
                        claim=str(claim["claim"]),
                        assessment=claim["assessment"],
                        report_periods=periods,
                        confidence=float(claim["confidence"]),
                        source_evidence_ids=[
                            f"{envelope.agent}:{evidence_id}" for evidence_id in original_ids
                        ],
                        limitations=list(payload.get("limitations", [])),
                    )
                )

    return {
        "findings": findings,
        "evidence": evidence,
        "missing_data": missing_data,
        "limitations": list(dict.fromkeys(limitations)),
        "summaries": summaries,
        "agent_statuses": statuses,
        "stock_name": stock_name,
        "industry_name": industry_name,
    }


def _financial_evidence_topics(payload: dict[str, Any], spec: AgentTypeSpec) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for source_topic, dimension in payload.get("dimensions", {}).items():
        mapped = spec.topic_map.get(source_topic)
        if not mapped:
            continue
        for finding in dimension.get("findings", []):
            for evidence_id in finding.get("evidence_ids", []):
                result[str(evidence_id)].add(mapped)
    return result


def _mapped_scope_topics(spec: AgentTypeSpec, payload: dict[str, Any]) -> list[SynthesisTopic]:
    mapping = spec.topic_map
    source_topics = payload.get("analysis_scope", {}).get("topics", [])
    return [mapping[topic] for topic in source_topics if topic in mapping]


def _claim_topics(
    spec: AgentTypeSpec,
    claim: dict[str, Any],
    evidence_ids: list[str],
    financial_evidence_topics: dict[str, set[str]],
    mapped_scope_topics: list[SynthesisTopic],
) -> list[SynthesisTopic]:
    mapping = spec.topic_map
    if spec.topic_strategy != "financial_dimensions":
        source_topic = claim.get("topic")
        return [mapping[source_topic]] if source_topic in mapping else []
    topics = {
        topic for evidence_id in evidence_ids for topic in financial_evidence_topics[evidence_id]
    }
    if (
        not topics
        and claim.get("assessment") == "not_determinable"
        and len(mapped_scope_topics) == 1
    ):
        topics.update(mapped_scope_topics)
    return sorted(topics)


def _evidence_period(evidence: dict[str, Any]) -> str | None:
    for key in ("report_period", "trade_date", "change_date", "quote_time"):
        if value := evidence.get(key):
            return str(value)
    return None
