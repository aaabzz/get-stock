from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.llm import create_deepseek_chat_model
from get_stock.shareholder_agent.schemas import ShareholderClaim, ShareholderLLMAnalysis

SHAREHOLDER_SYSTEM_PROMPT = """你是股东与股权结构分析专业子 Agent，输出将交给综合分析 Agent。
你只能使用输入 ShareholderFactPacket 中的事实，不得补充股东背景、新闻、公告原文、
实际控制关系或一致行动关系。不得重新计算、修改或猜测数值。
每项非弃权结论必须引用输入中存在且主题匹配的 evidence_id。
不得把股东人数下降解释为筹码集中或机构吸筹，不得把基金数量增加解释为长期看好，
不得把解禁事件解释为必然减持，不得根据质押事件推断实时质押余额。
不得预测股价或提供投资建议；无法支持的结论必须标记为 not_determinable。
每项 claim.topic 必须逐字复制 requested_topics 中的一个机器标识符，不得翻译、缩写或生成
别名。concentration_assessments、notable_holder_changes、risk_events、trend_assessments 是
输出容器名称，不是 topic。
"""


class ShareholderReasoner(Protocol):
    def __call__(self, fact_packet: dict[str, Any]) -> ShareholderLLMAnalysis: ...


def deterministic_reasoner(fact_packet: dict[str, Any]) -> ShareholderLLMAnalysis:
    concentration: list[ShareholderClaim] = []
    holder_changes: list[ShareholderClaim] = []
    risk_events: list[ShareholderClaim] = []
    trends: list[ShareholderClaim] = []
    for topic, dimension in fact_packet["dimensions"].items():
        for finding in dimension["findings"]:
            severity = finding["severity"]
            claim = ShareholderClaim(
                claim=finding["message"],
                topic=topic,
                assessment=(
                    "watch"
                    if severity == "watch"
                    else ("positive" if severity == "positive" else "neutral")
                ),
                evidence_ids=finding["evidence_ids"],
                confidence=0.95,
            )
            if topic == "shareholder_concentration":
                concentration.append(claim)
            elif topic == "major_holder_changes":
                holder_changes.append(claim)
            elif topic in {"restricted_unlocks", "equity_pledges"}:
                risk_events.append(claim)
            else:
                trends.append(claim)
    return ShareholderLLMAnalysis(
        ownership_summary=fact_packet["deterministic_summary"],
        concentration_assessments=concentration,
        notable_holder_changes=holder_changes,
        risk_events=risk_events,
        trend_assessments=trends,
        limitations=list(fact_packet["limitations"]),
    )


class LangChainShareholderReasoner:
    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            ShareholderLLMAnalysis,
            method="function_calling",
        )

    def __call__(self, fact_packet: dict[str, Any]) -> ShareholderLLMAnalysis:
        response = self._structured_model.invoke(
            [
                ("system", SHAREHOLDER_SYSTEM_PROMPT),
                ("human", json.dumps(fact_packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, ShareholderLLMAnalysis)
            else ShareholderLLMAnalysis.model_validate(response)
        )


def build_deepseek_shareholder_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], ShareholderLLMAnalysis]:
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainShareholderReasoner(model)
