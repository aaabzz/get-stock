# get-stock

版本：1.0

`get-stock` 是一个面向巨潮资讯网的个股信息采集项目。v1.0 可以根据股票代码获取证券信息、公告元数据和公告 PDF，并可在本地独立处理完整财报 PDF；不引入数据库、分布式调度、代理池或浏览器自动化。

## v1.0 目标

- 接收六位股票代码和日期范围。
- 解析证券简称、交易市场和巨潮 `orgId`。
- 分页采集个股公告标题、发布日期、分类和附件地址。
- 将结构化数据追加保存为 JSON Lines（JSONL）。
- 将新增公告 PDF 下载到本地目录。
- 采集公司介绍、高管和历史分红。
- 独立采集顶部财务摘要、主要指标和三张财务报表。
- 独立采集股本结构、股东人数、十大股东、限售解禁和股权质押。
- 独立采集最近六个月融资融券和最近五年大宗交易记录。
- 尝试采集行情快照和日线历史，并独立记录暂不可用的数据集。
- 根据公告 ID 去重，支持中断后继续采集。
- 对请求进行限速、重试和异常熔断。
- 保留少量原始响应，方便排查接口变化。
- 对已验证的完整财报执行逐页提取、文本清洗、章节识别和 Chunk 切分。
- 按 PDF 哈希与处理器版本缓存处理结果，并保留页码和章节来源。
- 使用白名单结构化数据执行第一版财务分析，不读取 PDF、网络或爬虫。

## 技术栈

| 技术 | 用途 |
| --- | --- |
| Python 3.10+ | 开发语言 |
| Scrapy | 请求调度、翻页、重试和限流 |
| JSONL | 本地结构化数据存储 |
| Scrapy FilesPipeline | 公告 PDF 下载 |
| pydantic-settings | 环境变量和配置管理 |
| pypdf | PDF 文件校验和基础文本提取 |
| Typer | 命令行入口 |
| pytest | 单元测试和集成测试 |
| Ruff | 代码格式化与静态检查 |

v1.0 暂不使用 SQLite、PostgreSQL、Redis、Celery、Playwright、Selenium、代理池、验证码识别和 OCR。

## 方案流程

```text
股票代码和日期范围
        ↓
校验股票代码
        ↓
解析证券简称、市场和 orgId
        ↓
保存证券信息和原始响应
        ↓
分页请求公告列表
        ↓
标准化公告字段并按公告 ID 去重
        ↓
追加写入 cleaned/announcements.jsonl
        ↓
下载并校验新增公告 PDF
        ↓
更新 state/crawl_state.json
        ↓
输出采集统计

已验证的完整财报（独立 PDF 处理入口）
        ↓
逐页提取 → 文本清洗 → 章节识别 → 章节内 Chunk
        ↓
写入 processed/reports/<announcement_id>/
```

PDF 处理模块目前是独立的本地预处理层，不会自动调用 LangChain、Retriever、LLM 或任何分析 Agent。
完整的输入输出契约、状态和缓存规则见 [PDF 处理模块设计](docs/pdf-processing.md)。

## 项目结构

```text
get-stock/
├─ README.md
├─ requirements.txt
├─ pyproject.toml
├─ scrapy.cfg
├─ main.py
├─ src/
│  └─ get_stock/
│     ├─ cli.py
│     ├─ config.py
│     ├─ items.py
│     ├─ parsers.py
│     ├─ pdf_validation.py
│     ├─ documents/
│     │  ├─ extractor.py
│     │  ├─ cleaner.py
│     │  ├─ segmenter.py
│     │  ├─ chunker.py
│     │  └─ processor.py
│     ├─ financial_agent/
│     │  ├─ agent.py
│     │  ├─ catalog.py
│     │  ├─ graph.py
│     │  ├─ intent.py
│     │  ├─ loaders.py
│     │  ├─ metrics.py
│     │  ├─ reasoner.py
│     │  ├─ schemas.py
│     │  └─ verifier.py
│     ├─ settings.py
│     ├─ spiders/
│     │  ├─ base.py
│     │  ├─ announcements.py
│     │  ├─ company.py
│     │  ├─ market.py
│     │  ├─ financials.py
│     │  ├─ shareholders.py
│     │  └─ trading.py
│     ├─ middlewares/
│     │  └─ response_guard.py
│     └─ pipelines/
│        ├─ jsonl.py
│        ├─ documents.py
│        ├─ company.py
│        ├─ market.py
│        ├─ financials.py
│        ├─ shareholders.py
│        └─ trading.py
├─ data/
└─ tests/
   ├─ test_cli.py
   ├─ test_parsers.py
   ├─ test_response_guard.py
   ├─ test_spider.py
   ├─ test_storage.py
   └─ test_live_cninfo.py
```

## 本地输出

```text
data/
├─ stocks/
│  └─ 000001/
│     ├─ cleaned/
│     │  ├─ security.json
│     │  ├─ announcements.jsonl
│     │  ├─ company_profile.json
│     │  ├─ executives.jsonl
│     │  ├─ dividends.jsonl
│     │  ├─ market_snapshot.json
│     │  ├─ market_history.jsonl
│     │  ├─ financial_summary.json
│     │  ├─ financial_indicators.jsonl
│     │  ├─ balance_sheets.jsonl
│     │  ├─ income_statements.jsonl
│     │  ├─ cash_flow_statements.jsonl
│     │  ├─ stock_structure.jsonl
│     │  ├─ shareholder_counts.jsonl
│     │  ├─ fund_holdings.jsonl
│     │  ├─ top_ten_shareholders.jsonl
│     │  ├─ top_ten_float_shareholders.jsonl
│     │  ├─ restricted_unlocks.jsonl
│     │  ├─ equity_pledges.jsonl
│     │  ├─ margin_trading.jsonl
│     │  └─ block_trades.jsonl
│     ├─ pretty/
│     │  ├─ security.json
│     │  ├─ company_profile.json
│     │  ├─ financial_summary.json
│     │  ├─ announcements.json
│     │  ├─ executives.json
│     │  ├─ dividends.json
│     │  ├─ market_history.json
│     │  └─ 其他清洗数据对应的可读 JSON
│     ├─ raw/
│     ├─ documents/
│     │  ├─ reports/
│     │  │  ├─ annual/
│     │  │  ├─ semiannual/
│     │  │  ├─ first_quarter/
│     │  │  └─ third_quarter/
│     │  └─ announcements/
│     ├─ processed/
│     │  └─ reports/
│     │     └─ <announcement_id>/
│     │        ├─ pages.jsonl
│     │        ├─ headings.jsonl
│     │        ├─ sections.jsonl
│     │        ├─ chunks.jsonl
│     │        └─ manifest.json
│     └─ state/
│        ├─ crawl_state.json
│        ├─ company_crawl_state.json
│        ├─ market_crawl_state.json
│        ├─ financial_crawl_state.json
│        ├─ shareholder_crawl_state.json
│        ├─ trading_crawl_state.json
│        ├─ crawl_all_state.json
│        └─ pdf_processing_state.json
└─ logs/
   └─ crawl.log
```

- `cleaned/`：解析、标准化后的正式数据，供程序处理；其中 `security.json` 保存证券代码、简称、市场和 `orgId`。
- `pretty/`：`cleaned/` 的完整可读镜像；JSONL 转换为缩进 JSON 数组，单对象 JSON 同名同步，只用于人工查看。
- `state/`：各 Spider 的断点、完成情况、失败信息和组合任务汇总状态。
- `announcements.jsonl`：每行一条公告或定期财报元数据；使用 `document_type` 区分 `financial_report` 和 `announcement`，财报同时包含 `report_type`、`report_period`、`is_summary` 和 `is_revision`。
- `pretty/announcements.json`：自动生成的缩进格式公告数组，供人工查看。
- `crawl_state.json`：日期范围、最后成功页和任务状态。
- `company_profile.json`：标准化公司介绍；当前行业使用 `industry_name`、`industry_source`、`industry_standard` 和 `industry_as_of` 字段。
- `executives.jsonl`：当前高管列表。
- `pretty/executives.json`：自动生成的缩进格式高管数组，供人工查看。
- `dividends.jsonl`：历史分红记录。
- `pretty/dividends.json`：自动生成的缩进格式分红数组，供人工查看。
- `company_crawl_state.json`：公司资料各模块采集状态。
- `market_snapshot.json`：最新价、成交量、市盈率、市净率、换手率和计算市值；仅在巨潮行情服务返回有效数据时生成。
- `market_history.jsonl`：日线开高低收和成交量；仅在历史行情接口返回有效数据时生成。
- `pretty/market_history.json`：日线历史的缩进 JSON 数组，供人工查看。
- `market_crawl_state.json`：行情各数据集的成功、失败及记录数量。
- `financial_summary.json`：总股本、流通股本、ROE、负债率、净利润和营业收入等摘要。
- `financial_indicators.jsonl`：按报告期保存每股、成长、偿债、运营和盈利指标。
- `balance_sheets.jsonl`、`income_statements.jsonl`、`cash_flow_statements.jsonl`：按报告期保存三张财务报表。
- `financial_crawl_state.json`：财务各数据集的成功、失败及记录数量。
- `stock_structure.jsonl`：历次股本结构变动。
- `shareholder_counts.jsonl`：最近五年的股东人数及变动幅度。
- `fund_holdings.jsonl`：根据基金定期报告统计的最近五年基金覆盖家数和基金合计持股数，不包含逐只基金明细。
- `top_ten_shareholders.jsonl`、`top_ten_float_shareholders.jsonl`：十大股东和十大流通股东。
- `restricted_unlocks.jsonl`、`equity_pledges.jsonl`：限售解禁和最近五年股权质押记录。
- `shareholder_crawl_state.json`：股东股本各数据集的成功、失败及记录数量。
- `margin_trading.jsonl`：最近六个月逐交易日融资余额、融资买入额、融券余量、融券卖出量、融券余额及两融余额；金额单位为元，数量单位为股。
- `block_trades.jsonl`：最近五年大宗交易价格、成交量、成交金额、买方和卖方；成交量单位为万股，成交金额单位为万元。
- `trading_crawl_state.json`：融资融券和大宗交易两个数据集的成功、失败及记录数量。
- `crawl_all_state.json`：组合采集任务中各 Spider 的成功、部分成功或失败状态。
- `raw/`：用于调试的原始响应。
- `documents/reports/<report_type>/<year>/`：按财报类型和年份保存年度、半年度及季度报告 PDF。
- `documents/announcements/<year>/`：按年份保存普通公告 PDF。
- `processed/reports/<announcement_id>/pages.jsonl`：清洗后的逐页文本及提取状态，保留原始页码。
- `processed/reports/<announcement_id>/headings.jsonl`：章节边界、原始标题、标准类型、分类方式和置信度。
- `processed/reports/<announcement_id>/sections.jsonl`：规则识别后的章节文本、章节类型和页码范围。
- `processed/reports/<announcement_id>/chunks.jsonl`：限制在单一章节内的检索粒度文本块，保留章节和页码来源。
- `processed/reports/<announcement_id>/manifest.json`：源 PDF 哈希、处理版本、参数、质量指标和输出清单，是缓存判定依据。
- `pdf_processing_state.json`：`pdf process-all` 的成功、失败和缓存命中摘要。

## 安装依赖

建议在项目虚拟环境中执行：

```powershell
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
```

第二条命令把当前项目安装为可编辑包，使 `get-stock` 和标准 `scrapy crawl` 命令可以找到 `src/get_stock` 包。

财务 Agent 的 LangChain/LangGraph 和模型 Provider 属于可选依赖，不影响单独使用爬虫：

```powershell
python -m pip install -r requirements-agent.txt
# 或
python -m pip install -e ".[agent,deepseek-agent]"
```

## 使用方式

推荐使用项目命令行入口：

```powershell
python -m get_stock crawl announcements 000001 `
  --start 2026-01-01 `
  --end 2026-08-29 `
  --download-pdf
```

只采集并下载定期财报，不保存普通公告：

```powershell
python -m get_stock crawl announcements 000001 `
  --start 2026-01-01 `
  --end 2026-08-29 `
  --reports `
  --no-regular-announcements `
  --report-scope full `
  --download-pdf
```

`--report-scope` 用于限定定期报告的文档角色，同时适用于 `crawl announcements`
和 `crawl all`：

| 值 | 保留的文档角色 |
| --- | --- |
| `all` | 全部报告类文档（默认） |
| `full` | 完整年度报告、完整半年度报告 |
| `summary` | 年报或半年报摘要 |
| `financial-statements` | 单独披露的财务报告/财务报表 |
| `assurance` | 审阅报告和审计报告 |

标题分类采用“报告名称严格后缀匹配 + 前缀风险词排除”，因此可兼容无前缀、股票简称、
公司全称及常见分隔符；含“关于”“延期”“问询”“审议”“披露”等风险词的前缀会被排除。
分类结果会生成 `document_role`，可能值为 `full_report`、`quarterly_report`、
`report_summary`、`financial_statements`、`review_report`、`audit_report`、
`report_related_notice` 或 `regular_announcement`。第一版只把标题精确匹配的年报和
半年报标记为 `is_full_report=true`；季报、摘要、单独财务报表和审阅/审计报告不会
被当作完整报告。

完整报告 PDF 下载后会做渐进式轻量验证：先读前 3 页确认公司名称、报告年度和类型，
再在前 10 页内寻找目录特征；一旦证据足够就立即停止。只有前 10 页无法确认时，才扩展到
最多 20 页。验证同时检查摘要误判，以及“管理层讨论与分析”“公司治理”“重要事项”“股份变动及股东情况”
“财务报告”等目录特征。验证结果写入 `content_validation_status`、`analysis_eligible`、
`page_count`、`requires_ocr`、`validation_page_limit`、`validated_pages`、`matched_sections` 和
`validation_errors`。
只有 `document_role=full_report` 且 `content_validation_status=passed` 时，
`analysis_eligible` 才为 `true`，后续 Agent 应以此作为入口条件。这一步不做全文分析，
也不执行 OCR。

## PDF 全文处理

先查看本地公告注册表中可供处理的完整财报：

```powershell
python -m get_stock pdf list 000001
```

处理指定完整财报（第二个参数是 `announcement_id`）：

```powershell
python -m get_stock pdf process 000001 1225475344
```

处理某只股票本地已经下载的全部完整财报：

```powershell
python -m get_stock pdf process-all 000001
```

默认 `chunk_size=1200`、`chunk_overlap=150`。可以通过 `--chunk-size` 和
`--chunk-overlap` 调整；使用 `--force` 可忽略有效缓存重新处理。缓存键同时包含源 PDF 的
SHA-256、清洗器/章节器/切分器版本、Chunk 参数、heading 模式及模型标识，因此 PDF、规则
或模型配置变化后会自动重新生成。

PDF处理命令默认使用 `--heading-mode auto`：规则先识别章节边界，未知“第X章”保持独立，
并在配置 DeepSeek 时交给结构化 LLM 分类。也可使用 `--heading-mode rules` 完全离线，或使用
`--heading-mode llm` 复核全部候选。LLM不能新增标题或页码，未通过原文与白名单校验的结果
会被丢弃。

处理入口只接受 `document_role=full_report` 且内容验证通过的文件。摘要、季报、单独财务报表、
审阅/审计报告和普通公告会被拒绝。旧公告记录若尚无内容验证字段，会先复用轻量 PDF 校验器做
兼容验证。全文质量状态包括 `success`、`partial` 和 `requires_ocr`；第一版只标记
`requires_ocr`，不执行 OCR。章节识别失败时仍会保留逐页文本并标记为 `partial`，不会伪造章节。

## 结构化数据财务分析 Agent

第一版财务 Agent 只读取 `cleaned/` 中经过白名单注册的结构化数据，不读取 PDF、
`processed/reports/`、`raw/` 或 `pretty/`，也不会访问网络或调用爬虫：

```powershell
python -m get_stock analyze financial "全面分析000001最近三年财务情况"
```

股票代码也可以通过参数提供：

```powershell
python -m get_stock analyze financial "分析最近三年盈利质量" `
  --stock-code 000001
```

指定报告类型、期数并保存 JSON：

```powershell
python -m get_stock analyze financial "分析半年报盈利能力" `
  --stock-code 000001 `
  --report-type semiannual `
  --years 3 `
  --output financial-analysis.json
```

支持成长、盈利、盈利质量、资产负债、偿债、运营效率、现金流、分红和股本结构主题。
数值计算由 Python 完成，每个结论绑定 `evidence_id`；数据不足时返回缺失清单，不自动采集。
当前三张报表没有显式金额单位，因此绝对值保留为 `source_statement_unit`，只对同口径数据
计算比率。具体边界、状态和输入输出契约见
[财务分析 Agent 设计](docs/financial-agent.md)。

生产环境中财务 Agent 不接收用户问题，而是接收 Supervisor 生成的
`FinancialAnalysisTask`，并把 `FinancialAnalysisResult` 交给综合分析 Agent。上面的 CLI
命令只用于模拟 Supervisor。模型统一配置为 DeepSeek 官方 OpenAI 兼容接口，默认
`deepseek-v4-pro` 和 `https://api.deepseek.com`。安装并测试 LangGraph/LangChain 接入：

```powershell
python -m pip install -e ".[agent,deepseek-agent]"
python -m get_stock analyze financial "分析000001盈利质量" `
  --llm
```

执行 `--llm` 时，如果没有设置 `DEEPSEEK_API_KEY`，CLI 会通过隐藏输入提示人工输入密钥；
密钥不会保存。也可以复制 `.env.example` 为 `.env` 后手工填写，`.env` 已加入 `.gitignore`。
完整模型配置和 Supervisor 初始化方法见 [财务分析 Agent 设计](docs/financial-agent.md)。

只采集普通公告：

```powershell
python -m get_stock crawl announcements 000001 `
  --start 2026-01-01 `
  --end 2026-08-29 `
  --no-reports `
  --regular-announcements
```

采集公司介绍、高管和历史分红：

```powershell
python -m get_stock crawl company 000001 --save-raw
```

采集行情快照与历史行情：

```powershell
python -m get_stock crawl market 000001 --save-raw
```

采集财务摘要、主要指标和三张财务报表：

```powershell
python -m get_stock crawl financials 000001 --save-raw
```

采集股本和股东资料：

```powershell
python -m get_stock crawl shareholders 000001 --save-raw
```

采集融资融券和大宗交易：

```powershell
python -m get_stock crawl trading 000001 --save-raw
```

一次串行执行全部 Spider：

```powershell
python -m get_stock crawl all 000001 `
  --start 2026-01-01 `
  --end 2026-08-31 `
  --save-raw
```

`crawl all` 默认运行公告、公司资料、行情、财务、股东和交易信息六个 Spider。它们共享一个
`CrawlerProcess` 和一个 Reactor，但按 Spider 严格串行执行，以避免多个 Crawler 各自的
单并发叠加成并发请求。关闭公告后不再要求日期：

```powershell
python -m get_stock crawl all 000001 --no-announcements
```

支持的参数：

| 参数 | 说明 |
| --- | --- |
| `stock_code` | 六位股票代码 |
| `--start` | 查询开始日期 |
| `--end` | 查询结束日期 |
| `--category` | 可选的公告分类 |
| `--max-pages` | 最大翻页数 |
| `--download-pdf` | 下载公告 PDF |
| `--reports/--no-reports` | 是否保留年度、半年度和季度财报，默认保留 |
| `--report-scope` | 报告角色范围：`all`、`full`、`summary`、`financial-statements` 或 `assurance` |
| `--regular-announcements/--no-regular-announcements` | 是否保留财报以外的普通公告，默认保留 |
| `--save-raw` | 保存原始响应 |
| `--pretty-json/--no-pretty-json` | 是否在 `pretty/` 中生成供人工查看的 JSON，默认生成 |
| `--snapshot/--no-snapshot` | 行情命令是否请求快照，默认请求 |
| `--history/--no-history` | 行情命令是否请求日线历史，默认请求 |
| `--announcements/--no-announcements` | 组合命令是否运行公告 Spider |
| `--company/--no-company` | 组合命令是否运行公司资料 Spider |
| `--market/--no-market` | 组合命令是否运行行情 Spider |
| `--financials/--no-financials` | 组合命令是否运行财务 Spider |
| `--shareholders/--no-shareholders` | 组合命令是否运行股东 Spider |
| `--trading/--no-trading` | 组合命令是否运行融资融券与大宗交易 Spider |

也可以使用标准 Scrapy 命令：

```powershell
scrapy crawl cninfo_announcements `
  -a stock_code=000001 `
  -a start_date=2026-01-01 `
  -a end_date=2026-08-29 `
  -a max_pages=1 `
  -a reports=true `
  -a regular_announcements=false `
  -a download_pdf=false
```

```powershell
scrapy crawl cninfo_company `
  -a stock_code=000001 `
  -a pretty_json=false `
  -a save_raw=true
```

```powershell
scrapy crawl cninfo_market `
  -a stock_code=000001 `
  -a snapshot=true `
  -a history=true `
  -a save_raw=true
```

```powershell
scrapy crawl cninfo_financials -a stock_code=000001 -a save_raw=true
scrapy crawl cninfo_shareholders -a stock_code=000001 -a save_raw=true
scrapy crawl cninfo_trading -a stock_code=000001 -a save_raw=true
```

## 市场交易分析 Agent

第一版市场交易 Agent 读取本地结构化行情、融资融券和大宗交易数据，支持价格趋势、
波动风险、流动性、价量关系、估值快照、融资融券和大宗交易七类主题。数值计算由
Python 完成，DeepSeek 只解释有证据 ID 的事实。

```powershell
python -m get_stock analyze market "分析000001最近20个交易日的股价和两融" `
  --sessions 20 `
  --llm
```

数据不足时返回 `partial` 或 `insufficient_data`，Agent 本身不会调用爬虫；输出中的
`recommended_action` 供后续 Supervisor 选择 `crawl_market` 或 `crawl_trading`。
设计及任务契约见 [市场交易 Agent 设计](docs/market-trading-agent.md)。

财务和市场交易 Agent 的文件访问权限集中配置在
`src/get_stock/agent_config/dataset_whitelists.py`。分析目录只声明主题依赖，不能绕过
该白名单读取任意本地文件。

## 股东分析 Agent

股东 Agent 支持股本结构、股东集中度、主要股东变化、股东人数、基金持股、限售解禁和
股权质押七类主题。它读取 `cleaned/` 与 `shareholder_crawl_state.json`，能够区分
“采集成功但零事件”和“采集失败”。

```powershell
python -m get_stock analyze shareholders "分析000001最近4期的股东变化和基金持股"
```

财务、市场交易和股东三个专业 Agent 现在均默认调用 `.env` 配置的 DeepSeek。若只需要
Python 确定性计算，必须显式传入 `--no-llm`。完整说明见
[股东分析 Agent 设计](docs/shareholder-agent.md)。

## 财报定性分析 Agent

财报 Agent 是由 Supervisor 条件唤醒的补充型 Agent。其他结构化专业 Agent 已经完整处理问题时，
它保持待命，不读取文件也不调用 LLM。第一版只读取上游授权完整报告目录中的 `chunks.jsonl`，
排除财务指标、财务报告、前置内容和未分类章节；先通过 heading 选择章节，再按正文关键词选择
少量 chunk。它不能读取 PDF、`pages.jsonl`、`sections.jsonl` 或任意其他本地文件。

```powershell
python -m get_stock analyze report "分析000001的技术优势和核心竞争力" `
  --report-id 1225475344
```

CLI 仅模拟 Supervisor，`--report-id` 是必须显式给出的授权边界。默认调用 `.env` 配置的
DeepSeek；使用 `--no-llm` 可只验证 heading 命中、chunk 检索和证据输出。完整任务契约、章节
边界和 LangGraph 子图见 [财报定性分析 Agent 设计](docs/report-agent.md)。

## 综合分析 Agent

综合分析 Agent 只消费专业 Agent 的完整结构化结果，负责需求覆盖、证据命名空间、冲突检测和
最终归纳，不直接读取原始股票数据，也不调度爬虫或其他 Agent。它每次都会在以下目录生成
`result.json`、`report.md` 和 `state.json`：

```text
data/stocks/<stock_code>/analysis/comprehensive/<task_id>/
```

使用 Supervisor 任务 JSON 进行本地模拟：

```powershell
python -m get_stock analyze comprehensive synthesis-task.json
```

现在也可以由 Supervisor 直接完成专业 Agent 路由、完整财报选择和综合任务构造，无需手工
创建 `synthesis-task.json`，也无需填写 `--report-id`：

```powershell
python -m get_stock analyze stock "综合分析000001最近三年的盈利、估值和股东变化"
```

Supervisor 默认调用 `.env` 中配置的 DeepSeek；使用 `--no-llm` 可执行离线规则分析。
`--report-fallback` 默认开启，只会授权本地已有 `chunks.jsonl` 的完整财报。问题理解会先生成
受 Schema 限制的标准请求，再由 Supervisor 规划数据和专业 Agent。`--auto-crawl` 默认关闭；
开启后会在专业 Agent 运行前补采缺失的必需结构化数据。`--auto-documents` 自动补充完整
年报/半年报PDF并生成chunks；`--auto-run` 同时开启两条恢复链。两者默认关闭且最多一轮。
完整边界、状态和产物说明见
[Supervisor 设计](docs/supervisor.md)。

面向命令行用户的推荐提问格式、风险类表达、自动化开关和结果核对方法见
[股票分析命令使用指南](docs/analysis-user-guide.md)。

项目模块、主要函数、运行架构、数据契约和扩展接口见
[开发文档](docs/development-guide.md)。

完整自动分析示例：

```powershell
python -m get_stock analyze stock `
  "综合分析000001最近三年的盈利、估值、股东变化和竞争优势" `
  --auto-run `
  --max-documents 3 `
  --heading-mode auto
```

当前自动文档链只处理 `document_role=full_report` 的年度和半年度报告；普通公告自动切片和
Announcement Agent保留为后续扩展。

启用 LLM 时，所有问题都先由 Supervisor 的 DeepSeek 问题理解器转换成受 Schema 限制的
Topic、时间意图和文档意图，再由固定 Router 选择专业 Agent。问题理解 LLM 失败时使用规则
结果，`--no-llm` 则始终走纯规则路径；综合 LLM 输出校验失败时使用确定性综合，
两种情况都不会因为模型输出越界而阻止最终 Markdown 生成。

`report.md` 从已校验的结构化结果确定性渲染，不会单独调用 LLM，确保 Markdown 与 JSON
结论一致。完整输入协议、证据链和状态说明见
[综合分析 Agent 设计](docs/comprehensive-agent.md)。

专业 Agent 已改为 `AgentTypeSpec + AgentTypeRegistry` 显式注册。新增公告、行业或其他专业
Agent 时，可通过类型描述接入问题路由、任务构造、数据白名单、运行时实例和综合结果适配，
无需在综合 Agent 中增加按 Agent 名称编写的分支。参见
[Agent 扩展机制](docs/agent-extension.md)。

## 请求控制

默认采用保守策略：

- 全局并发数为 4。
- 同一域名并发数为 4。
- 请求间隔默认 5 秒，并加入随机抖动。
- `5xx` 响应最多重试 2 次。
- 收到 `403` 时立即停止当前爬虫。
- 收到 `429` 时遵循 `Retry-After`，否则暂停任务。
- 遇到验证码、登录页或非预期 HTML 时停止并记录响应。
- 不使用代理轮换、验证码破解或其他规避访问限制的手段。

实际使用前应检查并遵守目标网站最新的服务条款、robots 规则和数据授权要求。

## 数据示例

`cleaned/announcements.jsonl` 中的单行示例：

```json
{"stock_code":"000001","stock_name":"平安银行","org_id":"示例orgId","exchange":"SZSE","announcement_id":"示例公告ID","title":"2026年半年度报告","category":"半年度报告","document_type":"financial_report","report_type":"semiannual","report_period":"2026-06-30","is_summary":false,"is_revision":false,"published_at":"2026-08-20T18:30:00+08:00","pdf_url":"https://static.cninfo.com.cn/example.pdf","local_path":"data/stocks/000001/documents/reports/semiannual/2026/example.pdf","download_status":"success","crawled_at":"2026-08-29T12:00:00+08:00"}
```

示例中的标识符和地址仅用于说明字段结构。

JSONL 文件仍作为增量写入和程序处理的数据源。Spider 结束时会通过通用的
`sync_pretty_json` 函数同步到 `pretty/`：JSONL 生成同名 `.json` 数组，单对象 JSON 则生成
同名的缩进 JSON。重新采集时可读文件会被原子更新，不会改写 `cleaned/` 中的正式数据。
同步功能默认开启；如不需要可在项目命令中传入 `--no-pretty-json`，或在
标准 Scrapy 命令中传入 `-a pretty_json=false`。

## 测试与代码检查

```powershell
pytest
ruff check .
ruff format --check .
```

默认测试不访问外网。执行低频端到端测试时，需要显式启用：

```powershell
$env:RUN_LIVE_CNINFO = "1"
pytest tests/test_live_cninfo.py -s
```

联网测试包含公告、公司资料、财务、股东股本和交易信息等低频冒烟用例。公告用例使用股票 `000001` 的固定历史日期，只查询一页并验证公告 JSONL 和 PDF；其余用例分别验证对应结构化文件。请勿在自动化流水线中高频执行这些测试。

## 版本记录

### 1.0

- 增加文档角色和严格标题分类，支持 `--report-scope` 按报告范围采集。
- 对下载后的完整年报/半年报执行 3/10/20 页渐进式轻量验证，输出 Agent 可用性标记。
- 确定首版采集范围和本地存储方案。
- 确定 Scrapy、JSONL 和本地 PDF 技术栈。
- 实现证券解析、公告分页、本地去重、JSONL输出和PDF下载。
- 将公告和公司资料拆分为独立Spider，并共享证券解析基类。
- 增加独立行情Spider，并隔离处理行情快照与日线历史接口失败。
- 将顶部基本指标从行情Spider迁移至财务Spider，增加主要指标和三张财务报表。
- 增加股东股本Spider，采集股本结构、股东人数、十大股东、限售解禁和股权质押。
- 在股东股本 Spider 中增加个股基金持股汇总，保存最近五年的基金覆盖家数和合计持股数。
- 增加交易信息 Spider，分别采集最近六个月融资融券和最近五年大宗交易数据。
- 增加定期财报识别及财报/普通公告开关，并将两类 PDF 分目录保存。
- 增加 `crawl all` 组合命令，在单个 Reactor 中串行执行选中的 Spider 并生成汇总状态。
- 实现公司介绍、高管和历史分红的本地文件输出。
- 实现请求限流、重试、异常响应保护和断点状态文件。
- 增加离线测试和显式启用的联网端到端测试。
