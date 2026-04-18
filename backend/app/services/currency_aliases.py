from __future__ import annotations


CURRENCY_ALIASES = {
    "XUSD": "USD",
    "EURX": "EUR",
    "USDC": "USD",
}


def normalize_currency_code(raw_currency: str | None) -> str | None:
    if raw_currency is None:
        return None
    normalized = raw_currency.strip().upper()
    return CURRENCY_ALIASES.get(normalized, normalized)
