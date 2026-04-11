import logging
import os
import sys

from sqlalchemy import inspect, text


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import Base, engine
from app.models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


TRANSACTIONS_MIGRATION_TABLE = "transactions__classification_assistant_migration"


def _has_recurrence_pattern_foreign_key() -> bool:
    inspector = inspect(engine)
    for foreign_key in inspector.get_foreign_keys("transactions"):
        constrained_columns = foreign_key.get("constrained_columns") or []
        if constrained_columns == ["recurrence_pattern_id"] and foreign_key.get("referred_table") == "recurrence_patterns":
            return True
    return False


def _rebuild_transactions_table_with_foreign_key(transaction_columns: set[str]) -> None:
    logger.info("Rebuilding transactions table to add recurrence_pattern_id foreign key")
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute(f"DROP TABLE IF EXISTS {TRANSACTIONS_MIGRATION_TABLE}")
        cursor.execute(
            f"""
            CREATE TABLE {TRANSACTIONS_MIGRATION_TABLE} (
                id INTEGER NOT NULL PRIMARY KEY,
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
                classification_source VARCHAR(50),
                recurrence_pattern_id INTEGER,
                source_bank VARCHAR(10),
                CONSTRAINT fk_transactions_recurrence_pattern_id
                    FOREIGN KEY(recurrence_pattern_id) REFERENCES recurrence_patterns (id)
            )
            """
        )

        classification_source_sql = "classification_source" if "classification_source" in transaction_columns else "NULL"
        recurrence_pattern_id_sql = "recurrence_pattern_id" if "recurrence_pattern_id" in transaction_columns else "NULL"
        cursor.execute(
            f"""
            INSERT INTO {TRANSACTIONS_MIGRATION_TABLE} (
                id,
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
                classification_source,
                recurrence_pattern_id,
                source_bank
            )
            SELECT
                id,
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
                {classification_source_sql},
                {recurrence_pattern_id_sql},
                source_bank
            FROM transactions
            """
        )
        cursor.execute("DROP TABLE transactions")
        cursor.execute(f"ALTER TABLE {TRANSACTIONS_MIGRATION_TABLE} RENAME TO transactions")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_transactions_id ON transactions (id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_transactions_account_number ON transactions (account_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_transactions_transaction_date ON transactions (transaction_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_transactions_recurrence_pattern_id ON transactions (recurrence_pattern_id)")
        raw_connection.commit()
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        raw_connection.close()


def migrate_classification_assistant():
    logger.info("Starting classification assistant migration...")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            ClassificationSession.__table__,
            ClassificationTurn.__table__,
            RecurrencePattern.__table__,
        ],
    )
    inspector = inspect(engine)
    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}

    needs_rebuild = (
        "classification_source" not in transaction_columns
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
