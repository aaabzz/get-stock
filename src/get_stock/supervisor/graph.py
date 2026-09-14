from __future__ import annotations

from typing import Any, TypedDict

from get_stock.supervisor.supervisor import StockAnalysisSupervisor


class SupervisorGraphState(TypedDict, total=False):
    task: dict[str, Any]
    understood: dict[str, Any]
    prepared: dict[str, Any]
    recovered: dict[str, Any]
    documents_recovered: dict[str, Any]
    executed: dict[str, Any]
    synthesized: dict[str, Any]
    result: dict[str, Any]


def build_supervisor_graph(supervisor: StockAnalysisSupervisor):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph dependencies are missing; install with pip install -e .[agent]"
        ) from exc

    builder = StateGraph(SupervisorGraphState)
    builder.add_node(
        "understand_question",
        lambda state: {"understood": supervisor.understand(state["task"])},
    )
    builder.add_node(
        "build_analysis_plan_and_inspect_cache",
        lambda state: {"prepared": supervisor.plan(state["understood"])},
    )
    builder.add_node(
        "recover_missing_structured_data",
        lambda state: {"recovered": supervisor.recover(state["prepared"])},
    )
    builder.add_node(
        "recover_and_process_documents",
        lambda state: {
            "documents_recovered": supervisor.recover_documents(state["recovered"])
        },
    )
    builder.add_node(
        "route_and_execute_specialists",
        lambda state: {"executed": supervisor.execute(state["documents_recovered"])},
    )
    builder.add_node(
        "build_and_execute_comprehensive_task",
        lambda state: {"synthesized": supervisor.synthesize(state["executed"])},
    )
    builder.add_node(
        "write_supervisor_artifacts",
        lambda state: {"result": supervisor.finalize(state["synthesized"]).model_dump(mode="json")},
    )
    builder.add_edge(START, "understand_question")
    builder.add_edge("understand_question", "build_analysis_plan_and_inspect_cache")
    builder.add_edge("build_analysis_plan_and_inspect_cache", "recover_missing_structured_data")
    builder.add_edge("recover_missing_structured_data", "recover_and_process_documents")
    builder.add_edge("recover_and_process_documents", "route_and_execute_specialists")
    builder.add_edge("route_and_execute_specialists", "build_and_execute_comprehensive_task")
    builder.add_edge("build_and_execute_comprehensive_task", "write_supervisor_artifacts")
    builder.add_edge("write_supervisor_artifacts", END)
    return builder.compile()
