from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from get_stock.agent_plugins import AgentTypeSpec, build_builtin_agent_types
from get_stock.supervisor import AgentRegistry, StockAnalysisSupervisor, SupervisorTask


class ExampleAnnouncementTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    stock_code: str
    topics: tuple[str, ...]


class ExampleAnnouncementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: Literal["announcement_analysis"] = "announcement_analysis"
    task_id: str
    status: Literal["completed"] = "completed"
    stock_code: str
    summary: str
    analysis_scope: dict
    claims: list[dict]
    evidence: list[dict]
    missing_data: list[dict] = []
    limitations: list[str] = []


class ExampleAnnouncementAgent:
    def analyze(self, task: ExampleAnnouncementTask) -> ExampleAnnouncementResult:
        return ExampleAnnouncementResult(
            task_id=task.task_id,
            stock_code=task.stock_code,
            summary="发现一项监管问询公告。",
            analysis_scope={"topics": list(task.topics)},
            claims=[
                {
                    "topic": "regulatory_inquiry",
                    "claim": "公告披露公司收到监管问询。",
                    "assessment": "watch",
                    "evidence_ids": ["ae0001"],
                    "confidence": 0.8,
                }
            ],
            evidence=[
                {
                    "evidence_id": "ae0001",
                    "announcement_id": "example-001",
                    "report_period": "2026-01-01",
                    "text_excerpt": "公司收到监管问询函。",
                }
            ],
        )


def _build_task(task, plan, topics, _context):
    return ExampleAnnouncementTask(
        task_id=f"{task.task_id}-announcement",
        stock_code=plan.stock_code,
        topics=topics,
    )


def _build_agent(_data_dir: Path, _reasoner):
    return ExampleAnnouncementAgent()


def test_new_agent_type_routes_executes_and_reaches_synthesis_without_core_edits(
    tmp_path: Path,
) -> None:
    agent_types = build_builtin_agent_types()
    agent_types.register(
        AgentTypeSpec(
            name="announcement_analysis",
            version="1.0",
            label="公告分析 Agent",
            topic_map={"regulatory_inquiry": "regulatory_inquiry"},
            intent_keywords={"regulatory_inquiry": ("监管问询", "问询函")},
            task_builder=_build_task,
            agent_factory=_build_agent,
            result_model=ExampleAnnouncementResult,
            claim_fields=(("claims", "claim"),),
            kind="document",
            source_weight=0.8,
        )
    )
    runtime = AgentRegistry(tmp_path, agent_types=agent_types)

    result = StockAnalysisSupervisor(
        tmp_path,
        registry=runtime,
        agent_types=agent_types,
    ).analyze(
        SupervisorTask(
            task_id="extensible-agent-smoke",
            question="分析000001是否收到监管问询",
            require_llm=False,
        )
    )

    assert result.status == "completed"
    assert result.expected_agents == ["announcement_analysis"]
    assert result.executions[0].status == "completed"
    assert result.comprehensive_result["findings"][0]["topics"] == ["regulatory_inquiry"]
    assert Path(result.artifacts.markdown).is_file()


def test_registry_rejects_duplicate_agent_names_and_ambiguous_routes() -> None:
    registry = build_builtin_agent_types()
    example = AgentTypeSpec(
        name="announcement_analysis",
        version="1.0",
        label="公告分析 Agent",
        topic_map={"valuation_notice": "valuation"},
        task_builder=_build_task,
        agent_factory=_build_agent,
        result_model=ExampleAnnouncementResult,
        claim_fields=(("claims", "claim"),),
    )

    with pytest.raises(ValueError, match="ambiguous agent routes"):
        registry.register(example)

    unique = AgentTypeSpec(
        name="announcement_analysis",
        version="1.0",
        label="公告分析 Agent Agent",
        topic_map={"regulatory_inquiry": "regulatory_inquiry"},
        task_builder=_build_task,
        agent_factory=_build_agent,
        result_model=ExampleAnnouncementResult,
        claim_fields=(("claims", "claim"),),
    )
    registry.register(unique)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(unique)
