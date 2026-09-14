from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from get_stock.shareholder_agent.catalog import TOPIC_LABELS
from get_stock.shareholder_agent.normalizers import normalize_shareholder_name

DATE_FIELDS = {
    "stock_structure": "change_date",
    "shareholder_counts": "report_date",
    "fund_holdings": "report_date",
    "top_ten_shareholders": "report_date",
    "top_ten_float_shareholders": "report_date",
    "restricted_unlocks": "unlock_date",
    "equity_pledges": "announcement_date",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass
class ShareholderAnalysisContext:
    max_periods: int
    as_of_date: date
    period_from: date | None
    period_to: date | None
    successful_empty_datasets: set[str]
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def add_evidence(
        self,
        *,
        topic: str,
        dataset: str,
        field_name: str,
        value: Any,
        unit: str,
        period_from: str | None = None,
        period_to: str | None = None,
        derivation: str | None = None,
    ) -> str:
        evidence_id = f"shr-e{len(self.evidence) + 1:04d}"
        item: dict[str, Any] = {
            "evidence_id": evidence_id,
            "evidence_type": field_name,
            "dataset": dataset,
            "field": field_name,
            "value": value,
            "unit": unit,
            "allowed_claim_types": [topic],
        }
        if period_from:
            item["period_from"] = period_from
        if period_to:
            item["period_to"] = period_to
        if derivation:
            item["derivation"] = derivation
        self.evidence.append(item)
        return evidence_id


def _records(
    bundle: dict[str, Any],
    dataset: str,
    context: ShareholderAnalysisContext,
    *,
    include_future: bool = False,
) -> list[dict[str, Any]]:
    values = bundle.get(dataset)
    if not isinstance(values, list):
        return []
    date_field = DATE_FIELDS[dataset]
    selected = []
    for record in values:
        if not isinstance(record, dict):
            continue
        raw_date = str(record.get(date_field) or "")[:10]
        if not raw_date:
            continue
        if context.period_from and raw_date < context.period_from.isoformat():
            continue
        if context.period_to and raw_date > context.period_to.isoformat():
            continue
        if not include_future and raw_date > context.as_of_date.isoformat():
            continue
        selected.append(record)
    selected.sort(key=lambda item: str(item.get(date_field) or ""))
    if dataset in {"restricted_unlocks", "equity_pledges"}:
        return selected
    periods = sorted(
        {str(item.get(date_field) or "") for item in selected},
        reverse=True,
    )[: context.max_periods]
    allowed = set(periods)
    return [item for item in selected if str(item.get(date_field) or "") in allowed]


def _dimension(
    topic: str,
    state: str,
    findings: list[dict[str, Any]],
    periods: list[str],
) -> dict[str, Any]:
    return {
        "topic": topic,
        "label": TOPIC_LABELS[topic],
        "status": "completed",
        "state": state,
        "periods": periods,
        "findings": findings,
    }


def _finding(message: str, severity: str, evidence_id: str) -> dict[str, Any]:
    return {
        "message": message,
        "severity": severity,
        "evidence_ids": [evidence_id],
    }


def analyze_ownership_structure(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "stock_structure", context)
    if not records:
        return None
    latest = records[-1]
    latest_date = str(latest.get("change_date"))
    total = _number(latest.get("total_shares_10k"))
    circulating = _number(latest.get("circulating_shares_10k"))
    restricted = _number(latest.get("restricted_shares_10k"))
    value = {
        "total_shares_10k": total,
        "circulating_shares_10k": circulating,
        "restricted_shares_10k": restricted,
        "circulating_ratio_percent": (
            round(circulating / total * 100, 4) if total and circulating is not None else None
        ),
        "restricted_ratio_percent": (
            round(restricted / total * 100, 4) if total and restricted is not None else None
        ),
    }
    if not any(item is not None for item in value.values()):
        return None
    evidence_id = context.add_evidence(
        topic="ownership_structure",
        dataset="stock_structure",
        field_name="latest_share_structure",
        value=value,
        unit="10k_shares_and_percent",
        period_to=latest_date,
        derivation="circulating_or_restricted_shares / total_shares",
    )
    findings = [_finding(f"{latest_date}股本结构已形成结构化快照", "info", evidence_id)]
    state = "snapshot_only"
    if len(records) >= 2 and total:
        previous_total = _number(records[-2].get("total_shares_10k"))
        if previous_total:
            change = (total / previous_total - 1) * 100
            change_id = context.add_evidence(
                topic="ownership_structure",
                dataset="calculated",
                field_name="total_shares_change_percent",
                value=round(change, 4),
                unit="percent",
                period_from=str(records[-2].get("change_date")),
                period_to=latest_date,
                derivation="latest_total_shares / previous_total_shares - 1",
            )
            state = "increasing" if change > 0 else ("decreasing" if change < 0 else "stable")
            findings.append(_finding(f"相邻两次股本记录总股本变动{change:.2f}%", "info", change_id))
    return _dimension(
        "ownership_structure",
        state,
        findings,
        [str(item.get("change_date")) for item in records],
    )


def analyze_shareholder_concentration(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    findings: list[dict[str, Any]] = []
    periods: set[str] = set()
    changes: list[float] = []
    for dataset, label in (
        ("top_ten_shareholders", "十大股东"),
        ("top_ten_float_shareholders", "十大流通股东"),
    ):
        records = _records(bundle, dataset, context)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[str(record.get("report_date"))].append(record)
        dates = sorted(grouped)
        if not dates:
            continue
        latest_total = sum(
            value
            for item in grouped[dates[-1]]
            if (value := _number(item.get("holding_percent"))) is not None
        )
        value: dict[str, Any] = {
            "report_date": dates[-1],
            "holding_percent_sum": round(latest_total, 4),
            "reported_holder_count": len(grouped[dates[-1]]),
        }
        if len(dates) >= 2:
            previous_total = sum(
                number
                for item in grouped[dates[-2]]
                if (number := _number(item.get("holding_percent"))) is not None
            )
            value["previous_report_date"] = dates[-2]
            value["change_percentage_points"] = round(latest_total - previous_total, 4)
            changes.append(latest_total - previous_total)
        evidence_id = context.add_evidence(
            topic="shareholder_concentration",
            dataset=dataset,
            field_name="top_ten_holding_summary",
            value=value,
            unit="percent_and_count",
            period_from=dates[-2] if len(dates) >= 2 else None,
            period_to=dates[-1],
            derivation="sum(reported holding_percent within one report date)",
        )
        periods.update(dates[-2:])
        findings.append(
            _finding(f"{dates[-1]}{label}披露持股比例合计{latest_total:.2f}%", "info", evidence_id)
        )
    if not findings:
        return None
    state = "single_period_only"
    if changes:
        average_change = sum(changes) / len(changes)
        state = (
            "increasing"
            if average_change > 0
            else ("decreasing" if average_change < 0 else "stable")
        )
    return _dimension("shareholder_concentration", state, findings, sorted(periods))


def analyze_major_holder_changes(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "top_ten_shareholders", context)
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        name = normalize_shareholder_name(str(record.get("shareholder_name") or ""))
        if name:
            grouped[str(record.get("report_date"))][name] = record
    dates = sorted(grouped)
    if len(dates) < 2:
        return None
    previous = grouped[dates[-2]]
    current = grouped[dates[-1]]
    changes: list[dict[str, Any]] = []
    for name in sorted(set(previous) | set(current)):
        if name not in previous:
            change_type = "new_entry"
        elif name not in current:
            change_type = "exit"
        else:
            before = _number(previous[name].get("shares_held_10k"))
            after = _number(current[name].get("shares_held_10k"))
            if before is None or after is None:
                continue
            change_type = (
                "increased" if after > before else ("decreased" if after < before else "unchanged")
            )
        changes.append({"shareholder_name": name, "change_type": change_type})
    if not changes:
        return None
    evidence_id = context.add_evidence(
        topic="major_holder_changes",
        dataset="calculated",
        field_name="major_holder_changes",
        value=changes,
        unit="categorical",
        period_from=dates[-2],
        period_to=dates[-1],
        derivation="match normalized shareholder names across adjacent report dates",
    )
    changed_count = sum(item["change_type"] != "unchanged" for item in changes)
    return _dimension(
        "major_holder_changes",
        "changed" if changed_count else "stable",
        [_finding(f"相邻两期十大股东中有{changed_count}项名单或持股变化", "info", evidence_id)],
        dates[-2:],
    )


def _analyze_series_change(
    bundle: dict[str, Any],
    context: ShareholderAnalysisContext,
    *,
    topic: str,
    dataset: str,
    value_fields: tuple[str, ...],
    unit: str,
) -> dict[str, Any] | None:
    records = _records(bundle, dataset, context)
    if not records:
        return None
    latest = records[-1]
    date_field = DATE_FIELDS[dataset]
    latest_date = str(latest.get(date_field))
    value = {field: _number(latest.get(field)) for field in value_fields}
    changes: dict[str, float] = {}
    if len(records) >= 2:
        previous = records[-2]
        for field in value_fields:
            before = _number(previous.get(field))
            after = value[field]
            if before and after is not None:
                changes[f"{field}_change_percent"] = round((after / before - 1) * 100, 4)
    evidence_id = context.add_evidence(
        topic=topic,
        dataset=dataset,
        field_name=f"{topic}_summary",
        value={**value, **changes},
        unit=unit,
        period_from=str(records[-2].get(date_field)) if len(records) >= 2 else None,
        period_to=latest_date,
        derivation="latest / previous - 1 for comparable numeric fields",
    )
    primary_change = next(iter(changes.values()), None)
    state = (
        "single_period_only"
        if primary_change is None
        else (
            "increasing"
            if primary_change > 0
            else ("decreasing" if primary_change < 0 else "stable")
        )
    )
    return _dimension(
        topic,
        state,
        [_finding(f"{latest_date}{TOPIC_LABELS[topic]}形成结构化记录", "info", evidence_id)],
        [str(item.get(date_field)) for item in records],
    )


def analyze_shareholder_count(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    return _analyze_series_change(
        bundle,
        context,
        topic="shareholder_count",
        dataset="shareholder_counts",
        value_fields=("shareholder_count",),
        unit="count_and_percent",
    )


def analyze_fund_holdings(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    return _analyze_series_change(
        bundle,
        context,
        topic="fund_holdings",
        dataset="fund_holdings",
        value_fields=("fund_count", "total_shares_held"),
        unit="count_and_source_share_unit",
    )


def analyze_restricted_unlocks(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "restricted_unlocks", context, include_future=True)
    if not records:
        if "restricted_unlocks" not in context.successful_empty_datasets:
            return None
        evidence_id = context.add_evidence(
            topic="restricted_unlocks",
            dataset="restricted_unlocks",
            field_name="record_count",
            value=0,
            unit="count",
            period_to=context.as_of_date.isoformat(),
        )
        return _dimension(
            "restricted_unlocks",
            "no_events_returned",
            [_finding("接口查询成功，范围内未返回限售解禁记录", "neutral", evidence_id)],
            [],
        )
    future = [
        item
        for item in records
        if str(item.get("unlock_date") or "")[:10] > context.as_of_date.isoformat()
    ]
    future_shares = sum(
        value for item in future if (value := _number(item.get("unlocked_shares_10k"))) is not None
    )
    evidence_id = context.add_evidence(
        topic="restricted_unlocks",
        dataset="restricted_unlocks",
        field_name="unlock_event_summary",
        value={
            "record_count": len(records),
            "future_record_count": len(future),
            "future_unlocked_shares_10k": round(future_shares, 4),
        },
        unit="count_and_10k_shares",
        period_from=str(records[0].get("unlock_date")),
        period_to=str(records[-1].get("unlock_date")),
    )
    return _dimension(
        "restricted_unlocks",
        "future_events" if future else "historical_only",
        [
            _finding(
                f"查询范围内有{len(records)}条解禁记录，其中未来{len(future)}条",
                "watch" if future else "info",
                evidence_id,
            )
        ],
        [str(item.get("unlock_date")) for item in records],
    )


def analyze_equity_pledges(
    bundle: dict[str, Any], context: ShareholderAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "equity_pledges", context)
    if not records:
        if "equity_pledges" not in context.successful_empty_datasets:
            return None
        evidence_id = context.add_evidence(
            topic="equity_pledges",
            dataset="equity_pledges",
            field_name="record_count",
            value=0,
            unit="count",
            period_to=context.as_of_date.isoformat(),
        )
        return _dimension(
            "equity_pledges",
            "no_events_returned",
            [_finding("接口查询成功，范围内未返回股权质押记录", "neutral", evidence_id)],
            [],
        )
    evidence_id = context.add_evidence(
        topic="equity_pledges",
        dataset="equity_pledges",
        field_name="pledge_event_summary",
        value={
            "record_count": len(records),
            "pledgors": sorted(
                {str(item.get("pledgor")) for item in records if item.get("pledgor")}
            ),
        },
        unit="event_count",
        period_from=str(records[0].get("announcement_date")),
        period_to=str(records[-1].get("announcement_date")),
        derivation="event count only; not a reconstructed current pledge balance",
    )
    return _dimension(
        "equity_pledges",
        "events_observed",
        [_finding(f"查询范围内有{len(records)}条股权质押或解除记录", "watch", evidence_id)],
        [str(item.get("announcement_date")) for item in records],
    )


ANALYZERS: dict[
    str,
    Callable[[dict[str, Any], ShareholderAnalysisContext], dict[str, Any] | None],
] = {
    "ownership_structure": analyze_ownership_structure,
    "shareholder_concentration": analyze_shareholder_concentration,
    "major_holder_changes": analyze_major_holder_changes,
    "shareholder_count": analyze_shareholder_count,
    "fund_holdings": analyze_fund_holdings,
    "restricted_unlocks": analyze_restricted_unlocks,
    "equity_pledges": analyze_equity_pledges,
}
