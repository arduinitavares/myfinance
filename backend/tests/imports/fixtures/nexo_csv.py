"""Module for backend tests imports fixtures nexo_csv."""

import csv
import io
from typing import Any

NEXO_CSV_HEADER: Any = [
    "Transaction",
    "Type",
    "Input Currency",
    "Input Amount",
    "Output Currency",
    "Output Amount",
    "USD Equivalent",
    "Fee",
    "Fee Currency",
    "Details",
    "Date / Time (UTC)",
    "normalizedDisplayDetails",
]
NEXO_ROW_TRAILING_FIELD_COUNT: int = 2


def nexo_row(
    transaction: str,
    row_type: str,
    input_currency: str,
    input_amount: str,
    *details_and_occurred_at: str,
) -> list[str]:
    """Handle nexo row."""
    if len(details_and_occurred_at) != NEXO_ROW_TRAILING_FIELD_COUNT:
        msg = "Nexo rows require details and occurred_at"
        raise ValueError(msg)
    details, occurred_at = details_and_occurred_at
    return [
        transaction,
        row_type,
        input_currency,
        input_amount,
        input_currency,
        input_amount.lstrip("-"),
        "$0.00",
        "-",
        "-",
        details,
        occurred_at,
        details,
    ]


def build_nexo_csv_bytes(*rows: list[str]) -> bytes:
    """Build nexo csv bytes."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(NEXO_CSV_HEADER)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")
