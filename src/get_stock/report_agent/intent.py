from __future__ import annotations

import re
from dataclasses import dataclass

from get_stock.report_agent.catalog import COMPREHENSIVE_TOPICS
from get_stock.report_agent.schemas import ReportTopic

TOPIC_KEYWORDS: dict[ReportTopic, tuple[str, ...]] = {
    "business_overview": ("主营业务", "业务概况", "业务模式"),
    "industry_position": ("行业地位", "市场地位", "行业排名", "竞争格局"),
    "market_share_disclosure": ("市场份额", "市占率", "市场占有率"),
    "competitive_advantage": ("竞争优势", "核心竞争力", "个股优势"),
    "technology_advantage": ("技术优势", "核心技术", "技术代际", "科技能力"),
    "research_and_development": ("研发", "研究开发"),
    "growth_drivers": ("增长动力", "增长驱动", "增长原因"),
    "management_explanation": ("管理层解释", "下降原因", "变化原因", "业绩原因"),
    "business_risks": ("经营风险", "风险因素", "主要风险"),
    "customer_supplier_dependency": ("客户依赖", "供应商", "客户集中"),
    "development_strategy": ("发展战略", "发展规划", "未来计划"),
}


@dataclass(frozen=True)
class ReportIntent:
    stock_code: str
    topics: tuple[ReportTopic, ...]
    question: str


def parse_report_intent(question: str, *, stock_code: str | None = None) -> ReportIntent:
    normalized = question.strip().lower()
    resolved_code = stock_code or _extract_stock_code(normalized)
    if not resolved_code:
        raise ValueError("a six-digit stock code is required")
    topics = tuple(
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    )
    if "综合" in normalized or "全面" in normalized:
        topics = COMPREHENSIVE_TOPICS
    if not topics:
        raise ValueError("question does not contain a supported financial-report topic")
    return ReportIntent(
        stock_code=resolved_code,
        topics=tuple(dict.fromkeys(topics)),
        question=question,
    )


def _extract_stock_code(question: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", question)
    return match.group(1) if match else None
