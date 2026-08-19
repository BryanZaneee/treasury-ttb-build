"""Reader layer (PRD §5.2, §5.3).

A reader turns a specimen into a `LabelReading`. It never sees application
values, so extraction has no dependency on the form and nothing written on the
label can steer the adjudication (PRD §3.3).

Three implementations, interchangeable by configuration:

  fake    replays fixtures/expectations.json - instant, free, used in CI
  ocr     local Tesseract - ~600ms, free, no network
  openai  } one OpenAI-compatible adapter; Gemini exposes a compatible
  gemini  } endpoint, so only key, base URL and model string differ
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from config import api_key_for, settings
from models import LabelReading

PROVIDERS = ("fake", "ocr", "openai", "gemini")


class Reader(Protocol):
    name: str

    def read(self, specimen: str, image_path: Path | None = ...) -> LabelReading: ...


def get_reader(
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> Reader:
    """Build a reader. Arguments override the environment, which is what lets
    the dev bench run several providers side by side in one process."""
    provider = (provider or settings.reader_provider or "fake").lower()

    if provider == "fake":
        from readers.fake import FakeReader

        return FakeReader()
    if provider == "ocr":
        from readers.ocr import OcrReader

        return OcrReader()
    if provider in ("openai", "gemini"):
        from readers.vision import VisionReader

        return VisionReader(
            provider=provider,
            model=model or settings.reader_model,
            api_key=api_key_for(provider),
            base_url=settings.reader_base_url,
            effort=effort or settings.reader_effort,
            service_tier=settings.reader_service_tier,
            timeout_s=settings.reader_timeout_s,
        )
    raise ValueError(f"unknown reader provider: {provider!r} (expected one of {PROVIDERS})")
