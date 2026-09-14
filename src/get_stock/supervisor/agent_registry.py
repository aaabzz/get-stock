from __future__ import annotations

from pathlib import Path
from typing import Any

from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.comprehensive_agent import ComprehensiveAnalysisAgent


class AgentRegistry:
    """Allowlisted in-process registry; agent names never come directly from an LLM."""

    def __init__(
        self,
        data_dir: Path,
        *,
        reasoners: dict[str, Any] | None = None,
        overrides: dict[str, Any] | None = None,
        agent_types: AgentTypeRegistry | None = None,
    ) -> None:
        reasoners = reasoners or {}
        self.agent_types = agent_types or build_builtin_agent_types()
        self._agents: dict[str, Any] = {
            spec.name: spec.agent_factory(data_dir, reasoners.get(spec.name))
            for spec in self.agent_types.all()
        }
        self._agents["comprehensive_analysis"] = ComprehensiveAnalysisAgent(
            data_dir,
            reasoner=reasoners.get("comprehensive_analysis"),
            agent_types=self.agent_types,
        )
        overrides = overrides or {}
        unknown_overrides = set(overrides) - set(self._agents)
        if unknown_overrides:
            raise ValueError(f"cannot override unregistered agents: {sorted(unknown_overrides)}")
        self._agents.update(overrides)

    def run(self, agent: str, task: object) -> Any:
        if agent not in self._agents:
            raise ValueError(f"agent is not registered: {agent}")
        return self._agents[agent].analyze(task)
