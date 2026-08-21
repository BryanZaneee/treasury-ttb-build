"""Deterministic rules engine (PRD §3).

The verdict of record is produced here, from normalised application values
against normalised label values. A reader supplies observed values only; it
cannot express a verdict at all (PRD §3.2). Pure functions - no I/O, no reader.
"""

from __future__ import annotations

import re
import unicodedata

import csv_io
from models import (
    Application,
    CaptureQuality,
    FieldResult,
    LabelReading,
    Verdict,
    WarningReading,
)

# PRD §3.1 field keys in determination-view order. camelCase is the fixture and
# CSV vocabulary; the map to Application's attributes is explicit, not derived.
FIELD_KEYS = ("brand", "classType", "abv", "net", "producer", "origin", "warning")
_APP_ATTR = {
    "brand": "brand",
    "classType": "class_type",
    "abv": "abv",
    "net": "net",
    "producer": "producer",
    "origin": "origin",
}

# One spelling of each field name, shared with the CSV `issues` column: two
# tables drifted and named the same field two ways. PRD §3.1 spells it spaced.
_LABELS = csv_io.FIELD_LABEL

# Adjudicated on every record. `producer` is conditional and `origin` is
# imports-only (PRD §3.1), so those wait for a value on one side.
_ALWAYS = ("brand", "classType", "abv", "net", "warning")

ILLEGIBLE = "ILLEGIBLE"

# `invalid` is not a field verdict (PRD §3.2) and adjudicate() short-circuits
# before the roll-up, but roll_up is public: rank it rather than KeyError.
_RANK: dict[Verdict, int] = {"match": 0, "review": 1, "fail": 2, "invalid": 3}

# Below this, a non-normal capture downgrades an otherwise-matching field (§3.2).
DEGRADED_CONFIDENCE = 0.7

# PRD §3.1: net contents tolerance.
NET_TOLERANCE_ML = 1.0
# ABV prints to one decimal, so anything closer is the same stated strength.
ABV_TOLERANCE = 0.05

_ML_PER = {"ml": 1.0, "cl": 10.0, "l": 1000.0, "floz": 29.5735295625}

# A number as printed on a label. `[.,]` because imports are in scope (PRD §3.1)
# and a European label writes "0,75 L"; the reader transcribes it verbatim.
_NUMBER = r"\d[\d.,]*"


def _to_float(raw: str) -> float | None:
    """A printed number to a float; a comma before three digits is thousands."""
    try:
        return float(re.sub(r",(?=\d{3}\b)", "", raw).replace(",", "."))
    except ValueError:
        return None

# PRD §3.1: "state abbreviation = full name" on producer.
_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc",
}
_STATE_RE = re.compile(r"\b(" + "|".join(_STATES) + r")\b")

# Statement-of-responsibility prefixes that precede the producer name.
_RESPONSIBILITY_RE = re.compile(
    r"^\s*(bottled|produced|brewed|distilled|imported|vinted|packaged|"
    r"blended|manufactured)(\s+and\s+bottled)?\s+(by|for)\s+",
    re.IGNORECASE,
)


def _fold(value: str) -> str:
    """Case-fold, strip diacritics and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    depunctuated = re.sub(r"[^\w\s]", " ", without_marks)
    return " ".join(depunctuated.casefold().split())


def normalise(key: str, value: str | None) -> str | float | None:
    """Field value reduced to the form the comparison is made on (PRD §3.1)."""
    if value is None or not value.strip():
        return None
    if key == "abv":
        return parse_abv(value)
    if key == "net":
        parsed = parse_net(value)
        return None if parsed is None else parsed[0]
    if key == "classType":
        # Drop trailing parentheticals, e.g. "Vodka (Grain Neutral)".
        return _fold(re.sub(r"\s*\([^)]*\)\s*$", "", value))
    if key == "producer":
        # "Bottled by X" and "X" name the same producer: label convention.
        without_prefix = _RESPONSIBILITY_RE.sub("", value)
        return _STATE_RE.sub(lambda m: _STATES[m.group(1)], _fold(without_prefix))
    if key == "origin":
        # "Product of X" = "X".
        return re.sub(r"^product of\s+", "", _fold(value))
    return _fold(value)


def parse_abv(value: str) -> float | None:
    """Percent by volume as a float. A proof statement is informational only."""
    match = re.search(rf"({_NUMBER})\s*%", value)
    if match is None:
        return None
    return _to_float(match.group(1))


def parse_net(value: str) -> tuple[float, str] | None:
    match = re.search(
        rf"({_NUMBER})\s*(ml|milliliters?|millilitres?|cl|centiliters?|centilitres?|"
        r"l|liters?|litres?|fl\.?\s*oz|fluid ounces?)",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    raw_unit = match.group(2).casefold().replace(".", "").replace(" ", "")
    if raw_unit.startswith("fl"):
        unit = "floz"
    elif raw_unit.startswith(("cl", "centi")):
        unit = "cl"
    elif raw_unit.startswith(("ml", "milli")):
        unit = "ml"
    else:
        unit = "l"
    amount = _to_float(match.group(1))
    return None if amount is None else (amount * _ML_PER[unit], unit)


def rounding_tolerance_ml(raw: str, unit: str) -> float:
    """A fl oz declaration is a rounded conversion of the metric fill, so it is
    only as precise as its last printed digit - 25.4 FL OZ means 750 mL."""
    if unit != "floz":
        return 0.0
    match = re.search(r"\d+(?:[.,](\d+))?", raw)
    places = len(match.group(1)) if match and match.group(1) else 0
    return 0.5 * 10.0**-places * _ML_PER["floz"]


def roll_up(verdicts: list[Verdict]) -> Verdict:
    """Record verdict is the worst field verdict (PRD §3.2)."""
    if not verdicts:
        return "match"
    return max(verdicts, key=lambda v: _RANK[v])


def apply_quality(
    verdict: Verdict, quality: CaptureQuality | None, confidence: float | None
) -> tuple[Verdict, str | None]:
    """Downgrade an otherwise-matching field read from a degraded capture.

    Quality alone is not enough - two blurry fixtures are legitimately `match`.
    It takes a poor capture *and* a reading the reader was unsure of.
    """
    if (
        verdict == "match"
        and quality is not None
        and quality != "normal"
        and confidence is not None
        and confidence < DEGRADED_CONFIDENCE
    ):
        return "review", (
            f"Values agree, but the capture is {quality} and this field was read "
            "with low confidence. Confirm against the specimen before closing."
        )
    return verdict, None


# 27 CFR fixes the warning verbatim, so the label is compared against the
# statute; the application only declares it present (PRD §3.1, §4.1).
STATUTORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)


_WARNING_HEADER = re.compile(r"^\s*GOVERNMENT\s+WARNING\s*:?\s*", re.IGNORECASE)


def warning_body(text: str) -> str:
    """The statement without its header - case is reported separately (§3.2)."""
    return " ".join(_WARNING_HEADER.sub("", text).split())


def _illegible_note(key: str) -> str:
    return (
        f"{_LABELS[key]} could not be read from the specimen. Request a clearer "
        "capture, or confirm the value against the physical label."
    )


def _presentation_form(key: str, value: str) -> str:
    """The value as the reviewer sees it, less conventions that are not
    presentation differences - "Bottled by X" against "X" must not raise a
    review the way a real capitalisation variant does."""
    if key == "producer":
        return _RESPONSIBILITY_RE.sub("", value).strip()
    return value


def _compare_text(key: str, app_raw: str | None, label_raw: str | None) -> tuple[Verdict, str | None]:
    label = _LABELS[key]
    if label_raw == ILLEGIBLE:
        return "fail", _illegible_note(key)
    if app_raw and not label_raw:
        return "fail", (
            f"{label} was filed as “{app_raw}” but does not appear on the label."
        )
    if label_raw and not app_raw:
        return "review", (
            f"The label shows a {label.lower()} of “{label_raw}” that the "
            "application did not declare. Confirm the filing is complete."
        )
    if not app_raw and not label_raw:
        return "match", None

    assert app_raw is not None and label_raw is not None
    if normalise(key, app_raw) != normalise(key, label_raw):
        return "fail", (
            f"{label} differs: the application filed “{app_raw}”, the label "
            f"shows “{label_raw}”."
        )
    app_shown = _presentation_form(key, app_raw)
    label_shown = _presentation_form(key, label_raw)
    if app_shown == label_shown:
        return "match", None

    if app_shown.casefold() == label_shown.casefold():
        difference = "capitalisation"
    elif " ".join(app_shown.split()).casefold() == " ".join(label_shown.split()).casefold():
        difference = "capitalisation and spacing"
    else:
        difference = "punctuation"
    return "review", (
        f"Same {label.lower()}; {difference} differs. The application filed "
        f"“{app_raw}” and the label shows “{label_raw}”. "
        "Presentation only, not a substantive difference."
    )


def _compare_abv(app_raw: str | None, label_raw: str | None) -> tuple[Verdict, str | None]:
    if label_raw == ILLEGIBLE:
        return "fail", _illegible_note("abv")
    if app_raw and not label_raw:
        return "fail", (
            f"Alcohol content was filed as “{app_raw}” but does not appear on the label."
        )
    # Same ladder as _compare_text: an undeclared value the label shows is a
    # review, not a parse failure, and neither side having one is a match.
    if label_raw and not app_raw:
        return "review", (
            f"The label shows an alcohol content of “{label_raw}” that the "
            "application did not declare. Confirm the filing is complete."
        )
    if not app_raw and not label_raw:
        return "match", None
    filed = parse_abv(app_raw or "")
    shown = parse_abv(label_raw or "")
    if filed is None or shown is None:
        return "fail", (
            "Alcohol content could not be read as a percentage by volume "
            f"(application “{app_raw}”, label “{label_raw}”)."
        )
    if abs(filed - shown) <= ABV_TOLERANCE:
        return "match", None
    return "fail", (
        f"Alcohol content differs: the application filed {filed:g}% by volume, the "
        f"label states {shown:g}%."
    )


def _compare_net(app_raw: str | None, label_raw: str | None) -> tuple[Verdict, str | None]:
    if label_raw == ILLEGIBLE:
        return "fail", _illegible_note("net")
    if app_raw and not label_raw:
        return "fail", (
            f"Net contents were filed as “{app_raw}” but do not appear on the label."
        )
    if label_raw and not app_raw:
        return "review", (
            f"The label shows net contents of “{label_raw}” that the application "
            "did not declare. Confirm the filing is complete."
        )
    if not app_raw and not label_raw:
        return "match", None
    filed = parse_net(app_raw or "")
    shown = parse_net(label_raw or "")
    if filed is None or shown is None:
        return "fail", (
            "Net contents could not be read as a volume "
            f"(application “{app_raw}”, label “{label_raw}”)."
        )
    tolerance = max(
        NET_TOLERANCE_ML,
        rounding_tolerance_ml(app_raw or "", filed[1]),
        rounding_tolerance_ml(label_raw or "", shown[1]),
    )
    if abs(filed[0] - shown[0]) > tolerance:
        return "fail", (
            f"Net contents differ: the application filed “{app_raw}” "
            f"({filed[0]:g} mL), the label shows “{label_raw}” ({shown[0]:g} mL)."
        )
    if filed[1] != shown[1]:
        return "review", (
            f"Equivalent volume expressed in a different unit: the application filed "
            f"“{app_raw}” and the label shows “{label_raw}” "
            f"({shown[0]:g} mL either way). Presentation only."
        )
    return "match", None


def _compare_warning(reading: WarningReading) -> tuple[Verdict, str | None]:
    # 27 CFR requires the warning on every label, so its absence is a fail even
    # when the application did not declare one (PRD §3.1: required).
    if not reading.present:
        return "fail", (
            "The government warning statement is absent from the specimen. A "
            "compliant label must carry it verbatim."
        )
    if reading.body == ILLEGIBLE:
        return "fail", _illegible_note("warning")
    if reading.body is None or warning_body(reading.body) != warning_body(STATUTORY_WARNING):
        return "fail", (
            "The government warning on the label is not the required statement. It "
            "must appear verbatim, including the numbering and punctuation."
        )
    if reading.header_case is not None and reading.header_case != "upper":
        return "review", (
            "The government warning text is correct, but the “GOVERNMENT "
            "WARNING” header is not in capital letters. Cosmetic defect - the "
            "statement itself is compliant."
        )
    if reading.header_bold is False:
        return "review", (
            "The government warning text is correct, but the “GOVERNMENT "
            "WARNING” header is not bold. Cosmetic defect - the statement "
            "itself is compliant."
        )
    return "match", None


def adjudicate(
    record_id: str, app: Application, reading: LabelReading
) -> tuple[list[FieldResult], Verdict]:
    """Compare an application to a label reading, field by field (PRD §3.2).

    Returns the field results and the rolled-up record verdict.
    """
    # Not a label: no field rows, no roll-up. A per-field verdict would blame the
    # brand name for the wrong file being filed (PRD §3.2 extension).
    if reading.not_a_label:
        return [], "invalid"

    results: list[FieldResult] = []

    for key in FIELD_KEYS:
        if key == "warning":
            verdict, note = _compare_warning(reading.warning)
            results.append(
                FieldResult(
                    record_id=record_id,
                    field_key=key,
                    app_value="declared" if app.warning else "not declared",
                    label_value=reading.warning.body if reading.warning.present else None,
                    verdict=verdict,
                    note=note,
                )
            )
            continue

        app_raw: str | None = getattr(app, _APP_ATTR[key])
        field = getattr(reading, _APP_ATTR[key])
        label_raw: str | None = field.value

        # producer is conditional, origin imports-only: only when a side has one.
        if key not in _ALWAYS and not app_raw and label_raw in (None, ""):
            continue

        if key == "abv":
            verdict, note = _compare_abv(app_raw, label_raw)
        elif key == "net":
            verdict, note = _compare_net(app_raw, label_raw)
        else:
            verdict, note = _compare_text(key, app_raw, label_raw)

        verdict, quality_note = apply_quality(verdict, reading.quality, field.confidence)
        results.append(
            FieldResult(
                record_id=record_id,
                field_key=key,
                app_value=app_raw,
                label_value=label_raw,
                verdict=verdict,
                note=quality_note or note,
                confidence=field.confidence,
            )
        )

    verdicts = [r.verdict for r in results if r.verdict is not None]
    return results, roll_up(verdicts)
