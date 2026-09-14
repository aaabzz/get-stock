from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.financial_agent.schemas import (
    FinancialClaim,
    FinancialLLMAnalysis,
)
from get_stock.llm import create_deepseek_chat_model

FINANCIAL_SYSTEM_PROMPT = """你是财务分析专业子Agent，输出将交给综合分析Agent。
你只能使用输入FinancialFactPacket中的事实，不得补充外部知识或公司事实。
不得重新计算、修改或猜测数值。每项关键结论必须引用输入中存在的evidence_id。
结构化数据不能支持的原因或结论必须标记为not_determinable。
不得提供股票买卖建议，不得声称访问了PDF、网络或公告原文。
区分可观察事实与解释，不得把相关性表述为因果关系。"""


class FinancialReasoner(Protocol):
    def __call__(self, fact_packet: dict[str, Any]) -> FinancialLLMAnalysis: ...


def deterministic_reasoner(fact_packet: dict[str, Any]) -> FinancialLLMAnalysis:
    """Offline fallback used when the Supervisor does not inject an LLM."""
    strengths: list[FinancialClaim] = []
    risks: list[FinancialClaim] = []
    trends: list[FinancialClaim] = []
    for topic, dimension in fact_packet["dimensions"].items():
        rating = str(dimension["rating"])
        for finding in dimension["findings"]:
            claim = FinancialClaim(
                claim=finding["message"],
                assessment=(
                    "positive"
                    if finding["severity"] == "positive"
                    else ("watch" if finding["severity"] == "watch" else "neutral")
                ),
                evidence_ids=finding["evidence_ids"],
                confidence=0.95,
            )
            if finding["severity"] == "positive":
                strengths.append(claim)
            elif finding["severity"] == "watch":
                risks.append(claim)
            else:
                trends.append(claim)
        if rating == "industry_context_required":
            trends.append(
                FinancialClaim(
                    claim=f"{topic}需要金融行业口径解释",
                    assessment="not_determinable",
                    evidence_ids=[],
                    confidence=1.0,
                )
            )
    return FinancialLLMAnalysis(
        overall_assessment=fact_packet["deterministic_summary"],
        key_strengths=strengths,
        key_risks=risks,
        trend_assessments=trends,
        limitations=list(fact_packet["limitations"]),
    )


class LangChainFinancialReasoner:
    """Adapter around a LangChain chat model with provider/tool structured output."""

    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            FinancialLLMAnalysis,
            method="function_calling",
        )

    def __call__(self, fact_packet: dict[str, Any]) -> FinancialLLMAnalysis:
        response = self._structured_model.invoke(
            [
                ("system", FINANCIAL_SYSTEM_PROMPT),
                ("human", json.dumps(fact_packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, FinancialLLMAnalysis)
            else FinancialLLMAnalysis.model_validate(response)
        )


def build_deepseek_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], FinancialLLMAnalysis]:
    """Create the configured DeepSeek model without persisting or logging its API key."""
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainFinancialReasoner(model)
