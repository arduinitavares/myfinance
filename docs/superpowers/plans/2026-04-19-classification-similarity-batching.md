# Classification Similarity Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated per-candidate similarity embedding in the classification preview/apply-batch flow with one batched scoring call, while silencing sentence-transformer progress bars across the category suggestion service.

**Architecture:** Keep `CategorySuggestionService` responsible for preprocessing, embedding, and cosine math by adding a narrow `similarity_scores(source, candidates)` method plus a small private cosine helper. Keep `ClassificationSessionService` responsible for candidate eligibility by switching `_similar_candidates(...)` from an interleaved filter-and-score loop to a two-pass filter-then-score flow, and migrate the preview/apply-batch tests to patch the new seam.

**Tech Stack:** FastAPI, SQLAlchemy, numpy, sentence-transformers, pytest, monkeypatch, Docker Compose

---

## File Structure

### Backend Code

- Modify: `/Users/aaat/myfinance/backend/app/services/category_suggestion_service.py`
  - Add a private cosine helper and a new `similarity_scores(...)` one-to-many batching method.
  - Pass `show_progress_bar=False` to every `self.model.encode(...)` call in the file.
- Modify: `/Users/aaat/myfinance/backend/app/services/classification_session_service.py`
  - Change `_similar_candidates(...)` to collect eligible survivors first, then batch-score them once.

### Tests

- Create: `/Users/aaat/myfinance/backend/tests/services/test_category_suggestion_service.py`
  - Deterministic unit coverage for `similarity_scores(...)` using a fake model.
- Modify: `/Users/aaat/myfinance/backend/tests/test_classification_api.py`
  - Move preview/apply-batch monkeypatching from `similarity_score` to `similarity_scores`.
  - Add one guard that fails if the old single-pair seam is still used.
- Modify: `/Users/aaat/myfinance/backend/tests/test_upload_trust_order.py`
  - Move the existing preview/apply-batch monkeypatching to `similarity_scores`.

### Verification-Only Files

- Read-only verification: `/Users/aaat/myfinance/backend/tests/test_text_normalization.py`
- Read-only verification: `/Users/aaat/myfinance/backend/tests/test_manual_edit_updates_index.py`

### Explicitly Out Of Scope For This Plan

- `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- `/Users/aaat/myfinance/backend/app/imports/enrichment.py`
- Qdrant bulk write refactors
- frontend code
- threshold or heuristic changes in similarity matching

### Task 1: Add The Batched Similarity Helper And Silence Transformer Progress Bars

**Files:**
- Create: `/Users/aaat/myfinance/backend/tests/services/test_category_suggestion_service.py`
- Modify: `/Users/aaat/myfinance/backend/app/services/category_suggestion_service.py`

- [ ] **Step 1: Write the failing unit tests for `similarity_scores(...)`**

```python
from types import SimpleNamespace

import numpy as np

from app.services.category_suggestion_service import CategorySuggestionService


def test_similarity_scores_returns_empty_list_for_no_candidates():
    service = CategorySuggestionService.__new__(CategorySuggestionService)

    assert service.similarity_scores("seed merchant", []) == []


def test_similarity_scores_batches_candidates_in_input_order():
    service = CategorySuggestionService.__new__(CategorySuggestionService)
    service._preprocess_description = lambda text: text

    encode_calls: list[tuple[list[str], bool]] = []
    vectors = {
        "seed merchant": np.array([1.0, 0.0]),
        "same merchant": np.array([1.0, 0.0]),
        "other merchant": np.array([0.0, 1.0]),
    }

    def fake_encode(texts, show_progress_bar=False):
        encode_calls.append((list(texts), show_progress_bar))
        return np.array([vectors[text] for text in texts])

    service.model = SimpleNamespace(encode=fake_encode)

    scores = service.similarity_scores(
        "seed merchant",
        ["same merchant", "other merchant"],
    )

    assert encode_calls == [
        (["seed merchant", "same merchant", "other merchant"], False)
    ]
    assert scores == [1.0, 0.0]
```

- [ ] **Step 2: Run the unit tests to verify they fail before implementation**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/services/test_category_suggestion_service.py -q
```

Expected: FAIL because `CategorySuggestionService` does not yet define `similarity_scores(...)`.

- [ ] **Step 3: Implement the minimal batching helper and the `show_progress_bar=False` sweep**

```python
def _cosine_similarity(self, source_embedding: np.ndarray, candidate_embedding: np.ndarray) -> float:
    source_norm = float(np.linalg.norm(source_embedding))
    candidate_norm = float(np.linalg.norm(candidate_embedding))
    if source_norm == 0.0 or candidate_norm == 0.0:
        return 0.0

    score = float(np.dot(source_embedding, candidate_embedding) / (source_norm * candidate_norm))
    return 0.0 if np.isnan(score) else score


def similarity_score(self, source_description: str, candidate_description: str) -> float:
    source_text = self._preprocess_description(source_description)
    candidate_text = self._preprocess_description(candidate_description)
    if not source_text or not candidate_text:
        return 0.0

    source_embedding = self.model.encode(source_text, show_progress_bar=False)
    candidate_embedding = self.model.encode(candidate_text, show_progress_bar=False)
    return self._cosine_similarity(source_embedding, candidate_embedding)


def similarity_scores(
    self,
    source_description: str,
    candidate_descriptions: list[str],
) -> list[float]:
    if not candidate_descriptions:
        return []

    source_text = self._preprocess_description(source_description)
    if not source_text:
        return [0.0] * len(candidate_descriptions)

    candidate_texts = [self._preprocess_description(description) for description in candidate_descriptions]
    embeddings = self.model.encode(
        [source_text] + candidate_texts,
        show_progress_bar=False,
    )

    source_embedding = embeddings[0]
    scores: list[float] = []
    for candidate_text, candidate_embedding in zip(candidate_texts, embeddings[1:]):
        if not candidate_text:
            scores.append(0.0)
            continue
        scores.append(self._cosine_similarity(source_embedding, candidate_embedding))
    return scores
```

Also update the remaining encode call sites in the same file:

```python
embedding = self.model.encode(text, show_progress_bar=False)
```

Apply that change in:

- `train_on_existing_transactions(...)`
- `suggest_category(...)`
- `add_transaction(...)`

- [ ] **Step 4: Re-run the new unit tests and make sure they pass**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/services/test_category_suggestion_service.py -q
```

Expected: PASS for both the empty-list case and the ordered batched-score case.

- [ ] **Step 5: Commit the service helper and unit test**

```bash
git -C /Users/aaat/myfinance add /Users/aaat/myfinance/backend/app/services/category_suggestion_service.py /Users/aaat/myfinance/backend/tests/services/test_category_suggestion_service.py
git -C /Users/aaat/myfinance commit -m "feat: batch category similarity scoring"
```

### Task 2: Switch Preview And Apply-Batch To The New Batched Scoring Seam

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/services/classification_session_service.py`
- Modify: `/Users/aaat/myfinance/backend/tests/test_classification_api.py`
- Modify: `/Users/aaat/myfinance/backend/tests/test_upload_trust_order.py`

- [ ] **Step 1: Update one preview test to patch `similarity_scores(...)` and fail if the old seam is still used**

```python
def fake_similarity_scores(source_text: str, candidate_texts: list[str]) -> list[float]:
    assert source_text == seed["description"].lower()
    return [scores.get(candidate_text, 0.0) for candidate_text in candidate_texts]


def fail_similarity_score(*_args, **_kwargs):
    raise AssertionError("single-pair similarity_score should not be used")


monkeypatch.setattr(
    classification_session_service.category_suggestion_service,
    "similarity_scores",
    fake_similarity_scores,
)
monkeypatch.setattr(
    classification_session_service.category_suggestion_service,
    "similarity_score",
    fail_similarity_score,
)
```

Apply that shape to `test_preview_similar_excludes_transfer_like_candidates_for_bill_seed`.

- [ ] **Step 2: Run the targeted preview test to verify it fails before the session-service change**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest backend/tests/test_classification_api.py::test_preview_similar_excludes_transfer_like_candidates_for_bill_seed -q
```

Expected: FAIL with `AssertionError: single-pair similarity_score should not be used` because `_similar_candidates(...)` still calls the old seam.

- [ ] **Step 3: Implement the two-pass survivor-and-score flow in `_similar_candidates(...)`**

```python
surviving: list[Transaction] = []
for transaction in query.all():
    if not _compatible_candidate_family(seed_transaction, transaction):
        continue
    if not shares_source_bank(seed_transaction, transaction):
        continue
    if has_conflicting_family(seed_transaction, transaction):
        continue
    surviving.append(transaction)

if not surviving:
    return []

scores = category_suggestion_service.similarity_scores(
    seed_transaction.description.lower(),
    [transaction.description.lower() for transaction in surviving],
)

candidates = [
    (transaction, score)
    for transaction, score in zip(surviving, scores)
    if score >= SIMILARITY_THRESHOLD
]
candidates.sort(key=lambda item: (-item[1], item[0].id))
return candidates[:SIMILARITY_PREVIEW_LIMIT]
```

- [ ] **Step 4: Migrate the remaining preview/apply-batch monkeypatch sites to the list-returning seam**

Use this fake in the remaining four sites:

```python
def fake_similarity_scores(source_text: str, candidate_texts: list[str]) -> list[float]:
    return [scores.get(candidate_text, 0.0) for candidate_text in candidate_texts]


monkeypatch.setattr(
    category_suggestion_service,
    "similarity_scores",
    fake_similarity_scores,
)
```

Apply that migration to:

- `backend/tests/test_classification_api.py::test_preview_similar_skips_already_transfer_classified_candidates`
- `backend/tests/test_classification_api.py::test_apply_batch_skips_already_transfer_classified_candidates`
- `backend/tests/test_upload_trust_order.py::test_similar_preview_only_returns_uncategorized_rows`
- `backend/tests/test_upload_trust_order.py::test_apply_batch_skips_uncategorized_rows_that_are_not_preview_matches`

- [ ] **Step 5: Run the targeted preview and batch-apply tests to verify they pass on the new seam**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/test_classification_api.py::test_preview_similar_excludes_transfer_like_candidates_for_bill_seed \
  backend/tests/test_classification_api.py::test_preview_similar_skips_already_transfer_classified_candidates \
  backend/tests/test_classification_api.py::test_apply_batch_skips_already_transfer_classified_candidates \
  backend/tests/test_upload_trust_order.py::test_similar_preview_only_returns_uncategorized_rows \
  backend/tests/test_upload_trust_order.py::test_apply_batch_skips_uncategorized_rows_that_are_not_preview_matches \
  -q
```

Expected: PASS, with the preview and batch-apply behavior unchanged and no test still depending on `similarity_score(...)`.

- [ ] **Step 6: Commit the session-service change and the test seam migration**

```bash
git -C /Users/aaat/myfinance add /Users/aaat/myfinance/backend/app/services/classification_session_service.py /Users/aaat/myfinance/backend/tests/test_classification_api.py /Users/aaat/myfinance/backend/tests/test_upload_trust_order.py
git -C /Users/aaat/myfinance commit -m "refactor: batch preview similarity scoring"
```

### Task 3: Run Focused Regression And A Log-Level Smoke Check

**Files:**
- Test: `/Users/aaat/myfinance/backend/tests/services/test_category_suggestion_service.py`
- Test: `/Users/aaat/myfinance/backend/tests/test_text_normalization.py`
- Test: `/Users/aaat/myfinance/backend/tests/test_classification_api.py`
- Test: `/Users/aaat/myfinance/backend/tests/test_upload_trust_order.py`
- Test: `/Users/aaat/myfinance/backend/tests/test_manual_edit_updates_index.py`

- [ ] **Step 1: Run the focused regression suite for the touched service and the affected flows**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/services/test_category_suggestion_service.py \
  backend/tests/test_text_normalization.py::test_preprocess_description_keeps_merchant_prepend \
  backend/tests/test_classification_api.py::test_preview_similar_excludes_transfer_like_candidates_for_bill_seed \
  backend/tests/test_classification_api.py::test_preview_similar_skips_already_transfer_classified_candidates \
  backend/tests/test_classification_api.py::test_apply_batch_skips_already_transfer_classified_candidates \
  backend/tests/test_upload_trust_order.py::test_similar_preview_only_returns_uncategorized_rows \
  backend/tests/test_upload_trust_order.py::test_apply_batch_skips_uncategorized_rows_that_are_not_preview_matches \
  backend/tests/test_manual_edit_updates_index.py::test_manual_category_edit_updates_suggestion_index \
  -q
```

Expected: PASS for the new batching contract, preview/apply-batch flows, preprocess behavior, and post-edit index update.

- [ ] **Step 2: Run a backend smoke script and confirm no `Batches:` lines appear in Docker logs for accept + similar-preview**

Run:

```bash
cd /Users/aaat/myfinance
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
python - <<'PY'
import json
import urllib.request

BASE = "http://localhost:8000"


def post(path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else None


post("/debug/reset-database")
seed = post(
    "/transactions/restore",
    {
        "account_number": "BE1234567890",
        "transaction_date": "2026-04-19",
        "amount": -97.79,
        "currency": "BRL",
        "description": "restaurante fernandes restaurante fernandes",
        "counterparty_name": "Restaurante Fernandes",
        "counterparty_account": "BR0000000001",
        "transaction_type": "Expense",
        "source_bank": "Wise",
    },
)
post(
    "/transactions/restore",
    {
        "account_number": "BE1234567890",
        "transaction_date": "2026-04-18",
        "amount": -96.50,
        "currency": "BRL",
        "description": "restaurante fernandes armacao dos b",
        "counterparty_name": "Restaurante Fernandes",
        "counterparty_account": "BR0000000002",
        "transaction_type": "Expense",
        "source_bank": "Wise",
    },
)
session = post("/classification/sessions", {"transaction_id": seed["id"]})
post(
    f"/classification/sessions/{session['id']}/accept",
    {
        "transaction_type": "Expense",
        "category": "Eating Out",
        "classification_source": "assistant",
        "confirm_type_change": False,
        "recurrence": {"is_recurrent": False},
    },
)
post(f"/classification/sessions/{session['id']}/similar-preview")
PY
docker compose logs backend --since "$START_TIME" | rg "Batches:"
```

Expected: `rg` prints nothing. The accept request still succeeds, the preview request still succeeds, and the backend log no longer contains sentence-transformer progress bars for either call path.

- [ ] **Step 3: Do not create a new commit in this task unless the regression run forces a real code change**

Success gate:

- all targeted tests pass
- the Docker log check shows no `Batches:` output after the smoke run
