"""Build the example store from api/fixtures/ (PRD §7).

The example set is what `POST /api/fixtures {mode: "reset"}` restores, and it
exists to be trained on: thirteen applications spanning every state a reviewer
meets - some still awaiting verification, clean matches, labels in review,
failures still open, one failure accepted over the engine's objection, and one
returned to the applicant.

Deviation from PRD §7/S12, deliberate: the store used to seed all 25 fixtures,
every one of them unverified. That shows exactly one state, so the inbox filters
all read zero and there is nothing to practise a decision on. The 25 are still
one click away as a batch on Check a batch, which is where a bulk run belongs.

The determinations are not hand-written. `FakeReader` replays what a perfect
reader would have seen on each specimen and the real rules engine adjudicates
it, so a seeded record carries the same field results the app would produce -
offline, and without a paid call.
"""

from __future__ import annotations

import csv
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import adjudicate
import db
from models import Application
from readers.fake import FakeReader

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

SEED_REVIEWER = "J. Park"

# filename -> what the reviewer has done with it so far. `None` means the record
# is filed but nobody has run verification yet; "open" means verified and
# waiting on a decision.
EXAMPLE_SET: dict[str, str | None] = {
    "quarry-house-units.jpg": None,
    "iron-gate-blur.jpg": None,
    "golden-hour-nonbold.jpg": None,
    "old-tom-pass.jpg": "accepted",
    "copper-kettle-pass.jpg": "open",
    "blue-heron-blur.jpg": "open",
    "stones-throw-caps.jpg": "open",
    "cedar-ridge-titlecase.jpg": "open",
    "maison-clair-angled.jpg": "open",
    "harbor-mist-nowarning.jpg": "open",
    "lark-hollow-reworded.jpg": "open",
    "saltmarsh-glare.jpg": "accepted",
    "vinos-del-sol-abv.jpg": "returned",
}

RETURN_REASON = "Label states 12.5% Alc./Vol.; the application declares 13.5%. Refile with artwork that matches."


def read_applications() -> list[dict[str, Any]]:
    with (FIXTURES_DIR / "applications.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def copy_fixture_images(only: set[str] | None = None) -> None:
    images_dir = db.data_dir() / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for row in read_applications():
        if only is not None and row["filename"] not in only:
            continue
        src = FIXTURES_DIR / row["filename"]
        if src.exists():
            shutil.copy2(src, images_dir / row["filename"])


def _application_from(app: dict[str, str]) -> Application:
    return Application(
        brand=app["brand_name"],
        class_type=app["class_type"],
        abv=app["alcohol_content"],
        net=app["net_contents"],
        producer=app["producer"] or None,
        origin=app["country_of_origin"] or None,
        warning=app["government_warning"].lower() == "true",
    )


def _verify(record_id: str, app: dict[str, str], filename: str) -> str:
    """Adjudicate one seeded record against its replayed reading."""
    reading = FakeReader().read(filename)
    results, verdict = adjudicate.adjudicate(record_id, _application_from(app), reading)
    db.upsert_field_results(record_id, [r.model_dump(exclude={"record_id"}) for r in results])
    db.update_record(
        record_id,
        verified=True,
        result=verdict,
        quality=reading.quality,
        engine="rules check (example set)",
        reader_provider="fake",
        # The reading these verdicts came from, kept like any other verified
        # record's (migrations/005). Without it, correcting a seeded record has
        # nothing to re-adjudicate against and it falls back to awaiting
        # verification - and the example set is the whole inbox on a fresh
        # store, so that was every record a reviewer could practise on.
        reading_json=reading.model_dump_json(),
    )
    return verdict


def seed_store() -> int:
    """Insert the example set. Returns the count."""
    applications = {row["filename"]: row for row in read_applications()}
    now = datetime.now(UTC)

    for index, (filename, state) in enumerate(EXAMPLE_SET.items()):
        app = applications[filename]
        record_id = db.next_record_id()
        # Staggered so the queue has an order to it rather than one timestamp.
        received = (now - timedelta(hours=len(EXAMPLE_SET) - index)).isoformat()
        db.insert_record(
            {
                "id": record_id,
                "received": received,
                "applicant": app["applicant"],
                "beverage": app["class_type"],
                "filename": filename,
                "specimen": filename,
                "quality": None,
                "app_brand": app["brand_name"],
                "app_class_type": app["class_type"],
                "app_alcohol_content": app["alcohol_content"],
                "app_net_contents": app["net_contents"],
                "app_producer": app["producer"] or None,
                "app_origin": app["country_of_origin"] or None,
                "app_warning_declared": app["government_warning"].lower() == "true",
                "verified": False,
                "result": None,
            }
        )
        if state is None:
            continue

        verdict = _verify(record_id, app, filename)
        if state == "open":
            continue

        # Decided records carry the same columns a reviewer's decision writes,
        # including the override flag a non-match acceptance requires (PRD §5.1).
        db.update_record(
            record_id,
            decision=state,
            override=state == "accepted" and verdict != "match",
            decided_by=SEED_REVIEWER,
            decided_at=received,
            note=RETURN_REASON if state == "returned" else None,
        )

    copy_fixture_images(set(EXAMPLE_SET))
    return len(EXAMPLE_SET)


def reset_store() -> int:
    """Snapshot the current store, wipe it, and reseed the example set."""
    db.snapshot(reason="reset")
    db.wipe()
    db.reset_images_dir()
    count = seed_store()
    db.append_audit(None, "reset", {"seeded": count})
    return count


def empty_store() -> None:
    """Snapshot the current store and leave it empty, so a reviewer starts from
    their own applications rather than someone else's examples."""
    db.snapshot(reason="empty")
    # wipe() drops the whole SQLite file, so staged batches and job progress
    # (the `documents` table) go with the records.
    db.wipe()
    db.reset_images_dir()
    db.append_audit(None, "emptied", {})


if __name__ == "__main__":
    db.init_db()
    print(f"seeded {seed_store()} records")
