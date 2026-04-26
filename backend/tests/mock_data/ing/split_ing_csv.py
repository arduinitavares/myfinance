"""Module for backend tests mock_data ing split_ing_csv."""

import sys
from pathlib import Path

import pandas as pd

EXPECTED_ARG_COUNT: int = 2


def split_ing_by_month(input_file: str | Path) -> None:
    # Read the ING CSV with semicolon delimiter
    """Handle split ing by month."""
    df = pd.read_csv(input_file, sep=";")
    # Parse booking date and extract year-month
    df["Booking date"] = pd.to_datetime(df["Booking date"], format="%d/%m/%Y")
    df["YearMonth"] = df["Booking date"].dt.strftime("%Y%m")
    # Determine output directory
    output_dir = Path(input_file).parent
    # Split and save per month
    for ym, group in df.groupby("YearMonth"):
        output_file = output_dir / f"ing-{ym}.csv"
        group.to_csv(output_file, sep=";", index=False)


if __name__ == "__main__":
    if len(sys.argv) != EXPECTED_ARG_COUNT:
        sys.exit(1)
    split_ing_by_month(sys.argv[1])
