"""Batch intake: filename pairing and staged-preview construction (PRD §5.5).

Applications are paired to specimens on the CSV `filename` column against
uploaded image basenames, in three passes. Ambiguity is always an error rather
than a guess - two images that normalise to the same stem block the commit
until a human resolves them.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Literal

Bucket = Literal["matched", "matched_fuzzy", "missing_image", "ambiguous"]

ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# The batch intake header (PRD §4.3) - the shorter, applicant-facing one. This
# is the single definition: the blank template served to applicants and the
# parser that accepts their file read the same list.
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

# The records mirror (csv_io.MIRROR_COLUMNS) names the same seven application
# fields differently, because it is the database row and the intake file is the
# applicant-facing form. A reviewer who exports the store, edits it, and uploads
# it as a batch is doing something obvious; refusing it over a column name is
# not. Extra mirror columns are ignored - only the required ones are checked.
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
    """Normalised comparison key: case-fold, drop extension, collapse
    separators to a single dash, strip a leading `./` (PRD §5.5 pass 2)."""
    name = name.strip().lstrip("./").rsplit("/", 1)[-1]
    base = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    return re.sub(r"[\s_-]+", "-", base).casefold()


def _intake_name(column: str | None) -> str:
    """An intake column name, whether the file was written by an applicant or
    exported from the store."""
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
        # The blank template is a valid file with nothing in it; staging it
        # silently produced an empty preview with no explanation.
        raise BatchCsvError("the file has a header but no application rows")
    return rows


def pair(rows: list[dict[str, str]], image_names: list[str]) -> tuple[list[Row], list[str]]:
    """Pair CSV rows to image basenames. Returns the staged rows and the
    images no row claimed."""
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
            # Pass 2 and 3 collapse to the same lookup - the stem already
            # ignores case, separators and the extension. One candidate is a
            # pairing; the fuzzy flag marks that the extension differed, which
            # the preview surfaces for visual confirmation before commit.
            staged_row.image = candidates[0]
            same_extension = candidates[0].casefold().endswith(
                base.casefold().rsplit(".", 1)[-1]
            )
            staged_row.bucket = "matched" if same_extension else "matched_fuzzy"
        elif len(candidates) > 1:
            staged_row.bucket = "ambiguous"
            staged_row.candidate_filenames = sorted(candidates)
            staged_row.errors.append(
                f"{len(candidates)} images normalise to the same name; "
                "rename or remove all but one before committing"
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

    Filename pairing is right for a curated CSV and a folder, but it has no
    answer for a typo: the reviewer can see that row 7 is that bottle even when
    the names disagree, and re-uploading the whole batch to fix one character
    is not a remedy.
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
        # Assigned by a human, so it is matched - not a fuzzy guess the
        # preview should ask them to confirm.
        row.bucket = "matched"


def unused_images(rows: list[Row], images: list[str]) -> list[str]:
    claimed = {r.image for r in rows if r.image}
    return sorted(set(images) - claimed)


def unresolved(rows: list[Row]) -> list[int]:
    """Row numbers still ambiguous, which no commit may quietly skip."""
    return [r.row for r in rows if r.bucket == "ambiguous"]


def blocks_commit(rows: list[Row]) -> bool:
    """Commit is blocked while any row is ambiguous. `missing_image` rows do
    not block: they file, and are editable but not verifiable (PRD §5.5)."""
    return any(row.bucket == "ambiguous" for row in rows)


def discard(rows: list[Row], images: list[str], name: str) -> None:
    """Drop an uploaded image from the batch and repair the rows that used it.

    Deleting the spare is the remedy an ambiguous row's own error message
    names, so a row left with one candidate pairs with it rather than staying
    blocked.
    """
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
