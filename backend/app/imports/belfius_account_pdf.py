"""Module for backend app imports belfius_account_pdf."""

import re
from datetime import UTC, datetime
from typing import Any

from .contracts import ExtractedTransaction, ExtractionResult, ImportIssue

ROW_RE: Any = re.compile(
    r"^(?P<sequence>\d{4})\s+(?P<date>\d{2}-\d{2}-\d{4})\s+\(VAL\.\s+(?P<value_date>\d{2}-\d{2}-\d{4})\)\s+(?P<sign>[+-])\s+(?P<amount>(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2})$"
)
ACCOUNT_RE: Any = re.compile(r"\b(BE\d{2}(?:\s+\d{4}){3})\b")
STATEMENT_DATE_RE: Any = re.compile(r"DATUM\s*:\s*(\d{2}-\d{2}-\d{4})")
SALDO_RE: Any = re.compile(r"^SALDO OP\s+(\d{2}-\d{2}-\d{4})")


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def _to_iso_date(value: str) -> str:
    return datetime.strptime(value, "%d-%m-%Y").replace(tzinfo=UTC).date().isoformat()


def _parse_amount(sign: str, amount_text: str) -> tuple[float, str]:
    absolute_amount = float(amount_text.replace(".", "").replace(",", "."))
    if absolute_amount == 0:
        msg = "zero amount not allowed"
        raise ValueError(msg)
    if sign == "+":
        return absolute_amount, "credit"
    return -absolute_amount, "debit"


class BelfiusAccountPdfExtractor:
    """Represent belfius account pdf extractor."""

    extractor_id = "belfius_account_pdf_v1"

    def extract_from_pages(
        self, pages: list[dict], raw_artifact_ref: str
    ) -> ExtractionResult:
        """Handle extract from pages."""
        issues: list[ImportIssue] = []
        transactions: list[ExtractedTransaction] = []
        statement_metadata = self._extract_statement_metadata(pages)

        for page in pages:
            if not self._page_has_transaction_rows(page):
                continue
            transactions.extend(self._parse_transaction_page(page, issues))

        return ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={
                "provider_hint": "belfius",
                "file_type": "pdf",
                "language": "nl",
            },
            statement_metadata=statement_metadata,
            transactions=transactions,
            issues=issues,
            overall_confidence=0.0 if any(issue.blocking for issue in issues) else 1.0,
        )

    def _extract_statement_metadata(self, pages: list[dict]) -> dict:
        metadata = {"currency": "EUR"}

        for page in pages:
            for line in page["lines"]:
                text = _collapse_spaces(line["text"])

                if "account_number_hint" not in metadata:
                    account_match = ACCOUNT_RE.search(text)
                    if account_match:
                        metadata["account_number_hint"] = account_match.group(1)

                if "statement_period_end" not in metadata:
                    statement_date_match = STATEMENT_DATE_RE.search(text)
                    if statement_date_match:
                        metadata["statement_period_end"] = _to_iso_date(
                            statement_date_match.group(1)
                        )

                if "statement_period_start" not in metadata:
                    saldo_match = SALDO_RE.match(text)
                    if saldo_match:
                        metadata["statement_period_start"] = _to_iso_date(
                            saldo_match.group(1)
                        )

        return metadata

    def _parse_transaction_page(
        self, page: dict, issues: list[ImportIssue]
    ) -> list[ExtractedTransaction]:
        transactions: list[ExtractedTransaction] = []
        current_row: dict | None = None
        after_table = False

        for line in page["lines"]:
            text = _collapse_spaces(line["text"])
            line_number = line["line_number"]

            if after_table:
                continue

            row_match = ROW_RE.match(text)
            if row_match:
                self._append_current_row(
                    page["page_number"], current_row, transactions, issues
                )
                current_row = self._start_transaction_row(
                    page["page_number"], line_number, text, row_match, issues
                )
                continue

            if current_row is not None:
                if text.startswith("SALDO OP "):
                    self._append_current_row(
                        page["page_number"], current_row, transactions, issues
                    )
                    current_row = None
                    after_table = True
                    continue

                current_row["description_parts"].append(text)
                current_row["end_line"] = line_number
                continue

        self._append_current_row(page["page_number"], current_row, transactions, issues)
        return transactions

    def _append_current_row(
        self,
        page_number: int,
        current_row: dict | None,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
    ) -> None:
        if current_row is None:
            return

        built_transaction = self._build_transaction(page_number, current_row)
        if built_transaction is None:
            issues.append(self._missing_description_issue(page_number, current_row))
            return
        transactions.append(built_transaction)

    def _start_transaction_row(
        self,
        page_number: int,
        line_number: int,
        text: str,
        row_match: re.Match[str],
        issues: list[ImportIssue],
    ) -> dict | None:
        try:
            signed_amount, debit_credit = _parse_amount(
                row_match.group("sign"), row_match.group("amount")
            )
        except ValueError:
            issues.append(self._unclassifiable_issue(page_number, line_number, text))
            return None

        return {
            "transaction_date": _to_iso_date(row_match.group("date")),
            "signed_amount": signed_amount,
            "debit_credit": debit_credit,
            "start_line": line_number,
            "end_line": line_number,
            "description_parts": [],
        }

    @staticmethod
    def _page_has_transaction_rows(page: dict) -> bool:
        return any(
            ROW_RE.match(_collapse_spaces(line["text"])) for line in page["lines"]
        )

    @staticmethod
    def _build_transaction(page_number: int, row: dict) -> ExtractedTransaction | None:
        description = " ".join(row["description_parts"]).strip()
        if not description:
            return None

        locator = f"pdf:p{page_number}:l{row['start_line']}"
        if row["end_line"] != row["start_line"]:
            locator += f"-{row['end_line']}"

        return ExtractedTransaction(
            transaction_date=row["transaction_date"],
            source_description=description,
            signed_amount=row["signed_amount"],
            currency="EUR",
            debit_credit=row["debit_credit"],
            source_locator=locator,
            edit_source="deterministic_extracted",
        )

    @staticmethod
    def _missing_description_issue(page_number: int, row: dict) -> ImportIssue:
        return ImportIssue(
            code="missing_transaction_description",
            message=(
                f"Transaction row on page {page_number} lines "
                f"{row['start_line']}-{row['end_line']} has no description."
            ),
            blocking=True,
            transaction_ref=f"pdf:p{page_number}:l{row['start_line']}-{row['end_line']}",
        )

    @staticmethod
    def _unclassifiable_issue(
        page_number: int, line_number: int, text: str
    ) -> ImportIssue:
        return ImportIssue(
            code="unclassifiable_table_line",
            message=(
                f"Unclassifiable Belfius table line on page {page_number}, "
                f"line {line_number}: {text}"
            ),
            blocking=True,
            transaction_ref=f"pdf:p{page_number}:l{line_number}",
        )
