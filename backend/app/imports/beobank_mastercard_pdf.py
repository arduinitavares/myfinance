import re
from datetime import datetime

from .contracts import ExtractionResult, ExtractedTransaction, ImportIssue

AMOUNT_BODY = r"(?:\d{1,3}(?:\.\d{3})+|\d{1,3}(?: \d{3})+|\d+),\d{2}"
SIGNED_AMOUNT_BODY = rf"-?{AMOUNT_BODY}"
AMOUNT_RE = re.compile(rf"^{SIGNED_AMOUNT_BODY}$")
ROW_RE = re.compile(
    rf"^(?P<date>\d{{2}}/\d{{2}}/\d{{4}})\s+(?P<description>.+?)\s+(?P<amount>{SIGNED_AMOUNT_BODY})$"
)
MALFORMED_ROW_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<description>.+?)\s+"
    r"(?P<amount>-?(?=[^,]*\.)(?=[^,]* )\d{1,3}(?:[. ]\d{3})+,\d{2})$"
)
FX_HELPER_RE = re.compile(
    rf"^(?P<amount>{AMOUNT_BODY})\s+[A-Z]{{3}}\s+WISSELKOERS\s+\d+(?:\.\d+)?$",
    re.IGNORECASE,
)
INLINE_WISSELKOSTEN_RE = re.compile(
    rf"^WISSELKOSTEN\s+(?P<amount>{SIGNED_AMOUNT_BODY})$",
    re.IGNORECASE,
)
PAGE_FOOTER_RE = re.compile(r"^(?:Blz\s+\d+|KB\..+)$", re.IGNORECASE)
CARD_HEADER_RE = re.compile(r"^Kaart\s+(?P<card>.+)$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PERIOD_RE = re.compile(
    r"(?P<start>\d{2}/\d{2}/\d{4})\s*[-\u2013]\s*(?P<end>\d{2}/\d{2}/\d{4})"
)


def _collapse_token(text: str) -> str:
    return " ".join(text.split()).casefold()


def _to_iso_date(value: str) -> str:
    return datetime.strptime(value, "%d/%m/%Y").date().isoformat()


def _parse_amount_text(amount_text: str) -> tuple[float, str]:
    if not AMOUNT_RE.match(amount_text):
        raise ValueError(f"invalid amount: {amount_text}")

    absolute_amount = float(amount_text.lstrip("-").replace(" ", "").replace(".", "").replace(",", "."))
    if absolute_amount == 0:
        raise ValueError(f"zero amount not allowed: {amount_text}")

    if amount_text.startswith("-"):
        return absolute_amount, "credit"
    return -absolute_amount, "debit"


class BeobankMastercardPdfExtractor:
    extractor_id = "beobank_mastercard_pdf_v1"

    def extract_from_pages(self, pages: list[dict], raw_artifact_ref: str) -> ExtractionResult:
        issues: list[ImportIssue] = []
        transactions: list[ExtractedTransaction] = []
        statement_metadata = self._extract_statement_metadata(pages)
        last_transaction_date: str | None = None
        last_transaction_description: str | None = None

        card_headers = self._collect_card_headers(pages)
        if len(card_headers) > 1:
            issues.append(
                ImportIssue(
                    code="multi_card_not_supported",
                    message="More than one distinct card header was detected in the statement.",
                    blocking=True,
                )
            )

        for page in pages:
            if page["page_number"] == 1:
                continue
            last_transaction_date, last_transaction_description = self._parse_transaction_page(
                page,
                transactions,
                issues,
                last_transaction_date,
                last_transaction_description,
            )

        return ExtractionResult(
            extractor_id=self.extractor_id,
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "beobank", "file_type": "pdf", "language": "nl"},
            statement_metadata=statement_metadata,
            transactions=transactions,
            issues=issues,
            overall_confidence=0.0 if any(issue.blocking for issue in issues) else 1.0,
        )

    def _extract_statement_metadata(self, pages: list[dict]) -> dict:
        metadata = {"currency": "EUR"}

        for page in pages:
            for line in page["lines"]:
                text = " ".join(line["text"].split())
                if "statement_period_start" not in metadata:
                    period_match = PERIOD_RE.search(text)
                    if period_match:
                        metadata["statement_period_start"] = _to_iso_date(period_match.group("start"))
                        metadata["statement_period_end"] = _to_iso_date(period_match.group("end"))

                if "card_number_hint" not in metadata:
                    card_match = CARD_HEADER_RE.match(text)
                    if card_match:
                        metadata["card_number_hint"] = " ".join(card_match.group("card").split())

        return metadata

    def _collect_card_headers(self, pages: list[dict]) -> set[str]:
        headers: set[str] = set()
        for page in pages:
            for line in page["lines"]:
                card_match = CARD_HEADER_RE.match(" ".join(line["text"].split()))
                if card_match:
                    headers.add(_collapse_token(card_match.group("card")))
        return headers

    def _parse_transaction_page(
        self,
        page: dict,
        transactions: list[ExtractedTransaction],
        issues: list[ImportIssue],
        last_transaction_date: str | None,
        last_transaction_description: str | None,
    ) -> tuple[str | None, str | None]:
        lines = page["lines"]
        if not lines:
            return last_transaction_date, last_transaction_description

        marker_index = self._find_line_index(lines, "Uw transacties")
        body_start = 0

        if marker_index is None:
            first_content_index = self._find_first_table_content_index(lines, 0)
            if first_content_index is None:
                return last_transaction_date, last_transaction_description
            if page["page_number"] <= 2 or not self._has_required_headers(lines, -1, first_content_index):
                issues.append(
                    ImportIssue(
                        code="unclassifiable_table_line",
                        message=f"Missing Dutch transaction marker before row-like content on page {page['page_number']}.",
                        blocking=True,
                    )
                )
                return last_transaction_date, last_transaction_description
        else:
            body_start = marker_index + 1
            first_content_index = self._find_first_table_content_index(lines, body_start)
            if first_content_index is None:
                return last_transaction_date, last_transaction_description

        if not self._has_required_headers(lines, body_start - 1, first_content_index):
            issues.append(
                ImportIssue(
                    code="unclassifiable_table_line",
                    message=f"Missing Dutch transaction table headers before first row on page {page['page_number']}.",
                    blocking=True,
                )
            )
            return last_transaction_date, last_transaction_description

        current_row: dict | None = None
        body_lines = lines[body_start:]
        index = 0
        while index < len(body_lines):
            line = body_lines[index]
            line_number = line["line_number"]
            text = line["text"]
            collapsed = _collapse_token(text)
            if collapsed == "uw miles":
                if current_row is not None:
                    transactions.append(self._build_transaction(page["page_number"], current_row))
                    last_transaction_date = current_row["transaction_date"]
                    last_transaction_description = self._joined_description(current_row)
                    current_row = None
                break
            line_class = self._classify_line(text, current_row is not None)

            if self._is_standalone_wisselkosten(body_lines, index):
                inherited_date = current_row["transaction_date"] if current_row is not None else last_transaction_date
                if inherited_date is None:
                    issues.append(self._unclassifiable_issue(page["page_number"], line_number, text))
                    index += 1
                    continue

                fee_context = self._fee_context_description(current_row, last_transaction_description)
                if current_row is not None:
                    transactions.append(self._build_transaction(page["page_number"], current_row))
                    last_transaction_date = current_row["transaction_date"]
                    last_transaction_description = self._joined_description(current_row)
                    current_row = None

                fee_amount_line = body_lines[index + 1]
                fee_row = self._build_standalone_wisselkosten_row(
                    transaction_date=inherited_date,
                    fee_context=fee_context,
                    start_line=line_number,
                    end_line=fee_amount_line["line_number"],
                    amount_text=fee_amount_line["text"],
                )
                transactions.append(self._build_transaction(page["page_number"], fee_row))
                last_transaction_date = inherited_date
                index += 2
                continue

            if self._is_inline_wisselkosten(text):
                inherited_date = current_row["transaction_date"] if current_row is not None else last_transaction_date
                if inherited_date is None:
                    issues.append(self._unclassifiable_issue(page["page_number"], line_number, text))
                    index += 1
                    continue

                fee_context = self._fee_context_description(current_row, last_transaction_description)
                if current_row is not None:
                    transactions.append(self._build_transaction(page["page_number"], current_row))
                    last_transaction_date = current_row["transaction_date"]
                    last_transaction_description = self._joined_description(current_row)
                    current_row = None

                fee_row = self._build_inline_wisselkosten_row(
                    transaction_date=inherited_date,
                    fee_context=fee_context,
                    line_number=line_number,
                    text=text,
                )
                transactions.append(self._build_transaction(page["page_number"], fee_row))
                last_transaction_date = inherited_date
                index += 1
                continue

            if line_class in {"card_header", "table_header", "fx_helper", "page_footer_noise"}:
                index += 1
                continue

            if line_class == "malformed_row_candidate":
                issues.append(self._unclassifiable_issue(page["page_number"], line_number, text))
                index += 1
                continue

            if line_class == "row_start":
                if current_row is not None:
                    transactions.append(self._build_transaction(page["page_number"], current_row))
                    last_transaction_date = current_row["transaction_date"]
                    last_transaction_description = self._joined_description(current_row)
                current_row = self._build_row_candidate(line_number, text)
                index += 1
                continue

            if line_class == "continuation":
                if current_row is None:
                    issues.append(self._unclassifiable_issue(page["page_number"], line_number, text))
                    index += 1
                    continue
                current_row["description_parts"].append(" ".join(text.split()))
                current_row["end_line"] = line_number
                index += 1
                continue

            issues.append(self._unclassifiable_issue(page["page_number"], line_number, text))
            index += 1

        if current_row is not None:
            transactions.append(self._build_transaction(page["page_number"], current_row))
            last_transaction_date = current_row["transaction_date"]
            last_transaction_description = self._joined_description(current_row)

        return last_transaction_date, last_transaction_description

    def _find_line_index(self, lines: list[dict], token: str) -> int | None:
        needle = _collapse_token(token)
        for index, line in enumerate(lines):
            if _collapse_token(line["text"]) == needle:
                return index
        return None

    def _find_first_table_content_index(self, lines: list[dict], start_index: int) -> int | None:
        for index, line in enumerate(lines[start_index:], start=start_index):
            if self._classify_line(line["text"], has_active_row=False) == "row_start":
                return index
            if self._classify_line(line["text"], has_active_row=False) == "malformed_row_candidate":
                return index
            if self._is_standalone_wisselkosten(lines, index):
                return index
        return None

    def _has_required_headers(self, lines: list[dict], marker_index: int, first_row_index: int) -> bool:
        header_tokens = {"datum": False, "beschrijving": False, "bedrag": False}
        for line in lines[marker_index + 1 : first_row_index]:
            collapsed = _collapse_token(line["text"])
            for token in header_tokens:
                if token in collapsed:
                    header_tokens[token] = True
        return all(header_tokens.values())

    def _classify_line(self, text: str, has_active_row: bool) -> str | None:
        normalized = " ".join(text.split())
        collapsed = _collapse_token(normalized)
        if CARD_HEADER_RE.match(normalized):
            return "card_header"
        if all(token in collapsed for token in ("datum", "beschrijving", "bedrag")):
            return "table_header"
        if FX_HELPER_RE.match(normalized):
            return "fx_helper"
        if PAGE_FOOTER_RE.match(normalized):
            return "page_footer_noise"
        if self._is_malformed_row_candidate(normalized):
            return "malformed_row_candidate"
        if self._is_row_start(normalized):
            return "row_start"
        if has_active_row and self._is_continuation(normalized):
            return "continuation"
        return None

    def _is_row_start(self, text: str) -> bool:
        match = ROW_RE.match(text)
        if not match:
            return False
        try:
            _parse_amount_text(match.group("amount"))
        except ValueError:
            return False
        return True

    def _is_malformed_row_candidate(self, text: str) -> bool:
        return MALFORMED_ROW_RE.match(text) is not None

    def _is_continuation(self, text: str) -> bool:
        stripped = " ".join(text.split())
        if not stripped:
            return False
        if stripped.casefold().startswith("wisselkosten"):
            return False
        if DATE_RE.match(stripped):
            return False
        if AMOUNT_RE.match(stripped):
            return False
        return True

    def _is_inline_wisselkosten(self, text: str) -> bool:
        return INLINE_WISSELKOSTEN_RE.match(" ".join(text.split())) is not None

    @staticmethod
    def _fee_context_description(current_row: dict | None, last_transaction_description: str | None) -> str | None:
        if current_row is None:
            return last_transaction_description
        description = BeobankMastercardPdfExtractor._joined_description(current_row)
        return description or None

    @staticmethod
    def _joined_description(row: dict) -> str:
        return " ".join(row["description_parts"]).strip()

    def _is_standalone_wisselkosten(self, body_lines: list[dict], index: int) -> bool:
        if body_lines[index]["text"].strip().casefold() != "wisselkosten":
            return False
        if index == 0 or index + 1 >= len(body_lines):
            return False
        if not FX_HELPER_RE.match(" ".join(body_lines[index - 1]["text"].split())):
            return False
        try:
            _parse_amount_text(" ".join(body_lines[index + 1]["text"].split()))
        except ValueError:
            return False
        return True

    def _build_row_candidate(self, line_number: int, text: str) -> dict:
        match = ROW_RE.match(" ".join(text.split()))
        assert match is not None
        return {
            "transaction_date": _to_iso_date(match.group("date")),
            "description_parts": [" ".join(match.group("description").split())],
            "amount_text": match.group("amount"),
            "start_line": line_number,
            "end_line": line_number,
        }

    def _build_standalone_wisselkosten_row(
        self,
        transaction_date: str,
        fee_context: str | None,
        start_line: int,
        end_line: int,
        amount_text: str,
    ) -> dict:
        return {
            "transaction_date": transaction_date,
            "description_parts": [self._wisselkosten_description(fee_context)],
            "amount_text": " ".join(amount_text.split()),
            "start_line": start_line,
            "end_line": end_line,
        }

    def _build_inline_wisselkosten_row(
        self,
        *,
        transaction_date: str,
        fee_context: str | None,
        line_number: int,
        text: str,
    ) -> dict:
        normalized = " ".join(text.split())
        match = INLINE_WISSELKOSTEN_RE.match(normalized)
        assert match is not None
        return {
            "transaction_date": transaction_date,
            "description_parts": [self._wisselkosten_description(fee_context)],
            "amount_text": match.group("amount"),
            "start_line": line_number,
            "end_line": line_number,
        }

    @staticmethod
    def _wisselkosten_description(fee_context: str | None) -> str:
        if fee_context:
            return f"WISSELKOSTEN - {fee_context}"
        return "WISSELKOSTEN"

    def _build_transaction(self, page_number: int, row: dict) -> ExtractedTransaction:
        signed_amount, debit_credit = _parse_amount_text(row["amount_text"])
        start_line = row["start_line"]
        end_line = row["end_line"]
        source_locator = (
            f"pdf:p{page_number}:l{start_line}"
            if start_line == end_line
            else f"pdf:p{page_number}:l{start_line}-{end_line}"
        )
        return ExtractedTransaction(
            transaction_date=row["transaction_date"],
            source_description=" ".join(row["description_parts"]),
            canonical_description_en=None,
            signed_amount=signed_amount,
            currency="EUR",
            debit_credit=debit_credit,
            inferred_category=None,
            category_source=None,
            confidence={},
            source_locator=source_locator,
            edit_source="deterministic_extracted",
        )

    def _unclassifiable_issue(self, page_number: int, line_number: int, text: str) -> ImportIssue:
        return ImportIssue(
            code="unclassifiable_table_line",
            message=f"Unclassifiable table line on page {page_number}, line {line_number}: {text}",
            blocking=True,
            transaction_ref=f"pdf:p{page_number}:l{line_number}",
        )
