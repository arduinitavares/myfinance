"""Module for backend app services fx_pairs."""

from __future__ import annotations


def required_fx_quotes(
    *,
    raw_currency: str,
    reporting_currency: str,
    base_currency: str,
) -> tuple[str, ...]:
    """Handle required fx quotes."""
    if raw_currency == reporting_currency:
        return ()
    if raw_currency == base_currency:
        return (reporting_currency,)
    if reporting_currency == base_currency:
        return (raw_currency,)
    return tuple(sorted({raw_currency, reporting_currency}))
