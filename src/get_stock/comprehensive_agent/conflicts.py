from __future__ import annotations

from collections import defaultdict
from typing import Any

from get_stock.comprehensive_agent.schemas import (
    EvidenceEnvelope,
    FindingEnvelope,
    SynthesisConflict,
)


def detect_conflicts(
    findings: list[FindingEnvelope], evidence: list[EvidenceEnvelope]
) -> list[SynthesisConflict]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    grouped: dict[tuple[str, str, str, str], list[tuple[FindingEnvelope, str, Any]]] = defaultdict(
        list
    )
    for finding in findings:
        for evidence_id in finding.source_evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                continue
            payload = item.payload
            value = payload.get("value")
            field = str(payload.get("field") or "")
            period = str(payload.get("report_period") or payload.get("trade_date") or "")
            unit = str(payload.get("unit") or "")
            if not field or not period or not isinstance(value, int | float | str):
                continue
            for topic in finding.topics:
                grouped[(topic, period, field, unit)].append((finding, evidence_id, value))

    conflicts: list[SynthesisConflict] = []
    for (topic, period, field, unit), records in grouped.items():
        sources = {record[0].source_agent for record in records}
        values = {json_safe_value(record[2]) for record in records}
        if len(sources) < 2 or len(values) < 2:
            continue
        finding_ids = list(dict.fromkeys(record[0].finding_id for record in records))
        evidence_ids = list(dict.fromkeys(record[1] for record in records))
        conflicts.append(
            SynthesisConflict(
                conflict_id=f"conflict-{len(conflicts) + 1:04d}",
                conflict_type="quantitative_value_mismatch",
                topic=topic,
                finding_ids=finding_ids,
                evidence_ids=evidence_ids,
                description=(
                    f"{period}的{field}在不同专业结果中存在不一致值（单位：{unit or '未知'}）"
                ),
                resolution="不自动覆盖；保留结构化来源并要求Supervisor核对期间、口径和单位",
            )
        )
    return conflicts


def json_safe_value(value: Any) -> str:
    return repr(value)
