"""Local Tesseract reader (PRD §5.3). No network, no marginal cost.

The fallback when the vision reader is unreachable, not an always-on second
reader. It reads the plain sans-serif warning near-perfectly and stylised brand
type badly; a field it cannot find returns `None`, which the rules engine reads
as absent-from-label rather than as a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image

from models import CaptureQuality, FieldReading, LabelReading, WarningReading
from readers.prep import Prepared, prepare

# Confidence Tesseract reports per word; below this the word is noise.
MIN_WORD_CONFIDENCE = 30.0

_PRODUCER_RE = re.compile(
    r"\b(?:bottled|produced|brewed|distilled|imported|vinted|packaged)\s+"
    r"(?:and\s+bottled\s+)?(?:by|for)\s+(?P<name>.+)",
    re.IGNORECASE,
)
_ORIGIN_RE = re.compile(r"\bproduct\s+of\s+(?P<name>[A-Za-z .'-]+)", re.IGNORECASE)
_ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*alc", re.IGNORECASE)
_ABV_LOOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NET_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ml|mL|ML|cl|cL|CL|L|l|fl\.?\s*oz|FL\.?\s*OZ)\b"
)
_WARNING_RE = re.compile(r"GOVERNMENT\s+WARNING", re.IGNORECASE)

# Lines that are never the brand or the class/type.
_NOISE = re.compile(
    r"government warning|bottled|produced|brewed|distilled|imported|vinted"
    r"|packaged|product of|alc\.?/?\s*vol|proof|^est\b|\bseries\b|^\W*$",
    re.IGNORECASE,
)


@dataclass
class _Line:
    text: str
    confidence: float


# Two passes: psm 3 gets the display type, psm 6 the body block. On harbor-mist
# that is 15 words against 25, neither set containing the other.
_PASSES = ("--psm 3", "--psm 6")


def _lines(image: Image.Image) -> list[_Line]:
    """OCR the image into lines, each carrying its mean word confidence."""
    lines: list[_Line] = []
    seen: set[str] = set()
    for config in _PASSES:
        for line in _pass(image, config):
            key = " ".join(line.text.split()).casefold()
            if key not in seen:
                seen.add(key)
                lines.append(line)
    return lines


def _pass(image: Image.Image, config: str) -> list[_Line]:
    data = pytesseract.image_to_data(
        image, config=config, output_type=pytesseract.Output.DICT
    )
    grouped: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    for i, word in enumerate(data["text"]):
        text = word.strip()
        confidence = float(data["conf"][i])
        if not text or confidence < MIN_WORD_CONFIDENCE:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append((text, confidence))

    out = []
    for words in grouped.values():
        text = " ".join(w for w, _ in words)
        mean = sum(c for _, c in words) / len(words)
        out.append(_Line(text=text, confidence=mean / 100.0))
    return out


def _find(lines: list[_Line], pattern: re.Pattern[str]) -> tuple[str | None, float | None]:
    for line in lines:
        match = pattern.search(line.text)
        if match:
            value = match.groupdict().get("name") or match.group(0)
            return value.strip().rstrip(".,"), line.confidence
    return None, None


def _brand_and_class(lines: list[_Line]) -> tuple[_Line | None, _Line | None]:
    """Brand is the most emphatically-cased line, class/type the one after it.

    Weak by construction: OCR has no type size, so it cannot see that the brand
    is the biggest thing on the label. The field where it does worst (PRD §5.4).
    """
    candidates = [
        line
        for line in lines
        if not _NOISE.search(line.text)
        and not _NET_RE.search(line.text)
        and len(line.text) > 2
        and any(c.isalpha() for c in line.text)
    ]
    if not candidates:
        return None, None

    def upper_ratio(line: _Line) -> float:
        letters = [c for c in line.text if c.isalpha()]
        return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0

    brand = max(candidates, key=lambda line: (upper_ratio(line), len(line.text)))
    index = candidates.index(brand)
    class_type = candidates[index + 1] if index + 1 < len(candidates) else None
    return brand, class_type


def _quality(prepared: Prepared) -> CaptureQuality:
    """OCR sees blur and nothing else, so anything else reports `normal`."""
    if prepared.sharpness < 15.0:
        return "heavyBlur"
    if not prepared.is_sharp:
        return "blurry"
    return "normal"


def _warning(lines: list[_Line]) -> WarningReading:
    for index, line in enumerate(lines):
        match = _WARNING_RE.search(line.text)
        if not match:
            continue
        body = " ".join(part.text for part in lines[index:])
        header = match.group(0)
        return WarningReading(
            present=True,
            body=" ".join(body.split()),
            header_case="upper" if header.isupper() else "title",
            # No font weight from Tesseract, so None (not False) - False would invent a defect.
            header_bold=None,
        )
    return WarningReading(present=False, body=None, header_case=None, header_bold=None)


class OcrReader:
    def read(self, specimen: str, image_path: Path | None = None) -> LabelReading:
        path = image_path or Path("fixtures") / Path(specimen).name
        prepared = prepare(path)
        lines = _lines(prepared.image)

        brand, class_type = _brand_and_class(lines)
        producer, producer_confidence = _find(lines, _PRODUCER_RE)
        origin, origin_confidence = _find(lines, _ORIGIN_RE)
        net, net_confidence = _find(lines, _NET_RE)
        abv, abv_confidence = _find(lines, _ABV_RE)
        if abv is None:
            abv, abv_confidence = _find(lines, _ABV_LOOSE_RE)

        return LabelReading(
            brand=FieldReading(
                value=brand.text if brand else None,
                confidence=brand.confidence if brand else None,
            ),
            class_type=FieldReading(
                value=class_type.text if class_type else None,
                confidence=class_type.confidence if class_type else None,
            ),
            abv=FieldReading(value=abv, confidence=abv_confidence),
            net=FieldReading(value=net, confidence=net_confidence),
            producer=FieldReading(value=producer, confidence=producer_confidence),
            origin=FieldReading(value=origin, confidence=origin_confidence),
            warning=_warning(lines),
            quality=_quality(prepared),
        )
