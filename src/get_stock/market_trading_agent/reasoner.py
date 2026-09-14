from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.llm import create_deepseek_chat_model
from get_stock.market_trading_agent.schemas import (
    MarketTradingClaim,
    MarketTradingLLMAnalysis,
)

MARKET_TRADING_SYSTEM_PROMPT = """你是市场交易分析专业子 Agent，输出将交给综合分析 Agent。
你只能使用输入 MarketTradingFactPacket 中的事实，不得补充外部行情、新闻、行业数据或公司事件。
不得重新计算、修改或猜测输入数值。每项非弃权结论必须引用输入中存在且类型匹配的 evidence_id。
你只能描述价格、成交量、波动率、估值快照、融资融券和大宗交易的历史状态。
不得预测未来价格，不得提供目标价或买卖建议，不得把相关关系描述为因果关系。
不得将融资余额增加解释为机构看多，不得将大宗交易席位解释为真实股东身份。
没有历史估值或行业基准时不得判断高估或低估；无法支持的结论必须标记为 not_determinable。
每项 claim.topic 必须逐字复制 requested_topics 中的一个机器标识符，不得翻译、缩写或生成
别名。notable_activity、risk_signals、trend_assessments 是输出容器名称，不是 topic。
"""


class MarketTradingReasoner(Protocol):
    def __call__(self, fact_packet: dict[str, Any]) -> MarketTradingLLMAnalysis: ...


def deterministic_reasoner(fact_packet: dict[str, Any]) -> MarketTradingLLMAnalysis:
    notable_activity: list[MarketTradingClaim] = []
    risk_signals: list[MarketTradingClaim] = []
    trend_assessments: list[MarketTradingClaim] = []
    for topic, dimension in fact_packet["dimensions"].items():
        for finding in dimension["findings"]:
            severity = finding["severity"]
            claim = MarketTradingClaim(
                claim=finding["message"],
                topic=topic,
                assessment=(
                    "positive"
                    if severity == "positive"
                    else ("watch" if severity == "watch" else "neutral")
                ),
                evidence_ids=finding["evidence_ids"],
                confidence=0.95,
            )
            if severity == "watch":
                risk_signals.append(claim)
            elif topic in {"price_trend", "price_volume"}:
                trend_assessments.append(claim)
            else:
                notable_activity.append(claim)
    return MarketTradingLLMAnalysis(
        market_state_summary=fact_packet["deterministic_summary"],
        notable_activity=notable_activity,
        risk_signals=risk_signals,
        trend_assessments=trend_assessments,
        limitations=list(fact_packet["limitations"]),
    )


class LangChainMarketTradingReasoner:
    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            MarketTradingLLMAnalysis,
            method="function_calling",
        )

    def __call__(self, fact_packet: dict[str, Any]) -> MarketTradingLLMAnalysis:
        response = self._structured_model.invoke(
            [
                ("system", MARKET_TRADING_SYSTEM_PROMPT),
                ("human", json.dumps(fact_packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, MarketTradingLLMAnalysis)
            else MarketTradingLLMAnalysis.model_validate(response)
        )


def build_deepseek_market_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], MarketTradingLLMAnalysis]:
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainMarketTradingReasoner(model)
