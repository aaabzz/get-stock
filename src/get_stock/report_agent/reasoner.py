from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.llm import create_deepseek_chat_model
from get_stock.report_agent.catalog import TOPIC_LABELS
from get_stock.report_agent.schemas import ReportClaim, ReportLLMAnalysis

REPORT_SYSTEM_PROMPT = """你是财报定性分析专业子 Agent，输出将交给综合分析 Agent。
你只能使用输入证据包中的 selected_evidence，不得使用外部知识，不得读取或推测财务报告章节、
财务报表或附注。每项确定性结论必须引用存在且主题匹配的 evidence_id。topic 只能使用任务中
requested_topics 给出的标准枚举值。公司对行业地位、市场份额和优势的描述必须明确标为公司
财报披露，不得表述为已经外部独立验证。不得重新计算财务指标，不得预测股价或提供投资建议；
证据不足时使用 not_determinable。"""


class ReportReasoner(Protocol):
    def __call__(self, evidence_packet: dict[str, Any]) -> ReportLLMAnalysis: ...


def deterministic_reasoner(evidence_packet: dict[str, Any]) -> ReportLLMAnalysis:
    claims: list[ReportClaim] = []
    evidence = evidence_packet["selected_evidence"]
    for requirement in evidence_packet["requirements"]:
        matching = [
            item for item in evidence if requirement["topic"] in item["allowed_claim_types"]
        ]
        if not matching:
            continue
        first = matching[0]
        claims.append(
            ReportClaim(
                claim=(
                    f"已在报告《{first['heading']}》章节检索到与"
                    f"{TOPIC_LABELS[requirement['topic']]}相关的披露"
                ),
                topic=requirement["topic"],
                assessment="neutral",
                evidence_ids=[first["evidence_id"]],
                confidence=0.9,
            )
        )
    return ReportLLMAnalysis(
        summary=(
            "已完成授权财报非财务报告章节的确定性检索；离线模式不对披露内容作进一步语义归纳。"
        ),
        claims=claims,
        limitations=list(evidence_packet["limitations"]),
    )


class LangChainReportReasoner:
    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            ReportLLMAnalysis,
            method="function_calling",
        )

    def __call__(self, evidence_packet: dict[str, Any]) -> ReportLLMAnalysis:
        response = self._structured_model.invoke(
            [
                ("system", REPORT_SYSTEM_PROMPT),
                ("human", json.dumps(evidence_packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, ReportLLMAnalysis)
            else ReportLLMAnalysis.model_validate(response)
        )


def build_deepseek_report_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], ReportLLMAnalysis]:
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainReportReasoner(model)
