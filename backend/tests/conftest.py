import os
import shutil
from pathlib import Path

import pytest


TEST_ROOT = Path(__file__).resolve().parent / ".tmp"
shutil.rmtree(TEST_ROOT, ignore_errors=True)
(TEST_ROOT / "data").mkdir(parents=True, exist_ok=True)

os.environ["MYFINANCE_DATA_DIR"] = str((TEST_ROOT / "data").resolve())
os.environ["MYFINANCE_DB_PATH"] = str((TEST_ROOT / "data" / "myfinance.db").resolve())
os.environ["MYFINANCE_PROVIDER_CONFIG"] = str((TEST_ROOT / "config.local.yaml").resolve())

from app.config import settings
from app.database import SessionLocal
from app.database_manager import reset_database


def _clear_import_artifacts() -> None:
    shutil.rmtree(settings.imports_dir, ignore_errors=True)
    settings.imports_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def db_session():
    _clear_import_artifacts()
    reset_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        _clear_import_artifacts()
