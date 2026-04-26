"""Module for backend app migrations run_migrations."""

import logging

from sqlalchemy.orm import Session

from app.database import engine
from app.database_manager import ensure_runtime_schema_compatibility
from app.migrations.migrate_classification_assistant import (
    migrate_classification_assistant,
)
from app.migrations.migrate_europe_iban_reclassification import (
    migrate_europe_iban_reclassification,
)
from app.migrations.migrate_expense_type_values import migrate_expense_type_values

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Handle run migrations."""
    try:
        logger.info("Starting migrations...")
        ensure_runtime_schema_compatibility()
        migrate_classification_assistant()
        migrate_expense_type_values()
        with Session(engine) as db:
            summary = migrate_europe_iban_reclassification(db)
        logger.info("Europe IBAN cleanup migration summary: %s", summary)
        logger.info("All migrations completed successfully")
    except Exception:
        logger.exception("Migration failed")
        raise


if __name__ == "__main__":
    run_migrations()
