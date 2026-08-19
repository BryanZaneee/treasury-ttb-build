"""Contract test: app boots, health responds, and each of the ten M0 stub
routes exists and returns the right shape for an empty/stub case."""

import os

os.environ.setdefault("ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")

from fastapi.testclient import TestClient

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


def test_get_record_stub() -> None:
    resp = client.get("/api/records/abc123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "abc123"
    assert body["field_results"] == []


def test_patch_record_stub() -> None:
    resp = client.patch("/api/records/abc123", headers=ACCESS, json={})
    assert resp.status_code == 200
    assert resp.json()["id"] == "abc123"


def test_verify_record_stub() -> None:
    resp = client.post("/api/records/abc123/verify", headers=ACCESS)
    assert resp.status_code == 200
    assert resp.json()["id"] == "abc123"


def test_stage_batch_stub() -> None:
    resp = client.post(
        "/api/batches/stage",
        headers=ACCESS,
        files={"applications_csv": ("apps.csv", b"filename,brand_name\n", "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == []
    assert body["summary"]["matched"] == 0


def test_create_job_stub() -> None:
    resp = client.post("/api/jobs", headers=ACCESS, json={"scope": "pending"})
    assert resp.status_code == 201
    assert "id" in resp.json()


def test_job_events_stub() -> None:
    resp = client.get("/api/jobs/stub/events")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


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


def test_store_import_stub() -> None:
    resp = client.post(
        "/api/store/import",
        headers=ADMIN,
        files={"csv_file": ("records.csv", b"id\n", "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"imported": 0, "skipped": 0}
