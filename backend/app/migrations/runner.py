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
CREATE_MIGRATION_TABLE = text(
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "name TEXT PRIMARY KEY, "
    "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ")"
)
SELECT_APPLIED_MIGRATIONS = text("SELECT name FROM schema_migrations")
INSERT_APPLIED_MIGRATION = text(
    "INSERT INTO schema_migrations (name) VALUES (:name)"
)


class MigrationFailedError(RuntimeError):
    """Raised when migration execution fails or recovery cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        migration_error: BaseException,
        recovery_error: BaseException | None = None,
        backup_path: Path | None,
    ) -> None:
        super().__init__(message)
        self.migration_error: BaseException = migration_error
        self.recovery_error: BaseException | None = recovery_error
        self.backup_path: Path | None = backup_path


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
        rows = connection.execute(SELECT_APPLIED_MIGRATIONS).scalars()
        return {str(name) for name in rows}


def _ensure_migration_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(CREATE_MIGRATION_TABLE)


def _record_migration(engine: Engine, name: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            INSERT_APPLIED_MIGRATION,
            {"name": name},
        )


def _recover_pre_migration_state(
    *,
    engine: Engine,
    database_path: Path,
    database_existed: bool,
    backup_path: Path | None,
) -> None:
    engine.dispose()
    if backup_path is not None:
        restore_verified_backup(backup_path, database_path)
    elif not database_existed:
        database_path.unlink(missing_ok=True)


def run_pending_migrations(
    *,
    engine: Engine,
    database_path: Path,
    backup_dir: Path,
    migrations: Sequence[MigrationSpec],
    validator: Callable[[], None] | None = None,
) -> MigrationRunResult:
    """Apply each pending migration once and restore the database on failure."""
    _validate_migrations(migrations)
    database_existed = database_path.is_file()
    if not database_existed and not migrations:
        return MigrationRunResult(applied_names=(), backup_path=None)

    applied = _applied_names(engine)
    pending = tuple(
        migration for migration in migrations if migration.name not in applied
    )

    if not pending:
        if database_path.is_file():
            verify_sqlite_database(database_path)
            if validator is not None:
                validator()
        return MigrationRunResult(applied_names=(), backup_path=None)

    backup_path = (
        create_verified_backup(database_path, backup_dir)
        if database_existed
        else None
    )
    applied_this_run: list[str] = []
    failure_target = pending[0].name

    try:
        _ensure_migration_table(engine)
        for migration in pending:
            failure_target = migration.name
            migration.apply()
            _record_migration(engine, migration.name)
            applied_this_run.append(migration.name)
        failure_target = "post_migration_validation"
        verify_sqlite_database(database_path)
        if validator is not None:
            validator()
    except BaseException as exc:
        try:
            _recover_pre_migration_state(
                engine=engine,
                database_path=database_path,
                database_existed=database_existed,
                backup_path=backup_path,
            )
        except BaseException as recovery_exc:
            recovery_description = (
                f"recovery from verified backup {backup_path}"
                if backup_path is not None
                else "removal of the newly created database"
            )
            raise MigrationFailedError(
                f"Migration {failure_target} failed and {recovery_description} "
                "failed; database state is unknown",
                migration_error=exc,
                recovery_error=recovery_exc,
                backup_path=backup_path,
            ) from recovery_exc

        if not isinstance(exc, Exception):
            if backup_path is not None:
                exc.add_note(f"Database restored from verified backup: {backup_path}")
            else:
                exc.add_note(
                    "The newly created database was removed; no backup was created"
                )
            raise
        recovery_message = (
            f"database was restored from verified backup {backup_path}"
            if backup_path is not None
            else "the newly created database was removed"
        )
        raise MigrationFailedError(
            f"Migration {failure_target} failed; {recovery_message}",
            migration_error=exc,
            backup_path=backup_path,
        ) from exc

    return MigrationRunResult(
        applied_names=tuple(applied_this_run),
        backup_path=backup_path,
    )
