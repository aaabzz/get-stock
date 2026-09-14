from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
TOPIC_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

AgentFactory = Callable[[Path, Any], Any]
TaskBuilder = Callable[[Any, Any, tuple[str, ...], Mapping[str, Any]], object | None]


@dataclass(frozen=True)
class AgentTypeSpec:
    """Declarative extension contract for one specialist Agent type."""

    name: str
    version: str
    label: str
    topic_map: Mapping[str, str]
    task_builder: TaskBuilder
    agent_factory: AgentFactory
    result_model: type
    claim_fields: tuple[tuple[str, str], ...]
    intent_keywords: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    data_catalog: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    dataset_files: Mapping[str, str] = field(default_factory=dict)
    kind: Literal["structured", "document"] = "structured"
    role: Literal["primary", "supplement"] = "primary"
    priority: int = 100
    source_weight: float = 1.0
    topic_strategy: Literal["claim_topic", "financial_dimensions"] = "claim_topic"

    def __post_init__(self) -> None:
        if not AGENT_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(f"invalid agent type name: {self.name}")
        if not self.version.strip() or not self.label.strip():
            raise ValueError("agent version and label are required")
        if not 0 <= self.source_weight <= 1:
            raise ValueError("source_weight must be between 0 and 1")
        if not self.topic_map:
            raise ValueError(f"specialist agent {self.name} must declare at least one topic")
        for specialist, synthesis in self.topic_map.items():
            if not TOPIC_NAME_PATTERN.fullmatch(specialist):
                raise ValueError(f"invalid specialist topic: {specialist}")
            if not TOPIC_NAME_PATTERN.fullmatch(synthesis):
                raise ValueError(f"invalid synthesis topic: {synthesis}")
        unknown_catalog_topics = set(self.data_catalog) - set(self.topic_map)
        if unknown_catalog_topics:
            raise ValueError(
                f"{self.name} data catalog contains unknown topics: "
                f"{sorted(unknown_catalog_topics)}"
            )
        unknown_keyword_topics = set(self.intent_keywords) - set(self.topic_map)
        if unknown_keyword_topics:
            raise ValueError(
                f"{self.name} intent keywords contain unknown topics: "
                f"{sorted(unknown_keyword_topics)}"
            )
        declared_datasets = {
            dataset
            for policy in self.data_catalog.values()
            for key in ("required", "optional")
            for dataset in policy.get(key, ())
        }
        missing_files = declared_datasets - set(self.dataset_files)
        if missing_files:
            raise ValueError(
                f"{self.name} datasets have no file allowlist entry: {sorted(missing_files)}"
            )
        if not callable(self.task_builder) or not callable(self.agent_factory):
            raise ValueError("task_builder and agent_factory must be callable")
        if not hasattr(self.result_model, "model_validate"):
            raise ValueError("result_model must be a Pydantic model type")
        object.__setattr__(self, "topic_map", MappingProxyType(dict(self.topic_map)))
        object.__setattr__(
            self,
            "data_catalog",
            MappingProxyType(
                {topic: MappingProxyType(dict(value)) for topic, value in self.data_catalog.items()}
            ),
        )
        object.__setattr__(self, "dataset_files", MappingProxyType(dict(self.dataset_files)))
        object.__setattr__(
            self,
            "intent_keywords",
            MappingProxyType(
                {topic: tuple(keywords) for topic, keywords in self.intent_keywords.items()}
            ),
        )

    @property
    def synthesis_topics(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.topic_map.values()))

    def specialist_topic(self, synthesis_topic: str) -> str:
        matches = [
            specialist
            for specialist, synthesis in self.topic_map.items()
            if synthesis == synthesis_topic
        ]
        if not matches:
            raise ValueError(f"{self.name} does not support topic: {synthesis_topic}")
        return matches[0]
