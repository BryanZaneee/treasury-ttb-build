"""csv_io round-trip and formula-injection prefixing (PRD §4.3)."""

from typing import Any

import pytest

from csv_io import MIRROR_COLUMNS, CsvImportError, from_csv, to_csv


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
