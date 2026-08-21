"""OpenAI vision reader (PRD §5.2).

A thin adapter on the Chat Completions API, so any OpenAI-compatible endpoint is
a base-URL change rather than a rewrite.

ponytail: synchronous client. The callers are sync `def`, so FastAPI already
runs them in a threadpool; move to AsyncOpenAI if a 300-record batch needs more.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import APIError, OpenAI

from models import CaptureQuality, FieldReading, LabelReading, WarningReading
from readers.prep import prepare
from readers.prompts import PROMPT, SCHEMA, VERSION

# PRD §5.2 clamps configured effort to the provider floor; OpenAI accepts "none".
_EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
_EFFORT_FLOOR = "none"

RETRIES = 2

_REASONING_MODEL = re.compile(r"^(gpt-[5-9]|o[1-9])", re.IGNORECASE)

# PRD §5.2 calls the default tier "standard"; the API does not have that value.
_SERVICE_TIER = {"standard": "auto"}


class ReaderError(RuntimeError):
    """The reader could not produce a usable reading. Callers fall back to OCR."""


class SpendCapReached(ReaderError):
    """The daily paid-call ceiling is spent. Verification degrades to rules."""


# In-service backstop behind the provider's own spend limit (PRD §8). The PRD
# sets it in dollars; counting calls needs no price table and cannot go stale.
# ponytail: in-process, so per-worker and reset on restart - move it to the
# audit table if the cap ever has to hold across either.
_calls: dict[str, int] = {}


def _charge_one_call(cap: int) -> None:
    today = datetime.now(UTC).date().isoformat()
    spent = _calls.get(today, 0)
    if cap and spent >= cap:
        raise SpendCapReached(
            f"daily paid-call cap of {cap} reached; verification is rules-only "
            "until UTC midnight"
        )
    _calls[today] = spent + 1


def calls_today() -> int:
    return _calls.get(datetime.now(UTC).date().isoformat(), 0)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


def clamp_effort(effort: str) -> str:
    """Raise a configured effort to the provider floor (PRD §5.2)."""
    if effort not in _EFFORT_ORDER:
        return _EFFORT_FLOOR
    return max(effort, _EFFORT_FLOOR, key=_EFFORT_ORDER.index)


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
        daily_call_cap: int = 0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.effort = clamp_effort(effort)
        self.service_tier = service_tier
        self.prompt_version = VERSION
        self.daily_call_cap = daily_call_cap
        if not api_key:
            raise ReaderError(f"{provider}: no API key configured")
        self.client = OpenAI(
            api_key=api_key, base_url=base_url or None, timeout=timeout_s, max_retries=0
        )
        self.usage = Usage()

    def read(self, specimen: str, image_path: Path | None = None) -> LabelReading:
        path = image_path or Path("fixtures") / Path(specimen).name
        prepared = prepare(path)
        encoded = base64.b64encode(prepared.jpeg).decode()

        last: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                return self._extract(encoded)
            except SpendCapReached:
                raise
            except (APIError, ValueError, KeyError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < RETRIES:
                    time.sleep(0.5 * (attempt + 1))
        raise ReaderError(f"{self.provider}/{self.model}: {last}") from last

    def _extract(self, encoded_jpeg: str) -> LabelReading:
        _charge_one_call(self.daily_call_cap)
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
        """Request knobs as the live API actually accepts them (PRD §5.2).

        Correcting the spec from the real endpoint: `service_tier` does not
        accept "standard", so the PRD's default is mapped onto `auto`.
        """
        kwargs: dict[str, Any] = {"service_tier": _SERVICE_TIER.get(
            self.service_tier, self.service_tier
        )}
        # `reasoning_effort` is a 400 on a non-reasoning model, so gate on name.
        # ponytail: name prefix; swap for a capability lookup if one ships.
        if _REASONING_MODEL.match(self.model):
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
            not_a_label=bool(payload.get("notALabel")),
        )
