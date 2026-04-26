"""Module for backend app migrations migrate_expense_type."""

import logging
import sys
from pathlib import Path

from sqlalchemy import inspect, text

# Add the parent directory to sys.path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.database import engine, get_db
from app.models.statistics import CategoryStatistics
from app.models.transaction import ExpenseCategory

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger: logging.Logger = logging.getLogger(__name__)


def migrate_expense_type() -> None:
    """Add and populate the category statistics expense_type column."""
    logger.info("Starting expense type migration...")

    # Check if the column already exists
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns("category_statistics")]

    if "expense_type" in columns:
        logger.info(
            "expense_type column already exists in category_statistics table. "
            "Skipping column creation."
        )
    else:
        # Add the column
        logger.info("Adding expense_type column to category_statistics table...")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE category_statistics ADD COLUMN "
                    "expense_type VARCHAR(20)"
                )
            )
        logger.info("expense_type column added successfully.")

    # Update existing expense category records with the appropriate expense type
    logger.info("Updating existing expense category records with expense types...")
    db = next(get_db())

    try:
        # Get all expense category statistics
        expense_stats = (
            db.query(CategoryStatistics)
            .filter(CategoryStatistics.transaction_type == "Expense")
            .all()
        )

        logger.info("Found %s expense category records to update.", len(expense_stats))

        # Update each record with the appropriate expense type
        for stat in expense_stats:
            try:
                # Get the expense category enum from the category name
                category = ExpenseCategory(stat.category_name)
                # Set the expense type
                stat.expense_type = category.expense_type
            except (ValueError, AttributeError) as exc:
                logger.warning(
                    "Could not update expense type for category %s: %s",
                    stat.category_name,
                    exc,
                )
                continue

        # Commit the changes
        db.commit()
        logger.info(
            "Successfully updated expense types for existing category statistics."
        )

    except Exception:
        db.rollback()
        logger.exception("Error updating expense types")
        raise
    finally:
        db.close()

    logger.info("Expense type migration completed successfully.")


if __name__ == "__main__":
    migrate_expense_type()
