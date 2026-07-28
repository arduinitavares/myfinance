"""Run registered MyFinance database migrations."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine
from app.database_manager import assert_required_schema, init_database
from app.migrations.migrate_classification_assistant import (
    migrate_classification_assistant,
)
from app.migrations.migrate_europe_iban_reclassification import (
    migrate_europe_iban_reclassification,
)
from app.migrations.migrate_expense_type_values import migrate_expense_type_values
from app.migrations.runner import (
    MigrationRunResult,
    MigrationSpec,
    RecurringMaintenanceSpec,
    run_pending_migrations,
)

logger: logging.Logger = logging.getLogger(__name__)


def _apply_existing_schema_baseline() -> None:
    """Run every existing schema initializer and idempotent value migration."""
    init_database(run_europe_iban_cleanup=False)
    migrate_classification_assistant()
    migrate_expense_type_values()


MIGRATIONS: tuple[MigrationSpec, ...] = (
    MigrationSpec(
        name="20260710_existing_schema_baseline",
        apply=_apply_existing_schema_baseline,
    ),
)


def _run_europe_iban_transfer_cleanup() -> None:
    """Correct deterministic Europe transfer rows imported since startup."""
    with Session(engine) as db:
        summary = migrate_europe_iban_reclassification(db)
    logger.info("Europe IBAN recurring cleanup summary: %s", summary)


RECURRING_MAINTENANCE: tuple[RecurringMaintenanceSpec, ...] = (
    RecurringMaintenanceSpec(
        name="europe_iban_transfer_cleanup",
        apply=_run_europe_iban_transfer_cleanup,
    ),
)


def run_migrations() -> MigrationRunResult:
    """Apply migrations and recurring maintenance inside backup recovery."""
    result = run_pending_migrations(
        engine=engine,
        database_path=settings.database_path,
        backup_dir=settings.backup_dir,
        migrations=MIGRATIONS,
        recurring_maintenance=RECURRING_MAINTENANCE,
        validator=assert_required_schema,
    )
    logger.info("Applied database migrations: %s", result.applied_names)
    return result


if __name__ == "__main__":
    run_migrations()
