"""M2 exit gate: every fixture expectation reproduced by the rules engine.

`fixtures/expectations.json` is the ground truth (PRD §7, §13) - the same file
the M3 benchmark scores readers against. If a defect fixture ever reaches
`match` on the field it targets, that is a false auto-close and the release is
blocked (PRD §1, §5.4).
"""

from typing import Any

import pytest

from adjudicate import (
    _compare_abv,
    _compare_net,
    apply_quality,
    normalise,
    parse_abv,
    parse_net,
    roll_up,
)
from adjudicate import adjudicate as run
from models import Application, WarningReading
from readers.fake import FakeReader, expectations

FIXTURES = sorted(expectations())
reader = FakeReader()


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


@pytest.mark.parametrize("specimen", FIXTURES)
def test_fixture_field_verdicts(specimen: str) -> None:
    fixture = expectations()[specimen]
    results, verdict = run(specimen, _application(fixture), reader.read(specimen))

    actual = {r.field_key: r.verdict for r in results}
    assert actual == fixture["field_verdicts"], specimen
    assert verdict == fixture["verdict"], specimen


@pytest.mark.parametrize("specimen", FIXTURES)
def test_every_field_result_carries_a_note_unless_it_matches(specimen: str) -> None:
    """A reviewer must never see a non-match with no explanation to paste."""
    fixture = expectations()[specimen]
    results, _ = run(specimen, _application(fixture), reader.read(specimen))
    for result in results:
        if result.verdict != "match":
            assert result.note, f"{specimen}:{result.field_key} has no note"


def test_no_defect_fixture_reaches_match() -> None:
    """PRD §1: zero false auto-closes across the fixture set."""
    offenders = []
    for specimen in FIXTURES:
        fixture = expectations()[specimen]
        if fixture["verdict"] == "match":
            continue  # a clean reference is allowed to match
        _, verdict = run(specimen, _application(fixture), reader.read(specimen))
        if verdict == "match":
            offenders.append(specimen)
    assert offenders == []


def test_record_verdict_is_the_worst_field_verdict() -> None:
    assert roll_up(["match", "match"]) == "match"
    assert roll_up(["match", "review"]) == "review"
    assert roll_up(["match", "review", "fail"]) == "fail"
    assert roll_up([]) == "match"


def test_producer_state_abbreviation_equals_the_full_name() -> None:
    """PRD §3.1. No fixture files a producer this way, but a reviewer typing
    "Kentucky" against a label reading "KY" must not raise a false review."""
    assert normalise("producer", "Old Tom Distillery, Bardstown, Kentucky") == normalise(
        "producer", "Old Tom Distillery, Bardstown, KY"
    )


def test_net_contents_units_convert_to_millilitres() -> None:
    assert parse_net("750 mL") == (750.0, "ml")
    assert parse_net("75 cl") == (750.0, "cl")
    assert parse_net("1 L") == (1000.0, "l")
    assert parse_net("12 FL OZ") is not None
    assert abs(parse_net("12 FL OZ")[0] - 354.88) < 0.01  # type: ignore[index]
    assert parse_net("not a volume") is None


def test_degraded_capture_downgrades_only_a_confident_match() -> None:
    """Capture quality alone must not downgrade - two blurry fixtures and one
    angled one are legitimately `match`."""
    assert apply_quality("match", "angled", 0.55)[0] == "review"
    assert apply_quality("match", "angled", 0.99)[0] == "match"
    assert apply_quality("match", "normal", 0.55)[0] == "match"
    # A degraded capture never *improves* a field that already failed.
    assert apply_quality("fail", "angled", 0.55)[0] == "fail"


def test_a_specimen_that_is_not_a_label_is_invalid_not_fail() -> None:
    """PRD §3.2 extension. An image that is not a label cannot be adjudicated
    field by field: `fail` would tell the reviewer the applicant's label is
    wrong, when the finding is that the wrong file was filed."""
    fixture = expectations()["old-tom-pass.jpg"]
    app = _application(fixture)
    reading = reader.read("old-tom-pass.jpg")

    results, verdict = run("COLA-TEST", app, reading)
    assert verdict == "match" and results, "guard the control case first"

    results, verdict = run("COLA-TEST", app, reading.model_copy(update={"not_a_label": True}))
    assert verdict == "invalid"
    # No field rows: there is nothing to compare, and half-populated evidence
    # against a photograph of something else is worse than none.
    assert results == []


def test_a_missing_government_warning_never_matches() -> None:
    """27 CFR requires the warning, so an absent one fails however it was filed.
    An empty intake cell makes `declared` false (csv_io.parse_bool), which
    previously reached `match` - a clean auto-close on a non-compliant label."""
    for declared in (True, False):
        app = Application(
            brand="Old Tom", class_type="Gin", abv="40%", net="750 ml", warning=declared
        )
        reading = reader.read("old-tom-pass.jpg")
        reading.warning = WarningReading(present=False)
        _, verdict = run("old-tom-pass.jpg", app, reading)
        assert verdict == "fail", f"declared={declared} reached {verdict}"


def test_a_rounded_fl_oz_declaration_is_not_a_mismatch() -> None:
    """750 mL prints as 25.4 FL OZ, which converts back to 751.2 mL - 1.2 mL
    past the flat tolerance. The commonest US bottle size must not fail."""
    assert _compare_net("750 ml", "25.4 fl oz")[0] == "review"
    assert _compare_net("750 ml", "25 fl oz")[0] == "review"
    assert _compare_net("1.75 l", "59.2 fl oz")[0] == "review"
    # A genuinely different fill still fails.
    assert _compare_net("750 ml", "700 ml")[0] == "fail"
    assert _compare_net("1 l", "750 ml")[0] == "fail"


def test_a_decimal_comma_parses_to_the_stated_strength() -> None:
    """Imports are in scope (PRD §3.1) and the reader transcribes verbatim, so
    "0,75 L" arrives intact. It previously read as 75 L and "13,5%" as 5%."""
    assert parse_abv("13,5%") == 13.5
    assert parse_net("0,75 L") == (750.0, "l")
    # A comma before three digits is still a thousands separator.
    assert parse_net("1,000 ml") == (1000.0, "ml")


def test_centilitres_parse_in_either_spelling() -> None:
    assert parse_net("75 centiliters") == parse_net("75 centilitres") == (750.0, "cl")


def test_a_value_the_application_omitted_is_a_review_not_a_parse_failure() -> None:
    """The numeric comparators must ladder the way _compare_text does: a label
    value nobody filed is a review, and neither side having one is a match."""
    assert _compare_abv("", "13.5%")[0] == "review"
    assert _compare_net("", "750 ml")[0] == "review"
    assert _compare_abv("", "")[0] == "match"
    assert _compare_net("", "")[0] == "match"


def test_roll_up_ranks_invalid_rather_than_raising() -> None:
    """`invalid` is not a field verdict (PRD §3.2), but roll_up is public."""
    assert roll_up(["match", "invalid"]) == "invalid"
