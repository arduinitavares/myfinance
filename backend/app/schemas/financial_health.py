"""Module for backend app schemas financial_health."""

from datetime import date
from typing import Any

from pydantic import BaseModel


class FinancialHealthBase(BaseModel):
    """Represent financial health base."""

    date: date
    overall_score: float
    savings_rate_score: float
    expense_ratio_score: float
    budget_adherence_score: float
    debt_to_income_score: float
    emergency_fund_score: float
    spending_stability_score: float
    investment_rate_score: float

    # Raw metrics
    savings_rate: float
    expense_ratio: float
    budget_adherence: float
    debt_to_income: float
    emergency_fund_months: float
    spending_stability: float
    investment_rate: float

    # Recommendations
    recommendations: list[dict[str, Any]] | None = None


class FinancialHealthCreate(FinancialHealthBase):
    """Represent financial health create."""



class FinancialHealth(FinancialHealthBase):
    """Represent financial health."""

    id: int

    class Config:
        """Represent config."""

        orm_mode = True


class FinancialHealthHistory(BaseModel):
    """Represent financial health history."""

    dates: list[date]
    overall_scores: list[float]
    savings_rate_scores: list[float]
    expense_ratio_scores: list[float]
    budget_adherence_scores: list[float]
    debt_to_income_scores: list[float]
    emergency_fund_scores: list[float]
    spending_stability_scores: list[float]
    investment_rate_scores: list[float]


class RecommendationBase(BaseModel):
    """Represent recommendation base."""

    title: str
    description: str
    category: str
    impact_area: str
    priority: int
    estimated_score_improvement: float


class RecommendationCreate(RecommendationBase):
    """Represent recommendation create."""



class Recommendation(RecommendationBase):
    """Represent recommendation."""

    id: int
    date_created: date
    is_completed: bool
    date_completed: date | None = None

    class Config:
        """Represent config."""

        orm_mode = True


class RecommendationUpdate(BaseModel):
    """Represent recommendation update."""

    is_completed: bool
    date_completed: date | None = None
