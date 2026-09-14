from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from get_stock.storage import atomic_write_json
from get_stock.supervisor.schemas import SupervisorArtifacts, SupervisorResult

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def supervisor_artifact_paths(data_dir: Path, stock_code: str, task_id: str) -> dict[str, Path]:
    allowed = (data_dir.resolve() / "stocks" / stock_code / "analysis" / "supervisor").resolve()
    root = (allowed / task_id).resolve()
    if not root.is_relative_to(allowed):
        raise ValueError("Supervisor artifact path escapes the stock analysis directory")
    return {
        "root": root,
        "request": root / "request.json",
        "understanding": root / "understanding.json",
        "resolved_dates": root / "resolved_dates.json",
        "plan": root / "plan.json",
        "cache_snapshot": root / "cache_snapshot.json",
        "acquisition": root / "acquisition.json",
        "document_acquisition": root / "document_acquisition.json",
        "specialist_results": root / "specialist_results",
        "result": root / "result.json",
        "state": root / "state.json",
    }


def build_artifact_manifest(
    paths: dict[str, Path], comprehensive_result: dict[str, Any] | None
) -> SupervisorArtifacts:
    comprehensive_artifacts = (comprehensive_result or {}).get("artifacts", {})
    return SupervisorArtifacts(
        request=str(paths["request"]),
        understanding=str(paths["understanding"]),
        resolved_dates=str(paths["resolved_dates"]),
        plan=str(paths["plan"]),
        cache_snapshot=str(paths["cache_snapshot"]),
        acquisition=str(paths["acquisition"]),
        document_acquisition=str(paths["document_acquisition"]),
        specialist_results=str(paths["specialist_results"]),
        result=str(paths["result"]),
        state=str(paths["state"]),
        comprehensive_result=comprehensive_artifacts.get("result_json"),
        markdown=comprehensive_artifacts.get("markdown"),
    )


def write_supervisor_artifacts(
    *,
    request: dict[str, Any],
    understanding: dict[str, Any],
    resolved_dates: dict[str, Any],
    plan: dict[str, Any],
    cache_snapshot: list[dict[str, Any]],
    acquisition: dict[str, Any],
    document_acquisition: dict[str, Any],
    specialist_results: dict[str, dict[str, Any]],
    result: SupervisorResult,
    paths: dict[str, Path],
) -> None:
    atomic_write_json(paths["request"], request)
    atomic_write_json(paths["understanding"], understanding)
    atomic_write_json(paths["resolved_dates"], resolved_dates)
    atomic_write_json(paths["plan"], plan)
    atomic_write_json(paths["cache_snapshot"], cache_snapshot)
    atomic_write_json(paths["acquisition"], acquisition)
    atomic_write_json(paths["document_acquisition"], document_acquisition)
    for agent, payload in specialist_results.items():
        atomic_write_json(paths["specialist_results"] / f"{agent}.json", payload)
    atomic_write_json(paths["result"], result.model_dump(mode="json"))
    atomic_write_json(
        paths["state"],
        {
            "schema_version": "1.0",
            "task_id": result.task_id,
            "stock_code": result.stock_code,
            "status": result.status,
            "executions": [item.model_dump(mode="json") for item in result.executions],
            "acquisition": result.acquisition,
            "document_acquisition": result.document_acquisition,
            "artifacts": result.artifacts.model_dump(mode="json"),
            "written_at": datetime.now(CHINA_TZ).isoformat(),
        },
    )
