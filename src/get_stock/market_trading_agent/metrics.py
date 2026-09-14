from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from get_stock.market_trading_agent.catalog import TOPIC_LABELS


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _records(
    bundle: dict[str, Any],
    dataset: str,
    context: MarketAnalysisContext,
) -> list[dict[str, Any]]:
    values = bundle.get(dataset)
    if not isinstance(values, list):
        return []
    selected = [
        item
        for item in values
        if isinstance(item, dict)
        and not (
            context.period_from
            and str(item.get("trade_date") or "") < context.period_from.isoformat()
        )
        and not (
            context.period_to and str(item.get("trade_date") or "") > context.period_to.isoformat()
        )
        and not (
            context.as_of_date
            and str(item.get("trade_date") or "") > context.as_of_date.isoformat()
        )
    ]
    selected.sort(key=lambda item: str(item.get("trade_date") or ""))
    return selected[-context.lookback_sessions :]


@dataclass
class MarketAnalysisContext:
    lookback_sessions: int
    as_of_date: date | None
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
        evidence_id = f"mkt-e{len(self.evidence) + 1:04d}"
        record: dict[str, Any] = {
            "evidence_id": evidence_id,
            "evidence_type": field_name,
            "dataset": dataset,
            "field": field_name,
            "value": value,
            "unit": unit,
            "allowed_claim_types": [topic],
        }
        if period_from:
            record["period_from"] = period_from
        if period_to:
            record["period_to"] = period_to
        if derivation:
            record["derivation"] = derivation
        self.evidence.append(record)
        return evidence_id


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


def analyze_price_trend(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "market_history", context)
    closes = [(record, _number(record.get("close"))) for record in records]
    closes = [(record, value) for record, value in closes if value is not None and value > 0]
    if len(closes) < 2:
        return None
    first_record, first_close = closes[0]
    latest_record, latest_close = closes[-1]
    change = (latest_close / first_close - 1) * 100
    evidence_id = context.add_evidence(
        topic="price_trend",
        dataset="calculated",
        field_name="period_return_percent",
        value=round(change, 4),
        unit="percent",
        period_from=str(first_record.get("trade_date")),
        period_to=str(latest_record.get("trade_date")),
        derivation="latest_close / first_close - 1",
    )
    state = "rising" if change > 3 else ("falling" if change < -3 else "sideways")
    return _dimension(
        "price_trend",
        state,
        [
            _finding(
                f"区间收盘价变动{change:.2f}%",
                "positive" if change > 0 else "watch",
                evidence_id,
            )
        ],
        [str(first_record.get("trade_date")), str(latest_record.get("trade_date"))],
    )


def analyze_volatility(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "market_history", context)
    closes = [value for record in records if (value := _number(record.get("close"))) and value > 0]
    if len(closes) < 3:
        return None
    returns = [
        current / previous - 1 for previous, current in zip(closes, closes[1:], strict=False)
    ]
    annualized = statistics.pstdev(returns) * math.sqrt(250) * 100
    peak = closes[0]
    maximum_drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        maximum_drawdown = min(maximum_drawdown, close / peak - 1)
    period_from = str(records[0].get("trade_date"))
    period_to = str(records[-1].get("trade_date"))
    volatility_id = context.add_evidence(
        topic="volatility",
        dataset="calculated",
        field_name="annualized_volatility_percent",
        value=round(annualized, 4),
        unit="percent",
        period_from=period_from,
        period_to=period_to,
        derivation="population_std(daily_returns) * sqrt(250)",
    )
    drawdown_id = context.add_evidence(
        topic="volatility",
        dataset="calculated",
        field_name="maximum_drawdown_percent",
        value=round(maximum_drawdown * 100, 4),
        unit="percent",
        period_from=period_from,
        period_to=period_to,
        derivation="minimum(close / running_peak - 1)",
    )
    state = "high" if annualized >= 40 else ("moderate" if annualized >= 20 else "low")
    return _dimension(
        "volatility",
        state,
        [
            _finding(
                f"区间年化波动率为{annualized:.2f}%",
                "watch" if state == "high" else "info",
                volatility_id,
            ),
            _finding(f"区间最大回撤为{maximum_drawdown * 100:.2f}%", "watch", drawdown_id),
        ],
        [period_from, period_to],
    )


def analyze_liquidity(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "market_history", context)
    volumes = [value for record in records if (value := _number(record.get("volume"))) is not None]
    if not volumes:
        return None
    recent = volumes[-min(5, len(volumes)) :]
    average = statistics.fmean(recent)
    evidence_id = context.add_evidence(
        topic="liquidity",
        dataset="calculated",
        field_name="average_volume_recent",
        value=round(average, 4),
        unit="source_volume_unit",
        period_from=str(records[-len(recent)].get("trade_date")),
        period_to=str(records[-1].get("trade_date")),
        derivation=f"mean(last {len(recent)} trading-session volumes)",
    )
    findings = [
        _finding(
            f"最近{len(recent)}个交易日平均成交量为{average:.2f}",
            "info",
            evidence_id,
        )
    ]
    state = "observed"
    if len(volumes) >= 10:
        baseline = statistics.fmean(volumes[-10:-5])
        if baseline > 0:
            ratio = average / baseline
            ratio_id = context.add_evidence(
                topic="liquidity",
                dataset="calculated",
                field_name="recent_volume_ratio",
                value=round(ratio, 4),
                unit="ratio",
                period_from=str(records[-10].get("trade_date")),
                period_to=str(records[-1].get("trade_date")),
                derivation="last_5d_average_volume / previous_5d_average_volume",
            )
            state = "active" if ratio >= 1.5 else ("weak" if ratio <= 0.67 else "normal")
            findings.append(_finding(f"近5日成交量相对前5日为{ratio:.2f}倍", "info", ratio_id))
    return _dimension(
        "liquidity",
        state,
        findings,
        [str(records[0].get("trade_date")), str(records[-1].get("trade_date"))],
    )


def analyze_price_volume(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "market_history", context)
    valid = [
        (record, _number(record.get("close")), _number(record.get("volume"))) for record in records
    ]
    valid = [
        (record, close, volume) for record, close, volume in valid if close and volume is not None
    ]
    if len(valid) < 6:
        return None
    recent = valid[-5:]
    baseline = valid[-10:-5] if len(valid) >= 10 else valid[:-5]
    first_close = recent[0][1]
    latest_close = recent[-1][1]
    baseline_volume = statistics.fmean(item[2] for item in baseline)
    if first_close <= 0 or baseline_volume <= 0:
        return None
    price_change = (latest_close / first_close - 1) * 100
    volume_ratio = statistics.fmean(item[2] for item in recent) / baseline_volume
    evidence_id = context.add_evidence(
        topic="price_volume",
        dataset="calculated",
        field_name="price_volume_state",
        value={
            "price_change_percent": round(price_change, 4),
            "volume_ratio": round(volume_ratio, 4),
        },
        unit="mixed",
        period_from=str(valid[-len(baseline) - 5][0].get("trade_date")),
        period_to=str(recent[-1][0].get("trade_date")),
        derivation="recent price return and recent/baseline average volume",
    )
    price_state = "rise" if price_change > 0 else "fall"
    volume_state = "expand" if volume_ratio >= 1 else "contract"
    return _dimension(
        "price_volume",
        f"{price_state}_{volume_state}",
        [
            _finding(
                f"近5日价格变动{price_change:.2f}%，成交量为基准期{volume_ratio:.2f}倍",
                "info",
                evidence_id,
            )
        ],
        [str(recent[0][0].get("trade_date")), str(recent[-1][0].get("trade_date"))],
    )


def analyze_valuation(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    snapshot = bundle.get("market_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        return None
    findings: list[dict[str, Any]] = []
    for field_name, label, unit in (
        ("pe_ttm", "PE(TTM)", "ratio"),
        ("pb_ratio", "PB", "ratio"),
        ("total_market_cap", "总市值", "source_currency_unit"),
        ("float_market_cap", "流通市值", "source_currency_unit"),
    ):
        value = _number(snapshot.get(field_name))
        if value is None:
            continue
        evidence_id = context.add_evidence(
            topic="valuation",
            dataset="market_snapshot",
            field_name=field_name,
            value=value,
            unit=unit,
            period_to=str(snapshot.get("quote_time") or ""),
        )
        findings.append(_finding(f"当前{label}为{value:.2f}", "info", evidence_id))
    if not findings:
        return None
    return _dimension(
        "valuation",
        "snapshot_only",
        findings,
        [str(snapshot.get("quote_time") or "")],
    )


def analyze_margin_activity(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "margin_trading", context)
    values = [(record, _number(record.get("financing_balance"))) for record in records]
    values = [(record, value) for record, value in values if value is not None]
    if len(values) < 2 or values[0][1] == 0:
        return None
    first_record, first_value = values[0]
    latest_record, latest_value = values[-1]
    change = (latest_value / first_value - 1) * 100
    evidence_id = context.add_evidence(
        topic="margin_activity",
        dataset="calculated",
        field_name="financing_balance_change_percent",
        value=round(change, 4),
        unit="percent",
        period_from=str(first_record.get("trade_date")),
        period_to=str(latest_record.get("trade_date")),
        derivation="latest_financing_balance / first_financing_balance - 1",
    )
    state = "expanding" if change > 3 else ("contracting" if change < -3 else "stable")
    return _dimension(
        "margin_activity",
        state,
        [
            _finding(
                f"区间融资余额变动{change:.2f}%",
                "watch" if abs(change) > 10 else "info",
                evidence_id,
            )
        ],
        [str(first_record.get("trade_date")), str(latest_record.get("trade_date"))],
    )


def analyze_block_trades(
    bundle: dict[str, Any], context: MarketAnalysisContext
) -> dict[str, Any] | None:
    records = _records(bundle, "block_trades", context)
    if not records:
        if "block_trades" not in context.successful_empty_datasets:
            return None
        evidence_id = context.add_evidence(
            topic="block_trades",
            dataset="block_trades",
            field_name="record_count",
            value=0,
            unit="count",
            period_from=context.period_from.isoformat() if context.period_from else None,
            period_to=(context.period_to or context.as_of_date).isoformat()
            if context.period_to or context.as_of_date
            else None,
        )
        return _dimension(
            "block_trades",
            "no_events",
            [_finding("已成功查询，范围内未发现大宗交易", "neutral", evidence_id)],
            [],
        )
    amounts = [_number(record.get("trade_amount_10k")) for record in records]
    total_amount = sum(value for value in amounts if value is not None)
    evidence_id = context.add_evidence(
        topic="block_trades",
        dataset="block_trades",
        field_name="block_trade_summary",
        value={"count": len(records), "total_amount_10k": round(total_amount, 4)},
        unit="count_and_10k_currency",
        period_from=str(records[0].get("trade_date")),
        period_to=str(records[-1].get("trade_date")),
        derivation="count(records), sum(trade_amount_10k)",
    )
    findings = [
        _finding(
            f"区间共有{len(records)}笔大宗交易，成交额合计{total_amount:.2f}万元",
            "info",
            evidence_id,
        )
    ]
    history = {
        str(record.get("trade_date")): _number(record.get("close"))
        for record in _records(bundle, "market_history", context)
    }
    premiums = []
    for record in records:
        price = _number(record.get("trade_price"))
        close = history.get(str(record.get("trade_date")))
        if price is not None and close and close > 0:
            premiums.append((price / close - 1) * 100)
    state = "observed"
    if premiums:
        average_premium = statistics.fmean(premiums)
        premium_id = context.add_evidence(
            topic="block_trades",
            dataset="calculated",
            field_name="average_premium_discount_percent",
            value=round(average_premium, 4),
            unit="percent",
            period_from=str(records[0].get("trade_date")),
            period_to=str(records[-1].get("trade_date")),
            derivation="mean(block_trade_price / same_day_close - 1)",
        )
        state = (
            "premium" if average_premium > 0 else ("discount" if average_premium < 0 else "flat")
        )
        findings.append(
            _finding(
                f"可匹配交易的平均折溢价率为{average_premium:.2f}%",
                "info",
                premium_id,
            )
        )
    return _dimension(
        "block_trades",
        state,
        findings,
        [str(records[0].get("trade_date")), str(records[-1].get("trade_date"))],
    )


ANALYZERS: dict[
    str,
    Callable[[dict[str, Any], MarketAnalysisContext], dict[str, Any] | None],
] = {
    "price_trend": analyze_price_trend,
    "volatility": analyze_volatility,
    "liquidity": analyze_liquidity,
    "price_volume": analyze_price_volume,
    "valuation": analyze_valuation,
    "margin_activity": analyze_margin_activity,
    "block_trades": analyze_block_trades,
}
