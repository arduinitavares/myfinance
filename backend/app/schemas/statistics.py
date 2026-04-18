from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from datetime import date
from enum import Enum
from ..models.transaction import TransactionType, ExpenseType
from ..models.statistics import StatisticsPeriod

# Models for get_statistics_timeseries
class FinancialStatisticsResponse(BaseModel):
    id: int
    period: str
    date: Optional[str] = None
    
    # Period-specific metrics
    period_income: float
    period_expenses: float
    period_net_savings: float
    savings_rate: float
    
    # Cumulative metrics
    total_income: float
    total_expenses: float
    total_net_savings: float
    
    # Transaction counts
    income_count: int
    expense_count: int
    
    # Averages
    average_income: float
    average_expense: float
    
    # Yearly metrics
    yearly_income: float
    yearly_expenses: float
    
    model_config = {
        "from_attributes": True
    }

# Models for get_category_statistics_timeseries
class ConversionSummaryResponse(BaseModel):
    converted_transaction_count: int
    unavailable_transaction_count: int
    unavailable_currencies: List[str]


class CategoryStatisticsResponse(BaseModel):
    category: Optional[str] = None
    category_name: Optional[str] = None
    period: str
    date: Optional[str] = None
    
    # Category identification
    transaction_type: str
    expense_type: Optional[str] = None
    
    # Period-specific metrics
    period_amount: float
    period_transaction_count: int
    period_percentage: float
    
    # Cumulative metrics
    total_amount: float
    transaction_count: Optional[int] = None
    total_amount_cumulative: Optional[float] = None
    total_transaction_count: int
    
    # Averages
    average_transaction_amount: float
    
    # Yearly metrics
    yearly_amount: float
    yearly_transaction_count: int
    
    model_config = {
        "from_attributes": True
    }


class CategoryStatisticsListResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[CategoryStatisticsResponse]

# Models for get_expense_type_statistics_timeseries
class ExpenseTypeTimeseriesItem(BaseModel):
    date: str = Field(..., description="Date in ISO format (YYYY-MM-DD)")
    expense_type: str = Field(..., description="Either 'essential' or 'discretionary'")
    period_amount: float = Field(..., description="Total amount for this expense type in the time period")
    period_transaction_count: int = Field(..., description="Number of transactions for this expense type in the time period")

class ExpenseTypeStatisticsCategoryItem(BaseModel):
    category: str
    period_amount: float
    period_transaction_count: int
    period_percentage: float

class ExpenseTypeStatisticsItem(BaseModel):
    expense_type: str
    period: str
    date: Optional[str] = None
    period_amount: float
    period_transaction_count: int
    period_percentage: float
    total_amount: float
    transaction_count: int
    total_amount_cumulative: float
    total_transaction_count: int
    average_transaction_amount: float
    yearly_amount: float
    yearly_transaction_count: int
    categories: List[ExpenseTypeStatisticsCategoryItem]

class ExpenseTypeStatisticsResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[ExpenseTypeStatisticsItem]


class ExpenseTypeTimeseriesResponse(BaseModel):
    reporting_currency: str
    conversion_summary: "ConversionSummaryResponse"
    items: List[ExpenseTypeTimeseriesItem]

# Models for get_category_averages
class CategoryAverageItem(BaseModel):
    category_name: str = Field(..., description="Category name")
    transaction_type: str = Field(..., description="Transaction type (EXPENSE or INCOME)")
    expense_type: Optional[str] = Field(None, description="Expense type (Essential or Discretionary) for expenses")
    average_amount: float = Field(..., description="Average monthly amount for this category in the time period")
    total_amount: float = Field(..., description="Total amount for this category in the time period")
    transaction_count: int = Field(..., description="Number of transactions for this category in the time period")
    average_transaction_amount: float = Field(..., description="Average amount per transaction")
    percentage: float = Field(..., description="Percentage of total expenses/income")

class CategoryAveragesResponse(BaseModel):
    reporting_currency: str = Field(..., description="Reporting currency used for category totals")
    conversion_summary: ConversionSummaryResponse = Field(..., description="Conversion coverage for the returned period")
    start_date: str = Field(..., description="Start date of the period")
    end_date: str = Field(..., description="End date of the period")
    months_count: int = Field(..., description="Number of months in the period")
    categories: List[CategoryAverageItem] = Field(..., description="List of category averages")


class StatisticsOverviewItemResponse(BaseModel):
    period: str = Field(..., description="Statistics period identifier")
    date: Optional[str] = Field(None, description="Anchor date in ISO format (YYYY-MM-DD)")
    reporting_currency: str = Field(..., description="Reporting currency used for monetary fields")
    conversion_summary: ConversionSummaryResponse = Field(..., description="Conversion coverage for the item window")
    period_income: float = Field(..., description="Income total for the selected period")
    period_expenses: float = Field(..., description="Expense total for the selected period")
    period_net_savings: float = Field(..., description="Net savings for the selected period")
    savings_rate: float = Field(..., description="Savings rate percentage for the selected period")
    total_income: float = Field(..., description="Cumulative income total")
    total_expenses: float = Field(..., description="Cumulative expense total")
    total_net_savings: float = Field(..., description="Cumulative net savings total")
    income_count: int = Field(..., description="Income transaction count")
    expense_count: int = Field(..., description="Expense transaction count")
    average_income: float = Field(..., description="Average income amount")
    average_expense: float = Field(..., description="Average expense amount")
    yearly_income: float = Field(..., description="Income total for the current year window")
    yearly_expenses: float = Field(..., description="Expense total for the current year window")


class StatisticsOverviewResponse(BaseModel):
    current_month: StatisticsOverviewItemResponse
    last_month: StatisticsOverviewItemResponse
    previous_year_last_month: Optional[StatisticsOverviewItemResponse] = None
    all_time: StatisticsOverviewItemResponse


class TransferSummaryItem(BaseModel):
    subtype: str = Field(..., description="Transfer category name")
    transaction_count: int = Field(..., description="Number of transfer transactions")
    total_outgoing: float = Field(..., description="Total outgoing transfer amount in the reporting currency")
    total_incoming: float = Field(..., description="Total incoming transfer amount in the reporting currency")


class TransferSummaryResponse(BaseModel):
    start_date: str = Field(..., description="Start date of the summary window")
    end_date: str = Field(..., description="End date of the summary window")
    reporting_currency: str = Field(..., description="Reporting currency used for transfer totals")
    conversion_summary: ConversionSummaryResponse = Field(..., description="Conversion coverage for the summary window")
    items: List[TransferSummaryItem] = Field(..., description="Transfer totals grouped by subtype")


class FinancialStatisticsTimeseriesItemResponse(BaseModel):
    period: str
    date: str | None = None
    period_income: float
    period_expenses: float
    period_net_savings: float
    savings_rate: float
    total_income: float
    total_expenses: float
    total_net_savings: float
    income_count: int
    expense_count: int
    average_income: float
    average_expense: float
    yearly_income: float
    yearly_expenses: float


class FinancialStatisticsTimeseriesResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[FinancialStatisticsTimeseriesItemResponse]


class CategoryTimeseriesResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[CategoryStatisticsResponse]
