"""OpenAI-compatible vision reader - serves both OpenAI and Gemini (PRD §5.2).

Gemini exposes an OpenAI-compatible endpoint, so one client covers both
providers; only the API key, base URL, and model string differ.

ponytail: synchronous client. The routes that call it are sync `def`, so
FastAPI already runs them in a threadpool. Move to AsyncOpenAI when M5's
bounded worker pool needs real concurrency across a 300-record batch.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import APIError, OpenAI

from models import CaptureQuality, FieldReading, LabelReading, WarningReading
from readers.prep import prepare
from readers.prompts import PROMPT, SCHEMA, VERSION

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# PRD §5.2: Gemini 3 rejects `minimal` and cannot disable reasoning, so effort
# is clamped to a per-provider floor.
_EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
_EFFORT_FLOOR = {"gemini": "low", "openai": "none"}

RETRIES = 2

_REASONING_MODEL = re.compile(r"^(gpt-[5-9]|o[1-9])", re.IGNORECASE)

# PRD §5.2 calls the default tier "standard"; the API does not have that value.
_SERVICE_TIER = {"standard": "auto"}
MAX_LONG_EDGE_NOTE = "prepared image"


class ReaderError(RuntimeError):
    """The reader could not produce a usable reading. Callers fall back to OCR."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


def clamp_effort(provider: str, effort: str) -> str:
    """Raise a configured effort to the provider's floor (PRD §5.2)."""
    floor = _EFFORT_FLOOR.get(provider, "none")
    if effort not in _EFFORT_ORDER:
        return floor
    return max(effort, floor, key=_EFFORT_ORDER.index)


def _field(raw: dict[str, Any] | None) -> FieldReading:
    if not raw:
        return FieldReading(value=None, confidence=None)
    return FieldReading(value=raw.get("value"), confidence=raw.get("confidence"))


class VisionReader:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str = "",
        effort: str = "low",
        service_tier: str = "standard",
        timeout_s: float = 25.0,
    ) -> None:
        self.provider = provider
        self.name = provider
        self.model = model
        self.effort = clamp_effort(provider, effort)
        self.service_tier = service_tier
        self.prompt_version = VERSION
        if not api_key:
            raise ReaderError(f"{provider}: no API key configured")
        url = base_url or (GEMINI_BASE_URL if provider == "gemini" else None)
        self.client = OpenAI(api_key=api_key, base_url=url, timeout=timeout_s, max_retries=0)
        self.usage = Usage()

    def read(self, specimen: str, image_path: Path | None = None) -> LabelReading:
        path = image_path or Path("fixtures") / Path(specimen).name
        prepared = prepare(path)
        encoded = base64.b64encode(prepared.jpeg).decode()

        last: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                return self._extract(encoded)
            except (APIError, ValueError, KeyError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < RETRIES:
                    time.sleep(0.5 * (attempt + 1))
        raise ReaderError(f"{self.provider}/{self.model}: {last}") from last

    def _extract(self, encoded_jpeg: str) -> LabelReading:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded_jpeg}"},
                        },
                    ],
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "label_reading", "schema": SCHEMA, "strict": True},
            },
            **self._effort_kwargs(),
        )
        if response.usage is not None:
            self.usage = Usage(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("empty response")
        return self._to_reading(json.loads(content))

    def _effort_kwargs(self) -> dict[str, Any]:
        """Provider-specific request knobs, as the live APIs actually accept
        them (PRD §5.2, verified against both providers).

        Two corrections to the PRD's description, each found by calling the real
        endpoint rather than trusting the spec:

        1. Gemini's OpenAI-compatibility layer accepts `reasoning_effort`
           directly. Sending `thinking_level` - the native Gemini name - is a
           400 ("Unknown name \"thinking_level\""), whether passed as a keyword
           or through extra_body.
        2. OpenAI's `service_tier` does not accept "standard". The valid values
           are auto, default, fast, flex and priority, so the PRD's default is
           mapped onto `auto`.
        """
        kwargs: dict[str, Any] = {"service_tier": _SERVICE_TIER.get(
            self.service_tier, self.service_tier
        )}
        # `reasoning_effort` is only accepted by reasoning models; sending it to
        # a gpt-4.x model is a 400. Gate on the model name rather than probing.
        # ponytail: name-prefix check, swap for a capability lookup if either
        # provider ever ships one.
        if self.provider == "gemini" or _REASONING_MODEL.match(self.model):
            kwargs["reasoning_effort"] = self.effort
        return kwargs

    def _to_reading(self, payload: dict[str, Any]) -> LabelReading:
        warning = payload.get("warning") or {}
        quality: CaptureQuality = payload.get("quality", "normal")
        return LabelReading(
            brand=_field(payload.get("brand")),
            class_type=_field(payload.get("classType")),
            abv=_field(payload.get("abv")),
            net=_field(payload.get("net")),
            producer=_field(payload.get("producer")),
            origin=_field(payload.get("origin")),
            warning=WarningReading(
                present=bool(warning.get("present")),
                body=warning.get("body"),
                header_case=warning.get("headerCase"),
                header_bold=warning.get("headerBold"),
            ),
            quality=quality,
        )
