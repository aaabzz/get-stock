from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import SecretStr

from get_stock.documents.heading_schemas import HeadingLLMAnalysis
from get_stock.llm import create_deepseek_chat_model

HEADING_REASONER_VERSION = "1.0"
HEADING_SYSTEM_PROMPT = """你是财报章节标题分类组件。输入只包含程序从PDF原文提取的
标题候选。你只能对 candidate_id 对应的候选进行分类，不得创建候选、页码、章节或原文。
section_type 必须使用结构化Schema允许的值；无法可靠分类时使用 unclassified。
normalized_heading 只允许规范空格和标点，不得改变标题含义。目录条目和正文边界已由程序
处理，你不负责决定文件、路径、命令、下载或Agent。只返回符合Schema的数据。"""


class HeadingReasoner(Protocol):
    def __call__(self, packet: dict[str, Any]) -> HeadingLLMAnalysis: ...


class LangChainHeadingReasoner:
    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must implement with_structured_output")
        self._structured_model = model.with_structured_output(
            HeadingLLMAnalysis,
            method="function_calling",
        )

    def __call__(self, packet: dict[str, Any]) -> HeadingLLMAnalysis:
        response = self._structured_model.invoke(
            [
                ("system", HEADING_SYSTEM_PROMPT),
                ("human", json.dumps(packet, ensure_ascii=False)),
            ]
        )
        return (
            response
            if isinstance(response, HeadingLLMAnalysis)
            else HeadingLLMAnalysis.model_validate(response)
        )


def build_deepseek_heading_reasoner(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Callable[[dict[str, Any]], HeadingLLMAnalysis]:
    model = create_deepseek_chat_model(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )
    return LangChainHeadingReasoner(model)
