# Nexo Import Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proper Nexo CSV importer on the import-session review pipeline so uploads and batch-folder imports produce reviewable draft sessions, commit the right transaction types on approval, and never route Nexo through the legacy direct-commit CSV lane.

**Architecture:** Extend the existing import-session pipeline with a new `nexo_csv` detection/extraction strategy and a typed proposal contract on import drafts. Keep Nexo off `backend/app/services/csv_parser.py` and `CsvImportService`; single-file upload and batch-folder import should both detect Nexo and hand it to `ImportWorkflowService`, while non-Nexo CSVs stay on the legacy lane for now.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite runtime migrations, pytest, React, TypeScript, React Testing Library, Jest, react-scripts

---

## File Structure

### Backend

- Create: `backend/app/imports/nexo_csv.py`
  - Deterministic Nexo CSV extractor that emits reviewable rows, row-level issues, and CSV evidence.
- Create: `backend/app/migrations/migrate_import_transaction_draft_proposals.py`
  - Adds proposal columns to `import_transaction_drafts` for existing databases.
- Create: `backend/tests/imports/fixtures/nexo_csv.py`
  - Shared helper that builds stable Nexo CSV fixtures for detector, extractor, API, and batch tests.
- Create: `backend/tests/imports/test_nexo_csv.py`
  - Focused extractor tests for purchase, fee, cash-out, skip, warning, and empty-session behavior.
- Modify: `backend/app/imports/contracts.py`
  - Add `ImportStrategyKey.NEXO_CSV` and typed proposal fields on `ExtractedTransaction`.
- Modify: `backend/app/imports/detection.py`
  - Detect Nexo CSVs by exact header shape and preserve charset hints for unknown CSVs.
- Modify: `backend/app/imports/workflow.py`
  - Dispatch `nexo_csv` extraction, persist proposal fields, validate proposal combinations, and commit typed transaction/category proposals.
- Modify: `backend/app/models/imports.py`
  - Add proposal columns to `ImportTransactionDraft`.
- Modify: `backend/app/schemas/imports.py`
  - Replace free-text category hints in the response contract with typed proposal fields.
- Modify: `backend/app/routers/imports.py`
  - Auto-extract Nexo CSV uploads the same way PDFs are auto-extracted today.
- Modify: `backend/app/imports/batch_folder.py`
  - Detect CSV content before routing; send recognized Nexo CSVs through the review pipeline and leave non-Nexo CSVs on the legacy path.
- Modify: `backend/app/database_manager.py`
  - Ensure proposal columns exist at runtime for older databases.
- Modify: `backend/app/migrations/run_migrations.py`
  - Hook the import-draft proposal migration into the manual migration runner.
- Modify: `backend/tests/imports/test_contracts.py`
- Modify: `backend/tests/imports/test_detection.py`
- Modify: `backend/tests/imports/test_import_models.py`
- Modify: `backend/tests/imports/test_import_workflow.py`
- Modify: `backend/tests/imports/test_import_review_api.py`
- Modify: `backend/tests/imports/test_import_batch_api.py`

### Frontend

- Modify: `frontend/src/types/import.ts`
  - Mirror the new proposal fields from the backend review contract.
- Modify: `frontend/src/components/imports/ImportReviewPage.tsx`
  - Show the committed proposal for each row and keep using shared display-money rendering.
- Modify: `frontend/src/components/imports/ImportReviewPage.test.tsx`
  - Cover Nexo review rows with explicit proposal display and “Needs classification” fallback.

### Guardrail

Do not add or keep Nexo-specific logic in:

- `backend/app/services/csv_parser.py`
- `backend/app/services/csv_import_service.py`

If a local exploratory Nexo spike exists there, discard it before starting Task 1.

## Task 1: Add The Typed Proposal Contract And Runtime Schema Support

**Files:**
- Create: `backend/app/migrations/migrate_import_transaction_draft_proposals.py`
- Modify: `backend/app/imports/contracts.py`
- Modify: `backend/app/models/imports.py`
- Modify: `backend/app/schemas/imports.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/migrations/run_migrations.py`
- Test: `backend/tests/imports/test_contracts.py`
- Test: `backend/tests/imports/test_import_models.py`

- [ ] **Step 1: Write the failing backend contract and schema tests**

```python
# backend/tests/imports/test_contracts.py
from app.models.transaction import ExpenseCategory, TransactionType


def test_extracted_transaction_serializes_proposal_fields():
    tx = ExtractedTransaction(
        transaction_date="2026-04-11",
        source_description="Nexo Card Transaction Fee",
        signed_amount=-0.16,
        currency="xUSD",
        debit_credit="debit",
        source_locator="csv:r3:NXT_FEE_1",
        proposed_transaction_type=TransactionType.EXPENSE,
        proposed_expense_category=ExpenseCategory.FINANCIAL_FEES,
        proposal_source="deterministic_extracted",
        edit_source="deterministic_extracted",
    )

    dumped = tx.model_dump(mode="json")
    assert dumped["proposed_transaction_type"] == "Expense"
    assert dumped["proposed_expense_category"] == "Financial Fees"
    assert dumped["proposal_source"] == "deterministic_extracted"
```

```python
# backend/tests/imports/test_import_models.py
def test_import_transaction_drafts_include_proposal_columns_after_init_database():
    database_manager.reset_database(reset_type="imports")
    database_manager.init_database()

    transaction_columns = {
        column["name"] for column in inspect(engine).get_columns("import_transaction_drafts")
    }

    assert {
        "proposed_transaction_type",
        "proposed_expense_category",
        "proposed_income_category",
        "proposed_transfer_category",
        "proposal_source",
    } <= transaction_columns
```

- [ ] **Step 2: Run the targeted backend tests and verify they fail**

Run:

```bash
cd backend && pytest tests/imports/test_contracts.py tests/imports/test_import_models.py -k "proposal" -v
```

Expected:

- FAIL because `ExtractedTransaction` does not accept proposal fields yet
- FAIL because `import_transaction_drafts` has no proposal columns yet

- [ ] **Step 3: Implement the proposal-field contract, response shape, and runtime migration**

```python
# backend/app/imports/contracts.py
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    TransactionType,
    TransferCategory,
)


class ExtractedTransaction(BaseModel):
    transaction_date: str
    source_description: str
    canonical_description_en: Optional[str] = None
    signed_amount: float
    currency: str
    debit_credit: str
    proposed_transaction_type: TransactionType | None = None
    proposed_expense_category: ExpenseCategory | None = None
    proposed_income_category: IncomeCategory | None = None
    proposed_transfer_category: TransferCategory | None = None
    proposal_source: Literal["deterministic_extracted", "ai_extracted", "user_edited"] | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    source_locator: str
    edit_source: Literal["deterministic_extracted", "ai_extracted", "user_edited"] = "ai_extracted"
```

```python
# backend/app/models/imports.py
from sqlalchemy import Enum
from ..models.transaction import ExpenseCategory, IncomeCategory, TransactionType, TransferCategory


class ImportTransactionDraft(Base):
    __tablename__ = "import_transaction_drafts"

    id = Column(Integer, primary_key=True, index=True)
    import_statement_draft_id = Column(Integer, ForeignKey("import_statement_drafts.id"), nullable=False, index=True)
    transaction_date = Column(Date, nullable=True)
    source_description = Column(Text, nullable=False)
    canonical_description_en = Column(Text, nullable=True)
    signed_amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    debit_credit = Column(String(10), nullable=True)
    source_locator = Column(String(255), nullable=False)
    inferred_category = Column(String(100), nullable=True)
    category_source = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    field_confidence = Column(Text, nullable=True)
    raw_fields = Column(Text, nullable=True)
    edit_source = Column(String(50), nullable=False, default="ai_extracted")
    proposed_transaction_type = Column(Enum(TransactionType), nullable=True)
    proposed_expense_category = Column(Enum(ExpenseCategory), nullable=True)
    proposed_income_category = Column(Enum(IncomeCategory), nullable=True)
    proposed_transfer_category = Column(Enum(TransferCategory), nullable=True)
    proposal_source = Column(String(50), nullable=True)
```

```python
# backend/app/schemas/imports.py
class ImportTransactionDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_date: date | None = None
    source_description: str
    canonical_description_en: str | None = None
    signed_amount: float
    currency: str
    debit_credit: str | None = None
    source_locator: str
    proposed_transaction_type: str | None = None
    proposed_expense_category: str | None = None
    proposed_income_category: str | None = None
    proposed_transfer_category: str | None = None
    proposal_source: str | None = None
    confidence: float | None = None
    field_confidence: dict[str, float] | None = None
    raw_fields: dict[str, Any] | None = None
    edit_source: str
    display_amount: float | None = None
    display_currency: str | None = None
    display_fx_rate: float | None = None
    display_rate_date: date | None = None
    display_is_available: bool | None = None
    display_unavailable_reason: str | None = None


def build_import_transaction_draft_response_payload(transaction_draft: Any, display_money: DisplayMoney) -> dict[str, Any]:
    payload = {
        "id": transaction_draft.id,
        "transaction_date": transaction_draft.transaction_date,
        "source_description": transaction_draft.source_description,
        "canonical_description_en": transaction_draft.canonical_description_en,
        "signed_amount": transaction_draft.signed_amount,
        "currency": transaction_draft.currency,
        "debit_credit": transaction_draft.debit_credit,
        "source_locator": transaction_draft.source_locator,
        "proposed_transaction_type": (
            transaction_draft.proposed_transaction_type.value
            if transaction_draft.proposed_transaction_type is not None
            else None
        ),
        "proposed_expense_category": (
            transaction_draft.proposed_expense_category.value
            if transaction_draft.proposed_expense_category is not None
            else None
        ),
        "proposed_income_category": (
            transaction_draft.proposed_income_category.value
            if transaction_draft.proposed_income_category is not None
            else None
        ),
        "proposed_transfer_category": (
            transaction_draft.proposed_transfer_category.value
            if transaction_draft.proposed_transfer_category is not None
            else None
        ),
        "proposal_source": transaction_draft.proposal_source,
        "confidence": transaction_draft.confidence,
        "field_confidence": None,
        "raw_fields": None,
        "edit_source": transaction_draft.edit_source,
    }
    payload.update(serialize_display_money(display_money))
    return payload
```

```python
# backend/app/migrations/migrate_import_transaction_draft_proposals.py
from sqlalchemy import inspect, text

from app.database import engine


def migrate_import_transaction_draft_proposals() -> None:
    inspector = inspect(engine)
    if "import_transaction_drafts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("import_transaction_drafts")}
    with engine.begin() as conn:
        if "proposed_transaction_type" not in columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_transaction_type VARCHAR(50)"))
        if "proposed_expense_category" not in columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_expense_category VARCHAR(100)"))
        if "proposed_income_category" not in columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_income_category VARCHAR(100)"))
        if "proposed_transfer_category" not in columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN proposed_transfer_category VARCHAR(100)"))
        if "proposal_source" not in columns:
            conn.execute(text("ALTER TABLE import_transaction_drafts ADD COLUMN proposal_source VARCHAR(50)"))
```

```python
# backend/app/database_manager.py
from .migrations.migrate_import_transaction_draft_proposals import migrate_import_transaction_draft_proposals


def ensure_runtime_schema_compatibility() -> None:
    _ensure_classification_transaction_columns()
    _ensure_import_traceability_transaction_columns()
    migrate_import_transaction_draft_proposals()
```

```python
# backend/app/migrations/run_migrations.py
from app.migrations.migrate_import_transaction_draft_proposals import (
    migrate_import_transaction_draft_proposals,
)


def run_migrations():
    logger.info("Starting migrations...")
    ensure_runtime_schema_compatibility()
    migrate_import_transaction_draft_proposals()
    migrate_classification_assistant()
    migrate_expense_type_values()
    with Session(engine) as db:
        summary = migrate_europe_iban_reclassification(db)
    logger.info("Europe IBAN cleanup migration summary: %s", summary)
    logger.info("All migrations completed successfully")
```

- [ ] **Step 4: Run the targeted backend tests and verify they pass**

Run:

```bash
cd backend && pytest tests/imports/test_contracts.py tests/imports/test_import_models.py -k "proposal" -v
```

Expected:

- PASS for proposal-field serialization
- PASS for runtime-added import-draft columns

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/contracts.py backend/app/models/imports.py backend/app/schemas/imports.py backend/app/database_manager.py backend/app/migrations/migrate_import_transaction_draft_proposals.py backend/app/migrations/run_migrations.py backend/tests/imports/test_contracts.py backend/tests/imports/test_import_models.py
git commit -m "feat: add import draft proposal contract"
```

## Task 2: Detect Nexo CSVs And Extract Reviewable Rows

**Files:**
- Create: `backend/app/imports/nexo_csv.py`
- Create: `backend/tests/imports/fixtures/nexo_csv.py`
- Create: `backend/tests/imports/test_nexo_csv.py`
- Modify: `backend/app/imports/contracts.py`
- Modify: `backend/app/imports/detection.py`
- Modify: `backend/tests/imports/test_detection.py`

- [ ] **Step 1: Write the failing detector and extractor tests**

```python
# backend/tests/imports/test_detection.py
from tests.imports.fixtures.nexo_csv import build_nexo_csv_bytes, nexo_row


def test_detector_flags_nexo_csv_exports():
    sample = build_nexo_csv_bytes(
        nexo_row(
            transaction="NXT_PURCHASE_1",
            row_type="Nexo Card Purchase",
            input_currency="xUSD",
            input_amount="-6.24",
            details="approved / Albert Heijn 3143 | Gent | BEL",
            occurred_at="2026-03-25 17:19:21",
        )
    )

    result = ImportDetector().detect(
        filename="nexo_transactions.csv",
        content_type="text/csv",
        sample=sample,
    )

    assert result.strategy_key == ImportStrategyKey.NEXO_CSV
    assert result.provider_hint == "nexo"
    assert result.charset_hint == "utf-8"
```

```python
# backend/tests/imports/test_nexo_csv.py
from app.imports.nexo_csv import NexoCsvExtractor
from tests.imports.fixtures.nexo_csv import build_nexo_csv_bytes, nexo_row


def test_nexo_csv_extractor_emits_purchase_fee_and_cashout_rows(tmp_path):
    csv_path = tmp_path / "nexo.csv"
    csv_path.write_bytes(
        build_nexo_csv_bytes(
            nexo_row("NXT_PURCHASE_1", "Nexo Card Purchase", "xUSD", "-6.24", "approved / Albert Heijn 3143 | Gent | BEL", "2026-03-25 17:19:21"),
            nexo_row("NXT_FEE_1", "Nexo Card Transaction Fee", "xUSD", "-0.16", "approved / 2.0% Weekday FX Fee", "2026-03-25 17:19:22"),
            nexo_row("NXT_CASHOUT_1", "Transfer Out", "USDC", "-120.00", "approved / Bank transfer to BE55000000000001", "2026-03-26 18:19:22"),
        )
    )

    evidence, result = NexoCsvExtractor().extract(file_path=csv_path, session_id="12", attempt_number=1)

    assert result.extractor_id == "nexo_csv_v1"
    assert [tx.source_description for tx in result.transactions] == [
        "Albert Heijn 3143 | Gent | BEL",
        "2.0% Weekday FX Fee",
        "Bank transfer to BE55000000000001",
    ]
    assert result.transactions[0].currency == "xUSD"
    assert result.transactions[1].proposed_expense_category.value == "Financial Fees"
    assert result.transactions[2].proposed_transaction_type.value == "Transfer"
    assert result.transactions[2].proposed_transfer_category.value == "Internal Transfer"
    assert evidence.text_blocks[0]["page_number"] == 1
```

```python
def test_nexo_csv_extractor_blocks_when_no_reviewable_rows_remain(tmp_path):
    csv_path = tmp_path / "nexo.csv"
    csv_path.write_bytes(
        build_nexo_csv_bytes(
            nexo_row("NXT_CASHBACK_1", "Cashback", "NEXO", "0.12", "approved / Cashback", "2026-03-25 10:00:00"),
            nexo_row("NXT_INTERNAL_1", "Transfer Out", "USDC", "-33.45", "approved / Auto Transfer from Savings Wallet to Credit Line Wallet", "2026-03-25 10:01:00"),
        )
    )

    _, result = NexoCsvExtractor().extract(file_path=csv_path, session_id="12", attempt_number=1)

    assert result.transactions == []
    assert result.issues[0].code == "no_importable_nexo_rows"
    assert result.issues[0].blocking is True


def test_nexo_csv_extractor_warns_on_ambiguous_transfer_out(tmp_path):
    csv_path = tmp_path / "nexo.csv"
    csv_path.write_bytes(
        build_nexo_csv_bytes(
            nexo_row("NXT_UNKNOWN_1", "Transfer Out", "USDC", "-50.00", "approved / Wallet move pending review", "2026-03-25 10:02:00"),
            nexo_row("NXT_PURCHASE_1", "Nexo Card Purchase", "xUSD", "-6.24", "approved / Albert Heijn 3143 | Gent | BEL", "2026-03-25 17:19:21"),
        )
    )

    _, result = NexoCsvExtractor().extract(file_path=csv_path, session_id="12", attempt_number=1)

    assert len(result.transactions) == 1
    assert result.issues[0].code == "nexo_ambiguous_transfer_out"
    assert result.issues[0].blocking is False
```

- [ ] **Step 2: Run the detector and extractor tests and verify they fail**

Run:

```bash
cd backend && pytest tests/imports/test_detection.py tests/imports/test_nexo_csv.py -v
```

Expected:

- FAIL because `ImportStrategyKey.NEXO_CSV` does not exist
- FAIL because `NexoCsvExtractor` does not exist

- [ ] **Step 3: Implement Nexo detection, shared CSV fixtures, and the deterministic extractor**

```python
# backend/tests/imports/fixtures/nexo_csv.py
import csv
import io


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


def nexo_row(transaction: str, row_type: str, input_currency: str, input_amount: str, details: str, occurred_at: str) -> list[str]:
    return [
        transaction,
        row_type,
        input_currency,
        input_amount,
        input_currency,
        input_amount.lstrip("-"),
        "$0.00",
        "-",
        "-",
        details,
        occurred_at,
        details,
    ]


def build_nexo_csv_bytes(*rows: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(NEXO_HEADER)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")
```

```python
# backend/app/imports/contracts.py
class ImportStrategyKey(str, Enum):
    BELFIUS_CSV = "belfius_csv"
    BEOBANK_CSV = "beobank_csv"
    NEXO_CSV = "nexo_csv"
    PDF_STATEMENT = "pdf_statement"
    UNKNOWN = "unknown"
```

```python
# backend/app/imports/detection.py
import csv
import io

from app.imports.contracts import DetectionResult, ImportStrategyKey
from app.imports.nexo_csv import NEXO_HEADER


class ImportDetector:
    def detect(self, *, filename: str, content_type: str, sample: bytes) -> DetectionResult:
        if sample.startswith(b"%PDF-"):
            return DetectionResult(strategy_key=ImportStrategyKey.PDF_STATEMENT, confidence=1.0)

        charset_hint = "utf-8"
        try:
            decoded = sample.decode("utf-8")
        except UnicodeDecodeError:
            charset_hint = "latin-1"
            decoded = sample.decode("latin-1")

        reader = csv.reader(io.StringIO(decoded))
        header = next((row for row in reader if any(cell.strip() for cell in row)), [])
        if header == NEXO_HEADER:
            return DetectionResult(
                strategy_key=ImportStrategyKey.NEXO_CSV,
                provider_hint="nexo",
                charset_hint=charset_hint,
                confidence=1.0,
                password_protected=False,
                notes=["Matched deterministic Nexo CSV header"],
            )

        return DetectionResult(
            strategy_key=ImportStrategyKey.UNKNOWN,
            provider_hint=None,
            language_hint=None,
            charset_hint=charset_hint,
            confidence=0.0,
            page_count=None,
            password_protected=False,
            notes=["No registered detector matched the uploaded file"],
        )
```

```python
# backend/app/imports/nexo_csv.py
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .contracts import ExtractionResult, ExtractedTransaction, ImportIssue, RawEvidence
from app.models.transaction import ExpenseCategory, TransactionType, TransferCategory


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


class NexoCsvExtractor:
    INTERNAL_MARKERS = ("auto transfer", "savings wallet", "credit line wallet")
    EXTERNAL_MARKERS = ("bank transfer", "sepa")
    IBAN_TOKEN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}$")

    def extract(self, *, file_path: str | Path, session_id: str, attempt_number: int) -> tuple[RawEvidence, ExtractionResult]:
        raw_text, charset, rows = self._read_rows(file_path)
        raw_artifact_ref = f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json"
        evidence_snippets = []
        transactions: list[ExtractedTransaction] = []
        issues: list[ImportIssue] = []
        seen_dates: list[str] = []

        for row_number, row in enumerate(rows, start=2):
            decision, payload, issue = self._classify_row(row, row_number)
            evidence_snippets.append(
                {
                    "row_number": row_number,
                    "transaction_id": row["Transaction"],
                    "type": row["Type"],
                    "details": row.get("normalizedDisplayDetails") or row.get("Details"),
                    "decision": decision,
                    "reason": issue.code if issue is not None else decision,
                }
            )
            if payload is not None:
                transactions.append(payload)
                seen_dates.append(payload.transaction_date)
            if issue is not None:
                issues.append(issue)

        if not transactions:
            issues.insert(
                0,
                ImportIssue(
                    code="no_importable_nexo_rows",
                    message="The Nexo CSV did not contain any reviewable outgoing rows.",
                    blocking=True,
                ),
            )

        evidence = RawEvidence(
            text_blocks=[{"page_number": 1, "raw_text": raw_text, "lines": raw_text.splitlines()}],
            ocr_blocks=[],
            snippets=evidence_snippets,
        )
        return evidence, ExtractionResult(
            extractor_id="nexo_csv_v1",
            raw_artifact_ref=raw_artifact_ref,
            source_metadata={"provider_hint": "nexo", "file_type": "csv", "charset": charset},
            statement_metadata={
                "account_number_hint": "NEXO",
                "card_number_hint": None,
                "currency": None,
                "statement_period_start": min(seen_dates) if seen_dates else None,
                "statement_period_end": max(seen_dates) if seen_dates else None,
            },
            transactions=transactions,
            issues=issues,
            overall_confidence=1.0 if transactions else 0.0,
        )

    def _read_rows(self, file_path: str | Path) -> tuple[str, str, list[dict[str, str]]]:
        path = Path(file_path)
        last_error: UnicodeDecodeError | None = None
        for charset in ("utf-8", "latin-1"):
            try:
                raw_text = path.read_text(encoding=charset)
                reader = csv.DictReader(io.StringIO(raw_text))
                return raw_text, charset, [dict(row) for row in reader]
            except UnicodeDecodeError as exc:
                last_error = exc
        raise last_error or UnicodeDecodeError("utf-8", b"", 0, 1, "Unable to decode Nexo CSV")

    def _classify_row(
        self,
        row: dict[str, str],
        row_number: int,
    ) -> tuple[str, ExtractedTransaction | None, ImportIssue | None]:
        row_type = (row.get("Type") or "").strip()
        details = (row.get("normalizedDisplayDetails") or row.get("Details") or "").strip()
        normalized_details = " ".join(details.casefold().split())
        locator = f"csv:r{row_number}:{(row.get('Transaction') or '').strip()}"
        amount = float(row.get("Input Amount") or 0)

        if normalized_details.startswith("rejected /"):
            return "skipped_rejected", None, None

        if row_type == "Nexo Card Purchase" and amount < 0:
            return "import_expense", self._build_transaction(
                row=row,
                row_number=row_number,
                source_description=self._clean_description(details),
                proposed_transaction_type=TransactionType.EXPENSE,
                proposed_expense_category=None,
                proposed_transfer_category=None,
            ), None

        if row_type == "Nexo Card Transaction Fee" and amount < 0:
            return "import_fee", self._build_transaction(
                row=row,
                row_number=row_number,
                source_description=self._clean_description(details),
                proposed_transaction_type=TransactionType.EXPENSE,
                proposed_expense_category=ExpenseCategory.FINANCIAL_FEES,
                proposed_transfer_category=None,
            ), None

        if row_type == "Transfer Out" and amount < 0:
            if any(marker in normalized_details for marker in self.INTERNAL_MARKERS):
                return "skipped_internal_plumbing", None, None
            if self._matches_external_cashout(normalized_details):
                return "import_transfer", self._build_transaction(
                    row=row,
                    row_number=row_number,
                    source_description=self._clean_description(details),
                    proposed_transaction_type=TransactionType.TRANSFER,
                    proposed_expense_category=None,
                    proposed_transfer_category=TransferCategory.INTERNAL_TRANSFER,
                ), None
            return "skipped_ambiguous_transfer", None, ImportIssue(
                code="nexo_ambiguous_transfer_out",
                message="Transfer Out row did not match an internal-wallet or external-cashout rule.",
                blocking=False,
                transaction_ref=locator,
            )

        if row_type in {"Cashback", "Exchange Credit", "Credit Card Withdrawal Credit"}:
            return "skipped_known_non_transaction", None, None

        return "skipped_unknown_type", None, ImportIssue(
            code="nexo_unknown_row_type",
            message=f"Unsupported Nexo row type: {row_type or 'missing'}",
            blocking=False,
            transaction_ref=locator,
        )

    def _build_transaction(
        self,
        *,
        row: dict[str, str],
        row_number: int,
        source_description: str,
        proposed_transaction_type: TransactionType,
        proposed_expense_category: ExpenseCategory | None,
        proposed_transfer_category: TransferCategory | None,
    ) -> ExtractedTransaction:
        return ExtractedTransaction(
            transaction_date=(row["Date / Time (UTC)"] or "").split(" ")[0],
            source_description=source_description,
            canonical_description_en=None,
            signed_amount=float(row["Input Amount"]),
            currency=(row["Input Currency"] or "").strip(),
            debit_credit="debit",
            source_locator=f"csv:r{row_number}:{(row.get('Transaction') or '').strip()}",
            proposed_transaction_type=proposed_transaction_type,
            proposed_expense_category=proposed_expense_category,
            proposed_income_category=None,
            proposed_transfer_category=proposed_transfer_category,
            proposal_source="deterministic_extracted",
            confidence={},
            edit_source="deterministic_extracted",
        )

    def _clean_description(self, details: str) -> str:
        return re.sub(r"^(approved|rejected)\s*/\s*", "", details.strip(), flags=re.IGNORECASE)

    def _matches_external_cashout(self, normalized_details: str) -> bool:
        if any(marker in normalized_details for marker in self.EXTERNAL_MARKERS):
            return True

        for token in normalized_details.upper().split():
            compact = token.replace(" ", "")
            if self.IBAN_TOKEN_RE.match(compact):
                return True
        return False
```

- [ ] **Step 4: Run the detector and extractor tests and verify they pass**

Run:

```bash
cd backend && pytest tests/imports/test_detection.py tests/imports/test_nexo_csv.py -v
```

Expected:

- PASS for header detection
- PASS for purchase/fee/cash-out extraction
- PASS for ambiguous `Transfer Out` warning handling
- PASS for blocking empty-session outcome

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/contracts.py backend/app/imports/detection.py backend/app/imports/nexo_csv.py backend/tests/imports/fixtures/nexo_csv.py backend/tests/imports/test_detection.py backend/tests/imports/test_nexo_csv.py
git commit -m "feat: detect and extract Nexo csv imports"
```

## Task 3: Wire Workflow Dispatch, Draft Persistence, And Approval Commit Rules

**Files:**
- Modify: `backend/app/imports/workflow.py`
- Modify: `backend/tests/imports/test_import_workflow.py`

- [ ] **Step 1: Write the failing workflow tests for Nexo dispatch, proposal persistence, and invalid combinations**

```python
# backend/tests/imports/test_import_workflow.py
from app.models.transaction import ExpenseCategory, TransactionType, TransferCategory


def _successful_nexo_result(session_id: int, attempt_number: int) -> tuple[RawEvidence, ExtractionResult]:
    return (
        RawEvidence(
            text_blocks=[{"page_number": 1, "raw_text": "Transaction,Type,...", "lines": ["Transaction,Type,..."]}],
            ocr_blocks=[],
            snippets=[],
        ),
        ExtractionResult(
            extractor_id="nexo_csv_v1",
            raw_artifact_ref=f"imports/{session_id}/attempts/{attempt_number}/evidence/raw.json",
            source_metadata={"provider_hint": "nexo", "file_type": "csv"},
            statement_metadata={
                "account_number_hint": "NEXO",
                "card_number_hint": None,
                "currency": None,
                "statement_period_start": "2026-03-25",
                "statement_period_end": "2026-03-26",
            },
            transactions=[
                ExtractedTransaction(
                    transaction_date="2026-03-25",
                    source_description="2.0% Weekday FX Fee",
                    signed_amount=-0.16,
                    currency="xUSD",
                    debit_credit="debit",
                    source_locator="csv:r3:NXT_FEE_1",
                    proposed_transaction_type=TransactionType.EXPENSE,
                    proposed_expense_category=ExpenseCategory.FINANCIAL_FEES,
                    proposal_source="deterministic_extracted",
                    edit_source="deterministic_extracted",
                ),
                ExtractedTransaction(
                    transaction_date="2026-03-26",
                    source_description="Bank transfer to BE55000000000001",
                    signed_amount=-120.0,
                    currency="USDC",
                    debit_credit="debit",
                    source_locator="csv:r4:NXT_CASHOUT_1",
                    proposed_transaction_type=TransactionType.TRANSFER,
                    proposed_transfer_category=TransferCategory.INTERNAL_TRANSFER,
                    proposal_source="deterministic_extracted",
                    edit_source="deterministic_extracted",
                ),
            ],
            issues=[],
            overall_confidence=1.0,
        ),
    )


def test_extract_detected_session_dispatches_nexo_csv_and_persists_proposals(db_session, tmp_path):
    csv_path = tmp_path / "nexo.csv"
    csv_path.write_text("Transaction,Type,...", encoding="utf-8")
    session, _ = ImportPipelineService(db_session).start_upload(
        filename="nexo.csv",
        content_type="text/csv",
        file_bytes=csv_path.read_bytes(),
    )
    session.strategy_key = ImportStrategyKey.NEXO_CSV.value
    db_session.commit()

    class StubNexoExtractor:
        def extract(self, *, file_path, session_id, attempt_number):
            return _successful_nexo_result(int(session_id), attempt_number)

    extracted = ImportWorkflowService(db_session, nexo_csv_extractor=StubNexoExtractor()).extract_detected_session(session.id)

    assert extracted.status == ImportSessionStatus.AWAITING_REVIEW.value
    drafts = db_session.query(ImportTransactionDraft).order_by(ImportTransactionDraft.id.asc()).all()
    assert drafts[0].proposed_transaction_type.value == "Expense"
    assert drafts[0].proposed_expense_category.value == "Financial Fees"
    assert drafts[1].proposed_transaction_type.value == "Transfer"
    assert drafts[1].proposed_transfer_category.value == "Internal Transfer"


def test_approve_session_rejects_invalid_proposal_combinations(db_session):
    session = ImportSession(
        file_name="nexo.csv",
        file_hash="nexo-invalid",
        mime_type="text/csv",
        status=ImportSessionStatus.AWAITING_REVIEW.value,
        strategy_key=ImportStrategyKey.NEXO_CSV.value,
        provider_hint="nexo",
    )
    db_session.add(session)
    db_session.flush()

    statement = ImportStatementDraft(
        import_session_id=session.id,
        attempt_number=1,
        account_number_hint="NEXO",
        transaction_count=1,
        review_status="awaiting_review",
        overall_confidence=1.0,
    )
    db_session.add(statement)
    db_session.flush()

    draft = ImportTransactionDraft(
        import_statement_draft_id=statement.id,
        transaction_date=date(2026, 3, 26),
        source_description="Invalid combination",
        canonical_description_en=None,
        signed_amount=-120.0,
        currency="USDC",
        debit_credit="debit",
        source_locator="csv:r4:NXT_INVALID_1",
        proposal_source="deterministic_extracted",
        edit_source="deterministic_extracted",
    )
    db_session.add(draft)
    db_session.flush()

    draft.proposed_transaction_type = TransactionType.TRANSFER
    draft.proposed_expense_category = ExpenseCategory.FINANCIAL_FEES
    db_session.commit()

    with pytest.raises(ImportSessionStateError, match="invalid proposal combination"):
        ImportWorkflowService(db_session).approve_session(session.id)
```

- [ ] **Step 2: Run the workflow tests and verify they fail**

Run:

```bash
cd backend && pytest tests/imports/test_import_workflow.py -k "nexo or proposal" -v
```

Expected:

- FAIL because workflow only accepts `pdf_statement`
- FAIL because proposal columns are not persisted or validated in workflow

- [ ] **Step 3: Implement strategy dispatch, proposal persistence, validation, and explicit Nexo source-bank mapping**

```python
# backend/app/imports/workflow.py
from app.models.transaction import TransactionType
from .nexo_csv import NexoCsvExtractor


class ImportWorkflowService:
    def __init__(
        self,
        db: Session,
        pdf_statement_extractor: PdfStatementExtractor | None = None,
        nexo_csv_extractor: NexoCsvExtractor | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.db = db
        self.pdf_statement_extractor = pdf_statement_extractor or PdfStatementExtractor()
        self.nexo_csv_extractor = nexo_csv_extractor or NexoCsvExtractor()
        self.artifacts = artifacts or ArtifactStore()

    def extract_detected_session(self, session_id: int) -> ImportSession:
        session = self._get_session(session_id)
        if session.status != ImportSessionStatus.DETECTED.value:
            raise ImportSessionStateError(f"Import session {session_id} must be in detected state.")
        if session.strategy_key not in {
            ImportStrategyKey.PDF_STATEMENT.value,
            ImportStrategyKey.NEXO_CSV.value,
        }:
            raise ImportSessionStateError(f"Import session {session_id} does not use a reviewable strategy.")

        attempt_number = self._next_attempt_number(session.id)
        original_file = self.artifacts.session_dir(str(session.id)) / "original" / session.file_name
        result: ExtractionResult | None = None

        if not original_file.exists():
            raise FileNotFoundError(f"Original upload missing for import session {session.id}.")

        evidence, result = self._extract_with_strategy(
            strategy_key=session.strategy_key,
            file_path=original_file,
            session_id=str(session.id),
            attempt_number=attempt_number,
        )
        self.artifacts.write_raw_evidence(str(session.id), attempt_number, evidence)
        self.artifacts.write_normalized_result(str(session.id), attempt_number, result)
        session.extractor_id = result.extractor_id
        session.raw_artifact_ref = result.raw_artifact_ref
        session.provider_hint = result.source_metadata.get("provider_hint") or session.provider_hint
        session.language_hint = result.source_metadata.get("language") or session.language_hint
        self._persist_issues(session.id, attempt_number, result)
        if any(issue.blocking for issue in result.issues):
            assert_transition_allowed(ImportSessionStatus(session.status), ImportSessionStatus.FAILED)
            session.status = ImportSessionStatus.FAILED.value
            session.error_stage = "extraction"
            session.error_message = self._failure_message(result)
        else:
            self._persist_statement_draft(session.id, attempt_number, result)
            self._advance_to_awaiting_review(session)
            session.error_stage = None
            session.error_message = None
        self._write_workflow_meta(
            session_id=str(session.id),
            attempt_number=attempt_number,
            state=session.status,
            extraction_succeeded=result is not None,
        )
        self.db.commit()
        self.db.refresh(session)
        return session

    def _extract_with_strategy(self, *, strategy_key: str, file_path, session_id: str, attempt_number: int):
        if strategy_key == ImportStrategyKey.PDF_STATEMENT.value:
            return self.pdf_statement_extractor.extract(
                file_path=file_path,
                session_id=session_id,
                attempt_number=attempt_number,
            )
        if strategy_key == ImportStrategyKey.NEXO_CSV.value:
            return self.nexo_csv_extractor.extract(
                file_path=file_path,
                session_id=session_id,
                attempt_number=attempt_number,
            )
        raise ImportSessionStateError(f"Unsupported review extraction strategy: {strategy_key}")

    def _persist_statement_draft(self, session_id: int, attempt_number: int, result: ExtractionResult) -> None:
        metadata = result.statement_metadata
        statement_draft = ImportStatementDraft(
            import_session_id=session_id,
            attempt_number=attempt_number,
            statement_period_start=self._parse_iso_date(metadata.get("statement_period_start")),
            statement_period_end=self._parse_iso_date(metadata.get("statement_period_end")),
            transaction_count=len(result.transactions),
            account_number_hint=metadata.get("account_number_hint"),
            card_number_hint=metadata.get("card_number_hint"),
            currency=metadata.get("currency"),
            overall_confidence=result.overall_confidence,
            review_status="awaiting_review",
        )
        self.db.add(statement_draft)
        self.db.flush()
        for transaction in result.transactions:
            self.db.add(
                ImportTransactionDraft(
                    import_statement_draft_id=statement_draft.id,
                    transaction_date=self._parse_iso_date(transaction.transaction_date),
                    source_description=transaction.source_description,
                    canonical_description_en=transaction.canonical_description_en,
                    signed_amount=transaction.signed_amount,
                    currency=transaction.currency,
                    debit_credit=transaction.debit_credit,
                    source_locator=transaction.source_locator,
                    proposed_transaction_type=transaction.proposed_transaction_type,
                    proposed_expense_category=transaction.proposed_expense_category,
                    proposed_income_category=transaction.proposed_income_category,
                    proposed_transfer_category=transaction.proposed_transfer_category,
                    proposal_source=transaction.proposal_source,
                    confidence=self._transaction_confidence(transaction, result),
                    field_confidence=json.dumps(transaction.confidence, sort_keys=True),
                    raw_fields=json.dumps(transaction.model_dump(mode="json"), sort_keys=True),
                    edit_source=transaction.edit_source,
                )
            )

    def _classification_fields_from_draft(self, draft: ImportTransactionDraft) -> dict:
        tx_type = draft.proposed_transaction_type
        expense = draft.proposed_expense_category
        income = draft.proposed_income_category
        transfer = draft.proposed_transfer_category

        if tx_type is None:
            if any(value is not None for value in (expense, income, transfer)):
                raise ImportSessionStateError("invalid proposal combination: category requires transaction type")
            return {
                "transaction_type": None,
                "expense_category": None,
                "income_category": None,
                "transfer_category": None,
            }

        if tx_type == TransactionType.EXPENSE:
            if income is not None or transfer is not None:
                raise ImportSessionStateError("invalid proposal combination: expense rows cannot carry income/transfer categories")
            return {
                "transaction_type": tx_type,
                "expense_category": expense,
                "income_category": None,
                "transfer_category": None,
            }

        if tx_type == TransactionType.INCOME:
            if expense is not None or transfer is not None:
                raise ImportSessionStateError("invalid proposal combination: income rows cannot carry expense/transfer categories")
            return {
                "transaction_type": tx_type,
                "expense_category": None,
                "income_category": income,
                "transfer_category": None,
            }

        if expense is not None or income is not None:
            raise ImportSessionStateError("invalid proposal combination: transfer rows cannot carry expense/income categories")
        return {
            "transaction_type": tx_type,
            "expense_category": None,
            "income_category": None,
            "transfer_category": transfer,
        }

    def _build_committed_transaction(self, import_session_id: int, statement: ImportStatementDraft, draft: ImportTransactionDraft) -> Transaction:
        classification_fields = self._classification_fields_from_draft(draft)
        transaction_payload = TransactionCreate(
            account_number=self._statement_account_number(statement),
            transaction_date=draft.transaction_date,
            amount=draft.signed_amount,
            currency=draft.currency,
            description=draft.source_description,
            counterparty_name=None,
            counterparty_account=None,
            transaction_type=classification_fields["transaction_type"],
            expense_category=classification_fields["expense_category"],
            income_category=classification_fields["income_category"],
            transfer_category=classification_fields["transfer_category"],
            classification_source=None,
            recurrence_pattern_id=None,
            source_bank=self._source_bank_name(statement),
        )
        payload = transaction_payload.model_dump()
        payload["import_session_id"] = import_session_id
        payload["import_source_locator"] = draft.source_locator
        payload["import_source_description"] = draft.source_description
        payload["canonical_description_en"] = draft.canonical_description_en
        return Transaction(**payload)

    def _session_bank_name(self, session_id: int) -> str:
        session = self.db.get(ImportSession, session_id)
        normalized = ((session.provider_hint if session is not None else None) or "").casefold()
        if normalized == "belfius":
            return "Belfius"
        if normalized == "beobank":
            return "Beobank"
        if normalized == "nexo":
            return "Nexo"
        return session.provider_hint.title() if session and session.provider_hint else "Unknown"
```

- [ ] **Step 4: Run the workflow tests and verify they pass**

Run:

```bash
cd backend && pytest tests/imports/test_import_workflow.py -k "nexo or proposal" -v
```

Expected:

- PASS for Nexo extractor dispatch
- PASS for proposal persistence
- PASS for invalid-combination rejection

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/workflow.py backend/tests/imports/test_import_workflow.py
git commit -m "feat: commit import proposal fields through workflow"
```

## Task 4: Route Uploads And Batch CSV Detection Through The Review Pipeline

**Files:**
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/app/imports/batch_folder.py`
- Modify: `backend/tests/imports/test_import_review_api.py`
- Modify: `backend/tests/imports/test_import_batch_api.py`
- Reuse: `backend/tests/imports/fixtures/nexo_csv.py`

- [ ] **Step 1: Write the failing API and batch tests for Nexo upload and batch routing**

```python
# backend/tests/imports/test_import_review_api.py
from tests.imports.fixtures.nexo_csv import build_nexo_csv_bytes, nexo_row


def _upload_nexo_csv(expected_status=200):
    response = client.post(
        "/imports/upload",
        files={
            "file": (
                "nexo.csv",
                build_nexo_csv_bytes(
                    nexo_row("NXT_PURCHASE_1", "Nexo Card Purchase", "xUSD", "-6.24", "approved / Albert Heijn 3143 | Gent | BEL", "2026-03-25 17:19:21"),
                    nexo_row("NXT_FEE_1", "Nexo Card Transaction Fee", "xUSD", "-0.16", "approved / 2.0% Weekday FX Fee", "2026-03-25 17:19:22"),
                    nexo_row("NXT_CASHOUT_1", "Transfer Out", "USDC", "-120.00", "approved / Bank transfer to BE55000000000001", "2026-03-26 18:19:22"),
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == expected_status
    return response.json()


def test_upload_endpoint_returns_reviewable_nexo_session_shape(db_session):
    payload = _upload_nexo_csv()

    assert payload["status"] == "awaiting_review"
    assert payload["strategy_key"] == "nexo_csv"
    assert payload["provider_hint"] == "nexo"
    assert payload["extractor_id"] == "nexo_csv_v1"


def test_get_review_payload_exposes_nexo_proposal_fields(db_session):
    session = _upload_nexo_csv()

    response = client.get(f"/imports/{session['id']}", headers={"X-Reporting-Currency": "USD"})

    assert response.status_code == 200
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["currency"] == "xUSD"
    assert first_transaction["proposed_transaction_type"] == "Expense"
    assert first_transaction["proposal_source"] == "deterministic_extracted"
    assert payload["transactions"][1]["proposed_expense_category"] == "Financial Fees"
    assert payload["transactions"][2]["proposed_transfer_category"] == "Internal Transfer"


def test_approve_nexo_import_commits_expense_fee_and_transfer_rows(db_session):
    session = _upload_nexo_csv()

    response = client.post(f"/imports/{session['id']}/approve")

    assert response.status_code == 200
    db_session.expire_all()
    transactions = db_session.query(Transaction).order_by(Transaction.id.asc()).all()
    assert [transaction.transaction_type.value for transaction in transactions] == [
        "Expense",
        "Expense",
        "Transfer",
    ]
    assert transactions[1].expense_category.value == "Financial Fees"
    assert transactions[2].transfer_category.value == "Internal Transfer"
```

```python
# backend/tests/imports/test_import_batch_api.py
def test_batch_folder_routes_nexo_csv_to_import_review_session(db_session, monkeypatch, tmp_path):
    batch_dir = tmp_path / "bank_files"
    batch_dir.mkdir()
    (batch_dir / "nexo.csv").write_bytes(
        build_nexo_csv_bytes(
            nexo_row("NXT_PURCHASE_1", "Nexo Card Purchase", "xUSD", "-6.24", "approved / Albert Heijn 3143 | Gent | BEL", "2026-03-25 17:19:21")
        )
    )
    _configure_batch_dir(monkeypatch, batch_dir)

    response = client.post("/imports/batch-folder")

    assert response.status_code == 200
    payload = response.json()
    item = payload["items"][0]
    assert item["status"] == "processed"
    assert item["session_id"] is not None
    assert item["session_status"] == "awaiting_review"
    assert item["strategy_key"] == "nexo_csv"
    assert item["extractor_id"] == "nexo_csv_v1"

    db_session.expire_all()
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(ImportSession).count() == 1
```

- [ ] **Step 2: Run the upload and batch tests and verify they fail**

Run:

```bash
cd backend && pytest tests/imports/test_import_review_api.py tests/imports/test_import_batch_api.py -k "nexo" -v
```

Expected:

- FAIL because `/imports/upload` only auto-extracts PDFs
- FAIL because batch CSVs still go straight to `CsvImportService`

- [ ] **Step 3: Implement upload auto-extraction and batch CSV pre-routing**

```python
# backend/app/routers/imports.py
if detection.strategy_key in {
    ImportStrategyKey.PDF_STATEMENT,
    ImportStrategyKey.NEXO_CSV,
}:
    try:
        session = workflow.extract_detected_session(session.id)
    except Exception:
        logger.warning("Import extraction crashed for session %s", session.id, exc_info=True)
```

```python
# backend/app/imports/batch_folder.py
def _process_file(self, batch_run: ImportBatchRun, item: ImportBatchItem, file_path: Path) -> None:
    if self._is_supported_csv(file_path):
        file_bytes = file_path.read_bytes()
        detection = self.pipeline.detector.detect(
            filename=file_path.name,
            content_type="text/csv",
            sample=file_bytes[:4096],
        )
        if detection.strategy_key == ImportStrategyKey.NEXO_CSV:
            self._process_import_session_file(
                batch_run,
                item,
                file_path=file_path,
                file_bytes=file_bytes,
                content_type="text/csv",
                allowed_strategy=ImportStrategyKey.NEXO_CSV,
            )
            return
        self._process_csv_file(batch_run, item, file_path)
        return

    if self._is_supported_pdf(file_path):
        self._process_import_session_file(
            batch_run,
            item,
            file_path=file_path,
            file_bytes=file_path.read_bytes(),
            content_type="application/pdf",
            allowed_strategy=ImportStrategyKey.PDF_STATEMENT,
        )
        return

    suffix = file_path.suffix.lower() or "(no extension)"
    self._finalize_item(batch_run, item, status="unsupported", message=f"Unsupported batch file type: {suffix}")


def _process_import_session_file(
    self,
    batch_run: ImportBatchRun,
    item: ImportBatchItem,
    *,
    file_path: Path,
    file_bytes: bytes,
    content_type: str,
    allowed_strategy: ImportStrategyKey,
) -> None:
    try:
        session, detection = self.pipeline.start_upload(
            filename=file_path.name,
            content_type=content_type,
            file_bytes=file_bytes,
        )
    except ImportUploadDuplicateError as exc:
        existing_session = self.workflow.get_session_snapshot(exc.existing_session_id)
        self._finalize_item(
            batch_run,
            item,
            file_hash=exc.file_hash,
            status="skipped_existing",
            message=str(exc),
            existing_session_id=existing_session["id"],
            existing_session_status=existing_session["status"],
        )
        return
    except Exception as exc:
        self._finalize_item(batch_run, item, status="failed", message=str(exc))
        return

    if detection.strategy_key != allowed_strategy:
        session = self._mark_session_failed(
            session.id,
            stage="detection",
            message=f"Unsupported import strategy for batch import: {detection.strategy_key.value}",
        )
        snapshot = self.workflow.get_session_snapshot(session.id)
        self._finalize_item(
            batch_run,
            item,
            file_hash=session.file_hash,
            status="failed",
            message=snapshot["error_message"],
            session_id=session.id,
            session_status=snapshot["status"],
            strategy_key=detection.strategy_key.value,
            extractor_id=snapshot["extractor_id"],
        )
        return

    try:
        session = self.workflow.extract_detected_session(session.id)
    except Exception:
        logger.warning("Import extraction crashed during batch run for session %s", session.id, exc_info=True)

    snapshot = self.workflow.get_session_snapshot(session.id)
    item_status = "processed" if snapshot["status"] == ImportSessionStatus.AWAITING_REVIEW.value else "failed"
    self._finalize_item(
        batch_run,
        item,
        file_hash=session.file_hash,
        status=item_status,
        message=None if item_status == "processed" else snapshot["error_message"],
        session_id=session.id,
        session_status=snapshot["status"],
        strategy_key=snapshot["strategy_key"],
        extractor_id=snapshot["extractor_id"],
    )
```

- [ ] **Step 4: Run the upload and batch tests and verify they pass**

Run:

```bash
cd backend && pytest tests/imports/test_import_review_api.py tests/imports/test_import_batch_api.py -k "nexo" -v
```

Expected:

- PASS for `/imports/upload` creating an awaiting-review Nexo session
- PASS for `/imports/batch-folder` creating a review session instead of direct transactions

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/imports.py backend/app/imports/batch_folder.py backend/tests/imports/test_import_review_api.py backend/tests/imports/test_import_batch_api.py
git commit -m "feat: route Nexo csv uploads through import review"
```

## Task 5: Show Proposal Fields On The Import Review Page

**Files:**
- Modify: `frontend/src/types/import.ts`
- Modify: `frontend/src/components/imports/ImportReviewPage.tsx`
- Modify: `frontend/src/components/imports/ImportReviewPage.test.tsx`

- [ ] **Step 1: Write the failing frontend test for proposal display**

```tsx
// frontend/src/components/imports/ImportReviewPage.test.tsx
test('renders proposal type and category for Nexo draft rows', async () => {
  mockedImportService.getReview.mockResolvedValueOnce({
    ...firstPayload,
    session: {
      ...firstPayload.session,
      file_name: 'nexo.csv',
      mime_type: 'text/csv',
      strategy_key: 'nexo_csv',
      provider_hint: 'nexo',
      extractor_id: 'nexo_csv_v1',
    },
    statement: {
      ...firstPayload.statement,
      card_number_hint: null,
      account_number_hint: 'NEXO',
      currency: null,
    },
    transactions: [
      {
        id: 101,
        transaction_date: '2026-03-26',
        source_description: 'Bank transfer to BE55000000000001',
        canonical_description_en: null,
        signed_amount: -120,
        currency: 'USDC',
        display_amount: -120,
        display_currency: 'USD',
        display_is_available: true,
        display_unavailable_reason: null,
        debit_credit: 'debit',
        source_locator: 'csv:r4:NXT_CASHOUT_1',
        proposed_transaction_type: 'Transfer',
        proposed_expense_category: null,
        proposed_income_category: null,
        proposed_transfer_category: 'Internal Transfer',
        proposal_source: 'deterministic_extracted',
        confidence: 1,
        field_confidence: {},
        raw_fields: { source_locator: 'csv:r4:NXT_CASHOUT_1' },
        edit_source: 'deterministic_extracted',
      },
      {
        id: 102,
        transaction_date: '2026-03-25',
        source_description: 'Albert Heijn 3143 | Gent | BEL',
        canonical_description_en: null,
        signed_amount: -6.24,
        currency: 'xUSD',
        display_amount: -6.24,
        display_currency: 'USD',
        display_is_available: true,
        display_unavailable_reason: null,
        debit_credit: 'debit',
        source_locator: 'csv:r2:NXT_PURCHASE_1',
        proposed_transaction_type: 'Expense',
        proposed_expense_category: null,
        proposed_income_category: null,
        proposed_transfer_category: null,
        proposal_source: 'deterministic_extracted',
        confidence: 1,
        field_confidence: {},
        raw_fields: { source_locator: 'csv:r2:NXT_PURCHASE_1' },
        edit_source: 'deterministic_extracted',
      },
    ],
    issues: [],
    evidence: null,
  } as never);

  renderImportReviewPage();

  expect(await screen.findByText('Transfer • Internal Transfer')).toBeInTheDocument();
  expect(screen.getByText('Expense')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend test and verify it fails**

Run:

```bash
cd frontend && CI=true npm test -- --watchAll=false --runInBand src/components/imports/ImportReviewPage.test.tsx
```

Expected:

- FAIL because `ImportTransactionDraft` does not define proposal fields yet
- FAIL because `ImportReviewPage` does not render the proposal contract

- [ ] **Step 3: Update the frontend import types and review table**

```ts
// frontend/src/types/import.ts
export interface ImportTransactionDraft extends DisplayMoneyFields {
  id: number;
  transaction_date: string | null;
  source_description: string;
  canonical_description_en: string | null;
  signed_amount: number;
  currency: string;
  debit_credit: string | null;
  source_locator: string;
  proposed_transaction_type: string | null;
  proposed_expense_category: string | null;
  proposed_income_category: string | null;
  proposed_transfer_category: string | null;
  proposal_source: string | null;
  confidence: number | null;
  field_confidence: Record<string, number> | null;
  raw_fields: Record<string, unknown> | null;
  edit_source: string;
}
```

```tsx
// frontend/src/components/imports/ImportReviewPage.tsx
const proposalLabel = (transaction: ImportReviewPayload['transactions'][number]) => {
  const proposalCategory =
    transaction.proposed_expense_category ??
    transaction.proposed_income_category ??
    transaction.proposed_transfer_category;

  if (!transaction.proposed_transaction_type) {
    return 'Needs classification';
  }

  return proposalCategory
    ? `${transaction.proposed_transaction_type} • ${proposalCategory}`
    : transaction.proposed_transaction_type;
};

// inside the table header
<th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
  Proposed
</th>

// inside the row
<td className="px-4 py-3 text-gray-900 dark:text-gray-200">
  <div>{proposalLabel(transaction)}</div>
  {transaction.proposal_source ? (
    <div className="text-xs text-gray-500 dark:text-gray-400">{transaction.proposal_source}</div>
  ) : null}
</td>
```

- [ ] **Step 4: Run the frontend test and verify it passes**

Run:

```bash
cd frontend && CI=true npm test -- --watchAll=false --runInBand src/components/imports/ImportReviewPage.test.tsx
```

Expected:

- PASS for Nexo proposal rendering
- PASS for the existing review-page assertions

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/import.ts frontend/src/components/imports/ImportReviewPage.tsx frontend/src/components/imports/ImportReviewPage.test.tsx
git commit -m "feat: show import proposal fields in review"
```

## Verification Commands

Run the focused backend regression suite:

```bash
cd backend && pytest tests/imports/test_contracts.py tests/imports/test_detection.py tests/imports/test_nexo_csv.py tests/imports/test_import_models.py tests/imports/test_import_workflow.py tests/imports/test_import_review_api.py tests/imports/test_import_batch_api.py -v
```

Expected:

- PASS for proposal-field serialization
- PASS for Nexo detection and extraction
- PASS for upload, review, approval, and batch routing behavior

Run the focused frontend regression suite:

```bash
cd frontend && CI=true npm test -- --watchAll=false --runInBand src/components/imports/ImportReviewPage.test.tsx
```

Expected:

- PASS for proposal display and existing import-review behavior

## Manual Smoke Check

1. Start the backend and frontend normally.
2. Upload a Nexo CSV through the app.
3. Confirm the review page shows only:
   - purchases
   - fees
   - bank cash-outs
4. Confirm cashback and internal wallet-plumbing rows are absent.
5. Approve the import.
6. Verify the committed rows in Transactions show:
   - purchase rows as `Expense`
   - fee rows as `Expense / Financial Fees`
   - bank cash-outs as `Transfer / Internal Transfer`
7. Verify the imported rows appear in analytics without using the legacy CSV path.
