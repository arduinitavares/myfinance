"""Module for backend app models statistics."""

import enum
from datetime import date

from sqlalchemy import Date, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .transaction import ExpenseType, TransactionType


class StatisticsPeriod(enum.Enum):
    """Represent statistics period."""

    MONTHLY = "monthly"
    YEARLY = "yearly"
    ALL_TIME = "all_time"


class FinancialStatistics(Base):
    """Represent financial statistics."""

    __tablename__ = "financial_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    period: Mapped[StatisticsPeriod] = mapped_column(
        Enum(StatisticsPeriod), nullable=False
    )
    date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Period-specific metrics
    period_income: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    period_expenses: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    period_net_savings: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    savings_rate: Mapped[float] = mapped_column(Float, default=0, nullable=True)

    # Cumulative metrics
    total_income: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    total_expenses: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    total_net_savings: Mapped[float] = mapped_column(Float, default=0, nullable=True)

    # Transaction counts
    income_count: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    expense_count: Mapped[int] = mapped_column(Integer, default=0, nullable=True)

    # Averages (can be calculated from other fields)
    average_income: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    average_expense: Mapped[float] = mapped_column(Float, default=0, nullable=True)

    # New: Yearly metrics
    yearly_income: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    yearly_expenses: Mapped[float] = mapped_column(Float, default=0, nullable=True)


class CategoryStatistics(Base):
    """Represent category statistics."""

    __tablename__ = "category_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    period: Mapped[StatisticsPeriod] = mapped_column(
        Enum(StatisticsPeriod), nullable=False
    )
    date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Category identification
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False
    )
    expense_type: Mapped[ExpenseType | None] = mapped_column(
        Enum(ExpenseType), nullable=True
    )  # Essential or Discretionary (null for income)

    # Period-specific metrics
    period_amount: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    period_transaction_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=True
    )
    period_percentage: Mapped[float] = mapped_column(Float, default=0, nullable=True)

    # Cumulative metrics
    total_amount: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    total_transaction_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=True
    )

    # Averages
    average_transaction_amount: Mapped[float] = mapped_column(
        Float, default=0, nullable=True
    )

    # Yearly metrics
    yearly_amount: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    yearly_transaction_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=True
    )

    # Unique constraint
    __table_args__ = (
        # unique constraint for category, transaction_type, period, and date
        {"sqlite_autoincrement": True},
    )
