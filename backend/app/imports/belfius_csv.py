from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .contracts import ExtractionResult, ExtractedTransaction, ImportIssue
from .csv_support import (
    BELFIUS_HEADER,
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


class BelfiusCsvExtractor:
    extractor_id = "belfius_csv_v1"

    def extract(self, *, file_path: str | Path, session_id: str, attempt_number: int):
        raw_text, encoding = read_csv_text(file_path)
        lines = raw_text.splitlines()
        header_match = find_header_row(lines, delimiter=";", expected_header=BELFIUS_HEADER)
        raw_artifact_ref = f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"

        if header_match is None:
            evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=[])
            return evidence, ExtractionResult(
                extractor_id=self.extractor_id,
                raw_artifact_ref=raw_artifact_ref,
                source_metadata={"provider_hint": "belfius", "file_type": "csv", "encoding": encoding},
                statement_metadata={},
                transactions=[],
                issues=[
                    ImportIssue(
                        code="missing_belfius_csv_header",
                        message="Supported Belfius CSV header was not found in the first 20 lines.",
                        blocking=True,
                    )
                ],
                overall_confidence=0.0,
            )

        header_row_index, _ = header_match
        rows = build_dict_rows(lines, delimiter=";", header_row_index=header_row_index)
        transactions: list[ExtractedTransaction] = []
        snippets: list[dict] = []

        for row_number, row in rows:
            if not any(row.values()):
                continue

            description = row.get("Mededelingen") or row.get("Transactie") or ""
            signed_amount = _parse_amount(row["Bedrag"])
            transactions.append(
                ExtractedTransaction(
                    transaction_date=_to_iso_date(row["Boekingsdatum"]),
                    source_description=description,
                    signed_amount=signed_amount,
                    currency=(row.get("Devies") or "EUR").strip() or "EUR",
                    debit_credit="credit" if signed_amount > 0 else "debit",
                    proposed_transaction_type="Income" if signed_amount > 0 else "Expense",
                    source_locator=f"csv:r{row_number}",
                    edit_source="deterministic_extracted",
                )
            )
            snippets.append(
                {
                    "row_number": row_number,
                    "decision": "imported",
                    "reason": "supported_belfius_row",
                    "row": row,
                }
            )

        evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=snippets)
        statement_metadata = {
            **statement_period_from_transactions(transactions),
            "account_number_hint": next(
                (row.get("Rekening") for _, row in rows if row.get("Rekening")),
                None,
            ),
            "currency": next((tx.currency for tx in transactions), "EUR"),
        }
        issues = []
        if not transactions:
            issues.append(
                ImportIssue(
                    code="no_importable_csv_rows",
                    message="The Belfius CSV did not produce any reviewable rows.",
                    blocking=True,
                )
            )

        return evidence, ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "belfius", "file_type": "csv", "encoding": encoding},
            statement_metadata=statement_metadata,
            transactions=transactions,
            issues=issues,
            overall_confidence=0.0 if issues else 1.0,
        )
