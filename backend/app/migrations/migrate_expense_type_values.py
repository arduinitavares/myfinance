"""Migration to update expense_type enum values in category_statistics table.

Old values:
- ESSENTIAL -> FIXED_ESSENTIAL
- DISCRETIONARY -> GUILT_FREE_DISCRETIONARY

This migration also adds support for new expense types:
- SAVINGS_INVESTMENT
- NEUTRAL
"""

import logging
import sys
from pathlib import Path

from sqlalchemy import text

# Add the parent directory to sys.path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.database import engine

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger: logging.Logger = logging.getLogger(__name__)


def migrate_expense_type_values() -> None:
    """
    Update expense_type enum values in category_statistics.

    Mapping:
    - ESSENTIAL -> FIXED_ESSENTIAL
    - DISCRETIONARY -> GUILT_FREE_DISCRETIONARY
    """
    logger.info("Starting expense type values migration...")

    # Define the mapping from old to new values
    value_mappings = [
        ("ESSENTIAL", "FIXED_ESSENTIAL"),
        ("DISCRETIONARY", "GUILT_FREE_DISCRETIONARY"),
    ]

    with engine.begin() as conn:
        for old_value, new_value in value_mappings:
            # Update the expense_type column values
            result = conn.execute(
                text(
                    "UPDATE category_statistics SET expense_type = :new_value "
                    "WHERE expense_type = :old_value"
                ),
                {"old_value": old_value, "new_value": new_value},
            )

            logger.info(
                "Updated %s rows from %r to %r",
                result.rowcount,
                old_value,
                new_value,
            )

    logger.info("Expense type values migration completed successfully.")


if __name__ == "__main__":
    migrate_expense_type_values()
