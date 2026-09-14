import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from twisted.internet.defer import inlineCallbacks

from get_stock.comprehensive_agent import (
    ComprehensiveAnalysisAgent,
    ComprehensiveAnalysisError,
    ComprehensiveAnalysisTask,
    build_deepseek_comprehensive_reasoner,
)
from get_stock.config import app_settings
from get_stock.document_acquisition import DocumentRecoveryCoordinator
from get_stock.documents import (
    HEADING_REASONER_VERSION,
    ReportProcessingError,
    build_deepseek_heading_reasoner,
    list_processable_reports,
    process_report,
)
from get_stock.documents.segmenter import HEADING_MODES
from get_stock.financial_agent import (
    FinancialAnalysisAgent,
    FinancialAnalysisError,
    FinancialAnalysisTask,
    FinancialTaskConstraints,
    build_deepseek_reasoner,
)
from get_stock.financial_agent.catalog import TOPIC_DATASETS
from get_stock.financial_agent.intent import parse_financial_intent
from get_stock.market_trading_agent import (
    MarketTradingAnalysisAgent,
    MarketTradingAnalysisError,
    MarketTradingAnalysisTask,
    MarketTradingTaskConstraints,
    build_deepseek_market_reasoner,
)
from get_stock.market_trading_agent.catalog import TOPIC_DATASETS as MARKET_TOPIC_DATASETS
from get_stock.market_trading_agent.intent import parse_market_trading_intent
from get_stock.report_agent import (
    ReportAnalysisAgent,
    ReportAnalysisError,
    ReportAnalysisTask,
    ReportReference,
    ReportRequirement,
    ReportRetrievalOptions,
    ReportTaskConstraints,
    build_deepseek_report_reasoner,
)
from get_stock.report_agent.intent import parse_report_intent
from get_stock.shareholder_agent import (
    ShareholderAnalysisAgent,
    ShareholderAnalysisError,
    ShareholderAnalysisTask,
    ShareholderTaskConstraints,
    build_deepseek_shareholder_reasoner,
)
from get_stock.shareholder_agent.catalog import TOPIC_DATASETS as SHAREHOLDER_TOPIC_DATASETS
from get_stock.shareholder_agent.intent import parse_shareholder_intent
from get_stock.spiders.announcements import REPORT_SCOPES, CninfoAnnouncementSpider
from get_stock.spiders.company import CninfoCompanySpider
from get_stock.spiders.financials import CninfoFinancialsSpider
from get_stock.spiders.market import CninfoMarketSpider
from get_stock.spiders.shareholders import CninfoShareholdersSpider
from get_stock.spiders.trading import CninfoTradingSpider
from get_stock.storage import atomic_write_json, state_data_path
from get_stock.supervisor import (
    AgentRegistry,
    StockAnalysisSupervisor,
    SupervisorError,
    SupervisorTask,
    build_deepseek_supervisor_reasoner,
)

app = typer.Typer(no_args_is_help=True, help="Low-frequency CNINFO stock crawler")
crawl_app = typer.Typer(no_args_is_help=True, help="Crawl one CNINFO data domain")
pdf_app = typer.Typer(no_args_is_help=True, help="Process downloaded full financial reports")
analyze_app = typer.Typer(no_args_is_help=True, help="Analyze local structured stock data")
app.add_typer(crawl_app, name="crawl")
app.add_typer(pdf_app, name="pdf")
app.add_typer(analyze_app, name="analyze")


def _abort(message: str) -> NoReturn:
    """Render a command error using Typer's stable public API."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


DEFAULT_DATA_DIR = app_settings.data_dir
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class SpiderJob:
    name: str
    spider_class: Any
    kwargs: dict[str, Any]
    state_filename: str
    expected_datasets: tuple[str, ...] = ()


@app.callback()
def main() -> None:
    """Collect low-frequency stock data from CNINFO."""


def _validate_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("expected YYYY-MM-DD") from exc
    return value


def _validate_report_scope(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized not in REPORT_SCOPES:
        choices = ", ".join(sorted(REPORT_SCOPES))
        raise typer.BadParameter(f"--report-scope must be one of: {choices}")
    return normalized


def _validate_heading_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in HEADING_MODES:
        choices = ", ".join(sorted(HEADING_MODES))
        raise typer.BadParameter(f"--heading-mode must be one of: {choices}")
    return normalized


def _build_pdf_heading_reasoner(mode: str):
    if mode == "rules":
        return None, None
    api_key = app_settings.deepseek_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        if mode == "auto":
            return None, None
        api_key = typer.prompt("DeepSeek API key", hide_input=True)
    try:
        reasoner = build_deepseek_heading_reasoner(
            api_key=api_key,
            model_name=app_settings.llm_model,
            base_url=app_settings.llm_base_url,
            temperature=app_settings.llm_temperature,
            timeout=app_settings.llm_timeout_seconds,
        )
    except RuntimeError:
        if mode == "auto":
            return None, None
        raise
    return reasoner, f"deepseek:{app_settings.llm_model}:heading-{HEADING_REASONER_VERSION}"


@analyze_app.command("financial")
def analyze_financial_data(
    question: Annotated[str, typer.Argument(help="Financial question in natural language")],
    stock_code: Annotated[
        str | None,
        typer.Option(help="Six-digit stock code; may instead appear in the question"),
    ] = None,
    years: Annotated[
        int | None,
        typer.Option(min=1, max=10, help="Override the requested number of periods"),
    ] = None,
    report_type: Annotated[
        str | None,
        typer.Option(help="annual, semiannual, first_quarter or third_quarter"),
    ] = None,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Use the configured DeepSeek model"),
    ] = True,
    output: Annotated[
        Path | None,
        typer.Option(help="Optional JSON output path; stdout is always written"),
    ] = None,
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Simulate a Supervisor task and invoke the financial specialist."""
    try:
        intent = parse_financial_intent(
            question,
            stock_code=stock_code,
            years=years,
            report_type=report_type,
        )
        datasets = {"company_profile"}
        for topic in intent.topics:
            datasets.update(TOPIC_DATASETS[topic]["required"])
            datasets.update(TOPIC_DATASETS[topic]["optional"])
        task = FinancialAnalysisTask(
            task_id=f"cli-{uuid.uuid4()}",
            stock_code=intent.stock_code,
            topics=intent.topics,
            report_type=intent.report_type,
            max_periods=intent.years,
            dataset_names=tuple(sorted(datasets)),
            constraints=FinancialTaskConstraints(require_llm=llm),
        )
        reasoner = None
        if llm:
            api_key = app_settings.deepseek_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                api_key = typer.prompt("DeepSeek API key", hide_input=True)
            reasoner = build_deepseek_reasoner(
                api_key=api_key,
                model_name=app_settings.llm_model,
                base_url=app_settings.llm_base_url,
                temperature=app_settings.llm_temperature,
                timeout=app_settings.llm_timeout_seconds,
            )
        result = FinancialAnalysisAgent(data_dir, reasoner=reasoner).analyze(task)
        payload = result.model_dump(mode="json")
    except (FinancialAnalysisError, RuntimeError, ValueError) as exc:
        _abort(str(exc))
    if output is not None:
        atomic_write_json(output.resolve(), payload)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@analyze_app.command("market")
def analyze_market_trading_data(
    question: Annotated[
        str,
        typer.Argument(help="Market trading question in natural language"),
    ],
    stock_code: Annotated[
        str | None,
        typer.Option(help="Six-digit stock code; may instead appear in the question"),
    ] = None,
    sessions: Annotated[
        int | None,
        typer.Option(min=2, max=500, help="Override the requested trading sessions"),
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option(help="Analysis date in YYYY-MM-DD format"),
    ] = None,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Use the configured DeepSeek model"),
    ] = True,
    output: Annotated[
        Path | None,
        typer.Option(help="Optional JSON output path; stdout is always written"),
    ] = None,
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Simulate a Supervisor task and invoke the market trading specialist."""
    try:
        intent = parse_market_trading_intent(
            question,
            stock_code=stock_code,
            lookback_sessions=sessions,
        )
        datasets = {"company_profile"}
        for topic in intent.topics:
            datasets.update(MARKET_TOPIC_DATASETS[topic]["required"])
            datasets.update(MARKET_TOPIC_DATASETS[topic]["optional"])
        task = MarketTradingAnalysisTask(
            task_id=f"cli-{uuid.uuid4()}",
            stock_code=intent.stock_code,
            topics=intent.topics,
            as_of_date=date.fromisoformat(as_of) if as_of else None,
            lookback_sessions=intent.lookback_sessions,
            dataset_names=tuple(sorted(datasets)),
            constraints=MarketTradingTaskConstraints(require_llm=llm),
        )
        reasoner = None
        if llm:
            api_key = app_settings.deepseek_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                api_key = typer.prompt("DeepSeek API key", hide_input=True)
            reasoner = build_deepseek_market_reasoner(
                api_key=api_key,
                model_name=app_settings.llm_model,
                base_url=app_settings.llm_base_url,
                temperature=app_settings.llm_temperature,
                timeout=app_settings.llm_timeout_seconds,
            )
        result = MarketTradingAnalysisAgent(data_dir, reasoner=reasoner).analyze(task)
        payload = result.model_dump(mode="json")
    except (MarketTradingAnalysisError, RuntimeError, ValueError) as exc:
        _abort(str(exc))
    if output is not None:
        atomic_write_json(output.resolve(), payload)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@analyze_app.command("shareholders")
def analyze_shareholder_data(
    question: Annotated[
        str,
        typer.Argument(help="Shareholder question in natural language"),
    ],
    stock_code: Annotated[
        str | None,
        typer.Option(help="Six-digit stock code; may instead appear in the question"),
    ] = None,
    periods: Annotated[
        int | None,
        typer.Option(min=1, max=20, help="Override the requested reporting periods"),
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option(help="Analysis date in YYYY-MM-DD format"),
    ] = None,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Use the configured DeepSeek model"),
    ] = True,
    output: Annotated[
        Path | None,
        typer.Option(help="Optional JSON output path; stdout is always written"),
    ] = None,
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Simulate a Supervisor task and invoke the shareholder specialist."""
    try:
        intent = parse_shareholder_intent(
            question,
            stock_code=stock_code,
            max_periods=periods,
        )
        datasets = {"company_profile"}
        for topic in intent.topics:
            datasets.update(SHAREHOLDER_TOPIC_DATASETS[topic]["required"])
            datasets.update(SHAREHOLDER_TOPIC_DATASETS[topic]["optional"])
        task = ShareholderAnalysisTask(
            task_id=f"cli-{uuid.uuid4()}",
            stock_code=intent.stock_code,
            topics=intent.topics,
            as_of_date=date.fromisoformat(as_of) if as_of else None,
            max_periods=intent.max_periods,
            dataset_names=tuple(sorted(datasets)),
            constraints=ShareholderTaskConstraints(require_llm=llm),
        )
        reasoner = None
        if llm:
            api_key = app_settings.deepseek_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                api_key = typer.prompt("DeepSeek API key", hide_input=True)
            reasoner = build_deepseek_shareholder_reasoner(
                api_key=api_key,
                model_name=app_settings.llm_model,
                base_url=app_settings.llm_base_url,
                temperature=app_settings.llm_temperature,
                timeout=app_settings.llm_timeout_seconds,
            )
        result = ShareholderAnalysisAgent(data_dir, reasoner=reasoner).analyze(task)
        payload = result.model_dump(mode="json")
    except (ShareholderAnalysisError, RuntimeError, ValueError) as exc:
        _abort(str(exc))
    if output is not None:
        atomic_write_json(output.resolve(), payload)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@analyze_app.command("report")
def analyze_financial_report(
    question: Annotated[
        str,
        typer.Argument(help="Qualitative financial-report question in natural language"),
    ],
    report_ids: Annotated[
        list[str],
        typer.Option(
            "--report-id",
            help="Supervisor-authorized full-report announcement ID; repeat for multiple reports",
        ),
    ],
    stock_code: Annotated[
        str | None,
        typer.Option(help="Six-digit stock code; may instead appear in the question"),
    ] = None,
    supplement: Annotated[
        bool,
        typer.Option("--supplement/--direct", help="Run as a supplement or direct task"),
    ] = True,
    top_k: Annotated[
        int,
        typer.Option(min=1, max=20, help="Maximum primary chunks selected per requirement"),
    ] = 8,
    adjacent_window: Annotated[
        int,
        typer.Option(min=0, max=2, help="Adjacent chunks included inside the same section"),
    ] = 1,
    max_context_characters: Annotated[
        int,
        typer.Option(min=1000, max=50000, help="Maximum report text sent to the reasoner"),
    ] = 16000,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Use the configured DeepSeek model"),
    ] = True,
    output: Annotated[
        Path | None,
        typer.Option(help="Optional JSON output path; stdout is always written"),
    ] = None,
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Simulate a Supervisor invocation of the standby financial-report specialist."""
    try:
        intent = parse_report_intent(question, stock_code=stock_code)
        reports = tuple(ReportReference(announcement_id=value) for value in report_ids)
        requirements = tuple(
            ReportRequirement(
                requirement_id=f"report-req-{index:02d}",
                topic=topic,
                question=question,
            )
            for index, topic in enumerate(intent.topics, start=1)
        )
        task = ReportAnalysisTask(
            task_id=f"cli-{uuid.uuid4()}",
            mode="supplement" if supplement else "direct",
            stock_code=intent.stock_code,
            question=question,
            requirements=requirements,
            reports=reports,
            retrieval=ReportRetrievalOptions(
                top_k=top_k,
                adjacent_window=adjacent_window,
                max_context_characters=max_context_characters,
            ),
            constraints=ReportTaskConstraints(require_llm=llm),
        )
        reasoner = None
        if llm:
            api_key = app_settings.deepseek_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                api_key = typer.prompt("DeepSeek API key", hide_input=True)
            reasoner = build_deepseek_report_reasoner(
                api_key=api_key,
                model_name=app_settings.llm_model,
                base_url=app_settings.llm_base_url,
                temperature=app_settings.llm_temperature,
                timeout=app_settings.llm_timeout_seconds,
            )
        result = ReportAnalysisAgent(data_dir, reasoner=reasoner).analyze(task)
        payload = result.model_dump(mode="json")
    except (ReportAnalysisError, RuntimeError, ValueError) as exc:
        _abort(str(exc))
    if output is not None:
        atomic_write_json(output.resolve(), payload)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@analyze_app.command("comprehensive")
def analyze_comprehensive_results(
    task_file: Annotated[
        Path,
        typer.Argument(help="Supervisor-generated comprehensive task JSON file"),
    ],
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Use the configured DeepSeek model"),
    ] = True,
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Synthesize validated specialist results and always write JSON and Markdown."""
    try:
        payload = json.loads(task_file.resolve().read_text(encoding="utf-8"))
        task = ComprehensiveAnalysisTask.model_validate(payload)
        task.constraints.require_llm = llm
        reasoner = None
        if llm:
            api_key = app_settings.deepseek_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                api_key = typer.prompt("DeepSeek API key", hide_input=True)
            reasoner = build_deepseek_comprehensive_reasoner(
                api_key=api_key,
                model_name=app_settings.llm_model,
                base_url=app_settings.llm_base_url,
                temperature=app_settings.llm_temperature,
                timeout=app_settings.llm_timeout_seconds,
            )
        result = ComprehensiveAnalysisAgent(data_dir, reasoner=reasoner).analyze(task)
        output = result.model_dump(mode="json")
    except (
        ComprehensiveAnalysisError,
        FileNotFoundError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
    ) as exc:
        _abort(str(exc))
    typer.echo(json.dumps(output, ensure_ascii=False, indent=2))


@analyze_app.command("stock")
def analyze_stock(
    question: Annotated[
        str,
        typer.Argument(help="Stock-analysis question routed by the Supervisor"),
    ],
    stock_code: Annotated[
        str | None,
        typer.Option(help="Six-digit stock code; may instead appear in the question"),
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option(help="Analysis date in YYYY-MM-DD format"),
    ] = None,
    period_from: Annotated[
        str | None,
        typer.Option(help="Optional start date in YYYY-MM-DD format"),
    ] = None,
    period_to: Annotated[
        str | None,
        typer.Option(help="Optional end date in YYYY-MM-DD format"),
    ] = None,
    report_fallback: Annotated[
        bool,
        typer.Option(
            "--report-fallback/--no-report-fallback",
            help="Allow automatic selection of processed full-report chunks",
        ),
    ] = True,
    auto_crawl: Annotated[
        bool,
        typer.Option(
            "--auto-crawl/--no-auto-crawl",
            help="Fetch missing required structured datasets using allowlisted spiders",
        ),
    ] = False,
    auto_documents: Annotated[
        bool,
        typer.Option(
            "--auto-documents/--no-auto-documents",
            help="Recover full-report PDFs and chunks before report analysis",
        ),
    ] = False,
    auto_run: Annotated[
        bool,
        typer.Option(
            "--auto-run/--no-auto-run",
            help="Enable structured crawling and full-report document recovery",
        ),
    ] = False,
    max_documents: Annotated[
        int,
        typer.Option(min=1, max=6, help="Maximum full reports recovered per task"),
    ] = 3,
    heading_mode: Annotated[
        str,
        typer.Option(help="PDF heading detection: rules, auto or llm"),
    ] = "auto",
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Use the configured DeepSeek model"),
    ] = True,
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Route specialists and produce the final comprehensive JSON and Markdown."""
    try:
        normalized_dates = {
            "as_of_date": date.fromisoformat(as_of) if as_of else None,
            "period_from": date.fromisoformat(period_from) if period_from else None,
            "period_to": date.fromisoformat(period_to) if period_to else None,
        }
        reasoners: dict[str, Any] = {}
        planning_reasoner = None
        heading_reasoner = None
        heading_reasoner_id = None
        heading_mode = _validate_heading_mode(heading_mode)
        effective_auto_documents = auto_documents or auto_run
        if llm:
            api_key = app_settings.deepseek_api_key
            if api_key is None or not api_key.get_secret_value().strip():
                api_key = typer.prompt("DeepSeek API key", hide_input=True)
            common = {
                "api_key": api_key,
                "model_name": app_settings.llm_model,
                "base_url": app_settings.llm_base_url,
                "temperature": app_settings.llm_temperature,
                "timeout": app_settings.llm_timeout_seconds,
            }
            reasoners = {
                "financial_analysis": build_deepseek_reasoner(**common),
                "market_trading": build_deepseek_market_reasoner(**common),
                "shareholder_analysis": build_deepseek_shareholder_reasoner(**common),
                "financial_report_analysis": build_deepseek_report_reasoner(**common),
                "comprehensive_analysis": build_deepseek_comprehensive_reasoner(**common),
            }
            planning_reasoner = build_deepseek_supervisor_reasoner(**common)
            if effective_auto_documents:
                heading_reasoner = build_deepseek_heading_reasoner(**common)
                heading_reasoner_id = (
                    f"deepseek:{app_settings.llm_model}:heading-{HEADING_REASONER_VERSION}"
                )
        registry = AgentRegistry(data_dir, reasoners=reasoners)
        document_coordinator = (
            DocumentRecoveryCoordinator(
                data_dir,
                heading_reasoner=heading_reasoner,
                heading_reasoner_id=heading_reasoner_id,
            )
            if effective_auto_documents
            else None
        )
        task = SupervisorTask(
            task_id=f"supervisor-{uuid.uuid4()}",
            question=question,
            stock_code=stock_code,
            auto_crawl=auto_crawl or auto_run,
            auto_documents=effective_auto_documents,
            allow_report_fallback=report_fallback,
            require_llm=llm,
            heading_mode=heading_mode,
            max_documents=max_documents,
            **normalized_dates,
        )
        result = StockAnalysisSupervisor(
            data_dir,
            registry=registry,
            planning_reasoner=planning_reasoner,
            document_coordinator=document_coordinator,
        ).analyze(task)
        output = result.model_dump(mode="json")
    except (SupervisorError, RuntimeError, ValueError) as exc:
        _abort(str(exc))
    typer.echo(json.dumps(output, ensure_ascii=False, indent=2))


@pdf_app.command("list")
def list_pdf_reports(
    stock_code: Annotated[str, typer.Argument(help="Six-digit stock code")],
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """List downloaded full reports discovered in the local announcement registry."""
    try:
        reports = list_processable_reports(data_dir, stock_code)
    except ReportProcessingError as exc:
        _abort(str(exc))
    typer.echo(
        json.dumps(
            [
                {
                    "announcement_id": report.get("announcement_id"),
                    "title": report.get("title"),
                    "report_type": report.get("report_type"),
                    "report_period": report.get("report_period"),
                    "content_validation_status": report.get("content_validation_status"),
                }
                for report in reports
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


@pdf_app.command("process")
def process_pdf_report(
    stock_code: Annotated[str, typer.Argument(help="Six-digit stock code")],
    announcement_id: Annotated[str, typer.Argument(help="CNINFO announcement ID")],
    force: Annotated[bool, typer.Option("--force", help="Ignore a valid processing cache")] = False,
    chunk_size: Annotated[int, typer.Option(min=200, help="Maximum chunk characters")] = 1200,
    chunk_overlap: Annotated[
        int, typer.Option(min=0, help="Character overlap inside one page")
    ] = 150,
    heading_mode: Annotated[
        str,
        typer.Option(help="Heading detection: rules, auto or llm"),
    ] = "auto",
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Process one validated full report into page, section and chunk datasets."""
    try:
        heading_mode = _validate_heading_mode(heading_mode)
        heading_reasoner, heading_reasoner_id = _build_pdf_heading_reasoner(heading_mode)
        result = process_report(
            data_dir,
            stock_code,
            announcement_id,
            force=force,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            heading_mode=heading_mode,
            heading_reasoner=heading_reasoner,
            heading_reasoner_id=heading_reasoner_id,
        )
    except (ReportProcessingError, RuntimeError, ValueError) as exc:
        _abort(str(exc))
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@pdf_app.command("process-all")
def process_all_pdf_reports(
    stock_code: Annotated[str, typer.Argument(help="Six-digit stock code")],
    force: Annotated[bool, typer.Option("--force", help="Ignore valid processing caches")] = False,
    chunk_size: Annotated[int, typer.Option(min=200, help="Maximum chunk characters")] = 1200,
    chunk_overlap: Annotated[
        int, typer.Option(min=0, help="Character overlap inside one page")
    ] = 150,
    heading_mode: Annotated[
        str,
        typer.Option(help="Heading detection: rules, auto or llm"),
    ] = "auto",
    data_dir: Annotated[Path, typer.Option(help="Local data directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Process every downloaded full report registered for a stock."""
    try:
        heading_mode = _validate_heading_mode(heading_mode)
        heading_reasoner, heading_reasoner_id = _build_pdf_heading_reasoner(heading_mode)
        reports = list_processable_reports(data_dir, stock_code)
        if not reports:
            raise ReportProcessingError("no downloaded full reports were found")
        results: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for report in reports:
            announcement_id = str(report.get("announcement_id") or "")
            try:
                results.append(
                    process_report(
                        data_dir,
                        stock_code,
                        announcement_id,
                        force=force,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        heading_mode=heading_mode,
                        heading_reasoner=heading_reasoner,
                        heading_reasoner_id=heading_reasoner_id,
                    )
                )
            except ReportProcessingError as exc:
                failures.append({"announcement_id": announcement_id, "error": str(exc)})
    except (ReportProcessingError, RuntimeError, ValueError) as exc:
        _abort(str(exc))

    stock_dir = data_dir.resolve() / "stocks" / stock_code
    state = {
        "stock_code": stock_code,
        "status": "partial" if failures else "success",
        "processed_count": len(results),
        "failed_count": len(failures),
        "results": [
            {
                "announcement_id": result["announcement_id"],
                "status": result["status"],
                "cache_hit": result["cache_hit"],
                "output_dir": result["output_dir"],
                "heading_mode": result["heading_mode"],
                "heading_llm_used": result["heading_detection"]["llm_used"],
                "unclassified_headings": result["heading_detection"][
                    "unclassified_count"
                ],
            }
            for result in results
        ],
        "failures": failures,
        "completed_at": datetime.now(CHINA_TZ).isoformat(),
    }
    atomic_write_json(state_data_path(stock_dir, "pdf_processing_state.json"), state)
    typer.echo(json.dumps(state, ensure_ascii=False, indent=2))
    if failures:
        raise typer.Exit(code=1)


def _run_spider(spider_class, data_dir: Path, **spider_kwargs: Any) -> Path:
    resolved_data_dir = data_dir.resolve()
    settings = get_project_settings()
    settings.set("DATA_DIR", str(resolved_data_dir), priority="cmdline")
    settings.set("FILES_STORE", str(resolved_data_dir), priority="cmdline")

    process = CrawlerProcess(settings)
    process.crawl(spider_class, data_dir=str(resolved_data_dir), **spider_kwargs)
    process.start()
    return resolved_data_dir


def _run_spiders(jobs: list[SpiderJob], data_dir: Path) -> Path:
    """Run selected spiders sequentially while starting the reactor only once."""
    resolved_data_dir = data_dir.resolve()
    settings = get_project_settings()
    settings.set("DATA_DIR", str(resolved_data_dir), priority="cmdline")
    settings.set("FILES_STORE", str(resolved_data_dir), priority="cmdline")

    process = CrawlerProcess(settings)

    @inlineCallbacks
    def crawl_sequentially():
        for job in jobs:
            yield process.crawl(
                job.spider_class,
                data_dir=str(resolved_data_dir),
                **job.kwargs,
            )

    crawl_sequentially()
    process.start()
    return resolved_data_dir


def _file_version(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _summarize_spider_state(
    state_path: Path,
    previous_version: tuple[int, int] | None,
    expected_datasets: tuple[str, ...],
) -> dict[str, Any]:
    summary: dict[str, Any] = {"state_file": state_path.name}
    current_version = _file_version(state_path)
    if current_version is None:
        return {**summary, "status": "failed", "reason": "state file was not created"}
    if previous_version is not None and current_version == previous_version:
        return {**summary, "status": "failed", "reason": "state file was not updated"}

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**summary, "status": "failed", "reason": f"invalid state file: {exc}"}

    completed = set(state.get("completed_datasets") or [])
    failed = dict(state.get("failed_datasets") or {})
    missing = sorted(set(expected_datasets) - completed)
    if completed:
        summary["completed_datasets"] = sorted(completed)
    if failed:
        summary["failed_datasets"] = failed
    if missing:
        summary["missing_datasets"] = missing

    if failed or missing:
        summary["status"] = "partial_success" if completed else "failed"
    else:
        summary["status"] = "success"
    return summary


def _write_all_state(
    output_dir: Path,
    stock_code: str,
    jobs: list[SpiderJob],
    previous_versions: dict[str, tuple[int, int] | None],
    started_at: datetime,
) -> Path:
    stock_dir = output_dir / "stocks" / stock_code
    spider_states = {
        job.name: _summarize_spider_state(
            state_data_path(stock_dir, job.state_filename),
            previous_versions.get(job.name),
            job.expected_datasets,
        )
        for job in jobs
    }
    statuses = {state["status"] for state in spider_states.values()}
    if statuses == {"success"}:
        status = "success"
    elif "success" in statuses or "partial_success" in statuses:
        status = "partial_success"
    else:
        status = "failed"

    state_path = state_data_path(stock_dir, "crawl_all_state.json")
    atomic_write_json(
        state_path,
        {
            "stock_code": stock_code,
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(CHINA_TZ).isoformat(),
            "spiders": spider_states,
        },
    )
    return state_path


def _print_state(state_path: Path) -> None:
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        typer.echo(json.dumps(state, ensure_ascii=False, indent=2))
    typer.echo(f"输出目录：{state_path.parent}")


@crawl_app.command("announcements")
def crawl_announcements(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    start: str = typer.Option(..., "--start", help="Start date, YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="End date, YYYY-MM-DD"),
    category: str = typer.Option("", "--category", help="CNINFO category key"),
    max_pages: int = typer.Option(20, min=1, help="Maximum announcement pages"),
    max_documents: int = typer.Option(
        0, min=0, help="Maximum selected documents; 0 means unlimited"
    ),
    download_pdf: bool = typer.Option(
        False,
        "--download-pdf/--no-download-pdf",
        help="Download newly discovered PDF attachments",
    ),
    reports: bool = typer.Option(
        True,
        "--reports/--no-reports",
        help="Include periodic financial reports",
    ),
    regular_announcements: bool = typer.Option(
        True,
        "--regular-announcements/--no-regular-announcements",
        help="Include announcements other than periodic financial reports",
    ),
    report_scope: str = typer.Option(
        "all",
        "--report-scope",
        help="Report roles: all, full, summary, financial-statements or assurance",
    ),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw JSON responses",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Crawl one stock's announcement metadata and PDF files."""
    start = _validate_date(start)
    end = _validate_date(end)
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise typer.BadParameter("--start cannot be later than --end")
    if not reports and not regular_announcements:
        raise typer.BadParameter("--reports and --regular-announcements cannot both be disabled")
    report_scope = _validate_report_scope(report_scope)

    output_dir = _run_spider(
        CninfoAnnouncementSpider,
        data_dir,
        stock_code=stock_code,
        start_date=start,
        end_date=end,
        category=category,
        max_pages=max_pages,
        max_documents=max_documents,
        download_pdf=download_pdf,
        reports=reports,
        regular_announcements=regular_announcements,
        report_scope=report_scope,
        save_raw=save_raw,
        pretty_json=pretty_json,
    )
    stock_dir = output_dir / "stocks" / stock_code
    _print_state(state_data_path(stock_dir, "crawl_state.json"))


@crawl_app.command("company")
def crawl_company(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw JSON responses",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Crawl company profile, executives and dividend history."""
    output_dir = _run_spider(
        CninfoCompanySpider,
        data_dir,
        stock_code=stock_code,
        save_raw=save_raw,
        pretty_json=pretty_json,
    )
    stock_dir = output_dir / "stocks" / stock_code
    _print_state(state_data_path(stock_dir, "company_crawl_state.json"))


@crawl_app.command("market")
def crawl_market(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    snapshot: bool = typer.Option(
        True,
        "--snapshot/--no-snapshot",
        help="Fetch the current market snapshot when CNINFO makes it available",
    ),
    history: bool = typer.Option(
        True,
        "--history/--no-history",
        help="Fetch daily historical quotes",
    ),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw JSON and JSONP responses",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Crawl market metrics, a quote snapshot and daily quote history."""
    output_dir = _run_spider(
        CninfoMarketSpider,
        data_dir,
        stock_code=stock_code,
        snapshot=snapshot,
        history=history,
        save_raw=save_raw,
        pretty_json=pretty_json,
    )
    stock_dir = output_dir / "stocks" / stock_code
    _print_state(state_data_path(stock_dir, "market_crawl_state.json"))


@crawl_app.command("financials")
def crawl_financials(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw JSON responses",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Crawl financial indicators and the three primary statements."""
    output_dir = _run_spider(
        CninfoFinancialsSpider,
        data_dir,
        stock_code=stock_code,
        save_raw=save_raw,
        pretty_json=pretty_json,
    )
    stock_dir = output_dir / "stocks" / stock_code
    _print_state(state_data_path(stock_dir, "financial_crawl_state.json"))


@crawl_app.command("shareholders")
def crawl_shareholders(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw JSON responses",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Crawl share capital, shareholder counts, top holders and pledges."""
    output_dir = _run_spider(
        CninfoShareholdersSpider,
        data_dir,
        stock_code=stock_code,
        save_raw=save_raw,
        pretty_json=pretty_json,
    )
    stock_dir = output_dir / "stocks" / stock_code
    _print_state(state_data_path(stock_dir, "shareholder_crawl_state.json"))


@crawl_app.command("trading")
def crawl_trading(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw trading information responses",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Crawl margin trading and block trade records."""
    output_dir = _run_spider(
        CninfoTradingSpider,
        data_dir,
        stock_code=stock_code,
        save_raw=save_raw,
        pretty_json=pretty_json,
    )
    stock_dir = output_dir / "stocks" / stock_code
    _print_state(state_data_path(stock_dir, "trading_crawl_state.json"))


@crawl_app.command("all")
def crawl_all(
    stock_code: str = typer.Argument(..., help="Six-digit stock code"),
    start: str = typer.Option("", "--start", help="Announcement start date, YYYY-MM-DD"),
    end: str = typer.Option("", "--end", help="Announcement end date, YYYY-MM-DD"),
    category: str = typer.Option("", "--category", help="CNINFO announcement category key"),
    max_pages: int = typer.Option(20, min=1, help="Maximum announcement pages"),
    max_documents: int = typer.Option(
        0, min=0, help="Maximum selected announcement documents; 0 means unlimited"
    ),
    download_pdf: bool = typer.Option(
        False,
        "--download-pdf/--no-download-pdf",
        help="Download newly discovered announcement PDFs",
    ),
    reports: bool = typer.Option(
        True,
        "--reports/--no-reports",
        help="Include periodic financial reports in the announcement crawl",
    ),
    regular_announcements: bool = typer.Option(
        True,
        "--regular-announcements/--no-regular-announcements",
        help="Include non-report announcements in the announcement crawl",
    ),
    report_scope: str = typer.Option(
        "all",
        "--report-scope",
        help="Report roles: all, full, summary, financial-statements or assurance",
    ),
    snapshot: bool = typer.Option(
        True,
        "--snapshot/--no-snapshot",
        help="Fetch the current market snapshot",
    ),
    history: bool = typer.Option(
        True,
        "--history/--no-history",
        help="Fetch daily historical quotes",
    ),
    include_announcements: bool = typer.Option(
        True,
        "--announcements/--no-announcements",
        help="Run the announcement spider",
    ),
    include_company: bool = typer.Option(
        True,
        "--company/--no-company",
        help="Run the company spider",
    ),
    include_market: bool = typer.Option(
        True,
        "--market/--no-market",
        help="Run the market spider",
    ),
    include_financials: bool = typer.Option(
        True,
        "--financials/--no-financials",
        help="Run the financial spider",
    ),
    include_shareholders: bool = typer.Option(
        True,
        "--shareholders/--no-shareholders",
        help="Run the shareholder spider",
    ),
    include_trading: bool = typer.Option(
        True,
        "--trading/--no-trading",
        help="Run the trading information spider",
    ),
    save_raw: bool = typer.Option(
        False,
        "--save-raw/--no-save-raw",
        help="Save raw responses for every selected spider",
    ),
    pretty_json: bool = typer.Option(
        True,
        "--pretty-json/--no-pretty-json",
        help="Generate indented JSON files for human inspection",
    ),
    data_dir: Annotated[Path, typer.Option(help="Local output directory")] = DEFAULT_DATA_DIR,
) -> None:
    """Run selected CNINFO spiders sequentially in one Scrapy process."""
    if include_announcements:
        report_scope = _validate_report_scope(report_scope)
        if not reports and not regular_announcements:
            raise typer.BadParameter(
                "--reports and --regular-announcements cannot both be disabled"
            )
        if not start or not end:
            raise typer.BadParameter(
                "--start and --end are required when announcements are enabled"
            )
        start = _validate_date(start)
        end = _validate_date(end)
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise typer.BadParameter("--start cannot be later than --end")

    common = {
        "stock_code": stock_code,
        "save_raw": save_raw,
        "pretty_json": pretty_json,
    }
    jobs: list[SpiderJob] = []
    if include_announcements:
        jobs.append(
            SpiderJob(
                name="announcements",
                spider_class=CninfoAnnouncementSpider,
                kwargs={
                    **common,
                    "start_date": start,
                    "end_date": end,
                    "category": category,
                    "max_pages": max_pages,
                    "max_documents": max_documents,
                    "download_pdf": download_pdf,
                    "reports": reports,
                    "regular_announcements": regular_announcements,
                    "report_scope": report_scope,
                },
                state_filename="crawl_state.json",
            )
        )
    if include_company:
        jobs.append(
            SpiderJob(
                name="company",
                spider_class=CninfoCompanySpider,
                kwargs=common.copy(),
                state_filename="company_crawl_state.json",
                expected_datasets=("profile", "executives", "dividends"),
            )
        )
    if include_market:
        market_datasets = tuple(
            dataset
            for dataset, enabled in (("snapshot", snapshot), ("history", history))
            if enabled
        )
        jobs.append(
            SpiderJob(
                name="market",
                spider_class=CninfoMarketSpider,
                kwargs={**common, "snapshot": snapshot, "history": history},
                state_filename="market_crawl_state.json",
                expected_datasets=market_datasets,
            )
        )
    if include_financials:
        jobs.append(
            SpiderJob(
                name="financials",
                spider_class=CninfoFinancialsSpider,
                kwargs=common.copy(),
                state_filename="financial_crawl_state.json",
                expected_datasets=(
                    "summary",
                    "indicators",
                    "balance_sheets",
                    "income_statements",
                    "cash_flow_statements",
                ),
            )
        )
    if include_shareholders:
        jobs.append(
            SpiderJob(
                name="shareholders",
                spider_class=CninfoShareholdersSpider,
                kwargs=common.copy(),
                state_filename="shareholder_crawl_state.json",
                expected_datasets=(
                    "stock_structure",
                    "shareholder_counts",
                    "fund_holdings",
                    "top_ten",
                    "top_ten_float",
                    "restricted_unlocks",
                    "equity_pledges",
                ),
            )
        )
    if include_trading:
        jobs.append(
            SpiderJob(
                name="trading",
                spider_class=CninfoTradingSpider,
                kwargs=common.copy(),
                state_filename="trading_crawl_state.json",
                expected_datasets=("margin_trading", "block_trades"),
            )
        )
    if not jobs:
        raise typer.BadParameter("at least one spider must be enabled")

    stock_dir = data_dir.resolve() / "stocks" / stock_code
    previous_versions = {
        job.name: _file_version(state_data_path(stock_dir, job.state_filename)) for job in jobs
    }
    started_at = datetime.now(CHINA_TZ)
    output_dir = _run_spiders(jobs, data_dir)
    state_path = _write_all_state(
        output_dir,
        stock_code,
        jobs,
        previous_versions,
        started_at,
    )
    _print_state(state_path)
