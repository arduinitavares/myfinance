"""Module for backend app models fx."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..database import Base


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store datetimes as naive UTC and return aware UTC values."""

    impl = DateTime
    cache_ok: bool = True

    def process_bind_param(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        """Normalize bound datetimes to naive UTC for SQLite storage."""
        _ = dialect
        if value is None:
            return None
        return _as_utc(value).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        """Return stored datetimes as UTC-aware values."""
        _ = dialect
        if value is None:
            return None
        return _as_utc(value)


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


class FXDailyReferenceRate(Base):
    """Represent f x daily reference rate."""

    __tablename__ = "fx_daily_reference_rates"
    __table_args__ = (
        UniqueConstraint(
            "rate_date",
            "base_currency",
            "quoted_currency",
            "source_name",
            name="uq_fx_daily_reference_rates_rate_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    quoted_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    units_per_base: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )
