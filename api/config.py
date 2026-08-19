"""Environment configuration, parsed once at import time.

Mirrors the variables in .env.example verbatim. Per-provider effort clamping and
spend accounting (PRD §5.2, §8) are M3 concerns and are not implemented here.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root (one level up from api/), not inside api/ itself -
# it's shared with the frontend's Vite config (PRD §9 subpath threading).
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")

    reader_provider: str = "fake"
    reader_model: str = "gpt-5.6-luna"
    reader_base_url: str = ""
    reader_api_key: str = ""
    # Per-provider keys. The bench races several providers in one process, so a
    # single READER_API_KEY cannot serve them all; these take precedence over it
    # for their own provider and fall back to it when unset.
    openai_api_key: str = ""
    gemini_api_key: str = ""
    reader_effort: str = "low"
    reader_service_tier: str = "standard"
    reader_timeout_s: int = 25
    reader_concurrency: int = 10
    daily_spend_cap_usd: float = 50

    access_token: str = ""
    admin_token: str = ""

    auto_approve_matches: bool = False
    qa_sample_rate: float = 0.05

    data_dir: str = str(_ROOT_ENV.parent / "data")
    public_base_path: str = ""


settings = Settings()


def api_key_for(provider: str) -> str:
    """The key a given provider should authenticate with (PRD §5.2)."""
    per_provider = {
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
    }.get(provider, "")
    return per_provider or settings.reader_api_key
