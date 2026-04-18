from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from app.models.transaction import ExpenseCategory, TransactionType, TransferCategory

from .contracts import ExtractionResult, ExtractedTransaction, ImportIssue, RawEvidence

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


class NexoCsvExtractor:
    extractor_id = "nexo_csv_v1"
    INTERNAL_MARKERS = ("auto transfer", "savings wallet", "credit line wallet")
    EXTERNAL_MARKERS = ("bank transfer", "bank-transfer", "sepa")
    IBAN_TOKEN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}$")

    def extract(self, *, file_path: str | Path, session_id: str, attempt_number: int) -> tuple[RawEvidence, ExtractionResult]:
        path = Path(file_path)
        raw_bytes = path.read_bytes()
        text, charset = self._decode_text(raw_bytes)
        lines = text.splitlines()
        normalized_lines = [line for line in lines if line.strip()]
        raw_text = "\n".join(normalized_lines)

        evidence = RawEvidence(
            text_blocks=[
                {
                    "page_number": 1,
                    "raw_text": raw_text,
                    "lines": normalized_lines,
                }
            ],
            ocr_blocks=[],
            snippets=[],
        )

        header_row, data_rows = self._parse_rows(text)
        if header_row != NEXO_CSV_HEADER:
            issue = ImportIssue(
                code="unsupported_nexo_csv_header",
                message="The uploaded CSV does not match the expected Nexo header shape.",
                blocking=True,
            )
            return evidence, self._failure_result(
                raw_artifact_ref=self._raw_artifact_ref(session_id, attempt_number),
                issues=[issue],
                charset=charset,
            )

        transactions: list[ExtractedTransaction] = []
        issues: list[ImportIssue] = []
        snippets: list[dict[str, str | int | None]] = []
        reviewable_dates: list[str] = []

        for row_number, row in data_rows:
            row_type = self._clean_value(row.get("Type"))
            input_currency = self._clean_value(row.get("Input Currency"))
            input_amount_text = self._clean_value(row.get("Input Amount"))
            details = self._clean_value(row.get("normalizedDisplayDetails") or row.get("Details"))
            date_time = self._clean_value(row.get("Date / Time (UTC)"))
            locator = self._source_locator(row, row_number)

            if self._is_rejected(row_type, details):
                snippets.append(self._snippet(row, row_number, "skipped_rejected", None))
                continue

            if row_type in {"Cashback", "Exchange Credit", "Credit Card Withdrawal Credit"}:
                snippets.append(self._snippet(row, row_number, "skipped_known_non_transaction", None))
                continue

            try:
                signed_amount = self._parse_amount(input_amount_text)
            except ValueError:
                snippets.append(self._snippet(row, row_number, "skipped_invalid_amount", "nexo_invalid_amount"))
                continue

            if row_type == "Nexo Card Purchase":
                if signed_amount >= 0:
                    snippets.append(self._snippet(row, row_number, "skipped_non_debit_purchase", None))
                    continue
                transaction = self._build_transaction(
                    row=row,
                    row_number=row_number,
                    date_time=date_time,
                    description=self._strip_status_prefix(details),
                    signed_amount=signed_amount,
                    currency=input_currency,
                    transaction_type=TransactionType.EXPENSE,
                    expense_category=None,
                    transfer_category=None,
                )
                transactions.append(transaction)
                reviewable_dates.append(transaction.transaction_date)
                snippets.append(self._snippet(row, row_number, "import_expense", None))
                continue

            if row_type == "Nexo Card Transaction Fee":
                if signed_amount >= 0:
                    snippets.append(self._snippet(row, row_number, "skipped_non_debit_fee", None))
                    continue
                transaction = self._build_transaction(
                    row=row,
                    row_number=row_number,
                    date_time=date_time,
                    description=self._strip_status_prefix(details),
                    signed_amount=signed_amount,
                    currency=input_currency,
                    transaction_type=TransactionType.EXPENSE,
                    expense_category=ExpenseCategory.FINANCIAL_FEES,
                    transfer_category=None,
                )
                transactions.append(transaction)
                reviewable_dates.append(transaction.transaction_date)
                snippets.append(self._snippet(row, row_number, "import_fee", None))
                continue

            if row_type == "Transfer Out":
                if self._is_internal_transfer_out(details):
                    snippets.append(self._snippet(row, row_number, "skipped_internal_plumbing", None))
                    continue

                if self._is_external_cashout(details):
                    if signed_amount >= 0:
                        snippets.append(self._snippet(row, row_number, "skipped_non_debit_transfer", None))
                        continue
                    transaction = self._build_transaction(
                        row=row,
                        row_number=row_number,
                        date_time=date_time,
                        description=self._strip_status_prefix(details),
                        signed_amount=signed_amount,
                        currency=input_currency,
                        transaction_type=TransactionType.TRANSFER,
                        expense_category=None,
                        transfer_category=TransferCategory.INTERNAL_TRANSFER,
                    )
                    transactions.append(transaction)
                    reviewable_dates.append(transaction.transaction_date)
                    snippets.append(self._snippet(row, row_number, "import_transfer", None))
                    continue

                issues.append(
                    ImportIssue(
                        code="nexo_ambiguous_transfer_out",
                        message="Skipped an ambiguous Nexo Transfer Out row that did not clearly describe an external cashout.",
                        blocking=False,
                        transaction_ref=locator,
                    )
                )
                snippets.append(self._snippet(row, row_number, "skipped_ambiguous_transfer", "nexo_ambiguous_transfer_out"))
                continue

            issues.append(
                ImportIssue(
                    code="nexo_unknown_row_type",
                    message=f"Unsupported Nexo row type: {row_type or 'missing'}",
                    blocking=False,
                    transaction_ref=locator,
                )
            )
            snippets.append(self._snippet(row, row_number, "skipped_unknown_type", "nexo_unknown_row_type"))
            continue

        if not transactions:
            issues.insert(
                0,
                ImportIssue(
                    code="no_importable_nexo_rows",
                    message="No reviewable Nexo rows were found in the uploaded CSV.",
                    blocking=True,
                )
            )

        result = ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=self._raw_artifact_ref(session_id, attempt_number),
            source_metadata={"provider_hint": "nexo", "file_type": "csv", "charset": charset},
            statement_metadata={
                "account_number_hint": "NEXO",
                "card_number_hint": None,
                "currency": None,
                "statement_period_start": min(reviewable_dates) if reviewable_dates else None,
                "statement_period_end": max(reviewable_dates) if reviewable_dates else None,
            },
            transactions=transactions,
            issues=issues,
            overall_confidence=1.0 if transactions else 0.0,
        )
        evidence.snippets = snippets
        return evidence, result

    @staticmethod
    def _decode_text(raw_bytes: bytes) -> tuple[str, str]:
        try:
            return raw_bytes.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1"), "latin-1"

    @staticmethod
    def _parse_rows(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
        reader = csv.reader(io.StringIO(text))
        try:
            header_row = next(reader)
        except StopIteration:
            return [], []

        normalized_header = [NexoCsvExtractor._clean_value(value) for value in header_row]
        dict_reader = csv.DictReader(io.StringIO(text))
        rows: list[tuple[int, dict[str, str]]] = []
        for row_number, row in enumerate(dict_reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            rows.append((row_number, row))
        return normalized_header, rows

    @staticmethod
    def _clean_value(value: str | None) -> str:
        if value is None:
            return ""
        return str(value).replace("\ufeff", "").strip()

    @staticmethod
    def _parse_amount(amount_text: str) -> float:
        cleaned = NexoCsvExtractor._clean_value(amount_text).replace(" ", "").replace(",", ".")
        if not cleaned:
            raise ValueError("empty amount")
        return float(cleaned)

    @staticmethod
    def _clean_date(date_time: str) -> str:
        cleaned = NexoCsvExtractor._clean_value(date_time)
        if not cleaned:
            raise ValueError("empty date")
        return cleaned.split(" ")[0]

    @staticmethod
    def _strip_status_prefix(details: str) -> str:
        cleaned = NexoCsvExtractor._clean_value(details)
        for prefix in ("approved / ", "rejected / "):
            if cleaned.casefold().startswith(prefix):
                return cleaned[len(prefix) :]
        return cleaned

    @staticmethod
    def _is_rejected(row_type: str, details: str) -> bool:
        row_type_cf = row_type.casefold()
        details_cf = details.casefold()
        return row_type_cf == "rejected" or details_cf.startswith("rejected /") or " rejected /" in details_cf

    @staticmethod
    def _is_internal_transfer_out(details: str) -> bool:
        details_cf = details.casefold()
        return any(marker in details_cf for marker in NexoCsvExtractor.INTERNAL_MARKERS)

    @staticmethod
    def _is_external_cashout(details: str) -> bool:
        details_cf = details.casefold()
        if any(marker in details_cf for marker in NexoCsvExtractor.EXTERNAL_MARKERS):
            return True
        return NexoCsvExtractor._contains_iban_like_token(details)

    @staticmethod
    def _contains_iban_like_token(details: str) -> bool:
        for token in re.split(r"[^A-Z0-9]+", details.upper()):
            if NexoCsvExtractor.IBAN_TOKEN_RE.match(token):
                return True
        return False

    @staticmethod
    def _build_transaction(
        *,
        row: dict[str, str],
        row_number: int,
        date_time: str,
        description: str,
        signed_amount: float,
        currency: str,
        transaction_type: TransactionType,
        expense_category: ExpenseCategory | None,
        transfer_category: TransferCategory | None,
    ) -> ExtractedTransaction:
        debit_credit = "credit" if signed_amount > 0 else "debit"
        return ExtractedTransaction(
            transaction_date=NexoCsvExtractor._clean_date(date_time),
            source_description=description,
            canonical_description_en=None,
            signed_amount=signed_amount,
            currency=NexoCsvExtractor._clean_value(currency),
            debit_credit=debit_credit,
            inferred_category=None,
            category_source=None,
            proposed_transaction_type=transaction_type,
            proposed_expense_category=expense_category,
            proposed_income_category=None,
            proposed_transfer_category=transfer_category,
            proposal_source="deterministic_extracted",
            confidence={},
            source_locator=NexoCsvExtractor._source_locator(row, row_number),
            edit_source="deterministic_extracted",
        )

    @staticmethod
    def _source_locator(row: dict[str, str], row_number: int) -> str:
        transaction_id = NexoCsvExtractor._clean_value(row.get("Transaction")) or "missing-id"
        return f"csv:r{row_number}:{transaction_id}"

    @staticmethod
    def _snippet(
        row: dict[str, str],
        row_number: int,
        decision: str,
        reason: str | None,
    ) -> dict[str, str | int | None]:
        return {
            "page_number": 1,
            "row_number": row_number,
            "transaction_id": NexoCsvExtractor._clean_value(row.get("Transaction")),
            "type": NexoCsvExtractor._clean_value(row.get("Type")),
            "details": NexoCsvExtractor._clean_value(row.get("normalizedDisplayDetails") or row.get("Details")),
            "decision": decision,
            "reason": reason,
        }

    @staticmethod
    def _raw_artifact_ref(session_id: str, attempt_number: int) -> str:
        return f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"

    @staticmethod
    def _failure_result(*, raw_artifact_ref: str, issues: list[ImportIssue], charset: str) -> ExtractionResult:
        return ExtractionResult(
            extractor_id=NexoCsvExtractor.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "nexo", "file_type": "csv", "charset": charset},
            statement_metadata={"account_number_hint": "NEXO"},
            transactions=[],
            issues=issues,
            overall_confidence=0.0,
        )
