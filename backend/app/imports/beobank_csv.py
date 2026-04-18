from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .contracts import ExtractionResult, ExtractedTransaction, ImportIssue
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
    return datetime.strptime(value, "%d/%m/%Y").date().isoformat()


def _parse_amount(value: str) -> float:
    return float(Decimal(value.replace(".", "").replace(",", ".")))


def _infer_numeric_filename_stem(file_path: str | Path) -> str:
    stem = Path(file_path).stem
    return stem if stem.isdigit() else ""


class BeobankCsvExtractor:
    extractor_id = "beobank_csv_v1"

    def extract(self, *, file_path: str | Path, session_id: str, attempt_number: int):
        raw_text, encoding = read_csv_text(file_path)
        lines = raw_text.splitlines()
        raw_artifact_ref = f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"

        header_match = find_header_row(lines, delimiter=";", expected_header=BEOBANK_COMPACT_HEADER)
        format_name = "compact"
        delimiter = ";"
        if header_match is None:
            header_match = find_header_row(lines, delimiter=";", expected_header=BEOBANK_DEBIT_CREDIT_HEADER)
            format_name = "debit_credit"
        if header_match is None:
            header_match = find_header_row(lines, delimiter=",", expected_header=BEOBANK_DEBIT_CREDIT_HEADER)
            delimiter = ","
            format_name = "debit_credit"

        if header_match is None:
            evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=[])
            return evidence, ExtractionResult(
                extractor_id=self.extractor_id,
                raw_artifact_ref=raw_artifact_ref,
                source_metadata={"provider_hint": "beobank", "file_type": "csv", "encoding": encoding},
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

        header_row_index, _ = header_match
        rows = build_dict_rows(lines, delimiter=delimiter, header_row_index=header_row_index)
        transactions: list[ExtractedTransaction] = []
        snippets: list[dict] = []

        for row_number, row in rows:
            if not any(row.values()):
                continue

            if format_name == "compact":
                debit = row.get("Debet", "")
                credit = row.get("Krediet", "")
                description = row.get("Omschrijving", "")
                tx_date = row.get("Datum", "")
            else:
                debit = row.get("Debit", "")
                credit = row.get("Credit", "")
                description = row.get("Message", "")
                tx_date = row.get("Date", "")

            signed_amount: float | None = None
            proposed_type: str | None = None
            if debit:
                signed_amount = _parse_amount(debit)
                if signed_amount > 0:
                    signed_amount = -signed_amount
                proposed_type = "Expense"
            elif credit:
                signed_amount = _parse_amount(credit)
                proposed_type = "Income"

            if signed_amount is None:
                snippets.append(
                    {
                        "row_number": row_number,
                        "decision": "skipped",
                        "reason": "missing_amount",
                        "row": row,
                    }
                )
                continue

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
            "account_number_hint": _infer_numeric_filename_stem(file_path) if format_name == "compact" else "",
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
