"""Environment configuration, parsed once at import time. Mirrors .env.example.

Effort clamping (PRD §5.2) belongs to the adapter that knows the floor, in
`readers/vision.py`.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root, shared with the frontend's Vite config (PRD §9).
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")

    reader_provider: str = "fake"
    reader_model: str = "gpt-5.6-luna"
    reader_base_url: str = ""
    reader_api_key: str = ""
    # Named per provider so the key is unambiguous; READER_API_KEY is the fallback.
    openai_api_key: str = ""
    reader_effort: str = "none"
    reader_service_tier: str = "standard"
    reader_timeout_s: int = 25
    # PRD §8: bounded - 300 simultaneous calls would breach the provider's limits.
    reader_concurrency: int = 10
    # Paid calls per UTC day, enforced in the reader layer; 0 disables it.
    daily_vision_call_cap: int = 300

    access_token: str = ""
    admin_token: str = ""

    auto_approve_matches: bool = False
    # PRD §8: a fraction goes to a human anyway, so auto-close stays spot-checked.
    qa_sample_rate: float = 0.05

    data_dir: str = str(_ROOT_ENV.parent / "data")


settings = Settings()


def api_key() -> str:
    """The vision reader's key: OPENAI_API_KEY, else the generic READER_API_KEY."""
    return settings.openai_api_key or settings.reader_api_key
