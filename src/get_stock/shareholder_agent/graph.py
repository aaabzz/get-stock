from __future__ import annotations

from typing import Any, TypedDict

from get_stock.shareholder_agent.agent import ShareholderAnalysisAgent
from get_stock.shareholder_agent.schemas import ShareholderLLMAnalysis


class ShareholderGraphState(TypedDict, total=False):
    task: dict[str, Any]
    prepared: dict[str, Any]
    llm_analysis: ShareholderLLMAnalysis
    llm_used: bool
    result: dict[str, Any]


def build_shareholder_graph(agent: ShareholderAnalysisAgent):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph dependencies are missing; install with pip install -e .[agent]"
        ) from exc

    def prepare_node(state: ShareholderGraphState) -> ShareholderGraphState:
        return {"prepared": agent.prepare(state["task"])}

    def reason_node(state: ShareholderGraphState) -> ShareholderGraphState:
        analysis, llm_used = agent.reason(state["prepared"])
        return {"llm_analysis": analysis, "llm_used": llm_used}

    def finalize_node(state: ShareholderGraphState) -> ShareholderGraphState:
        result = agent.finalize(
            state["prepared"],
            state["llm_analysis"],
            llm_used=state["llm_used"],
        )
        return {"result": result.model_dump(mode="json")}

    builder = StateGraph(ShareholderGraphState)
    builder.add_node("prepare_shareholder_facts", prepare_node)
    builder.add_node("shareholder_llm_reasoning", reason_node)
    builder.add_node("verify_and_finalize", finalize_node)
    builder.add_edge(START, "prepare_shareholder_facts")
    builder.add_edge("prepare_shareholder_facts", "shareholder_llm_reasoning")
    builder.add_edge("shareholder_llm_reasoning", "verify_and_finalize")
    builder.add_edge("verify_and_finalize", END)
    return builder.compile()
