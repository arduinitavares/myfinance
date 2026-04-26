"""Module for backend app models financial_health."""

from datetime import date

from sqlalchemy import JSON, Boolean, Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class FinancialHealth(Base):
    """Represent financial health."""

    __tablename__ = "financial_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Overall score (0-100)
    overall_score: Mapped[float] = mapped_column(Float, default=0, nullable=True)

    # Component scores (0-100)
    savings_rate_score: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    expense_ratio_score: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    budget_adherence_score: Mapped[float] = mapped_column(
        Float, default=0, nullable=True
    )
    debt_to_income_score: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    emergency_fund_score: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    spending_stability_score: Mapped[float] = mapped_column(
        Float, default=0, nullable=True
    )
    investment_rate_score: Mapped[float] = mapped_column(
        Float, default=0, nullable=True
    )

    # Raw metrics (for reference)
    savings_rate: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    expense_ratio: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    budget_adherence: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    debt_to_income: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    emergency_fund_months: Mapped[float] = mapped_column(
        Float, default=0, nullable=True
    )
    spending_stability: Mapped[float] = mapped_column(Float, default=0, nullable=True)
    investment_rate: Mapped[float] = mapped_column(Float, default=0, nullable=True)

    # Metadata
    recommendations: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON, nullable=True
    )


class FinancialRecommendation(Base):
    """Represent financial recommendation."""

    __tablename__ = "financial_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    date_created: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    # Recommendation details
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    impact_area: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=True)

    # Tracking
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    date_completed: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Potential impact
    estimated_score_improvement: Mapped[float] = mapped_column(
        Float, default=0, nullable=True
    )
