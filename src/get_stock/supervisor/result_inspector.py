from __future__ import annotations

from typing import Any

from get_stock.supervisor.catalog import DATASET_CRAWL_ACTIONS


def collect_missing_data(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for agent, result in results.items():
        for item in result.get("missing_data", []):
            if isinstance(item, dict):
                collected.append({"source_agent": agent, **item})
    return collected


def recommend_actions(
    missing_data: list[dict[str, Any]],
    failures: dict[str, str],
    *,
    auto_crawl_requested: bool,
    auto_documents_requested: bool = False,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in missing_data:
        dataset = str(item.get("dataset") or "")
        action = str(item.get("recommended_action") or "")
        if not action and dataset:
            action = DATASET_CRAWL_ACTIONS.get(dataset, "")
        if not action:
            continue
        key = (dataset, action)
        if key in seen:
            continue
        seen.add(key)
        actions.append(
            {
                "dataset": dataset or None,
                "action": action,
                "automatic": (
                    auto_documents_requested
                    if action == "process_full_report_pdf"
                    else auto_crawl_requested
                ),
                "reason": item.get("reason"),
            }
        )
    for agent, error in failures.items():
        actions.append(
            {
                "agent": agent,
                "action": "inspect_agent_failure",
                "automatic": False,
                "reason": error,
            }
        )
    return actions
