from __future__ import annotations

from typing import Any, TypedDict

from get_stock.financial_agent.agent import FinancialAnalysisAgent
from get_stock.financial_agent.schemas import FinancialLLMAnalysis


class FinancialGraphState(TypedDict, total=False):
    task: dict[str, Any]
    prepared: dict[str, Any]
    llm_analysis: FinancialLLMAnalysis
    llm_used: bool
    result: dict[str, Any]


def build_financial_graph(agent: FinancialAnalysisAgent):
    """Compile the specialist as a LangGraph subgraph with a narrow state contract."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph dependencies are missing; install with pip install -e .[agent]"
        ) from exc

    def prepare_node(state: FinancialGraphState) -> FinancialGraphState:
        return {"prepared": agent.prepare(state["task"])}

    def reason_node(state: FinancialGraphState) -> FinancialGraphState:
        analysis, llm_used = agent.reason(state["prepared"])
        return {"llm_analysis": analysis, "llm_used": llm_used}

    def finalize_node(state: FinancialGraphState) -> FinancialGraphState:
        result = agent.finalize(
            state["prepared"],
            state["llm_analysis"],
            llm_used=state["llm_used"],
        )
        return {"result": result.model_dump(mode="json")}

    builder = StateGraph(FinancialGraphState)
    builder.add_node("prepare_structured_facts", prepare_node)
    builder.add_node("financial_llm_reasoning", reason_node)
    builder.add_node("verify_and_finalize", finalize_node)
    builder.add_edge(START, "prepare_structured_facts")
    builder.add_edge("prepare_structured_facts", "financial_llm_reasoning")
    builder.add_edge("financial_llm_reasoning", "verify_and_finalize")
    builder.add_edge("verify_and_finalize", END)
    return builder.compile()
