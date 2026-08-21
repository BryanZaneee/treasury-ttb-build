"""Pydantic v2 domain models. Shapes only, no storage.

Names mirror PRD §3.1 and §4.1 verbatim so nothing needs renaming on the way to
or from the database.
"""

from typing import Literal

from pydantic import BaseModel

# "invalid" extends PRD §3.2's enum: `fail` would blame the applicant's label
# for the wrong image being filed. Only the vision reader raises it.
Verdict = Literal["match", "review", "fail", "invalid"]
Decision = Literal["accepted", "returned"] | None
CaptureQuality = Literal[
    "normal",
    "blurry",
    "heavyBlur",
    "glare",
    "pixelated",
    "angled",
    "dark",
    "damaged",
    "cropped",
]


class Application(BaseModel):
    """The seven verified fields as filed by the applicant (PRD §3.1)."""

    brand: str
    class_type: str
    abv: str
    net: str
    producer: str | None = None
    origin: str | None = None
    warning: bool = False


class FieldReading(BaseModel):
    """One field as observed by a reader. `ILLEGIBLE` is a sentinel, not a value."""

    value: str | Literal["ILLEGIBLE"] | None = None
    confidence: float | None = None


class WarningReading(BaseModel):
    """The government warning composite (PRD §5.2): body plus header presentation."""

    present: bool
    body: str | Literal["ILLEGIBLE"] | None = None
    header_case: str | None = None
    header_bold: bool | None = None


class LabelReading(BaseModel):
    """A full extraction pass across the seven fields, from one reader."""

    brand: FieldReading
    class_type: FieldReading
    abv: FieldReading
    net: FieldReading
    producer: FieldReading
    origin: FieldReading
    warning: WarningReading
    quality: CaptureQuality
    # The image is clearly not an alcohol beverage label (PRD §3.2 ext).
    not_a_label: bool = False


class FieldResult(BaseModel):
    """One row of the `field_results` table (PRD §4.1)."""

    record_id: str
    field_key: str
    app_value: str | None = None
    label_value: str | None = None
    verdict: Verdict | None = None
    note: str | None = None
    confidence: float | None = None


class Record(BaseModel):
    """One row of `records` (PRD §4.1); `result` is null until verified."""

    id: str
    received: str
    applicant: str
    beverage: str
    filename: str
    specimen: str
    quality: CaptureQuality | None = None
    app_brand: str
    app_class_type: str
    app_alcohol_content: str
    app_net_contents: str
    app_producer: str | None = None
    app_origin: str | None = None
    app_warning_declared: bool = False
    verified: bool = False
    result: Verdict | None = None
    elapsed_ms: int | None = None
    engine: str | None = None
    decision: Decision = None
    decided_by: str | None = None
    decided_at: str | None = None
    note: str | None = None

    # Database-only columns, not part of the CSV mirror (PRD §4.1).
    override: bool = False
    reader_provider: str | None = None
    reader_model: str | None = None
    prompt_version: str | None = None
    prep_ms: int | None = None
    reader_ms: int | None = None
    rules_ms: int | None = None
