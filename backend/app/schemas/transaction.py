from pydantic import BaseModel, root_validator, validator
from datetime import date
from typing import Optional, Literal
from enum import Enum
from ..models.transaction import ExpenseCategory, IncomeCategory, TransactionType, TransferCategory

class TransactionBase(BaseModel):
    account_number: str
    transaction_date: date
    amount: float
    currency: str
    description: str
    counterparty_name: Optional[str] = None
    counterparty_account: Optional[str] = None
    transaction_type: Optional[TransactionType] = None
    expense_category: Optional[ExpenseCategory] = None
    income_category: Optional[IncomeCategory] = None
    transfer_category: Optional[TransferCategory] = None
    classification_source: Optional[str] = None
    recurrence_pattern_id: Optional[int] = None
    source_bank: str

    @root_validator(pre=True)
    def set_transaction_type(cls, values):
        if values.get("transaction_type") is not None:
            return values

        if values.get("transfer_category") is not None:
            values["transaction_type"] = TransactionType.TRANSFER
            return values

        amount = values.get("amount")
        if amount is not None:
            values["transaction_type"] = (
                TransactionType.EXPENSE if float(amount) < 0 else TransactionType.INCOME
            )
        return values

    @validator('expense_category', pre=True)
    def validate_expense_category(cls, v, values):
        if not v:
            return None
        if values.get('transaction_type') == TransactionType.EXPENSE:
            return ExpenseCategory(v)
        return None

    @validator('income_category', pre=True)
    def validate_income_category(cls, v, values):
        if not v:
            return None
        if values.get('transaction_type') == TransactionType.INCOME:
            return IncomeCategory(v)
        return None

    @validator('transfer_category', pre=True)
    def validate_transfer_category(cls, v, values):
        if not v:
            return None
        if values.get('transaction_type') == TransactionType.TRANSFER:
            return TransferCategory(v)
        return None


class TransactionCreate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: int

    class Config:
        orm_mode = True
        
class TransactionRestore(TransactionBase):
    id: Optional[int] = None

    class Config:
        orm_mode = True

class TransactionPage(BaseModel):
    items: list[Transaction]
    total: int
    page: int
    page_size: int
    total_pages: int

    class Config:
        orm_mode = True


class TimePeriod(str, Enum):
    """Represents relative time periods for filtering data."""
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    YEAR_TO_DATE = "YTD"
    ONE_YEAR = "1Y"
    TWO_YEARS = "2Y"
    ALL_TIME = "ALL_TIME"
