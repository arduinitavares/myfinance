"""Module for backend tests imports test_runtime_config."""

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from app.config import load_settings, settings

TEST_ROOT: Path = Path(__file__).resolve().parents[1] / ".tmp"


def _load_module_from_path(module_name: str, module_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load module spec for {module_path}"
        raise AssertionError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_use_isolated_backend_test_paths() -> None:
    """Verify settings use isolated backend test paths."""
    assert settings.data_dir == TEST_ROOT / "data"
    assert settings.database_path == TEST_ROOT / "data" / "myfinance.db"
    assert settings.imports_dir == TEST_ROOT / "data" / "imports"
    assert settings.provider_config_path == TEST_ROOT / "config.local.yaml"


def test_conftest_bootstrap_overrides_preset_database_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify conftest bootstrap overrides preset database path."""
    monkeypatch.setenv(
        "MYFINANCE_DB_PATH",
        str(TEST_ROOT / "developer-shell.db"),
    )

    conftest_path = Path(__file__).resolve().parents[1] / "conftest.py"
    _load_module_from_path("runtime_config_conftest", conftest_path)

    assert os.environ["MYFINANCE_DB_PATH"] == str(TEST_ROOT / "data" / "myfinance.db")


def test_conftest_bootstrap_is_idempotent() -> None:
    """Verify conftest bootstrap is idempotent."""
    sentinel = TEST_ROOT / "data" / "keep-me.txt"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("present", encoding="utf-8")

    conftest_path = Path(__file__).resolve().parents[1] / "conftest.py"
    _load_module_from_path(
        "runtime_config_conftest_idempotent", conftest_path
    )

    assert sentinel.read_text(encoding="utf-8") == "present"


def test_load_settings_creates_parent_for_custom_database_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify load settings creates parent for custom database path."""
    custom_db_path = TEST_ROOT / "custom-db" / "nested" / "myfinance.sqlite3"
    monkeypatch.setenv("MYFINANCE_DATA_DIR", str(TEST_ROOT / "data"))
    monkeypatch.setenv("MYFINANCE_DB_PATH", str(custom_db_path))
    monkeypatch.setenv(
        "MYFINANCE_PROVIDER_CONFIG", str(TEST_ROOT / "config.local.yaml")
    )

    loaded = load_settings()

    assert loaded.database_path == custom_db_path.resolve()
    assert loaded.database_path.parent.exists()
