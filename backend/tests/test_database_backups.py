"""Tests for verified local SQLite backup and restore."""

from __future__ import annotations

import sqlite3
from contextlib import closing
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
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("CREATE TABLE entries (value TEXT NOT NULL)")
            connection.execute("INSERT INTO entries (value) VALUES (?)", (value,))


def _read_value(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
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

    with closing(sqlite3.connect(live)) as connection:
        with connection:
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
