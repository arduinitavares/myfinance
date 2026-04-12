# Bank Files Batch Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click `Import bank_files` flow that scans the configured folder, processes supported PDF statements through the existing import-session review workflow, persists batch results, and safely reuses or replaces same-hash sessions across both batch and single-file upload paths.

**Architecture:** Keep the existing PDF import pipeline and review model, but add a small batch orchestration layer plus persistent batch-run tables. Centralize same-hash ownership rules in one backend helper so `/imports/upload` and `/imports/batch-folder` share identical duplicate handling, including the poisoned-session escape hatch.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, React, React Router, Axios, Jest, React Testing Library, Docker Compose

---

## File Structure

### Backend

- Create: `backend/app/imports/dedupe.py`
  - Owns canonical same-hash owner selection, retryable-session checks, and replacement-session escape hatch logic.
- Create: `backend/app/imports/batch_folder.py`
  - Owns folder scan, guardrails, per-file processing, persisted batch-run lifecycle, and latest-batch lookup.
- Modify: `backend/app/config.py`
  - Add `batch_import_dir` setting from `MYFINANCE_BATCH_IMPORT_DIR`.
- Modify: `backend/app/models/imports.py`
  - Add `ImportBatchRun` / `ImportBatchItem` models and reflect unique file-hash intent.
- Modify: `backend/app/models/__init__.py`
  - Export new import batch models.
- Modify: `backend/app/database_manager.py`
  - Add idempotent bootstrap/migration helpers for import batch tables and `import_sessions.file_hash` uniqueness backfill.
- Modify: `backend/app/schemas/imports.py`
  - Add batch response models and duplicate-upload response model.
- Modify: `backend/app/imports/pipeline.py`
  - Use shared dedupe helper before and after insert attempts; raise typed duplicate result instead of leaking DB failure.
- Modify: `backend/app/routers/imports.py`
  - Add `/imports/batch-folder`, `/imports/batches/{id}`, `/imports/batches/latest`, and duplicate-safe `/imports/upload` behavior.
- Test: `backend/tests/imports/test_import_models.py`
  - Verify new import batch tables / schema.
- Create: `backend/tests/imports/test_import_dedupe.py`
  - Cover canonical-owner precedence, retryable failed detection, and replacement-session path.
- Create: `backend/tests/imports/test_import_batch_api.py`
  - Cover batch-folder route, persisted batch runs, latest route, unsupported CSV reporting, and mid-run failure finalization.
- Modify: `backend/tests/imports/test_import_review_api.py`
  - Replace duplicate single-upload expectations with `409` usable-owner path and add replacement-session behavior.

### Frontend

- Modify: `frontend/src/types/import.ts`
  - Add batch-run, batch-item, and duplicate-upload detail types.
- Modify: `frontend/src/services/importService.ts`
  - Add batch import and batch lookup methods.
- Create: `frontend/src/components/imports/ImportBatchResultsPage.tsx`
  - Render persisted batch summary and per-item actions.
- Create: `frontend/src/components/imports/ImportBatchResultsPage.test.tsx`
  - Cover loading, persisted reload, item rows, and action links.
- Modify: `frontend/src/App.tsx`
  - Register `/imports/batches/:batchId`.
- Modify: `frontend/src/components/FileUpload.tsx`
  - Add `Import bank_files` button, duplicate-upload `Open Existing` affordance, and batch navigation.
- Modify: `frontend/src/components/FileUpload.test.tsx`
  - Cover new batch button and duplicate-upload UX.

### Runtime

- Modify: `docker-compose.yaml`
  - Mount `./bank_files:/bank_files:ro` and set `MYFINANCE_BATCH_IMPORT_DIR=/bank_files`.

---

### Task 1: Add Config And Persistent Batch Tables

**Files:**
- Create: none
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/imports.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database_manager.py`
- Test: `backend/tests/imports/test_import_models.py`

- [ ] **Step 1: Write the failing schema/config tests**

```python
# backend/tests/imports/test_import_models.py
from importlib import reload

from sqlalchemy import inspect

import app.config as config_module
from app.database import engine
from app.models.imports import ImportBatchItem, ImportBatchRun


def test_settings_exposes_batch_import_dir(monkeypatch, tmp_path):
    batch_dir = tmp_path / "bank_files"
    monkeypatch.setenv("MYFINANCE_BATCH_IMPORT_DIR", str(batch_dir))

    reloaded = reload(config_module)

    assert reloaded.settings.batch_import_dir == batch_dir.resolve()


def test_import_batch_tables_exist_after_init_database():
    inspector = inspect(engine)

    assert "import_batch_runs" in inspector.get_table_names()
    assert "import_batch_items" in inspector.get_table_names()

    batch_item_columns = {column["name"] for column in inspector.get_columns("import_batch_items")}
    assert {"batch_run_id", "filename", "status", "session_id", "existing_session_id"} <= batch_item_columns
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/imports/test_import_models.py -v`

Expected: FAIL because `Settings` has no `batch_import_dir` and import batch tables do not exist.

- [ ] **Step 3: Add the setting and SQLAlchemy models**

```python
# backend/app/config.py
@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    imports_dir: Path
    batch_import_dir: Path
    provider_config_path: Path
    provider_example_path: Path


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("MYFINANCE_DATA_DIR", APP_DIR / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)

    batch_import_dir = Path(os.environ.get("MYFINANCE_BATCH_IMPORT_DIR", "/bank_files")).resolve()

    return Settings(
        data_dir=data_dir,
        database_path=database_path,
        imports_dir=imports_dir,
        batch_import_dir=batch_import_dir,
        provider_config_path=provider_config_path,
        provider_example_path=provider_example_path,
    )
```

```python
# backend/app/models/imports.py
class ImportBatchRun(Base):
    __tablename__ = "import_batch_runs"

    id = Column(Integer, primary_key=True, index=True)
    folder_path = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=True)
    total_files = Column(Integer, nullable=False, default=0)
    processed_count = Column(Integer, nullable=False, default=0)
    skipped_existing_count = Column(Integer, nullable=False, default=0)
    unsupported_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ImportBatchItem(Base):
    __tablename__ = "import_batch_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_run_id = Column(Integer, ForeignKey("import_batch_runs.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(128), nullable=True)
    status = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=True)
    session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=True, index=True)
    session_status = Column(String(50), nullable=True)
    existing_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=True, index=True)
    existing_session_status = Column(String(50), nullable=True)
    strategy_key = Column(String(50), nullable=True)
    extractor_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
```

```python
# backend/app/database_manager.py
def _ensure_import_batch_tables() -> None:
    Base.metadata.create_all(
        bind=engine,
        tables=[ImportBatchRun.__table__, ImportBatchItem.__table__],
    )
```

- [ ] **Step 4: Wire the new models into bootstrap imports**

```python
# backend/app/models/__init__.py
from .imports import (
    ImportBatchItem,
    ImportBatchRun,
    ImportIssue,
    ImportSession,
    ImportStatementDraft,
    ImportTransactionDraft,
)
```

```python
# backend/app/database_manager.py
def init_database():
    ...
    _ensure_import_batch_tables()
    ...
    tables_to_check = [
        ...
        "import_batch_runs",
        "import_batch_items",
    ]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest backend/tests/imports/test_import_models.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/models/imports.py backend/app/models/__init__.py backend/app/database_manager.py backend/tests/imports/test_import_models.py
git commit -m "feat: add import batch config and tables"
```

### Task 2: Centralize Same-Hash Owner Selection And Safe Replacement

**Files:**
- Create: `backend/app/imports/dedupe.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/models/imports.py`
- Test: `backend/tests/imports/test_import_dedupe.py`

- [ ] **Step 1: Write the failing dedupe tests**

```python
# backend/tests/imports/test_import_dedupe.py
from app.imports.dedupe import choose_canonical_session, is_retryable_failed_session
from app.imports.state_machine import ImportSessionStatus
from app.models.imports import ImportSession


def test_choose_canonical_session_prefers_awaiting_review_over_older_failed(tmp_path):
    failed = ImportSession(
        id=1,
        file_name="statement.pdf",
        file_hash="abc",
        mime_type="application/pdf",
        status=ImportSessionStatus.FAILED.value,
        strategy_key="unknown",
    )
    reviewable = ImportSession(
        id=2,
        file_name="statement.pdf",
        file_hash="abc",
        mime_type="application/pdf",
        status=ImportSessionStatus.AWAITING_REVIEW.value,
        strategy_key="pdf_statement",
    )

    chosen = choose_canonical_session([failed, reviewable], artifact_root=tmp_path)

    assert chosen.id == 2


def test_is_retryable_failed_session_requires_pdf_statement_and_original_file(tmp_path):
    session = ImportSession(
        id=3,
        file_name="statement.pdf",
        file_hash="abc",
        mime_type="application/pdf",
        status=ImportSessionStatus.FAILED.value,
        strategy_key="pdf_statement",
    )

    assert is_retryable_failed_session(session, artifact_root=tmp_path) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/imports/test_import_dedupe.py -v`

Expected: FAIL because `app.imports.dedupe` does not exist.

- [ ] **Step 3: Implement canonical-owner precedence and retryable checks**

```python
# backend/app/imports/dedupe.py
from pathlib import Path

from app.imports.state_machine import ImportSessionStatus
from app.models.imports import ImportSession


def is_retryable_failed_session(session: ImportSession, *, artifact_root: Path) -> bool:
    if session.status != ImportSessionStatus.FAILED.value:
        return False
    if session.strategy_key != "pdf_statement":
        return False
    return (artifact_root / str(session.id) / "original" / session.file_name).exists()


def _session_rank(session: ImportSession, *, artifact_root: Path) -> tuple[int, str]:
    if session.status in {
        ImportSessionStatus.COMMITTED.value,
        ImportSessionStatus.PARTIALLY_COMMITTED.value,
    }:
        return (0, session.created_at.isoformat())
    if session.status == ImportSessionStatus.AWAITING_REVIEW.value:
        return (1, session.created_at.isoformat())
    if is_retryable_failed_session(session, artifact_root=artifact_root):
        return (2, session.created_at.isoformat())
    return (3, session.created_at.isoformat())


def choose_canonical_session(sessions: list[ImportSession], *, artifact_root: Path) -> ImportSession:
    return sorted(sessions, key=lambda session: _session_rank(session, artifact_root=artifact_root))[0]
```

- [ ] **Step 4: Add the backfill helper for duplicate hashes**

```python
# backend/app/database_manager.py
def _ensure_import_session_file_hash_uniqueness() -> None:
    inspector = inspect(engine)
    if "import_sessions" not in inspector.get_table_names():
        return

    with Session(engine) as db:
        duplicate_hashes = [
            row[0]
            for row in db.execute(
                text(
                    "SELECT file_hash FROM import_sessions "
                    "GROUP BY file_hash HAVING COUNT(*) > 1"
                )
            )
        ]

        for file_hash in duplicate_hashes:
            sessions = (
                db.query(ImportSession)
                .filter(ImportSession.file_hash == file_hash)
                .order_by(ImportSession.created_at.asc(), ImportSession.id.asc())
                .all()
            )
            canonical = choose_canonical_session(sessions, artifact_root=settings.imports_dir)
            for session in sessions:
                if session.id == canonical.id:
                    continue
                session.file_hash = f"{file_hash}#legacy-duplicate#{session.id}"
                if session.status not in {"committed", "partially_committed"}:
                    session.status = ImportSessionStatus.SUPERSEDED.value
        db.commit()

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_import_sessions_file_hash "
                "ON import_sessions (file_hash)"
            )
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/imports/test_import_dedupe.py backend/tests/imports/test_import_models.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/imports/dedupe.py backend/app/database_manager.py backend/tests/imports/test_import_dedupe.py backend/tests/imports/test_import_models.py
git commit -m "feat: add canonical import hash owner rules"
```

### Task 3: Make Single-File Upload Duplicate-Safe

**Files:**
- Modify: `backend/app/imports/pipeline.py`
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/app/schemas/imports.py`
- Modify: `backend/tests/imports/test_import_review_api.py`
- Test: `backend/tests/imports/test_import_review_api.py`

- [ ] **Step 1: Replace the old duplicate-upload expectation with failing API tests**

```python
# backend/tests/imports/test_import_review_api.py
def test_upload_duplicate_pdf_returns_existing_session_payload(db_session, monkeypatch):
    first = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", b"%PDF-1.7\nstub", "application/pdf")},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["file_hash"]
    assert detail["existing_session"]["id"] == first["id"]


def test_upload_duplicate_pdf_with_non_retryable_owner_creates_replacement(db_session, monkeypatch):
    first = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)
    db_session.expire_all()
    poisoned = db_session.get(ImportSession, first["id"])
    poisoned.status = "failed"
    poisoned.strategy_key = "unknown"
    db_session.commit()

    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", b"%PDF-1.7\nstub", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["id"] != first["id"]
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `pytest backend/tests/imports/test_import_review_api.py -k "duplicate_pdf" -v`

Expected: FAIL because `/imports/upload` still returns `200` for duplicate bytes.

- [ ] **Step 3: Add a typed duplicate result to the pipeline**

```python
# backend/app/schemas/imports.py
class ImportDuplicateResponse(BaseModel):
    message: str
    file_hash: str
    existing_session: ImportSessionResponse
```

```python
# backend/app/imports/pipeline.py
class ImportDuplicateFileError(RuntimeError):
    def __init__(self, *, file_hash: str, existing_session: ImportSession) -> None:
        super().__init__("This file was already uploaded.")
        self.file_hash = file_hash
        self.existing_session = existing_session


def start_upload(self, *, filename: str, content_type: str, file_bytes: bytes):
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = resolve_existing_hash_owner(self.db, file_hash=file_hash, filename=filename, file_bytes=file_bytes)
    if existing is not None:
        raise ImportDuplicateFileError(file_hash=file_hash, existing_session=existing)
    ...
```

- [ ] **Step 4: Translate duplicate uploads into `409` in the router**

```python
# backend/app/routers/imports.py
@router.post("/upload", response_model=ImportSessionResponse)
async def upload_import(...):
    ...
    try:
        session, detection = pipeline.start_upload(...)
    except ImportDuplicateFileError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "file_hash": exc.file_hash,
                "existing_session": workflow.get_session_snapshot(exc.existing_session.id),
            },
        ) from exc
```

- [ ] **Step 5: Run the API tests to verify they pass**

Run: `pytest backend/tests/imports/test_import_review_api.py -k "duplicate_pdf" -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/imports/pipeline.py backend/app/routers/imports.py backend/app/schemas/imports.py backend/tests/imports/test_import_review_api.py
git commit -m "feat: make single-file import uploads duplicate-safe"
```

### Task 4: Add Batch Folder Backend Service And Routes

**Files:**
- Create: `backend/app/imports/batch_folder.py`
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/app/schemas/imports.py`
- Test: `backend/tests/imports/test_import_batch_api.py`

- [ ] **Step 1: Write the failing batch API tests**

```python
# backend/tests/imports/test_import_batch_api.py
def test_batch_folder_processes_pdf_and_reports_csv_as_unsupported(tmp_path, monkeypatch, db_session):
    batch_dir = tmp_path / "bank_files"
    batch_dir.mkdir()
    (batch_dir / "statement.pdf").write_bytes(b"%PDF-1.7\nstub")
    (batch_dir / "transactions.csv").write_text("date,description\n", encoding="utf-8")

    monkeypatch.setenv("MYFINANCE_BATCH_IMPORT_DIR", str(batch_dir))
    monkeypatch.setattr("app.imports.pdf_statement.read_pdf_page_text", lambda _: SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.post("/imports/batch-folder")

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["unsupported_count"] == 1
    assert payload["items"][1]["status"] == "unsupported"


def test_latest_batch_returns_persisted_failed_run(tmp_path, monkeypatch, db_session):
    batch_dir = tmp_path / "bank_files"
    batch_dir.mkdir()
    (batch_dir / "statement.pdf").write_bytes(b"%PDF-1.7\nstub")
    monkeypatch.setenv("MYFINANCE_BATCH_IMPORT_DIR", str(batch_dir))
    monkeypatch.setattr("app.imports.batch_folder.ImportBatchFolderService._process_pdf", side_effect=RuntimeError("boom"))

    client.post("/imports/batch-folder")
    latest = client.get("/imports/batches/latest")

    assert latest.status_code == 200
    assert latest.json()["status"] == "failed"
    assert latest.json()["completed_at"] is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/imports/test_import_batch_api.py -v`

Expected: FAIL because the batch routes and service do not exist.

- [ ] **Step 3: Implement the batch service**

```python
# backend/app/imports/batch_folder.py
class ImportBatchFolderService:
    MAX_SCAN_FILES = 200
    MAX_PDF_FILES = 50

    def __init__(self, db: Session) -> None:
        self.db = db
        self.pipeline = ImportPipelineService(db)
        self.workflow = ImportWorkflowService(db)

    def run(self) -> ImportBatchRun:
        folder = settings.batch_import_dir
        children = sorted([child for child in folder.iterdir() if child.is_file()], key=lambda path: path.name.casefold())
        ...
        batch = ImportBatchRun(folder_path=str(folder), status="running", total_files=len(children))
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        try:
            for child in children:
                self._process_child(batch, child)
            batch.status = "completed"
            batch.completed_at = datetime.utcnow()
            self.db.commit()
        except Exception as exc:
            batch.status = "failed"
            batch.message = str(exc)
            batch.completed_at = datetime.utcnow()
            self.db.commit()
        return batch
```

- [ ] **Step 4: Add response models and routes**

```python
# backend/app/schemas/imports.py
class ImportBatchItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    file_hash: str | None = None
    status: str
    message: str | None = None
    session_id: int | None = None
    session_status: str | None = None
    existing_session_id: int | None = None
    existing_session_status: str | None = None
    strategy_key: str | None = None
    extractor_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImportBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    folder_path: str
    status: str
    message: str | None = None
    total_files: int
    processed_count: int
    skipped_existing_count: int
    unsupported_count: int
    failed_count: int
    created_at: datetime
    completed_at: datetime | None = None
    items: list[ImportBatchItemResponse]
```

```python
# backend/app/routers/imports.py
@router.post("/batch-folder", response_model=ImportBatchResponse)
def import_batch_folder(db: Session = Depends(get_db)):
    service = ImportBatchFolderService(db)
    return service.get_batch_payload(service.run().id)


@router.get("/batches/{batch_id}", response_model=ImportBatchResponse)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    return ImportBatchFolderService(db).get_batch_payload(batch_id)


@router.get("/batches/latest", response_model=ImportBatchResponse)
def get_latest_batch(db: Session = Depends(get_db)):
    return ImportBatchFolderService(db).get_latest_batch_payload()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/imports/test_import_batch_api.py backend/tests/imports/test_import_review_api.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/imports/batch_folder.py backend/app/routers/imports.py backend/app/schemas/imports.py backend/tests/imports/test_import_batch_api.py backend/tests/imports/test_import_review_api.py
git commit -m "feat: add bank_files batch import backend flow"
```

### Task 5: Add Frontend Types, Service Methods, And Batch Results Page

**Files:**
- Modify: `frontend/src/types/import.ts`
- Modify: `frontend/src/services/importService.ts`
- Create: `frontend/src/components/imports/ImportBatchResultsPage.tsx`
- Create: `frontend/src/components/imports/ImportBatchResultsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/imports/ImportBatchResultsPage.test.tsx`

- [ ] **Step 1: Write the failing batch results page test**

```tsx
// frontend/src/components/imports/ImportBatchResultsPage.test.tsx
test('loads and renders a persisted batch summary', async () => {
  mockedImportService.getBatchRun.mockResolvedValue({
    id: 7,
    folder_path: '/bank_files',
    status: 'completed',
    total_files: 2,
    processed_count: 1,
    skipped_existing_count: 0,
    unsupported_count: 1,
    failed_count: 0,
    created_at: '2026-04-12T12:00:00',
    completed_at: '2026-04-12T12:00:10',
    items: [
      { id: 1, filename: 'statement.pdf', status: 'processed', session_id: 12, session_status: 'awaiting_review' },
      { id: 2, filename: 'transactions.csv', status: 'unsupported', message: 'CSV batch import is not supported in v1; use Upload File.' },
    ],
  } as any);

  render(<ImportBatchResultsPage />);

  expect(await screen.findByText('statement.pdf')).toBeInTheDocument();
  expect(screen.getByText('transactions.csv')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /review/i })).toHaveAttribute('href', '/imports/12/review');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- --runInBand ImportBatchResultsPage.test.tsx`

Expected: FAIL because the page, types, and service methods do not exist.

- [ ] **Step 3: Add types and service methods**

```ts
// frontend/src/types/import.ts
export interface ImportBatchItem {
  id: number;
  filename: string;
  file_hash: string | null;
  status: 'processed' | 'skipped_existing' | 'unsupported' | 'failed';
  message: string | null;
  session_id: number | null;
  session_status: string | null;
  existing_session_id: number | null;
  existing_session_status: string | null;
  strategy_key: string | null;
  extractor_id: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ImportBatchRun {
  id: number;
  folder_path: string;
  status: 'running' | 'completed' | 'failed';
  message: string | null;
  total_files: number;
  processed_count: number;
  skipped_existing_count: number;
  unsupported_count: number;
  failed_count: number;
  created_at: string;
  completed_at: string | null;
  items: ImportBatchItem[];
}
```

```ts
// frontend/src/services/importService.ts
async startBatchFolderImport(): Promise<ImportBatchRun> {
  const response = await axios.post(`${API_BASE_URL}/imports/batch-folder`);
  return response.data;
},

async getBatchRun(batchId: number): Promise<ImportBatchRun> {
  const response = await axios.get(`${API_BASE_URL}/imports/batches/${batchId}`);
  return response.data;
},

async getLatestBatchRun(): Promise<ImportBatchRun> {
  const response = await axios.get(`${API_BASE_URL}/imports/batches/latest`);
  return response.data;
},
```

- [ ] **Step 4: Implement the page and route**

```tsx
// frontend/src/components/imports/ImportBatchResultsPage.tsx
export const ImportBatchResultsPage: React.FC = () => {
  const { batchId } = useParams();
  const [batch, setBatch] = useState<ImportBatchRun | null>(null);

  useEffect(() => {
    if (!batchId) return;
    void importService.getBatchRun(Number(batchId)).then(setBatch);
  }, [batchId]);

  if (!batch) return <div>Loading batch results...</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Import Batch Results</h1>
      <p className="text-sm text-gray-500">{batch.folder_path}</p>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <div>Processed: {batch.processed_count}</div>
        <div>Skipped: {batch.skipped_existing_count}</div>
        <div>Unsupported: {batch.unsupported_count}</div>
        <div>Failed: {batch.failed_count}</div>
        <div>Status: {batch.status}</div>
      </div>
      <ul className="space-y-3">
        {batch.items.map((item) => (
          <li key={item.id} className="rounded-md border p-4">
            <div className="font-medium">{item.filename}</div>
            <div className="text-sm text-gray-500">{item.status}</div>
          </li>
        ))}
      </ul>
    </div>
  );
};
```

```tsx
// frontend/src/App.tsx
<Route
  path="/imports/batches/:batchId"
  element={
    <MainLayout onUploadSuccess={handleUploadSuccess}>
      <ImportBatchResultsPage />
    </MainLayout>
  }
/>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- --runInBand ImportBatchResultsPage.test.tsx`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/import.ts frontend/src/services/importService.ts frontend/src/components/imports/ImportBatchResultsPage.tsx frontend/src/components/imports/ImportBatchResultsPage.test.tsx frontend/src/App.tsx
git commit -m "feat: add batch import results page"
```

### Task 6: Update FileUpload And Runtime Wiring

**Files:**
- Modify: `frontend/src/components/FileUpload.tsx`
- Modify: `frontend/src/components/FileUpload.test.tsx`
- Modify: `docker-compose.yaml`
- Test: `frontend/src/components/FileUpload.test.tsx`

- [ ] **Step 1: Write the failing FileUpload tests**

```tsx
// frontend/src/components/FileUpload.test.tsx
test('starts bank_files import and navigates to batch results', async () => {
  mockedImportService.startBatchFolderImport.mockResolvedValue({
    id: 5,
    status: 'completed',
  } as any);

  render(<FileUpload onUploadSuccess={jest.fn()} />);

  fireEvent.click(screen.getByRole('button', { name: /import bank_files/i }));

  await waitFor(() => {
    expect(mockedImportService.startBatchFolderImport).toHaveBeenCalledTimes(1);
  });
  expect(mockNavigate).toHaveBeenCalledWith('/imports/batches/5');
});


test('offers Open Existing when pdf upload returns duplicate 409', async () => {
  mockIsAxiosError = true;
  mockedImportService.uploadStatement.mockRejectedValue({
    response: {
      status: 409,
      data: {
        detail: {
          message: 'This file was already uploaded.',
          file_hash: 'abc',
          existing_session: { id: 14 },
        },
      },
    },
  } as never);

  render(<FileUpload onUploadSuccess={jest.fn()} />);

  fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
    target: { files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' })] },
  });

  expect(await screen.findByRole('button', { name: /open existing/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- --runInBand FileUpload.test.tsx`

Expected: FAIL because `startBatchFolderImport` is not wired into `FileUpload` and duplicate `409` is not handled.

- [ ] **Step 3: Add the batch button and duplicate-upload state**

```tsx
// frontend/src/components/FileUpload.tsx
const [duplicateSessionId, setDuplicateSessionId] = useState<number | null>(null);
const [batchLoading, setBatchLoading] = useState(false);

const handleBatchImport = async () => {
  setBatchLoading(true);
  setError(null);
  try {
    const batch = await importService.startBatchFolderImport();
    navigate(`/imports/batches/${batch.id}`);
  } catch (err) {
    setError('Could not import bank_files right now.');
  } finally {
    setBatchLoading(false);
  }
};
```

```tsx
// frontend/src/components/FileUpload.tsx
catch (err) {
  ...
  if (status === 409 && detail?.existing_session?.id) {
    setDuplicateSessionId(detail.existing_session.id);
    message = detail.message || 'This file was already uploaded.';
  }
  ...
}
```

```tsx
// frontend/src/components/FileUpload.tsx
<div className="flex gap-3">
  <Dialog.Root>...</Dialog.Root>
  <button
    type="button"
    onClick={() => { void handleBatchImport(); }}
    disabled={loading || batchLoading}
    className="inline-flex items-center px-4 py-2 border rounded-md text-sm font-medium"
  >
    {batchLoading ? 'Processing bank_files...' : 'Import bank_files'}
  </button>
</div>
```

- [ ] **Step 4: Add the duplicate-upload action and Docker mount**

```tsx
// frontend/src/components/FileUpload.tsx
{duplicateSessionId ? (
  <button
    type="button"
    onClick={() => navigate(`/imports/${duplicateSessionId}/review`)}
    className="inline-flex items-center rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700"
  >
    Open Existing
  </button>
) : null}
```

```yaml
# docker-compose.yaml
services:
  backend:
    volumes:
      - ./backend:/app
      - ./bank_files:/bank_files:ro
      - myfinance-data:/app/app/data
    environment:
      - MYFINANCE_BATCH_IMPORT_DIR=/bank_files
```

- [ ] **Step 5: Run the tests and runtime config check**

Run: `npm test -- --runInBand FileUpload.test.tsx`

Expected: PASS

Run: `docker compose config | rg "/bank_files|MYFINANCE_BATCH_IMPORT_DIR"`

Expected:

```text
- ./bank_files:/bank_files:ro
- MYFINANCE_BATCH_IMPORT_DIR=/bank_files
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/FileUpload.tsx frontend/src/components/FileUpload.test.tsx docker-compose.yaml
git commit -m "feat: wire batch import entry point"
```

## Self-Review

- Spec coverage:
  - PDF-only batch scope: covered in Tasks 4 and 6.
  - Persistent batch runs and latest recovery: covered in Task 4.
  - Global duplicate-safe hash ownership: covered in Tasks 2 and 3.
  - Canonical owner precedence and poisoned-session escape hatch: covered in Task 2 and Task 3.
  - Frontend `Import bank_files` button and results page: covered in Tasks 5 and 6.
  - Docker/runtime folder mount and config path: covered in Task 6.
- Placeholder scan:
  - No `TODO`, `TBD`, or “implement later” markers remain.
- Type consistency:
  - Batch response models use the same field names across backend schemas, frontend types, and route snippets.
  - Duplicate upload contract uses `message`, `file_hash`, and `existing_session` consistently in backend and frontend tasks.

