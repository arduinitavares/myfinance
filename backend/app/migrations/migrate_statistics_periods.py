import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database import SQLALCHEMY_DATABASE_URL
from app.services.statistics_service import StatisticsService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_statistics_periods():
    """
    Migration to update the statistics_period enum from (daily, monthly, all_time) to (monthly, yearly, all_time)
    - Remove daily stats
    - Add yearly stats
    - Rebuild statistics for all transactions
    """
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

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

        yearly_column_definitions = {
            "yearly_income": "NUMERIC(15,2) DEFAULT 0.00",
            "yearly_expenses": "NUMERIC(15,2) DEFAULT 0.00",
        }

        yearly_column_statements = [
            f"ALTER TABLE financial_statistics ADD COLUMN {column_name} {column_definition}"
            for column_name, column_definition in yearly_column_definitions.items()
            if column_name not in existing_columns
        ]

        if yearly_column_statements:
            for statement in yearly_column_statements:
                db.execute(text(statement))
                logger.info(f"Executed: {statement}")
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

    except Exception as e:
        db.rollback()
        logger.error(f"Error during migration: {e!s}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_statistics_periods()
