"""Reader layer (PRD §5.2, §5.3).

A reader turns a specimen into a `LabelReading`. It never sees application
values, so nothing written on a label can steer the adjudication (PRD §3.3).

  fake    replays fixtures/expectations.json - instant, free, the CI reader
  ocr     local Tesseract - free, no network, and the automatic fallback
  openai  vision, the production reader (see the README's bake-off table)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from config import api_key, settings
from models import LabelReading

PROVIDERS = ("fake", "ocr", "openai")


class Reader(Protocol):
    def read(self, specimen: str, image_path: Path | None = ...) -> LabelReading: ...


def get_reader(
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> Reader:
    """Build a reader; arguments override the environment, which the bench uses."""
    provider = (provider or settings.reader_provider or "fake").lower()

    if provider == "fake":
        from readers.fake import FakeReader

        return FakeReader()
    if provider == "ocr":
        from readers.ocr import OcrReader

        return OcrReader()
    if provider == "openai":
        from readers.vision import VisionReader

        return VisionReader(
            provider=provider,
            model=model or settings.reader_model,
            api_key=api_key(),
            base_url=settings.reader_base_url,
            effort=effort or settings.reader_effort,
            service_tier=settings.reader_service_tier,
            timeout_s=settings.reader_timeout_s,
            daily_call_cap=settings.daily_vision_call_cap,
        )
    raise ValueError(f"unknown reader provider: {provider!r} (expected one of {PROVIDERS})")
