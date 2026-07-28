"""Tests for versioned, recoverable SQLite migrations."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, text

from app.database_backups import verify_sqlite_database
from app.migrations import runner as runner_module
from app.migrations.runner import (
    MigrationFailedError,
    MigrationSpec,
    RecurringMaintenanceSpec,
    run_pending_migrations,
)


def _engine_for(path: Path, request: pytest.FixtureRequest) -> Engine:
    engine = create_engine(f"sqlite:///{path}")
    request.addfinalizer(engine.dispose)
    return engine


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


class SyntheticCancellation(BaseException):
    """Represent cancellation after a migration has committed a change."""


def test_migration_runs_once_while_recurring_maintenance_runs_each_time(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)
    migration_calls: list[str] = []
    maintenance_calls: list[str] = []

    def add_bonus() -> None:
        migration_calls.append("called")
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = balance + 5"))

    def add_recurring_credit() -> None:
        maintenance_calls.append("called")
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = balance + 1"))

    migration = MigrationSpec(name="20260710_add_bonus", apply=add_bonus)
    maintenance = RecurringMaintenanceSpec(
        name="recurring_credit",
        apply=add_recurring_credit,
    )

    first = run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(migration,),
        recurring_maintenance=(maintenance,),
    )
    assert first.backup_path is not None
    assert first.backup_path.is_file()
    first.backup_path.unlink()

    second = run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(migration,),
        recurring_maintenance=(maintenance,),
    )

    assert migration_calls == ["called"]
    assert maintenance_calls == ["called", "called"]
    assert _wallet_balance(engine) == 17
    assert first.applied_names == ("20260710_add_bonus",)
    assert second.applied_names == ()
    assert second.backup_path is None
    assert list(backup_dir.glob("*.db")) == []


def test_failed_recurring_maintenance_restores_and_reports_retained_backup(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)
    migration = MigrationSpec(name="baseline", apply=lambda: None)
    first = run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(migration,),
    )
    assert first.backup_path is not None
    first.backup_path.unlink()

    def damage_then_fail() -> None:
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = 0"))
        raise RuntimeError("synthetic recurring maintenance failure")

    with pytest.raises(MigrationFailedError) as exc_info:
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=backup_dir,
            migrations=(migration,),
            recurring_maintenance=(
                RecurringMaintenanceSpec(
                    name="recurring_cleanup",
                    apply=damage_then_fail,
                ),
            ),
        )

    backup_path = exc_info.value.backup_path
    assert backup_path is not None
    assert backup_path.is_file()
    assert str(backup_path) in str(exc_info.value)
    assert "recurring_cleanup" in str(exc_info.value)
    verify_sqlite_database(backup_path)
    restored_engine = _engine_for(database_path, request)
    assert _wallet_balance(restored_engine) == 10


def test_failed_migration_restores_the_pre_migration_database(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)

    def damage_then_fail() -> None:
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = 0"))
        raise RuntimeError("synthetic migration failure")

    migration = MigrationSpec(name="20260710_failing_change", apply=damage_then_fail)

    with pytest.raises(
        MigrationFailedError,
        match="20260710_failing_change",
    ) as exc_info:
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=backup_dir,
            migrations=(migration,),
        )

    backup_path = exc_info.value.backup_path
    assert backup_path is not None
    assert str(backup_path) in str(exc_info.value)
    assert backup_path.is_file()
    verify_sqlite_database(backup_path)
    restored_engine = _engine_for(database_path, request)
    assert _wallet_balance(restored_engine) == 10
    assert "schema_migrations" not in inspect(restored_engine).get_table_names()


def test_failed_post_migration_validation_restores_the_database(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)

    def add_bonus() -> None:
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = balance + 5"))

    def reject_schema() -> None:
        raise RuntimeError("synthetic schema validation failure")

    with pytest.raises(MigrationFailedError, match="post_migration_validation"):
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=tmp_path / "backups",
            migrations=(MigrationSpec(name="add_bonus", apply=add_bonus),),
            validator=reject_schema,
        )

    restored_engine = _engine_for(database_path, request)
    assert _wallet_balance(restored_engine) == 10
    assert "schema_migrations" not in inspect(restored_engine).get_table_names()


def test_cancellation_restores_then_preserves_cancellation_semantics(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)
    cancellation = SyntheticCancellation()

    def damage_then_cancel() -> None:
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = 0"))
        raise cancellation

    with pytest.raises(SyntheticCancellation) as exc_info:
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=tmp_path / "backups",
            migrations=(MigrationSpec(name="cancelled", apply=damage_then_cancel),),
        )

    assert exc_info.value is cancellation
    backup_paths = list((tmp_path / "backups").glob("*.db"))
    assert len(backup_paths) == 1
    backup_path = backup_paths[0]
    assert exc_info.value.__notes__ == [
        f"Database restored from verified backup: {backup_path}"
    ]
    verify_sqlite_database(backup_path)
    restored_engine = _engine_for(database_path, request)
    assert _wallet_balance(restored_engine) == 10
    assert "schema_migrations" not in inspect(restored_engine).get_table_names()


def test_recovery_failure_reports_unknown_state_and_preserves_both_errors(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "live.db"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)
    migration_error = RuntimeError("synthetic migration failure")
    recovery_error = OSError("synthetic restore failure")

    def damage_then_fail() -> None:
        with engine.begin() as connection:
            connection.execute(text("UPDATE wallet SET balance = 0"))
        raise migration_error

    def fail_restore(_backup_path: Path, _destination_path: Path) -> None:
        raise recovery_error

    monkeypatch.setattr(runner_module, "restore_verified_backup", fail_restore)

    with pytest.raises(MigrationFailedError) as exc_info:
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=tmp_path / "backups",
            migrations=(MigrationSpec(name="broken", apply=damage_then_fail),),
        )

    assert exc_info.value.migration_error is migration_error
    assert exc_info.value.recovery_error is recovery_error
    assert exc_info.value.__cause__ is recovery_error
    backup_path = exc_info.value.backup_path
    assert backup_path is not None
    assert str(exc_info.value) == (
        f"Migration broken failed and recovery from verified backup "
        f"{backup_path} failed; database state is unknown"
    )
    assert backup_path.is_file()
    verify_sqlite_database(backup_path)


def test_failed_new_database_migration_reports_removal_without_backup(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "new.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path, request)

    def create_then_fail() -> None:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE wallet (balance INTEGER)"))
        raise RuntimeError("synthetic new database migration failure")

    with pytest.raises(MigrationFailedError) as exc_info:
        run_pending_migrations(
            engine=engine,
            database_path=database_path,
            backup_dir=backup_dir,
            migrations=(MigrationSpec(name="new_database", apply=create_then_fail),),
        )

    assert exc_info.value.backup_path is None
    assert str(exc_info.value) == (
        "Migration new_database failed; the newly created database was removed"
    )
    assert not database_path.exists()
    assert not backup_dir.exists()


def test_absent_database_with_no_migrations_is_a_filesystem_no_op(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "absent.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path, request)

    result = run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(),
    )

    assert result.applied_names == ()
    assert result.backup_path is None
    assert not database_path.exists()
    assert not backup_dir.exists()


def test_no_pending_migrations_validates_without_creating_a_backup(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    engine = _engine_for(database_path, request)
    _seed_wallet(engine, 10)
    validator_calls: list[str] = []

    run_pending_migrations(
        engine=engine,
        database_path=database_path,
        backup_dir=backup_dir,
        migrations=(),
        validator=lambda: validator_calls.append("called"),
    )

    assert validator_calls == ["called"]
    assert _wallet_balance(engine) == 10
    assert not backup_dir.exists()
    assert "schema_migrations" not in inspect(engine).get_table_names()


def test_duplicate_migration_names_are_rejected_before_database_changes(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    database_path = tmp_path / "live.db"
    engine = _engine_for(database_path, request)
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
    assert _wallet_balance(engine) == 10
    assert "schema_migrations" not in inspect(engine).get_table_names()
