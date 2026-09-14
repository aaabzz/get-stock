from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppSettings(BaseSettings):
    """Configuration shared by the CLI and Scrapy settings."""

    data_dir: Path = PROJECT_ROOT / "data"
    download_delay: float = 5.0
    user_agent: str = "get-stock/1.0 (+local development test)"
    llm_provider: Literal["deepseek"] = "deepseek"
    llm_model: str = "deepseek-v4-pro"
    llm_base_url: str = "https://api.deepseek.com"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 120.0
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "GET_STOCK_DEEPSEEK_API_KEY"),
    )

    model_config = SettingsConfigDict(
        env_prefix="GET_STOCK_",
        env_file=".env",
        extra="ignore",
    )


app_settings = AppSettings()
