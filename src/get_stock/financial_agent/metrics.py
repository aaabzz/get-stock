from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from get_stock.financial_agent.catalog import TOPIC_LABELS

INCOME_ALIASES = {
    "revenue": ("营业收入", "营业总收入"),
    "operating_profit": ("营业利润",),
    "net_profit": ("归属母公司净利润", "归属于母公司股东的净利润", "净利润"),
}
BALANCE_ALIASES = {
    "total_assets": ("总资产", "资产总计"),
    "total_liabilities": ("总负债", "负债合计"),
    "total_equity": ("所有者权益", "股东权益合计", "所有者权益合计"),
}
CASH_FLOW_ALIASES = {
    "operating_cash_flow": ("经营活动产生的现金流量净额",),
    "investing_cash_flow": ("投资活动产生的现金流量净额",),
    "financing_cash_flow": ("筹资活动产生的现金流量净额",),
}


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
    report_type: str,
    years: int,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[dict[str, Any]]:
    values = bundle.get(dataset)
    if not isinstance(values, list):
        return []
    selected = [
        record
        for record in values
        if isinstance(record, dict)
        and record.get("report_type") == report_type
        and not (period_from and str(record.get("report_date") or "") < period_from)
        and not (period_to and str(record.get("report_date") or "") > period_to)
    ]
    return sorted(selected, key=lambda record: str(record.get("report_date") or ""), reverse=True)[
        :years
    ]


def _item(record: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str, float] | None:
    items = record.get("items")
    if not isinstance(items, dict):
        return None
    for alias in aliases:
        value = _number(items.get(alias))
        if value is not None:
            return alias, value
    return None


@dataclass
class AnalysisContext:
    report_type: str
    years: int
    period_from: str | None
    period_to: str | None
    is_financial_company: bool
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def add_evidence(
        self,
        *,
        dataset: str,
        period: str | None,
        field_name: str,
        value: Any,
        unit: str,
        derivation: str | None = None,
    ) -> str:
        evidence_id = f"e{len(self.evidence) + 1:04d}"
        evidence = {
            "evidence_id": evidence_id,
            "dataset": dataset,
            "report_period": period,
            "field": field_name,
            "value": value,
            "unit": unit,
        }
        if derivation:
            evidence["derivation"] = derivation
        self.evidence.append(evidence)
        return evidence_id


def _dimension(
    topic: str, rating: str, findings: list[dict[str, Any]], periods: list[str]
) -> dict[str, Any]:
    return {
        "topic": topic,
        "label": TOPIC_LABELS[topic],
        "status": "completed",
        "rating": rating,
        "periods": periods,
        "findings": findings,
    }


def analyze_growth(bundle: dict[str, Any], context: AnalysisContext) -> dict[str, Any] | None:
    records = _records(
        bundle,
        "financial_indicators",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    if not records:
        return None
    findings: list[dict[str, Any]] = []
    latest = records[0]
    period = str(latest.get("report_date") or "")
    values: dict[str, float] = {}
    for field_name, label in (
        ("revenue_growth_percent", "营业收入同比"),
        ("net_profit_growth_percent", "净利润同比"),
        ("total_assets_growth_percent", "总资产同比"),
        ("net_assets_growth_percent", "净资产同比"),
    ):
        value = _number(latest.get(field_name))
        if value is None:
            continue
        values[field_name] = value
        evidence_id = context.add_evidence(
            dataset="financial_indicators",
            period=period,
            field_name=field_name,
            value=value,
            unit="percent",
        )
        findings.append(
            {
                "message": f"{period} {label}为{value:.2f}%",
                "severity": "positive" if value > 0 else "watch",
                "evidence_ids": [evidence_id],
            }
        )
    core = [values.get("revenue_growth_percent"), values.get("net_profit_growth_percent")]
    comparable = [value for value in core if value is not None]
    if comparable and all(value > 0 for value in comparable):
        rating = "improving"
    elif comparable and all(value < 0 for value in comparable):
        rating = "weak"
    else:
        rating = "mixed" if comparable else "unavailable"
    return _dimension(
        "growth", rating, findings, [str(record.get("report_date")) for record in records]
    )


def analyze_profitability(
    bundle: dict[str, Any], context: AnalysisContext
) -> dict[str, Any] | None:
    records = _records(
        bundle,
        "financial_indicators",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    if not records:
        return None
    latest = records[0]
    period = str(latest.get("report_date") or "")
    findings: list[dict[str, Any]] = []
    values: list[float] = []
    for field_name, label in (
        ("weighted_roe_percent", "加权ROE"),
        ("return_on_total_assets_percent", "总资产收益率"),
        ("gross_margin_percent", "毛利率"),
        ("net_profit_margin_percent", "净利率"),
        ("operating_profit_margin_percent", "营业利润率"),
    ):
        value = _number(latest.get(field_name))
        if value is None:
            continue
        values.append(value)
        evidence_id = context.add_evidence(
            dataset="financial_indicators",
            period=period,
            field_name=field_name,
            value=value,
            unit="percent",
        )
        findings.append(
            {
                "message": f"{period} {label}为{value:.2f}%",
                "severity": "positive" if value > 0 else "watch",
                "evidence_ids": [evidence_id],
            }
        )
    if values and all(value < 0 for value in values):
        rating = "weak"
    elif values and _number(latest.get("weighted_roe_percent")) is not None:
        rating = "positive" if float(latest["weighted_roe_percent"]) >= 10 else "stable"
    else:
        rating = "mixed" if values else "unavailable"
    return _dimension(
        "profitability",
        rating,
        findings,
        [str(record.get("report_date")) for record in records],
    )


def analyze_earnings_quality(
    bundle: dict[str, Any], context: AnalysisContext
) -> dict[str, Any] | None:
    income = _records(
        bundle,
        "income_statements",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    cash = _records(
        bundle,
        "cash_flow_statements",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    cash_by_period = {str(record.get("report_date")): record for record in cash}
    findings: list[dict[str, Any]] = []
    ratios: list[float] = []
    periods: list[str] = []
    for income_record in income:
        period = str(income_record.get("report_date") or "")
        cash_record = cash_by_period.get(period)
        net_profit = _item(income_record, INCOME_ALIASES["net_profit"])
        operating_cash = (
            _item(cash_record, CASH_FLOW_ALIASES["operating_cash_flow"]) if cash_record else None
        )
        if not net_profit or not operating_cash or net_profit[1] == 0:
            continue
        ratio = operating_cash[1] / net_profit[1]
        ratios.append(ratio)
        periods.append(period)
        evidence_id = context.add_evidence(
            dataset="calculated",
            period=period,
            field_name="operating_cash_flow_to_net_profit",
            value=round(ratio, 4),
            unit="ratio",
            derivation=(
                f"cash_flow_statements.items.{operating_cash[0]} / "
                f"income_statements.items.{net_profit[0]} (same source unit)"
            ),
        )
        findings.append(
            {
                "message": f"{period} 经营现金流净额/归母净利润为{ratio:.2f}",
                "severity": "positive" if ratio >= 1 else ("info" if ratio >= 0.8 else "watch"),
                "evidence_ids": [evidence_id],
            }
        )
    if not ratios:
        return None
    latest = ratios[0]
    if latest >= 1:
        rating = "positive"
    elif latest >= 0.8:
        rating = "stable"
    elif latest >= 0:
        rating = "watch"
    else:
        rating = "weak"
    return _dimension("earnings_quality", rating, findings, periods)


def analyze_balance_sheet(
    bundle: dict[str, Any], context: AnalysisContext
) -> dict[str, Any] | None:
    records = _records(
        bundle,
        "balance_sheets",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    if not records:
        return None
    findings: list[dict[str, Any]] = []
    periods: list[str] = []
    latest_ratio: float | None = None
    for record in records:
        period = str(record.get("report_date") or "")
        assets = _item(record, BALANCE_ALIASES["total_assets"])
        liabilities = _item(record, BALANCE_ALIASES["total_liabilities"])
        if not assets or not liabilities or assets[1] == 0:
            continue
        ratio = liabilities[1] / assets[1] * 100
        if latest_ratio is None:
            latest_ratio = ratio
        periods.append(period)
        evidence_id = context.add_evidence(
            dataset="calculated",
            period=period,
            field_name="debt_ratio_percent",
            value=round(ratio, 4),
            unit="percent",
            derivation=(
                f"balance_sheets.items.{liabilities[0]} / balance_sheets.items.{assets[0]}"
            ),
        )
        findings.append(
            {
                "message": f"{period} 按资产负债表计算的资产负债率为{ratio:.2f}%",
                "severity": (
                    "info" if context.is_financial_company else ("watch" if ratio > 70 else "info")
                ),
                "evidence_ids": [evidence_id],
            }
        )
    if not findings:
        return None
    rating = (
        "industry_context_required"
        if context.is_financial_company
        else ("watch" if latest_ratio is not None and latest_ratio > 70 else "stable")
    )
    return _dimension("balance_sheet", rating, findings, periods)


def analyze_solvency(bundle: dict[str, Any], context: AnalysisContext) -> dict[str, Any] | None:
    records = _records(
        bundle,
        "financial_indicators",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    if not records:
        return None
    latest = records[0]
    period = str(latest.get("report_date") or "")
    findings: list[dict[str, Any]] = []
    values: dict[str, float] = {}
    for field_name, label, unit in (
        ("current_ratio", "流动比率", "ratio"),
        ("quick_ratio", "速动比率", "ratio"),
        ("debt_ratio_percent", "资产负债率", "percent"),
    ):
        value = _number(latest.get(field_name))
        if value is None:
            continue
        values[field_name] = value
        evidence_id = context.add_evidence(
            dataset="financial_indicators",
            period=period,
            field_name=field_name,
            value=value,
            unit=unit,
        )
        findings.append(
            {
                "message": f"{period} {label}为{value:.3f}{'%' if unit == 'percent' else ''}",
                "severity": "info",
                "evidence_ids": [evidence_id],
            }
        )
    if not findings:
        return None
    if context.is_financial_company:
        rating = "industry_context_required"
    elif (values.get("current_ratio") is not None and values["current_ratio"] < 1) or values.get(
        "debt_ratio_percent", 0
    ) > 70:
        rating = "watch"
    else:
        rating = "stable"
    return _dimension(
        "solvency", rating, findings, [str(record.get("report_date")) for record in records]
    )


def analyze_operating_efficiency(
    bundle: dict[str, Any], context: AnalysisContext
) -> dict[str, Any] | None:
    records = _records(
        bundle,
        "financial_indicators",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    if not records:
        return None
    latest = records[0]
    period = str(latest.get("report_date") or "")
    findings: list[dict[str, Any]] = []
    for field_name, label in (
        ("receivables_turnover", "应收账款周转率"),
        ("inventory_turnover", "存货周转率"),
        ("current_assets_turnover", "流动资产周转率"),
        ("fixed_assets_turnover", "固定资产周转率"),
        ("total_assets_turnover", "总资产周转率"),
    ):
        value = _number(latest.get(field_name))
        if value is None:
            continue
        evidence_id = context.add_evidence(
            dataset="financial_indicators",
            period=period,
            field_name=field_name,
            value=value,
            unit="times",
        )
        findings.append(
            {
                "message": f"{period} {label}为{value:.3f}次",
                "severity": "info",
                "evidence_ids": [evidence_id],
            }
        )
    if not findings:
        return None
    rating = "industry_context_required" if context.is_financial_company else "observed"
    return _dimension(
        "operating_efficiency",
        rating,
        findings,
        [str(record.get("report_date")) for record in records],
    )


def analyze_cash_flow(bundle: dict[str, Any], context: AnalysisContext) -> dict[str, Any] | None:
    records = _records(
        bundle,
        "cash_flow_statements",
        context.report_type,
        context.years,
        context.period_from,
        context.period_to,
    )
    if not records:
        return None
    latest = records[0]
    period = str(latest.get("report_date") or "")
    findings: list[dict[str, Any]] = []
    values: dict[str, float] = {}
    for key, label in (
        ("operating_cash_flow", "经营活动现金流量净额"),
        ("investing_cash_flow", "投资活动现金流量净额"),
        ("financing_cash_flow", "筹资活动现金流量净额"),
    ):
        item = _item(latest, CASH_FLOW_ALIASES[key])
        if not item:
            continue
        values[key] = item[1]
        evidence_id = context.add_evidence(
            dataset="cash_flow_statements",
            period=period,
            field_name=f"items.{item[0]}",
            value=item[1],
            unit="source_statement_unit",
        )
        findings.append(
            {
                "message": f"{period} {label}为{item[1]:.2f}（原报表单位）",
                "severity": "positive" if key == "operating_cash_flow" and item[1] > 0 else "info",
                "evidence_ids": [evidence_id],
            }
        )
    if not findings:
        return None
    operating = values.get("operating_cash_flow")
    rating = "positive" if operating is not None and operating > 0 else "watch"
    return _dimension(
        "cash_flow", rating, findings, [str(record.get("report_date")) for record in records]
    )


def analyze_dividend(bundle: dict[str, Any], context: AnalysisContext) -> dict[str, Any] | None:
    records = bundle.get("dividends")
    if not isinstance(records, list) or not records:
        return None
    selected = records[: context.years]
    findings: list[dict[str, Any]] = []
    for record in selected:
        period = str(record.get("report_period") or "")
        plan = str(record.get("distribution_plan") or "")
        if not plan:
            continue
        evidence_id = context.add_evidence(
            dataset="dividends",
            period=period,
            field_name="distribution_plan",
            value=plan,
            unit="raw_plan",
        )
        findings.append(
            {
                "message": f"{period} 分配方案：{plan}",
                "severity": "info",
                "evidence_ids": [evidence_id],
            }
        )
    return _dimension(
        "dividend",
        "observed" if findings else "unavailable",
        findings,
        [str(record.get("report_period") or "") for record in selected],
    )


def analyze_capital_structure(
    bundle: dict[str, Any], context: AnalysisContext
) -> dict[str, Any] | None:
    records = bundle.get("stock_structure")
    if not isinstance(records, list) or not records:
        return None
    selected = sorted(
        records, key=lambda record: str(record.get("change_date") or ""), reverse=True
    )[: context.years]
    findings: list[dict[str, Any]] = []
    for record in selected:
        period = str(record.get("change_date") or "")
        evidence_ids: list[str] = []
        for field_name in ("total_shares_10k", "circulating_shares_10k", "restricted_shares_10k"):
            value = _number(record.get(field_name))
            if value is not None:
                evidence_ids.append(
                    context.add_evidence(
                        dataset="stock_structure",
                        period=period,
                        field_name=field_name,
                        value=value,
                        unit="10k_shares",
                    )
                )
        if evidence_ids:
            findings.append(
                {
                    "message": f"{period} 股本结构记录已纳入分析",
                    "severity": "info",
                    "evidence_ids": evidence_ids,
                }
            )
    return _dimension(
        "capital_structure",
        "observed" if findings else "unavailable",
        findings,
        [str(record.get("change_date") or "") for record in selected],
    )


ANALYZERS: dict[str, Callable[[dict[str, Any], AnalysisContext], dict[str, Any] | None]] = {
    "growth": analyze_growth,
    "profitability": analyze_profitability,
    "earnings_quality": analyze_earnings_quality,
    "balance_sheet": analyze_balance_sheet,
    "solvency": analyze_solvency,
    "operating_efficiency": analyze_operating_efficiency,
    "cash_flow": analyze_cash_flow,
    "dividend": analyze_dividend,
    "capital_structure": analyze_capital_structure,
}
