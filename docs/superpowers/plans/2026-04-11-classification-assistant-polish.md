# Classification Assistant Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the classification assistant rough edges so transactions can always be reviewed and deleted safely, the modal makes the chosen category obvious, and batch apply becomes conservative enough for daily use.

**Architecture:** Keep the existing assistant flow intact and tighten the seams around it. Backend work focuses on deletion cleanup and stricter similar-match filtering; frontend work keeps the transaction table layout stable, makes the modal selection state explicit, and removes the dead-end completion branch from `Save & Next`.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, React, TypeScript, Radix Dialog, React Testing Library, pytest, Docker Compose.

---

## File Map

### Backend modify

- `backend/app/models/transaction.py` — add ORM cascade rules for classification sessions and seeded recurrence patterns.
- `backend/app/routers/transactions.py` — clean recurrence references and assistant-side rows before deleting a transaction.
- `backend/app/services/classification_session_service.py` — tighten similar-preview thresholds and add conflicting-family filters.
- `backend/tests/test_classification_api.py` — regression tests for delete behavior and similar-preview conservatism.

### Frontend modify

- `frontend/src/components/TransactionList.tsx` — keep the action cell stable and show `Ask AI` for every row.
- `frontend/src/components/transactions/ClassificationAssistantModal.tsx` — add selected type/category controls, clearer confidence wording, stable recurrence controls, and close-on-last `Save & Next`.
- `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx` — modal regressions for clarity and flow.
- `frontend/src/components/TransactionList.test.tsx` — table/action layout behavior.

## Verification Commands

- Backend focused tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'`
- Frontend modal and table tests:
  - `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx src/components/TransactionList.test.tsx`
- End-to-end polish slice:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'`
  - `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx src/components/TransactionList.test.tsx`

## Task 1: Backend Delete Cleanup

**Files:**
- Modify: `backend/app/models/transaction.py`
- Modify: `backend/app/routers/transactions.py`
- Test: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Write the failing delete regression**

```python
def test_delete_transaction_removes_classification_rows_and_cleans_linked_recurrence_references():
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    follower = _restore_transaction(description="PROXIMUS telecom invoice", amount=-49.99)

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    accepted = client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": True, "frequency": "monthly"},
        },
    ).json()

    db = SessionLocal()
    try:
        follower_row = db.query(Transaction).filter(Transaction.id == follower["id"]).first()
        follower_row.recurrence_pattern_id = accepted["recurrence_pattern_id"]
        db.commit()
    finally:
        db.close()

    response = client.delete(f"/transactions/{seed['id']}")

    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(Transaction).filter(Transaction.id == seed["id"]).first() is None
        assert db.query(ClassificationSession).filter(ClassificationSession.transaction_id == seed["id"]).count() == 0
        assert db.query(RecurrencePattern).filter(RecurrencePattern.seed_transaction_id == seed["id"]).count() == 0
        refreshed_follower = db.query(Transaction).filter(Transaction.id == follower["id"]).first()
        assert refreshed_follower is not None
        assert refreshed_follower.recurrence_pattern_id is None
    finally:
        db.close()
```

- [ ] **Step 2: Run the focused backend test and confirm it fails with the integrity error**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q -k delete_transaction'
```

- [ ] **Step 3: Add ORM cascade plus explicit recurrence cleanup**

```python
# backend/app/models/transaction.py
classification_sessions = relationship(
    "ClassificationSession",
    back_populates="transaction",
    cascade="all, delete-orphan",
)
seeded_recurrence_patterns = relationship(
    "RecurrencePattern",
    foreign_keys="RecurrencePattern.seed_transaction_id",
    back_populates="seed_transaction",
    cascade="all, delete-orphan",
)
```

```python
# backend/app/routers/transactions.py
pattern_ids = [pattern.id for pattern in transaction.seeded_recurrence_patterns]
if pattern_ids:
    (
        db.query(Transaction)
        .filter(Transaction.recurrence_pattern_id.in_(pattern_ids))
        .update({Transaction.recurrence_pattern_id: None}, synchronize_session=False)
    )

db.query(TransactionAnomaly).filter(TransactionAnomaly.transaction_id == transaction_id).delete()
db.query(ClassificationSession).filter(ClassificationSession.transaction_id == transaction_id).delete()
if pattern_ids:
    db.query(RecurrencePattern).filter(RecurrencePattern.id.in_(pattern_ids)).delete(synchronize_session=False)
db.delete(transaction)
db.commit()
```

- [ ] **Step 4: Re-run the focused backend test and confirm it passes**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q -k delete_transaction'
```

## Task 2: Conservative Similar Preview

**Files:**
- Modify: `backend/app/services/classification_session_service.py`
- Test: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Write failing preview tests for risky cross-family matches**

```python
def test_preview_similar_excludes_transfer_like_candidates_for_bill_seed():
    _reset_database()
    seed = _restore_transaction(description="PROXIMUS telecom invoice")
    transfer = _restore_transaction(description="Bancontact transfer Arne P2P MOBILE", amount=-4.0)
    utility = _restore_transaction(description="Overschrijving naar proximus", amount=-86.99)

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    client.post(
        f"/classification/sessions/{session['id']}/accept",
        json={
            "transaction_type": "Expense",
            "category": "Utilities",
            "classification_source": "assistant",
            "confirm_type_change": False,
            "recurrence": {"is_recurrent": False},
        },
    )

    response = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert response.status_code == 200
    match_ids = {match["transaction_id"] for match in response.json()["matches"]}
    assert utility["id"] in match_ids
    assert transfer["id"] not in match_ids
```

- [ ] **Step 2: Run the focused backend test and watch the risky candidate appear**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q -k preview_similar'
```

- [ ] **Step 3: Raise the threshold and add simple family filters**

```python
SIMILARITY_THRESHOLD = 0.8
SIMILARITY_PREVIEW_LIMIT = 3

TRANSFER_LIKE_TERMS = ("p2p", "transfer", "own account", "internal", "mobile")
MERCHANT_OR_BILL_LIKE_TERMS = ("energie", "proximus", "rent", "invoice", "telecom")

def looks_like_transfer(description: str) -> bool:
    normalized = normalize_for_matching(description)
    return any(term in normalized for term in TRANSFER_LIKE_TERMS)

def looks_like_bill_or_merchant(description: str) -> bool:
    normalized = normalize_for_matching(description)
    return any(term in normalized for term in MERCHANT_OR_BILL_LIKE_TERMS)
```

- [ ] **Step 4: Re-run the focused backend test and confirm only conservative matches survive**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q -k preview_similar'
```

## Task 3: Modal and Table Regressions

**Files:**
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`
- Modify: `frontend/src/components/TransactionList.test.tsx`

- [ ] **Step 1: Write failing frontend tests for the new clarity rules**

```tsx
test('save and next closes when there is no next row', async () => {
  const onOpenChange = jest.fn();
  render(/* modal with getNextTransaction={() => null} */);
  fireEvent.click(await screen.findByRole('button', { name: /save & next/i }));
  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});

test('shows editable selected category and AI confidence label', async () => {
  render(/* modal */);
  expect(await screen.findByText(/ai confidence/i)).toBeInTheDocument();
  expect(screen.getByDisplayValue('Utilities')).toBeInTheDocument();
});

test('renders ask ai for categorized rows too', () => {
  render(/* transaction list with categorized and uncategorized rows */);
  expect(screen.getAllByRole('button', { name: /ask ai/i })).toHaveLength(2);
});
```

- [ ] **Step 2: Run the focused frontend tests and watch them fail**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx src/components/TransactionList.test.tsx
```

- [ ] **Step 3: Keep the tests minimal and specific**

```tsx
// Add only the assertions needed for:
// - AI button present for every row
// - AI confidence label vs. fallback similarity label
// - preselected category dropdown
// - close-on-last Save & Next
// - apply-preview shows the chosen category
```

- [ ] **Step 4: Re-run the frontend tests and confirm the failures are the intended ones**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx src/components/TransactionList.test.tsx
```

## Task 4: Frontend Polish Implementation

**Files:**
- Modify: `frontend/src/components/TransactionList.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.tsx`

- [ ] **Step 1: Make the action cell stable and always show `Ask AI`**

```tsx
<div className="flex min-w-[160px] items-center justify-end gap-2">
  <button type="button" onClick={() => setSelectedTransaction(transaction)}>
    <SparklesIcon className="h-3.5 w-3.5" />
    <span>Ask AI</span>
  </button>
  <button onClick={() => onTransactionDelete(transaction.id)}>
    <TrashIcon className="h-4 w-4" />
  </button>
</div>
```

- [ ] **Step 2: Add authoritative type/category controls in the modal**

```tsx
const [selectedType, setSelectedType] = useState<TransactionType>(proposal.transaction_type);
const [selectedCategory, setSelectedCategory] = useState(proposal.category);

await classificationService.accept(sessionId, {
  transaction_type: selectedType,
  category: selectedCategory,
  classification_source: 'assistant',
  confirm_type_change: confirmTypeChange,
  recurrence: { ... },
});
```

- [ ] **Step 3: Keep recurrence controls layout-stable and remove the dead-end completion state**

```tsx
<div className="min-h-[88px] rounded-md border ...">
  <label className="flex items-center gap-3">...</label>
  <div className={recurrenceEnabled ? 'mt-3 flex items-center gap-3' : 'mt-3 invisible flex items-center gap-3'}>
    ...
  </div>
</div>

if (advanceToNext && !nextTransaction) {
  onOpenChange(false);
  return;
}
```

- [ ] **Step 4: Make preview and fallback wording explicit**

```tsx
<p className="text-xs text-gray-500">AI confidence • {Math.round(proposal.confidence * 100)}%</p>
<p className="text-xs text-gray-500">Similarity • {Math.round(suggestion.confidence * 100)}%</p>
<p className="text-sm font-medium">Apply category: {selectedCategory}</p>
```

- [ ] **Step 5: Re-run the focused frontend tests and confirm they pass**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx src/components/TransactionList.test.tsx
```

## Task 5: Verification

**Files:**
- Verify only

- [ ] **Step 1: Run the backend classification API slice**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'
```

- [ ] **Step 2: Run the frontend modal and table slice**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx src/components/TransactionList.test.tsx
```

- [ ] **Step 3: Sanity-check the app manually if needed**

```bash
docker compose up -d backend frontend
docker compose logs --tail=100 backend
```
