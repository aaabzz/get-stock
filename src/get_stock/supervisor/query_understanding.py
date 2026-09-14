from __future__ import annotations

import re

from get_stock.agent_plugins import AgentTypeRegistry, build_builtin_agent_types
from get_stock.supervisor.reasoner import SupervisorPlanningReasoner
from get_stock.supervisor.schemas import (
    DocumentIntent,
    QuestionUnderstanding,
    SupervisorPlanDraft,
    SupervisorTask,
    TimeIntent,
)

SUPERVISOR_TOPIC_ALIASES = {
    "profitability": ("盈利", "赚钱能力"),
    "earnings_quality": ("利润是否真实", "盈利是否真实"),
}


def understand_supervisor_question(
    task: SupervisorTask,
    *,
    reasoner: SupervisorPlanningReasoner | None = None,
    agent_types: AgentTypeRegistry | None = None,
) -> QuestionUnderstanding:
    """Interpret natural language without selecting files, spiders, or executable commands."""
    question = task.question.strip()
    agent_types = agent_types or build_builtin_agent_types()
    routes = agent_types.routes()
    normalized = question.lower()
    stock_code = task.stock_code or _extract_stock_code(normalized)
    if stock_code is None:
        raise ValueError("a six-digit stock code is required")

    deterministic_selected = _select_deterministic_topics(normalized, agent_types)
    selected = list(deterministic_selected)
    defaults = {
        "financial_years": _extract_number(normalized, "年", default=3, maximum=10),
        "shareholder_periods": _extract_number(normalized, "期", default=4, maximum=20),
        "market_sessions": _extract_sessions(normalized),
        "report_type": _extract_report_type(normalized),
        "time_intent": _build_time_intent(task, normalized),
        "document_intent": _build_document_intent(normalized, deterministic_selected),
    }
    mode = "deterministic"
    llm_used = False
    warnings: list[str] = []
    draft = None
    if task.require_llm and reasoner is not None:
        try:
            response = reasoner(
                {
                    "question": question,
                    "stock_code": stock_code,
                    "allowed_topics": sorted(routes),
                    "deterministic_topic_candidates": [
                        topic for topic, _ in deterministic_selected
                    ],
                    "explicit_period": {
                        "as_of_date": task.as_of_date.isoformat() if task.as_of_date else None,
                        "period_from": task.period_from.isoformat() if task.period_from else None,
                        "period_to": task.period_to.isoformat() if task.period_to else None,
                    },
                    "defaults": {
                        key: value.model_dump(mode="json")
                        if hasattr(value, "model_dump")
                        else value
                        for key, value in defaults.items()
                    },
                }
            )
            draft = (
                response
                if isinstance(response, SupervisorPlanDraft)
                else SupervisorPlanDraft.model_validate(response)
            )
            unknown = sorted(set(draft.topics) - set(routes))
            if unknown:
                raise ValueError(f"unsupported planning topics: {unknown}")
            selected = [(topic, routes[topic][0]) for topic in draft.topics]
            mode = "deepseek"
            llm_used = True
        except Exception as exc:
            draft = None
            mode = "deterministic_fallback"
            warnings.append(
                f"Supervisor LLM understanding failed; deterministic result used: {exc}"
            )
    elif task.require_llm:
        mode = "deterministic_fallback"
        warnings.append(
            "Supervisor LLM was requested but no planning reasoner was configured; "
            "deterministic result used"
        )

    if not selected:
        topic_maps = agent_types.topic_maps()
        for agent in agent_types.structured_names():
            selected.extend(
                (synthesis_topic, agent) for synthesis_topic in topic_maps[agent].values()
            )

    topics = tuple(dict.fromkeys(topic for topic, _ in selected))
    values = draft.model_dump() if draft is not None else defaults
    time_intent = TimeIntent.model_validate(values["time_intent"])
    if task.period_from is not None or task.period_to is not None:
        time_intent = defaults["time_intent"]
    if time_intent.mode == "recent_years" and time_intent.count is not None:
        values["financial_years"] = min(time_intent.count, 10)
    elif time_intent.mode == "recent_periods" and time_intent.count is not None:
        values["shareholder_periods"] = min(time_intent.count, 20)
    elif time_intent.mode == "recent_sessions" and time_intent.count is not None:
        values["market_sessions"] = max(2, min(time_intent.count, 500))
    document_intent = values["document_intent"]
    if any(agent == "financial_report_analysis" for _, agent in selected):
        parsed_document_intent = DocumentIntent.model_validate(document_intent)
        document_intent = parsed_document_intent.model_copy(
            update={"needs_full_report": True}
        )
    return QuestionUnderstanding(
        stock_code=stock_code,
        topics=topics,
        financial_years=values["financial_years"],
        shareholder_periods=values["shareholder_periods"],
        market_sessions=values["market_sessions"],
        report_type=values["report_type"],
        time_intent=time_intent,
        document_intent=document_intent,
        interpreter_mode=mode,
        llm_used=llm_used,
        warnings=tuple(warnings),
    )


def _select_deterministic_topics(
    normalized: str, agent_types: AgentTypeRegistry
) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    routes = agent_types.routes()
    for spec in agent_types.all():
        for specialist_topic, keywords in spec.intent_keywords.items():
            if any(keyword.lower() in normalized for keyword in keywords):
                synthesis_topic = spec.topic_map[specialist_topic]
                selected.append((synthesis_topic, routes[synthesis_topic][0]))
    for topic, aliases in SUPERVISOR_TOPIC_ALIASES.items():
        if topic in routes and any(alias in normalized for alias in aliases):
            selected.append((topic, routes[topic][0]))
    return selected


def _extract_stock_code(question: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", question)
    return match.group(1) if match else None


def _extract_number(question: str, suffix: str, *, default: int, maximum: int) -> int:
    match = re.search(
        rf"(?:最近|近)\s*((?:\d{{1,3}})|[一二三四五六七八九十]+)\s*{suffix}",
        question,
    )
    if not match:
        return default
    return _parse_bounded_number(match.group(1), maximum=maximum)


def _extract_sessions(question: str) -> int:
    match = re.search(
        r"(?:最近|近)\s*((?:\d{1,3})|[一二三四五六七八九十]+)\s*(?:个)?(?:交易日|日)",
        question,
    )
    if not match:
        return 60
    return max(2, _parse_bounded_number(match.group(1), maximum=500))


def _extract_report_type(question: str) -> str:
    if "半年" in question or "中报" in question:
        return "semiannual"
    if "一季" in question:
        return "first_quarter"
    if "三季" in question:
        return "third_quarter"
    return "annual"


def _build_time_intent(task: SupervisorTask, question: str) -> TimeIntent:
    if task.period_from is not None or task.period_to is not None:
        return TimeIntent(
            mode="absolute_range",
            raw_expression="explicit CLI period",
            start_date=task.period_from,
            end_date=task.period_to,
        )
    sessions = re.search(
        r"(?:最近|近)\s*((?:\d{1,3})|[一二三四五六七八九十]+)\s*(?:个)?(?:交易日|日)",
        question,
    )
    if sessions:
        return TimeIntent(
            mode="recent_sessions",
            raw_expression=sessions.group(0),
            count=_parse_bounded_number(sessions.group(1), maximum=500),
        )
    years = re.search(
        r"(?:最近|近)\s*((?:\d{1,2})|[一二三四五六七八九十]+)\s*年",
        question,
    )
    if years:
        return TimeIntent(
            mode="recent_years",
            raw_expression=years.group(0),
            count=_parse_bounded_number(years.group(1), maximum=10),
        )
    periods = re.search(
        r"(?:最近|近)\s*((?:\d{1,2})|[一二三四五六七八九十]+)\s*期",
        question,
    )
    if periods:
        return TimeIntent(
            mode="recent_periods",
            raw_expression=periods.group(0),
            count=_parse_bounded_number(periods.group(1), maximum=20),
        )
    fiscal_year = re.search(r"(?<!\d)(20\d{2})\s*年", question)
    if fiscal_year:
        year = int(fiscal_year.group(1))
        return TimeIntent(
            mode="absolute_range",
            raw_expression=fiscal_year.group(0),
            start_date=f"{year:04d}-01-01",
            end_date=f"{year:04d}-12-31",
        )
    if "最新" in question or "当前" in question:
        return TimeIntent(mode="latest", raw_expression="最新/当前")
    return TimeIntent()


def _build_document_intent(
    question: str, selected: list[tuple[str, str]]
) -> DocumentIntent:
    report_requested = any(agent == "financial_report_analysis" for _, agent in selected)
    announcement_requested = any(
        keyword in question for keyword in ("公告", "问询函", "监管问询", "公告PDF")
    )
    return DocumentIntent(
        needs_full_report=report_requested,
        needs_announcements=announcement_requested,
        explicitly_requested=report_requested or announcement_requested,
    )


def _parse_bounded_number(value: str, *, maximum: int) -> int:
    if value.isdigit():
        return max(1, min(int(value), maximum))
    digits = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        number = 10
    elif "十" in value:
        tens, _, ones = value.partition("十")
        number = (digits.get(tens, 1) * 10) + digits.get(ones, 0)
    else:
        number = digits.get(value, 1)
    return max(1, min(number, maximum))
