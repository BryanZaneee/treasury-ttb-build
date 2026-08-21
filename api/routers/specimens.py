"""The bundled specimen catalogue (PRD §7). Read-only.

The 25 synthetic specimens are published so the single-label form can be filled
from a named sample and reproduce its documented verdict. Fictional brands, no
real trade dress, no applicant information of any kind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import Verdict
from readers.fake import expectations

router = APIRouter(tags=["specimens"], prefix="/specimens")


# The named samples the picker leads with (PRD §7), in the prototype's own copy.
SAMPLE_COPY: dict[str, tuple[str, str]] = {
    "old-tom-pass.jpg": ("Clean match", "Every field agrees"),
    "stones-throw-caps.jpg": ("Casing difference", "Brand set in full caps"),
    "harbor-mist-nowarning.jpg": ("Missing warning", "No warning statement"),
    "cedar-ridge-titlecase.jpg": ("Title-case warning", "Header not in all caps"),
    "lark-hollow-reworded.jpg": ("Reworded warning", "Statutory text altered"),
    "vinos-del-sol-abv.jpg": ("ABV mismatch", "12.5% on label, 13.5% filed"),
    "iron-gate-blur.jpg": ("Blurry capture", "Readable, low confidence"),
    "saltmarsh-glare.jpg": ("Glare on bottle", "Net contents illegible"),
    "north-fen-pixel.jpg": ("Pixelated upload", "Brand name illegible"),
    "brasserie-verte-origin.jpg": ("Missing origin", "Import lacks country of origin"),
    "quarry-house-units.jpg": ("Unit difference", "75 cl on label, 750 mL filed"),
    "golden-hour-nonbold.jpg": ("Non-bold header", "Warning header not bold"),
}


class SpecimenSummary(BaseModel):
    filename: str
    brand: str
    expected_verdict: Verdict
    quality: str
    intended_defect: str
    title: str = ""
    hint: str = ""


@router.get("", response_model=list[SpecimenSummary])
def list_specimens() -> list[SpecimenSummary]:
    """The 25 bundled specimens, with the verdict each one should produce."""
    out = []
    for filename, fixture in sorted(expectations().items()):
        title, hint = SAMPLE_COPY.get(filename, ("", ""))
        illegible = fixture["illegible"]
        degraded = fixture["degraded"]
        defect = ", ".join(
            [f"{f} illegible" for f in illegible] + [f"{f} degraded" for f in degraded]
        )
        out.append(
            SpecimenSummary(
                filename=filename,
                brand=fixture["app"]["brand"],
                expected_verdict=fixture["verdict"],
                quality=fixture["quality"],
                intended_defect=defect or "-",
                title=title,
                hint=hint,
            )
        )
    # Named samples first in PRD §7's order, the rest alphabetically.
    order = list(SAMPLE_COPY)
    return sorted(
        out,
        key=lambda s: (order.index(s.filename) if s.filename in order else len(order), s.filename),
    )


class FixturePrefill(BaseModel):
    filename: str
    applicant: str
    beverage: str
    app: dict[str, Any]


@router.get("/{filename}", response_model=FixturePrefill)
def fixture_prefill(filename: str) -> FixturePrefill:
    """The application values as filed for one bundled specimen (S2)."""
    fixture = expectations().get(Path(filename).name)
    if fixture is None:
        raise HTTPException(status_code=404, detail=f"unknown specimen {filename!r}")
    return FixturePrefill(
        filename=filename,
        applicant=fixture["applicant"],
        beverage=fixture["beverage"],
        app=fixture["app"],
    )
