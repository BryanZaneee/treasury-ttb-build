"""Point every test at an isolated, throwaway data directory - never the real
dev .env's data/ - and give each test a fresh, migrated database."""

import os
import shutil
import tempfile

import pytest

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="ttb-test-data-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR
os.environ.setdefault("ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")

import db  # must import after DATA_DIR is set above


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    db.wipe()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
