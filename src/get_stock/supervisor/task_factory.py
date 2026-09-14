from __future__ import annotations

from collections import defaultdict

from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.comprehensive_agent import ComprehensiveAnalysisTask
from get_stock.comprehensive_agent.schemas import (
    ComprehensiveRequirement,
    ComprehensiveTaskConstraints,
    SpecialistResultEnvelope,
)
from get_stock.report_agent import ReportReference
from get_stock.supervisor.schemas import SupervisorPlan, SupervisorTask


def build_specialist_tasks(
    task: SupervisorTask,
    plan: SupervisorPlan,
    *,
    reports: tuple[ReportReference, ...] = (),
    agent_types: AgentTypeRegistry | None = None,
) -> dict[str, object]:
    agent_types = agent_types or build_builtin_agent_types()
    topics_by_agent: dict[str, list[str]] = defaultdict(list)
    for requirement in plan.requirements:
        for agent in requirement.required_agents:
            specialist = agent_types.get(agent).specialist_topic(requirement.topic)
            if specialist not in topics_by_agent[agent]:
                topics_by_agent[agent].append(specialist)

    result: dict[str, object] = {}
    context = {"reports": reports}
    for agent in plan.expected_agents:
        topics = tuple(topics_by_agent.get(agent, ()))
        if not topics:
            continue
        built = agent_types.get(agent).task_builder(task, plan, topics, context)
        if built is not None:
            result[agent] = built
    return result


def build_comprehensive_task(
    task: SupervisorTask,
    plan: SupervisorPlan,
    results: dict[str, dict],
) -> ComprehensiveAnalysisTask:
    return ComprehensiveAnalysisTask(
        task_id=f"{task.task_id}-comprehensive",
        parent_task_id=task.task_id,
        stock_code=plan.stock_code,
        question=task.question,
        requirements=tuple(
            ComprehensiveRequirement(
                requirement_id=item.requirement_id,
                topic=item.topic,
                question=item.question,
                required_agents=item.required_agents,
            )
            for item in plan.requirements
        ),
        expected_agents=plan.expected_agents,
        agent_results=tuple(
            SpecialistResultEnvelope(agent=agent, result=result)
            for agent, result in results.items()
        ),
        constraints=ComprehensiveTaskConstraints(require_llm=task.require_llm),
    )
