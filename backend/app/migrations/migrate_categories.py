"""Module for backend app migrations migrate_categories."""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import SQLALCHEMY_DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


def migrate_categories() -> None:
    """
    Migrate existing categories.

    - Merge 'HEALTHCARE' and 'CLOTHING' into 'PERSONAL'
    - Split 'FOOD' into 'GROCERIES' (default) and 'EATING_OUT'.
    """
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    try:
        # Use raw SQL updates to bypass enum validation
        logger.info("Updating HEALTHCARE and CLOTHING categories to PERSONAL...")
        db.execute(
            text("""
            UPDATE transactions
            SET expense_category = 'PERSONAL'
            WHERE expense_category IN ('HEALTHCARE', 'CLOTHING')
        """)
        )

        logger.info("Updating FOOD category to GROCERIES...")
        db.execute(
            text("""
            UPDATE transactions
            SET expense_category = 'GROCERIES'
            WHERE expense_category = 'FOOD'
        """)
        )

        db.commit()
        logger.info("Successfully migrated categories")

    except Exception:
        db.rollback()
        logger.exception("Error during migration")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_categories()
