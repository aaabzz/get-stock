from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.comprehensive_agent.schemas import (
    ComprehensiveLLMAnalysis,
    SynthesisClaim,
)
from get_stock.llm import create_deepseek_chat_model

COMPREHENSIVE_SYSTEM_PROMPT = """你是最终综合分析 Agent。你只能使用输入中的专业 Agent
Finding、Evidence、覆盖度、冲突和限制，不得补充外部知识，不得访问或声称访问原始股票数据、
PDF、网络或爬虫。每项非弃权结论必须引用存在且主题匹配的 finding_id；不得重新计算、修改或
覆盖专业 Agent 数值。结构化专业 Agent 的定量结论优先于财报中的叙述，财报中的行业地位、
市场份额和优势必须明确注明“公司在财报中披露”且未经外部验证。不得把相关性描述为因果，
不得预测股价，不得提供买卖建议或目标价。存在冲突或证据不足时必须保留限制，并使用
conflicted 或 not_determinable。"""


class ComprehensiveReasoner(Protocol):
    def __call__(self, synthesis_packet: dict[str, Any]) -> ComprehensiveLLMAnalysis: ...


def deterministic_reasoner(synthesis_packet: dict[str, Any]) -> ComprehensiveLLMAnalysis:
    strengths: list[SynthesisClaim] = []
    risks: list[SynthesisClaim] = []
    trends: list[SynthesisClaim] = []
    others: list[SynthesisClaim] = []
    requested = set(synthesis_packet["requested_topics"])
    for finding in synthesis_packet["findings"]:
        topics = [topic for topic in finding["topics"] if topic in requested]
        if not topics:
            continue
        assessment = finding["assessment"]
        claim = SynthesisClaim(
            claim=finding["claim"],
            topic=topics[0],
            assessment=assessment,
            finding_ids=[finding["finding_id"]] if finding["source_evidence_ids"] else [],
            confidence=finding["confidence"],
        )
        if finding["category"] == "strength" or assessment == "positive":
            strengths.append(claim)
        elif finding["category"] == "risk" or assessment in {"watch", "risk"}:
            risks.append(claim)
        elif finding["category"] == "trend":
            trends.append(claim)
        else:
            others.append(claim)
    answered = sum(
        item["status"] == "answered" for item in synthesis_packet["requirement_coverage"]
    )
    total = len(synthesis_packet["requirement_coverage"])
    return ComprehensiveLLMAnalysis(
        summary=f"已汇总专业Agent结果，{total}项分析要求中有{answered}项得到完整证据支持。",
        key_strengths=strengths,
        key_risks=risks,
        trend_assessments=trends,
        other_findings=others,
        limitations=list(synthesis_packet["limitations"]),
    )


class LangChainComprehensiveReasoner:
    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            ComprehensiveLLMAnalysis,
            method="function_calling",
        )

    def __call__(self, synthesis_packet: dict[str, Any]) -> ComprehensiveLLMAnalysis:
        response = self._structured_model.invoke(
            [
                ("system", COMPREHENSIVE_SYSTEM_PROMPT),
                ("human", json.dumps(synthesis_packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, ComprehensiveLLMAnalysis)
            else ComprehensiveLLMAnalysis.model_validate(response)
        )


def build_deepseek_comprehensive_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], ComprehensiveLLMAnalysis]:
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainComprehensiveReasoner(model)
