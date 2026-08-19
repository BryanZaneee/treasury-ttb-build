"""Temporary developer bench (not part of the PRD §5.1 API surface).

Runs one specimen through several readers in the same process and reports what
each one saw, how long each stage took, and how its verdict compares to the
fixture ground truth. This is the interactive form of `scripts/bench.py`
(PRD §5.4) - it exists to answer "which reader, and how slow?" by measurement.

Remove this router before the M6 cutover; it is a development affordance and it
can spend money on every request.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db
from adjudicate import adjudicate
from models import Application, Verdict
from readers import PROVIDERS, get_reader
from readers.fake import expectations
from readers.prep import prepare

router = APIRouter(tags=["dev"], prefix="/dev")

# The named single-label samples published to the UI (PRD §7). Copy is the
# prototype's, so the picker reads the same as the approved design.
SAMPLE_COPY: dict[str, tuple[str, str]] = {
    "old-tom-pass.png": ("Clean match", "Every field agrees"),
    "stones-throw-caps.jpg": ("Casing difference", "Brand set in full caps"),
    "harbor-mist-nowarning.png": ("Missing warning", "No warning statement"),
    "cedar-ridge-titlecase.jpg": ("Title-case warning", "Header not in all caps"),
    "lark-hollow-reworded.png": ("Reworded warning", "Statutory text altered"),
    "vinos-del-sol-abv.jpg": ("ABV mismatch", "12.5% on label, 13.5% filed"),
    "iron-gate-blur.jpg": ("Blurry capture", "Readable, low confidence"),
    "saltmarsh-glare.jpg": ("Glare on bottle", "Net contents illegible"),
    "north-fen-pixel.png": ("Pixelated upload", "Brand name illegible"),
    "brasserie-verte-origin.jpg": ("Missing origin", "Import lacks country of origin"),
    "quarry-house-units.png": ("Unit difference", "75 cl on label, 750 mL filed"),
    "golden-hour-nonbold.jpg": ("Non-bold header", "Warning header not bold"),
}


class Lane(BaseModel):
    provider: str
    model: str | None = None
    effort: str | None = None


class BenchRequest(BaseModel):
    specimen: str
    lanes: list[Lane]


class FieldRow(BaseModel):
    field_key: str
    app_value: str | None = None
    label_value: str | None = None
    verdict: Verdict | None = None
    expected: Verdict | None = None
    note: str | None = None
    confidence: float | None = None


class LaneResult(BaseModel):
    provider: str
    model: str | None = None
    effort: str | None = None
    ok: bool
    error: str | None = None
    prep_ms: int | None = None
    reader_ms: int | None = None
    rules_ms: int | None = None
    total_ms: int | None = None
    verdict: Verdict | None = None
    expected_verdict: Verdict | None = None
    quality: str | None = None
    fields_correct: int | None = None
    fields_total: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    fields: list[FieldRow] = []


class BenchResponse(BaseModel):
    specimen: str
    expected_verdict: Verdict | None = None
    sharpness: float | None = None
    lanes: list[LaneResult] = []


class SpecimenSummary(BaseModel):
    filename: str
    brand: str
    expected_verdict: Verdict
    quality: str
    intended_defect: str
    title: str = ""
    hint: str = ""


@router.get("/specimens", response_model=list[SpecimenSummary])
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
    # The named samples the single-label picker leads with come first, in the
    # order PRD §7 lists them; the rest follow alphabetically.
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


@router.get("/fixture/{filename}", response_model=FixturePrefill)
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


@router.get("/providers", response_model=list[str])
def list_providers() -> list[str]:
    return list(PROVIDERS)


@router.get("/models", response_model=list[str])
def list_models(provider: str) -> list[str]:
    """Models the configured key can actually reach.

    The PRD names `gpt-5.6-luna` and `gemini-3.7-flash`, but which models a key
    is entitled to is an account fact, not a spec fact - so the bench asks the
    provider rather than offering a model the request would 400 on.
    """
    if provider not in ("openai", "gemini"):
        return []
    from openai import OpenAI

    from config import api_key_for
    from readers.vision import GEMINI_BASE_URL

    key = api_key_for(provider)
    if not key:
        raise HTTPException(status_code=422, detail=f"no API key configured for {provider}")
    client = OpenAI(
        api_key=key,
        base_url=GEMINI_BASE_URL if provider == "gemini" else None,
        timeout=20,
    )
    try:
        ids = [m.id.removeprefix("models/") for m in client.models.list()]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:200]) from exc
    # Image-capable text models only; embeddings, TTS and image *generators*
    # cannot read a label.
    skip = ("embedding", "-tts", "-image", "native-audio", "-live", "nano-banana", "robotics")
    return sorted(m for m in ids if not any(x in m for x in skip))


def _application(fixture: dict[str, Any]) -> Application:
    app = fixture["app"]
    return Application(
        brand=app["brand"],
        class_type=app["classType"],
        abv=app["abv"],
        net=app["net"],
        producer=app["producer"],
        origin=app["origin"],
        warning=app["warning"],
    )


def _image_path(specimen: str) -> Path:
    name = Path(specimen).name
    stored = db.data_dir() / "images" / name
    return stored if stored.exists() else Path("fixtures") / name


@router.post("/bench", response_model=BenchResponse)
def bench(body: BenchRequest) -> BenchResponse:
    fixture = expectations().get(Path(body.specimen).name)
    if fixture is None:
        raise HTTPException(status_code=404, detail=f"unknown specimen {body.specimen!r}")

    app = _application(fixture)
    path = _image_path(body.specimen)
    expected_fields: dict[str, Verdict] = fixture["field_verdicts"]

    # Measured once and reported alongside the lanes: every reader sees the
    # identical prepared image, so a difference is the reader's, not prep's.
    sharpness = prepare(path).sharpness if path.exists() else None

    lanes = [_run_lane(lane, body.specimen, path, app, expected_fields) for lane in body.lanes]
    return BenchResponse(
        specimen=body.specimen,
        expected_verdict=fixture["verdict"],
        sharpness=sharpness,
        lanes=lanes,
    )


def _run_lane(
    lane: Lane,
    specimen: str,
    path: Path,
    app: Application,
    expected_fields: dict[str, Verdict],
) -> LaneResult:
    base = LaneResult(provider=lane.provider, model=lane.model, effort=lane.effort, ok=False)
    try:
        reader = get_reader(lane.provider, lane.model, lane.effort)
    except Exception as exc:  # noqa: BLE001 - a misconfigured lane must not fail the others
        base.error = str(exc)
        return base

    started = time.perf_counter_ns()
    try:
        # The prepare() call inside each reader is the prep stage; timing it
        # separately here would double the work, so prep is reported as the
        # slice of reader time spent before the request goes out. For fake it
        # is zero because no image is opened at all.
        reading = reader.read(specimen, path)
    except Exception as exc:  # noqa: BLE001
        base.error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        base.total_ms = round((time.perf_counter_ns() - started) / 1_000_000)
        return base
    read_done = time.perf_counter_ns()

    results, verdict = adjudicate(f"bench-{lane.provider}", app, reading)
    finished = time.perf_counter_ns()

    rows = [
        FieldRow(
            field_key=r.field_key,
            app_value=r.app_value,
            label_value=r.label_value,
            verdict=r.verdict,
            expected=expected_fields.get(r.field_key),
            note=r.note,
            confidence=r.confidence,
        )
        for r in results
    ]
    correct = sum(1 for r in rows if r.expected is not None and r.verdict == r.expected)

    usage = getattr(reader, "usage", None)
    base.ok = True
    base.prep_ms = 0
    base.reader_ms = round((read_done - started) / 1_000_000)
    base.rules_ms = round((finished - read_done) / 1_000_000)
    base.total_ms = round((finished - started) / 1_000_000)
    base.verdict = verdict
    base.expected_verdict = None
    base.quality = reading.quality
    base.fields_correct = correct
    base.fields_total = len(expected_fields)
    base.input_tokens = getattr(usage, "input_tokens", None)
    base.output_tokens = getattr(usage, "output_tokens", None)
    base.fields = rows
    return base
