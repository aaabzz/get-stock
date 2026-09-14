from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.llm import create_deepseek_chat_model
from get_stock.supervisor.schemas import SupervisorPlanDraft

SUPERVISOR_SYSTEM_PROMPT = """You are the planning component of a stock-analysis
Supervisor. Convert the user's Chinese question into only the allowed structured topics,
time intent, document intent, and bounded lookback values. Do not analyze the stock, make
claims, give investment advice, choose files,
choose Python classes, choose crawler commands, or invent announcement IDs.

Interpret common expressions semantically. For example, 盈利/赚钱能力 usually maps to
profitability, 利润是否真实 maps to earnings_quality, 估值 maps to valuation, and 股东变化
maps to holder_changes. Select report-derived topics only when the question explicitly asks
about qualitative disclosures such as competitive advantage, technology, market share,
industry position, strategy, management explanations, or business risks.

The explicit_period values supplied by the application override inferred dates. Keep
financial_years, shareholder_periods, and market_sessions consistent with time_intent when
the user states a matching lookback. needs_full_report means qualitative evidence from a
complete financial report is needed; needs_announcements means ordinary/event disclosures
are explicitly needed. These flags are semantic requirements, not permission to download.

Return only data conforming to the supplied schema. Use conservative defaults when the user
does not specify a time or document scope.
"""


class SupervisorPlanningReasoner(Protocol):
    def __call__(self, packet: dict[str, Any]) -> SupervisorPlanDraft: ...


class LangChainSupervisorPlanningReasoner:
    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            SupervisorPlanDraft,
            method="function_calling",
        )

    def __call__(self, packet: dict[str, Any]) -> SupervisorPlanDraft:
        response = self._structured_model.invoke(
            [
                ("system", SUPERVISOR_SYSTEM_PROMPT),
                ("human", json.dumps(packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, SupervisorPlanDraft)
            else SupervisorPlanDraft.model_validate(response)
        )


def build_deepseek_supervisor_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], SupervisorPlanDraft]:
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainSupervisorPlanningReasoner(model)
