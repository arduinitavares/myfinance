"""Tests for explicit database administration commands."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Protocol

import pytest

from app.cli import database as database_cli


class _DisposableEngine(Protocol):
    def dispose(self) -> None:
        """Release every pooled database connection."""


def test_migrate_calls_migration_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[None] = []

    def fake_run_migrations() -> None:
        called.append(None)

    monkeypatch.setattr(database_cli, "run_migrations", fake_run_migrations)

    result = database_cli.main(["migrate"])

    assert result == 0
    assert called == [None]


def test_restore_requires_explicit_yes(tmp_path: Path) -> None:
    backup = tmp_path / "backup.db"

    with pytest.raises(SystemExit) as exc_info:
        database_cli.main(["restore", "--backup", str(backup)])

    assert exc_info.value.code == 2


def test_reset_requires_explicit_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        database_cli,
        "settings",
        replace(database_cli.settings, environment="test"),
    )

    with pytest.raises(SystemExit) as exc_info:
        database_cli.main(["reset", "--scope", "all"])

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


def test_restore_disposes_engine_around_database_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = tmp_path / "selected.db"
    events: list[str] = []

    class FakeEngine:
        def dispose(self) -> None:
            events.append("dispose")

    fake_engine: _DisposableEngine = FakeEngine()

    def fake_restore(_source: Path, _destination: Path) -> None:
        events.append("restore")

    monkeypatch.setattr(database_cli, "engine", fake_engine)
    monkeypatch.setattr(database_cli, "restore_verified_backup", fake_restore)

    result = database_cli.main(
        ["restore", "--backup", str(backup), "--yes"]
    )

    assert result == 0
    assert events == ["dispose", "restore", "dispose"]
