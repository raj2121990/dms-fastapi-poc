import os
import tempfile
import shutil
import pathlib

import pytest

# Prepare a temporary workspace before importing application modules.
TMP_ROOT = tempfile.mkdtemp(prefix="dms_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_ROOT}/test.db"
os.environ["UPLOAD_DIR"] = str(pathlib.Path(TMP_ROOT) / "uploads")
os.environ["STORAGE_BACKEND"] = "local"
os.environ["SEARCH_BACKEND"] = "sql"
os.environ["FORCE_BACKGROUND_PROCESSING"] = "false"
os.environ["PROCESSING_SYNC_SIZE_LIMIT_BYTES"] = str(10 * 1024 * 1024)


@pytest.fixture(scope="session")
def app():
    from database import init_db
    from main import app as application

    init_db()
    return application


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def pytest_unconfigure(config):
    try:
        shutil.rmtree(TMP_ROOT)
    except OSError:
        pass
