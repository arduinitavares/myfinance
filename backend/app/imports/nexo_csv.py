from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .contracts import ExtractionResult, ExtractedTransaction, ImportIssue
from .csv_support import NEXO_HEADER, build_csv_raw_evidence, build_dict_rows, find_header_row, read_csv_text

NEXO_SKIP_TYPES = {
    "Cashback",
    "Exchange Credit",
    "Credit Card Withdrawal Credit",
}
INTERNAL_TRANSFER_MARKERS = ("auto transfer", "savings wallet", "credit line wallet")
EXTERNAL_TRANSFER_MARKERS = ("bank transfer", "sepa")
IBAN_RE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}")
STATUS_PREFIX_RE = re.compile(r"^(approved|rejected)\s*/\s*", re.IGNORECASE)


def _to_iso_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date().isoformat()


def _parse_amount(value: str) -> float:
    return float(Decimal(value.replace(",", "")))


def _strip_status_prefix(details: str) -> tuple[str | None, str]:
    text = details.strip()
    match = STATUS_PREFIX_RE.match(text)
    if not match:
        return None, text
    return match.group(1).lower(), STATUS_PREFIX_RE.sub("", text, count=1).strip()


def _looks_like_external_cashout(description: str) -> bool:
    normalized = description.casefold()
    if any(marker in normalized for marker in EXTERNAL_TRANSFER_MARKERS):
        return True
    compact = re.sub(r"\s+", "", description).upper()
    return bool(IBAN_RE.search(compact))


def _looks_like_internal_transfer(description: str) -> bool:
    normalized = description.casefold()
    return any(marker in normalized for marker in INTERNAL_TRANSFER_MARKERS)


class NexoCsvExtractor:
    extractor_id = "nexo_csv_v1"

    def extract(self, *, file_path: str | Path, session_id: str, attempt_number: int):
        raw_text, encoding = read_csv_text(file_path)
        lines = raw_text.splitlines()
        raw_artifact_ref = f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"

        header_match = find_header_row(lines, delimiter=",", expected_header=NEXO_HEADER)
        if header_match is None:
            evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=[])
            return evidence, ExtractionResult(
                extractor_id=self.extractor_id,
                raw_artifact_ref=raw_artifact_ref,
                source_metadata={"provider_hint": "nexo", "file_type": "csv", "encoding": encoding},
                statement_metadata={},
                transactions=[],
                issues=[
                    ImportIssue(
                        code="missing_nexo_csv_header",
                        message="The Nexo CSV header did not match the supported deterministic format.",
                        blocking=True,
                    )
                ],
                overall_confidence=0.0,
            )

        header_row_index, _ = header_match
        rows = build_dict_rows(lines, delimiter=",", header_row_index=header_row_index)
        transactions: list[ExtractedTransaction] = []
        issues: list[ImportIssue] = []
        snippets: list[dict] = []

        for row_number, row in rows:
            if not any(row.values()):
                continue

            transaction_id = row.get("Transaction", "").strip()
            row_type = row.get("Type", "").strip()
            details = row.get("normalizedDisplayDetails") or row.get("Details") or ""
            status_prefix, description = _strip_status_prefix(details)
            amount = _parse_amount(row.get("Input Amount", "0"))

            snippet = {
                "row_number": row_number,
                "transaction_id": transaction_id,
                "type": row_type,
                "details": description,
                "decision": "skipped",
            }

            if status_prefix == "rejected":
                snippet["reason"] = "rejected_row"
                snippets.append(snippet)
                continue

            if row_type in NEXO_SKIP_TYPES:
                snippet["reason"] = "deterministic_skip_type"
                snippets.append(snippet)
                continue

            if row_type == "Transfer Out" and _looks_like_internal_transfer(description):
                snippet["reason"] = "internal_plumbing_transfer"
                snippets.append(snippet)
                continue

            proposed_transaction_type = None
            proposed_expense_category = None
            proposed_transfer_category = None

            if row_type == "Nexo Card Purchase" and amount < 0:
                proposed_transaction_type = "Expense"
                snippet["reason"] = "card_purchase"
            elif row_type == "Nexo Card Transaction Fee" and amount < 0:
                proposed_transaction_type = "Expense"
                proposed_expense_category = "Financial Fees"
                snippet["reason"] = "card_fee"
            elif row_type == "Transfer Out" and amount < 0 and _looks_like_external_cashout(description):
                proposed_transaction_type = "Transfer"
                proposed_transfer_category = "Internal Transfer"
                snippet["reason"] = "external_cash_out"
            elif row_type == "Transfer Out":
                issues.append(
                    ImportIssue(
                        code="ambiguous_nexo_transfer_out",
                        message=f"Nexo Transfer Out row {transaction_id or row_number} could not be classified deterministically.",
                        blocking=False,
                        transaction_ref=f"csv:r{row_number}:{transaction_id}" if transaction_id else f"csv:r{row_number}",
                    )
                )
                snippet["reason"] = "ambiguous_transfer_out"
                snippets.append(snippet)
                continue
            else:
                issues.append(
                    ImportIssue(
                        code="unsupported_nexo_row_type",
                        message=f"Nexo row {transaction_id or row_number} has unsupported type {row_type!r}.",
                        blocking=False,
                        transaction_ref=f"csv:r{row_number}:{transaction_id}" if transaction_id else f"csv:r{row_number}",
                    )
                )
                snippet["reason"] = "unsupported_type"
                snippets.append(snippet)
                continue

            transactions.append(
                ExtractedTransaction(
                    transaction_date=_to_iso_date(row["Date / Time (UTC)"]),
                    source_description=description,
                    signed_amount=amount,
                    currency=row.get("Input Currency", "").strip(),
                    debit_credit="credit" if amount > 0 else "debit",
                    proposed_transaction_type=proposed_transaction_type,
                    proposed_expense_category=proposed_expense_category,
                    proposed_transfer_category=proposed_transfer_category,
                    classification_source="deterministic_nexo_csv",
                    source_locator=f"csv:r{row_number}:{transaction_id}" if transaction_id else f"csv:r{row_number}",
                    edit_source="deterministic_extracted",
                )
            )
            snippet["decision"] = "imported"
            snippets.append(snippet)

        if not transactions:
            issues.append(
                ImportIssue(
                    code="no_importable_nexo_rows",
                    message="The Nexo CSV did not contain any reviewable rows after deterministic skips.",
                    blocking=True,
                )
            )

        evidence = build_csv_raw_evidence(raw_text=raw_text, snippets=snippets)
        return evidence, ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "nexo", "file_type": "csv", "encoding": encoding},
            statement_metadata={"account_number_hint": "NEXO"},
            transactions=transactions,
            issues=issues,
            overall_confidence=0.0 if any(issue.blocking for issue in issues) else 1.0,
        )

