"""Module for backend app database."""

import logging
import sqlite3
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger: logging.Logger = logging.getLogger(__name__)

DATABASE_PATH: str = str(settings.database_path)
SQLALCHEMY_DATABASE_URL: str = f"sqlite:///{DATABASE_PATH}"

logger.info("Database path: %s", DATABASE_PATH)

engine: Engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


def enable_sqlite_foreign_keys(
    dbapi_connection: sqlite3.Connection, _connection_record: object
) -> None:
    """Handle enable sqlite foreign keys."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


event.listen(engine, "connect", enable_sqlite_foreign_keys)

SessionLocal: sessionmaker[Session] = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)


class Base(DeclarativeBase):
    """Base class for ORM models."""


def get_db() -> Iterator[Session]:
    """Return db."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
