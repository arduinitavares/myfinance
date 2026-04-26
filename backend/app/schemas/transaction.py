"""Module for backend app schemas transaction."""

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from enum import Enum, StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ..models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    TransactionType,
    TransferCategory,
)
from ..models.transaction import (
    Transaction as TransactionModel,
)
from ..services.currency_conversion import CurrencyConversionService, DisplayMoney


def _matches_enum_value(value: object, enum_member: Enum) -> bool:
    return value in (enum_member, enum_member.value)


def _coerce_values(values: object, field_names: Iterable[str]) -> dict[str, object]:
    if isinstance(values, Mapping):
        return {str(key): value for key, value in values.items()}
    return {field_name: getattr(values, field_name, None) for field_name in field_names}


def _amount_as_float(value: object) -> float:
    if isinstance(value, str | int | float):
        return float(value)
    msg = f"Unsupported transaction amount value: {value!r}"
    raise TypeError(msg)


def _decimal_as_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


class TransactionBase(BaseModel):
    """Represent transaction base."""

    account_number: str
    transaction_date: date
    amount: float
    currency: str
    description: str
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    transaction_type: TransactionType | None = None
    expense_category: ExpenseCategory | None = None
    income_category: IncomeCategory | None = None
    transfer_category: TransferCategory | None = None
    classification_source: str | None = None
    recurrence_pattern_id: int | None = None
    source_bank: str

    @model_validator(mode="before")
    @classmethod
    def set_transaction_type(cls, values: object) -> dict[str, object]:
        """Handle set transaction type."""
        coerced_values = _coerce_values(values, cls.model_fields.keys())
        transaction_type = coerced_values.get("transaction_type")

        if _matches_enum_value(transaction_type, TransactionType.TRANSFER):
            return coerced_values

        if coerced_values.get("transfer_category") is not None:
            coerced_values["transaction_type"] = TransactionType.TRANSFER
            return coerced_values

        amount = coerced_values.get("amount")
        if amount is not None:
            coerced_values["transaction_type"] = (
                TransactionType.EXPENSE
                if _amount_as_float(amount) < 0
                else TransactionType.INCOME
            )
        return coerced_values

    @field_validator("expense_category")
    @classmethod
    def validate_expense_category(
        cls, value: ExpenseCategory | None, info: ValidationInfo
    ) -> ExpenseCategory | None:
        """Handle validate expense category."""
        if value is None:
            return None
        if info.data.get("transaction_type") == TransactionType.EXPENSE:
            return value
        return None

    @field_validator("income_category")
    @classmethod
    def validate_income_category(
        cls, value: IncomeCategory | None, info: ValidationInfo
    ) -> IncomeCategory | None:
        """Handle validate income category."""
        if value is None:
            return None
        if info.data.get("transaction_type") == TransactionType.INCOME:
            return value
        return None

    @field_validator("transfer_category")
    @classmethod
    def validate_transfer_category(
        cls, value: TransferCategory | None, info: ValidationInfo
    ) -> TransferCategory | None:
        """Handle validate transfer category."""
        if value is None:
            return None
        if info.data.get("transaction_type") == TransactionType.TRANSFER:
            return value
        return None


class TransactionCreate(TransactionBase):
    """Represent transaction create."""


class Transaction(TransactionBase):
    """Represent transaction."""

    id: int
    import_session_id: int | None = None
    import_source_locator: str | None = None
    import_source_description: str | None = None
    canonical_description_en: str | None = None
    display_amount: float | None = None
    display_currency: str | None = None
    display_fx_rate: float | None = None
    display_rate_date: date | None = None
    display_is_available: bool | None = None
    display_unavailable_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionRestore(TransactionBase):
    """Represent transaction restore."""

    id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionPage(BaseModel):
    """Represent transaction page."""

    items: list[Transaction]
    total: int
    page: int
    page_size: int
    total_pages: int

    model_config = ConfigDict(from_attributes=True)


class TimePeriod(StrEnum):
    """Represents relative time periods for filtering data."""

    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    YEAR_TO_DATE = "YTD"
    ONE_YEAR = "1Y"
    TWO_YEARS = "2Y"
    ALL_TIME = "ALL_TIME"


def serialize_display_money(display_money: DisplayMoney) -> dict[str, object]:
    """Handle serialize display money."""
    return {
        "display_amount": _decimal_as_float(display_money.display_amount),
        "display_currency": display_money.display_currency,
        "display_fx_rate": _decimal_as_float(display_money.display_fx_rate),
        "display_rate_date": display_money.display_rate_date,
        "display_is_available": display_money.is_available,
        "display_unavailable_reason": display_money.unavailable_reason,
    }


def build_transaction_response_payload(
    transaction: TransactionModel,
    display_money: DisplayMoney,
) -> dict[str, object]:
    """Build transaction response payload."""
    payload = Transaction.model_validate(transaction, from_attributes=True).model_dump()
    payload.update(serialize_display_money(display_money))
    return payload


def build_transaction_response_payload_for_reporting_currency(
    transaction: TransactionModel,
    *,
    conversion_service: CurrencyConversionService,
    reporting_currency: str,
) -> dict[str, object]:
    """Build transaction response payload for reporting currency."""
    display_money = conversion_service.convert(
        raw_amount=transaction.amount,
        raw_currency=transaction.currency,
        reporting_currency=reporting_currency,
        transaction_date=transaction.transaction_date,
    )
    return build_transaction_response_payload(transaction, display_money)
