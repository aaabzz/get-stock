from __future__ import annotations

from typing import Any, TypedDict

from get_stock.report_agent.agent import ReportAnalysisAgent
from get_stock.report_agent.schemas import ReportClaimValidationIssue, ReportLLMAnalysis


class ReportGraphState(TypedDict, total=False):
    task: dict[str, Any]
    prepared: dict[str, Any]
    retrieved: dict[str, Any]
    llm_analysis: ReportLLMAnalysis
    llm_used: bool
    claim_validation_issues: list[ReportClaimValidationIssue]
    result: dict[str, Any]


def build_report_graph(agent: ReportAnalysisAgent):
    """Compile the standby report specialist for conditional Supervisor routing."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph dependencies are missing; install with pip install -e .[agent]"
        ) from exc

    def prepare_node(state: ReportGraphState) -> ReportGraphState:
        return {"prepared": agent.prepare(state["task"])}

    def retrieve_node(state: ReportGraphState) -> ReportGraphState:
        return {"retrieved": agent.retrieve(state["prepared"])}

    def reason_node(state: ReportGraphState) -> ReportGraphState:
        analysis, llm_used, validation_issues = agent.reason(state["retrieved"])
        return {
            "llm_analysis": analysis,
            "llm_used": llm_used,
            "claim_validation_issues": validation_issues,
        }

    def finalize_node(state: ReportGraphState) -> ReportGraphState:
        result = agent.finalize(
            state["retrieved"],
            state["llm_analysis"],
            llm_used=state["llm_used"],
            validation_issues=state.get("claim_validation_issues", []),
        )
        return {"result": result.model_dump(mode="json")}

    builder = StateGraph(ReportGraphState)
    builder.add_node("validate_and_load_authorized_chunks", prepare_node)
    builder.add_node("match_headings_and_rank_chunks", retrieve_node)
    builder.add_node("report_llm_reasoning", reason_node)
    builder.add_node("verify_and_finalize", finalize_node)
    builder.add_edge(START, "validate_and_load_authorized_chunks")
    builder.add_edge("validate_and_load_authorized_chunks", "match_headings_and_rank_chunks")
    builder.add_edge("match_headings_and_rank_chunks", "report_llm_reasoning")
    builder.add_edge("report_llm_reasoning", "verify_and_finalize")
    builder.add_edge("verify_and_finalize", END)
    return builder.compile()
