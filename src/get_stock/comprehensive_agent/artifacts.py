from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from get_stock.comprehensive_agent.schemas import ComprehensiveAnalysisResult
from get_stock.storage import atomic_write_json

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def artifact_paths(data_dir: Path, stock_code: str, task_id: str) -> dict[str, Path]:
    root = (
        data_dir.resolve() / "stocks" / stock_code / "analysis" / "comprehensive" / task_id
    ).resolve()
    allowed_root = (
        data_dir.resolve() / "stocks" / stock_code / "analysis" / "comprehensive"
    ).resolve()
    if not root.is_relative_to(allowed_root):
        raise ValueError("analysis artifact path escapes the stock analysis directory")
    return {
        "result_json": root / "result.json",
        "markdown": root / "report.md",
        "state": root / "state.json",
    }


def write_analysis_artifacts(
    result: ComprehensiveAnalysisResult,
    markdown: str,
    paths: dict[str, Path],
) -> None:
    atomic_write_json(paths["result_json"], result.model_dump(mode="json"))
    _atomic_write_text(paths["markdown"], markdown)
    atomic_write_json(
        paths["state"],
        {
            "schema_version": "1.0",
            "agent": result.agent,
            "agent_version": result.agent_version,
            "task_id": result.task_id,
            "stock_code": result.stock_code,
            "status": result.status,
            "llm_used": result.llm_used,
            "artifacts": result.artifacts.model_dump(mode="json"),
            "written_at": datetime.now(CHINA_TZ).isoformat(),
        },
    )


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)
