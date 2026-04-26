"""Module for backend tests conftest."""

import importlib
import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol, cast

import pytest
from sqlalchemy.orm import Session, sessionmaker

TEST_ROOT: Path = Path(__file__).resolve().parent / ".tmp"


class _Settings(Protocol):
    """Settings attributes used by test fixtures."""

    imports_dir: Path


class _ConfigModule(Protocol):
    """Config module attributes used by test fixtures."""

    settings: _Settings


class _DatabaseModule(Protocol):
    """Database module attributes used by test fixtures."""

    SessionLocal: sessionmaker[Session]


class _DatabaseManagerModule(Protocol):
    """Database manager module attributes used by test fixtures."""

    reset_database: Callable[[], None]


def bootstrap_test_environment() -> None:
    """Handle bootstrap test environment."""
    data_dir = TEST_ROOT / "data"
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ["MYFINANCE_DATA_DIR"] = str(data_dir.resolve())
    os.environ["MYFINANCE_DB_PATH"] = str((data_dir / "myfinance.db").resolve())
    os.environ["MYFINANCE_PROVIDER_CONFIG"] = str(
        (TEST_ROOT / "config.local.yaml").resolve()
    )


bootstrap_test_environment()

_config_module: _ConfigModule = cast(
    "_ConfigModule", importlib.import_module("app.config")
)
_database_module: _DatabaseModule = cast(
    "_DatabaseModule", importlib.import_module("app.database")
)
_database_manager_module: _DatabaseManagerModule = cast(
    "_DatabaseManagerModule", importlib.import_module("app.database_manager")
)
settings: _Settings = _config_module.settings
SessionLocal: sessionmaker[Session] = _database_module.SessionLocal
reset_database: Callable[[], None] = _database_manager_module.reset_database


def _clear_import_artifacts() -> None:
    shutil.rmtree(settings.imports_dir, ignore_errors=True)
    settings.imports_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Handle db session."""
    _clear_import_artifacts()
    reset_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        _clear_import_artifacts()
