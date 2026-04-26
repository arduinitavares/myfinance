"""Module for backend app imports beobank_csv."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .contracts import ExtractedTransaction, ExtractionResult, ImportIssue, RawEvidence
from .csv_support import (
    BEOBANK_COMPACT_HEADER,
    BEOBANK_DEBIT_CREDIT_HEADER,
    build_csv_raw_evidence,
    build_dict_rows,
    find_header_row,
    read_csv_text,
    statement_period_from_transactions,
)


def _to_iso_date(value: str) -> str:
    return datetime.strptime(value, "%d/%m/%Y").replace(tzinfo=UTC).date().isoformat()


def _parse_amount(value: str) -> float:
    return float(Decimal(value.replace(".", "").replace(",", ".")))


def _infer_numeric_filename_stem(file_path: str | Path) -> str:
    stem = Path(file_path).stem
    return stem if stem.isdigit() else ""


def _find_supported_header(lines: list[str]) -> tuple[int, str, str] | None:
    header_match = find_header_row(
        lines, delimiter=";", expected_header=BEOBANK_COMPACT_HEADER
    )
    if header_match is not None:
        header_row_index, _ = header_match
        return header_row_index, ";", "compact"

    header_match = find_header_row(
        lines, delimiter=";", expected_header=BEOBANK_DEBIT_CREDIT_HEADER
    )
    if header_match is not None:
        header_row_index, _ = header_match
        return header_row_index, ";", "debit_credit"

    header_match = find_header_row(
        lines, delimiter=",", expected_header=BEOBANK_DEBIT_CREDIT_HEADER
    )
    if header_match is None:
        return None
    header_row_index, _ = header_match
    return header_row_index, ",", "debit_credit"


def _extract_row_fields(
    row: dict[str, str], format_name: str
) -> tuple[str, str, str, str]:
    if format_name == "compact":
        return (
            row.get("Debet", ""),
            row.get("Krediet", ""),
            row.get("Omschrijving", ""),
            row.get("Datum", ""),
        )
    return (
        row.get("Debit", ""),
        row.get("Credit", ""),
        row.get("Message", ""),
        row.get("Date", ""),
    )


def _signed_amount_and_type(debit: str, credit: str) -> tuple[float, str] | None:
    if debit:
        signed_amount = _parse_amount(debit)
        if signed_amount > 0:
            signed_amount = -signed_amount
        return signed_amount, "Expense"
    if credit:
        return _parse_amount(credit), "Income"
    return None


class BeobankCsvExtractor:
    """Represent beobank csv extractor."""

    extractor_id = "beobank_csv_v1"

    def extract(
        self, *, file_path: str | Path, session_id: str, attempt_number: int
    ) -> tuple[RawEvidence, ExtractionResult]:
        """Handle extract."""
        raw_text, encoding = read_csv_text(file_path)
        lines = raw_text.splitlines()
        raw_artifact_ref = (
            f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"
        )

        header_info = _find_supported_header(lines)
        if header_info is None:
            evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=[])
            return evidence, ExtractionResult(
                extractor_id=self.extractor_id,
                raw_artifact_ref=raw_artifact_ref,
                source_metadata={
                    "provider_hint": "beobank",
                    "file_type": "csv",
                    "encoding": encoding,
                },
                statement_metadata={},
                transactions=[],
                issues=[
                    ImportIssue(
                        code="missing_beobank_csv_header",
                        message="Supported Beobank CSV header was not found.",
                        blocking=True,
                    )
                ],
                overall_confidence=0.0,
            )

        header_row_index, delimiter, format_name = header_info
        rows = build_dict_rows(
            lines, delimiter=delimiter, header_row_index=header_row_index
        )
        transactions: list[ExtractedTransaction] = []
        snippets: list[dict] = []

        for row_number, row in rows:
            if not any(row.values()):
                continue

            debit, credit, description, tx_date = _extract_row_fields(row, format_name)
            amount_and_type = _signed_amount_and_type(debit, credit)
            if amount_and_type is None:
                snippets.append(
                    {
                        "row_number": row_number,
                        "decision": "skipped",
                        "reason": "missing_amount",
                        "row": row,
                    }
                )
                continue

            signed_amount, proposed_type = amount_and_type
            transactions.append(
                ExtractedTransaction(
                    transaction_date=_to_iso_date(tx_date),
                    source_description=description,
                    signed_amount=signed_amount,
                    currency="EUR",
                    debit_credit="credit" if signed_amount > 0 else "debit",
                    proposed_transaction_type=proposed_type,
                    source_locator=f"csv:r{row_number}",
                    edit_source="deterministic_extracted",
                )
            )
            snippets.append(
                {
                    "row_number": row_number,
                    "decision": "imported",
                    "reason": f"supported_beobank_{format_name}_row",
                    "row": row,
                }
            )

        evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=snippets)
        statement_metadata = {
            **statement_period_from_transactions(transactions),
            "account_number_hint": _infer_numeric_filename_stem(file_path)
            if format_name == "compact"
            else "",
            "currency": "EUR",
        }
        issues = []
        if not transactions:
            issues.append(
                ImportIssue(
                    code="no_importable_csv_rows",
                    message="The Beobank CSV did not produce any reviewable rows.",
                    blocking=True,
                )
            )

        return evidence, ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={
                "provider_hint": "beobank",
                "file_type": "csv",
                "encoding": encoding,
                "format": format_name,
            },
            statement_metadata=statement_metadata,
            transactions=transactions,
            issues=issues,
            overall_confidence=0.0 if issues else 1.0,
        )
