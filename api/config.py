"""Environment configuration, parsed once at import time.

Mirrors .env.example verbatim. Per-provider effort clamping (PRD §5.2) is an M3
concern and is not implemented here.
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
    # Named per provider so the key a reader uses is unambiguous; falls back to
    # READER_API_KEY when unset.
    openai_api_key: str = ""
    reader_effort: str = "low"
    reader_service_tier: str = "standard"
    reader_timeout_s: int = 25
    # Paid vision calls allowed per UTC day, enforced in the reader layer.
    # 0 disables the backstop. See readers/vision.py for why calls, not dollars.
    daily_vision_call_cap: int = 300

    access_token: str = ""
    admin_token: str = ""

    auto_approve_matches: bool = False
    # PRD §8: a fraction of otherwise-eligible records goes to a human anyway,
    # so an auto-close policy is always being spot-checked by someone.
    qa_sample_rate: float = 0.05

    data_dir: str = str(_ROOT_ENV.parent / "data")
    public_base_path: str = ""


settings = Settings()


def api_key_for(provider: str) -> str:
    """The key a given provider should authenticate with (PRD §5.2)."""
    per_provider = {"openai": settings.openai_api_key}.get(provider, "")
    return per_provider or settings.reader_api_key
