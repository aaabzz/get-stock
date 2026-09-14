from __future__ import annotations

from typing import Any

from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.supervisor.query_understanding import understand_supervisor_question
from get_stock.supervisor.reasoner import SupervisorPlanningReasoner
from get_stock.supervisor.schemas import (
    QuestionUnderstanding,
    SupervisorPlan,
    SupervisorRequirement,
    SupervisorTask,
)


def build_supervisor_plan(
    task: SupervisorTask,
    *,
    reasoner: SupervisorPlanningReasoner | None = None,
    agent_types: AgentTypeRegistry | None = None,
) -> SupervisorPlan:
    agent_types = agent_types or build_builtin_agent_types()
    understanding = understand_supervisor_question(task, reasoner=reasoner, agent_types=agent_types)
    return build_plan_from_understanding(task, understanding, agent_types=agent_types)


def build_plan_from_understanding(
    task: SupervisorTask,
    understanding: QuestionUnderstanding,
    *,
    agent_types: AgentTypeRegistry | None = None,
) -> SupervisorPlan:
    """Map validated topics to allowlisted agents and datasets deterministically."""
    routes = (agent_types or build_builtin_agent_types()).routes()
    selected = [(topic, routes[topic][0]) for topic in understanding.topics]
    return _make_plan(
        stock_code=understanding.stock_code,
        question=task.question.strip(),
        selected=selected,
        values={
            "financial_years": understanding.financial_years,
            "shareholder_periods": understanding.shareholder_periods,
            "market_sessions": understanding.market_sessions,
            "report_type": understanding.report_type,
            "time_intent": understanding.time_intent,
            "document_intent": understanding.document_intent,
        },
        planner_mode=understanding.interpreter_mode,
        planning_llm_used=understanding.llm_used,
        warnings=list(understanding.warnings),
    )


def _make_plan(
    *,
    stock_code: str,
    question: str,
    selected: list[tuple[str, str]],
    values: dict[str, Any],
    planner_mode: str,
    planning_llm_used: bool,
    warnings: list[str],
) -> SupervisorPlan:
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for topic, agent in selected:
        if topic not in seen:
            unique.append((topic, agent))
            seen.add(topic)

    requirements = tuple(
        SupervisorRequirement(
            requirement_id=f"req-{index:02d}",
            topic=topic,
            question=question,
            required_agents=(agent,),
        )
        for index, (topic, agent) in enumerate(unique, start=1)
    )
    expected_agents = tuple(dict.fromkeys(agent for _, agent in unique))
    return SupervisorPlan(
        stock_code=stock_code,
        requirements=requirements,
        expected_agents=expected_agents,
        financial_years=values["financial_years"],
        shareholder_periods=values["shareholder_periods"],
        market_sessions=values["market_sessions"],
        report_type=values["report_type"],
        time_intent=values["time_intent"],
        document_intent=values["document_intent"],
        planner_mode=planner_mode,
        planning_llm_used=planning_llm_used,
        warnings=tuple(warnings),
    )
