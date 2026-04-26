"""Migrate financial statistics fields to the current schema."""

import logging
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import SQLALCHEMY_DATABASE_URL
from app.services.statistics_service import StatisticsService

logging.basicConfig(level=logging.INFO)
logger: Any = logging.getLogger(__name__)


def migrate_statistics_fields() -> None:
    """Migrate statistics table fields.

    Rename period-specific columns, add cumulative fields, and rebuild
    statistics.
    """
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    session_local = sessionmaker(bind=engine)
    db = session_local()

    try:
        # Step 1: Rename existing columns
        logger.info("Renaming existing columns...")
        rename_statements = [
            (
                "ALTER TABLE financial_statistics RENAME COLUMN total_income "
                "TO period_income"
            ),
            (
                "ALTER TABLE financial_statistics RENAME COLUMN total_expenses "
                "TO period_expenses"
            ),
            (
                "ALTER TABLE financial_statistics RENAME COLUMN net_savings "
                "TO period_net_savings"
            ),
        ]

        for statement in rename_statements:
            db.execute(text(statement))
            db.commit()
            logger.info("Executed: %s", statement)

        # Step 2: Add new columns
        logger.info("Adding new columns...")
        add_column_statements = [
            # Add cumulative columns
            (
                "ALTER TABLE financial_statistics ADD COLUMN total_income "
                "NUMERIC(15,2) DEFAULT 0.00"
            ),
            (
                "ALTER TABLE financial_statistics ADD COLUMN total_expenses "
                "NUMERIC(15,2) DEFAULT 0.00"
            ),
            (
                "ALTER TABLE financial_statistics ADD COLUMN total_net_savings "
                "NUMERIC(15,2) DEFAULT 0.00"
            ),
            # Add transaction count columns
            (
                "ALTER TABLE financial_statistics ADD COLUMN expense_count "
                "INTEGER DEFAULT 0"
            ),
            # Add average columns
            (
                "ALTER TABLE financial_statistics ADD COLUMN average_income "
                "NUMERIC(15,2) DEFAULT 0.00"
            ),
            (
                "ALTER TABLE financial_statistics ADD COLUMN average_expense "
                "NUMERIC(15,2) DEFAULT 0.00"
            ),
        ]

        for statement in add_column_statements:
            db.execute(text(statement))
            db.commit()
            logger.info("Executed: %s", statement)

        logger.info("Successfully updated table structure")

        # Step 3: Recalculate all statistics
        logger.info("Recalculating statistics...")
        StatisticsService.initialize_statistics(db)
        logger.info("Successfully recalculated statistics")

    except Exception:
        db.rollback()
        logger.exception("Error during migration")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_statistics_fields()
