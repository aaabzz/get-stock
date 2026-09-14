# 股票分析命令使用指南

版本：1.0

本文面向直接使用 `get-stock` 命令行进行股票分析的用户，说明如何编写问题、如何开启自动
数据补充、系统会调用哪些 Agent，以及如何核对问题是否被正确理解。

## 1. 推荐命令

完整自动分析命令：

```powershell
python -m get_stock analyze stock `
  "综合分析688449最近三年的盈利能力、估值和股东变化" `
  --auto-run `
  --max-documents 3 `
  --heading-mode auto
```

`analyze stock` 默认使用项目 `.env` 中配置的 DeepSeek。没有配置密钥时，CLI 会通过隐藏输入
提示用户输入。只检查本地数据、不联网补采且不调用模型时，可以使用：

```powershell
python -m get_stock analyze stock `
  "分析688449的盈利能力和估值" `
  --no-llm
```

## 2. 如何编写问题

推荐使用以下结构：

```text
股票代码 + 时间范围 + 分析维度 + 可选的数据来源要求
```

示例：

```text
分析688449最近三年的盈利能力、当前估值和十大股东变化。
```

```text
分析688449最近120个交易日的价格趋势、成交量和波动风险。
```

```text
根据688449最近三份完整年度报告，分析主营业务、行业地位和核心技术优势。
```

不建议只输入：

```text
看看688449怎么样。
```

```text
分析688449的风险。
```

这类问题没有明确分析维度，模型可能选择范围过宽的 Topic。问题中不包含六位股票代码且
没有使用 `--stock-code` 时，命令会返回 `a six-digit stock code is required`，不会进入分析
工作流。

## 3. 常用分析表达

Supervisor 使用 DeepSeek 语义理解，并把结果限制在已注册的 Topic 白名单中；模型调用失败时
使用关键词规则降级。常用表达与路由如下。

| 用户表达 | Topic | 负责模块 |
| --- | --- | --- |
| 收入增长、净利润增长、成长性 | `growth` | 财务 Agent |
| 盈利能力、ROE、毛利率、净利率 | `profitability` | 财务 Agent |
| 盈利质量、利润是否有现金流支撑 | `earnings_quality` | 财务 Agent |
| 负债率、流动比率、偿债能力 | `solvency` | 财务 Agent |
| 经营现金流、现金含量 | `cash_flow` | 财务 Agent |
| 股价趋势、涨跌表现 | `price_trend` | 市场交易 Agent |
| 波动、回撤、振幅 | `volatility` | 市场交易 Agent |
| 成交量、流动性 | `liquidity` | 市场交易 Agent |
| PE、PB、PS、估值 | `valuation` | 市场交易 Agent |
| 融资融券 | `margin_activity` | 市场交易 Agent |
| 大宗交易 | `block_trades` | 市场交易 Agent |
| 十大股东变化、大股东持仓变化 | `major_holder_changes` | 股东 Agent |
| 股东集中度 | `shareholder_concentration` | 股东 Agent |
| 股东人数 | `shareholder_count` | 股东 Agent |
| 基金持股 | `fund_holdings` | 股东 Agent |
| 限售解禁、解禁压力 | `restricted_unlocks` | 股东 Agent |
| 股权质押、解除质押 | `equity_pledges` | 股东 Agent |
| 主营业务、业务模式 | `business_overview` | 财报 Agent |
| 行业地位、市场排名、竞争格局 | `industry_position` | 财报 Agent |
| 市占率、市场份额 | `market_share_disclosure` | 财报 Agent |
| 核心竞争力、竞争优势 | `competitive_advantage` | 财报 Agent |
| 核心技术、技术代际 | `technology_advantage` | 财报 Agent |
| 研发能力、研发情况 | `research_and_development` | 财报 Agent |
| 经营风险、风险因素、主要挑战 | `business_risks` | 财报 Agent |

## 4. 风险类问题

当前没有单独的 Risk Agent。Supervisor 会根据风险类型分派给相应专业 Agent，因此应尽量
说明风险来源。

| 风险表达 | 典型 Topic | 主要证据 |
| --- | --- | --- |
| 偿债风险、负债风险 | `solvency` | 财务指标、资产负债表、现金流量表 |
| 盈利质量风险 | `earnings_quality` | 利润表、现金流量表 |
| 股价波动或回撤风险 | `volatility` | 历史行情 |
| 流动性风险 | `liquidity` | 历史行情、行情快照 |
| 质押风险 | `equity_pledges` | 股权质押记录 |
| 解禁压力 | `restricted_unlocks` | 限售解禁记录 |
| 财报披露的经营风险 | `business_risks` | 完整财报相关 chunks |

多维风险示例：

```powershell
python -m get_stock analyze stock `
  "分析688449最近三年的偿债风险、盈利质量、股价波动和股权质押风险" `
  --auto-run
```

需要完整财报披露信息时，应在问题中明确写出“完整年报”“经营风险”等要求：

```powershell
python -m get_stock analyze stock `
  "结合688449最近三份完整年报，分析经营风险、竞争优势和未来发展挑战" `
  --auto-run `
  --max-documents 3
```

## 5. 自动化开关

| 参数 | 作用 |
| --- | --- |
| `--llm` / `--no-llm` | 开启 DeepSeek 或使用离线规则；默认开启 DeepSeek |
| `--auto-crawl` | 自动补采缺失的必需结构化数据 |
| `--auto-documents` | 当计划需要完整财报时，自动补充 PDF 和 chunks |
| `--auto-run` | 同时开启 `--auto-crawl` 和 `--auto-documents` |
| `--report-fallback` | 允许财报 Agent 使用已经处理的完整财报；默认开启 |
| `--max-documents N` | 单次任务最多恢复的完整财报数量，范围为 1 到 6 |
| `--heading-mode rules` | 只用规则识别财报标题，适合完全离线运行 |
| `--heading-mode auto` | 规则优先，未分类候选再交给 LLM；默认模式 |
| `--heading-mode llm` | 将全部规则标题候选交给 LLM 分类 |
| `--period-from` / `--period-to` | 显式设置分析起止日期，格式为 `YYYY-MM-DD` |
| `--as-of` | 设置分析基准日期，便于历史回测或固定结果 |

`--auto-run` 只表示授权两类恢复流程，不会无条件下载 PDF。只有问题被规划为财报类 Topic，且
`document_intent.needs_full_report=true` 时，系统才会查找或下载完整年报、半年报并生成 chunks。

当前自动文档链不处理普通公告分析。普通公告虽然可以单独爬取和下载，但公告 Agent 尚未接入
Supervisor。

## 6. 时间范围说明

自然语言中的“最近三年”会形成结构化时间意图，但当前不同 Agent 的回看单位并不完全相同：

- 财务 Agent 通常按最近三个报告期分析；
- 股东 Agent 按报告期记录数量分析，默认最多四期；
- 市场交易 Agent 按交易日分析，默认最多六十个交易日；
- 完整财报恢复会把报告期和公告披露搜索日期分开计算。

需要所有模块严格使用固定日期时，建议显式指定：

```powershell
python -m get_stock analyze stock `
  "分析688449的盈利、估值和股东变化" `
  --period-from 2023-01-01 `
  --period-to 2025-12-31 `
  --auto-run
```

历史行情不等于历史估值。如果问题要求“三年 PE/PB 分位”，本地只有最新行情快照时，市场
Agent 应返回数据不足，而不能用最新 PE/PB 推断三年估值趋势。

## 7. 如何核对理解和路由

每次 Supervisor 任务的过程文件保存在：

```text
data/stocks/<stock_code>/analysis/supervisor/<task_id>/
```

首先检查 `understanding.json`：

```json
{
  "stock_code": "688449",
  "topics": [
    "profitability",
    "valuation",
    "major_holder_changes"
  ],
  "time_intent": {
    "mode": "recent_years",
    "count": 3
  },
  "document_intent": {
    "needs_full_report": false,
    "needs_announcements": false
  },
  "interpreter_mode": "deepseek",
  "llm_used": true
}
```

然后检查 `plan.json` 中的 `expected_agents`：

```json
{
  "expected_agents": [
    "financial_analysis",
    "market_trading",
    "shareholder_analysis"
  ]
}
```

其余常用诊断文件：

| 文件 | 用途 |
| --- | --- |
| `resolved_dates.json` | 自动计算的报告期和披露搜索日期 |
| `cache_snapshot.json` | 分析前后的本地数据可用性 |
| `acquisition.json` | 结构化数据自动补采状态 |
| `document_acquisition.json` | 完整财报查找、下载和处理状态 |
| `specialist_results/` | 各专业 Agent 的结构化输出 |
| `result.json` | Supervisor 最终状态和产物路径 |
| `state.json` | 本次任务的完成状态 |

## 8. 最终报告

综合 Agent 的产物保存在：

```text
data/stocks/<stock_code>/analysis/comprehensive/<task_id>-comprehensive/
```

其中：

- `report.md`：适合人工阅读的综合报告；
- `result.json`：完整结构化结果和证据链；
- `state.json`：综合任务状态。

CLI 返回结果中的 `artifacts.markdown` 是本次 `report.md` 的准确路径。

可能出现的状态：

| 状态 | 含义 |
| --- | --- |
| `completed` | 所有必要分析要求均有有效证据 |
| `partial` | 部分要求有证据，部分数据缺失或存在冲突 |
| `insufficient_data` | 没有足够证据回答主要问题 |
| `failed` | 综合任务未能生成有效结果 |

某个专业 Agent 失败时，Supervisor 会隔离该失败并继续运行其他 Agent。结论必须引用合法的
`evidence_id`；模型输出未通过 Topic 或证据校验时，会降级为确定性结果或记录为失败。

## 9. 使用边界

- 输出仅基于当前本地结构化数据、已下载完整财报和经过校验的 Agent 证据；
- 系统不预测未来股价，也不提供买入、卖出或目标价建议；
- 财报中的市场份额、行业地位等内容属于公司披露，应与独立行业数据交叉验证；
- 数据不足会明确写入 `missing_data`，不应把 `partial` 当作完整结论；
- 自动爬取应保持低频，并遵守目标网站的服务条款、robots 规则和数据授权要求；
- API 密钥只应保存在本地 `.env`，不要写入命令、报告或提交到版本库。

