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
    """PRD §5.2 / acceptance test 16: Gemini rejects anything below `low`."""
    assert clamp_effort("gemini", "minimal") == "low"
    assert clamp_effort("gemini", "none") == "low"
    assert clamp_effort("gemini", "high") == "high"
    assert clamp_effort("openai", "none") == "none"
    assert clamp_effort("openai", "medium") == "medium"
    # An unrecognised value falls to the floor rather than being forwarded.
    assert clamp_effort("gemini", "nonsense") == "low"


def test_gemini_uses_reasoning_effort_not_thinking_level() -> None:
    """Regression: Gemini's OpenAI-compatibility layer 400s on `thinking_level`
    ('Unknown name "thinking_level"'), by keyword or via extra_body."""
    kwargs = _reader("gemini", "gemini-3.7-flash")._effort_kwargs()
    assert "thinking_level" not in str(kwargs)
    assert kwargs["reasoning_effort"] == "low"


def test_service_tier_standard_is_mapped_to_a_value_the_api_accepts() -> None:
    """Regression: PRD §5.2 calls the default tier "standard"; OpenAI accepts
    only auto, default, fast, flex and priority."""
    for provider in ("openai", "gemini"):
        kwargs = _reader(provider)._effort_kwargs()
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


def test_gemini_gets_the_compatibility_base_url() -> None:
    assert "generativelanguage" in str(_reader("gemini").client.base_url)


def test_registry_returns_the_configured_reader() -> None:
    assert isinstance(get_reader("fake"), FakeReader)
    assert isinstance(get_reader("ocr"), OcrReader)
    with pytest.raises(ValueError, match="unknown reader provider"):
        get_reader("nope")


@pytest.mark.parametrize("specimen", ["old-tom-pass.png", "saltmarsh-glare.jpg"])
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
