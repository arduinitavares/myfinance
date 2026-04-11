# AI Classification Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI-assisted transaction classification modal that proposes type, category, and recurrence metadata, accepts structured user feedback, safely applies approved results to similar uncategorized rows, and records provenance for every saved classification.

**Architecture:** Keep the current embedding-based `CategorySuggestionService` as the lightweight background learner and add a separate backend-owned classification assistant flow. The backend owns session state, recurrence patterns, trust-order upload behavior, and the shared commit helper; the frontend adds one modal on top of the existing transactions table and never mutates transactions without an explicit save.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, hand-rolled migrations, sentence-transformers, Qdrant, React, TypeScript, Radix Dialog, React Testing Library, Docker Compose.

---

## File Map

### Backend create

- `backend/app/utils/__init__.py` — make `utils` importable.
- `backend/app/utils/text_normalization.py` — shared regex constants plus `normalize_for_matching()`.
- `backend/app/models/classification.py` — `ClassificationSession`, `ClassificationTurn`, `RecurrencePattern`, and status enums.
- `backend/app/schemas/classification.py` — request and response schemas for the classification API.
- `backend/app/services/classifier_providers/__init__.py` — provider package exports.
- `backend/app/services/classifier_providers/base.py` — `ClassificationProposal`, `ProviderDescription`, `ClassifierProvider`.
- `backend/app/services/classifier_providers/stub.py` — deterministic local and CI provider.
- `backend/app/services/classification_commit_service.py` — shared `commit_category_change()` helper.
- `backend/app/services/classification_session_service.py` — create or resume session, propose, retry, accept, preview similar, apply batch.
- `backend/app/routers/classification.py` — `/classification` endpoints.
- `backend/app/migrations/migrate_classification_assistant.py` — add transaction provenance columns and create assistant tables.
- `backend/tests/test_text_normalization.py` — unit coverage for matching normalization.
- `backend/tests/test_classifier_provider.py` — unit coverage for the stub provider and provider registry.
- `backend/tests/test_classification_api.py` — API coverage for session create, propose, feedback, accept, and confirmation rules.
- `backend/tests/test_upload_trust_order.py` — integration coverage for recurrence, similar preview, batch apply, and upload priority.

### Backend modify

- `backend/app/models/transaction.py` — add `classification_source` and `recurrence_pattern_id`.
- `backend/app/models/__init__.py` — export assistant models.
- `backend/app/schemas/transaction.py` — expose provenance fields in API responses and restore payloads.
- `backend/app/database_manager.py` — register the assistant tables in initialization and reset helpers.
- `backend/app/main.py` — include the classification router.
- `backend/app/imports/providers.py` — add `classification_assistant` provider family.
- `backend/app/services/category_suggestion_service.py` — reuse normalization constants and expose cosine similarity scoring.
- `backend/app/routers/transactions.py` — use trust order on upload and shared commit helper for manual edits.
- `backend/config.example.yaml` — add `classification_assistant` stub provider config.
- `backend/app/migrations/run_migrations.py` — run the assistant migration.

### Frontend create

- `frontend/src/types/classification.ts` — assistant proposal, session, feedback, and modal state types.
- `frontend/src/services/classificationService.ts` — axios client for the classification endpoints.
- `frontend/src/hooks/useClassificationSession.ts` — proposal lifecycle and modal state management.
- `frontend/src/components/transactions/ClassificationAssistantModal.tsx` — modal UI.
- `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx` — modal behavior tests.

### Frontend modify

- `frontend/src/components/TransactionList.tsx` — add the `Ask AI` action and host the modal.
- `frontend/src/types/transaction.ts` — add `classification_source` and `recurrence_pattern_id`.

## Verification Commands

- Backend normalization tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_text_normalization.py -q'`
- Backend provider tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py -q'`
- Backend API tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'`
- Backend trust-order tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_upload_trust_order.py -q'`
- Backend full suite:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests -q'`
- Frontend focused modal tests:
  - `cd frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx`
- Frontend full tests:
  - `cd frontend && CI=true npm test -- --runInBand --watch=false`
- Frontend production build:
  - `cd frontend && npm run build`

## Task 1: Shared Text Normalization Foundation

**Files:**
- Create: `backend/app/utils/__init__.py`
- Create: `backend/app/utils/text_normalization.py`
- Modify: `backend/app/services/category_suggestion_service.py`
- Test: `backend/tests/test_text_normalization.py`

- [ ] **Step 1: Write the failing normalization tests**

```python
# backend/tests/test_text_normalization.py
from app.utils.text_normalization import normalize_for_matching


def test_normalize_for_matching_strips_dates_refs_cards_and_iban():
    raw = "SEPA PROXIMUS 15/03/2026 REF. 12345 BE68539007547034 CARD 4976 1234 5678 9012"
    assert normalize_for_matching(raw) == "sepa proximus"


def test_normalize_for_matching_preserves_word_order():
    raw = "LOYER appartement centre ville 31-03-2026 REF ABC987"
    assert normalize_for_matching(raw) == "loyer appartement centre ville"


def test_normalize_for_matching_collapses_whitespace():
    raw = "  EUROPEAN   DIRECT   DEBIT   PROXIMUS   "
    assert normalize_for_matching(raw) == "european direct debit proximus"
```

- [ ] **Step 2: Run the focused backend test to verify it fails**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_text_normalization.py -q'
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.utils'
```

- [ ] **Step 3: Implement the shared normalization module and reuse its pattern constants**

```python
# backend/app/utils/__init__.py
from .text_normalization import (
    CARD_NUMBER_PATTERNS,
    IBAN_BIC_PATTERNS,
    REFERENCE_PATTERNS,
    TRANSACTION_DATE_PATTERNS,
    normalize_for_matching,
)

__all__ = [
    "CARD_NUMBER_PATTERNS",
    "IBAN_BIC_PATTERNS",
    "REFERENCE_PATTERNS",
    "TRANSACTION_DATE_PATTERNS",
    "normalize_for_matching",
]
```

```python
# backend/app/utils/text_normalization.py
import re

TRANSACTION_DATE_PATTERNS = [
    r"\d{2}[-/]\d{2}[-/]\d{2,4}",
    r"\d{2}[-/]\d{2}",
    r"\d{1,2}[:.]\d{2}\s*(?:am|pm)?",
]

CARD_NUMBER_PATTERNS = [
    r"card number \d*x*\s*\d*x*\s*\d*x*\s*\d*",
    r"\b\d{4}\s\d{4}\s\d{4}\s\d{4}\b",
    r"with \w+ (?:debit|credit) card \d{4}\s*\d*x*\s*\d*x*\s*\d*",
]

REFERENCE_PATTERNS = [
    r"creditor ref\.\s*:\s*[\w\s/.-]+",
    r"mandate ref\.\s*:\s*[\w\s/.-]+",
    r"ref\.\s*[: ]\s*[\w\s/.-]+",
    r"reference\s*:\s*[\w\s/.-]+",
]

IBAN_BIC_PATTERNS = [
    r"[A-Z]{2}\d{2}\s*[A-Z0-9\s]{10,30}",
    r"[A-Z]{6}[A-Z0-9]{2,5}",
]


def _strip_patterns(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return text


def normalize_for_matching(description: str) -> str:
    text = description.lower()
    text = _strip_patterns(text, TRANSACTION_DATE_PATTERNS)
    text = _strip_patterns(text, CARD_NUMBER_PATTERNS)
    text = _strip_patterns(text, REFERENCE_PATTERNS)
    text = _strip_patterns(text, IBAN_BIC_PATTERNS)
    text = re.sub(r"\s+", " ", text).strip()
    return text
```

```python
# backend/app/services/category_suggestion_service.py
from ..utils.text_normalization import (
    CARD_NUMBER_PATTERNS,
    IBAN_BIC_PATTERNS,
    REFERENCE_PATTERNS,
    TRANSACTION_DATE_PATTERNS,
)

def _preprocess_description(self, description: str) -> str:
    text = description.lower()

    prefixes = [
        r'payment via \w+\s+',
        r'european direct debit\s+',
        r'instant credit transfer from\s+',
        r'charge\s+',
        r'payment\s+'
    ]
    for prefix in prefixes:
        text = re.sub(prefix, '', text, flags=re.IGNORECASE)

    for pattern in TRANSACTION_DATE_PATTERNS:
        text = re.sub(pattern, '', text)
    for pattern in CARD_NUMBER_PATTERNS:
        text = re.sub(pattern, '', text)
    for pattern in REFERENCE_PATTERNS:
        text = re.sub(pattern, '', text)
    for pattern in IBAN_BIC_PATTERNS:
        text = re.sub(pattern, '', text)

    text = re.sub(r'\d{4,5}\s*[-\s]*[a-z]{2,3}', '', text)
    text = re.sub(r'\d{3,4}\s+\d{4}\s+[a-zA-Z\s]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```

- [ ] **Step 4: Run the focused backend test to verify it passes**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_text_normalization.py -q'
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/__init__.py \
  backend/app/utils/text_normalization.py \
  backend/app/services/category_suggestion_service.py \
  backend/tests/test_text_normalization.py
git commit -m "feat: add shared transaction text normalization"
```

---

## Task 2: Persistence Foundation, Provenance, and Migration

**Files:**
- Create: `backend/app/models/classification.py`
- Create: `backend/app/migrations/migrate_classification_assistant.py`
- Modify: `backend/app/models/transaction.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/transaction.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/migrations/run_migrations.py`
- Test: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Write the failing persistence-level API tests**

```python
# backend/tests/test_classification_api.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create_transaction(description: str = "SEPA PROXIMUS"):
    return client.post(
        "/transactions/restore",
        json={
            "account_number": "BE46",
            "transaction_date": "2026-04-10",
            "amount": -45.99,
            "currency": "EUR",
            "description": description,
            "transaction_type": "Expense",
            "source_bank": "Belfius",
        },
    ).json()


def test_create_classification_session_returns_open_session():
    reset = client.post("/debug/reset-database")
    assert reset.status_code == 200

    tx = _create_transaction()
    response = client.post("/classification/sessions", json={"transaction_id": tx["id"]})

    assert response.status_code == 200
    assert response.json()["status"] == "open"


def test_create_classification_session_reuses_open_session():
    reset = client.post("/debug/reset-database")
    assert reset.status_code == 200

    tx = _create_transaction("Own account transfer")
    first = client.post("/classification/sessions", json={"transaction_id": tx["id"]}).json()
    second = client.post("/classification/sessions", json={"transaction_id": tx["id"]}).json()

    assert second["id"] == first["id"]
```

- [ ] **Step 2: Run the focused backend test to verify it fails**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py::test_create_classification_session_returns_open_session -q'
```

Expected:

```text
F
```

The route does not exist yet, so a 404 response is the correct first failure.

- [ ] **Step 3: Add the new tables, provenance columns, and migration hook**

```python
# backend/app/models/classification.py
import enum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.sql import func

from ..database import Base


class ClassificationSessionStatus(enum.Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ClassificationSession(Base):
    __tablename__ = "classification_sessions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="open")
    provider_name = Column(String(100), nullable=True)
    model_name = Column(String(200), nullable=True)
    final_transaction_type = Column(String(20), nullable=True)
    final_category = Column(String(100), nullable=True)
    final_recurrence_frequency = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "uq_classification_sessions_open",
            "transaction_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
    )


class ClassificationTurn(Base):
    __tablename__ = "classification_turns"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("classification_sessions.id"), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)
    proposal_type = Column(String(20), nullable=False)
    proposal_category = Column(String(100), nullable=False)
    proposal_confidence = Column(String(20), nullable=False)
    proposal_rationale = Column(Text, nullable=False)
    proposal_alternatives_json = Column(Text, nullable=False)
    proposal_follow_up_question = Column(Text, nullable=True)
    proposal_recurrence_json = Column(Text, nullable=False)
    feedback_tag = Column(String(50), nullable=True)
    feedback_note = Column(Text, nullable=True)
    token_count_prompt = Column(Integer, nullable=True)
    token_count_completion = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RecurrencePattern(Base):
    __tablename__ = "recurrence_patterns"

    id = Column(Integer, primary_key=True, index=True)
    source_session_id = Column(Integer, ForeignKey("classification_sessions.id"), nullable=False, index=True)
    seed_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    normalized_description_key = Column(String(500), nullable=False, index=True)
    source_bank = Column(String(50), nullable=True)
    currency = Column(String(3), nullable=False)
    transaction_type = Column(String(20), nullable=False)
    category = Column(String(100), nullable=False)
    frequency = Column(String(20), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

```python
# backend/app/models/transaction.py
from sqlalchemy import Column, Date, Enum, Float, ForeignKey, Integer, String

classification_source = Column(String(50), nullable=True)
recurrence_pattern_id = Column(Integer, ForeignKey("recurrence_patterns.id"), nullable=True)
```

```python
# backend/app/schemas/transaction.py
class TransactionBase(BaseModel):
    account_number: str
    transaction_date: date
    amount: float
    currency: str
    description: str
    counterparty_name: Optional[str] = None
    counterparty_account: Optional[str] = None
    transaction_type: Optional[TransactionType] = None
    expense_category: Optional[ExpenseCategory] = None
    income_category: Optional[IncomeCategory] = None
    classification_source: Optional[str] = None
    recurrence_pattern_id: Optional[int] = None
    source_bank: str
```

```python
# backend/app/models/__init__.py
from .classification import ClassificationSession, ClassificationSessionStatus, ClassificationTurn, RecurrencePattern

__all__ = [
    "ClassificationSession",
    "ClassificationSessionStatus",
    "ClassificationTurn",
    "RecurrencePattern",
]
```

```python
# backend/app/database_manager.py
from .models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern

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
    "classification_sessions",
    "classification_turns",
    "recurrence_patterns",
]

elif reset_type == "classification":
    Base.metadata.drop_all(
        bind=engine,
        tables=[
            ClassificationTurn.__table__,
            ClassificationSession.__table__,
            RecurrencePattern.__table__,
        ],
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            ClassificationSession.__table__,
            ClassificationTurn.__table__,
            RecurrencePattern.__table__,
        ],
    )
```

```python
# backend/app/migrations/migrate_classification_assistant.py
from sqlalchemy import inspect, text

from app.database import Base, engine
from app.models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern


def migrate_classification_assistant():
    with engine.begin() as conn:
        inspector = inspect(conn)
        transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
        if "classification_source" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN classification_source VARCHAR(50)"))
        if "recurrence_pattern_id" not in transaction_columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN recurrence_pattern_id INTEGER"))

    Base.metadata.create_all(
        bind=engine,
        tables=[
            ClassificationSession.__table__,
            ClassificationTurn.__table__,
            RecurrencePattern.__table__,
        ],
    )
```

```python
# backend/app/migrations/run_migrations.py
from app.migrations.migrate_classification_assistant import migrate_classification_assistant
from app.migrations.migrate_expense_type_values import migrate_expense_type_values


def run_migrations():
    migrate_classification_assistant()
    migrate_expense_type_values()
```

- [ ] **Step 4: Run the focused backend test to verify the schema work is in place**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py::test_create_classification_session_returns_open_session -q'
```

Expected:

```text
F
```

The route still does not exist, but the database layer no longer blocks the feature.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/classification.py \
  backend/app/models/transaction.py \
  backend/app/models/__init__.py \
  backend/app/schemas/transaction.py \
  backend/app/database_manager.py \
  backend/app/migrations/migrate_classification_assistant.py \
  backend/app/migrations/run_migrations.py \
  backend/tests/test_classification_api.py
git commit -m "feat: add classification assistant persistence foundation"
```

---

## Task 3: Provider Protocol, Stub Provider, and Config Family

**Files:**
- Create: `backend/app/services/classifier_providers/__init__.py`
- Create: `backend/app/services/classifier_providers/base.py`
- Create: `backend/app/services/classifier_providers/stub.py`
- Modify: `backend/app/imports/providers.py`
- Modify: `backend/config.example.yaml`
- Test: `backend/tests/test_classifier_provider.py`

- [ ] **Step 1: Write the failing provider tests**

```python
# backend/tests/test_classifier_provider.py
from pathlib import Path
from types import SimpleNamespace

from app.imports.providers import ProviderRegistry
from app.models.transaction import TransactionType
from app.services.classifier_providers.stub import StubClassifierProvider


def test_stub_classifier_provider_returns_utilities_for_proximus():
    provider = StubClassifierProvider()
    transaction = SimpleNamespace(
        description="SEPA PROXIMUS",
        transaction_type=TransactionType.EXPENSE,
        amount=-45.99,
    )

    proposal = provider.classify(
        transaction=transaction,
        allowed_types=[item.value for item in TransactionType],
        allowed_categories=["Utilities", "Personal"],
        conversation_history=[],
    )

    assert proposal.category == "Utilities"
    assert proposal.transaction_type == "Expense"
    assert proposal.recurrence_suggestion["frequency"] == "monthly"


def test_provider_registry_accepts_classification_assistant_family(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
classification_assistant:
  order: [stub]
  fallback_on: []
  providers:
    stub:
      enabled: true
      kind: stub
      timeout_seconds: 30
      max_retries: 1
      supports_pdf: false
      supports_images: false
      supports_json_schema: true
      cost_tier: free
      requires_confirmation: false
""".strip(),
        encoding="utf-8",
    )

    registry = ProviderRegistry.from_path(config_path)
    report = registry.validate()

    assert report["classification_assistant"]["__family__"]["selected_provider"] == "stub"
```

- [ ] **Step 2: Run the focused backend test to verify it fails**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py -q'
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.services.classifier_providers'
```

- [ ] **Step 3: Add the provider protocol, stub provider, and config family**

```python
# backend/app/services/classifier_providers/base.py
from dataclasses import dataclass
from typing import Any


@dataclass
class ClassificationProposal:
    transaction_type: str
    category: str
    confidence: float
    rationale: str
    alternative_categories: list[dict[str, Any]]
    follow_up_question: str | None
    recurrence_suggestion: dict[str, Any]


@dataclass
class ProviderDescription:
    provider_name: str
    model_name: str
    schema_version: str
    prompt_fingerprint: str
    cost_tier: str = "free"


class ClassifierProvider:
    def classify(self, transaction, allowed_types, allowed_categories, conversation_history):
        raise NotImplementedError

    def describe(self) -> ProviderDescription:
        raise NotImplementedError
```

```python
# backend/app/services/classifier_providers/__init__.py
from .base import ClassificationProposal, ClassifierProvider, ProviderDescription
from .stub import StubClassifierProvider

__all__ = [
    "ClassificationProposal",
    "ClassifierProvider",
    "ProviderDescription",
    "StubClassifierProvider",
]
```

```python
# backend/app/services/classifier_providers/stub.py
from .base import ClassificationProposal, ClassifierProvider, ProviderDescription


class StubClassifierProvider(ClassifierProvider):
    def classify(self, transaction, allowed_types, allowed_categories, conversation_history):
        description = transaction.description.lower()
        if "proximus" in description:
            return ClassificationProposal(
                transaction_type="Expense",
                category="Utilities",
                confidence=0.91,
                rationale="The merchant name suggests a telecom or household bill.",
                alternative_categories=[
                    {"category": "Personal", "confidence": 0.41, "rationale": "Possible subscription expense"},
                    {"category": "Entertainment", "confidence": 0.17, "rationale": "Only if this is media-related"},
                ],
                follow_up_question=None,
                recurrence_suggestion={"is_recurrent": True, "frequency": "monthly", "reason": "Looks like a recurring biller"},
            )
        return ClassificationProposal(
            transaction_type=transaction.transaction_type.value,
            category=allowed_categories[0],
            confidence=0.5,
            rationale="Fallback stub proposal.",
            alternative_categories=[],
            follow_up_question="Is this your own account movement or an external payment?",
            recurrence_suggestion={"is_recurrent": False, "frequency": "unknown", "reason": "No stable recurring signal"},
        )

    def describe(self) -> ProviderDescription:
        return ProviderDescription(
            provider_name="stub",
            model_name="deterministic-keywords",
            schema_version="v1",
            prompt_fingerprint="stub-v1",
            cost_tier="free",
        )
```

```python
# backend/app/imports/providers.py
class ProviderRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_extraction: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    translation_normalization: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    category_inference: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    duplicate_detection: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)
    classification_assistant: ProviderFamilyConfig = Field(default_factory=ProviderFamilyConfig)

    def validate(self) -> dict[str, dict[str, dict[str, Any]]]:
        report: dict[str, dict[str, dict[str, Any]]] = {}
        for family_name in (
            "document_extraction",
            "translation_normalization",
            "category_inference",
            "duplicate_detection",
            "classification_assistant",
        ):
            family = getattr(self, family_name)
            report[family_name] = {}
            available_in_order: list[str] = []
            skipped_in_order: list[str] = []
            for provider_name, provider in family.providers.items():
                available, reason = self._provider_availability(family_name, provider)
                report[family_name][provider_name] = {
                    "available": available,
                    "reason": reason,
                }
            for provider_name in family.order:
                provider_report = report[family_name][provider_name]
                if provider_report["available"]:
                    available_in_order.append(provider_name)
                else:
                    skipped_in_order.append(provider_name)
```

```yaml
# backend/config.example.yaml
classification_assistant:
  order: [stub]
  fallback_on: []
  providers:
    stub:
      enabled: true
      kind: stub
      timeout_seconds: 30
      max_retries: 1
      supports_pdf: false
      supports_images: false
      supports_json_schema: true
      cost_tier: free
      requires_confirmation: false
```

- [ ] **Step 4: Run the focused backend test to verify it passes**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py -q'
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/classifier_providers/__init__.py \
  backend/app/services/classifier_providers/base.py \
  backend/app/services/classifier_providers/stub.py \
  backend/app/imports/providers.py \
  backend/config.example.yaml \
  backend/tests/test_classifier_provider.py
git commit -m "feat: add classification assistant provider protocol"
```

---

## Task 4: Backend Session API and Shared Commit Helper

**Files:**
- Create: `backend/app/schemas/classification.py`
- Create: `backend/app/services/classification_commit_service.py`
- Create: `backend/app/services/classification_session_service.py`
- Create: `backend/app/routers/classification.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/transactions.py`
- Test: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Expand the failing API tests for propose, feedback, accept, and type confirmation**

```python
# backend/tests/test_classification_api.py
def test_propose_persists_turn_and_returns_structured_proposal():
    reset = client.post("/debug/reset-database")
    assert reset.status_code == 200

    tx = _create_transaction()
    session = client.post("/classification/sessions", json={"transaction_id": tx["id"]}).json()
    response = client.post(f"/classification/sessions/{session['id']}/propose")

    assert response.status_code == 200
    payload = response.json()
    assert payload["proposal"]["category"] == "Utilities"
    assert payload["proposal"]["transaction_type"] == "Expense"
    assert payload["proposal"]["recurrence_suggestion"]["frequency"] == "monthly"


def test_feedback_creates_another_turn():
    reset = client.post("/debug/reset-database")
    assert reset.status_code == 200

    tx = _create_transaction("Own account transfer")
    session = client.post("/classification/sessions", json={"transaction_id": tx["id"]}).json()
    client.post(f"/classification/sessions/{session['id']}/propose")
    response = client.post(
        f"/classification/sessions/{session['id']}/feedback",
        json={"feedback_tag": "wrong_category", "feedback_note": "This is an internal transfer"},
    )

    assert response.status_code == 200
    assert response.json()["proposal"]["follow_up_question"] == "Is this your own account movement or an external payment?"


def test_accept_requires_confirmation_for_type_change():
    reset = client.post("/debug/reset-database")
    assert reset.status_code == 200

    tx = _create_transaction("Own account transfer")
    session = client.post("/classification/sessions", json={"transaction_id": tx["id"]}).json()
    client.post(f"/classification/sessions/{session['id']}/propose")
    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Transfer",
            "category": "Internal Transfer",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": False, "frequency": "unknown"},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Type change requires confirmation"


def test_accept_commits_transaction_and_sets_classification_source():
    reset = client.post("/debug/reset-database")
    assert reset.status_code == 200

    tx = _create_transaction()
    session = client.post("/classification/sessions", json={"transaction_id": tx["id"]}).json()
    client.post(f"/classification/sessions/{session['id']}/propose")
    response = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction"]["expense_category"] == "Utilities"
    assert payload["transaction"]["classification_source"] == "assistant"
    assert payload["session"]["status"] == "accepted"
```

- [ ] **Step 2: Run the focused backend tests to verify they fail**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'
```

Expected:

```text
FFFF
```

- [ ] **Step 3: Implement the schemas, commit helper, session service, and router**

```python
# backend/app/schemas/classification.py
from pydantic import BaseModel


class CreateClassificationSessionRequest(BaseModel):
    transaction_id: int


class SubmitFeedbackRequest(BaseModel):
    feedback_tag: str
    feedback_note: str | None = None


class AcceptClassificationRequest(BaseModel):
    transaction_type: str
    category: str
    classification_source: str
    confirm_type_change: bool = False
    recurrence: dict


class ApplyBatchRequest(BaseModel):
    transaction_ids: list[int]
```

```python
# backend/app/services/classification_commit_service.py
from app.models.transaction import ExpenseCategory, IncomeCategory, Transaction, TransactionType
from app.routers.suggestions import category_suggestion_service
from app.services.statistics_service import StatisticsService


def commit_category_change(
    db,
    transaction: Transaction,
    transaction_type: TransactionType,
    category: str,
    classification_source: str,
    recurrence_pattern_id: int | None = None,
    session_id: int | None = None,
):
    transaction.transaction_type = transaction_type
    if transaction_type == TransactionType.EXPENSE:
        transaction.expense_category = ExpenseCategory(category)
        transaction.income_category = None
    elif transaction_type == TransactionType.INCOME:
        transaction.income_category = IncomeCategory(category)
        transaction.expense_category = None
    else:
        if transaction.amount < 0:
            transaction.expense_category = ExpenseCategory.INTERNAL_TRANSFER
            transaction.income_category = None
        else:
            transaction.income_category = IncomeCategory.INTERNAL_TRANSFER
            transaction.expense_category = None

    transaction.classification_source = classification_source
    transaction.recurrence_pattern_id = recurrence_pattern_id

    db.add(transaction)
    db.flush()
    StatisticsService.update_statistics(db, transaction.transaction_date)
    db.commit()
    db.refresh(transaction)
    if transaction.transaction_type in (TransactionType.EXPENSE, TransactionType.INCOME):
        category_suggestion_service.add_transaction(transaction)
    return transaction
```

```python
# backend/app/services/classification_session_service.py
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.models.classification import ClassificationSession, ClassificationTurn, RecurrencePattern
from app.models.transaction import ExpenseCategory, IncomeCategory, Transaction, TransactionType
from app.routers.suggestions import category_suggestion_service
from app.services.classification_commit_service import commit_category_change
from app.services.classifier_providers.stub import StubClassifierProvider
from app.utils.text_normalization import normalize_for_matching


class ClassificationSessionService:
    SESSION_TIMEOUT = timedelta(hours=24)

    @classmethod
    def _require_transaction(cls, db, transaction_id: int) -> Transaction:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return transaction

    @classmethod
    def _require_open_session(cls, db, session_id: int) -> ClassificationSession:
        session = db.query(ClassificationSession).filter(ClassificationSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Classification session not found")
        if session.status != "open":
            raise HTTPException(status_code=400, detail="Classification session is not open")
        return session

    @classmethod
    def _next_turn_index(cls, db, session_id: int) -> int:
        last_turn = (
            db.query(ClassificationTurn)
            .filter(ClassificationTurn.session_id == session_id)
            .order_by(ClassificationTurn.turn_index.desc())
            .first()
        )
        return 1 if not last_turn else last_turn.turn_index + 1

    @classmethod
    def create_or_resume_session(cls, db, transaction_id: int):
        session = (
            db.query(ClassificationSession)
            .filter(
                ClassificationSession.transaction_id == transaction_id,
                ClassificationSession.status == "open",
            )
            .first()
        )
        if session and session.updated_at and session.updated_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - cls.SESSION_TIMEOUT:
            session.status = "expired"
            db.add(session)
            db.commit()
            session = None
        if session:
            return session

        session = ClassificationSession(transaction_id=transaction_id, status="open")
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    @classmethod
    def propose(cls, db, session_id: int):
        session = cls._require_open_session(db, session_id)
        transaction = cls._require_transaction(db, session.transaction_id)
        provider = StubClassifierProvider()
        allowed_categories = [item.value for item in ExpenseCategory] + [item.value for item in IncomeCategory]
        try:
            proposal = provider.classify(
                transaction=transaction,
                allowed_types=[item.value for item in TransactionType],
                allowed_categories=allowed_categories,
                conversation_history=[],
            )
        except Exception:
            fallback = category_suggestion_service.suggest_category(
                transaction.description,
                transaction.amount,
                transaction.transaction_type,
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Classification provider unavailable",
                    "suggestions": [
                        {"category": category, "confidence": confidence}
                        for category, confidence in fallback
                    ],
                },
            )

        turn = ClassificationTurn(
            session_id=session.id,
            turn_index=cls._next_turn_index(db, session.id),
            proposal_type=proposal.transaction_type,
            proposal_category=proposal.category,
            proposal_confidence=str(proposal.confidence),
            proposal_rationale=proposal.rationale,
            proposal_alternatives_json=json.dumps(proposal.alternative_categories),
            proposal_follow_up_question=proposal.follow_up_question,
            proposal_recurrence_json=json.dumps(proposal.recurrence_suggestion),
        )
        description = provider.describe()
        session.provider_name = description.provider_name
        session.model_name = description.model_name
        db.add_all([session, turn])
        db.commit()
        db.refresh(session)
        return {"session": session, "proposal": proposal}

    @classmethod
    def record_feedback(cls, db, session_id: int, request):
        session = cls._require_open_session(db, session_id)
        last_turn = (
            db.query(ClassificationTurn)
            .filter(ClassificationTurn.session_id == session.id)
            .order_by(ClassificationTurn.turn_index.desc())
            .first()
        )
        if not last_turn:
            raise HTTPException(status_code=400, detail="Create a proposal before sending feedback")
        last_turn.feedback_tag = request.feedback_tag
        last_turn.feedback_note = request.feedback_note
        db.add(last_turn)
        db.commit()
        return cls.propose(db, session_id)

    @classmethod
    def accept(cls, db, session_id: int, request):
        session = cls._require_open_session(db, session_id)
        transaction = cls._require_transaction(db, session.transaction_id)
        new_type = TransactionType(request.transaction_type)
        if new_type != transaction.transaction_type and not request.confirm_type_change:
            raise HTTPException(status_code=400, detail="Type change requires confirmation")

        recurrence_pattern_id = None
        if request.recurrence.get("is_recurrent"):
            pattern = RecurrencePattern(
                source_session_id=session.id,
                seed_transaction_id=transaction.id,
                normalized_description_key=normalize_for_matching(transaction.description),
                source_bank=transaction.source_bank,
                currency=transaction.currency,
                transaction_type=request.transaction_type,
                category=request.category,
                frequency=request.recurrence["frequency"],
                active=True,
            )
            db.add(pattern)
            db.flush()
            recurrence_pattern_id = pattern.id

        committed = commit_category_change(
            db=db,
            transaction=transaction,
            transaction_type=new_type,
            category=request.category,
            classification_source=request.classification_source,
            recurrence_pattern_id=recurrence_pattern_id,
            session_id=session.id,
        )
        session.status = "accepted"
        session.final_transaction_type = request.transaction_type
        session.final_category = request.category
        session.final_recurrence_frequency = request.recurrence["frequency"]
        db.add(session)
        db.commit()
        db.refresh(session)
        return {"transaction": committed, "session": session}
```

```python
# backend/app/routers/classification.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.classification import (
    AcceptClassificationRequest,
    CreateClassificationSessionRequest,
    SubmitFeedbackRequest,
)
from ..services.classification_session_service import ClassificationSessionService

router = APIRouter(prefix="/classification", tags=["classification"])


@router.post("/sessions")
def create_session(request: CreateClassificationSessionRequest, db: Session = Depends(get_db)):
    return ClassificationSessionService.create_or_resume_session(db, request.transaction_id)


@router.post("/sessions/{session_id}/propose")
def propose(session_id: int, db: Session = Depends(get_db)):
    return ClassificationSessionService.propose(db, session_id)


@router.post("/sessions/{session_id}/feedback")
def feedback(session_id: int, request: SubmitFeedbackRequest, db: Session = Depends(get_db)):
    return ClassificationSessionService.record_feedback(db, session_id, request)


@router.post("/sessions/{session_id}/accept")
def accept(session_id: int, request: AcceptClassificationRequest, db: Session = Depends(get_db)):
    return ClassificationSessionService.accept(db, session_id, request)
```

```python
# backend/app/main.py
from .routers import anomalies, classification, financial_health, projections, statistics, suggestions, transactions

app.include_router(classification.router)
```

```python
# backend/app/routers/transactions.py
from ..services.classification_commit_service import commit_category_change

@router.patch("/{transaction_id}/category")
def update_transaction_category(
    transaction_id: int,
    category: str = Query(...),
    transaction_type: TransactionType = Query(...),
    db: Session = Depends(get_db)
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(404, detail="Transaction not found")
    return commit_category_change(
        db=db,
        transaction=transaction,
        transaction_type=transaction_type,
        category=category,
        classification_source="manual",
    )
```

- [ ] **Step 4: Run the focused backend tests to verify they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/classification.py \
  backend/app/services/classification_commit_service.py \
  backend/app/services/classification_session_service.py \
  backend/app/routers/classification.py \
  backend/app/main.py \
  backend/app/routers/transactions.py \
  backend/tests/test_classification_api.py
git commit -m "feat: add classification assistant session API"
```

---

## Task 5: Similar Preview, Batch Apply, and Upload Trust Order

**Files:**
- Modify: `backend/app/services/category_suggestion_service.py`
- Modify: `backend/app/services/classification_session_service.py`
- Modify: `backend/app/routers/classification.py`
- Modify: `backend/app/routers/transactions.py`
- Test: `backend/tests/test_upload_trust_order.py`

- [ ] **Step 1: Write the failing preview, batch, and trust-order integration tests**

```python
# backend/tests/test_upload_trust_order.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create_transaction(description: str, tx_date: str, amount: float = -45.99):
    return client.post(
        "/transactions/restore",
        json={
            "account_number": "BE46",
            "transaction_date": tx_date,
            "amount": amount,
            "currency": "EUR",
            "description": description,
            "transaction_type": "Expense",
            "source_bank": "Belfius",
        },
    ).json()


def _csv_bytes(posting_date: str, description: str) -> bytes:
    return (
        "Datum;Waardedatum;Debet;Krediet;Omschrijving;Saldo\n"
        f"{posting_date};{posting_date};10,00;;{description};375,53\n"
    ).encode("latin-1")


def test_similar_preview_only_returns_uncategorized_rows():
    client.post("/debug/reset-database")

    seed = _create_transaction("SEPA PROXIMUS", "2026-04-10")
    _create_transaction("SEPA PROXIMUS APRIL", "2026-04-11")
    client.post(
        "/transactions/restore",
        json={
            "account_number": "BE46",
            "transaction_date": "2026-04-12",
            "amount": -50.10,
            "currency": "EUR",
            "description": "SEPA PROXIMUS MAY",
            "transaction_type": "Expense",
            "expense_category": "Utilities",
            "source_bank": "Belfius",
        },
    )

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    client.post(f"/classification/sessions/{session['id']}/propose")
    preview = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert preview.status_code == 200
    assert len(preview.json()["matches"]) == 1


def test_apply_batch_skips_rows_that_are_already_categorized():
    client.post("/debug/reset-database")

    seed = _create_transaction("SEPA PROXIMUS", "2026-04-10")
    match_one = _create_transaction("SEPA PROXIMUS APRIL", "2026-04-11")
    match_two = _create_transaction("SEPA PROXIMUS MAY", "2026-04-12")
    client.patch(
        f"/transactions/{match_two['id']}/category",
        params={"category": "Utilities", "transaction_type": "Expense"},
    )

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    client.post(f"/classification/sessions/{session['id']}/propose")
    response = client.post(
        f"/classification/sessions/{session['id']}/apply-batch",
        json={"transaction_ids": [match_one["id"], match_two["id"]]},
    )

    assert response.status_code == 200
    assert response.json()["applied_transaction_ids"] == [match_one["id"]]
    assert response.json()["skipped_transaction_ids"] == [match_two["id"]]


def test_recurrence_pattern_wins_before_upload_suggester():
    client.post("/debug/reset-database")

    first_upload = client.post(
        "/transactions/upload/",
        files={"file": ("50212984548.csv", _csv_bytes("03/01/2026", "PROXIMUS"), "text/csv")},
    )
    assert first_upload.status_code == 200

    tx_id = first_upload.json()[0]["id"]
    session = client.post("/classification/sessions", json={"transaction_id": tx_id}).json()
    client.post(f"/classification/sessions/{session['id']}/propose")
    client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    )

    second_upload = client.post(
        "/transactions/upload/",
        files={"file": ("50212984548.csv", _csv_bytes("03/02/2026", "PROXIMUS"), "text/csv")},
    )
    assert second_upload.status_code == 200
    assert second_upload.json()[0]["expense_category"] == "Utilities"
    assert second_upload.json()[0]["classification_source"] == "recurrence_pattern"
```

- [ ] **Step 2: Run the focused backend tests to verify they fail**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_upload_trust_order.py -q'
```

Expected:

```text
FFF
```

- [ ] **Step 3: Implement similarity scoring, preview and batch endpoints, and upload trust order**

```python
# backend/app/services/category_suggestion_service.py
import numpy as np

def similarity_score(self, source_text: str, candidate_text: str) -> float:
    source_vec = self.model.encode(source_text, normalize_embeddings=True)
    candidate_vec = self.model.encode(candidate_text, normalize_embeddings=True)
    return float(np.dot(source_vec, candidate_vec) / (np.linalg.norm(source_vec) * np.linalg.norm(candidate_vec)))
```

```python
# backend/app/services/classification_session_service.py
@classmethod
def preview_similar(cls, db, session_id: int):
    session = cls._require_open_session(db, session_id)
    seed = cls._require_transaction(db, session.transaction_id)
    seed_key = normalize_for_matching(seed.description)
    candidates = (
        db.query(Transaction)
        .filter(Transaction.id != seed.id)
        .filter(Transaction.expense_category.is_(None))
        .filter(Transaction.income_category.is_(None))
        .filter(Transaction.currency == seed.currency)
        .all()
    )

    matches = []
    for candidate in candidates:
        if candidate.amount * seed.amount <= 0:
            continue
        candidate_key = normalize_for_matching(candidate.description)
        score = category_suggestion_service.similarity_score(seed_key, candidate_key)
        if score >= 0.65:
            matches.append(
                {
                    "transaction_id": candidate.id,
                    "description": candidate.description,
                    "amount": candidate.amount,
                    "score": round(score, 4),
                }
            )
    matches.sort(key=lambda item: item["score"], reverse=True)
    return {"matches": matches[:10]}


@classmethod
def apply_batch(cls, db, session_id: int, transaction_ids: list[int]):
    session = cls._require_open_session(db, session_id)
    last_turn = (
        db.query(ClassificationTurn)
        .filter(ClassificationTurn.session_id == session.id)
        .order_by(ClassificationTurn.turn_index.desc())
        .first()
    )
    if not last_turn:
        raise HTTPException(status_code=400, detail="Create a proposal before applying a batch")

    applied_ids: list[int] = []
    skipped_ids: list[int] = []
    target_type = TransactionType(last_turn.proposal_type)

    for transaction in db.query(Transaction).filter(Transaction.id.in_(transaction_ids)).all():
        if transaction.expense_category or transaction.income_category:
            skipped_ids.append(transaction.id)
            continue
        commit_category_change(
            db=db,
            transaction=transaction,
            transaction_type=target_type,
            category=last_turn.proposal_category,
            classification_source="assistant_batch",
        )
        applied_ids.append(transaction.id)

    return {
        "applied_transaction_ids": applied_ids,
        "skipped_transaction_ids": skipped_ids,
    }
```

```python
# backend/app/routers/classification.py
from ..schemas.classification import ApplyBatchRequest

@router.post("/sessions/{session_id}/similar-preview")
def similar_preview(session_id: int, db: Session = Depends(get_db)):
    return ClassificationSessionService.preview_similar(db, session_id)


@router.post("/sessions/{session_id}/apply-batch")
def apply_batch(session_id: int, request: ApplyBatchRequest, db: Session = Depends(get_db)):
    return ClassificationSessionService.apply_batch(db, session_id, request.transaction_ids)
```

```python
# backend/app/routers/transactions.py
from ..models.classification import RecurrencePattern
from ..utils.text_normalization import normalize_for_matching
from sqlalchemy import or_

pattern = (
    db.query(RecurrencePattern)
    .filter(RecurrencePattern.active == True)
    .filter(RecurrencePattern.normalized_description_key == normalize_for_matching(trans.description))
    .filter(RecurrencePattern.currency == trans.currency)
    .filter(or_(RecurrencePattern.source_bank.is_(None), RecurrencePattern.source_bank == trans.source_bank))
    .first()
)
if pattern:
    db_trans = Transaction(**trans.dict())
    db.add(db_trans)
    db.flush()
    commit_category_change(
        db=db,
        transaction=db_trans,
        transaction_type=TransactionType(pattern.transaction_type),
        category=pattern.category,
        classification_source="recurrence_pattern",
        recurrence_pattern_id=pattern.id,
    )
    db_transactions.append(db_trans)
    continue

suggestions = category_suggestion_service.suggest_category(
    trans.description,
    trans.amount,
    trans.transaction_type,
)
if suggestions and suggestions[0][1] > 0.5:
    best_category, confidence = suggestions[0]
    logger.info(f"Setting category {best_category} with confidence {confidence} for transaction: {trans.description}")
    if trans.transaction_type == TransactionType.EXPENSE:
        trans.expense_category = ExpenseCategory(best_category)
    else:
        trans.income_category = IncomeCategory(best_category)
    trans.classification_source = "upload_suggester"
```

- [ ] **Step 4: Run the focused backend tests to verify they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_upload_trust_order.py -q'
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/category_suggestion_service.py \
  backend/app/services/classification_session_service.py \
  backend/app/routers/classification.py \
  backend/app/routers/transactions.py \
  backend/tests/test_upload_trust_order.py
git commit -m "feat: add classification preview and recurrence trust order"
```

---

## Task 6: Frontend Modal, Retry Loop, and Save & Next

**Files:**
- Create: `frontend/src/types/classification.ts`
- Create: `frontend/src/services/classificationService.ts`
- Create: `frontend/src/hooks/useClassificationSession.ts`
- Create: `frontend/src/components/transactions/ClassificationAssistantModal.tsx`
- Create: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`
- Modify: `frontend/src/components/TransactionList.tsx`
- Modify: `frontend/src/types/transaction.ts`

- [ ] **Step 1: Write the failing frontend modal tests**

```tsx
// frontend/src/components/transactions/ClassificationAssistantModal.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';

import { ClassificationAssistantModal } from './ClassificationAssistantModal';
import { classificationService } from '../../services/classificationService';

jest.mock('../../services/classificationService', () => ({
  classificationService: {
    createSession: jest.fn(),
    propose: jest.fn(),
    feedback: jest.fn(),
    accept: jest.fn(),
    previewSimilar: jest.fn(),
    applyBatch: jest.fn(),
  },
}));

const mockedService = classificationService as jest.Mocked<typeof classificationService>;

beforeEach(() => {
  mockedService.createSession.mockResolvedValue({ id: 10, status: 'open' } as never);
  mockedService.propose.mockResolvedValue({
    proposal: {
      transaction_type: 'Expense',
      category: 'Utilities',
      confidence: 0.91,
      rationale: 'The merchant name suggests a telecom or household bill.',
      alternative_categories: [{ category: 'Personal', confidence: 0.41, rationale: 'Possible subscription expense' }],
      follow_up_question: null,
      recurrence_suggestion: { is_recurrent: true, frequency: 'monthly', reason: 'Looks like a biller' },
    },
  } as never);
  mockedService.previewSimilar.mockResolvedValue({ matches: [] } as never);
});

test('renders proposal rationale, recurrence, and retry controls', async () => {
  render(
    <ClassificationAssistantModal
      open
      transaction={{
        id: 1,
        description: 'SEPA PROXIMUS',
        amount: -45.99,
        currency: 'EUR',
        transaction_type: 'Expense',
      } as any}
      onOpenChange={() => {}}
      onSaved={async () => {}}
      getNextTransaction={() => null}
    />
  );

  expect(await screen.findByText(/utilities/i)).toBeInTheDocument();
  expect(screen.getByText(/telecom or household bill/i)).toBeInTheDocument();
  expect(screen.getByText(/monthly/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
});

test('renders degraded fallback without rationale when provider is unavailable', async () => {
  mockedService.propose.mockRejectedValueOnce({
    response: {
      data: {
        detail: {
          message: 'Classification provider unavailable',
          suggestions: [
            { category: 'Utilities', confidence: 0.77 },
            { category: 'Personal', confidence: 0.32 },
          ],
        },
      },
    },
  });

  render(
    <ClassificationAssistantModal
      open
      transaction={{
        id: 2,
        description: 'SEPA PROXIMUS',
        amount: -45.99,
        currency: 'EUR',
        transaction_type: 'Expense',
      } as any}
      onOpenChange={() => {}}
      onSaved={async () => {}}
      getNextTransaction={() => null}
    />
  );

  expect(await screen.findByText(/fallback suggestions/i)).toBeInTheDocument();
  expect(screen.queryByText(/telecom or household bill/i)).not.toBeInTheDocument();
});

test('save and next closes with a completion state when there is no next row', async () => {
  mockedService.accept.mockResolvedValue({
    transaction: { id: 1, expense_category: 'Utilities', classification_source: 'assistant' },
    session: { id: 10, status: 'accepted' },
  } as never);

  render(
    <ClassificationAssistantModal
      open
      transaction={{
        id: 1,
        description: 'SEPA PROXIMUS',
        amount: -45.99,
        currency: 'EUR',
        transaction_type: 'Expense',
      } as any}
      onOpenChange={() => {}}
      onSaved={async () => {}}
      getNextTransaction={() => null}
    />
  );

  await screen.findByText(/utilities/i);
  fireEvent.click(screen.getByRole('button', { name: /save & next/i }));

  expect(await screen.findByText(/no more uncategorized transactions/i)).toBeInTheDocument();
});

test('requires confirmation before saving a type change', async () => {
  mockedService.propose.mockResolvedValueOnce({
    proposal: {
      transaction_type: 'Transfer',
      category: 'Internal Transfer',
      confidence: 0.88,
      rationale: 'The note looks like a movement between your own accounts.',
      alternative_categories: [],
      follow_up_question: null,
      recurrence_suggestion: { is_recurrent: false, frequency: 'unknown', reason: 'Transfers are not recurring by default' },
    },
  } as never);

  render(
    <ClassificationAssistantModal
      open
      transaction={{
        id: 3,
        description: 'Own account transfer',
        amount: -1000,
        currency: 'EUR',
        transaction_type: 'Expense',
      } as any}
      onOpenChange={() => {}}
      onSaved={async () => {}}
      getNextTransaction={() => null}
    />
  );

  await screen.findByText(/internal transfer/i);
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

  expect(await screen.findByText(/confirm type change/i)).toBeInTheDocument();
});

test('shows apply-to-similar preview before a batch action', async () => {
  mockedService.accept.mockResolvedValue({
    transaction: { id: 1, expense_category: 'Utilities', classification_source: 'assistant' },
    session: { id: 10, status: 'accepted' },
  } as never);
  mockedService.previewSimilar.mockResolvedValueOnce({
    matches: [{ transaction_id: 11, description: 'SEPA PROXIMUS APRIL', amount: -50.1, score: 0.93 }],
  } as never);

  render(
    <ClassificationAssistantModal
      open
      transaction={{
        id: 1,
        description: 'SEPA PROXIMUS',
        amount: -45.99,
        currency: 'EUR',
        transaction_type: 'Expense',
      } as any}
      onOpenChange={() => {}}
      onSaved={async () => {}}
      getNextTransaction={() => null}
    />
  );

  await screen.findByText(/utilities/i);
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

  expect(await screen.findByText(/apply to similar/i)).toBeInTheDocument();
  expect(screen.getByText(/sepa proximus april/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused frontend test to verify it fails**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

```text
Cannot find module './ClassificationAssistantModal'
```

- [ ] **Step 3: Implement the modal, hook, service client, and transactions-table entry point**

```ts
// frontend/src/types/classification.ts
export type ClassificationFeedbackTag =
  | 'wrong_category'
  | 'wrong_type'
  | 'close'
  | 'missing_context'
  | 'explain_reasoning'
  | 'accept';

export type ClassificationModalPhase =
  | 'idle'
  | 'generating_proposal'
  | 'waiting_for_feedback'
  | 'retrying_with_feedback'
  | 'confirm_type_change'
  | 'preview_similar'
  | 'saving'
  | 'complete_no_more_uncategorized'
  | 'provider_unavailable_degraded'
  | 'error';

export interface ClassificationProposal {
  transaction_type: string;
  category: string;
  confidence: number;
  rationale: string;
  alternative_categories: Array<{ category: string; confidence: number; rationale: string }>;
  follow_up_question: string | null;
  recurrence_suggestion: { is_recurrent: boolean; frequency: string; reason: string };
}
```

```ts
// frontend/src/services/classificationService.ts
import axios from 'axios';

import { API_BASE_URL } from '../config';

export const classificationService = {
  createSession: async (transactionId: number) =>
    (await axios.post(`${API_BASE_URL}/classification/sessions`, { transaction_id: transactionId })).data,
  propose: async (sessionId: number) =>
    (await axios.post(`${API_BASE_URL}/classification/sessions/${sessionId}/propose`)).data,
  feedback: async (sessionId: number, payload: { feedback_tag: string; feedback_note: string | null }) =>
    (await axios.post(`${API_BASE_URL}/classification/sessions/${sessionId}/feedback`, payload)).data,
  accept: async (sessionId: number, payload: Record<string, unknown>) =>
    (await axios.post(`${API_BASE_URL}/classification/sessions/${sessionId}/accept`, payload)).data,
  previewSimilar: async (sessionId: number) =>
    (await axios.post(`${API_BASE_URL}/classification/sessions/${sessionId}/similar-preview`)).data,
  applyBatch: async (sessionId: number, transactionIds: number[]) =>
    (await axios.post(`${API_BASE_URL}/classification/sessions/${sessionId}/apply-batch`, { transaction_ids: transactionIds })).data,
};
```

```ts
// frontend/src/hooks/useClassificationSession.ts
import { useEffect, useState } from 'react';

import { classificationService } from '../services/classificationService';
import { ClassificationModalPhase, ClassificationProposal } from '../types/classification';

export const useClassificationSession = (open: boolean, transactionId?: number) => {
  const [phase, setPhase] = useState<ClassificationModalPhase>('idle');
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [proposal, setProposal] = useState<ClassificationProposal | null>(null);
  const [fallbackSuggestions, setFallbackSuggestions] = useState<Array<{ category: string; confidence: number }>>([]);

  useEffect(() => {
    if (!open || !transactionId) return;
    const bootstrap = async () => {
      try {
        setPhase('generating_proposal');
        const session = await classificationService.createSession(transactionId);
        setSessionId(session.id);
        const response = await classificationService.propose(session.id);
        setProposal(response.proposal);
        setPhase('waiting_for_feedback');
      } catch (error: any) {
        const suggestions = error?.response?.data?.detail?.suggestions;
        if (Array.isArray(suggestions)) {
          setFallbackSuggestions(suggestions);
          setPhase('provider_unavailable_degraded');
          return;
        }
        setPhase('error');
      }
    };
    void bootstrap();
  }, [open, transactionId]);

  return { phase, sessionId, proposal, fallbackSuggestions, setPhase, setProposal };
};
```

```tsx
// frontend/src/components/transactions/ClassificationAssistantModal.tsx
import * as Dialog from '@radix-ui/react-dialog';
import { useState } from 'react';

import { classificationService } from '../../services/classificationService';
import { dispatchDataRefresh } from '../../hooks/useDataRefresh';
import { useClassificationSession } from '../../hooks/useClassificationSession';

export const ClassificationAssistantModal = ({ open, transaction, onOpenChange, onSaved, getNextTransaction }: any) => {
  const { phase, sessionId, proposal, fallbackSuggestions, setPhase, setProposal } = useClassificationSession(open, transaction?.id);
  const [feedbackTag, setFeedbackTag] = useState('close');
  const [feedbackNote, setFeedbackNote] = useState('');
  const [similarMatches, setSimilarMatches] = useState<any[]>([]);
  const [pendingAdvanceToNext, setPendingAdvanceToNext] = useState(false);

  const handleRetry = async () => {
    if (!sessionId) return;
    setPhase('retrying_with_feedback');
    const response = await classificationService.feedback(sessionId, {
      feedback_tag: feedbackTag,
      feedback_note: feedbackNote || null,
    });
    setProposal(response.proposal);
    setFeedbackNote('');
    setPhase('waiting_for_feedback');
  };

  const finishSave = async (advanceToNext: boolean, confirmTypeChange: boolean) => {
    if (!sessionId || !proposal) return;
    setPhase('saving');
    const nextTransaction = advanceToNext ? getNextTransaction(transaction.id) : null;
    await classificationService.accept(sessionId, {
      transaction_type: proposal.transaction_type,
      category: proposal.category,
      classification_source: 'assistant',
      confirm_type_change: confirmTypeChange,
      recurrence: proposal.recurrence_suggestion,
    });
    const preview = await classificationService.previewSimilar(sessionId);
    if (preview.matches.length > 0) {
      setSimilarMatches(preview.matches);
      setPendingAdvanceToNext(advanceToNext);
      setPhase('preview_similar');
      return;
    }
    dispatchDataRefresh();
    await onSaved(nextTransaction);
    if (advanceToNext) {
      if (!nextTransaction) {
        setPhase('complete_no_more_uncategorized');
        return;
      }
      return;
    }
    onOpenChange(false);
  };

  const handleSave = async (advanceToNext: boolean) => {
    if (!proposal) return;
    if (proposal.transaction_type !== transaction.transaction_type) {
      setPendingAdvanceToNext(advanceToNext);
      setPhase('confirm_type_change');
      return;
    }
    await finishSave(advanceToNext, false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(720px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 dark:bg-gray-900">
          <Dialog.Title className="text-lg font-semibold">AI Classification Assistant</Dialog.Title>
          {phase === 'generating_proposal' && <p className="mt-4 text-sm">Generating proposal…</p>}
          {phase === 'provider_unavailable_degraded' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm font-medium">Fallback suggestions</p>
              {fallbackSuggestions.map((item) => (
                <div key={item.category} className="rounded border px-3 py-2 text-sm">
                  {item.category} ({Math.round(item.confidence * 100)}%)
                </div>
              ))}
            </div>
          )}
          {phase === 'waiting_for_feedback' && proposal && (
            <div className="mt-4 space-y-4">
              <div className="rounded border p-3">
                <p className="text-sm font-medium">{proposal.category}</p>
                <p className="text-sm">{proposal.rationale}</p>
                <p className="text-xs text-gray-500">
                  Recurrence: {proposal.recurrence_suggestion.is_recurrent ? proposal.recurrence_suggestion.frequency : 'not recurrent'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {['wrong_category', 'wrong_type', 'close', 'missing_context', 'explain_reasoning', 'accept'].map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className={feedbackTag === tag ? 'rounded bg-blue-600 px-2 py-1 text-white' : 'rounded border px-2 py-1'}
                    onClick={() => setFeedbackTag(tag)}
                  >
                    {tag}
                  </button>
                ))}
              </div>
              <textarea
                value={feedbackNote}
                onChange={(event) => setFeedbackNote(event.target.value)}
                className="min-h-[96px] w-full rounded border p-2 text-sm"
                placeholder="Add context for the next try"
              />
              <div className="flex justify-end gap-2">
                <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => void handleRetry()}>
                  Try Again
                </button>
                <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => void handleSave(true)}>
                  Save & Next
                </button>
                <button type="button" className="rounded bg-blue-600 px-3 py-2 text-sm text-white" onClick={() => void handleSave(false)}>
                  Save
                </button>
              </div>
            </div>
          )}
          {phase === 'confirm_type_change' && proposal && (
            <div className="mt-4 space-y-3">
              <p className="text-sm font-medium">Confirm type change</p>
              <p className="text-sm">
                The assistant wants to change this transaction from {transaction.transaction_type} to {proposal.transaction_type}.
              </p>
              <div className="flex justify-end gap-2">
                <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => setPhase('waiting_for_feedback')}>
                  Go Back
                </button>
                <button
                  type="button"
                  className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
                  onClick={() => void finishSave(pendingAdvanceToNext, true)}
                >
                  Confirm and Save
                </button>
              </div>
            </div>
          )}
          {phase === 'preview_similar' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm font-medium">Apply to similar</p>
              {similarMatches.map((match) => (
                <label key={match.transaction_id} className="flex items-center justify-between rounded border px-3 py-2 text-sm">
                  <span>{match.description}</span>
                  <span>{Math.round(match.score * 100)}%</span>
                </label>
              ))}
              <div className="flex justify-end gap-2">
                <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => onOpenChange(false)}>
                  Skip
                </button>
                <button
                  type="button"
                  className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
                  onClick={async () => {
                    await classificationService.applyBatch(
                      sessionId!,
                      similarMatches.map((match) => match.transaction_id)
                    );
                    dispatchDataRefresh();
                    await onSaved(pendingAdvanceToNext ? getNextTransaction(transaction.id) : null);
                    onOpenChange(false);
                  }}
                >
                  Apply All
                </button>
              </div>
            </div>
          )}
          {phase === 'complete_no_more_uncategorized' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm">No more uncategorized transactions in this view.</p>
              <button type="button" className="rounded bg-blue-600 px-3 py-2 text-sm text-white" onClick={() => onOpenChange(false)}>
                Close
              </button>
            </div>
          )}
          {phase === 'error' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm text-red-600">Something went wrong while talking to the assistant.</p>
              <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => onOpenChange(false)}>
                Cancel
              </button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
```

```tsx
// frontend/src/components/TransactionList.tsx
import { SparklesIcon } from '@heroicons/react/24/outline';

import { ClassificationAssistantModal } from './transactions/ClassificationAssistantModal';

const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);

const getNextTransaction = (currentId: number) => {
  const uncategorized = transactions.filter((item) => !item.expense_category && !item.income_category);
  const currentIndex = uncategorized.findIndex((item) => item.id === currentId);
  return currentIndex === -1 ? null : uncategorized[currentIndex + 1] ?? null;
};

{!transaction.expense_category && !transaction.income_category && (
  <button
    onClick={() => setSelectedTransaction(transaction)}
    className="mr-2 rounded border border-blue-500 px-2 py-1 text-xs text-blue-600"
  >
    <SparklesIcon className="mr-1 inline h-3 w-3" />
    Ask AI
  </button>
)}

<ClassificationAssistantModal
  open={selectedTransaction !== null}
  transaction={selectedTransaction}
  onOpenChange={(nextOpen: boolean) => {
    if (!nextOpen) setSelectedTransaction(null);
  }}
  onSaved={async (nextTransaction: Transaction | null) => {
    setSelectedTransaction(nextTransaction);
  }}
  getNextTransaction={getNextTransaction}
/>
```

```ts
// frontend/src/types/transaction.ts
export interface Transaction {
  id: number;
  account_number: string;
  transaction_date: string;
  amount: number;
  currency: string;
  description: string;
  counterparty_name?: string;
  counterparty_account?: string;
  transaction_type: TransactionType;
  expense_category?: ExpenseCategory;
  income_category?: IncomeCategory;
  classification_source?: 'manual' | 'assistant' | 'assistant_batch' | 'upload_suggester' | 'recurrence_pattern' | null;
  recurrence_pattern_id?: number | null;
  source_bank: string;
}
```

- [ ] **Step 4: Run the focused frontend test to verify it passes**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

```text
PASS src/components/transactions/ClassificationAssistantModal.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/classification.ts \
  frontend/src/services/classificationService.ts \
  frontend/src/hooks/useClassificationSession.ts \
  frontend/src/components/transactions/ClassificationAssistantModal.tsx \
  frontend/src/components/transactions/ClassificationAssistantModal.test.tsx \
  frontend/src/components/TransactionList.tsx \
  frontend/src/types/transaction.ts
git commit -m "feat: add AI classification assistant modal"
```

---

## Task 7: Full Verification and Manual Flow Check

**Files:**
- Verify: `backend/tests/test_text_normalization.py`
- Verify: `backend/tests/test_classifier_provider.py`
- Verify: `backend/tests/test_classification_api.py`
- Verify: `backend/tests/test_upload_trust_order.py`
- Verify: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`
- Verify: `frontend` build output

- [ ] **Step 1: Run the focused backend assistant suite**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_text_normalization.py tests/test_classifier_provider.py tests/test_classification_api.py tests/test_upload_trust_order.py -q'
```

Expected:

```text
pytest exits with code 0 and the summary line ends with only `passed`
```

- [ ] **Step 2: Run the full backend suite**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests -q'
```

Expected:

```text
pytest exits with code 0 and the summary contains no `FAILED` or `ERROR` lines
```

- [ ] **Step 3: Run the frontend suite and production build**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand --watch=false
cd frontend && npm run build
```

Expected:

```text
the test command exits with code 0 and the build finishes with `Compiled successfully` or `Compiled with warnings`
```

- [ ] **Step 4: Manually verify the live flow**

Run:

```bash
docker compose up -d --build frontend backend
open http://localhost:8080
```

Manual checklist:

- open `Transactions`
- locate an uncategorized row
- launch `Ask AI`
- retry once with a structured feedback tag and a short note
- save the assistant suggestion
- confirm that the row refreshes with the saved category
- run `Save & Next` on another uncategorized row
- verify the completion state appears when there is no next row
- preview `Apply to similar`
- verify only uncategorized rows are changed by the batch action
- upload a matching CSV row and confirm recurrence trust order wins before the embedding suggester

- [ ] **Step 5: Commit**

```bash
git add backend frontend
git commit -m "feat: complete AI classification assistant flow"
```

---

## Self-Review Checklist

- Spec coverage:
  - modal entry point covered by Task 6
  - backend-owned sessions, expiry, and one-open-session rule covered by Tasks 2 and 4
  - provider-agnostic stub-backed assistant covered by Task 3
  - provenance and migration covered by Task 2
  - structured retry feedback, accept, and confirmation rules covered by Task 4
  - recurrence metadata, similar preview, batch apply, and upload trust order covered by Task 5
  - degraded fallback and explicit error states covered by Task 6
- Placeholder scan:
  - no `TODO`, `TBD`, `implement later`, ellipsis placeholders, or “similar to previous task” shortcuts remain
- Type consistency:
  - `classification_source` values match the accepted spec
  - recurrence frequencies include `quarterly`
  - `Transfer` remains an allowed assistant type and still requires explicit confirmation on type change

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-11-ai-classification-assistant.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
