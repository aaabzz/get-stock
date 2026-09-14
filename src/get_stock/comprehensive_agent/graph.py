from __future__ import annotations

from typing import Any, TypedDict

from get_stock.comprehensive_agent.agent import ComprehensiveAnalysisAgent
from get_stock.comprehensive_agent.schemas import ComprehensiveLLMAnalysis


class ComprehensiveGraphState(TypedDict, total=False):
    task: dict[str, Any]
    prepared: dict[str, Any]
    llm_analysis: ComprehensiveLLMAnalysis
    llm_used: bool
    result: dict[str, Any]


def build_comprehensive_graph(agent: ComprehensiveAnalysisAgent):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph dependencies are missing; install with pip install -e .[agent]"
        ) from exc

    def prepare_node(state: ComprehensiveGraphState) -> ComprehensiveGraphState:
        return {"prepared": agent.prepare(state["task"])}

    def reason_node(state: ComprehensiveGraphState) -> ComprehensiveGraphState:
        analysis, llm_used = agent.reason(state["prepared"])
        return {"llm_analysis": analysis, "llm_used": llm_used}

    def finalize_node(state: ComprehensiveGraphState) -> ComprehensiveGraphState:
        result = agent.finalize(
            state["prepared"],
            state["llm_analysis"],
            llm_used=state["llm_used"],
        )
        return {"result": result.model_dump(mode="json")}

    builder = StateGraph(ComprehensiveGraphState)
    builder.add_node("normalize_and_verify_specialist_results", prepare_node)
    builder.add_node("comprehensive_llm_reasoning", reason_node)
    builder.add_node("render_and_write_analysis_artifacts", finalize_node)
    builder.add_edge(START, "normalize_and_verify_specialist_results")
    builder.add_edge("normalize_and_verify_specialist_results", "comprehensive_llm_reasoning")
    builder.add_edge("comprehensive_llm_reasoning", "render_and_write_analysis_artifacts")
    builder.add_edge("render_and_write_analysis_artifacts", END)
    return builder.compile()
