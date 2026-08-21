"""Reader-layer contract tests (PRD §5.2).

No network: the vision adapter is exercised through its request-building
methods, which is where the provider-specific bugs actually live. The two
regressions covered here were both found by calling the live APIs - the spec
described neither correctly.
"""

import pytest

from models import LabelReading
from readers import get_reader
from readers.fake import FakeReader, expectations
from readers.ocr import OcrReader
from readers.vision import VisionReader, clamp_effort


def _reader(provider: str, model: str = "m", effort: str = "low") -> VisionReader:
    return VisionReader(provider=provider, model=model, api_key="test-key", effort=effort)


def test_effort_is_clamped_to_the_provider_floor() -> None:
    """PRD §5.2: configured effort is raised to the provider's floor."""
    assert clamp_effort("none") == "none"
    assert clamp_effort("medium") == "medium"
    # An unrecognised value falls to the floor rather than being forwarded.
    assert clamp_effort("nonsense") == "none"


def test_service_tier_standard_is_mapped_to_a_value_the_api_accepts() -> None:
    """Regression: PRD §5.2 calls the default tier "standard"; OpenAI accepts
    only auto, default, fast, flex and priority."""
    kwargs = _reader("openai")._effort_kwargs()
    assert kwargs["service_tier"] != "standard"
    assert kwargs["service_tier"] == "auto"


def test_reasoning_effort_is_withheld_from_non_reasoning_models() -> None:
    """gpt-4.x rejects `reasoning_effort` outright."""
    assert "reasoning_effort" not in _reader("openai", "gpt-4.1-mini")._effort_kwargs()
    assert "reasoning_effort" not in _reader("openai", "gpt-4o-mini")._effort_kwargs()
    assert "reasoning_effort" in _reader("openai", "gpt-5.4-nano")._effort_kwargs()


def test_a_vision_reader_without_a_key_fails_fast() -> None:
    with pytest.raises(Exception, match="no API key"):
        VisionReader(provider="openai", model="m", api_key="")


def test_registry_returns_the_configured_reader() -> None:
    assert isinstance(get_reader("fake"), FakeReader)
    assert isinstance(get_reader("ocr"), OcrReader)
    with pytest.raises(ValueError, match="unknown reader provider"):
        get_reader("nope")
    with pytest.raises(ValueError, match="unknown reader provider"):
        get_reader("gemini")


@pytest.mark.parametrize("specimen", ["old-tom-pass.jpg", "saltmarsh-glare.jpg"])
def test_fake_reader_conforms_to_the_reading_schema(specimen: str) -> None:
    """PRD §5.4: the benchmark code path is covered in CI against the fake
    reader, with no network access and no spend."""
    reading = FakeReader().read(specimen)
    assert isinstance(reading, LabelReading)
    fixture = expectations()[specimen]
    assert reading.quality == fixture["quality"]
    for key in fixture["illegible"]:
        field = getattr(reading, {"classType": "class_type"}.get(key, key))
        value = field.body if key == "warning" else field.value
        assert value == "ILLEGIBLE"


def test_fake_reader_rejects_an_unknown_specimen() -> None:
    with pytest.raises(KeyError):
        FakeReader().read("not-a-fixture.png")


def test_daily_call_cap_stops_paid_requests_and_does_not_retry() -> None:
    """PRD §8: the in-service backstop degrades rather than spending. A cap
    breach must not be retried - it cannot clear inside the retry window."""
    from readers import vision

    vision._calls.clear()
    reader = VisionReader(provider="openai", model="m", api_key="k", daily_call_cap=2)
    vision._charge_one_call(2)
    vision._charge_one_call(2)
    assert vision.calls_today() == 2
    with pytest.raises(vision.SpendCapReached):
        vision._charge_one_call(2)
    # A zero cap disables the backstop entirely.
    vision._charge_one_call(0)
    assert reader.daily_call_cap == 2
    vision._calls.clear()


def test_a_reader_cannot_express_a_verdict() -> None:
    """PRD §3.2 holds by construction: no reader can express a verdict at all."""
    from readers.prompts import SCHEMA

    assert "verdict" not in str(SCHEMA).lower(), "the reader schema must not expose a verdict"
    assert SCHEMA.get("additionalProperties") is False, "an open schema lets a verdict back in"

    verdict_fields = [f for f in LabelReading.model_fields if "verdict" in f.lower()]
    assert verdict_fields == [], f"LabelReading gained a verdict field: {verdict_fields}"


def test_the_ocr_warning_body_stops_at_the_statement() -> None:
    """`_lines` concatenates a psm-3 and a psm-6 pass, so a body read to the end
    of the list absorbs the second pass and fails a compliant label on the
    verbatim compare. Pure over `_Line`, so it needs no Tesseract."""
    from adjudicate import STATUTORY_WARNING, warning_body
    from readers.ocr import _Line, _warning

    statute = STATUTORY_WARNING.split(": ", 1)[1]
    lines = [
        # Pass 1: the display type, then the warning block.
        _Line("OLD TOM", 92.0),
        _Line("GOVERNMENT WARNING: " + statute, 88.0),
        # Pass 2: the same label read again, which must not join the body.
        _Line("OLD TOM GIN", 90.0),
        _Line("40% ALC/VOL 750 ML", 91.0),
        _Line("Bottled by Old Tom Distillery", 87.0),
    ]
    reading = _warning(lines)
    assert reading.present is True
    assert reading.body is not None
    assert warning_body(reading.body) == warning_body(STATUTORY_WARNING)
    assert "750 ML" not in reading.body
