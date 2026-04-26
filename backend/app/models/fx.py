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

from ..database import Base


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
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
