from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint

from ..database import Base


class FXDailyReferenceRate(Base):
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

    id = Column(Integer, primary_key=True, index=True)
    rate_date = Column(Date, nullable=False, index=True)
    base_currency = Column(String(3), nullable=False, index=True)
    quoted_currency = Column(String(3), nullable=False, index=True)
    units_per_base = Column(Numeric(18, 8), nullable=False)
    source_name = Column(String(50), nullable=False, index=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
