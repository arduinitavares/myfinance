"""Module for backend app services reporting_currency."""

from typing import Any

from fastapi import Header, HTTPException

ALLOWED_REPORTING_CURRENCIES: Any = ["EUR", "USD", "BRL"]
REPORTING_CURRENCY_HEADER: Any = "X-Reporting-Currency"
DEFAULT_REPORTING_CURRENCY: Any = "EUR"


def get_reporting_currency(
    x_reporting_currency: str | None = Header(
        default=None, alias=REPORTING_CURRENCY_HEADER
    ),
) -> str:
    """Return reporting currency."""
    if x_reporting_currency is None:
        return DEFAULT_REPORTING_CURRENCY

    normalized_currency = x_reporting_currency.strip().upper()
    if normalized_currency not in ALLOWED_REPORTING_CURRENCIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_reporting_currency",
                "allowed": ALLOWED_REPORTING_CURRENCIES,
            },
        )

    return normalized_currency
