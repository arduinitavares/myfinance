from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from .contracts import RawEvidence

CSV_CHARSETS = ("utf-8-sig", "utf-8", "latin-1")
HEADER_SCAN_LIMIT = 20

BELFIUS_HEADER = [
    "Rekening",
    "Boekingsdatum",
    "Rekeninguittrekselnummer",
    "Transactienummer",
    "Rekening tegenpartij",
    "Naam tegenpartij bevat",
    "Straat en nummer",
    "Postcode en plaats",
    "Transactie",
    "Valutadatum",
    "Bedrag",
    "Devies",
    "BIC",
    "Landcode",
    "Mededelingen",
]

BEOBANK_COMPACT_HEADER = [
    "Datum",
    "Waardedatum",
    "Debet",
    "Krediet",
    "Omschrijving",
    "Saldo",
]

BEOBANK_DEBIT_CREDIT_HEADER = [
    "Date",
    "Debit",
    "Credit",
    "Message",
    "Balance",
]

NEXO_HEADER = [
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


def _normalize_encoding_name(encoding: str) -> str:
    if encoding == "utf-8-sig":
        return "utf-8"
    return encoding


def decode_csv_bytes(payload: bytes) -> tuple[str, str]:
    for encoding in CSV_CHARSETS:
        try:
            return payload.decode(encoding), _normalize_encoding_name(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="replace"), "latin-1"


def read_csv_text(file_path: str | Path) -> tuple[str, str]:
    payload = Path(file_path).read_bytes()
    return decode_csv_bytes(payload)


def normalize_header_cells(cells: Sequence[str]) -> list[str]:
    return [cell.strip().strip('"') for cell in cells]


def find_header_row(
    lines: Sequence[str],
    *,
    delimiter: str,
    expected_header: Sequence[str],
    max_lines: int = HEADER_SCAN_LIMIT,
) -> tuple[int, list[str]] | None:
    for index, line in enumerate(lines[:max_lines]):
        cells = normalize_header_cells(next(csv.reader([line], delimiter=delimiter)))
        if cells == list(expected_header):
            return index, cells
    return None


def build_dict_rows(
    lines: Sequence[str],
    *,
    delimiter: str,
    header_row_index: int,
) -> list[tuple[int, dict[str, str]]]:
    reader = csv.DictReader(lines[header_row_index:], delimiter=delimiter)
    return [
        (
            header_row_index + 2 + offset,
            {key.strip(): (value or "").strip() for key, value in row.items() if key is not None},
        )
        for offset, row in enumerate(reader)
    ]


def build_csv_raw_evidence(
    *,
    raw_text: str,
    snippets: Iterable[dict],
) -> RawEvidence:
    return RawEvidence(
        text_blocks=[
            {
                "page_number": 1,
                "raw_text": raw_text,
                "lines": raw_text.splitlines(),
            }
        ],
        ocr_blocks=[],
        snippets=list(snippets),
    )

