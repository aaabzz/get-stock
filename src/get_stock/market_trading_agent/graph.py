from __future__ import annotations

from typing import Any, TypedDict

from get_stock.market_trading_agent.agent import MarketTradingAnalysisAgent
from get_stock.market_trading_agent.schemas import MarketTradingLLMAnalysis


class MarketTradingGraphState(TypedDict, total=False):
    task: dict[str, Any]
    prepared: dict[str, Any]
    llm_analysis: MarketTradingLLMAnalysis
    llm_used: bool
    result: dict[str, Any]


def build_market_trading_graph(agent: MarketTradingAnalysisAgent):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph dependencies are missing; install with pip install -e .[agent]"
        ) from exc

    def prepare_node(state: MarketTradingGraphState) -> MarketTradingGraphState:
        return {"prepared": agent.prepare(state["task"])}

    def reason_node(state: MarketTradingGraphState) -> MarketTradingGraphState:
        analysis, llm_used = agent.reason(state["prepared"])
        return {"llm_analysis": analysis, "llm_used": llm_used}

    def finalize_node(state: MarketTradingGraphState) -> MarketTradingGraphState:
        result = agent.finalize(
            state["prepared"],
            state["llm_analysis"],
            llm_used=state["llm_used"],
        )
        return {"result": result.model_dump(mode="json")}

    builder = StateGraph(MarketTradingGraphState)
    builder.add_node("prepare_market_facts", prepare_node)
    builder.add_node("market_llm_reasoning", reason_node)
    builder.add_node("verify_and_finalize", finalize_node)
    builder.add_edge(START, "prepare_market_facts")
    builder.add_edge("prepare_market_facts", "market_llm_reasoning")
    builder.add_edge("market_llm_reasoning", "verify_and_finalize")
    builder.add_edge("verify_and_finalize", END)
    return builder.compile()
