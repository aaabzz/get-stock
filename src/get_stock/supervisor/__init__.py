"""Supervisor for end-to-end local stock analysis orchestration."""

from get_stock.supervisor.agent_registry import AgentRegistry
from get_stock.supervisor.date_resolver import resolve_time_scope
from get_stock.supervisor.graph import build_supervisor_graph
from get_stock.supervisor.planner import build_plan_from_understanding, build_supervisor_plan
from get_stock.supervisor.query_understanding import understand_supervisor_question
from get_stock.supervisor.reasoner import (
    LangChainSupervisorPlanningReasoner,
    build_deepseek_supervisor_reasoner,
)
from get_stock.supervisor.schemas import (
    DocumentIntent,
    QuestionUnderstanding,
    ResolvedTimeScope,
    SupervisorPlan,
    SupervisorPlanDraft,
    SupervisorRequirement,
    SupervisorResult,
    SupervisorTask,
    TimeIntent,
)
from get_stock.supervisor.supervisor import StockAnalysisSupervisor, SupervisorError

__all__ = [
    "AgentRegistry",
    "StockAnalysisSupervisor",
    "SupervisorError",
    "SupervisorPlan",
    "QuestionUnderstanding",
    "ResolvedTimeScope",
    "SupervisorPlanDraft",
    "SupervisorRequirement",
    "SupervisorResult",
    "SupervisorTask",
    "TimeIntent",
    "DocumentIntent",
    "build_supervisor_graph",
    "build_supervisor_plan",
    "build_plan_from_understanding",
    "understand_supervisor_question",
    "resolve_time_scope",
    "build_deepseek_supervisor_reasoner",
    "LangChainSupervisorPlanningReasoner",
]
