"""Verified SQLite backup and restore primitives."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
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
        with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise DatabaseIntegrityError(
            f"SQLite integrity check failed for {path}"
        ) from exc

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
            closing(
                sqlite3.connect(_read_only_uri(source_path), uri=True)
            ) as source,
            closing(sqlite3.connect(temporary_path)) as destination,
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
            closing(
                sqlite3.connect(_read_only_uri(backup_path), uri=True)
            ) as source,
            closing(sqlite3.connect(temporary_path)) as destination,
        ):
            source.backup(destination)
        verify_sqlite_database(temporary_path)
        os.replace(temporary_path, destination_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
