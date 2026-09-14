# 综合分析 Agent（v1.0）

## 定位

综合分析 Agent 是 Supervisor 调度流程的最后一个专业子图。它只消费财务、市场交易、股东和
财报定性 Agent 的稳定结果，不直接读取本地股票原始数据、PDF、财报 chunk，不调用网络、爬虫
或其他 Agent。

Supervisor 决定本次需要哪些专业 Agent；未被某项需求声明为必要的 Agent 即使没有运行，也不
会被综合分析 Agent 判定为缺失。

## 流程

```text
校验Supervisor任务
→ 校验并标准化专业Agent结果
→ 为Finding和Evidence增加Agent命名空间
→ 过滤到本次需求相关的Finding
→ 检查需求覆盖度
→ 检测可机械确认的同口径数值冲突
→ DeepSeek结构化综合分析
→ 校验最终Claim与Finding引用
→ 生成result.json
→ 从已校验JSON确定性渲染report.md
→ 最后写入state.json
```

数据完全不足时跳过 LLM，但仍生成 JSON、Markdown 和 state。

## 输入契约

综合 Agent 不接收自然语言后自行调度。生产环境中应接收 Supervisor 生成的
`ComprehensiveAnalysisTask`：

```json
{
  "task_id": "synthesis-task-001",
  "parent_task_id": "supervisor-task-001",
  "stock_code": "000001",
  "question": "综合分析盈利质量和技术优势",
  "requirements": [
    {
      "requirement_id": "req-financial",
      "topic": "earnings_quality",
      "question": "盈利质量如何？",
      "required_agents": ["financial_analysis"]
    },
    {
      "requirement_id": "req-technology",
      "topic": "technology_advantage",
      "question": "公司披露了哪些技术优势？",
      "required_agents": ["financial_report_analysis"]
    }
  ],
  "expected_agents": [
    "financial_analysis",
    "financial_report_analysis"
  ],
  "agent_results": [
    {
      "agent": "financial_analysis",
      "result": {
        "agent": "financial_analysis",
        "...": "完整的FinancialAnalysisResult"
      }
    },
    {
      "agent": "financial_report_analysis",
      "result": {
        "agent": "financial_report_analysis",
        "...": "完整的ReportAnalysisResult"
      }
    }
  ],
  "constraints": {
    "consume_specialist_results_only": true,
    "allow_local_source_data": false,
    "allow_pdf": false,
    "allow_network": false,
    "allow_crawler": false,
    "allow_agent_dispatch": false,
    "allow_recalculation": false,
    "allow_investment_advice": false,
    "write_markdown": true,
    "require_llm": true
  }
}
```

`agent_results[*].result` 必须是对应专业 Agent 的完整 JSON 输出，示例中的省略字段不能用于
实际调用。

## 标准化与证据链

专业 Agent 的原始 Evidence ID 可能都叫 `e0001`。综合层增加来源命名空间：

```text
financial_analysis:e0001
market_trading:e0001
shareholder_analysis:e0001
financial_report_analysis:re0001
```

专业 Claim 被转换为 `FindingEnvelope`，例如：

```json
{
  "finding_id": "financial_analysis:f0001",
  "source_agent": "financial_analysis",
  "topics": ["earnings_quality"],
  "claim": "经营现金流对利润形成支持",
  "source_evidence_ids": ["financial_analysis:e0001"]
}
```

最终综合 Claim 引用 `finding_id`，Finding 再引用专业 Evidence，形成：

```text
综合Claim → Finding → 专业Evidence → 原始字段或财报chunk
```

财务 Agent 的 Claim 没有显式 topic，适配器通过
`dimensions.<topic>.findings[*].evidence_ids` 反向确定主题，不根据中文结论文本猜测。

## 状态与覆盖度

每项要求状态为：

- `answered`：存在可验证 Finding，必要 Agent 均提供有效结果；
- `partially_answered`：只有部分支持，或者必要 Agent 未提供有效结果；
- `unanswered`：没有可验证 Finding；
- `conflicted`：发现尚未解决的同口径数值冲突。

整体状态为 `completed`、`partial` 或 `insufficient_data`。综合置信度由系统根据需求覆盖、
专业 Finding 置信度、来源权重和冲突惩罚计算，不直接平均 LLM 自评值。财报定性来源权重低于
结构化专业 Agent，因为行业地位和优势属于公司披露、未经过外部验证。

## LLM边界

DeepSeek 只接收与本次 requirements 相关的 Finding 及其引用 Evidence。输出使用严格枚举。
每条非 `not_determinable` 综合结论必须引用真实且主题匹配的 `finding_id`。校验器拒绝：

- 未请求主题；
- 不存在的 Finding；
- 跨主题 Finding；
- 没有专业证据链的确定性 Finding；
- 买入、卖出和目标价等投资建议。

结构化专业 Agent 的定量结论优先于财报叙述，但冲突不会被静默覆盖。

## 输出产物

每个任务写入独立目录：

```text
data/stocks/<stock_code>/analysis/comprehensive/<task_id>/
├── result.json
├── report.md
└── state.json
```

`report.md` 不单独调用 LLM，而是从已经校验的 `ComprehensiveAnalysisResult` 确定性生成，包含：

- 综合结论；
- 问题覆盖情况；
- 主要优势和风险；
- 趋势与其他发现；
- 专业 Agent 摘要；
- 冲突和缺失数据；
- Finding 到 Evidence 的两级索引；
- 分析限制和非投资建议声明。

`state.json` 最后写入，作为产物完成标志。三个文件均使用 UTF-8 和原子替换。

## LangGraph

```text
normalize_and_verify_specialist_results
→ comprehensive_llm_reasoning
→ render_and_write_analysis_artifacts
```

该子图不具备调度权。数据缺口只会写入结果，后续是否再次采集或调用 Agent 必须由 Supervisor
决定。

## CLI

CLI 使用任务文件模拟 Supervisor：

```powershell
python -m get_stock analyze comprehensive synthesis-task.json
```

离线验证：

```powershell
python -m get_stock analyze comprehensive synthesis-task.json --no-llm
```

默认从 `.env` 读取统一 DeepSeek 配置。CLI 返回结构化结果，同时在结果的 `artifacts` 字段中
给出三个输出文件的绝对路径。
