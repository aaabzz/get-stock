---
name: extend-get-stock-agents
description: Extend or modify get-stock specialist analysis Agents and their Supervisor/Comprehensive integration. Use when adding an Agent such as an announcement, industry, news, or API-backed Agent; changing Agent topics, task/result schemas, data requirements, routing, synthesis adaptation, runtime registration, or extension tests in this repository.
---

# Extend Get Stock Agents

Add specialist capabilities through the runtime type registry. Preserve the boundary that LLMs
select validated topics while deterministic code selects Agent implementations, files, providers,
and crawlers.

## Inspect the contracts

Read `agent_plugins/spec.py`, `agent_plugins/registry.py`, `agent_plugins/builtins.py`,
`supervisor/task_factory.py`, `comprehensive_agent/adapters.py`, and the target Agent package.

## Add a specialist Agent

1. Create strict Task and Result Pydantic schemas, catalog, Agent, reasoner, verifier, and tests.
2. Include `agent`, `task_id`, `status`, `stock_code`, `summary`, `analysis_scope`, `evidence`,
   `missing_data`, and `limitations` in the Result.
3. Include `claim`, `assessment`, `evidence_ids`, `confidence`, and `topic` in supported claims.
4. Implement one task builder and one Agent factory.
5. Create `AgentTypeSpec` with Topic mapping, intent keywords, construction hooks, Result model,
   claim fields, data requirements, file allowlist, role, priority, and source weight.
6. Register the spec explicitly in `build_builtin_agent_types()`. Do not scan arbitrary packages.

```python
AgentTypeSpec(
    name="announcement_analysis",
    version="1.0",
    label="Announcement Analysis Agent",
    topic_map={"regulatory_inquiry": "regulatory_inquiry"},
    intent_keywords={"regulatory_inquiry": ("regulatory inquiry", "inquiry letter")},
    task_builder=build_announcement_task,
    agent_factory=build_announcement_agent,
    result_model=AnnouncementAnalysisResult,
    claim_fields=(("claims", "claim"),),
    kind="document",
    role="supplement",
    priority=200,
    source_weight=0.8,
)
```

## Enforce boundaries

- Declare structured requirements in `data_catalog` and readable filenames in `dataset_files`.
- Route structured gaps through `DataAcquisitionCoordinator` and documents through a document
  coordinator when available.
- Never let an Agent or LLM construct shell commands, URLs, Spider classes, or arbitrary paths.
- Keep announcement IDs, document roles, datasets, and Agent names under explicit validation.

## Integrate synthesis

Use `claim_fields` and `topic_map` so the generic comprehensive adapter handles the Result without
Agent-specific branches. Reserve `topic_strategy="financial_dimensions"` for the existing financial
evidence relationship; use `claim_topic` otherwise.

Use `role="primary"` for an authoritative handler and `role="supplement"` for optional evidence.
Lower priority wins between equal roles. Test any duplicate Topic route.

## Verify

Test routing, task scope, evidence validation, failure isolation, normalized Findings, and Markdown.

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Do not run live CNINFO tests unless the user explicitly requests network verification.
