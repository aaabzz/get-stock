"""Shared model-client construction for specialist agents."""

from typing import Any

from pydantic import SecretStr


def create_deepseek_chat_model(
    *,
    api_key: SecretStr | str,
    model_name: str,
    base_url: str,
    temperature: float = 0.0,
    timeout: float = 120.0,
) -> Any:
    """Create a DeepSeek-compatible LangChain chat model without logging its key."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError(
            "DeepSeek LangChain dependencies are missing; "
            "install with pip install -e .[agent,deepseek-agent]"
        ) from exc
    raw_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
    if not raw_key.strip():
        raise ValueError("DeepSeek API key cannot be empty")
    return ChatOpenAI(
        api_key=SecretStr(raw_key),
        model=model_name,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
        max_retries=2,
    )
