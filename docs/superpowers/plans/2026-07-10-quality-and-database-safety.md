# Quality and Database Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a reproducible quality gate and make every SQLite schema change recoverable before adding expense-completeness tables.

**Architecture:** First execute the warning-clean prerequisite plan linked
below. Then keep the existing FastAPI, SQLAlchemy, and SQLite structure.
Configure each quality tool to inspect only repository-owned code while
retaining every rule, then add stdlib SQLite backup primitives and a small
migration ledger that backs up, verifies, applies, and restores. Destructive
reset moves out of the HTTP API into an explicitly confirmed development/test
CLI.

**Tech Stack:** Python 3.13.12, uv, pyrepo-check 0.1.0, Ruff, ty, Bandit, pytest 8.3.5, FastAPI, SQLAlchemy 2.0.36, SQLite, GitHub Actions

## Global Constraints

- At execution time, create `dev/quality-database-safety` from the accepted documentation commit.
- Keep the application single-operator and local-first. Do not add hosted or multi-user behavior.
- Do not modify Financial Health, Projection, Anomaly, advice, or route-optimization behavior.
- Use the Python 3.13.12 environment declared by `.python-version` and `pyproject.toml`.
- The canonical Python gate is exactly `pyrepo-check --all` from the repository root.
- Ruff, annotations, ty, and pytest cover owned application code and tests. Bandit covers runtime application code and operational scripts, not test code.
- Owned code may not use `noqa`, `type: ignore`, `nosec`, disabled rules, per-file rule ignores, or configuration rule skips.
- Tool path exclusions may remove only environments, dependencies, generated files, worktrees, private financial files, documentation, frontend files from Python tools, and tests from Bandit.
- Use the smallest focused failing test before each behavior change.
- Add no dependency that is not already present in `backend/requirements.txt`; this slice only makes the existing backend environment reproducible from the root lock.
- Never read, copy, log, commit, or attach files under `bank_files/`, the live database, or backups during tests. Tests create temporary synthetic SQLite databases.
- Do not stage or commit `.codegraph/`.
- Every task ends with its focused tests passing and a small commit.

---

## Prerequisite

Execute
[Application Warning Cleanup](2026-07-23-application-warning-cleanup.md)
before Task 1. Its application/test/build output must be clean. `npm ci`
install-time third-party deprecation and audit notices remain separate
dependency-modernization work and must not be auto-fixed.

---

### Task 1: Make `pyrepo-check --all` Reproducible

**Files:**

- Create: `backend/tests/test_quality_policy.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.github/workflows/backend-tests.yml`
- Delete: `backend/pytest.ini`

**Interfaces:**

- Consumes: the existing `pyrepo-check --all` CLI contract and backend dependency versions in `backend/requirements.txt`.
- Produces: one root Python environment, native tool scope configuration, a suppression-policy test, and a CI job that runs the same local command.

- [ ] **Step 1: Write the failing quality-policy test**

Create `backend/tests/test_quality_policy.py`:

```python
"""Enforce the repository-owned Python quality contract."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OWNED_PYTHON_ROOTS = (
    PROJECT_ROOT / "backend" / "app",
    PROJECT_ROOT / "backend" / "scripts",
    PROJECT_ROOT / "backend" / "tests",
    PROJECT_ROOT / "backup",
    PROJECT_ROOT / "scripts",
)
EXPECTED_TY_INCLUDE = [
    "backend/app",
    "backend/scripts",
    "backend/tests",
    "backup",
    "scripts",
]
EXPECTED_RUFF_EXTEND_EXCLUDE = [
    ".codegraph",
    ".worktrees",
    "bank_files",
    "docs",
    "frontend",
]
EXPECTED_BANDIT_EXCLUDES = [
    ".codegraph",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    ".worktrees",
    "backend/tests",
    "bank_files",
    "docs",
    "frontend",
]
EXPECTED_PYTEST_ADDOPTS = "--ignore=backend/tests/live"
FORBIDDEN_SOURCE_MARKERS = (
    "no" + "qa",
    "no" + "sec",
    "type:" + " ignore",
)


def _pyproject() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)


def _table(container: dict[str, object], key: str) -> dict[str, object]:
    value = container[key]
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def test_python_tool_scope_matches_owned_code() -> None:
    """Require explicit owned-code scope without disabling rules."""
    config = _pyproject()
    tool = _table(config, "tool")
    ruff = _table(tool, "ruff")
    ty = _table(tool, "ty")
    ty_environment = _table(ty, "environment")
    ty_src = _table(ty, "src")
    bandit = _table(tool, "bandit")
    pytest_tool = _table(tool, "pytest")
    pytest_config = _table(pytest_tool, "ini_options")

    assert set(ruff) == {"extend-exclude"}
    assert ruff["extend-exclude"] == EXPECTED_RUFF_EXTEND_EXCLUDE
    assert set(ty) == {"environment", "src"}
    assert ty_environment == {
        "python": ".venv",
        "python-version": "3.13",
    }
    assert set(ty_src) == {"include"}
    assert ty_src["include"] == EXPECTED_TY_INCLUDE
    assert set(bandit) == {"exclude_dirs"}
    assert bandit["exclude_dirs"] == EXPECTED_BANDIT_EXCLUDES
    assert set(pytest_config) == {
        "addopts",
        "filterwarnings",
        "pythonpath",
        "testpaths",
    }
    assert pytest_config["testpaths"] == ["backend/tests"]
    assert pytest_config["pythonpath"] == ["backend"]
    assert pytest_config["filterwarnings"] == ["error"]
    assert pytest_config["addopts"] == EXPECTED_PYTEST_ADDOPTS


def test_owned_python_has_no_quality_suppression_markers() -> None:
    """Reject inline suppressions in application code, scripts, and tests."""
    violations: list[str] = []
    for owned_root in OWNED_PYTHON_ROOTS:
        for path in sorted(owned_root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN_SOURCE_MARKERS:
                if marker in text:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}: {marker}")

    assert violations == []


def test_quality_configuration_has_no_rule_suppression_tables() -> None:
    """Reject rule-ignore configuration while allowing path exclusions."""
    config = _pyproject()
    tool = _table(config, "tool")
    ruff_value = tool.get("ruff", {})
    assert isinstance(ruff_value, dict)
    ruff = cast("dict[str, object]", ruff_value)
    lint_value = ruff.get("lint", {})
    assert isinstance(lint_value, dict)
    lint = cast("dict[str, object]", lint_value)

    assert lint == {}
```

- [ ] **Step 2: Run the policy test and verify the scope assertion fails**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --with pytest==8.3.5 python -m pytest backend/tests/test_quality_policy.py -q
```

Expected: FAIL in `test_python_tool_scope_matches_owned_code` because the root tool scopes and root pytest configuration do not exist yet.

- [ ] **Step 3: Declare the existing backend environment and native tool scopes**

Replace the empty project dependency list and extend the development group in `pyproject.toml` with the versions already used by the backend:

```toml
[project]
name = "myfinance"
version = "0.1.0"
requires-python = ">=3.13.12,<3.14"
dependencies = [
    "apscheduler==3.10.4",
    "defusedxml==0.7.1",
    "fastapi==0.128.0",
    "httpx<0.28",
    "openai>=2.0.0",
    "pandas==2.3.3",
    "pydantic==2.13.3",
    "pypdf>=5.0.0",
    "python-dotenv==1.0.0",
    "python-multipart==0.0.6",
    "pyyaml==6.0.2",
    "qdrant-client>=1.7.0",
    "sentence-transformers>=2.5.0",
    "sqlalchemy==2.0.36",
    "uvicorn==0.24.0",
]

[dependency-groups]
dev = [
    "bandit[toml]>=1.8.6",
    "importlib-metadata>=8.7.1",
    "pytest==8.3.5",
    "ruff>=0.15.11",
    "ty>=0.0.31",
]
```

Add these tool sections. These are path boundaries, not rule suppressions:

```toml
[tool.ruff]
extend-exclude = [
    ".codegraph",
    ".worktrees",
    "bank_files",
    "docs",
    "frontend",
]

[tool.ty.environment]
python = ".venv"
python-version = "3.13"

[tool.ty.src]
include = [
    "backend/app",
    "backend/scripts",
    "backend/tests",
    "backup",
    "scripts",
]

[tool.bandit]
exclude_dirs = [
    ".codegraph",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    ".worktrees",
    "backend/tests",
    "bank_files",
    "docs",
    "frontend",
]

[tool.pytest.ini_options]
addopts = "--ignore=backend/tests/live"
filterwarnings = ["error"]
pythonpath = ["backend"]
testpaths = ["backend/tests"]
```

Remove the narrower duplicate pytest configuration and regenerate the lock:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
git rm backend/pytest.ini
uv lock
```

Expected: `uv.lock` now contains pytest and the existing backend runtime packages.

- [ ] **Step 4: Make CI install the pinned gate and run the exact command**

Replace `.github/workflows/backend-tests.yml` with:

```yaml
name: backend-tests

on:
  push:
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv and Python 3.13.12
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          enable-cache: true
          python-version: "3.13.12"

      - name: Install the pinned repository gate
        run: |
          uv tool install git+https://github.com/arduinitavares/pyrepo-check.git@8f88465e1ca88bf29b508f3c0f4eb96f4de31623
          echo "$(uv tool dir --bin)" >> "$GITHUB_PATH"

      - name: Sync the locked environment
        run: uv sync --frozen

      - name: Run the Python quality gate
        run: pyrepo-check --all
```

- [ ] **Step 5: Run the policy test and complete gate**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv sync --frozen
uv run --frozen python -m pytest backend/tests/test_quality_policy.py -q
pyrepo-check --all
```

Expected: the focused test passes, then Ruff, annotation checks, ty, scoped Bandit, and all backend tests pass. Bandit reports zero findings and does not traverse `.venv`, `.worktrees`, frontend dependencies, private files, or test code.

- [ ] **Step 6: Commit the reproducible gate**

```bash
git add pyproject.toml uv.lock .github/workflows/backend-tests.yml backend/tests/test_quality_policy.py backend/pytest.ini
git commit -m "build: enforce the repository Python gate"
```

---

### Task 2: Add Verified SQLite Backup and Restore Primitives

**Files:**

- Create: `backend/app/database_backups.py`
- Create: `backend/tests/test_database_backups.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/imports/test_runtime_config.py`

**Interfaces:**

- Consumes: `Settings.database_path` and `Settings.data_dir`.
- Produces: `verify_sqlite_database(path: Path) -> None`, `create_verified_backup(source_path: Path, backup_dir: Path, *, now: datetime | None = None) -> Path`, `restore_verified_backup(backup_path: Path, destination_path: Path) -> None`, and `Settings.backup_dir`.

- [ ] **Step 1: Write failing backup and restore tests**

Create `backend/tests/test_database_backups.py`:

```python
"""Tests for verified local SQLite backup and restore."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.database_backups import (
    DatabaseIntegrityError,
    create_verified_backup,
    restore_verified_backup,
    verify_sqlite_database,
)


def _create_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        connection.execute("INSERT INTO entries (value) VALUES (?)", (value,))


def _read_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM entries").fetchone()
    assert row is not None
    return str(row[0])


def test_create_verified_backup_captures_a_consistent_database(tmp_path: Path) -> None:
    source = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    _create_database(source, "before")

    backup = create_verified_backup(
        source,
        backup_dir,
        now=datetime(2026, 7, 10, 12, 30, tzinfo=UTC),
    )

    assert backup == backup_dir / "myfinance-20260710T123000000000Z.db"
    assert _read_value(backup) == "before"
    verify_sqlite_database(backup)


def test_restore_verified_backup_replaces_destination_atomically(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    _create_database(live, "before")
    backup = create_verified_backup(live, backup_dir)

    with sqlite3.connect(live) as connection:
        connection.execute("UPDATE entries SET value = 'after'")

    restore_verified_backup(backup, live)

    assert _read_value(live) == "before"
    assert not (tmp_path / ".live.db.restore").exists()


def test_corrupt_backup_never_replaces_live_database(tmp_path: Path) -> None:
    live = tmp_path / "live.db"
    corrupt = tmp_path / "corrupt.db"
    _create_database(live, "keep")
    corrupt.write_text("not a sqlite database", encoding="utf-8")

    with pytest.raises(DatabaseIntegrityError):
        restore_verified_backup(corrupt, live)

    assert _read_value(live) == "keep"
```

Add this assertion to `test_settings_use_isolated_backend_test_paths` in `backend/tests/imports/test_runtime_config.py`:

```python
assert settings.backup_dir == TEST_ROOT / "data" / "backups"
```

Add the matching field to the test protocol in that file:

```python
class _Settings(Protocol):
    """Settings attributes used by test fixtures."""

    backup_dir: Path
    imports_dir: Path
```

- [ ] **Step 2: Run the focused tests and verify the module is missing**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest \
  backend/tests/test_database_backups.py \
  backend/tests/imports/test_runtime_config.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.database_backups'`.

- [ ] **Step 3: Implement verified backup and atomic restore**

Create `backend/app/database_backups.py`:

```python
"""Verified SQLite backup and restore primitives."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class DatabaseIntegrityError(RuntimeError):
    """Raised when SQLite does not report a clean integrity check."""


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def verify_sqlite_database(path: Path) -> None:
    """Raise when a SQLite file is absent, unreadable, or corrupt."""
    if not path.is_file():
        raise FileNotFoundError(path)

    try:
        with sqlite3.connect(_read_only_uri(path), uri=True) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise DatabaseIntegrityError(f"SQLite integrity check failed for {path}") from exc

    if rows != [("ok",)]:
        raise DatabaseIntegrityError(
            f"SQLite integrity check did not return ok for {path}"
        )


def create_verified_backup(
    source_path: Path,
    backup_dir: Path,
    *,
    now: datetime | None = None,
) -> Path:
    """Create a consistent SQLite backup, verify it, then publish it."""
    verify_sqlite_database(source_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"myfinance-{stamp}.db"
    if backup_path.exists():
        raise FileExistsError(backup_path)
    temporary_path = backup_path.with_suffix(".tmp")
    temporary_path.unlink(missing_ok=True)

    try:
        with (
            sqlite3.connect(_read_only_uri(source_path), uri=True) as source,
            sqlite3.connect(temporary_path) as destination,
        ):
            source.backup(destination)
        verify_sqlite_database(temporary_path)
        os.replace(temporary_path, backup_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return backup_path


def restore_verified_backup(backup_path: Path, destination_path: Path) -> None:
    """Verify a backup and atomically replace the destination database."""
    verify_sqlite_database(backup_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_name(f".{destination_path.name}.restore")
    temporary_path.unlink(missing_ok=True)

    try:
        with (
            sqlite3.connect(_read_only_uri(backup_path), uri=True) as source,
            sqlite3.connect(temporary_path) as destination,
        ):
            source.backup(destination)
        verify_sqlite_database(temporary_path)
        os.replace(temporary_path, destination_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
```

Extend `Settings` in `backend/app/config.py`:

```python
@dataclass(frozen=True)
class Settings:
    """Represent settings."""

    data_dir: Path
    database_path: Path
    backup_dir: Path
    imports_dir: Path
    batch_import_dir: Path
    provider_config_path: Path
    provider_example_path: Path
    fx_seed_years: int
    fx_startup_catchup_days: int
    fx_refresh_hour_utc: int
    fx_refresh_minute_utc: int
    ecb_history_url: str
    ecb_history_90d_url: str
```

Inside `load_settings`, create the backup directory next to `imports_dir`:

```python
backup_dir = data_dir / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
```

Pass it to `Settings`:

```python
return Settings(
    data_dir=data_dir,
    database_path=database_path,
    backup_dir=backup_dir,
    imports_dir=imports_dir,
    batch_import_dir=batch_import_dir,
    provider_config_path=provider_config_path,
    provider_example_path=provider_example_path,
    fx_seed_years=fx_seed_years,
    fx_startup_catchup_days=fx_startup_catchup_days,
    fx_refresh_hour_utc=fx_refresh_hour_utc,
    fx_refresh_minute_utc=fx_refresh_minute_utc,
    ecb_history_url=ecb_history_url,
    ecb_history_90d_url=ecb_history_90d_url,
)
```

- [ ] **Step 4: Run the focused tests and quality checks**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest \
  backend/tests/test_database_backups.py \
  backend/tests/imports/test_runtime_config.py -q
uv run --frozen python -m ruff check \
  backend/app/database_backups.py \
  backend/app/config.py \
  backend/tests/test_database_backups.py \
  backend/tests/imports/test_runtime_config.py
uv run --frozen python -m ty check \
  backend/app/database_backups.py \
  backend/app/config.py \
  backend/tests/test_database_backups.py
```

Expected: all commands pass. The tests use only synthetic databases under pytest temporary directories.

- [ ] **Step 5: Commit verified local backups**

```bash
git add \
  backend/app/database_backups.py \
  backend/app/config.py \
  backend/tests/test_database_backups.py \
  backend/tests/imports/test_runtime_config.py
git commit -m "feat: add verified SQLite backup restore"
```

---

### Task 3: Guard Versioned Migrations with Automatic Recovery

**Files:**

- Create: `backend/app/migrations/runner.py`
- Create: `backend/tests/test_migration_runner.py`
- Modify: `backend/app/migrations/run_migrations.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/main.py`

**Interfaces:**

- Consumes: the verified backup functions from Task 2, the existing `init_database()`, SQLAlchemy `engine`, and `Settings.backup_dir`.
- Produces: `MigrationSpec`, `MigrationRunResult`, `MigrationFailedError`, `run_pending_migrations(...)`, a recorded baseline migration, and `assert_required_schema() -> None`.

- [ ] **Step 1: Write failing migration-runner tests**

Create `backend/tests/test_migration_runner.py`:

```python
"""Tests for versioned, recoverable SQLite migrations."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, text

from app.migrations.runner import (
    MigrationFailedError,
    MigrationSpec,
    run_pending_migrations,
)


def _engine_for(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}")


def _seed_wallet(engine: Engine, balance: int) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE wallet (balance INTEGER NOT NULL)"))
        connection.execute(
            text("INSERT INTO wallet (balance) VALUES (:balance)"),
            {"balance": balance},
        )


def _wallet_balance(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.execute(text("SELECT balance FROM wallet")).scalar_one()
    return int(value)


def test_successful_migration_is_backed_up_recorded_and_not_repeated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path)
    _seed_wallet(engine, 10)
    calls: list[str] = []

    def add_bonus() -> None:
        calls.append("called")
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = balance + 5"))

    migration = MigrationSpec(name="20260710_add_bonus", apply=add_bonus)

    first = run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(migration,),
    )
    second = run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(migration,),
    )

    assert calls == ["called"]
    assert _wallet_balance(engine) == 15
    assert first.applied_names == ("20260710_add_bonus",)
    assert first.backup_path is not None
    assert first.backup_path.is_file()
    assert second.applied_names == ()
    assert second.backup_path is None


def test_failed_migration_restores_the_pre_migration_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path)
    _seed_wallet(engine, 10)

    def damage_then_fail() -> None:
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = 0"))
        raise RuntimeError("synthetic migration failure")

    migration = MigrationSpec(name="20260710_failing_change", apply=damage_then_fail)

    with pytest.raises(MigrationFailedError, match="20260710_failing_change"):
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=backup_dir,
            migrations=(migration,),
        )

    restored_engine = _engine_for(database_path)
    assert _wallet_balance(restored_engine) == 10
    assert "schema_migrations" not in inspect(restored_engine).get_table_names()


def test_duplicate_migration_names_are_rejected_before_database_changes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "live.db"
    engine = _engine_for(database_path)
    _seed_wallet(engine, 10)
    duplicate = MigrationSpec(name="same", apply=lambda: None)

    with pytest.raises(ValueError, match="Migration names must be unique"):
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=tmp_path / "backups",
            migrations=(duplicate, duplicate),
        )

    assert list((tmp_path / "backups").glob("*.db")) == []
```

- [ ] **Step 2: Run the focused test and verify the runner is missing**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest backend/tests/test_migration_runner.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.migrations.runner'`.

- [ ] **Step 3: Implement the recoverable migration runner**

Create `backend/app/migrations/runner.py`:

```python
"""Versioned migration execution with verified backup recovery."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, inspect, text

from app.database_backups import (
    create_verified_backup,
    restore_verified_backup,
    verify_sqlite_database,
)

MIGRATION_TABLE = "schema_migrations"


class MigrationFailedError(RuntimeError):
    """Raised after a failed migration has restored the prior database."""


@dataclass(frozen=True)
class MigrationSpec:
    """One named, idempotent database migration."""

    name: str
    apply: Callable[[], None]


@dataclass(frozen=True)
class MigrationRunResult:
    """Describe the changes and backup produced by one migration run."""

    applied_names: tuple[str, ...]
    backup_path: Path | None


def _validate_migrations(migrations: Sequence[MigrationSpec]) -> None:
    names = [migration.name for migration in migrations]
    if any(not name.strip() for name in names):
        raise ValueError("Migration names must not be empty")
    if len(names) != len(set(names)):
        raise ValueError("Migration names must be unique")


def _applied_names(engine: Engine) -> set[str]:
    if MIGRATION_TABLE not in inspect(engine).get_table_names():
        return set()
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT name FROM {MIGRATION_TABLE}")
        ).scalars()
        return {str(name) for name in rows}


def _ensure_migration_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} ("
                "name TEXT PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


def _record_migration(engine: Engine, name: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {MIGRATION_TABLE} (name) VALUES (:name)"),
            {"name": name},
        )


def run_pending_migrations(
    *,
    engine: Engine,
    database_path: Path,
    backup_dir: Path,
    migrations: Sequence[MigrationSpec],
) -> MigrationRunResult:
    """Apply each pending migration once and restore the database on failure."""
    _validate_migrations(migrations)
    database_existed = database_path.is_file()
    applied = _applied_names(engine)
    pending = tuple(migration for migration in migrations if migration.name not in applied)

    if not pending:
        if database_path.is_file():
            verify_sqlite_database(database_path)
        return MigrationRunResult(applied_names=(), backup_path=None)

    backup_path = (
        create_verified_backup(database_path, backup_dir)
        if database_existed
        else None
    )
    applied_this_run: list[str] = []

    try:
        _ensure_migration_table(engine)
        for migration in pending:
            migration.apply()
            _record_migration(engine, migration.name)
            applied_this_run.append(migration.name)
        verify_sqlite_database(database_path)
    except Exception as exc:
        failed_name = (
            pending[len(applied_this_run)].name
            if len(applied_this_run) < len(pending)
            else "post_migration_integrity_check"
        )
        engine.dispose()
        if backup_path is not None:
            restore_verified_backup(backup_path, database_path)
        elif not database_existed:
            database_path.unlink(missing_ok=True)
        raise MigrationFailedError(
            f"Migration {failed_name} failed; the previous database was restored"
        ) from exc

    return MigrationRunResult(
        applied_names=tuple(applied_this_run),
        backup_path=backup_path,
    )
```

- [ ] **Step 4: Register the current schema as the first versioned baseline**

Add this function to `backend/app/database_manager.py` after `init_database`:

```python
def assert_required_schema() -> None:
    """Fail startup when a recorded database is missing required tables."""
    existing_tables = set(inspect(engine).get_table_names())
    missing_tables = sorted(set(REQUIRED_TABLE_NAMES) - existing_tables)
    if missing_tables:
        missing = ", ".join(missing_tables)
        raise RuntimeError(f"Database schema is missing required tables: {missing}")
```

Replace `backend/app/migrations/run_migrations.py` with:

```python
"""Run registered MyFinance database migrations."""

from __future__ import annotations

import logging

from app.config import settings
from app.database import engine
from app.database_manager import assert_required_schema, init_database
from app.migrations.migrate_classification_assistant import (
    migrate_classification_assistant,
)
from app.migrations.migrate_expense_type_values import migrate_expense_type_values
from app.migrations.runner import (
    MigrationRunResult,
    MigrationSpec,
    run_pending_migrations,
)

logger: logging.Logger = logging.getLogger(__name__)


def _apply_existing_schema_baseline() -> None:
    """Run every existing schema initializer and idempotent value migration."""
    init_database()
    migrate_classification_assistant()
    migrate_expense_type_values()


MIGRATIONS: tuple[MigrationSpec, ...] = (
    MigrationSpec(
        name="20260710_existing_schema_baseline",
        apply=_apply_existing_schema_baseline,
    ),
)


def run_migrations() -> MigrationRunResult:
    """Apply pending migrations, verify the schema, and return the backup used."""
    result = run_pending_migrations(
        engine=engine,
        database_path=settings.database_path,
        backup_dir=settings.backup_dir,
        migrations=MIGRATIONS,
    )
    assert_required_schema()
    logger.info("Applied database migrations: %s", result.applied_names)
    return result


if __name__ == "__main__":
    run_migrations()
```

In `backend/app/main.py`, replace the existing `database_manager` import block with these imports:

```python
from .database_manager import reset_database
from .migrations.run_migrations import run_migrations
```

Replace the startup call:

```python
# Apply recoverable schema migrations before startup-only data loading.
run_migrations()
suggestions.initialize_category_suggestion_model()
```

- [ ] **Step 5: Run migration, startup, and existing migration tests**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest \
  backend/tests/test_migration_runner.py \
  backend/tests/test_europe_transfer_cleanup_migration.py \
  backend/tests/imports/test_import_dedupe.py \
  backend/tests/services/test_reporting_currency.py -q
uv run --frozen python -m ruff check \
  backend/app/migrations/runner.py \
  backend/app/migrations/run_migrations.py \
  backend/app/database_manager.py \
  backend/app/main.py \
  backend/tests/test_migration_runner.py
uv run --frozen python -m ty check \
  backend/app/migrations/runner.py \
  backend/app/migrations/run_migrations.py \
  backend/app/database_manager.py \
  backend/tests/test_migration_runner.py
```

Expected: all commands pass. The failure test proves the committed pre-migration value survives a migration that commits damage and then raises.

- [ ] **Step 6: Commit recoverable migrations**

```bash
git add \
  backend/app/migrations/runner.py \
  backend/app/migrations/run_migrations.py \
  backend/app/database_manager.py \
  backend/app/main.py \
  backend/tests/test_migration_runner.py
git commit -m "feat: guard database migrations with backups"
```

---

### Task 4: Move Restore and Reset into an Explicit Database CLI

**Files:**

- Create: `backend/app/cli/__init__.py`
- Create: `backend/app/cli/database.py`
- Create: `backend/tests/test_database_cli.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/imports/test_runtime_config.py`
- Modify: `README.md`

**Interfaces:**

- Consumes: `run_migrations()`, `restore_verified_backup(...)`, `reset_database(scope)`, SQLAlchemy `engine`, and `Settings.database_path`.
- Produces: `python -m app.cli.database migrate`, `python -m app.cli.database restore --backup PATH --yes`, and development/test-only `python -m app.cli.database reset --scope SCOPE --yes`.

- [ ] **Step 1: Write failing CLI safety tests**

Create `backend/tests/test_database_cli.py`:

```python
"""Tests for explicit database administration commands."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.cli import database as database_cli


def test_restore_requires_explicit_yes(tmp_path: Path) -> None:
    backup = tmp_path / "backup.db"

    with pytest.raises(SystemExit) as exc_info:
        database_cli.main(["restore", "--backup", str(backup)])

    assert exc_info.value.code == 2


def test_reset_is_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        database_cli,
        "settings",
        replace(database_cli.settings, environment="production"),
    )

    with pytest.raises(RuntimeError, match="development or test"):
        database_cli.main(["reset", "--scope", "all", "--yes"])


def test_reset_calls_existing_reset_service_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        database_cli,
        "settings",
        replace(database_cli.settings, environment="test"),
    )
    monkeypatch.setattr(database_cli, "reset_database", called.append)

    result = database_cli.main(
        ["reset", "--scope", "transactions", "--yes"]
    )

    assert result == 0
    assert called == ["transactions"]


def test_restore_uses_the_selected_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = tmp_path / "selected.db"
    restored: list[tuple[Path, Path]] = []

    def fake_restore(source: Path, destination: Path) -> None:
        restored.append((source, destination))

    monkeypatch.setattr(database_cli, "restore_verified_backup", fake_restore)

    result = database_cli.main(
        ["restore", "--backup", str(backup), "--yes"]
    )

    assert result == 0
    assert restored == [(backup.resolve(), database_cli.settings.database_path)]
```

Add these tests to `backend/tests/imports/test_runtime_config.py`:

```python
def test_load_settings_defaults_to_production_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYFINANCE_ENV", raising=False)

    loaded = load_settings()

    assert loaded.environment == "production"


def test_load_settings_rejects_unknown_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYFINANCE_ENV", "shared-host")

    with pytest.raises(ValueError, match="MYFINANCE_ENV"):
        load_settings()
```

- [ ] **Step 2: Run the tests and verify the CLI package is missing**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest \
  backend/tests/test_database_cli.py \
  backend/tests/imports/test_runtime_config.py -q
```

Expected: collection fails because `app.cli.database` does not exist.

- [ ] **Step 3: Add validated runtime environment configuration**

Add `environment: str` to the exact `Settings` dataclass field list in `backend/app/config.py`, directly after `backup_dir`:

```python
environment: str
```

In `load_settings`, validate the environment after creating `backup_dir`:

```python
environment = os.environ.get("MYFINANCE_ENV", "production").strip().lower()
if environment not in {"development", "test", "production"}:
    raise ValueError(
        "MYFINANCE_ENV must be development, test, or production"
    )
```

Pass the value to `Settings` between `backup_dir` and `imports_dir`:

```python
environment=environment,
```

- [ ] **Step 4: Implement the database CLI**

Create `backend/app/cli/__init__.py`:

```python
"""Command-line administration for local MyFinance operations."""
```

Create `backend/app/cli/database.py`:

```python
"""Explicit migration, restore, and development reset commands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from app.config import settings
from app.database import engine
from app.database_backups import restore_verified_backup
from app.database_manager import reset_database
from app.migrations.run_migrations import run_migrations

RESET_SCOPES: tuple[str, ...] = (
    "all",
    "transactions",
    "statistics",
    "financial_health",
    "projections",
    "anomalies",
    "imports",
    "classification",
)
RESET_ENVIRONMENTS: frozenset[str] = frozenset({"development", "test"})


def build_parser() -> argparse.ArgumentParser:
    """Build the local database administration parser."""
    parser = argparse.ArgumentParser(prog="myfinance-database")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Apply pending verified migrations")

    restore = commands.add_parser("restore", help="Restore a verified backup")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--yes", action="store_true")

    reset = commands.add_parser("reset", help="Reset development or test data")
    reset.add_argument("--scope", choices=RESET_SCOPES, default="all")
    reset.add_argument("--yes", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicitly selected database administration command."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        run_migrations()
        return 0

    if not args.yes:
        parser.error("--yes is required for restore and reset")

    if args.command == "restore":
        backup_path = Path(args.backup).expanduser().resolve()
        engine.dispose()
        restore_verified_backup(backup_path, settings.database_path)
        engine.dispose()
        return 0

    if settings.environment not in RESET_ENVIRONMENTS:
        raise RuntimeError(
            "Database reset is available only in development or test"
        )
    reset_database(str(args.scope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Document the exact recovery commands**

Add this section to `README.md`:

````markdown
## Database safety

MyFinance creates and verifies a timestamped SQLite backup before applying any pending migration to an existing database. A failed migration restores that backup automatically.

Apply pending migrations:

```bash
PYTHONPATH=backend uv run --frozen python -m app.cli.database migrate
```

Restore a selected verified backup:

Stop the backend process before restoring so no other process holds or writes the live database.

```bash
PYTHONPATH=backend uv run --frozen python -m app.cli.database restore \
  --backup /absolute/path/to/myfinance-YYYYMMDDTHHMMSSffffffZ.db \
  --yes
```

Reset is unavailable in the production environment. For development or tests only:

```bash
MYFINANCE_ENV=development PYTHONPATH=backend uv run --frozen \
  python -m app.cli.database reset --scope transactions --yes
```
````

- [ ] **Step 6: Run the CLI and configuration tests**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest \
  backend/tests/test_database_cli.py \
  backend/tests/test_database_backups.py \
  backend/tests/test_migration_runner.py \
  backend/tests/imports/test_runtime_config.py -q
uv run --frozen python -m ruff check \
  backend/app/cli \
  backend/app/config.py \
  backend/tests/test_database_cli.py \
  backend/tests/imports/test_runtime_config.py
uv run --frozen python -m ty check \
  backend/app/cli \
  backend/app/config.py \
  backend/tests/test_database_cli.py
```

Expected: all commands pass. The tests prove reset cannot run under the default production environment and restore cannot run without `--yes`.

- [ ] **Step 7: Commit the explicit database CLI**

```bash
git add \
  README.md \
  backend/app/cli \
  backend/app/config.py \
  backend/tests/test_database_cli.py \
  backend/tests/imports/test_runtime_config.py
git commit -m "feat: add explicit database recovery CLI"
```

---

### Task 5: Remove the Destructive API and Restrict CORS

**Files:**

- Create: `backend/tests/test_app_security.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `docker-compose.yaml`
- Modify: `README.md`

**Interfaces:**

- Consumes: the production-default `Settings.environment` from Task 4 and the existing FastAPI application.
- Produces: `Settings.frontend_origin`, exact-origin CORS middleware, no HTTP reset route, and a documented local network boundary.

- [ ] **Step 1: Write failing application-boundary tests**

Create `backend/tests/test_app_security.py`:

```python
"""Tests for the local application network and destructive-operation boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from app.config import load_settings, settings
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _cors_middleware() -> Middleware:
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return middleware
    raise AssertionError("CORS middleware is not configured")


def test_normal_api_has_no_database_reset_route() -> None:
    """Keep destructive reset outside the HTTP application."""
    route_paths = {route.path for route in app.routes}

    assert "/debug/reset-database" not in route_paths


def test_cors_uses_only_the_configured_frontend_origin() -> None:
    """Reject wildcard browser origins even for a local deployment."""
    middleware = _cors_middleware()

    assert middleware.options["allow_origins"] == [settings.frontend_origin]
    assert middleware.options["allow_credentials"] is True


def test_frontend_origin_can_be_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYFINANCE_FRONTEND_ORIGIN", "https://finance.local")

    loaded = load_settings()

    assert loaded.frontend_origin == "https://finance.local"


def test_wildcard_frontend_origin_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYFINANCE_FRONTEND_ORIGIN", "*")

    with pytest.raises(ValueError, match="must be one exact origin"):
        load_settings()


def test_compose_binds_backend_and_frontend_to_loopback() -> None:
    """Keep Docker services off externally reachable host interfaces."""
    with (PROJECT_ROOT / "docker-compose.yaml").open(encoding="utf-8") as stream:
        compose = yaml.safe_load(stream)

    assert compose["services"]["backend"]["ports"] == [
        "127.0.0.1:8000:8000"
    ]
    assert compose["services"]["frontend"]["ports"] == [
        "127.0.0.1:8080:8080"
    ]
```

- [ ] **Step 2: Run the boundary tests and verify the current API fails them**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest backend/tests/test_app_security.py -q
```

Expected: FAIL because `/debug/reset-database` exists, CORS uses `allow_origins=["*"]`, and `Settings` has no `frontend_origin`.

- [ ] **Step 3: Add exact frontend-origin configuration**

Add this field to `Settings` in `backend/app/config.py` after `environment`:

```python
frontend_origin: str
```

In `load_settings`, validate the exact origin after validating `environment`:

```python
frontend_origin = os.environ.get(
    "MYFINANCE_FRONTEND_ORIGIN",
    "http://localhost:3000",
).strip().rstrip("/")
if not frontend_origin or frontend_origin == "*":
    raise ValueError("MYFINANCE_FRONTEND_ORIGIN must be one exact origin")
```

Pass it to `Settings` between `environment` and `imports_dir`:

```python
frontend_origin=frontend_origin,
```

- [ ] **Step 4: Remove HTTP reset and configure exact-origin CORS**

In `backend/app/main.py`:

1. Replace `from fastapi import FastAPI, HTTPException` with `from fastapi import FastAPI`.
2. Remove `from sqlalchemy.exc import SQLAlchemyError` because the reset route was its only caller.
3. Remove the `database_manager` import that contains only `reset_database` after Task 3.
4. Remove the entire `debug_reset_database` route and function.
5. Replace the CORS block with:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
```

Add these backend environment entries to `docker-compose.yaml`:

```yaml
      - MYFINANCE_ENV=production
      - MYFINANCE_FRONTEND_ORIGIN=http://localhost:8080
```

Bind both published ports to host loopback:

```yaml
    ports:
      - "127.0.0.1:8000:8000"
```

```yaml
    ports:
      - "127.0.0.1:8080:8080"
```

- [ ] **Step 5: Document the local network boundary**

Add this paragraph after the database-safety section in `README.md`:

```markdown
## Local network boundary

The backend is for a single trusted device and is not a public internet service. It accepts browser requests only from `MYFINANCE_FRONTEND_ORIGIN`. Docker Compose sets that origin to `http://localhost:8080`. Remote access must use a trusted tunnel or VPN; the current PIN is not an authentication boundary.
```

- [ ] **Step 6: Run the application-boundary and regression tests**

Run:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv run --frozen python -m pytest \
  backend/tests/test_app_security.py \
  backend/tests/test_database_cli.py \
  backend/tests/test_upload_guardrails.py \
  backend/tests/test_upload_trust_order.py -q
uv run --frozen python -m ruff check \
  backend/app/config.py \
  backend/app/main.py \
  backend/tests/test_app_security.py
uv run --frozen python -m ty check \
  backend/app/config.py \
  backend/app/main.py \
  backend/tests/test_app_security.py
```

Expected: all commands pass. Route inspection proves the destructive endpoint is absent, and middleware inspection proves wildcard origins are absent.

- [ ] **Step 7: Commit the local application boundary**

```bash
git add \
  README.md \
  backend/app/config.py \
  backend/app/main.py \
  backend/tests/test_app_security.py \
  docker-compose.yaml
git commit -m "fix: enforce the local application boundary"
```

---

## Final Verification

Run the complete repository gates from a fresh locked environment:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
uv sync --frozen
pyrepo-check --all
cd frontend
npm ci
npm run test:ci
npm run build
npm run check:bundle
cd ..
git diff --check
git status --short
```

Expected:

- `pyrepo-check --all` exits 0 after Ruff, annotation checks, ty, scoped Bandit, and all backend tests.
- Bandit reports zero findings in owned runtime code, and the suppression-policy test reports no forbidden markers in owned Python.
- All four frontend commands exit 0. Frontend test and build output contains no
  application/test/build warnings. Install-time third-party deprecation and
  audit notices from `npm ci` are recorded separately and are not auto-fixed.
- `git diff --check` exits 0.
- `git status --short` contains no implementation files. The user-created `.codegraph/` may remain untracked and must not be staged.
- No real statement, database, backup, account identifier, or private transaction text appears in the diff or test output.
