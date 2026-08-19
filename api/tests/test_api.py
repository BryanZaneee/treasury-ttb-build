"""Contract test: app boots, health responds, and each documented route
exists with the right shape. GET/create/read records are DB-backed (M1);
verify/patch/batches/jobs stay contract-only stubs until M2/M3/M5."""

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


def test_patch_record_stub() -> None:
    record_id = _create_record()
    resp = client.patch(f"/api/records/{record_id}", headers=ACCESS, json={})
    assert resp.status_code == 200
    assert resp.json()["id"] == record_id


def test_verify_record_not_found() -> None:
    resp = client.post("/api/records/does-not-exist/verify", headers=ACCESS)
    assert resp.status_code == 404


def test_verify_record_stub() -> None:
    record_id = _create_record()
    resp = client.post(f"/api/records/{record_id}/verify", headers=ACCESS)
    assert resp.status_code == 200
    assert resp.json()["id"] == record_id


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
