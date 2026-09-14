from __future__ import annotations

import json
from pathlib import Path

from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.storage import iter_json_lines
from get_stock.supervisor.schemas import DatasetAvailability, SupervisorPlan


def inspect_local_cache(
    data_dir: Path,
    plan: SupervisorPlan,
    specialist_tasks: dict[str, object] | None = None,
    agent_types: AgentTypeRegistry | None = None,
) -> list[DatasetAvailability]:
    agent_types = agent_types or build_builtin_agent_types()
    stock_dir = data_dir.resolve() / "stocks" / plan.stock_code
    snapshots: list[DatasetAvailability] = []
    for agent in plan.expected_agents:
        files = agent_types.get(agent).dataset_files
        agent_task = (specialist_tasks or {}).get(agent)
        requested = getattr(agent_task, "dataset_names", tuple(files))
        for dataset in requested:
            filename = files[dataset]
            path = stock_dir / "cleaned" / filename
            exists = path.is_file()
            count = None
            if exists:
                if path.suffix == ".jsonl":
                    count = sum(1 for _ in iter_json_lines(path))
                else:
                    try:
                        count = 1 if json.loads(path.read_text(encoding="utf-8")) else 0
                    except (OSError, json.JSONDecodeError):
                        count = 0
            snapshots.append(
                DatasetAvailability(
                    agent=agent,
                    dataset=dataset,
                    path=str(path),
                    exists=exists,
                    record_count=count,
                )
            )
    return snapshots


def find_blocking_cache_gaps(
    plan: SupervisorPlan,
    specialist_tasks: dict[str, object],
    snapshots: list[DatasetAvailability],
    agent_types: AgentTypeRegistry | None = None,
) -> list[str]:
    """Return absent/empty required datasets before any specialist is executed."""
    availability = {
        (item.agent, item.dataset): item.exists and bool(item.record_count) for item in snapshots
    }
    missing: list[str] = []
    agent_types = agent_types or build_builtin_agent_types()
    for agent, agent_task in specialist_tasks.items():
        catalog = agent_types.get(agent).data_catalog
        if not catalog:
            continue
        for topic in getattr(agent_task, "topics", ()):
            for dataset in catalog[topic]["required"]:
                if not availability.get((agent, dataset), False) and dataset not in missing:
                    missing.append(dataset)
    return missing
