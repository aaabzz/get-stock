# 财报定性分析 Agent（v1.1）

## 定位

财报 Agent 是由 Supervisor 条件唤醒的补充型专业 Agent。其他专业 Agent 能完整回答时，
Supervisor 不进入本子图，Agent 保持逻辑上的 `standby`，不会读取文件或调用 LLM。

第一版只读取上游明确授权的完整报告目录中的 `chunks.jsonl`。不读取 PDF、`pages.jsonl`、
`sections.jsonl`、`manifest.json` 或其他结构化股票数据，不访问网络和爬虫。

## 与其他 Agent 的边界

| 内容 | 负责 Agent |
| --- | --- |
| 营收、净利润、现金流、ROE等定量指标 | 财务分析 Agent |
| 股价、成交量、估值、融资融券、大宗交易 | 市场交易 Agent |
| 股东人数、十大股东、基金持股、解禁、质押 | 股东分析 Agent |
| 行业地位、技术、竞争优势、经营解释和风险披露 | 财报 Agent |

财报 Agent 不能用 PDF 文字替代缺失的标准化财务、行情或股东数据。混合问题由 Supervisor
先调用结构化专业 Agent，再把仍需财报定性解释的要求作为 `ReportAnalysisTask` 派发。

## 允许与禁止的章节

允许章节类型包括：公司简介、业务概要、管理层讨论、公司治理、环境与社会、重要事项、
股份及股东和债券相关章节。

禁止 `financial_indicators`、`financial_report`、`front_matter` 和 `unclassified`。检索器还会
检查 chunk 正文中的独立章节标题，避免旧版切分将“会计数据和财务指标”或“财务报告”的
开头残留在前一个允许章节末尾。

## 上游任务契约

```json
{
  "task_id": "report-task-001",
  "parent_task_id": "supervisor-task-001",
  "mode": "supplement",
  "stock_code": "000001",
  "question": "解释利润变化原因并分析技术优势",
  "requirements": [
    {
      "requirement_id": "req-01",
      "topic": "management_explanation",
      "question": "管理层如何解释利润变化？",
      "preferred_headings": ["管理层讨论与分析"]
    },
    {
      "requirement_id": "req-02",
      "topic": "technology_advantage",
      "question": "公司披露了哪些技术优势？",
      "preferred_headings": []
    }
  ],
  "reports": [
    {
      "announcement_id": "1225475344",
      "report_period": "2026-06-30",
      "report_type": "semiannual",
      "document_role": "full_report"
    }
  ],
  "retrieval": {
    "top_k": 8,
    "adjacent_window": 1,
    "max_context_characters": 16000
  },
  "constraints": {
    "chunks_only": true,
    "exclude_financial_report_section": true,
    "allow_pdf": false,
    "allow_pages": false,
    "allow_sections": false,
    "allow_network": false,
    "allow_crawler": false,
    "allow_financial_table_analysis": false,
    "allow_investment_advice": false,
    "require_llm": true
  }
}
```

`announcement_id` 由 Supervisor 授权，加载器只会解析：

```text
data/stocks/<stock_code>/processed/reports/<announcement_id>/chunks.jsonl
```

加载器拒绝路径穿越，并核对每条记录的 `announcement_id`。由于 Agent 不读取 manifest，
Supervisor 必须保证任务中的报告已经过完整报告识别和内容验证。

## 检索流程

1. 逐行扫描授权报告的 `chunks.jsonl`，但不把全部正文交给 LLM。
2. 排除禁止章节和正文中残留的禁止章节标题。
3. 根据主题目录和上游 `preferred_headings` 执行 heading 命中。
4. 只在命中章节内按主题关键词给正文评分。
5. 每个 requirement 独立判断 heading 和正文关键词；同一 chunk 分别命中多个 requirement
   时，将对应 Topic 精确合并到 `allowed_claim_types`。
6. 每个需求保留 `top_k` 个主要 chunk，并在同一章节内补充有限相邻 chunk。相邻关系只授予
   上下文读取资格，不会自动继承主 chunk 的 Topic；相邻 chunk 必须对该 requirement 重新
   匹配成功才能获得结论授权。
7. 按 `max_context_characters` 控制发送给推理器的总文本量。
8. 没有 heading 或正文证据时返回 `insufficient_data`，不调用 LLM。

第一版采用可解释的 heading、章节和关键词评分，不使用向量数据库。当前 `heading` 是一级章节，
因此 heading 用于章节准入，正文关键词用于选择具体 chunk。

## LLM与证据校验

默认使用统一 DeepSeek 配置。`ReportClaim.topic` 使用 `Literal` 枚举，合法主题会进入提供给模型的
JSON Schema。每条非 `not_determinable` 结论必须引用存在的 `evidence_id`，校验器同时检查：

- topic 是本次任务请求的主题；
- evidence 来自上游授权报告；
- evidence 不属于禁止章节；
- evidence 的主题权限能够支持该 claim。

每条 Evidence 除 `allowed_claim_types` 外，还输出 `authorization_details`，记录每个获授权
Topic 的 `requirement_ids`、`match_reasons` 和 `matched_keywords`，便于审计授权来源。

校验器按单条 Claim 隔离错误：一条结论不合规时，只剔除该条，其他通过校验的 LLM 结论继续
进入结果，此时 `llm_used=true`。结果通过 `dropped_claim_count` 和
`claim_validation_issues` 记录剔除数量、结论序号、错误类型和证据 ID。为防止原始 summary
夹带已剔除结论，只要发生隔离，summary 就根据保留结论确定性重建。如果全部 Claim 都无效，
才整体降级为确定性检索并令 `llm_used=false`；无法解析成 `ReportLLMAnalysis` 的 Schema 级
错误仍然需要整体降级。

公司披露的市场份额、行业地位和优势必须使用“公司在财报中披露”等限定表述，不能视为已经
外部独立验证。

## LangGraph节点

```text
validate_and_load_authorized_chunks
→ match_headings_and_rank_chunks
→ report_llm_reasoning
→ verify_and_finalize
```

该子图不负责决定自己何时运行。未来 Supervisor 应在汇总其他专业 Agent 的
`unresolved_requirements` 后，通过条件边决定保持待命或调用本子图。

## CLI冒烟测试

CLI 只是 Supervisor 适配器，必须显式提供授权报告 ID：

```powershell
python -m get_stock analyze report "分析000001的技术优势和核心竞争力" `
  --report-id 1225475344
```

离线检查检索与边界：

```powershell
python -m get_stock analyze report "分析000001的技术优势" `
  --report-id 1225475344 `
  --no-llm
```

`--supplement` 为默认模式；独立验证时可传入 `--direct`。数据完全不足时，即使默认要求 LLM，
也会跳过模型调用。
