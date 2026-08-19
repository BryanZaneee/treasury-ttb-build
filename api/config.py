"""Environment configuration, parsed once at import time.

Mirrors the variables in .env.example verbatim. Per-provider effort clamping and
spend accounting (PRD §5.2, §8) are M3 concerns and are not implemented here.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reader_provider: str = "fake"
    reader_model: str = "gpt-5.6-luna"
    reader_base_url: str = ""
    reader_api_key: str = ""
    reader_effort: str = "low"
    reader_service_tier: str = "standard"
    reader_timeout_s: int = 25
    reader_concurrency: int = 10
    daily_spend_cap_usd: float = 50

    access_token: str = ""
    admin_token: str = ""

    auto_approve_matches: bool = False
    qa_sample_rate: float = 0.05

    data_dir: str = "./data"
    public_base_path: str = ""


settings = Settings()
