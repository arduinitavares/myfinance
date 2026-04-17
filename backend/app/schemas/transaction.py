from datetime import date
from typing import Any, Optional, Literal
from enum import Enum
from pydantic import BaseModel, root_validator, validator

from ..services.currency_conversion import DisplayMoney
from ..models.transaction import ExpenseCategory, IncomeCategory, TransactionType, TransferCategory


def _matches_enum_value(value, enum_member):
    return value == enum_member or value == enum_member.value

def _coerce_values(values, field_names):
    if isinstance(values, dict):
        return dict(values)
    return {field_name: getattr(values, field_name, None) for field_name in field_names}

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
        values = _coerce_values(values, cls.model_fields.keys())
        transaction_type = values.get("transaction_type")

        if _matches_enum_value(transaction_type, TransactionType.TRANSFER):
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
    import_session_id: Optional[int] = None
    import_source_locator: Optional[str] = None
    import_source_description: Optional[str] = None
    canonical_description_en: Optional[str] = None
    display_amount: Optional[float] = None
    display_currency: Optional[str] = None
    display_fx_rate: Optional[float] = None
    display_rate_date: Optional[date] = None

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


def serialize_display_money(display_money: DisplayMoney) -> dict[str, Any]:
    return {
        "display_amount": display_money.display_amount,
        "display_currency": display_money.display_currency,
        "display_fx_rate": display_money.display_fx_rate,
        "display_rate_date": display_money.display_rate_date,
    }


def build_transaction_response_payload(transaction: Any, display_money: DisplayMoney) -> dict[str, Any]:
    payload = Transaction.model_validate(transaction, from_attributes=True).model_dump()
    payload.update(serialize_display_money(display_money))
    return payload
