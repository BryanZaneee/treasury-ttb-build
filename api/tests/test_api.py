"""Contract and behaviour tests for the documented API surface (PRD §5.1)."""

import json
import sqlite3
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import csv_io
import db
import seed
from config import settings
from main import app

client = TestClient(app)
ACCESS = {"Authorization": f"Bearer {settings.access_token}"}
ADMIN = {"Authorization": f"Bearer {settings.admin_token}"}


def test_health() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "provider" in body and "model" in body


def test_list_records_empty() -> None:
    resp = client.get("/api/records")
    assert resp.status_code == 200
    body = resp.json()
    assert body["records"] == []
    assert body["counts"]["attention"] == 0


def test_create_record_requires_token() -> None:
    resp = client.post("/api/records", data={}, files={})
    assert resp.status_code == 401


def test_create_record_against_a_bundled_specimen() -> None:
    resp = client.post(
        "/api/records",
        headers=ACCESS,
        data={
            "applicant": "Acme Distilling",
            "beverage": "spirits",
            "application": (
                '{"brand": "Old Tom", "class_type": "Bourbon", "abv": "45%", '
                '"net": "750 mL"}'
            ),
            "specimen_key": "old-tom-pass.jpg",
        },
        files={},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["app_brand"] == "Old Tom"
    assert body["verified"] is False
    assert body["result"] is None


def _create_record(specimen: str = "old-tom-pass.jpg") -> str:
    resp = client.post(
        "/api/records",
        headers=ACCESS,
        data={
            "applicant": "Acme Distilling",
            "beverage": "spirits",
            "application": (
                '{"brand": "Old Tom", "class_type": "Bourbon", "abv": "45%", '
                '"net": "750 mL"}'
            ),
            "specimen_key": specimen,
        },
        files={},
    )
    return str(resp.json()["id"])


def test_get_record_not_found() -> None:
    resp = client.get("/api/records/does-not-exist")
    assert resp.status_code == 404


def test_get_record() -> None:
    record_id = _create_record()
    resp = client.get(f"/api/records/{record_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == record_id
    assert body["field_results"] == []


def test_patch_record_not_found() -> None:
    resp = client.patch("/api/records/does-not-exist", headers=ACCESS, json={})
    assert resp.status_code == 404


def test_patch_record_noop() -> None:
    record_id = _create_record()
    resp = client.patch(f"/api/records/{record_id}", headers=ACCESS, json={})
    assert resp.status_code == 200
    assert resp.json()["id"] == record_id


def test_verify_record_not_found() -> None:
    resp = client.post("/api/records/does-not-exist/verify", headers=ACCESS)
    assert resp.status_code == 404


def _seed_and_get(filename: str) -> str:
    """Seed the fixture store and return the record id for one specimen."""
    seed.seed_store()
    rows = client.get("/api/records").json()["records"]
    return str(next(r["id"] for r in rows if r["filename"] == filename))


def test_verify_unknown_specimen_is_rejected() -> None:
    record_id = _create_record(specimen="not-a-fixture.png")
    resp = client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert resp.status_code == 422


def test_verify_clean_fixture_matches() -> None:
    record_id = _seed_and_get("old-tom-pass.jpg")
    resp = client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "match"
    assert body["verified"] is True
    assert body["quality"] == "normal"
    assert body["engine"] == "deterministic rules engine (fake reader)"
    assert body["elapsed_ms"] is not None

    detail = client.get(f"/api/records/{record_id}").json()
    assert {f["field_key"] for f in detail["field_results"]} == {
        "brand", "classType", "abv", "net", "producer", "warning",
    }
    assert all(f["verdict"] == "match" for f in detail["field_results"])


def test_verify_defect_fixture_fails_with_a_note() -> None:
    record_id = _seed_and_get("harbor-mist-nowarning.jpg")
    assert client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()["result"] == "fail"

    detail = client.get(f"/api/records/{record_id}").json()
    warning = next(f for f in detail["field_results"] if f["field_key"] == "warning")
    assert warning["verdict"] == "fail"
    assert "absent" in warning["note"]


def test_accepting_a_failed_record_requires_an_override() -> None:
    """PRD §5.1 / acceptance test 8."""
    record_id = _seed_and_get("harbor-mist-nowarning.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)

    refused = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "accepted", "reviewer_name": "R. Mills"},
    )
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["error"] == "override_required"
    assert "warning" in detail["fields"]
    # Cancelling changes nothing.
    assert client.get(f"/api/records/{record_id}").json()["decision"] is None

    accepted = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "accepted", "override": True, "reviewer_name": "R. Mills"},
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["decision"] == "accepted"
    assert body["override"] is True
    assert body["decided_by"] == "R. Mills"
    assert body["decided_at"] is not None


def test_accepting_a_matching_record_needs_no_override() -> None:
    record_id = _seed_and_get("old-tom-pass.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    resp = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "accepted", "reviewer_name": "R. Mills"},
    )
    assert resp.status_code == 200
    assert resp.json()["override"] is False


def test_a_decided_record_is_not_reopenable() -> None:
    """PRD §12: the applicant files afresh."""
    record_id = _seed_and_get("old-tom-pass.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "returned", "reviewer_name": "R. Mills", "reason": "Warning missing"},
    )
    resp = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "accepted", "override": True},
    )
    assert resp.status_code == 409


def test_editing_the_application_invalidates_the_verdict() -> None:
    record_id = _seed_and_get("old-tom-pass.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert client.get(f"/api/records/{record_id}").json()["field_results"]

    resp = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={
            "application": {
                "brand": "Old Tom Distillery",
                "class_type": "Kentucky Straight Bourbon Whiskey",
                "abv": "40%",
                "net": "750 mL",
                "producer": "Old Tom Distillery, Bardstown, KY",
                "warning": True,
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is False
    assert body["result"] is None
    assert body["app_alcohol_content"] == "40%"
    assert client.get(f"/api/records/{record_id}").json()["field_results"] == []

    # Re-verifying now catches the mismatch the edit introduced.
    assert client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()["result"] == "fail"


def test_verification_appends_audit_rows_without_overwriting() -> None:
    """PRD §12 / acceptance test 18: re-verification appends, never overwrites."""
    record_id = _seed_and_get("old-tom-pass.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)

    conn = db.connect()
    try:
        events = [
            r["event"]
            for r in conn.execute(
                "SELECT event FROM audit WHERE record_id = ? ORDER BY seq", (record_id,)
            )
        ]
    finally:
        conn.close()
    assert events == ["filed", "verified", "verified"]


SAMPLE_CSV = (
    b"filename,brand_name,class_type,alcohol_content,net_contents,"
    b"producer,country_of_origin,government_warning,applicant\n"
    b"old-tom-pass.jpg,Old Tom Distillery,Kentucky Straight Bourbon Whiskey,45%,"
    b"750 mL,\"Old Tom Distillery, Bardstown, KY\",,true,Old Tom Distillery LLC\n"
)


def test_stage_batch_rejects_a_csv_missing_required_columns() -> None:
    resp = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files={"applications_csv": ("apps.csv", b"filename,brand_name\n", "text/csv")},
    )
    assert resp.status_code == 422
    assert "class_type" in resp.json()["detail"]


def test_stage_batch_pairs_an_image_and_reports_an_unused_one() -> None:
    resp = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files=[
            ("applications_csv", ("apps.csv", SAMPLE_CSV, "text/csv")),
            ("images", ("old-tom-pass.jpg", b"\x89PNG fake", "image/png")),
            ("images", ("nobody-claims-me.png", b"\x89PNG fake", "image/png")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["matched"] == 1
    assert body["summary"]["unused_images"] == ["nobody-claims-me.png"]
    assert body["blocks_commit"] is False
    assert body["rows"][0]["image"] == "old-tom-pass.jpg"


def test_stage_batch_row_with_no_image_files_but_does_not_block() -> None:
    """PRD §5.5 / acceptance test 9: missing_image rows file, they do not block."""
    resp = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files={"applications_csv": ("apps.csv", SAMPLE_CSV, "text/csv")},
    )
    body = resp.json()
    assert body["summary"]["missing_image"] == 1
    assert body["blocks_commit"] is False


def test_sample_batch_stages_all_25_with_images_resolved() -> None:
    """S4: load the bundled sample batch in one click."""
    resp = client.post("/api/fixtures", headers=ACCESS, json={"mode": "stage"})
    assert resp.status_code == 200
    batch = resp.json()["batch"]
    assert len(batch["rows"]) == 25
    assert batch["summary"]["matched"] == 25
    assert batch["blocks_commit"] is False


def _await_job(job_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def test_committing_the_sample_batch_verifies_every_record() -> None:
    batch = client.post("/api/fixtures", headers=ACCESS, json={"mode": "stage"}).json()["batch"]
    resp = client.post(
        "/api/jobs",
        headers=ACCESS,
        json={"scope": "batch", "batch_id": batch["batch_id"], "verify_now": True},
    )
    assert resp.status_code == 200
    job = _await_job(resp.json()["id"])
    assert job["state"] == "done"
    assert job["committed"] == 25
    assert job["failed"] == 0
    # The fixture set is 6 match, 5 review, 14 fail.
    assert job["verdicts"] == {"match": 6, "review": 5, "fail": 14}


def test_job_events_stream_closes_when_the_job_finishes() -> None:
    job_id = client.post("/api/jobs", headers=ACCESS, json={"scope": "pending"}).json()["id"]
    _await_job(job_id)
    resp = client.get(f"/api/jobs/{job_id}/events")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: done" in resp.text


def test_fixtures_stub() -> None:
    resp = client.post("/api/fixtures", headers=ACCESS, json={"mode": "stage"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "stage"


def test_store_import_requires_admin_token() -> None:
    resp = client.post(
        "/api/store/import",
        headers=ACCESS,
        files={"csv_file": ("records.csv", b"id\n", "text/csv")},
    )
    assert resp.status_code == 401


def test_store_import_rejects_missing_required_column() -> None:
    resp = client.post(
        "/api/store/import",
        headers=ADMIN,
        files={"csv_file": ("records.csv", b"id\n", "text/csv")},
    )
    assert resp.status_code == 422


def test_store_import() -> None:
    csv_bytes = b"id,app_brand,app_class_type,app_alcohol_content,app_net_contents\nrec-1,Old Tom,Bourbon,45%,750 mL\n"
    resp = client.post(
        "/api/store/import",
        headers=ADMIN,
        files={"csv_file": ("records.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"imported": 1, "skipped": 0, "errors": []}


def _export() -> bytes:
    resp = client.get("/api/export/records.csv")
    assert resp.status_code == 200
    return resp.content


def _import(data: bytes, mode: str = "merge") -> dict[str, Any]:
    resp = client.post(
        "/api/store/import",
        headers=ADMIN,
        data={"mode": mode},
        files={"csv_file": ("records.csv", data, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def test_export_import_export_is_byte_identical() -> None:
    """Acceptance test 10, against a store that has actually been verified.

    The old import compared booleans to the string "True" while the exporter
    writes SQLite's 1/0, so every verified record came back unverified, and
    field results were parsed and then dropped entirely.
    """
    seed.seed_store()
    job = client.post("/api/jobs", headers=ACCESS, json={"scope": "pending"}).json()
    _await_job(job["id"])

    before = _export()
    assert b"brand:match" in before, "the export carries packed field results"

    summary = _import(before, mode="replace")
    assert summary["imported"] == 25
    assert summary["skipped"] == 0

    assert _export() == before


def test_import_restores_verdicts_and_field_results() -> None:
    seed.seed_store()
    record_id = _seed_and_get("old-tom-pass.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    exported = _export()

    client.post("/api/fixtures", headers=ADMIN, json={"mode": "reset"})
    _import(exported, mode="replace")

    detail = client.get(f"/api/records/{record_id}").json()
    assert detail["verified"] is True, "booleans survive the round trip"
    assert detail["result"] == "match"
    assert {f["field_key"] for f in detail["field_results"]} == {
        "brand", "classType", "abv", "net", "producer", "warning",
    }
    assert all(f["verdict"] == "match" for f in detail["field_results"])

    # The evidence, not just the verdict. A store restored from a mirror that
    # dropped these showed every field as "Not recorded" in the determination
    # view - a verdict with no observed values behind it.
    by_key = {f["field_key"]: f for f in detail["field_results"]}
    assert by_key["brand"]["app_value"] == detail["app_brand"]
    assert by_key["brand"]["label_value"] == detail["app_brand"], "a match reads the same"
    assert by_key["warning"]["app_value"] == "declared"
    assert by_key["warning"]["label_value"], "the warning body survives the round trip"


def test_packed_field_values_survive_pipes_and_colons() -> None:
    """The sibling `field_notes` column packs as `key:note|key:note`, which a
    value containing either separator would corrupt. Observed label values
    contain both routinely, which is why this column is JSON."""
    rows = [
        {"field_key": "producer", "app_value": "Bottled by: A|B Co", "label_value": None},
        {"field_key": "brand", "app_value": None, "label_value": "X|Y: Z"},
    ]
    restored = csv_io.unpack_field_results(
        "COLA-1", "producer:match|brand:fail", "", csv_io.pack_field_values(rows)
    )
    by_key = {r["field_key"]: r for r in restored}
    assert by_key["producer"]["app_value"] == "Bottled by: A|B Co"
    assert by_key["brand"]["label_value"] == "X|Y: Z"


def test_importing_the_same_file_twice_is_idempotent() -> None:
    """Re-importing an export used to raise a primary-key violation on the
    first row and escape as a 500, after committing some rows."""
    seed.seed_store()
    exported = _export()
    first = _import(exported)
    second = _import(exported)
    assert first == second
    assert len(client.get("/api/records").json()["records"]) == 25


def test_import_reports_rows_it_could_not_take() -> None:
    csv_bytes = (
        b"id,app_brand\n"
        b"rec-1,Old Tom\n"
        b",No Id Here\n"
    )
    summary = _import(csv_bytes)
    assert summary["imported"] == 1
    assert summary["skipped"] == 1
    assert "row 2" in summary["errors"][0]


def test_replace_mode_leaves_only_what_the_file_contained() -> None:
    seed.seed_store()
    csv_bytes = b"id,app_brand,app_class_type,app_alcohol_content,app_net_contents\nrec-1,Old Tom,Bourbon,45%,750 mL\n"
    _import(csv_bytes, mode="replace")
    records = client.get("/api/records").json()["records"]
    assert [r["id"] for r in records] == ["rec-1"]


def test_fixtures_reset_requires_admin() -> None:
    resp = client.post("/api/fixtures", headers=ACCESS, json={"mode": "reset"})
    assert resp.status_code == 401


def test_fixtures_reset() -> None:
    resp = client.post("/api/fixtures", headers=ADMIN, json={"mode": "reset"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "reset"
    assert body["reset_count"] == 25


def test_verification_falls_back_to_ocr_when_the_vision_reader_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD §3.2 / acceptance test 11: the service never blocks on a reader.

    The record must also record the reader that actually ran, not the one that
    was configured - that is what lets the UI warn the reviewer that this
    determination was read less reliably.
    """
    import config
    import readers
    from routers import records as records_router

    record_id = _seed_and_get("old-tom-pass.jpg")
    monkeypatch.setattr(config.settings, "reader_provider", "openai")

    real = readers.get_reader

    def flaky(provider: str | None = None, *args: object, **kwargs: object) -> object:
        if provider == "openai":
            raise RuntimeError("connection refused")
        return real("fake")

    monkeypatch.setattr(records_router, "get_reader", flaky)

    resp = client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] is not None, "a verdict is still returned"
    assert body["reader_provider"] == "ocr", "records the reader that actually ran"
    assert body["reader_model"] is None
    assert "unavailable" in body["engine"] and "OCR" in body["engine"]


def test_verification_records_the_configured_reader_when_it_works() -> None:
    record_id = _seed_and_get("old-tom-pass.jpg")
    body = client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()
    assert body["reader_provider"] == "fake"
    assert "fake reader" in body["engine"]


def test_specimen_catalogue_lists_the_named_samples() -> None:
    """PRD §7: the bundled samples the single-label form is filled from."""
    resp = client.get("/api/specimens")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 25
    named = [s for s in body if s["title"]]
    assert len(named) == 12, "the named samples lead the catalogue"
    assert named[0]["filename"] == "old-tom-pass.jpg"
    assert named[0]["title"] == "Clean match"


def test_specimen_prefill_returns_the_application_as_filed() -> None:
    resp = client.get("/api/specimens/old-tom-pass.jpg")
    assert resp.status_code == 200
    body = resp.json()
    assert body["applicant"] == "Old Tom Distillery LLC"
    assert body["app"]["brand"] == "Old Tom Distillery"


def test_specimen_prefill_rejects_an_unknown_filename() -> None:
    assert client.get("/api/specimens/not-a-fixture.png").status_code == 404


def test_bulk_verify_runs_exactly_the_selected_records() -> None:
    seed.seed_store()
    ids = [r["id"] for r in client.get("/api/records").json()["records"][:3]]
    resp = client.post(
        "/api/jobs", headers=ACCESS, json={"scope": "ids", "record_ids": ids}
    )
    assert resp.status_code == 200
    job = _await_job(resp.json()["id"])
    assert job["state"] == "done"
    assert job["completed"] == 3
    assert job["failed"] == 0

    verified = [r for r in client.get("/api/records").json()["records"] if r["verified"]]
    assert {r["id"] for r in verified} == set(ids), "nothing outside the selection ran"


def test_bulk_verify_survives_an_id_that_does_not_exist() -> None:
    """One bad record must not abort the rest of the job (PRD §5.1, S7)."""
    seed.seed_store()
    good = [r["id"] for r in client.get("/api/records").json()["records"][:2]]
    resp = client.post(
        "/api/jobs",
        headers=ACCESS,
        json={"scope": "ids", "record_ids": [*good, "COLA-2026-9999"]},
    )
    job = _await_job(resp.json()["id"])
    assert job["state"] == "done"
    assert job["failed"] == 1
    assert sum(job["verdicts"].values()) == 2


def test_bulk_verify_requires_ids() -> None:
    resp = client.post("/api/jobs", headers=ACCESS, json={"scope": "ids", "record_ids": []})
    job = _await_job(resp.json()["id"])
    assert job["state"] == "error"
    assert "record_ids" in (job["error"] or "")


def _png(colour: str = "red") -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 60), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(name: str, data: bytes, applicant: str = "Acme Distilling") -> object:
    return client.post(
        "/api/records",
        headers=ACCESS,
        data={
            "applicant": applicant,
            "beverage": "spirits",
            "application": (
                '{"brand": "Old Tom", "class_type": "Bourbon", "abv": "45%", "net": "750 mL"}'
            ),
        },
        files={"image": (name, data, "image/png")},
    )


def test_uploading_a_label_stores_it_content_addressed() -> None:
    resp = _upload("my label.png", _png())
    assert resp.status_code == 201  # type: ignore[attr-defined]
    body = resp.json()  # type: ignore[attr-defined]
    assert body["filename"] == "my label.png", "the original name is kept for display"
    assert body["specimen"].endswith(".png")
    assert len(body["specimen"]) == 68, "sha256 hex plus extension"
    assert (db.data_dir() / "images" / body["specimen"]).exists()


def test_two_uploads_sharing_a_name_do_not_overwrite_each_other() -> None:
    first = _upload("label.png", _png("red")).json()  # type: ignore[attr-defined]
    second = _upload("label.png", _png("blue")).json()  # type: ignore[attr-defined]
    assert first["specimen"] != second["specimen"]
    assert (db.data_dir() / "images" / first["specimen"]).exists()
    assert (db.data_dir() / "images" / second["specimen"]).exists()


def test_an_upload_cannot_overwrite_a_bundled_fixture() -> None:
    seed.seed_store()
    original = (db.data_dir() / "images" / "old-tom-pass.jpg").read_bytes()
    _upload("old-tom-pass.jpg", _png("blue"))
    assert (db.data_dir() / "images" / "old-tom-pass.jpg").read_bytes() == original


def test_a_non_image_upload_is_refused() -> None:
    resp = _upload("label.png", b"not an image at all")
    assert resp.status_code == 422  # type: ignore[attr-defined]
    assert "PNG" in resp.json()["detail"]  # type: ignore[attr-defined]


def test_sending_both_an_image_and_a_specimen_key_is_refused() -> None:
    """They resolve to different specimens, and the handler used to silently
    prefer the sample while still writing the upload to disk."""
    resp = client.post(
        "/api/records",
        headers=ACCESS,
        data={
            "applicant": "Acme",
            "beverage": "spirits",
            "application": (
                '{"brand": "Old Tom", "class_type": "Bourbon", "abv": "45%", "net": "750 mL"}'
            ),
            "specimen_key": "old-tom-pass.jpg",
        },
        files={"image": ("label.png", _png(), "image/png")},
    )
    assert resp.status_code == 422
    assert "not both" in resp.json()["detail"]


def test_a_record_needs_a_specimen() -> None:
    resp = client.post(
        "/api/records",
        headers=ACCESS,
        data={
            "applicant": "Acme",
            "beverage": "spirits",
            "application": (
                '{"brand": "Old Tom", "class_type": "Bourbon", "abv": "45%", "net": "750 mL"}'
            ),
        },
        files={},
    )
    assert resp.status_code == 422


def test_an_uploaded_label_is_what_verify_resolves() -> None:
    """The record must point at the uploaded bytes, not at a fixture.

    read_specimen falls back to `fixtures/<specimen>` when the stored path is
    missing, so a specimen key that could collide with a fixture name would let
    an upload be verified against somebody else's label.
    """
    from pathlib import Path

    body = _upload("old-tom-pass.jpg", _png("blue")).json()  # type: ignore[attr-defined]
    stored = db.data_dir() / "images" / body["specimen"]
    assert stored.exists(), "verify resolves this path first"
    assert not (Path("fixtures") / body["specimen"]).exists(), "and cannot fall back to a fixture"
    assert body["specimen"] != "old-tom-pass.jpg"


def test_assigning_an_image_over_the_api_unblocks_a_stuck_batch() -> None:
    csv_bytes = (
        b"filename,brand_name,class_type,alcohol_content,net_contents,applicant\n"
        b"old-tom.png,Old Tom,Bourbon,45%,750 mL,Acme\n"
    )
    staged = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files=[
            ("applications_csv", ("apps.csv", csv_bytes, "text/csv")),
            ("images", ("totally-different-name.png", _png(), "image/png")),
        ],
    ).json()
    assert staged["summary"]["missing_image"] == 1
    assert staged["summary"]["unused_images"] == ["totally-different-name.png"]

    resp = client.post(
        f"/api/batches/{staged['batch_id']}/rows/1/image",
        headers=ACCESS,
        json={"image": "totally-different-name.png"},
    )
    assert resp.status_code == 200
    fixed = resp.json()
    assert fixed["summary"]["matched"] == 1
    assert fixed["summary"]["missing_image"] == 0
    assert fixed["summary"]["unused_images"] == []
    assert fixed["rows"][0]["image"] == "totally-different-name.png"


def test_committing_an_unresolved_batch_is_refused() -> None:
    """It used to skip ambiguous rows silently and file the rest."""
    csv_bytes = (
        b"filename,brand_name,class_type,alcohol_content,net_contents,applicant\n"
        b"old-tom.png,Old Tom,Bourbon,45%,750 mL,Acme\n"
        b"clean.png,Clean,Bourbon,45%,750 mL,Acme\n"
    )
    staged = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files=[
            ("applications_csv", ("apps.csv", csv_bytes, "text/csv")),
            ("images", ("Old_Tom.jpg", _png("red"), "image/png")),
            ("images", ("old-tom.jpeg", _png("blue"), "image/png")),
            ("images", ("clean.png", _png("green"), "image/png")),
        ],
    ).json()
    assert staged["blocks_commit"] is True

    job_id = client.post(
        "/api/jobs",
        headers=ACCESS,
        json={"scope": "batch", "batch_id": staged["batch_id"]},
    ).json()["id"]
    job = _await_job(job_id)
    assert job["state"] == "error"
    assert "ambiguous" in (job["error"] or "")
    assert job["committed"] == 0, "nothing files while a row is unresolved"

    client.post(
        f"/api/batches/{staged['batch_id']}/rows/1/image",
        headers=ACCESS,
        json={"image": "Old_Tom.jpg"},
    )
    job_id = client.post(
        "/api/jobs",
        headers=ACCESS,
        json={"scope": "batch", "batch_id": staged["batch_id"], "verify_now": False},
    ).json()["id"]
    job = _await_job(job_id)
    assert job["state"] == "done"
    assert job["committed"] == 2


def test_extraction_is_cached_and_keyed_on_the_reader_config() -> None:
    """PRD §5.2 / acceptance test 15: switching model must not serve the
    reading the previous model produced."""
    record_id = _seed_and_get("old-tom-pass.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)

    conn = sqlite3.connect(db.db_path())
    keys = [r[0] for r in conn.execute("SELECT key FROM extraction_cache")]
    conn.close()
    assert len(keys) == 1, "the reading should have been cached once"
    assert settings.reader_model in keys[0]

    # Same record, different model - a second entry, not a stale hit.
    original = settings.reader_model
    settings.reader_model = "some-other-model"
    try:
        client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    finally:
        settings.reader_model = original

    conn = sqlite3.connect(db.db_path())
    after = [r[0] for r in conn.execute("SELECT key FROM extraction_cache")]
    conn.close()
    assert len(after) == 2, "a model change must produce a distinct cache entry"


def test_a_fallback_reading_is_never_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A degraded reading must not become sticky for the configured reader.

    Cached under the openai key, one unreachable-provider blip would keep
    serving the OCR answer long after the provider came back.
    """
    import config
    import readers

    record_id = _seed_and_get("old-tom-pass.jpg")
    monkeypatch.setattr(config.settings, "reader_provider", "openai")

    real = readers.get_reader

    def flaky(provider: str | None = None, *args: object, **kwargs: object) -> object:
        if provider == "openai":
            raise RuntimeError("connection refused")
        return real("fake")

    monkeypatch.setattr(readers, "get_reader", flaky)
    from routers import records as records_router

    monkeypatch.setattr(records_router, "get_reader", flaky)

    resp = client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert resp.status_code == 200
    assert resp.json()["reader_provider"] == "ocr"

    conn = sqlite3.connect(db.db_path())
    cached = conn.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0]
    conn.close()
    assert cached == 0, "the OCR fallback reading must not be cached under openai"


def test_a_clean_match_auto_closes_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRD §5.3 / §8: off by default, and an operator has to turn it on."""
    record_id = _seed_and_get("old-tom-pass.jpg")
    assert settings.auto_approve_matches is False, "the default must stay off"

    body = client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()
    assert body["result"] == "match"
    assert body["decision"] is None, "a match must not close itself while the toggle is off"

    db.wipe()
    seed.seed_store()
    record_id = _seed_and_get("old-tom-pass.jpg")
    monkeypatch.setattr(settings, "auto_approve_matches", True)
    monkeypatch.setattr(settings, "qa_sample_rate", 0.0)  # never sample, so this is deterministic
    body = client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()
    assert body["decision"] == "accepted"
    assert body["decided_by"] == "Automatic"

    conn = sqlite3.connect(db.db_path())
    events = [r[0] for r in conn.execute("SELECT event FROM audit WHERE record_id = ?", (record_id,))]
    conn.close()
    assert "auto_closed" in events, "§8 requires an audit row for every auto-close"


def test_a_failing_record_never_auto_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    record_id = _seed_and_get("harbor-mist-nowarning.jpg")
    monkeypatch.setattr(settings, "auto_approve_matches", True)
    monkeypatch.setattr(settings, "qa_sample_rate", 0.0)
    body = client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()
    assert body["result"] == "fail"
    assert body["decision"] is None


def test_an_ocr_only_reading_never_auto_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single degraded reader is not grounds for an unattended approval."""
    import config
    import readers
    from routers import records as records_router

    record_id = _seed_and_get("old-tom-pass.jpg")
    monkeypatch.setattr(config.settings, "reader_provider", "openai")
    monkeypatch.setattr(settings, "auto_approve_matches", True)
    monkeypatch.setattr(settings, "qa_sample_rate", 0.0)

    real = readers.get_reader

    def flaky(provider: str | None = None, *args: object, **kwargs: object) -> object:
        if provider == "openai":
            raise RuntimeError("connection refused")
        return real("fake")

    monkeypatch.setattr(readers, "get_reader", flaky)
    monkeypatch.setattr(records_router, "get_reader", flaky)

    body = client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()
    assert body["reader_provider"] == "ocr"
    assert body["result"] == "match", "the fake reading still matches"
    assert body["decision"] is None, "but an OCR-only reading must not close itself"


def test_filing_with_verify_now_adjudicates_without_a_second_request() -> None:
    """A reviewer who files and immediately moves on must still get a verdict.

    Filing and verifying used to be two round trips from the browser, so
    navigating away in between left a record nobody would ever verify.
    """
    seed.copy_fixture_images()
    resp = client.post(
        "/api/records",
        headers=ACCESS,
        data={
            "applicant": "Acme Distilling",
            "beverage": "spirits",
            "application": (
                '{"brand": "Old Tom Distillery", '
                '"class_type": "Kentucky Straight Bourbon Whiskey", '
                '"abv": "45%", "net": "750 mL", '
                '"producer": "Old Tom Distillery, Bardstown, KY", "warning": true}'
            ),
            "specimen_key": "old-tom-pass.jpg",
            "verify_now": "true",
        },
        files={},
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]

    # No verify call is made here on purpose - that is the whole point.
    for _ in range(100):
        body = client.get(f"/api/records/{record_id}").json()
        if body["verified"]:
            break
        time.sleep(0.05)
    assert body["verified"] is True
    assert body["result"] == "match"


def test_filing_without_verify_now_calls_no_reader() -> None:
    """Deviation from PRD §5.2, deliberate: extraction costs money, so nothing
    is read until a reviewer asks for it."""
    seed.copy_fixture_images()
    record_id = _create_record()
    time.sleep(0.5)  # generous: a background read would have landed by now

    body = client.get(f"/api/records/{record_id}").json()
    assert body["verified"] is False
    assert body["result"] is None

    conn = sqlite3.connect(db.db_path())
    cached = conn.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0]
    conn.close()
    assert cached == 0, "filing alone must not populate the extraction cache"


def test_overriding_a_failure_must_be_attributed() -> None:
    """The audit row is the whole point of an override, so it needs a name."""
    record_id = _seed_and_get("harbor-mist-nowarning.jpg")
    client.post(f"/api/records/{record_id}/verify", headers=ACCESS)

    anonymous = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "accepted", "override": True},
    )
    assert anonymous.status_code == 422
    assert anonymous.json()["detail"]["error"] == "reviewer_name_required"
    assert client.get(f"/api/records/{record_id}").json()["decision"] is None

    named = client.patch(
        f"/api/records/{record_id}",
        headers=ACCESS,
        json={"decision": "accepted", "override": True, "reviewer_name": "R. Mills"},
    )
    assert named.status_code == 200, "a named reviewer may still accept a failed record"
    assert named.json()["decision"] == "accepted"
    assert named.json()["result"] == "fail", "the verdict of record is not rewritten"

    conn = sqlite3.connect(db.db_path())
    payload = conn.execute(
        "SELECT payload_json FROM audit WHERE record_id = ? AND event = 'decision'", (record_id,)
    ).fetchone()[0]
    conn.close()
    entry = json.loads(payload)
    assert entry["override"] is True
    assert entry["decided_by"] == "R. Mills"
    assert entry["result"] == "fail"


def test_the_engine_string_names_a_spend_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance test 17: on a cap breach the record must say so.

    "openai unavailable" reads as an outage worth retrying. A cap is not - it
    holds until UTC midnight, and the reviewer needs to be able to tell.
    """
    import config
    import readers
    from readers.vision import SpendCapReached
    from routers import records as records_router

    record_id = _seed_and_get("old-tom-pass.jpg")
    monkeypatch.setattr(config.settings, "reader_provider", "openai")

    real = readers.get_reader

    class Capped:
        name = "openai"

        def read(self, specimen: str, image_path: Any = None) -> Any:
            raise SpendCapReached("daily paid-call cap of 300 reached")

    def capped(provider: str | None = None, *args: object, **kwargs: object) -> object:
        return Capped() if provider == "openai" else real("fake")

    monkeypatch.setattr(records_router, "get_reader", capped)

    body = client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()
    assert body["reader_provider"] == "ocr"
    assert "cap" in body["engine"], f"engine string must name the cap: {body['engine']}"
    assert "unavailable" not in body["engine"], "a cap is not an outage"


def test_upload_is_rate_limited_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRD §8. Verification costs money per call, so nothing should be able to
    drive it in a loop unthrottled."""
    import main

    monkeypatch.setattr(main, "_LIMIT_PER_MINUTE", 3)
    main._hits.clear()

    statuses = [
        client.post(
            "/api/records",
            headers=ACCESS,
            data={
                "applicant": "Acme",
                "beverage": "spirits",
                "application": (
                    '{"brand": "Old Tom", "class_type": "Bourbon", '
                    '"abv": "45%", "net": "750 mL"}'
                ),
                "specimen_key": "old-tom-pass.jpg",
            },
            files={},
        ).status_code
        for _ in range(5)
    ]
    assert 429 in statuses, f"expected throttling, got {statuses}"
    assert statuses.count(429) == 2, f"first three should pass: {statuses}"
    main._hits.clear()


def test_reads_are_never_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the routes that cost money are limited; a reviewer working the
    inbox quickly must never be throttled."""
    import main

    monkeypatch.setattr(main, "_LIMIT_PER_MINUTE", 2)
    main._hits.clear()
    assert all(client.get("/api/records").status_code == 200 for _ in range(6))
    main._hits.clear()


def test_uploading_a_specimen_for_one_row_pairs_it() -> None:
    """The reviewer has the missing file; re-uploading the batch is not a remedy."""
    csv_bytes = (
        b"filename,brand_name,class_type,alcohol_content,net_contents,applicant\n"
        b"old-tom.png,Old Tom,Bourbon,45%,750 mL,Acme\n"
    )
    staged = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files={"applications_csv": ("apps.csv", csv_bytes, "text/csv")},
    ).json()
    assert staged["summary"]["missing_image"] == 1

    resp = client.post(
        f"/api/batches/{staged['batch_id']}/rows/1/upload",
        headers=ACCESS,
        files={"image": ("old-tom.png", _png(), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["rows"][0]["image"] == "old-tom.png"
    assert (db.data_dir() / "images" / "old-tom.png").exists()


def test_discarding_an_unwanted_image_removes_it_from_the_batch() -> None:
    csv_bytes = (
        b"filename,brand_name,class_type,alcohol_content,net_contents,applicant\n"
        b"old-tom.png,Old Tom,Bourbon,45%,750 mL,Acme\n"
    )
    staged = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files=[
            ("applications_csv", ("apps.csv", csv_bytes, "text/csv")),
            ("images", ("old-tom.png", _png(), "image/png")),
            ("images", ("stray.png", _png("red"), "image/png")),
        ],
    ).json()
    assert staged["summary"]["unused_images"] == ["stray.png"]

    resp = client.delete(f"/api/batches/{staged['batch_id']}/images/stray.png", headers=ACCESS)
    assert resp.status_code == 200
    assert resp.json()["summary"]["unused_images"] == []

    gone = client.delete(f"/api/batches/{staged['batch_id']}/images/stray.png", headers=ACCESS)
    assert gone.status_code == 404


TWO_ROW_CSV = (
    b"filename,brand_name,class_type,alcohol_content,net_contents,applicant\n"
    b"old-tom.png,Old Tom,Bourbon,45%,750 mL,Acme\n"
    b"harbor.png,Harbor Mist,Lager,5%,355 mL,Harbor\n"
)


def _two_row_batch() -> dict[str, Any]:
    body: dict[str, Any] = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files=[
            ("applications_csv", ("apps.csv", TWO_ROW_CSV, "text/csv")),
            ("images", ("old-tom.png", _png(), "image/png")),
            ("images", ("harbor.png", _png("red"), "image/png")),
        ],
    ).json()
    return body


def test_dropping_a_staged_row_removes_it_before_anything_is_filed() -> None:
    staged = _two_row_batch()
    resp = client.delete(f"/api/batches/{staged['batch_id']}/rows/1", headers=ACCESS)
    assert resp.status_code == 200
    assert [r["row"] for r in resp.json()["rows"]] == [2]
    # Its image is nobody's now, so another row can still claim it.
    assert resp.json()["summary"]["unused_images"] == ["old-tom.png"]

    gone = client.delete(f"/api/batches/{staged['batch_id']}/rows/1", headers=ACCESS)
    assert gone.status_code == 404


def test_committing_a_selection_files_only_those_rows_and_leaves_the_rest() -> None:
    staged = _two_row_batch()
    resp = client.post(
        "/api/jobs",
        headers=ACCESS,
        json={
            "scope": "batch",
            "batch_id": staged["batch_id"],
            "rows": [2],
            "verify_now": False,
        },
    )
    job = _await_job(resp.json()["id"])
    assert job["state"] == "done"
    assert job["committed"] == 1
    filed = client.get("/api/records", headers=ACCESS).json()["records"]
    assert [r["app_brand"] for r in filed] == ["Harbor Mist"]

    # Row 1 is still staged; filing the whole batch now does not re-file row 2.
    again = client.post(
        "/api/jobs",
        headers=ACCESS,
        json={
            "scope": "batch",
            "batch_id": staged["batch_id"],
            "rows": [1, 2],
            "verify_now": False,
        },
    )
    assert _await_job(again.json()["id"])["committed"] == 1
    assert len(client.get("/api/records", headers=ACCESS).json()["records"]) == 2
