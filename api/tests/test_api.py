"""Contract and behaviour tests for the documented API surface (PRD §5.1)."""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
    assert body["cursor"] is None


def test_create_record_requires_token() -> None:
    resp = client.post("/api/records", data={}, files={})
    assert resp.status_code == 401


def test_create_record_stub() -> None:
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
        },
        files={},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["app_brand"] == "Old Tom"
    assert body["verified"] is False
    assert body["result"] is None


def _create_record() -> str:
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
    record_id = _create_record()
    resp = client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert resp.status_code == 422


def test_verify_clean_fixture_matches() -> None:
    record_id = _seed_and_get("old-tom-pass.png")
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
    record_id = _seed_and_get("harbor-mist-nowarning.png")
    assert client.post(f"/api/records/{record_id}/verify", headers=ACCESS).json()["result"] == "fail"

    detail = client.get(f"/api/records/{record_id}").json()
    warning = next(f for f in detail["field_results"] if f["field_key"] == "warning")
    assert warning["verdict"] == "fail"
    assert "absent" in warning["note"]


def test_accepting_a_failed_record_requires_an_override() -> None:
    """PRD §5.1 / acceptance test 8."""
    record_id = _seed_and_get("harbor-mist-nowarning.png")
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
    record_id = _seed_and_get("old-tom-pass.png")
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
    record_id = _seed_and_get("old-tom-pass.png")
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
    record_id = _seed_and_get("old-tom-pass.png")
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
    record_id = _seed_and_get("old-tom-pass.png")
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
    b"old-tom-pass.png,Old Tom Distillery,Kentucky Straight Bourbon Whiskey,45%,"
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
            ("images", ("old-tom-pass.png", b"\x89PNG fake", "image/png")),
            ("images", ("nobody-claims-me.png", b"\x89PNG fake", "image/png")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["matched"] == 1
    assert body["summary"]["unused_images"] == ["nobody-claims-me.png"]
    assert body["blocks_commit"] is False
    assert body["rows"][0]["image"] == "old-tom-pass.png"


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
    assert resp.json() == {"imported": 1, "skipped": 0}


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

    record_id = _seed_and_get("old-tom-pass.png")
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
    record_id = _seed_and_get("old-tom-pass.png")
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
    assert named[0]["filename"] == "old-tom-pass.png"
    assert named[0]["title"] == "Clean match"


def test_specimen_prefill_returns_the_application_as_filed() -> None:
    resp = client.get("/api/specimens/old-tom-pass.png")
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
