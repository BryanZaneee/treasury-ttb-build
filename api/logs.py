"""Structured logging and service counters (PRD §8).

JSON on stdout, one object per line, so the journal unit on the app host can be
shipped without a parser. Every line carries the request id stamped by the
middleware in main.py, which is what lets one reviewer's failed verification be
followed across the reader, the rules engine and the store.

Applicant names and reviewer notes never reach a log line: `redact` drops them
by key, so a payload picked up from a record row cannot leak one by accident.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import uuid
from contextvars import ContextVar
from typing import Any

# PRD §8: personal and free-text fields stay out of logs. Keyed rather than
# pattern-matched - a note can contain anything, including something that looks
# like an id, so the only safe rule is never to emit the field at all.
REDACTED_KEYS = frozenset(
    {"applicant", "note", "notes", "reason", "reviewer_name", "decided_by", "field_notes"}
)

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_counters: dict[str, int] = {}
_counter_lock = threading.Lock()

logger = logging.getLogger("ttb")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(value: str) -> None:
    _request_id.set(value)


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if k in REDACTED_KEYS else v) for k, v in payload.items()}


def count(name: str, amount: int = 1) -> None:
    with _counter_lock:
        _counters[name] = _counters.get(name, 0) + amount


def counters() -> dict[str, int]:
    with _counter_lock:
        return dict(_counters)


def reset_counters() -> None:
    with _counter_lock:
        _counters.clear()


def event(name: str, **fields: Any) -> None:
    """Log one structured event. Field values are redacted by key."""
    logger.info(name, extra={"fields": redact(fields)})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "request_id": _request_id.get(),
        }
        line.update(getattr(record, "fields", {}))
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure() -> None:
    """Idempotent: uvicorn --reload re-imports, and two handlers double lines."""
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
