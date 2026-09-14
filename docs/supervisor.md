# Supervisor 1.4

Supervisor 是股票分析的唯一编排入口。问题理解节点先把自然语言转换成受 Schema 限制的
标准请求；Supervisor 再通过固定 Catalog 规划 Agent 和数据需求。爬虫由独立的
`DataAcquisitionCoordinator` 管理，Supervisor 不直接运行命令或访问 Spider。

## 调用

```powershell
python -m get_stock analyze stock "综合分析000001最近三年的盈利、估值和股东变化"
```

默认使用 `.env` 中的 DeepSeek 配置。离线验证使用：

```powershell
python -m get_stock analyze stock "分析000001的盈利质量" --no-llm
```

常用开关：

- `--report-fallback/--no-report-fallback`：是否允许自动选择本地已处理完整财报；默认开启。
- `--auto-crawl/--no-auto-crawl`：是否在专业 Agent 运行前自动补采缺失的必需结构化数据；
  默认关闭，最多执行一轮。
- `--auto-documents/--no-auto-documents`：是否自动补充完整年报/半年报PDF并生成chunks；
  默认关闭，最多执行一轮、每次最多3份。
- `--auto-run`：同时开启结构化数据补采和完整财报恢复。
- `--max-documents`、`--heading-mode`：控制单次文档数量及章节识别模式。
- `--as-of`、`--period-from`、`--period-to`：限制分析日期范围。

## 执行边界

1. 启用 LLM 时，问题理解节点对每个问题优先调用 DeepSeek，输出 Topic、`time_intent`、
   `document_intent` 和受限回看参数；输出必须通过 `SupervisorPlanDraft` 和
   `QuestionUnderstanding` 校验。规则结果只作为模型提示和失败回退。
2. Supervisor 通过固定 Catalog 将 Topic 映射到 Financial、Market Trading、Shareholder
   或 Report Agent，不再解释原始自然语言。
3. 缓存检查节点在专业 Agent 之前检查必需文件是否存在且非空。
4. 开启 `--auto-crawl` 时，缺失的必需结构化数据交给独立采集协调器。协调器只接受数据集
   名称，并通过固定 `Crawler Registry` 合并、串行执行 Spider；不接受 shell 命令。
5. 日期解析器把报告期和巨潮公告披露检索期分开计算；显式CLI日期优先，相对日期按
   `as_of_date` 确定性解析。
6. 开启 `--auto-documents` 时，独立文档协调器先处理已有PDF；不足时通过固定子进程参数调用
   公告Spider，只下载完整报告，再生成pages/headings/sections/chunks并刷新任务。
7. Report Agent 只会获得公告注册表中 `document_role=full_report` 且本地存在
   `processed/reports/<announcement_id>/chunks.jsonl` 的报告。
8. Comprehensive Agent 只接收专业 Agent 的完整结构化结果。
9. 任一采集、处理或专业 Agent 失败不会抹掉其他 Agent 已生成的证据。

LLM 不能指定 Agent 类、文件路径、公告 ID 或爬虫命令。DeepSeek 只能输出候选 Topic、时间
意图、文档需求和有限的回看参数；Topic 还会根据运行时 Agent 注册表再次校验，随后由确定性
Router 执行。任何问题的模型调用失败时都会使用规则规划，并在 `understanding.json` 和
`plan.json` 记录 `deterministic_fallback`。`--no-llm` 则完全使用规则，不尝试调用模型。

`time_intent` 记录 `latest`、`recent_years`、`recent_periods`、`recent_sessions` 或
`absolute_range` 等语义。CLI 显式传入的 `--period-from/--period-to` 优先于模型推断。
`document_intent` 表达是否需要完整财报或普通公告；只有用户显式开启 `--auto-documents`
或 `--auto-run` 后才产生下载授权。当前自动链只支持完整年度、半年度报告；普通公告仍只记录
需求，不会自动下载或分析。

综合 Agent 的 LLM 输出若包含未请求 Topic、无效 Finding ID 或其他非法证据引用，会放弃该
LLM 结果并使用确定性综合，确保仍能生成 `result.json` 和 `report.md`。降级原因记录在最终
`limitations` 中。

## 状态

- `completed`：综合 Agent 认为所有必要需求均已回答。
- `partial`：存在有效证据，但部分需求缺失或冲突。
- `insufficient_data`：现有专业结果不足以回答问题。
- `failed`：综合阶段无法生成合法结果。

结构化自动补采授权 company、financials、market、shareholders、trading 五类Spider。文档恢复
固定为 `cninfo_announcements + reports + full + download_pdf`，最大查询跨度5年、单任务最多
6份，不接受LLM提供的命令、URL或公告ID。

## 产物

Supervisor 写入：

```text
data/stocks/<stock_code>/analysis/supervisor/<task_id>/
├── request.json
├── understanding.json
├── resolved_dates.json
├── plan.json
├── cache_snapshot.json
├── acquisition.json
├── document_acquisition.json
├── specialist_results/
├── result.json
└── state.json
```

综合 Agent 仍独立写入：

```text
data/stocks/<stock_code>/analysis/comprehensive/<task_id>/
├── result.json
├── report.md
└── state.json
```

Supervisor 的 `artifacts.markdown` 和 `artifacts.comprehensive_result` 指向综合产物，避免复制
两份最终报告。

## LangGraph

`build_supervisor_graph()` 提供七个稳定节点：

```text
understand_question
→ build_analysis_plan_and_inspect_cache
→ recover_missing_structured_data
→ recover_and_process_documents
→ route_and_execute_specialists
→ build_and_execute_comprehensive_task
→ write_supervisor_artifacts
```

同步 CLI 与 LangGraph 共用同一个 `StockAnalysisSupervisor`，因此任务校验、路由和产物规则
不会分叉。
