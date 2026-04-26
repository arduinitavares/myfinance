"""Module for backend app migrations migrate_classification_assistant."""

import contextlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from sqlalchemy import inspect, text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Table

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.database import Base, engine
from app.models.classification import (
    ClassificationSession,
    ClassificationTurn,
    RecurrencePattern,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger: logging.Logger = logging.getLogger(__name__)


class SqlCursor(Protocol):
    """Minimal DB-API cursor protocol used by this migration."""

    def execute(self, operation: str) -> object:
        """Execute one SQL statement."""


def _has_recurrence_pattern_foreign_key() -> bool:
    inspector = inspect(engine)
    for foreign_key in inspector.get_foreign_keys("transactions"):
        constrained_columns = foreign_key.get("constrained_columns") or []
        if (
            constrained_columns == ["recurrence_pattern_id"]
            and foreign_key.get("referred_table") == "recurrence_patterns"
        ):
            return True
    return False


def _rebuild_transactions_table_with_foreign_key(transaction_columns: set[str]) -> None:
    logger.info(
        "Rebuilding transactions table to add recurrence_pattern_id foreign key"
    )
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute(
            "DROP TABLE IF EXISTS transactions__classification_assistant_migration"
        )
        cursor.execute(
            """
            CREATE TABLE transactions__classification_assistant_migration (
                id INTEGER NOT NULL PRIMARY KEY,
                import_session_id INTEGER,
                import_source_locator VARCHAR(255),
                import_source_description VARCHAR(500),
                canonical_description_en VARCHAR(500),
                account_number VARCHAR(50),
                transaction_date DATE,
                amount FLOAT,
                currency VARCHAR(3),
                description VARCHAR(500),
                counterparty_name VARCHAR(200),
                counterparty_account VARCHAR(50),
                transaction_type VARCHAR(8),
                expense_category VARCHAR(20),
                income_category VARCHAR(20),
                transfer_category VARCHAR(50),
                classification_source VARCHAR(50),
                recurrence_pattern_id INTEGER,
                source_bank VARCHAR(10),
                CONSTRAINT fk_transactions_recurrence_pattern_id
                    FOREIGN KEY(recurrence_pattern_id)
                    REFERENCES recurrence_patterns (id)
            )
            """
        )

        _ensure_source_columns_for_copy(cursor, transaction_columns)
        cursor.execute(
            """
            INSERT INTO transactions__classification_assistant_migration (
                id,
                import_session_id,
                import_source_locator,
                import_source_description,
                canonical_description_en,
                account_number,
                transaction_date,
                amount,
                currency,
                description,
                counterparty_name,
                counterparty_account,
                transaction_type,
                expense_category,
                income_category,
                transfer_category,
                classification_source,
                recurrence_pattern_id,
                source_bank
            )
            SELECT
                id,
                import_session_id,
                import_source_locator,
                import_source_description,
                canonical_description_en,
                account_number,
                transaction_date,
                amount,
                currency,
                description,
                counterparty_name,
                counterparty_account,
                transaction_type,
                expense_category,
                income_category,
                transfer_category,
                classification_source,
                recurrence_pattern_id,
                source_bank
            FROM transactions
            """
        )
        cursor.execute("DROP TABLE transactions")
        cursor.execute(
            "ALTER TABLE transactions__classification_assistant_migration "
            "RENAME TO transactions"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_transactions_id ON transactions (id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_transactions_account_number "
            "ON transactions (account_number)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_transactions_transaction_date "
            "ON transactions (transaction_date)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_transactions_recurrence_pattern_id "
            "ON transactions (recurrence_pattern_id)"
        )
        raw_connection.commit()
    finally:
        with contextlib.suppress(Exception):
            cursor.execute("PRAGMA foreign_keys=ON")
        raw_connection.close()


def _ensure_source_columns_for_copy(
    cursor: SqlCursor, transaction_columns: set[str]
) -> None:
    for column_name, statement in (
        (
            "transfer_category",
            "ALTER TABLE transactions ADD COLUMN transfer_category VARCHAR(50)",
        ),
        (
            "classification_source",
            "ALTER TABLE transactions ADD COLUMN classification_source VARCHAR(50)",
        ),
        (
            "recurrence_pattern_id",
            "ALTER TABLE transactions ADD COLUMN recurrence_pattern_id INTEGER",
        ),
        (
            "import_session_id",
            "ALTER TABLE transactions ADD COLUMN import_session_id INTEGER",
        ),
        (
            "import_source_locator",
            "ALTER TABLE transactions ADD COLUMN import_source_locator VARCHAR(255)",
        ),
        (
            "import_source_description",
            "ALTER TABLE transactions ADD COLUMN "
            "import_source_description VARCHAR(500)",
        ),
        (
            "canonical_description_en",
            "ALTER TABLE transactions ADD COLUMN canonical_description_en VARCHAR(500)",
        ),
    ):
        if column_name not in transaction_columns:
            cursor.execute(statement)


def migrate_classification_assistant() -> None:
    """Handle migrate classification assistant."""
    logger.info("Starting classification assistant migration...")
    classification_tables = cast(
        "Sequence[Table]",
        [
            ClassificationSession.__table__,
            ClassificationTurn.__table__,
            RecurrencePattern.__table__,
        ],
    )
    Base.metadata.create_all(
        bind=engine,
        tables=classification_tables,
    )
    inspector = inspect(engine)
    transaction_columns = {
        column["name"] for column in inspector.get_columns("transactions")
    }

    needs_rebuild = (
        "transfer_category" not in transaction_columns
        or "classification_source" not in transaction_columns
        or "recurrence_pattern_id" not in transaction_columns
        or not _has_recurrence_pattern_foreign_key()
    )

    if needs_rebuild:
        _rebuild_transactions_table_with_foreign_key(transaction_columns)
    else:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_transactions_recurrence_pattern_id "
                    "ON transactions (recurrence_pattern_id)"
                )
            )
    logger.info("Classification assistant migration completed successfully")


if __name__ == "__main__":
    migrate_classification_assistant()
