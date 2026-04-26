# Python 3.13.12 Migration Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align local, CI, Docker, and uv execution on Python 3.13.12 and restore a green backend test suite.

**Architecture:** Keep the runtime change narrow by updating version declarations first, then fix only the behavior and test-isolation regressions exposed by the existing full backend suite. Preserve the existing classification-provider degraded fallback behavior and make tests deterministic around the global in-memory category suggestion index.

**Tech Stack:** Python 3.13.12, uv, FastAPI, pytest, Qdrant in-memory collections, Pydantic v2.

---

## File Structure

- Modify: `/Users/aaat/myfinance/.python-version`
  - Pin local version managers to `3.13.12`.
- Modify: `/Users/aaat/myfinance/pyproject.toml`
  - Require `>=3.13.12,<3.14` while leaving tool config on the Python 3.13 minor line.
- Modify: `/Users/aaat/myfinance/backend/Dockerfile`
  - Use `python:3.13.12-slim`.
- Modify: `/Users/aaat/myfinance/backend/app/imports/nexo_csv.py`
  - Emit enum proposal values for deterministic extracted Nexo classifications.
- Modify: `/Users/aaat/myfinance/backend/tests/test_classification_api.py`
  - Clear category suggestion vector collections when the test database is reset.
- Modify: `/Users/aaat/myfinance/backend/tests/test_transfer_analytics.py`
  - Update the `model.encode` monkeypatch to accept `show_progress_bar=False`.

## Task 1: Align Python Version Declarations

- [ ] **Step 1: Update `.python-version`**

Set `/Users/aaat/myfinance/.python-version` to:

```text
3.13.12
```

- [ ] **Step 2: Update `pyproject.toml`**

Change:

```toml
requires-python = ">=3.13.7,<3.14"
```

to:

```toml
requires-python = ">=3.13.12,<3.14"
```

- [ ] **Step 3: Update `backend/Dockerfile`**

Change:

```dockerfile
FROM python:3.13.7-slim
```

to:

```dockerfile
FROM python:3.13.12-slim
```

- [ ] **Step 4: Re-sync uv to Python 3.13.12**

Run:

```bash
cd /Users/aaat/myfinance
uv sync --python 3.13.12
uv run python --version
```

Expected: `Python 3.13.12`.

## Task 2: Preserve Deterministic Nexo Enum Proposals

- [ ] **Step 1: Run the focused failing test**

Run:

```bash
cd /Users/aaat/myfinance
PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/imports/test_nexo_csv.py::test_nexo_csv_extractor_emits_expected_transactions_and_evidence -q
```

Expected before fix: failure because `purchase.proposed_transaction_type` is a `str`, not a `TransactionType`.

- [ ] **Step 2: Update Nexo deterministic proposal assignments**

In `/Users/aaat/myfinance/backend/app/imports/nexo_csv.py`, import:

```python
from ..models.transaction import ExpenseCategory, TransactionType, TransferCategory
```

Use:

```python
TransactionType.EXPENSE
ExpenseCategory.FINANCIAL_FEES
TransactionType.TRANSFER
TransferCategory.INTERNAL_TRANSFER
```

instead of string literals for deterministic proposal fields.

- [ ] **Step 3: Re-run the focused test**

Run the same focused pytest command. Expected: pass.

## Task 3: Make Classification API Tests Isolate Category Suggestions

- [ ] **Step 1: Run the focused failing tests**

Run:

```bash
cd /Users/aaat/myfinance
PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/test_classification_api.py::test_propose_returns_503_when_runtime_provider_config_is_missing backend/tests/test_classification_api.py::test_propose_returns_degraded_suggestions_when_remote_provider_fails -q
```

Expected before fix: failures because the global in-memory category suggestion index contains prior Proximus vectors.

- [ ] **Step 2: Add vector collection reset helper to `test_classification_api.py`**

Import:

```python
from qdrant_client.http import models
from app.routers.suggestions import category_suggestion_service
```

Add:

```python
def _clear_vector_collections():
    category_suggestion_service.client.recreate_collection(
        collection_name="expense_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )
    category_suggestion_service.client.recreate_collection(
        collection_name="income_embeddings",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )
```

Call `_clear_vector_collections()` inside `_reset_database()` after the debug reset succeeds.

- [ ] **Step 3: Re-run the focused tests**

Run the same focused pytest command. Expected: both pass.

## Task 4: Update Transfer Analytics Encode Mock

- [ ] **Step 1: Run the focused failing test**

Run:

```bash
cd /Users/aaat/myfinance
PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/test_transfer_analytics.py::test_category_suggestion_service_skips_transfer_transactions_for_training_and_add -q
```

Expected before fix: `TypeError` because the monkeypatched `encode` lambda does not accept `show_progress_bar`.

- [ ] **Step 2: Update the monkeypatch**

Change:

```python
lambda text: np.array([0.1, 0.2, 0.3], dtype=float)
```

to:

```python
lambda text, show_progress_bar=False: np.array([0.1, 0.2, 0.3], dtype=float)
```

- [ ] **Step 3: Re-run the focused test**

Run the same focused pytest command. Expected: pass.

## Task 5: Verify Migration

- [ ] **Step 1: Check version alignment**

Run:

```bash
cd /Users/aaat/myfinance
python --version
uv run python --version
```

Expected: both report `Python 3.13.12`.

- [ ] **Step 2: Run the full backend suite**

Run:

```bash
cd /Users/aaat/myfinance
PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests -q
```

Expected: all backend tests pass.

- [ ] **Step 3: Check patch hygiene**

Run:

```bash
cd /Users/aaat/myfinance
git diff --check
git status --short
```

Expected: no whitespace errors; status shows only intentional migration/stabilization files and pre-existing WIP.
