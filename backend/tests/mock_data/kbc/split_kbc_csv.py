"""Module for backend tests mock_data kbc split_kbc_csv."""

import sys
from pathlib import Path

import pandas as pd

EXPECTED_ARG_COUNT: int = 2


def split_kbc_by_month(input_file: str | Path) -> None:
    # Read the KBC CSV with semicolon delimiter
    """Handle split kbc by month."""
    df = pd.read_csv(input_file, sep=";")
    # Parse Date column and extract year-month
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    df["YearMonth"] = df["Date"].dt.strftime("%Y%m")
    # Determine output directory
    output_dir = Path(input_file).parent
    # Split and save per month
    for ym, group in df.groupby("YearMonth"):
        output_file = output_dir / f"kbc-{ym}.csv"
        group.to_csv(output_file, sep=";", index=False)


if __name__ == "__main__":
    if len(sys.argv) != EXPECTED_ARG_COUNT:
        sys.exit(1)
    split_kbc_by_month(sys.argv[1])
