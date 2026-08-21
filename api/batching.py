"""Batch intake: filename pairing and staged-preview construction (PRD §5.5).

Applications pair to specimens on the CSV `filename` column against uploaded
basenames. Ambiguity is an error, never a guess: two images normalising to one
stem block the commit until a human resolves them.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Literal

Bucket = Literal["matched", "matched_fuzzy", "missing_image", "ambiguous"]

# The applicant-facing intake header (PRD §4.3), defined once: the blank template
# and the parser that accepts it read the same list.
INTAKE_COLUMNS = (
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "producer",
    "country_of_origin",
    "government_warning",
    "applicant",
)
REQUIRED_COLUMNS = INTAKE_COLUMNS[:5]

# The mirror names the same seven fields differently. Refusing a file this
# service wrote, over a column name, is not a defensible error.
_MIRROR_ALIASES = {
    "app_brand": "brand_name",
    "app_class_type": "class_type",
    "app_alcohol_content": "alcohol_content",
    "app_net_contents": "net_contents",
    "app_producer": "producer",
    "app_origin": "country_of_origin",
    "app_warning_declared": "government_warning",
}


class BatchCsvError(ValueError):
    """The uploaded CSV cannot be staged at all."""


@dataclass
class Row:
    row: int
    filename: str
    applicant: str
    brand: str
    bucket: Bucket
    image: str | None = None
    candidate_filenames: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)


def stem(name: str) -> str:
    """Case-fold, drop extension, collapse separators, strip `./` (PRD §5.5)."""
    name = name.strip().lstrip("./").rsplit("/", 1)[-1]
    base = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    return re.sub(r"[\s_-]+", "-", base).casefold()


def _intake_name(column: str | None) -> str:
    """An intake column name, from an applicant's file or from an export."""
    name = (column or "").strip().casefold()
    return _MIRROR_ALIASES.get(name, name)


def parse_csv(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise BatchCsvError("the file is empty")
    header = {_intake_name(f) for f in reader.fieldnames}
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise BatchCsvError(f"missing required column(s): {', '.join(missing)}")
    rows = [{_intake_name(k): (v or "").strip() for k, v in row.items()} for row in reader]
    if not rows:
        # The blank template is valid and empty; staging it silently produced a
        # preview with no explanation.
        raise BatchCsvError("the file has a header but no application rows")
    return rows


def pair(rows: list[dict[str, str]], image_names: list[str]) -> tuple[list[Row], list[str]]:
    """Pair CSV rows to image basenames; returns the rows and the unclaimed."""
    exact = {name.rsplit("/", 1)[-1]: name for name in image_names}

    by_stem: dict[str, list[str]] = {}
    for name in image_names:
        by_stem.setdefault(stem(name), []).append(name)

    staged: list[Row] = []
    claimed: set[str] = set()

    for index, values in enumerate(rows, start=1):
        filename = values.get("filename", "")
        staged_row = Row(
            row=index,
            filename=filename,
            applicant=values.get("applicant", ""),
            brand=values.get("brand_name", ""),
            bucket="missing_image",
            values=values,
        )
        if not filename:
            staged_row.errors.append("no filename given")
            staged.append(staged_row)
            continue

        base = filename.rsplit("/", 1)[-1]
        candidates = by_stem.get(stem(filename), [])

        if base in exact:
            # Pass 1: exact basename.
            staged_row.bucket = "matched"
            staged_row.image = exact[base]
        elif len(candidates) == 1:
            # The stem already ignores case, separators and extension, so one
            # candidate is a pairing; `fuzzy` marks that the extension differed
            # and the preview asks for confirmation before commit.
            staged_row.image = candidates[0]
            same_extension = candidates[0].casefold().endswith(
                base.casefold().rsplit(".", 1)[-1]
            )
            staged_row.bucket = "matched" if same_extension else "matched_fuzzy"
        elif len(candidates) > 1:
            staged_row.bucket = "ambiguous"
            staged_row.candidate_filenames = sorted(candidates)
            staged_row.errors.append(
                f"{len(candidates)} uploads match this name; "
                "pick the right one in the Image picker"
            )
        else:
            staged_row.errors.append("no image supplied for this row")

        if staged_row.image:
            claimed.add(staged_row.image)
        staged.append(staged_row)

    unused = sorted(set(image_names) - claimed)
    return staged, unused


def assign(rows: list[Row], images: list[str], row_no: int, image: str | None) -> None:
    """Pair a row with an image by hand, or clear the pairing.

    Filename pairing has no answer for a typo, and re-uploading the whole batch
    to fix one character is not a remedy.
    """
    row = next((r for r in rows if r.row == row_no), None)
    if row is None:
        raise KeyError(f"no row {row_no} in this batch")

    if image is not None:
        if image not in images:
            raise KeyError(f"{image!r} was not uploaded with this batch")
        claimed = {r.image for r in rows if r.image and r.row != row_no}
        if image in claimed:
            raise ValueError(f"{image!r} is already paired with another row")

    row.image = image
    row.candidate_filenames = []
    row.errors = []
    if image is None:
        row.bucket = "missing_image"
        row.errors.append("no image supplied for this row")
    else:
        # A human assigned it, so it is matched, not a guess to confirm.
        row.bucket = "matched"


def unused_images(rows: list[Row], images: list[str]) -> list[str]:
    claimed = {r.image for r in rows if r.image}
    return sorted(set(images) - claimed)


def unresolved(rows: list[Row]) -> list[int]:
    """Row numbers still ambiguous, which no commit may quietly skip."""
    return [r.row for r in rows if r.bucket == "ambiguous"]


def blocks_commit(rows: list[Row]) -> bool:
    """Ambiguity blocks the commit; a missing image does not (PRD §5.5)."""
    return any(row.bucket == "ambiguous" for row in rows)


def discard(rows: list[Row], images: list[str], name: str) -> None:
    """Drop an image and repair the rows that used it, resolving an ambiguity."""
    if name not in images:
        raise KeyError(f"{name!r} was not uploaded with this batch")
    images.remove(name)
    for row in list(rows):
        if row.image == name:
            assign(rows, images, row.row, None)
        elif name in row.candidate_filenames:
            left = [c for c in row.candidate_filenames if c != name]
            row.candidate_filenames = left
            if len(left) == 1:
                try:
                    assign(rows, images, row.row, left[0])
                except ValueError:
                    # Another row already claims it; leave this one ambiguous.
                    row.candidate_filenames = left
