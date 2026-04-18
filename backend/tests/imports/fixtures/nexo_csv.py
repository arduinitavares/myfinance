import csv
import io


NEXO_CSV_HEADER = [
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


def nexo_row(
    transaction: str,
    row_type: str,
    input_currency: str,
    input_amount: str,
    details: str,
    occurred_at: str,
) -> list[str]:
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
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(NEXO_CSV_HEADER)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")
