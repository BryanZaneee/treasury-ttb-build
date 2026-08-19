"""Build the 25-record example store from api/fixtures/ (PRD §7).

Seeded records are unverified (verified=False, result=None): the rules
engine (M2) and reader layer (M3) don't exist yet, so there is nothing to
run verification with. `reset_store()` is what M1 wires into
`POST /api/fixtures {mode: "reset"}`.
"""

from __future__ import annotations

import csv
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import db

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def read_applications() -> list[dict[str, Any]]:
    with (FIXTURES_DIR / "applications.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def copy_fixture_images() -> None:
    images_dir = db.data_dir() / "images"
    for row in read_applications():
        src = FIXTURES_DIR / row["filename"]
        if src.exists():
            shutil.copy2(src, images_dir / row["filename"])


def seed_store() -> int:
    """Insert one unverified record per fixture application. Returns the count."""
    applications = read_applications()
    received = datetime.now(UTC).isoformat()
    for app in applications:
        db.insert_record(
            {
                "id": db.next_record_id(),
                "received": received,
                "applicant": app["applicant"],
                "beverage": app["class_type"],
                "filename": app["filename"],
                "specimen": app["filename"],
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
    copy_fixture_images()
    return len(applications)


def reset_store() -> int:
    """Snapshot the current store, wipe it, and reseed the fixture set."""
    db.snapshot(reason="reset")
    db.wipe()
    db.reset_images_dir()
    count = seed_store()
    db.append_audit(None, "reset", {"seeded": count})
    return count


if __name__ == "__main__":
    db.init_db()
    print(f"seeded {seed_store()} records")
