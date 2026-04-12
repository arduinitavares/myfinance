# Beobank Mastercard PDF Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one end-to-end Beobank Mastercard PDF import path: upload PDF, extract deterministic draft rows from pages 2..N, review them with issues/evidence, and commit approved rows into `transactions`.

**Architecture:** Keep `strategy_key = pdf_statement` at the pipeline level, but introduce a `PdfStatementExtractor` chain that first tries a deterministic `BeobankMastercardPdfExtractor`. Add the missing post-detection orchestration, review APIs, and commit path needed to make imports shippable. Frontend keeps a single upload entry point and routes PDF uploads into a review screen instead of the CSV success toast path.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, `pypdf`, React, React Router, Axios, Testing Library, pytest.

---

## File Structure

### Backend

- Modify: `/Users/aaat/myfinance/backend/requirements.txt`
  - Add `pypdf`.
- Modify: `/Users/aaat/myfinance/backend/app/imports/contracts.py`
  - Allow deterministic provenance and richer raw PDF evidence.
- Modify: `/Users/aaat/myfinance/backend/app/models/imports.py`
  - Keep draft schema aligned with deterministic extraction.
- Modify: `/Users/aaat/myfinance/backend/app/models/transaction.py`
  - Persist import traceability on committed transactions.
- Modify: `/Users/aaat/myfinance/backend/app/schemas/transaction.py`
  - Expose new traceability fields on committed transactions.
- Modify: `/Users/aaat/myfinance/backend/app/database_manager.py`
  - Backfill new transaction columns for existing local DBs.
- Create: `/Users/aaat/myfinance/backend/app/imports/pdf_text.py`
  - `pypdf` wrapper and canonical page lineization.
- Create: `/Users/aaat/myfinance/backend/app/imports/beobank_mastercard_pdf.py`
  - Layout validator + deterministic parser.
- Create: `/Users/aaat/myfinance/backend/app/imports/pdf_statement.py`
  - Ordered PDF extractor chain and “not my format” dispatch.
- Create: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
  - Post-detection orchestration: extract, normalize, validate, persist drafts/issues, approve/reject/retry, commit.
- Modify: `/Users/aaat/myfinance/backend/app/imports/artifacts.py`
  - Write normalized extraction artifacts and optional AI files only when used.
- Modify: `/Users/aaat/myfinance/backend/app/imports/pipeline.py`
  - Keep upload/detect, but expose session IDs cleanly for workflow handoff.
- Create: `/Users/aaat/myfinance/backend/app/schemas/imports.py`
  - Upload/review/approve API payloads.
- Create: `/Users/aaat/myfinance/backend/app/routers/imports.py`
  - Upload PDF, fetch review payload, approve, reject, retry.
- Modify: `/Users/aaat/myfinance/backend/app/main.py`
  - Register import router.

### Backend tests

- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_contracts.py`
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_models.py`
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_pipeline.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/fixtures/beobank_mastercard_pages.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_pdf_text.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_beobank_mastercard_pdf.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`

### Frontend

- Create: `/Users/aaat/myfinance/frontend/src/types/import.ts`
  - Import session/review payload types.
- Create: `/Users/aaat/myfinance/frontend/src/services/importService.ts`
  - PDF upload + review/approve/reject/retry calls.
- Modify: `/Users/aaat/myfinance/frontend/src/components/FileUpload.tsx`
  - Accept PDF, branch upload behavior, navigate into review screen.
- Create: `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.tsx`
  - Draft rows + issues + evidence + actions.
- Create: `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.test.tsx`
- Create: `/Users/aaat/myfinance/frontend/src/components/FileUpload.test.tsx`
- Modify: `/Users/aaat/myfinance/frontend/src/App.tsx`
  - Add `/imports/:sessionId/review` route.

---

### Task 1: Align Contracts and Schema for Deterministic PDF Imports

**Files:**
- Modify: `/Users/aaat/myfinance/backend/requirements.txt`
- Modify: `/Users/aaat/myfinance/backend/app/imports/contracts.py`
- Modify: `/Users/aaat/myfinance/backend/app/models/imports.py`
- Modify: `/Users/aaat/myfinance/backend/app/models/transaction.py`
- Modify: `/Users/aaat/myfinance/backend/app/schemas/transaction.py`
- Modify: `/Users/aaat/myfinance/backend/app/database_manager.py`
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_contracts.py`
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_models.py`

- [ ] **Step 1: Write failing backend contract tests**

```python
def test_extracted_transaction_accepts_deterministic_edit_source():
    tx = ExtractedTransaction(
        transaction_date="2026-04-11",
        source_description="WISSELKOSTEN",
        signed_amount=-0.38,
        currency="EUR",
        debit_credit="debit",
        source_locator="pdf:p2:l21",
        edit_source="deterministic_extracted",
    )
    assert tx.edit_source == "deterministic_extracted"


def test_raw_evidence_accepts_page_line_payloads():
    evidence = RawEvidence(
        text_blocks=[
            {
                "page_number": 2,
                "raw_text": "Uw transacties\\n15/12/2025 Merchant 14,20",
                "lines": ["Uw transacties", "15/12/2025 Merchant 14,20"],
            }
        ]
    )
    assert evidence.model_dump()["text_blocks"][0]["page_number"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_contracts.py tests/imports/test_import_models.py -q'
```

Expected: FAIL because `deterministic_extracted` is rejected and transaction traceability columns do not exist yet.

- [ ] **Step 3: Add minimal contract and schema support**

```python
# backend/app/imports/contracts.py
class ExtractedTransaction(BaseModel):
    ...
    edit_source: Literal["deterministic_extracted", "ai_extracted", "user_edited"] = "ai_extracted"


# backend/app/models/transaction.py
class Transaction(Base):
    ...
    import_session_id = Column(Integer, nullable=True, index=True)
    import_source_locator = Column(String(255), nullable=True)
    import_source_description = Column(String(500), nullable=True)
    canonical_description_en = Column(String(500), nullable=True)
```

```python
# backend/app/database_manager.py
def _ensure_import_transaction_columns() -> None:
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return
    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    with engine.begin() as conn:
        if "import_session_id" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN import_session_id INTEGER"))
        if "import_source_locator" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN import_source_locator VARCHAR(255)"))
        if "import_source_description" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN import_source_description VARCHAR(500)"))
        if "canonical_description_en" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN canonical_description_en VARCHAR(500)"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_contracts.py tests/imports/test_import_models.py -q'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/imports/contracts.py backend/app/models/imports.py backend/app/models/transaction.py backend/app/schemas/transaction.py backend/app/database_manager.py backend/tests/imports/test_contracts.py backend/tests/imports/test_import_models.py
git commit -m "feat: align import contracts for deterministic pdf extraction"
```

### Task 2: Add Canonical PDF Text Extraction and Deterministic Beobank Parser

**Files:**
- Create: `/Users/aaat/myfinance/backend/app/imports/pdf_text.py`
- Create: `/Users/aaat/myfinance/backend/app/imports/beobank_mastercard_pdf.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/fixtures/beobank_mastercard_pages.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_pdf_text.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_beobank_mastercard_pdf.py`

- [ ] **Step 1: Write failing parser tests from sanitized page fixtures**

```python
def test_lineize_pdf_pages_drops_empty_lines_and_numbers_from_one():
    pages = lineize_pdf_pages(
        [
            "Uittreksel van uw kredietkaart\\n\\nPeriode\\n",
            "Uw transacties\\nDatum Beschrijving Bedrag\\n15/12/2025 DE TRAITEUR BV GENT BE 14,20\\n",
        ]
    )
    assert pages[1]["lines"][0] == "Uw transacties"
    assert pages[1]["lines"][2] == "15/12/2025 DE TRAITEUR BV GENT BE 14,20"


def test_parser_ignores_page_one_and_emits_fee_row():
    result = BeobankMastercardPdfExtractor().extract_from_pages(
        SANITIZED_BEOBANK_PAGES
    )
    descriptions = [tx.source_description for tx in result.transactions]
    assert "WISSELKOSTEN" in descriptions
    assert all("Vorig saldo" not in description for description in descriptions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_pdf_text.py tests/imports/test_beobank_mastercard_pdf.py -q'
```

Expected: FAIL because extractor and lineizer do not exist.

- [ ] **Step 3: Implement `pypdf` reader, canonical lineization, and parser**

```python
# backend/app/imports/pdf_text.py
from pypdf import PdfReader


def read_pdf_page_text(file_path: str) -> list[str]:
    reader = PdfReader(file_path)
    return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]


def lineize_pdf_pages(page_texts: list[str]) -> list[dict]:
    pages = []
    for index, text in enumerate(page_texts, start=1):
        normalized = text.replace("\u00A0", " ").replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in normalized.split("\n") if line.strip()]
        pages.append({"page_number": index, "raw_text": normalized, "lines": lines})
    return pages
```

```python
# backend/app/imports/beobank_mastercard_pdf.py
ROW_RE = re.compile(r"^(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<desc>.+?)\s+(?P<amount>-?\d{1,3}(?:\.\d{3})*,\d{2})$")

if amount_text.startswith("-"):
    signed_amount = parse_belgian_amount(amount_text) * -1
    debit_credit = "credit"
else:
    signed_amount = -parse_belgian_amount(amount_text)
    debit_credit = "debit"
```

- [ ] **Step 4: Run tests to verify parser behavior**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_pdf_text.py tests/imports/test_beobank_mastercard_pdf.py -q'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/pdf_text.py backend/app/imports/beobank_mastercard_pdf.py backend/tests/imports/fixtures/beobank_mastercard_pages.py backend/tests/imports/test_pdf_text.py backend/tests/imports/test_beobank_mastercard_pdf.py
git commit -m "feat: add deterministic beobank mastercard pdf parser"
```

### Task 3: Build `pdf_statement` Extraction Chain and Draft Persistence Workflow

**Files:**
- Create: `/Users/aaat/myfinance/backend/app/imports/pdf_statement.py`
- Create: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- Modify: `/Users/aaat/myfinance/backend/app/imports/artifacts.py`
- Modify: `/Users/aaat/myfinance/backend/app/imports/pipeline.py`
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_pipeline.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

```python
def test_pdf_workflow_persists_drafts_and_enters_awaiting_review(db_session, monkeypatch):
    service = ImportWorkflowService(db_session)
    session, detection = ImportPipelineService(db_session).start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\\nhello",
    )
    monkeypatch.setattr(
        "app.imports.workflow.read_pdf_page_text",
        lambda _: SANITIZED_BEOBANK_PAGE_TEXTS,
    )

    reviewed = service.extract_detected_session(session.id)

    assert reviewed.status == ImportSessionStatus.AWAITING_REVIEW.value
    assert db_session.query(ImportTransactionDraft).count() > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_pipeline.py tests/imports/test_import_workflow.py -q'
```

Expected: FAIL because no extraction workflow exists.

- [ ] **Step 3: Implement extractor chain and workflow persistence**

```python
# backend/app/imports/pdf_statement.py
class NotMyPdfFormat(Exception):
    pass


class PdfStatementExtractor:
    def __init__(self) -> None:
        self.extractors = [BeobankMastercardPdfExtractor()]

    def extract(self, *, file_path: str) -> tuple[RawEvidence, ExtractionResult]:
        page_texts = read_pdf_page_text(file_path)
        evidence = RawEvidence(text_blocks=lineize_pdf_pages(page_texts))
        for extractor in self.extractors:
            try:
                return evidence, extractor.extract(evidence)
            except NotMyPdfFormat:
                continue
        raise ValueError("unsupported pdf_statement format")
```

```python
# backend/app/imports/workflow.py
class ImportWorkflowService:
    def extract_detected_session(self, session_id: int) -> ImportSession:
        session = self._get_session(session_id, expected=ImportSessionStatus.DETECTED)
        evidence, result = PdfStatementExtractor().extract(file_path=str(original_file))
        self.artifacts.write_raw_evidence(str(session.id), 1, evidence)
        self.artifacts.write_normalized_result(str(session.id), 1, result)
        self._persist_drafts(session, result)
        session.status = ImportSessionStatus.AWAITING_REVIEW.value
        self.db.commit()
        return session
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_pipeline.py tests/imports/test_import_workflow.py -q'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/pdf_statement.py backend/app/imports/workflow.py backend/app/imports/artifacts.py backend/app/imports/pipeline.py backend/tests/imports/test_pipeline.py backend/tests/imports/test_import_workflow.py
git commit -m "feat: add pdf import extraction workflow"
```

### Task 4: Expose Review, Retry, Reject, and Approve APIs

**Files:**
- Create: `/Users/aaat/myfinance/backend/app/schemas/imports.py`
- Create: `/Users/aaat/myfinance/backend/app/routers/imports.py`
- Modify: `/Users/aaat/myfinance/backend/app/main.py`
- Modify: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- Create: `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_get_import_review_payload_returns_drafts_issues_and_evidence(client, seeded_pdf_import_session):
    response = client.get(f"/imports/{seeded_pdf_import_session.id}")
    assert response.status_code == 200
    payload = response.json()
    assert "statement" in payload
    assert "transactions" in payload
    assert "issues" in payload
    assert "evidence" in payload


def test_approve_import_commits_transactions(client, seeded_pdf_import_session, db_session):
    response = client.post(f"/imports/{seeded_pdf_import_session.id}/approve")
    assert response.status_code == 200
    assert db_session.query(Transaction).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_import_review_api.py -q'
```

Expected: FAIL because router and payload schemas do not exist.

- [ ] **Step 3: Implement import review router and commit path**

```python
# backend/app/routers/imports.py
router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/upload", response_model=ImportUploadResponse)
async def upload_import_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    session, _ = ImportPipelineService(db).start_upload(
        filename=file.filename,
        content_type=file.content_type or "",
        file_bytes=await file.read(),
    )
    session = ImportWorkflowService(db).extract_detected_session(session.id)
    return ImportUploadResponse(id=session.id, status=session.status, strategy_key=session.strategy_key)
```

```python
# backend/app/imports/workflow.py
def approve_session(self, session_id: int) -> list[Transaction]:
    session = self._get_session(session_id, expected=ImportSessionStatus.AWAITING_REVIEW)
    session.status = ImportSessionStatus.COMMITTING.value
    self.db.flush()
    created = []
    for draft in self._drafts_for_session(session_id):
        transaction = TransactionCreate(
            account_number=self._card_number_hint(session_id),
            transaction_date=draft.transaction_date,
            amount=draft.signed_amount,
            currency=draft.currency,
            description=draft.source_description,
            source_bank="Beobank",
        )
        created.append(self._commit_draft_transaction(session, draft, transaction))
    session.status = ImportSessionStatus.COMMITTED.value
    self.db.commit()
    return created
```

- [ ] **Step 4: Run backend API tests**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_import_review_api.py tests/imports/test_import_workflow.py -q'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/imports.py backend/app/routers/imports.py backend/app/imports/workflow.py backend/app/main.py backend/tests/imports/test_import_review_api.py
git commit -m "feat: add import review and approval api"
```

### Task 5: Add Frontend PDF Upload Branch and Review Screen

**Files:**
- Create: `/Users/aaat/myfinance/frontend/src/types/import.ts`
- Create: `/Users/aaat/myfinance/frontend/src/services/importService.ts`
- Modify: `/Users/aaat/myfinance/frontend/src/components/FileUpload.tsx`
- Create: `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.tsx`
- Create: `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.test.tsx`
- Create: `/Users/aaat/myfinance/frontend/src/components/FileUpload.test.tsx`
- Modify: `/Users/aaat/myfinance/frontend/src/App.tsx`

- [ ] **Step 1: Write failing frontend tests**

```tsx
test('uploads pdf statements through import service and navigates to review page', async () => {
  mockedImportService.uploadStatement.mockResolvedValue({ id: 12, status: 'awaiting_review' });
  render(<FileUpload onUploadSuccess={jest.fn()} />, { wrapper: MemoryRouter });
  const file = new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByLabelText(/upload transaction file/i), { target: { files: [file] } });
  await waitFor(() => expect(mockedImportService.uploadStatement).toHaveBeenCalled());
});

test('renders issues and evidence on import review page', async () => {
  mockedImportService.getReview.mockResolvedValue({
    statement: { id: 12, status: 'awaiting_review', currency: 'EUR' },
    transactions: [{ id: 1, source_description: 'DE TRAITEUR BV GENT BE', signed_amount: -14.2, source_locator: 'pdf:p2:l3' }],
    issues: [{ code: 'warning_only', message: 'Minor metadata gap', blocking: false }],
    evidence: { 2: { lines: ['Uw transacties', '15/12/2025 DE TRAITEUR BV GENT BE 14,20'] } },
  });
  render(<ImportReviewPage />);
  expect(await screen.findByText(/DE TRAITEUR BV GENT BE/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/aaat/myfinance/frontend
CI=true npm test -- --runInBand --watch=false src/components/FileUpload.test.tsx src/components/imports/ImportReviewPage.test.tsx
```

Expected: FAIL because import service and review page do not exist.

- [ ] **Step 3: Implement PDF upload branch and review route**

```tsx
// frontend/src/components/FileUpload.tsx
const isPdf = file.name.toLowerCase().endsWith('.pdf');
if (isPdf) {
  const session = await importService.uploadStatement(file);
  navigate(`/imports/${session.id}/review`);
  return;
}
const result = await transactionService.uploadCSV(file);
```

```tsx
// frontend/src/App.tsx
<Route
  path="/imports/:sessionId/review"
  element={
    <MainLayout onUploadSuccess={handleUploadSuccess}>
      <ImportReviewPage />
    </MainLayout>
  }
/>
```

- [ ] **Step 4: Run frontend tests and typecheck**

Run:

```bash
cd /Users/aaat/myfinance/frontend
CI=true npm test -- --runInBand --watch=false src/components/FileUpload.test.tsx src/components/imports/ImportReviewPage.test.tsx
npx tsc --noEmit --pretty false
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/import.ts frontend/src/services/importService.ts frontend/src/components/FileUpload.tsx frontend/src/components/FileUpload.test.tsx frontend/src/components/imports/ImportReviewPage.tsx frontend/src/components/imports/ImportReviewPage.test.tsx frontend/src/App.tsx
git commit -m "feat: add pdf import review ui"
```

### Task 6: Run End-to-End Verification and Tighten Edges

**Files:**
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`
- Modify: `/Users/aaat/myfinance/frontend/src/components/imports/ImportReviewPage.test.tsx`

- [ ] **Step 1: Add regression tests for duplicate rejection and blocking issue gating**

```python
def test_blocking_issue_prevents_approval(client, seeded_blocking_pdf_import_session):
    response = client.post(f"/imports/{seeded_blocking_pdf_import_session.id}/approve")
    assert response.status_code == 409
    assert "blocking" in response.text.lower()


def test_duplicate_fingerprint_is_rejected_on_approve(client, seeded_duplicate_pdf_import_session):
    response = client.post(f"/imports/{seeded_duplicate_pdf_import_session.id}/approve")
    assert response.status_code == 409
```

```tsx
test('disables approve button when blocking issue exists', async () => {
  mockedImportService.getReview.mockResolvedValue({
    statement: { id: 12, status: 'awaiting_review', currency: 'EUR' },
    transactions: [],
    issues: [{ code: 'malformed_row', message: 'Bad amount', blocking: true }],
    evidence: {},
  });
  render(<ImportReviewPage />);
  expect(await screen.findByRole('button', { name: /approve/i })).toBeDisabled();
});
```

- [ ] **Step 2: Run the focused regression suite**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports/test_import_review_api.py tests/imports/test_import_workflow.py -q'
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/imports/ImportReviewPage.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run whole targeted verification batch**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=/app pytest tests/imports -q'
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/FileUpload.test.tsx src/components/imports/ImportReviewPage.test.tsx
cd /Users/aaat/myfinance/frontend && npx tsc --noEmit --pretty false
```

Expected:

- backend import suite passes
- frontend review/upload tests pass
- TypeScript passes with no errors

- [ ] **Step 4: Smoke-test manually with ignored local PDF**

Run:

```bash
docker compose up -d
open http://localhost:8080
```

Manual checks:

- Upload ignored local Beobank Mastercard PDF from `/Users/aaat/myfinance/bank_files/`
- App navigates to review page
- Page 1 summary rows do not appear
- `WISSELKOSTEN` rows appear
- Evidence panel line locator matches selected row
- Approve creates transactions with `source_bank = Beobank`

- [ ] **Step 5: Commit**

```bash
git add backend/tests/imports/test_import_review_api.py backend/tests/imports/test_import_workflow.py frontend/src/components/imports/ImportReviewPage.test.tsx
git commit -m "test: cover pdf import edge cases"
```

---

## Self-Review

- **Spec coverage:** This plan covers contract alignment, deterministic PDF parsing, post-detection orchestration, review APIs/UI, commit behavior, duplicate checks, and verification. No approved spec section is left unassigned.
- **Placeholder scan:** No `TODO`, `TBD`, or “handle appropriately” steps remain. Every task has explicit files, commands, and code targets.
- **Type consistency:** The plan consistently uses `deterministic_extracted`, `PdfStatementExtractor`, `BeobankMastercardPdfExtractor`, `ImportWorkflowService`, and committed traceability fields `import_session_id`, `import_source_locator`, `import_source_description`, `canonical_description_en`.

