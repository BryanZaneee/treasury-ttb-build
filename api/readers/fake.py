"""Fixture-replaying reader - the CI reader, no network and no spend (PRD §5.2).

Replays `fixtures/expectations.json`'s `label` block, which is what a perfect
reader would have seen on that specimen. Fields listed under `illegible` come
back as the `ILLEGIBLE` sentinel; fields listed under `degraded` come back with
a value but low confidence, which is what drives the §3.2 degraded-capture
downgrade.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from models import CaptureQuality, FieldReading, LabelReading, WarningReading

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

ILLEGIBLE = "ILLEGIBLE"
CONFIDENT = 0.99
DEGRADED = 0.55


@cache
def expectations() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES_DIR / "expectations.json").read_text())
    return data


class FakeReader:
    name = "fake"

    def read(self, specimen: str, image_path: Path | None = None) -> LabelReading:
        # The fixture replayer never opens the image - it replays what a
        # perfect reader would have seen. image_path is accepted so every
        # reader satisfies one protocol.
        del image_path
        fixture = expectations().get(Path(specimen).name)
        if fixture is None:
            raise KeyError(f"no fixture expectation for specimen {specimen!r}")

        label = fixture["label"]
        illegible = set(fixture.get("illegible", []))
        degraded = set(fixture.get("degraded", []))

        def field(key: str) -> FieldReading:
            if key in illegible:
                return FieldReading(value=ILLEGIBLE, confidence=DEGRADED)
            return FieldReading(
                value=label[key],
                confidence=DEGRADED if key in degraded else CONFIDENT,
            )

        warning_illegible = "warning" in illegible
        quality: CaptureQuality = fixture["quality"]
        return LabelReading(
            brand=field("brand"),
            class_type=field("classType"),
            abv=field("abv"),
            net=field("net"),
            producer=field("producer"),
            origin=field("origin"),
            warning=WarningReading(
                present=label["warningPresent"],
                body=ILLEGIBLE if warning_illegible else label["warningBody"],
                header_case=label["warningHeaderCase"],
                header_bold=label["warningHeaderBold"],
            ),
            quality=quality,
        )
