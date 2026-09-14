from __future__ import annotations

from typing import Any

from get_stock.comprehensive_agent.catalog import SOURCE_LABELS, TOPIC_LABELS
from get_stock.comprehensive_agent.schemas import ComprehensiveAnalysisResult, SynthesisClaim

STATUS_LABELS = {
    "completed": "已完成",
    "partial": "部分完成",
    "insufficient_data": "数据不足",
    "answered": "已回答",
    "partially_answered": "部分回答",
    "unanswered": "未回答",
    "conflicted": "存在冲突",
    "not_run": "未调用",
}


def render_markdown(
    result: ComprehensiveAnalysisResult,
    *,
    source_labels: dict[str, str] | None = None,
) -> str:
    source_labels = {**SOURCE_LABELS, **(source_labels or {})}
    lines = [
        f"# {result.stock_code} {result.stock_name or ''}综合分析报告".replace("  ", " "),
        "",
        f"- 分析时间：{result.generated_at}",
        f"- 任务状态：{STATUS_LABELS[result.status]}",
        f"- 所属行业：{result.industry_name or '未知'}",
        f"- 综合置信度：{result.confidence:.2f}",
        "- 本报告仅基于已提供的专业 Agent 结果，不构成投资建议。",
        "",
        "## 一、综合结论",
        "",
        result.summary,
        "",
        "## 二、问题覆盖情况",
        "",
        "| 分析要求 | 状态 | 支持Finding | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in result.requirement_coverage:
        lines.append(
            "| "
            + " | ".join(
                (
                    _escape(TOPIC_LABELS.get(item.topic, item.topic)),
                    STATUS_LABELS[item.status],
                    _escape(", ".join(item.supporting_finding_ids) or "—"),
                    _escape(item.reason or "—"),
                )
            )
            + " |"
        )

    _claim_section(lines, "三、主要优势", result.key_strengths)
    _claim_section(lines, "四、主要风险", result.key_risks)
    _claim_section(lines, "五、趋势判断", result.trend_assessments)
    _claim_section(lines, "六、其他发现", result.other_findings)

    lines.extend(["", "## 七、专业Agent摘要", ""])
    if result.agent_summaries:
        for agent, summary in result.agent_summaries.items():
            lines.extend([f"### {source_labels.get(agent, agent)}", "", summary, ""])
    else:
        lines.extend(["没有可用的专业 Agent 摘要。", ""])

    lines.extend(["## 八、冲突与不确定性", ""])
    if result.conflicts:
        for conflict in result.conflicts:
            lines.append(f"- {conflict.description}；处理原则：{conflict.resolution}")
    else:
        lines.append("未检测到可机械确认的同口径数值冲突。")

    lines.extend(["", "## 九、缺失数据", ""])
    if result.missing_data:
        for item in result.missing_data:
            source = source_labels.get(str(item.get("source_agent") or ""), "上游任务")
            reason = item.get("reason") or item.get("reason_code") or "未说明原因"
            lines.append(f"- {source}：{reason}")
    else:
        lines.append("没有已报告的数据缺失项。")

    lines.extend(
        [
            "",
            "## 十、Finding与证据链",
            "",
            "| Finding编号 | 来源Agent | 主题 | 底层证据 |",
            "| --- | --- | --- | --- |",
        ]
    )
    if result.findings:
        for item in result.findings:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _escape(item.finding_id),
                        _escape(source_labels.get(item.source_agent, item.source_agent)),
                        _escape("、".join(TOPIC_LABELS.get(topic, topic) for topic in item.topics)),
                        _escape(", ".join(item.source_evidence_ids) or "—"),
                    )
                )
                + " |"
            )
    else:
        lines.append("| — | — | — | — |")

    lines.extend(
        [
            "",
            "## 十一、证据索引",
            "",
            "| 证据编号 | 来源Agent | 数据集或报告 | 期间 | 字段或页码 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if result.evidence:
        for item in result.evidence:
            source, period, location = _evidence_location(item.payload)
            lines.append(
                "| "
                + " | ".join(
                    (
                        _escape(item.evidence_id),
                        _escape(source_labels.get(item.source_agent, item.source_agent)),
                        _escape(source),
                        _escape(period),
                        _escape(location),
                    )
                )
                + " |"
            )
    else:
        lines.append("| — | — | — | — | — |")

    lines.extend(["", "## 十二、分析限制", ""])
    for limitation in result.limitations:
        lines.append(f"- {limitation}")
    if not result.limitations:
        lines.append("- 当前没有额外限制说明。")
    lines.extend(["", "---", "", "本报告不构成投资建议。", ""])
    return "\n".join(lines)


def _claim_section(lines: list[str], title: str, claims: list[SynthesisClaim]) -> None:
    lines.extend(["", f"## {title}", ""])
    if not claims:
        lines.append("当前没有得到证据支持的相关结论。")
        return
    for index, claim in enumerate(claims, start=1):
        references = ", ".join(claim.finding_ids) or "无直接Finding"
        lines.extend(
            [
                f"### {index}. {TOPIC_LABELS.get(claim.topic, claim.topic)}",
                "",
                claim.claim,
                "",
                f"证据链：`{references}`；置信度：{claim.confidence:.2f}",
                "",
            ]
        )


def _evidence_location(payload: dict[str, Any]) -> tuple[str, str, str]:
    source = str(payload.get("dataset") or payload.get("announcement_id") or "—")
    period = str(
        payload.get("report_period")
        or payload.get("trade_date")
        or payload.get("quote_time")
        or "—"
    )
    if payload.get("chunk_id"):
        location = (
            f"{payload['chunk_id']}，第{payload.get('start_page', '?')}～"
            f"{payload.get('end_page', '?')}页"
        )
    else:
        location = str(payload.get("field") or "—")
    return source, period, location


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
