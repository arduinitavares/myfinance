"""Module for backend app migrations migrate_statistics_periods."""

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database import SQLALCHEMY_DATABASE_URL
from app.services.statistics_service import StatisticsService

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


def migrate_statistics_periods() -> None:
    """
    Update statistics_period enum values and rebuild statistics.

    - Remove daily stats
    - Add yearly stats
    - Rebuild statistics for all transactions.
    """
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    try:
        # Step 1: Delete all daily statistics
        logger.info("Removing daily statistics...")
        db.execute(text("DELETE FROM financial_statistics WHERE period = 'daily'"))
        db.execute(text("DELETE FROM category_statistics WHERE period = 'daily'"))
        db.commit()
        logger.info("Successfully removed daily statistics")

        # Step 2: Add yearly_income and yearly_expenses columns if they don't exist
        logger.info("Ensuring yearly columns exist...")
        inspector = inspect(engine)
        existing_columns = {
            column["name"] for column in inspector.get_columns("financial_statistics")
        }

        yearly_column_statements = [
            statement
            for column_name, statement in (
                (
                    "yearly_income",
                    "ALTER TABLE financial_statistics ADD COLUMN "
                    "yearly_income NUMERIC(15,2) DEFAULT 0.00",
                ),
                (
                    "yearly_expenses",
                    "ALTER TABLE financial_statistics ADD COLUMN "
                    "yearly_expenses NUMERIC(15,2) DEFAULT 0.00",
                ),
            )
            if column_name not in existing_columns
        ]

        if yearly_column_statements:
            for statement in yearly_column_statements:
                db.execute(text(statement))
                logger.info("Executed: %s", statement)
            db.commit()
            logger.info("Added missing yearly columns")
        else:
            logger.info("Yearly columns already exist; no table changes needed")

        # Step 3: Recalculate all statistics with the new period structure
        logger.info("Recalculating all statistics...")
        StatisticsService.initialize_statistics(db)
        logger.info("Recalculated financial statistics")

        StatisticsService.initialize_category_statistics(db)
        logger.info("Recalculated category statistics")

        logger.info("Migration completed successfully")

    except Exception:
        db.rollback()
        logger.exception("Error during migration")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_statistics_periods()
