"""csv_io round-trip and formula-injection prefixing (PRD §4.3)."""

import csv
import io
from typing import Any

import pytest

from csv_io import (
    MIRROR_COLUMNS,
    REVIEW_COLUMNS,
    CsvImportError,
    from_csv,
    to_csv,
    to_review_csv,
)


def _row(**overrides: str) -> dict[str, Any]:
    base: dict[str, Any] = {col: "" for col in MIRROR_COLUMNS}
    base.update(
        id="rec-1",
        received="2026-08-19T00:00:00+00:00",
        applicant="Acme Distilling",
        app_brand="Old Tom",
        app_class_type="Bourbon",
        app_alcohol_content="45%",
        app_net_contents="750 mL",
        verified="False",
        field_results="brand:match|abv:match",
        field_notes="",
    )
    base.update(overrides)
    return base


def test_round_trip_is_byte_identical() -> None:
    rows = [_row(id="rec-1"), _row(id="rec-2", app_brand="Stone's Throw")]
    first = to_csv(rows)
    parsed = from_csv(first)
    second = to_csv(parsed)
    assert first == second


def test_from_csv_rejects_missing_app_brand() -> None:
    try:
        from_csv(b"id,received\nrec-1,2026-08-19\n")
        raise AssertionError("expected CsvImportError")
    except CsvImportError as exc:
        assert exc.field == "app_brand"


def test_from_csv_tolerates_bom_and_crlf() -> None:
    data = "﻿app_brand,id\r\nOld Tom,rec-1\r\n".encode()
    rows = from_csv(data)
    assert rows[0]["app_brand"] == "Old Tom"
    assert rows[0]["id"] == "rec-1"


def test_from_csv_tolerates_reordered_columns() -> None:
    data = b"id,app_brand\nrec-9,Old Tom\n"
    rows = from_csv(data)
    assert rows[0]["id"] == "rec-9"
    assert rows[0]["app_brand"] == "Old Tom"


def test_to_csv_prefixes_formula_injection_cells() -> None:
    data = to_csv([_row(app_brand="=cmd|'/c calc'!A1")])
    text = data.decode()
    assert "'=cmd" in text
    assert "\n=cmd" not in text and ",=cmd" not in text


def test_to_csv_fixed_column_order() -> None:
    data = to_csv([_row()])
    header = data.decode().splitlines()[0]
    assert header.split(",") == MIRROR_COLUMNS


def test_a_batch_intake_csv_is_named_as_such_not_as_a_missing_column() -> None:
    import batching

    data = (",".join(batching.INTAKE_COLUMNS) + "\na.png,Old Tom,Gin,40% ALC/VOL,750 ML,,,,\n")
    with pytest.raises(CsvImportError, match="batch-intake CSV"):
        from_csv(data.encode())


def test_the_review_export_names_the_fields_that_did_not_match() -> None:
    """What a reviewer takes away says which fields disagreed, in words - not a
    packed `abv:fail` cell they have to decode."""
    rows = [
        _row(id="rec-1", field_results="brand:match|abv:fail|warning:review"),
        _row(id="rec-2", field_results="brand:match|abv:match"),
    ]
    lines = to_review_csv(rows).decode().splitlines()

    assert lines[0] == ",".join(REVIEW_COLUMNS)
    assert "elapsed_ms" not in lines[0] and "field_results" not in lines[0]
    assert "engine" not in lines[0]
    # The intake header names, so the file can be re-uploaded as a batch.
    assert "brand_name" in lines[0] and "country_of_origin" in lines[0]

    assert '"Alcohol content, Government warning"' in lines[1]
    assert lines[2].endswith(",,,,,,")  # rec-2 matched: no issues, no decision


def test_the_review_export_carries_the_application_as_filed() -> None:
    row = _row(app_producer="Acme, Bardstown, KY", app_origin="France", note="Refile")
    parsed = list(csv.DictReader(io.StringIO(to_review_csv([row]).decode())))
    values = parsed[0]
    assert values["brand_name"] == "Old Tom"
    assert values["net_contents"] == "750 mL"
    assert values["country_of_origin"] == "France"
    assert values["producer"] == "Acme, Bardstown, KY"
    # `note` is the return reason; the column says so.
    assert values["reason"] == "Refile"
