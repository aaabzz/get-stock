from pydantic import SecretStr

from get_stock.config import AppSettings
from get_stock.financial_agent.reasoner import build_deepseek_reasoner
from get_stock.financial_agent.schemas import FinancialLLMAnalysis


def test_unified_model_config_defaults_to_deepseek() -> None:
    settings = AppSettings(_env_file=None)

    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-v4-pro"
    assert settings.llm_base_url == "https://api.deepseek.com"


def test_deepseek_key_can_be_manually_supplied_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "manual-test-key")

    settings = AppSettings(_env_file=None)

    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "manual-test-key"
    assert "manual-test-key" not in repr(settings)


def test_deepseek_key_can_be_manually_supplied_by_dotenv(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=dotenv-test-key\n", encoding="utf-8")

    settings = AppSettings(_env_file=env_file)

    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "dotenv-test-key"


def test_deepseek_reasoner_passes_secret_to_openai_compatible_client(monkeypatch) -> None:
    captured = {}

    class FakeStructuredModel:
        def invoke(self, _messages):
            return FinancialLLMAnalysis(overall_assessment="测试")

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def with_structured_output(self, _schema, **_kwargs):
            return FakeStructuredModel()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    reasoner = build_deepseek_reasoner(
        api_key="manual-test-key",
        model_name="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
    )

    result = reasoner({"facts": []})

    assert result.overall_assessment == "测试"
    assert isinstance(captured["api_key"], SecretStr)
    assert captured["api_key"].get_secret_value() == "manual-test-key"
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["base_url"] == "https://api.deepseek.com"
