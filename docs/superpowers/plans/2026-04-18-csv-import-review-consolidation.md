# CSV Import Review Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all supported CSV imports onto the import-review pipeline, preserve deterministic provider semantics plus existing enrichment/post-commit behavior, and delete the legacy direct-commit CSV stack (`CSVParser`, `CsvImportService`, `/transactions/upload/`, and provider code for unsupported banks).
**Architecture:** Extend the import-review domain model to store extractor proposals on `ImportTransactionDraft`, add CSV detection plus dedicated provider extractors for Belfius, Beobank, and Nexo, route upload and batch ingestion through `ImportPipelineService` and `ImportWorkflowService`, run recurrence/category enrichment before review as gap-filling only, commit approved rows using persisted proposals, then remove the legacy CSV importer and its frontend/backend entry points.
**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, React, TypeScript, stdlib `csv`/`io`, existing import workflow services.

---

## Task 1: Expand import draft contracts and persistence for review-time proposals

### Files
- [ ] Modify `/Users/aaat/myfinance/backend/app/imports/contracts.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/models/imports.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/schemas/imports.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/database_manager.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/imports/test_import_models.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`

### Steps
- [ ] Add CSV strategy support to the contracts layer. Update `ImportStrategyKey` to include `NEXO_CSV`, and extend `ExtractedTransaction` so extractors can persist deterministic proposals instead of flattening them away during approval.

```python
class ImportStrategyKey(str, Enum):
    BELFIUS_CSV = "belfius_csv"
    BEOBANK_CSV = "beobank_csv"
    NEXO_CSV = "nexo_csv"
    PDF_STATEMENT = "pdf_statement"
    UNKNOWN = "unknown"


class ExtractedTransaction(BaseModel):
    posted_at: datetime
    settled_at: Optional[datetime] = None
    amount: Decimal
    currency: str
    description: str
    account_number_hint: Optional[str] = None
    counterparty_hint: Optional[str] = None
    external_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_evidence: Dict[str, Any] = Field(default_factory=dict)
    proposed_transaction_type: Optional[str] = None
    proposed_expense_category: Optional[str] = None
    proposed_income_category: Optional[str] = None
    proposed_transfer_category: Optional[str] = None
    classification_source: Optional[str] = None
    recurrence_pattern_id: Optional[int] = None
```

- [ ] Add matching persistence columns on `ImportTransactionDraft`. Keep them nullable so PDF imports and unknown strategies still work.

```python
proposed_transaction_type = Column(String, nullable=True)
proposed_expense_category = Column(String, nullable=True)
proposed_income_category = Column(String, nullable=True)
proposed_transfer_category = Column(String, nullable=True)
classification_source = Column(String, nullable=True)
recurrence_pattern_id = Column(Integer, nullable=True)
```

- [ ] Update import API schemas so review responses expose the new draft fields. Extend both the `ImportTransactionDraftResponse` model and `build_import_transaction_draft_response_payload`.

```python
proposed_transaction_type=draft.proposed_transaction_type,
proposed_expense_category=draft.proposed_expense_category,
proposed_income_category=draft.proposed_income_category,
proposed_transfer_category=draft.proposed_transfer_category,
classification_source=draft.classification_source,
recurrence_pattern_id=draft.recurrence_pattern_id,
```

- [ ] Extend runtime schema compatibility in `database_manager.py` so existing local databases gain these draft columns automatically when the app boots. Reuse the existing pattern that inspects columns and issues `ALTER TABLE` only when missing.

```python
_ensure_columns(
    conn,
    "import_transaction_drafts",
    {
        "proposed_transaction_type": "TEXT",
        "proposed_expense_category": "TEXT",
        "proposed_income_category": "TEXT",
        "proposed_transfer_category": "TEXT",
        "classification_source": "TEXT",
        "recurrence_pattern_id": "INTEGER",
    },
)
```

- [ ] Add model/schema tests that prove the new columns are present and returned by the review API. Use the existing import-review API fixture style; do not add a new test harness.

### Commands
- [ ] Run targeted backend tests after the contract/schema changes.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_import_models.py backend/tests/imports/test_import_review_api.py -q
```

### Expected result
- `ImportTransactionDraft` stores proposal metadata.
- Review API payloads expose proposal fields without breaking existing PDF sessions.
- Boot-time schema compatibility adds the new columns on old databases.

---

## Task 2: Add CSV detection utilities with bounded Belfius header scanning

### Files
- [ ] Create `/Users/aaat/myfinance/backend/app/imports/csv_support.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/imports/detection.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/imports/test_detection.py`

### Steps
- [ ] Create a small stdlib-only CSV support module. This replaces the old `pandas`-driven detection path and keeps decoding logic in one place.

```python
CSV_CHARSETS = ("utf-8-sig", "utf-8", "latin-1")
HEADER_SCAN_LIMIT = 20


def decode_csv_bytes(payload: bytes) -> tuple[str, str]:
    for encoding in CSV_CHARSETS:
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="replace"), "latin-1"
```

- [ ] Add helpers to normalize header cells and to search the first 20 physical lines for known header signatures. Keep the scan limit in the helper so Belfius behavior cannot drift in later call sites.

```python
def normalize_header_cells(cells: Sequence[str]) -> list[str]:
    return [cell.strip().strip('"') for cell in cells]


def find_header_row(
    lines: Sequence[str],
    *,
    delimiter: str,
    expected_header: Sequence[str],
    max_lines: int = HEADER_SCAN_LIMIT,
) -> Optional[tuple[int, list[str]]]:
    for idx, line in enumerate(lines[:max_lines]):
        cells = normalize_header_cells(next(csv.reader([line], delimiter=delimiter)))
        if cells == list(expected_header):
            return idx, cells
    return None
```

- [ ] Update `ImportDetector.detect` so it still prioritizes PDFs, then checks the decoded text against the supported CSV providers:
  - Belfius: semicolon-delimited header found within first 20 lines.
  - Beobank compact: comma-delimited exact header.
  - Beobank debit/credit: comma-delimited exact header.
  - Nexo: comma-delimited exact header.
  - Anything else: `UNKNOWN`.

```python
if _is_pdf(sample):
    ...

decoded, encoding = decode_csv_bytes(sample)
lines = decoded.splitlines()

if find_header_row(lines, delimiter=";", expected_header=BELFIUS_HEADER):
    return ImportDetectionResult(
        strategy_key=ImportStrategyKey.BELFIUS_CSV,
        confidence=0.95,
        metadata={"encoding": encoding},
    )
```

- [ ] Add detection tests for all supported CSV signatures plus two negative cases:
  - Belfius metadata rows before the header still detect correctly.
  - A Belfius header after line 20 does not match.

### Commands
- [ ] Run the detection test file after implementing the helper and detector updates.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_detection.py -q
```

### Expected result
- CSV strategy detection is deterministic and bounded.
- No provider detection depends on `pandas`.

---

## Task 3: Implement dedicated CSV extractors for Belfius, Beobank, and Nexo

### Files
- [ ] Create `/Users/aaat/myfinance/backend/app/imports/extractors/belfius_csv.py`
- [ ] Create `/Users/aaat/myfinance/backend/app/imports/extractors/beobank_csv.py`
- [ ] Create `/Users/aaat/myfinance/backend/app/imports/extractors/nexo_csv.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/imports/__init__.py`
- [ ] Create `/Users/aaat/myfinance/backend/tests/imports/test_csv_extractors.py`

### Steps
- [ ] Implement a Belfius extractor that:
  - skips metadata rows until the bounded header match,
  - parses semicolon-delimited data,
  - converts `DD/MM/YYYY` to timezone-naive midnight datetimes,
  - parses decimal amounts that use commas,
  - uses the row account field as `account_number_hint`,
  - preserves raw source values in `raw_evidence`.

```python
def _parse_belfius_amount(raw_value: str) -> Decimal:
    return Decimal(raw_value.replace(".", "").replace(",", ".").strip())


def _build_belfius_transaction(row: dict[str, str]) -> ExtractedTransaction:
    return ExtractedTransaction(
        posted_at=parse_dayfirst_date(row["Date comptable"]),
        settled_at=parse_dayfirst_date(row["Date de valeur"]),
        amount=_parse_belfius_amount(row["Montant"]),
        currency=(row.get("Devise") or "EUR").strip(),
        description=(row.get("Communication") or row.get("Libellés") or "").strip(),
        account_number_hint=(row.get("Compte") or "").strip() or None,
        raw_evidence={"row": row},
        metadata={"provider": "belfius_csv"},
    )
```

- [ ] Implement Beobank extraction for both supported legacy formats in one module:
  - compact format: infer `account_number_hint` from an all-digit filename stem;
  - debit/credit format: persist an empty account hint;
  - description field comes from the format-specific column names;
  - amounts become negative for debits and positive for credits.

```python
def infer_numeric_filename_stem(filename: str) -> Optional[str]:
    stem = Path(filename).stem
    return stem if stem.isdigit() else None
```

- [ ] Implement Nexo extraction according to the approved spec:
  - preserve the raw input currency exactly as exported,
  - normalize rejected status prefixes before the skip guard so `Rejected/...` and `rejected /...` are both dropped,
  - use the Nexo transaction ID only as `external_id`, never as the account number,
  - emit deterministic proposals for transfers, fees, and known purchase/repayment shapes,
  - keep proposal precedence strong by writing proposal fields, not finalized categories.

```python
def _normalized_status_prefix(description: str) -> str:
    cleaned = description.strip()
    return cleaned.split("/", 1)[0].strip().lower()


if _normalized_status_prefix(description) == "rejected":
    return None

return ExtractedTransaction(
    posted_at=posted_at,
    amount=amount,
    currency=asset.strip(),
    description=clean_description,
    external_id=transaction_id,
    proposed_transaction_type="transfer",
    proposed_transfer_category="internal",
    classification_source="deterministic_nexo_csv",
    raw_evidence={"row": row},
    metadata={"provider": "nexo_csv"},
)
```

- [ ] Export the new extractor classes/functions from `backend/app/imports/__init__.py` so the workflow layer can import them without touching legacy modules.

- [ ] Add extractor tests that cover:
  - Belfius metadata prefix rows.
  - Beobank compact numeric filename inference.
  - Beobank debit/credit account hint stays empty.
  - Nexo rejected rows are skipped after prefix normalization.
  - Nexo preserves `xUSD` and `USDC` as raw currencies.
  - Nexo transfer and fee proposals are set deterministically.

### Commands
- [ ] Run the extractor tests after implementing the new modules.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_csv_extractors.py -q
```

### Expected result
- Provider-specific CSV parsing exists entirely inside the review pipeline.
- Nexo semantics survive extraction without the legacy parser’s data loss.

---

## Task 4: Teach the workflow to persist extractor proposals, run enrichment before review, and commit approved drafts correctly

### Files
- [ ] Modify `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- [ ] Create `/Users/aaat/myfinance/backend/app/imports/enrichment.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/test_transfer_analytics.py`

### Steps
- [ ] Add CSV extractor dependencies to `ImportWorkflowService` and dispatch them from `extract_detected_session`.

```python
extractors = {
    ImportStrategyKey.PDF_STATEMENT: self._pdf_statement_extractor,
    ImportStrategyKey.BELFIUS_CSV: self._belfius_csv_extractor,
    ImportStrategyKey.BEOBANK_CSV: self._beobank_csv_extractor,
    ImportStrategyKey.NEXO_CSV: self._nexo_csv_extractor,
}
```

- [ ] Persist all extractor proposal fields when writing `ImportTransactionDraft` rows.

```python
draft = ImportTransactionDraft(
    import_session_id=session.id,
    posted_at=tx.posted_at,
    settled_at=tx.settled_at,
    amount=tx.amount,
    currency=tx.currency,
    description=tx.description,
    account_number_hint=tx.account_number_hint,
    counterparty_hint=tx.counterparty_hint,
    external_id=tx.external_id,
    raw_evidence=tx.raw_evidence,
    metadata=tx.metadata,
    proposed_transaction_type=tx.proposed_transaction_type,
    proposed_expense_category=tx.proposed_expense_category,
    proposed_income_category=tx.proposed_income_category,
    proposed_transfer_category=tx.proposed_transfer_category,
    classification_source=tx.classification_source,
    recurrence_pattern_id=tx.recurrence_pattern_id,
)
```

- [ ] Create `imports/enrichment.py` and move the legacy enrichment behavior into explicit pre-review functions:
  - recurrence matching runs before review,
  - upload suggester runs after recurrence matching,
  - both are gap-filling only,
  - upload suggester must skip drafts whose effective transaction type is already `transfer`.

```python
def effective_transaction_type(draft: ImportTransactionDraft) -> Optional[str]:
    return draft.proposed_transaction_type


def apply_upload_suggestions(
    draft: ImportTransactionDraft,
    *,
    suggester: UploadSuggestionService,
) -> None:
    if effective_transaction_type(draft) == TransactionType.TRANSFER.value:
        return
    if draft.proposed_expense_category or draft.proposed_income_category or draft.proposed_transfer_category:
        return
    ...
```

- [ ] Call the enrichment step after draft persistence and before the session moves to `awaiting_review`. Keep extractor proposals authoritative by only filling `None` fields.

```python
self._persist_statement_drafts(...)
self._enrich_drafts_before_review(import_session)
self._advance_to_awaiting_review(import_session)
```

- [ ] Update approval so committed transactions read back the persisted proposal fields instead of discarding them:
  - `transaction_type` comes from `draft.proposed_transaction_type`,
  - the category field matches the chosen type,
  - `classification_source` and `recurrence_pattern_id` are copied to `TransactionCreate`.

```python
return TransactionCreate(
    amount=Decimal(draft.amount),
    currency=draft.currency,
    description=draft.description,
    transaction_type=draft.proposed_transaction_type,
    expense_category=draft.proposed_expense_category,
    income_category=draft.proposed_income_category,
    transfer_category=draft.proposed_transfer_category,
    classification_source=draft.classification_source,
    recurrence_pattern_id=draft.recurrence_pattern_id,
    ...
)
```

- [ ] Preserve and relocate the post-commit hooks that used to live in `CsvImportService`:
  - statistics refresh,
  - category suggestion index update,
  - anomaly detection.
  Keep them in the approval path after all selected drafts are committed successfully.

- [ ] Add workflow tests for:
  - CSV strategy dispatch,
  - extractor proposal persistence,
  - recurrence matching before review,
  - upload suggester not overwriting deterministic extractor proposals,
  - upload suggester skipping transfer drafts,
  - approval copying proposal fields into committed transactions,
  - approval invoking statistics refresh, suggestion index update, and anomaly detection.

### Commands
- [ ] Run the workflow-focused backend tests after the enrichment and approval changes.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_import_workflow.py backend/tests/test_transfer_analytics.py -q
```

### Expected result
- Review sessions carry provider proposals all the way to approval.
- Recurrence and suggester logic move from direct-import time to pre-review enrichment without losing the transfer guard.

---

## Task 5: Route upload and batch ingestion through the review pipeline and fail unsupported CSVs cleanly

### Files
- [ ] Modify `/Users/aaat/myfinance/backend/app/routers/imports.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/imports/pipeline.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/imports/batch_folder.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/imports/test_import_batch_api.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/test_upload_guardrails.py`

### Steps
- [ ] Move the CSV upload guardrails from `/transactions/upload/` onto `/imports/upload` so PDFs and CSVs share one entry point. Keep the same file-size ceiling and content-type checks, but treat supported CSV MIME types as import-review uploads.

```python
ALLOWED_IMPORT_CONTENT_TYPES = {
    "application/pdf",
    "text/csv",
    "application/vnd.ms-excel",
}
```

- [ ] Update the import upload route so supported CSV sessions auto-extract exactly like PDFs. Unsupported CSV signatures must create the session record and then fail it with a clear detection-stage error instead of silently succeeding.

```python
snapshot = pipeline.start_upload(...)
if snapshot.strategy_key in {
    ImportStrategyKey.PDF_STATEMENT.value,
    ImportStrategyKey.BELFIUS_CSV.value,
    ImportStrategyKey.BEOBANK_CSV.value,
    ImportStrategyKey.NEXO_CSV.value,
}:
    snapshot = workflow.extract_detected_session(snapshot.id)
else:
    snapshot = workflow.fail_session(
        snapshot.id,
        stage="detection",
        message=f"Unsupported import strategy: {snapshot.strategy_key}",
    )
```

- [ ] Add a public workflow failure helper if one does not already exist. Do not reach into private batch-only methods from the API router.

- [ ] Rewrite `ImportBatchFolderService` so every supported PDF or CSV file uses the same upload-plus-extract flow. Remove the `_process_csv_file` direct-commit path entirely.

```python
snapshot = self._pipeline.start_upload(...)
if snapshot.strategy_key in SUPPORTED_REVIEW_STRATEGIES:
    self._workflow.extract_detected_session(snapshot.id)
else:
    self._workflow.fail_session(snapshot.id, stage="detection", message=...)
```

- [ ] Update the API and batch tests so CSV imports now produce `awaiting_review` sessions rather than immediately committed transactions. Cover Belfius, Beobank, Nexo, and one unsupported CSV fixture.

- [ ] Rewrite the old upload guardrail tests against `/imports/upload` and remove any expectation that CSV upload responses contain an `imported_count`.

### Commands
- [ ] Run the API and batch tests after routing changes.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_import_review_api.py backend/tests/imports/test_import_batch_api.py backend/tests/test_upload_guardrails.py -q
```

### Expected result
- There is one backend ingestion path for PDFs and CSVs.
- Unsupported CSVs fail visibly inside import-review state instead of bypassing the workflow.

---

## Task 6: Remove the direct transaction CSV upload endpoint and migrate old behavior tests to the review flow

### Files
- [ ] Modify `/Users/aaat/myfinance/backend/app/routers/transactions.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/test_upload_trust_order.py`
- [ ] Modify `/Users/aaat/myfinance/backend/tests/test_manual_edit_updates_index.py`

### Steps
- [ ] Delete the `/transactions/upload/` route and all imports/constants that only existed for direct CSV import.

```python
# remove:
@router.post("/upload/")
async def upload_csv(...):
    ...
```

- [ ] Rewrite the old trust-order tests so they assert the same business guarantees through import review:
  - deterministic extractor proposals survive enrichment,
  - recurrence matching fills gaps before review,
  - approval remains atomic when downstream hooks fail.

- [ ] Update the category-index test that previously depended on `/transactions/upload/` so it now creates an import session, approves the draft(s), and then asserts index updates against the committed transactions.

### Commands
- [ ] Run the migrated legacy-behavior tests.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/test_upload_trust_order.py backend/tests/test_manual_edit_updates_index.py -q
```

### Expected result
- No production path depends on the removed direct transaction upload endpoint.
- Existing behavior guarantees are still covered, now at the review-pipeline boundary.

---

## Task 7: Update frontend upload flow so CSV files open import review instead of importing immediately

### Files
- [ ] Modify `/Users/aaat/myfinance/frontend/src/services/importService.ts`
- [ ] Modify `/Users/aaat/myfinance/frontend/src/services/transactionService.ts`
- [ ] Modify `/Users/aaat/myfinance/frontend/src/components/FileUpload.tsx`
- [ ] Modify `/Users/aaat/myfinance/frontend/src/components/FileUpload.test.tsx`
- [ ] Modify `/Users/aaat/myfinance/frontend/src/types/import.ts`
- [ ] Modify `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.tsx`
- [ ] Modify `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.test.tsx`

### Steps
- [ ] Remove the legacy `uploadCSV` API client from `transactionService.ts`. Add or rename a single import upload function in `importService.ts` that handles both PDFs and CSVs.

```ts
export const uploadImportFile = async (file: File): Promise<ImportSession> => {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post("/imports/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
};
```

- [ ] Update `FileUpload.tsx` so CSV and PDF files follow the same path:
  - call the import upload service,
  - navigate to `/imports/{session.id}/review`,
  - stop showing the old “imported count” success flow for CSVs.

```tsx
const session = await importService.uploadImportFile(file);
navigate(`/imports/${session.id}/review`);
```

- [ ] Keep the existing client-side size/type checks, but align the accepted file list with the backend import endpoint.

- [ ] Extend the frontend import types with the new proposal fields so the review page can render them.

```ts
export interface ImportTransactionDraft {
  ...
  proposed_transaction_type?: string | null;
  proposed_expense_category?: string | null;
  proposed_income_category?: string | null;
  proposed_transfer_category?: string | null;
  classification_source?: string | null;
  recurrence_pattern_id?: number | null;
}
```

- [ ] Add a compact proposal section to the review page so users can see what the extractor/enrichment proposed before approval. Show only populated fields and keep the UI text product-facing.

```tsx
{draft.proposed_transaction_type && (
  <div>
    <span>Type</span>
    <span>{draft.proposed_transaction_type}</span>
  </div>
)}
```

- [ ] Update the component tests so:
  - CSV upload uses the import service and navigates to review,
  - the old transaction upload service is no longer mocked,
  - proposal fields render on the review page when present.

### Commands
- [ ] Run the focused frontend test set after the upload-flow update.

```bash
cd /Users/aaat/myfinance/frontend && npm test -- --runInBand src/components/FileUpload.test.tsx src/components/imports/ImportReviewPage.test.tsx
```

### Expected result
- The UI has one upload experience for PDFs and CSVs.
- CSV users land in review instead of committing rows immediately.

---

## Task 8: Delete the legacy CSV stack and drop `pandas` if nothing else imports it

### Files
- [ ] Delete `/Users/aaat/myfinance/backend/app/services/csv_parser.py`
- [ ] Delete `/Users/aaat/myfinance/backend/app/services/csv_import_service.py`
- [ ] Modify `/Users/aaat/myfinance/backend/app/services/__init__.py` if it exports deleted symbols
- [ ] Modify `/Users/aaat/myfinance/backend/requirements.txt`
- [ ] Modify or delete any tests that only covered deleted unsupported providers

### Steps
- [ ] Remove all remaining imports and references to `CSVParser`, `CsvImportService`, and the deleted endpoint.

```bash
cd /Users/aaat/myfinance && rg "CSVParser|CsvImportService|/transactions/upload|uploadCSV\(" backend frontend
```

- [ ] Delete the two legacy backend service modules with `apply_patch`, then clean any import/export stubs that still mention them.

- [ ] Check whether anything outside the deleted importer still uses `pandas`. Remove `pandas==...` from `backend/requirements.txt` only if the repository-wide search is empty after the deletions.

```bash
cd /Users/aaat/myfinance && rg "import pandas|from pandas" backend
```

- [ ] Remove or replace tests for unsupported providers that are explicitly out of scope now (ING and KBC). Keep coverage only for the supported review-pipeline providers.

### Commands
- [ ] Run the repository-wide search checks before the final test pass.

```bash
cd /Users/aaat/myfinance && rg "CSVParser|CsvImportService|/transactions/upload|uploadCSV\(" backend frontend
cd /Users/aaat/myfinance && rg "import pandas|from pandas" backend
```

### Expected result
- No legacy direct CSV import code remains in the repository.
- `pandas` is removed from backend dependencies if and only if it is now unused.

---

## Task 9: Run the final verification sweep and commit in small, reviewable slices

### Files
- [ ] No new files; verify the full changed set from Tasks 1-8

### Steps
- [ ] Run the backend import-review suite first, then the full backend test suite if the targeted tests pass cleanly.

```bash
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_detection.py backend/tests/imports/test_csv_extractors.py backend/tests/imports/test_import_models.py backend/tests/imports/test_import_review_api.py backend/tests/imports/test_import_workflow.py backend/tests/imports/test_import_batch_api.py backend/tests/test_upload_guardrails.py backend/tests/test_upload_trust_order.py backend/tests/test_transfer_analytics.py backend/tests/test_manual_edit_updates_index.py -q
cd /Users/aaat/myfinance/backend && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest -q
```

- [ ] Run the frontend tests touched by the upload/review changes, then the standard frontend test command used in the repo if it exists.

```bash
cd /Users/aaat/myfinance/frontend && npm test -- --runInBand src/components/FileUpload.test.tsx src/components/imports/ImportReviewPage.test.tsx
```

- [ ] Inspect the final diff for deletion scope, proposal persistence, and endpoint removal.

```bash
cd /Users/aaat/myfinance && git diff -- backend/app/imports backend/app/routers backend/app/services backend/requirements.txt frontend/src/services frontend/src/components
```

- [ ] Commit in slices that map to the architecture:
  1. import draft schema/contracts,
  2. CSV detection/extractors/workflow,
  3. routing/frontend migration and legacy deletion.

### Expected result
- The branch is verifiably free of direct CSV-import paths.
- CSV uploads, batch ingestion, and review approval all use the same pipeline and preserve provider semantics.

---

## Notes For The Implementer

- [ ] Do not touch the dirty unrelated user edits in `/Users/aaat/myfinance/backend/app/services/csv_parser.py` and `/Users/aaat/myfinance/backend/tests/imports/test_import_batch_api.py` until you are actively replacing them with the planned migration. Read them carefully first and work with the current branch state instead of reverting anything.
- [ ] Keep extractor proposals authoritative. Enrichment fills missing fields only.
- [ ] Preserve the transfer guard from legacy upload suggestions. A draft whose effective type is `transfer` must not receive a category suggestion.
- [ ] Preserve raw exported currencies for Nexo. Alias handling belongs in reporting, not extraction.
- [ ] Keep Belfius header scanning bounded to 20 physical lines in both detection and extraction entry points.

