from __future__ import annotations

from collections.abc import Iterable

from get_stock.agent_plugins.spec import AgentTypeSpec


class AgentTypeRegistry:
    """Explicit allowlist of specialist Agent capabilities and construction hooks."""

    def __init__(self, specs: Iterable[AgentTypeSpec] = ()) -> None:
        self._specs: dict[str, AgentTypeSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: AgentTypeSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"agent type is already registered: {spec.name}")
        for existing in self._specs.values():
            overlap = set(spec.synthesis_topics).intersection(existing.synthesis_topics)
            if overlap and (spec.role, spec.priority) == (existing.role, existing.priority):
                raise ValueError(
                    "ambiguous agent routes for topics "
                    f"{sorted(overlap)}: {existing.name} and {spec.name}"
                )
        self._specs[spec.name] = spec

    def get(self, name: str) -> AgentTypeSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ValueError(f"agent type is not registered: {name}") from exc

    def all(self) -> tuple[AgentTypeSpec, ...]:
        return tuple(self._specs.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def topic_maps(self) -> dict[str, dict[str, str]]:
        return {spec.name: dict(spec.topic_map) for spec in self.all()}

    def routes(self) -> dict[str, tuple[str, str]]:
        """Select the highest-priority primary provider for each synthesis topic."""
        candidates: dict[str, list[tuple[int, int, str, str]]] = {}
        for spec in self.all():
            role_rank = 0 if spec.role == "primary" else 1
            for specialist, synthesis in spec.topic_map.items():
                candidates.setdefault(synthesis, []).append(
                    (role_rank, spec.priority, spec.name, specialist)
                )
        return {
            synthesis: (selected[2], selected[3])
            for synthesis, values in candidates.items()
            for selected in [sorted(values)[0]]
        }

    def structured_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.all() if spec.kind == "structured")

    def source_weights(self) -> dict[str, float]:
        return {spec.name: spec.source_weight for spec in self.all()}

    def labels(self) -> dict[str, str]:
        return {spec.name: spec.label for spec in self.all()}
