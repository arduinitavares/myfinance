import logging
import os
import sys

from sqlalchemy import inspect, text


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import Base, engine
from app.models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def migrate_classification_assistant():
    logger.info("Starting classification assistant migration...")
    inspector = inspect(engine)
    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}

    with engine.begin() as conn:
        if "classification_source" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN classification_source VARCHAR(50)"))
            logger.info("Added transactions.classification_source column")
        if "recurrence_pattern_id" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN recurrence_pattern_id INTEGER"))
            logger.info("Added transactions.recurrence_pattern_id column")
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_transactions_recurrence_pattern_id "
                "ON transactions (recurrence_pattern_id)"
            )
        )

    Base.metadata.create_all(
        bind=engine,
        tables=[
            ClassificationSession.__table__,
            ClassificationTurn.__table__,
            RecurrencePattern.__table__,
        ],
    )
    logger.info("Classification assistant migration completed successfully")


if __name__ == "__main__":
    migrate_classification_assistant()
