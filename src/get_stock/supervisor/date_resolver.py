from __future__ import annotations

from datetime import date

from get_stock.supervisor.schemas import (
    QuestionUnderstanding,
    ResolvedTimeScope,
    SupervisorTask,
)


def resolve_time_scope(
    task: SupervisorTask,
    understanding: QuestionUnderstanding,
    *,
    today: date | None = None,
) -> ResolvedTimeScope:
    """Resolve semantic time without allowing the LLM to calculate execution dates."""
    as_of = task.as_of_date or today or date.today()
    if not understanding.document_intent.needs_full_report:
        return ResolvedTimeScope(
            as_of_date=as_of,
            report_period_from=task.period_from,
            report_period_to=task.period_to,
            resolution_source="not_required",
        )

    if task.period_from is not None or task.period_to is not None:
        start = task.period_from
        end = task.period_to or as_of
        return ResolvedTimeScope(
            as_of_date=as_of,
            report_period_from=start,
            report_period_to=end,
            disclosure_search_from=_bounded_search_start(start or as_of, as_of),
            disclosure_search_to=as_of,
            resolution_source="explicit",
        )

    intent = understanding.time_intent
    if intent.mode == "absolute_range":
        start = intent.start_date
        end = intent.end_date or as_of
        return ResolvedTimeScope(
            as_of_date=as_of,
            report_period_from=start,
            report_period_to=end,
            disclosure_search_from=_bounded_search_start(start or as_of, as_of),
            disclosure_search_to=as_of,
            resolution_source="explicit",
        )

    count = min(understanding.financial_years, task.max_documents)
    report_type = understanding.report_type
    warnings: list[str] = []
    if report_type == "annual":
        latest_year = as_of.year - 1 if (as_of.month, as_of.day) >= (4, 30) else as_of.year - 2
        start = date(latest_year - count + 1, 12, 31)
        end = date(latest_year, 12, 31)
        disclosure_start = date(start.year + 1, 1, 1)
    elif report_type == "semiannual":
        latest_year = as_of.year if (as_of.month, as_of.day) >= (8, 31) else as_of.year - 1
        start = date(latest_year - count + 1, 6, 30)
        end = date(latest_year, 6, 30)
        disclosure_start = date(start.year, 7, 1)
    else:
        warnings.append(
            "automatic document recovery currently supports annual and semiannual full reports only"
        )
        start = None
        end = None
        disclosure_start = _bounded_search_start(as_of, as_of)

    return ResolvedTimeScope(
        as_of_date=as_of,
        report_period_from=start,
        report_period_to=end,
        disclosure_search_from=_bounded_search_start(disclosure_start, as_of),
        disclosure_search_to=as_of,
        resolution_source="relative" if intent.mode == "recent_years" else "default",
        warnings=tuple(warnings),
    )


def _bounded_search_start(value: date, as_of: date) -> date:
    floor = date(as_of.year - 5, as_of.month, min(as_of.day, 28))
    return max(value, floor)
