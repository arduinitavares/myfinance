"""Module for backend app services currency_aliases."""

from __future__ import annotations

from typing import Any

CURRENCY_ALIASES: Any = {
    "XUSD": "USD",
    "EURX": "EUR",
    "USDC": "USD",
}


def normalize_currency_code(raw_currency: str | None) -> str | None:
    """Handle normalize currency code."""
    if raw_currency is None:
        return None
    normalized = raw_currency.strip().upper()
    return CURRENCY_ALIASES.get(normalized, normalized)
