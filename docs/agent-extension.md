# Agent 扩展机制

专业 Agent 通过 `AgentTypeSpec` 显式注册。Supervisor、缓存检查、运行时构造和综合结果适配
共用同一个 `AgentTypeRegistry`，LLM 只能选择注册表暴露的 Topic。

## 类型描述

每个专业 Agent 声明：

- `name/version/label`：稳定身份和展示信息；
- `topic_map/intent_keywords`：专业 Topic 到综合 Topic 的映射及规则关键词；
- `task_builder/agent_factory`：任务和实例构造入口；
- `result_model/claim_fields`：专业结果校验及通用 Finding 适配规则；
- `data_catalog/dataset_files`：数据需求和文件访问白名单；
- `kind/role/priority/source_weight`：数据类型、路由角色、优先级和综合权重。

`role=primary` 优先于 `supplement`，同角色由较小的 `priority` 获胜。注册表不扫描外部包，
新增内置 Agent 必须显式加入 `build_builtin_agent_types()`。

## 接入步骤

1. 新建 Agent 的 Task、Result、Agent、reasoner、verifier 和 catalog。
2. 实现 `task_builder` 与 `agent_factory`。
3. 创建 `AgentTypeSpec` 并加入内置注册表。
4. 为新综合 Topic 添加显示名称。
5. 为新 reasoner 在应用组合层注入对应的模型调用器。
6. 测试问题路由、结果校验、综合 Finding 和 Markdown 产物。

通用综合适配要求 Result 至少提供 `agent`、`task_id`、`status`、`stock_code`、`summary`、
`analysis_scope`、`evidence`、`missing_data` 和 `limitations`。`claim_fields` 中的每项 Claim 应
包含 `topic`、`claim`、`assessment`、`evidence_ids` 和 `confidence`。

## 公告 Agent 示例

```python
AgentTypeSpec(
    name="announcement_analysis",
    version="1.0",
    label="公告分析 Agent",
    topic_map={"regulatory_inquiry": "regulatory_inquiry"},
    intent_keywords={"regulatory_inquiry": ("监管问询", "问询函")},
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

公告检索和 PDF 下载仍应由 `DocumentAcquisitionCoordinator` 管理，公告 Agent 本身只读取
上游授权的本地文档或派生内容。

项目内的 Codex 开发规范位于
`.codex/skills/extend-get-stock-agents/SKILL.md`。
