# Import Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared backend import foundation for statement ingestion: runtime config, import contracts, session state machine, import draft tables, artifact storage, detection skeleton, provider registry, and fixture-safe CI-ready tests.

**Architecture:** Keep PR 1 backend-only and do not wire the new pipeline into the existing upload route yet. Build the import foundation as an isolated `app.imports` package plus import draft models, so PRs 2 and 3 can add deterministic CSV extractors without revisiting core contracts, filesystem layout, or provider configuration.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, PyYAML, GitHub Actions

---

## Planned File Map

**Create**

- `backend/app/config.py`
  Centralize runtime paths for data, database, import artifacts, and provider config files.
- `backend/app/imports/__init__.py`
  Export the import foundation package surface.
- `backend/app/imports/contracts.py`
  Define `DetectionResult`, `RawEvidence`, `ImportIssue`, `ExtractedTransaction`, `ExtractionResult`, and provider audit description models.
- `backend/app/imports/state_machine.py`
  Define `ImportSessionStatus`, allowed transitions, and helpers that raise on invalid transitions.
- `backend/app/imports/artifacts.py`
  Write `meta.json`, `detection.json`, original uploads, and `attempts/<n>/evidence/raw.json`.
- `backend/app/imports/detection.py`
  Detect `pdf_statement` vs `unknown`, including `charset_hint`.
- `backend/app/imports/pipeline.py`
  Create import sessions, save original files, run detection, update state, and persist detection artifacts.
- `backend/app/imports/providers.py`
  Load provider config, validate env-backed availability, and expose family lookup.
- `backend/app/models/imports.py`
  Add `ImportSession`, `ImportStatementDraft`, `ImportTransactionDraft`, and `ImportIssue`.
- `backend/tests/conftest.py`
  Isolate test data paths and database paths from local development data.
- `backend/tests/imports/test_runtime_config.py`
- `backend/tests/imports/test_contracts.py`
- `backend/tests/imports/test_state_machine.py`
- `backend/tests/imports/test_import_models.py`
- `backend/tests/imports/test_artifacts.py`
- `backend/tests/imports/test_detection.py`
- `backend/tests/imports/test_pipeline.py`
- `backend/tests/imports/test_provider_registry.py`
- `backend/tests/imports/test_sanitize_fixture.py`
- `backend/pytest.ini`
  Exclude `tests/live/` from default runs.
- `backend/config.example.yaml`
  Ship disabled provider families and example fields.
- `scripts/sanitize_fixture.py`
  Provide a first-pass sanitizer for obvious account/card patterns before fixtures land in git.
- `.github/workflows/backend-tests.yml`
  Run backend tests in CI without live providers.

**Modify**

- `backend/app/database.py`
  Read database path from `app.config.settings`.
- `backend/app/database_manager.py`
  Include import tables in bootstrap checks and reset helpers.
- `backend/app/models/__init__.py`
  Export the new import models.
- `backend/requirements.txt`
  Add `pytest`.
- `.gitignore`
  Ignore backend runtime data, local backend config, and test temp directories.

## Task 1: Runtime Config and Test Harness

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/imports/test_runtime_config.py`
- Create: `backend/pytest.ini`
- Modify: `backend/app/database.py`
- Modify: `backend/requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing runtime-config test and test bootstrap**

```python
# backend/tests/conftest.py
import os
import shutil
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent / ".tmp"
shutil.rmtree(TEST_ROOT, ignore_errors=True)
(TEST_ROOT / "data").mkdir(parents=True, exist_ok=True)
os.environ["MYFINANCE_DATA_DIR"] = str((TEST_ROOT / "data").resolve())
os.environ["MYFINANCE_PROVIDER_CONFIG"] = str((TEST_ROOT / "config.local.yaml").resolve())
```

```python
# backend/tests/imports/test_runtime_config.py
from app.config import settings


def test_settings_use_isolated_backend_test_paths():
    assert "backend/tests/.tmp/data" in str(settings.data_dir)
    assert settings.database_path.parent == settings.data_dir
    assert settings.imports_dir.parent == settings.data_dir
    assert settings.provider_config_path.name == "config.local.yaml"
```

- [ ] **Step 2: Run the test to verify the current repo does not support it**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_runtime_config.py -q`

Expected: FAIL with `No module named pytest` or `No module named 'app.config'`

- [ ] **Step 3: Add pytest, runtime settings, and backend test isolation**

```python
# backend/app/config.py
from dataclasses import dataclass
from pathlib import Path
import os

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    imports_dir: Path
    provider_config_path: Path
    provider_example_path: Path


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("MYFINANCE_DATA_DIR", APP_DIR / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    database_path = Path(os.environ.get("MYFINANCE_DB_PATH", data_dir / "myfinance.db")).resolve()
    provider_config_path = Path(
        os.environ.get("MYFINANCE_PROVIDER_CONFIG", BACKEND_DIR / "config.local.yaml")
    ).resolve()
    provider_example_path = (BACKEND_DIR / "config.example.yaml").resolve()
    return Settings(
        data_dir=data_dir,
        database_path=database_path,
        imports_dir=imports_dir,
        provider_config_path=provider_config_path,
        provider_example_path=provider_example_path,
    )


settings = load_settings()
```

```python
# backend/app/database.py
from .config import settings

DATABASE_PATH = str(settings.database_path)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
```

```ini
# backend/pytest.ini
[pytest]
testpaths = tests
addopts = --ignore=tests/live
```

```text
# backend/requirements.txt
pytest==8.3.5
PyYAML==6.0.2
```

```gitignore
# .gitignore
/backend/app/data/
/backend/config.local.yaml
/backend/tests/.tmp/
```

- [ ] **Step 4: Run the test again to verify the isolated runtime config passes**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_runtime_config.py -q`

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend/app/config.py backend/app/database.py backend/pytest.ini backend/requirements.txt backend/tests/conftest.py backend/tests/imports/test_runtime_config.py
git commit -m "test: add backend import runtime harness"
```

### Task 2: Import Contracts

**Files:**
- Create: `backend/app/imports/__init__.py`
- Create: `backend/app/imports/contracts.py`
- Create: `backend/tests/imports/test_contracts.py`

- [ ] **Step 1: Write the failing contract-serialization test**

```python
# backend/tests/imports/test_contracts.py
from app.imports.contracts import (
    DetectionResult,
    ExtractionResult,
    ExtractedTransaction,
    ImportIssue,
    ImportStrategyKey,
    RawEvidence,
)


def test_extraction_result_serializes_blocking_issues_and_nullable_fields():
    result = ExtractionResult(
        extractor_id="csv.stub",
        raw_artifact_ref="imports/session-1/attempts/1/evidence/raw.json",
        source_metadata={"provider_hint": "belfius", "file_type": "csv", "language": "nl"},
        statement_metadata={"currency": "EUR"},
        transactions=[
            ExtractedTransaction(
                transaction_date="2026-04-11",
                source_description="Bancontact betaling",
                canonical_description_en=None,
                signed_amount=-10.0,
                currency="EUR",
                debit_credit="debit",
                inferred_category=None,
                category_source=None,
                confidence={"amount": 1.0},
                source_locator="csv:row:2",
                edit_source="ai_extracted",
            )
        ],
        issues=[
            ImportIssue(
                code="missing_balance",
                message="Balance missing from statement footer",
                blocking=True,
                transaction_ref=None,
            )
        ],
        overall_confidence=0.91,
    )

    dumped = result.model_dump()
    assert dumped["issues"][0]["blocking"] is True
    assert dumped["transactions"][0]["canonical_description_en"] is None


def test_raw_evidence_is_json_serializable():
    evidence = RawEvidence(
        text_blocks=[{"page": 1, "text": "Statement header"}],
        ocr_blocks=[],
        snippets=[{"page": 1, "text": "Bancontact betaling"}],
    )
    assert evidence.model_dump()["snippets"][0]["text"] == "Bancontact betaling"


def test_detection_result_exposes_strategy_enum():
    detected = DetectionResult(
        strategy_key=ImportStrategyKey.PDF_STATEMENT,
        provider_hint="beobank",
        language_hint="nl",
        charset_hint=None,
        confidence=0.8,
        page_count=2,
        password_protected=False,
        notes=[],
    )
    assert detected.strategy_key == ImportStrategyKey.PDF_STATEMENT
```

- [ ] **Step 2: Run the contract test to confirm the package does not exist yet**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_contracts.py -q`

Expected: FAIL with `No module named 'app.imports'`

- [ ] **Step 3: Add the shared import contracts**

```python
# backend/app/imports/contracts.py
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ImportStrategyKey(str, Enum):
    BELFIUS_CSV = "belfius_csv"
    BEOBANK_CSV = "beobank_csv"
    PDF_STATEMENT = "pdf_statement"
    UNKNOWN = "unknown"


class ImportIssue(BaseModel):
    code: str
    message: str
    blocking: bool
    transaction_ref: str | None = None


class DetectionResult(BaseModel):
    strategy_key: ImportStrategyKey
    provider_hint: str | None = None
    language_hint: str | None = None
    charset_hint: str | None = None
    confidence: float = 0.0
    page_count: int | None = None
    password_protected: bool = False
    notes: list[str] = Field(default_factory=list)


class RawEvidence(BaseModel):
    text_blocks: list[dict[str, Any]] = Field(default_factory=list)
    ocr_blocks: list[dict[str, Any]] = Field(default_factory=list)
    snippets: list[dict[str, Any]] = Field(default_factory=list)


class ExtractedTransaction(BaseModel):
    transaction_date: str
    source_description: str
    canonical_description_en: str | None = None
    signed_amount: float
    currency: str
    debit_credit: str
    inferred_category: str | None = None
    category_source: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    source_locator: str
    edit_source: str = "ai_extracted"


class ExtractionResult(BaseModel):
    extractor_id: str
    raw_artifact_ref: str
    source_metadata: dict[str, Any]
    statement_metadata: dict[str, Any]
    transactions: list[ExtractedTransaction]
    issues: list[ImportIssue] = Field(default_factory=list)
    overall_confidence: float = 0.0


class ProviderDescription(BaseModel):
    provider_name: str
    model_name: str
    schema_version: str
    prompt_fingerprint: str
```

```python
# backend/app/imports/__init__.py
from .contracts import (
    DetectionResult,
    ExtractionResult,
    ExtractedTransaction,
    ImportIssue,
    ImportStrategyKey,
    ProviderDescription,
    RawEvidence,
)
```

- [ ] **Step 4: Run the contract tests**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_contracts.py -q`

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/__init__.py backend/app/imports/contracts.py backend/tests/imports/test_contracts.py
git commit -m "feat: add import contracts"
```

### Task 3: Session State Machine and Import Persistence Models

**Files:**
- Create: `backend/app/imports/state_machine.py`
- Create: `backend/app/models/imports.py`
- Create: `backend/tests/imports/test_state_machine.py`
- Create: `backend/tests/imports/test_import_models.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Write failing tests for valid transitions and import-table creation**

```python
# backend/tests/imports/test_state_machine.py
import pytest

from app.imports.state_machine import ImportSessionStatus, assert_transition_allowed


def test_committed_state_requires_approved_chain():
    assert_transition_allowed(ImportSessionStatus.APPROVED, ImportSessionStatus.COMMITTING)
    assert_transition_allowed(ImportSessionStatus.COMMITTING, ImportSessionStatus.COMMITTED)


def test_invalid_transition_raises():
    with pytest.raises(ValueError):
        assert_transition_allowed(ImportSessionStatus.UPLOADED, ImportSessionStatus.COMMITTED)
```

```python
# backend/tests/imports/test_import_models.py
from sqlalchemy import inspect

from app.database import engine
from app.database_manager import init_database, reset_database


def test_import_tables_exist_after_init_database():
    reset_database()
    init_database()
    tables = set(inspect(engine).get_table_names())
    assert {
        "import_sessions",
        "import_statement_drafts",
        "import_transaction_drafts",
        "import_issues",
    } <= tables
```

- [ ] **Step 2: Run the tests to verify the state machine and tables do not exist yet**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_state_machine.py tests/imports/test_import_models.py -q`

Expected: FAIL with `No module named 'app.imports.state_machine'` and missing import tables

- [ ] **Step 3: Implement the state machine and import draft models**

```python
# backend/app/imports/state_machine.py
from enum import Enum


class ImportSessionStatus(str, Enum):
    UPLOADED = "uploaded"
    DETECTED = "detected"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    VALIDATED = "validated"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    COMMITTING = "committing"
    COMMITTED = "committed"
    FAILED = "failed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    PARTIALLY_COMMITTED = "partially_committed"


ALLOWED_STATUS_TRANSITIONS = {
    ImportSessionStatus.UPLOADED: {ImportSessionStatus.DETECTED, ImportSessionStatus.FAILED},
    ImportSessionStatus.DETECTED: {ImportSessionStatus.EXTRACTED, ImportSessionStatus.FAILED},
    ImportSessionStatus.EXTRACTED: {ImportSessionStatus.NORMALIZED, ImportSessionStatus.FAILED},
    ImportSessionStatus.NORMALIZED: {ImportSessionStatus.VALIDATED, ImportSessionStatus.FAILED},
    ImportSessionStatus.VALIDATED: {ImportSessionStatus.AWAITING_REVIEW, ImportSessionStatus.FAILED},
    ImportSessionStatus.AWAITING_REVIEW: {
        ImportSessionStatus.APPROVED,
        ImportSessionStatus.REJECTED,
        ImportSessionStatus.SUPERSEDED,
    },
    ImportSessionStatus.APPROVED: {ImportSessionStatus.COMMITTING},
    ImportSessionStatus.COMMITTING: {
        ImportSessionStatus.COMMITTED,
        ImportSessionStatus.PARTIALLY_COMMITTED,
        ImportSessionStatus.FAILED,
    },
    ImportSessionStatus.REJECTED: {ImportSessionStatus.SUPERSEDED},
    ImportSessionStatus.FAILED: {ImportSessionStatus.SUPERSEDED},
}


def assert_transition_allowed(current: ImportSessionStatus, target: ImportSessionStatus) -> None:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"Invalid import session transition: {current} -> {target}")
```

```python
# backend/app/models/imports.py
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text

from ..database import Base


class ImportSession(Base):
    __tablename__ = "import_sessions"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_hash = Column(String(128), nullable=False, index=True)
    mime_type = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    strategy_key = Column(String(50), nullable=True)
    provider_hint = Column(String(50), nullable=True)
    language_hint = Column(String(20), nullable=True)
    charset_hint = Column(String(50), nullable=True)
    extractor_id = Column(String(100), nullable=True)
    raw_artifact_ref = Column(String(255), nullable=True)
    error_stage = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    approved_by = Column(String(100), nullable=True)


class ImportStatementDraft(Base):
    __tablename__ = "import_statement_drafts"

    id = Column(Integer, primary_key=True, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    account_number_hint = Column(String(100), nullable=True)
    card_number_hint = Column(String(100), nullable=True)
    currency = Column(String(10), nullable=True)
    overall_confidence = Column(Float, nullable=False, default=0.0)
    review_status = Column(String(50), nullable=False, default="draft")


class ImportTransactionDraft(Base):
    __tablename__ = "import_transaction_drafts"

    id = Column(Integer, primary_key=True, index=True)
    import_statement_draft_id = Column(
        Integer,
        ForeignKey("import_statement_drafts.id"),
        nullable=False,
        index=True,
    )
    source_description = Column(Text, nullable=False)
    canonical_description_en = Column(Text, nullable=True)
    signed_amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    source_locator = Column(String(255), nullable=False)
    inferred_category = Column(String(100), nullable=True)
    category_source = Column(String(50), nullable=True)
    edit_source = Column(String(50), nullable=False, default="ai_extracted")


class ImportIssue(Base):
    __tablename__ = "import_issues"

    id = Column(Integer, primary_key=True, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    severity = Column(String(20), nullable=False)
    blocking = Column(Boolean, nullable=False, default=True)
    issue_code = Column(String(100), nullable=False)
    issue_message = Column(Text, nullable=False)
    transaction_ref = Column(String(255), nullable=True)
```

```python
# backend/app/models/__init__.py
from .imports import ImportIssue, ImportSession, ImportStatementDraft, ImportTransactionDraft
```

```python
# backend/app/database_manager.py
from .models.imports import ImportIssue, ImportSession, ImportStatementDraft, ImportTransactionDraft

tables_to_check = [
    "transactions",
    "financial_statistics",
    "category_statistics",
    "financial_health",
    "financial_recommendations",
    "projection_scenarios",
    "projection_parameters",
    "projection_results",
    "transaction_anomalies",
    "anomaly_patterns",
    "anomaly_rules",
    "import_sessions",
    "import_statement_drafts",
    "import_transaction_drafts",
    "import_issues",
]

elif reset_type == "imports":
    Base.metadata.drop_all(
        bind=engine,
        tables=[
            ImportIssue.__table__,
            ImportTransactionDraft.__table__,
            ImportStatementDraft.__table__,
            ImportSession.__table__,
        ],
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            ImportSession.__table__,
            ImportStatementDraft.__table__,
            ImportTransactionDraft.__table__,
            ImportIssue.__table__,
        ],
    )
```

```python
# backend/tests/conftest.py
import pytest

from app.database import SessionLocal
from app.database_manager import reset_database


@pytest.fixture
def db_session():
    reset_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Run the import foundation model tests**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_state_machine.py tests/imports/test_import_models.py -q`

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/state_machine.py backend/app/models/imports.py backend/app/models/__init__.py backend/app/database_manager.py backend/tests/conftest.py backend/tests/imports/test_state_machine.py backend/tests/imports/test_import_models.py
git commit -m "feat: add import session state and draft tables"
```

### Task 4: Artifact Store

**Files:**
- Create: `backend/app/imports/artifacts.py`
- Create: `backend/tests/imports/test_artifacts.py`

- [ ] **Step 1: Write the failing artifact-store test**

```python
# backend/tests/imports/test_artifacts.py
import json

from app.imports.artifacts import ArtifactStore
from app.imports.contracts import DetectionResult, ImportStrategyKey, RawEvidence


def test_artifact_store_writes_manifest_detection_and_raw_evidence():
    store = ArtifactStore()
    session_dir = store.init_session("session-001")
    store.write_meta("session-001", {"state": "uploaded", "attempt_count": 1})
    store.write_detection(
        "session-001",
        DetectionResult(
            strategy_key=ImportStrategyKey.UNKNOWN,
            provider_hint=None,
            language_hint="nl",
            charset_hint="latin-1",
            confidence=0.2,
            page_count=None,
            password_protected=False,
            notes=["headers not registered"],
        ),
    )
    store.write_raw_evidence(
        "session-001",
        1,
        RawEvidence(text_blocks=[{"page": 1, "text": "Statement header"}]),
    )

    assert session_dir.exists()
    assert json.loads((session_dir / "meta.json").read_text())["state"] == "uploaded"
    evidence_path = session_dir / "attempts" / "1" / "evidence" / "raw.json"
    assert json.loads(evidence_path.read_text())["text_blocks"][0]["text"] == "Statement header"
```

- [ ] **Step 2: Run the artifact-store test**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_artifacts.py -q`

Expected: FAIL with `No module named 'app.imports.artifacts'`

- [ ] **Step 3: Implement the artifact store**

```python
# backend/app/imports/artifacts.py
import json
from pathlib import Path

from app.config import settings
from app.imports.contracts import DetectionResult, RawEvidence


class ArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.imports_dir

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def init_session(self, session_id: str) -> Path:
        session_dir = self.session_dir(session_id)
        (session_dir / "original").mkdir(parents=True, exist_ok=True)
        return session_dir

    def attempt_dir(self, session_id: str, attempt_number: int) -> Path:
        attempt_dir = self.session_dir(session_id) / "attempts" / str(attempt_number)
        (attempt_dir / "evidence").mkdir(parents=True, exist_ok=True)
        (attempt_dir / "ai").mkdir(parents=True, exist_ok=True)
        (attempt_dir / "normalized").mkdir(parents=True, exist_ok=True)
        return attempt_dir

    def write_meta(self, session_id: str, payload: dict) -> None:
        self._write_json(self.session_dir(session_id) / "meta.json", payload)

    def write_detection(self, session_id: str, detection: DetectionResult) -> None:
        self._write_json(self.session_dir(session_id) / "detection.json", detection.model_dump())

    def write_raw_evidence(self, session_id: str, attempt_number: int, evidence: RawEvidence) -> None:
        attempt_dir = self.attempt_dir(session_id, attempt_number)
        self._write_json(attempt_dir / "evidence" / "raw.json", evidence.model_dump())

    def write_original_file(self, session_id: str, filename: str, file_bytes: bytes) -> Path:
        target = self.session_dir(session_id) / "original" / filename
        target.write_bytes(file_bytes)
        return target

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
```

- [ ] **Step 4: Run the artifact-store test**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_artifacts.py -q`

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/artifacts.py backend/tests/imports/test_artifacts.py
git commit -m "feat: add import artifact store"
```

### Task 5: Detection and Pipeline Skeleton

**Files:**
- Create: `backend/app/imports/detection.py`
- Create: `backend/app/imports/pipeline.py`
- Create: `backend/tests/imports/test_detection.py`
- Create: `backend/tests/imports/test_pipeline.py`

- [ ] **Step 1: Write the failing detection and pipeline tests**

```python
# backend/tests/imports/test_detection.py
from app.imports.detection import ImportDetector
from app.imports.contracts import ImportStrategyKey


def test_detector_flags_pdf_statements():
    result = ImportDetector().detect(
        filename="statement.pdf",
        content_type="application/pdf",
        sample=b"%PDF-1.7\n",
    )
    assert result.strategy_key == ImportStrategyKey.PDF_STATEMENT
    assert result.password_protected is False


def test_detector_sets_latin1_charset_for_unknown_csv():
    sample = "Datum;Debet\n01/01/2026;-10,00\n".encode("latin-1")
    result = ImportDetector().detect(
        filename="statement.csv",
        content_type="text/csv",
        sample=sample,
    )
    assert result.strategy_key == ImportStrategyKey.UNKNOWN
    assert result.charset_hint == "latin-1"
```

```python
# backend/tests/imports/test_pipeline.py
from app.imports.pipeline import ImportPipelineService
from app.imports.state_machine import ImportSessionStatus


def test_pipeline_creates_session_persists_upload_and_records_detection(db_session):
    service = ImportPipelineService(db_session)
    session, detection = service.start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nhello",
    )

    assert session.status == ImportSessionStatus.DETECTED.value
    assert session.strategy_key == detection.strategy_key.value
    assert session.file_name == "statement.pdf"
```

- [ ] **Step 2: Run the tests**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_detection.py tests/imports/test_pipeline.py -q`

Expected: FAIL with missing `app.imports.detection` / `app.imports.pipeline`

- [ ] **Step 3: Implement detection and the upload-to-detected pipeline skeleton**

```python
# backend/app/imports/detection.py
from app.imports.contracts import DetectionResult, ImportStrategyKey


class ImportDetector:
    def detect(self, *, filename: str, content_type: str, sample: bytes) -> DetectionResult:
        lower_name = filename.lower()
        if lower_name.endswith(".pdf") or content_type == "application/pdf":
            return DetectionResult(
                strategy_key=ImportStrategyKey.PDF_STATEMENT,
                provider_hint=None,
                language_hint=None,
                charset_hint=None,
                confidence=1.0,
                page_count=None,
                password_protected=False,
                notes=[],
            )

        charset_hint = "utf-8"
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            charset_hint = "latin-1"

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
# backend/app/imports/pipeline.py
import hashlib

from sqlalchemy.orm import Session

from app.imports.artifacts import ArtifactStore
from app.imports.detection import ImportDetector
from app.imports.state_machine import ImportSessionStatus, assert_transition_allowed
from app.models.imports import ImportSession


class ImportPipelineService:
    def __init__(
        self,
        db: Session,
        detector: ImportDetector | None = None,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.db = db
        self.detector = detector or ImportDetector()
        self.artifacts = artifacts or ArtifactStore()

    def start_upload(self, *, filename: str, content_type: str, file_bytes: bytes):
        session = ImportSession(
            file_name=filename,
            file_hash=hashlib.sha256(file_bytes).hexdigest(),
            mime_type=content_type,
            status=ImportSessionStatus.UPLOADED.value,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        session_id = str(session.id)
        self.artifacts.init_session(session_id)
        self.artifacts.write_original_file(session_id, filename, file_bytes)
        self.artifacts.write_meta(
            session_id,
            {"state": session.status, "attempt_count": 1, "stage_timestamps": {"uploaded": True}},
        )

        detection = self.detector.detect(
            filename=filename,
            content_type=content_type,
            sample=file_bytes[:4096],
        )
        assert_transition_allowed(ImportSessionStatus(session.status), ImportSessionStatus.DETECTED)
        session.status = ImportSessionStatus.DETECTED.value
        session.strategy_key = detection.strategy_key.value
        session.provider_hint = detection.provider_hint
        session.language_hint = detection.language_hint
        session.charset_hint = detection.charset_hint
        self.artifacts.write_detection(session_id, detection)
        self.artifacts.write_meta(
            session_id,
            {"state": session.status, "attempt_count": 1, "stage_timestamps": {"uploaded": True, "detected": True}},
        )
        self.db.commit()
        self.db.refresh(session)
        return session, detection
```

- [ ] **Step 4: Run the detection and pipeline tests**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_detection.py tests/imports/test_pipeline.py -q`

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/detection.py backend/app/imports/pipeline.py backend/tests/imports/test_detection.py backend/tests/imports/test_pipeline.py
git commit -m "feat: add import detection pipeline skeleton"
```

### Task 6: Provider Registry and Example Config

**Files:**
- Create: `backend/app/imports/providers.py`
- Create: `backend/tests/imports/test_provider_registry.py`
- Create: `backend/config.example.yaml`

- [ ] **Step 1: Write the failing provider-registry test**

```python
# backend/tests/imports/test_provider_registry.py
import textwrap

from app.imports.providers import ProviderRegistry


def test_provider_registry_marks_missing_env_provider_unavailable(tmp_path, monkeypatch):
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            document_extraction:
              order: [openai]
              fallback_on:
                - condition: low_confidence
                  threshold: 0.75
              providers:
                openai:
                  enabled: true
                  kind: openai
                  model: gpt-4o-mini
                  api_key_env: OPENAI_API_KEY
                  timeout_seconds: 30
                  max_retries: 2
                  supports_pdf: true
                  supports_images: true
                  supports_json_schema: true
                  cost_tier: metered
                  requires_confirmation: true
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    registry = ProviderRegistry.from_path(config_path)
    report = registry.validate()

    assert report["document_extraction"]["openai"]["available"] is False
    assert report["document_extraction"]["openai"]["reason"] == "missing_env"
```

- [ ] **Step 2: Run the provider-registry test**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_provider_registry.py -q`

Expected: FAIL with missing `app.imports.providers`

- [ ] **Step 3: Implement the provider registry and example config**

```python
# backend/app/imports/providers.py
from pathlib import Path
import os

import yaml
from pydantic import BaseModel, Field


class FallbackRule(BaseModel):
    condition: str
    threshold: float | None = None


class ProviderConfig(BaseModel):
    enabled: bool = False
    kind: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 1
    supports_pdf: bool = False
    supports_images: bool = False
    supports_json_schema: bool = False
    cost_tier: str = "free"
    requires_confirmation: bool = False


class ProviderFamilyConfig(BaseModel):
    order: list[str] = Field(default_factory=list)
    fallback_on: list[FallbackRule] = Field(default_factory=list)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class ProviderRegistry(BaseModel):
    document_extraction: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    translation_normalization: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    category_inference: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    duplicate_detection: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)

    @classmethod
    def from_path(cls, path: Path) -> "ProviderRegistry":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(payload)

    def validate(self) -> dict[str, dict[str, dict[str, str | bool]]]:
        report: dict[str, dict[str, dict[str, str | bool]]] = {}
        for family_name in (
            "document_extraction",
            "translation_normalization",
            "category_inference",
            "duplicate_detection",
        ):
            family = getattr(self, family_name)
            report[family_name] = {}
            for provider_name, provider in family.providers.items():
                available = True
                reason = "enabled"
                if not provider.enabled:
                    available = False
                    reason = "disabled"
                elif provider.api_key_env and not os.environ.get(provider.api_key_env):
                    available = False
                    reason = "missing_env"
                report[family_name][provider_name] = {
                    "available": available,
                    "reason": reason,
                }
        return report
```

```yaml
# backend/config.example.yaml
document_extraction:
  order: []
  fallback_on: []
  providers: {}

translation_normalization:
  order: []
  fallback_on: []
  providers: {}

category_inference:
  order: []
  fallback_on: []
  providers: {}

duplicate_detection:
  order: []
  fallback_on: []
  providers: {}
```

- [ ] **Step 4: Run the provider-registry test**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_provider_registry.py -q`

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/imports/providers.py backend/tests/imports/test_provider_registry.py backend/config.example.yaml
git commit -m "feat: add provider registry foundation"
```

### Task 7: Fixture Sanitizer and Backend CI

**Files:**
- Create: `scripts/sanitize_fixture.py`
- Create: `backend/tests/imports/test_sanitize_fixture.py`
- Create: `.github/workflows/backend-tests.yml`

- [ ] **Step 1: Write the failing sanitizer test**

```python
# backend/tests/imports/test_sanitize_fixture.py
import importlib.util
from pathlib import Path


def _load_sanitizer_module():
    module_path = Path(__file__).resolve().parents[2] / ".." / "scripts" / "sanitize_fixture.py"
    spec = importlib.util.spec_from_file_location("sanitize_fixture", module_path.resolve())
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sanitize_fixture_masks_iban_and_card_shapes():
    sanitizer = _load_sanitizer_module()
    cleaned = sanitizer.sanitize_fixture_text(
        "Naam;BE68539007547034;4976 1234 5678 9012;1234,56"
    )
    assert "BE68539007547034" not in cleaned
    assert "4976 1234 5678 9012" not in cleaned
    assert "1234,56" not in cleaned
```

- [ ] **Step 2: Run the sanitizer test**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports/test_sanitize_fixture.py -q`

Expected: FAIL because `scripts/sanitize_fixture.py` does not exist

- [ ] **Step 3: Implement the sanitizer helper and CI workflow**

```python
# scripts/sanitize_fixture.py
import re
import sys
from pathlib import Path

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
AMOUNT_RE = re.compile(r"\b\d{1,6},\d{2}\b")


def sanitize_fixture_text(text: str) -> str:
    text = IBAN_RE.sub("BE00SANITIZED00000000", text)
    text = CARD_RE.sub("0000 0000 0000 0000", text)
    text = AMOUNT_RE.sub("99,99", text)
    return text.replace("Naam", "Fixture Name")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: sanitize_fixture.py <input> <output>")
        return 1
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    target.write_text(sanitize_fixture_text(source.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```yaml
# .github/workflows/backend-tests.yml
name: backend-tests

on:
  push:
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install backend dependencies
        run: pip install -r requirements.txt
      - name: Run backend tests
        run: python -m pytest tests -q
```

- [ ] **Step 4: Run the sanitizer test and the full PR 1 backend suite**

Run: `cd /Users/aaat/myfinance/backend && python -m pytest tests/imports -q`

Expected: all import-foundation tests PASS and no live-provider tests are collected

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/backend-tests.yml scripts/sanitize_fixture.py backend/tests/imports/test_sanitize_fixture.py
git commit -m "chore: add fixture sanitizer and backend ci"
```

## Self-Review

### Spec coverage

- runtime config and backend-local data path isolation: Task 1
- contracts, including `describe()` audit shape: Task 2 and Task 6
- state machine and valid transition enforcement: Task 3
- draft tables and DB bootstrap: Task 3
- artifact layout with `meta.json`, `detection.json`, and `evidence/raw.json`: Task 4
- detection skeleton with `charset_hint`: Task 5
- pipeline skeleton: Task 5
- provider registry, example config, and env validation: Task 6
- sanitizer helper before fixtures land: Task 7
- CI without live providers: Task 7

### Placeholder scan

- No `TODO`, `TBD`, or "implement later" markers remain.
- Every task includes exact file paths, concrete code, concrete commands, and an explicit commit.

### Type consistency

- `ImportStrategyKey`, `ImportIssue`, `RawEvidence`, `ExtractionResult`, and `ImportSessionStatus` are defined before later tasks use them.
- `edit_source` is consistently `ai_extracted` / `user_edited`.
- `ProviderDescription.prompt_fingerprint` matches the accepted spec wording.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-11-import-foundation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
