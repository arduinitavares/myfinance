# Transfer Analytics Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce first-class `TransferCategory` support and fix analytics so transfers no longer pollute spending, savings, health, projections, suggestions, or transaction editing flows.

**Architecture:** Ship this as a transfer-semantics slice first. Add `transfer_category` as a first-class transaction field, route all transfer writes through it, keep `FinancialStatistics` focused on income/expense, and expose transfer totals through a dedicated statistics response instead of overloading the existing overview model. Historical FX normalization stays out of this plan except for API shape boundaries already defined in the spec.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite migrations, Pydantic, pytest, React, TypeScript, Axios, React Testing Library, Docker Compose.

---

## Scope Check

This plan intentionally covers only the transfer-analytics core:

- `TransferCategory` backend/frontend support
- transfer-safe commit/update/undo flows
- analytics correctness for transfers
- transfer summary API + dashboard section
- historical statistics / financial-health regeneration

This plan does **not** implement the FX source/population pipeline. The approved spec allows that to land as a follow-on plan once the rate source is chosen.

## File Map

### Backend create

- `backend/app/migrations/migrate_transfer_categories.py` — add `transfer_category`, backfill legacy transfer rows, then regenerate derived aggregate tables.
- `backend/tests/test_transfer_analytics.py` — focused regression coverage for transfer category writes, statistics exclusion, transfer summary output, and migration-side expectations.

### Backend modify

- `backend/app/models/transaction.py` — add `TransferCategory` enum and `transfer_category` column.
- `backend/app/models/__init__.py` — export `TransferCategory`.
- `backend/app/schemas/transaction.py` — expose `transfer_category` and validate category families by transaction type.
- `backend/app/schemas/statistics.py` — add transfer summary response models.
- `backend/app/services/classification_commit_service.py` — write transfer categories to `transfer_category` and clear legacy income/expense category columns.
- `backend/app/services/classification_session_service.py` — supply transfer-only option families and exclude already transfer-classified rows from batch preview.
- `backend/app/services/category_suggestion_service.py` — treat transfer-classified rows as already classified and keep transfer rows out of the expense/income vector index.
- `backend/app/services/statistics_service.py` — exclude transfers from financial statistics and category statistics; add a dedicated transfer-summary query.
- `backend/app/services/financial_health_service.py` — no new formula, but rely on regenerated `FinancialStatistics`.
- `backend/app/services/projection_service.py` — rely on regenerated `FinancialStatistics` / `CategoryStatistics` without transfer leakage.
- `backend/app/routers/transactions.py` — allow `transfer_category` filtering and manual transfer-category updates.
- `backend/app/routers/statistics.py` — expose a dedicated `/statistics/transfers/summary` response and keep existing overview endpoints expense/income-only.
- `backend/app/migrations/run_migrations.py` — register the new transfer-category migration.

### Frontend create

- `frontend/src/components/dashboard/TransferSummary.tsx` — compact `Transfers & Settlements` analytics section.
- `frontend/src/components/dashboard/TransferSummary.test.tsx` — rendering + empty/error-state coverage.

### Frontend modify

- `frontend/src/types/transaction.ts` — add `TransferCategory`, `transfer_category`, and widen undo/update/filter unions.
- `frontend/src/services/transactionService.ts` — accept transfer categories in update requests.
- `frontend/src/services/statisticService.ts` — add `getTransferSummary`.
- `frontend/src/hooks/useTransactions.ts` — read/write transfer categories in list updates and undo history.
- `frontend/src/hooks/useActionHistory.ts` — restore transfer categories correctly.
- `frontend/src/components/TransactionFilters.tsx` — include transfer categories in the category filter options.
- `frontend/src/components/TransactionList.tsx` — display and edit transfer rows via `transfer_category`.
- `frontend/src/components/TransactionList.test.tsx` — transfer-row category behavior.
- `frontend/src/App.tsx` — mount `TransferSummary` in the analytics dashboard.

## Verification Commands

- Backend focused tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q'`
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q -k "transfer or category"'`
- Frontend focused tests:
  - `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/TransactionList.test.tsx src/components/dashboard/TransferSummary.test.tsx`
- Full backend regression pass for touched areas:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py tests/test_classification_api.py tests/test_upload_trust_order.py -q'`

## Task 1: Add `TransferCategory` to the Backend Transaction Model

**Files:**
- Create: `backend/tests/test_transfer_analytics.py`
- Modify: `backend/app/models/transaction.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/transaction.py`

- [ ] **Step 1: Write the failing backend contract test**

```python
from app.models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    TransactionType,
    TransferCategory,
)


def test_manual_transfer_update_uses_transfer_category_and_clears_legacy_columns():
    _reset_database()
    transaction = _restore_transaction(
        description="Belfius card settlement",
        amount=-240.00,
        transaction_type=TransactionType.TRANSFER.value,
        expense_category=ExpenseCategory.INTERNAL_TRANSFER.value,
    )

    response = client.patch(
        f"/transactions/{transaction['id']}/category",
        params={
            "transaction_type": TransactionType.TRANSFER.value,
            "category": TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_type"] == TransactionType.TRANSFER.value
    assert payload["transfer_category"] == TransferCategory.CREDIT_CARD_SETTLEMENT.value
    assert payload["expense_category"] is None
    assert payload["income_category"] is None
```

- [ ] **Step 2: Run the focused backend test and confirm it fails because `transfer_category` does not exist yet**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q -k transfer_category'
```

- [ ] **Step 3: Add the enum, ORM column, exports, and schema validation**

```python
# backend/app/models/transaction.py
class TransferCategory(enum.Enum):
    INTERNAL_TRANSFER = "Internal Transfer"
    CREDIT_CARD_SETTLEMENT = "Credit Card Settlement"
    LOAN_TO_PERSON = "Loan to Person"
    LOAN_REPAYMENT_RECEIVED = "Loan Repayment Received"
    LOAN_FROM_PERSON = "Loan from Person"
    DEBT_REPAYMENT_SENT = "Debt Repayment Sent"


transfer_category = Column(Enum(TransferCategory), nullable=True)
```

```python
# backend/app/schemas/transaction.py
from ..models.transaction import ExpenseCategory, IncomeCategory, TransactionType, TransferCategory


class TransactionBase(BaseModel):
    ...
    transfer_category: Optional[TransferCategory] = None

    @validator("expense_category", "income_category", "transfer_category", pre=True)
    def validate_categories(cls, v, values):
        if not v:
            return None
        transaction_type = values.get("transaction_type")
        if transaction_type == TransactionType.EXPENSE:
            return ExpenseCategory(v) if isinstance(v, (str, ExpenseCategory)) else None
        if transaction_type == TransactionType.INCOME:
            return IncomeCategory(v) if isinstance(v, (str, IncomeCategory)) else None
        if transaction_type == TransactionType.TRANSFER:
            return TransferCategory(v) if isinstance(v, (str, TransferCategory)) else None
        return None
```

- [ ] **Step 4: Re-run the focused backend test and confirm the remaining failure moves into commit logic instead of serialization**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q -k transfer_category'
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/transaction.py backend/app/models/__init__.py backend/app/schemas/transaction.py backend/tests/test_transfer_analytics.py
git commit -m "feat: add transfer category model support"
```

## Task 2: Rewrite Commit, Assistant, and Suggestion Flows for Transfer Categories

**Files:**
- Modify: `backend/app/services/classification_commit_service.py`
- Modify: `backend/app/services/classification_session_service.py`
- Modify: `backend/app/services/category_suggestion_service.py`
- Modify: `backend/app/routers/transactions.py`
- Test: `backend/tests/test_transfer_analytics.py`
- Test: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Add failing tests for commit flow, assistant options, and suggestion guards**

```python
def test_transfer_rows_are_not_treated_as_uncategorized_in_similar_preview():
    _reset_database()
    seed = _restore_transaction(
        description="Monthly credit card settlement",
        amount=-240.00,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
    )
    already_classified = _restore_transaction(
        description="Previous credit card settlement",
        amount=-225.00,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
    )

    session = client.post("/classification/sessions", json={"transaction_id": seed["id"]}).json()
    preview = client.post(f"/classification/sessions/{session['id']}/similar-preview")

    assert preview.status_code == 200
    match_ids = {item["transaction_id"] for item in preview.json()["matches"]}
    assert already_classified["id"] not in match_ids


def test_transfer_allowed_options_include_all_transfer_categories():
    options = ClassificationSessionService._allowed_options_by_type(TransactionType.TRANSFER)
    assert options[TransactionType.TRANSFER.value] == [
        TransferCategory.INTERNAL_TRANSFER.value,
        TransferCategory.CREDIT_CARD_SETTLEMENT.value,
        TransferCategory.LOAN_TO_PERSON.value,
        TransferCategory.LOAN_REPAYMENT_RECEIVED.value,
        TransferCategory.LOAN_FROM_PERSON.value,
        TransferCategory.DEBT_REPAYMENT_SENT.value,
    ]
```

- [ ] **Step 2: Run the backend tests and confirm the transfer path still hardcodes legacy income/expense categories**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py tests/test_classification_api.py -q -k "transfer or uncategorized"'
```

- [ ] **Step 3: Replace legacy transfer normalization with first-class `transfer_category` writes**

```python
# backend/app/services/classification_commit_service.py
from ..models.transaction import (
    ExpenseCategory,
    IncomeCategory,
    Transaction,
    TransactionType,
    TransferCategory,
)


def normalized_category_for(*, transaction_type: TransactionType, category: str, amount: float) -> str:
    if transaction_type == TransactionType.EXPENSE:
        return ExpenseCategory(category).value
    if transaction_type == TransactionType.INCOME:
        return IncomeCategory(category).value
    return TransferCategory(category).value


if transaction_type == TransactionType.EXPENSE:
    transaction.expense_category = ExpenseCategory(normalized_category)
    transaction.income_category = None
    transaction.transfer_category = None
elif transaction_type == TransactionType.INCOME:
    transaction.income_category = IncomeCategory(normalized_category)
    transaction.expense_category = None
    transaction.transfer_category = None
else:
    transaction.transfer_category = TransferCategory(normalized_category)
    transaction.expense_category = None
    transaction.income_category = None
```

```python
# backend/app/services/classification_session_service.py
def _allowed_options_by_type(transaction_type: TransactionType) -> dict[str, list[str]]:
    transfer_categories = [category.value for category in TransferCategory]
    if transaction_type == TransactionType.EXPENSE:
        return {
            TransactionType.EXPENSE.value: [category.value for category in ExpenseCategory],
            TransactionType.TRANSFER.value: transfer_categories,
        }
    if transaction_type == TransactionType.INCOME:
        return {
            TransactionType.INCOME.value: [category.value for category in IncomeCategory],
            TransactionType.TRANSFER.value: transfer_categories,
        }
    return {TransactionType.TRANSFER.value: transfer_categories}
```

```python
# backend/app/services/category_suggestion_service.py
if transaction.transfer_category:
    continue

...

if transaction.transfer_category:
    return
```

- [ ] **Step 4: Update transaction filtering to understand transfer categories**

```python
# backend/app/routers/transactions.py
transfer_enum = None
try:
    transfer_enum = TransferCategory(category)
except Exception:
    pass

if expense_enum and income_enum and transfer_enum:
    query = query.filter(
        or_(
            Transaction.expense_category == expense_enum,
            Transaction.income_category == income_enum,
            Transaction.transfer_category == transfer_enum,
        )
    )
elif transfer_enum:
    query = query.filter(Transaction.transfer_category == transfer_enum)
```

- [ ] **Step 5: Re-run the backend tests and confirm transfer writes/read paths now use `transfer_category`**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py tests/test_classification_api.py -q -k "transfer or uncategorized"'
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/classification_commit_service.py backend/app/services/classification_session_service.py backend/app/services/category_suggestion_service.py backend/app/routers/transactions.py backend/tests/test_transfer_analytics.py backend/tests/test_classification_api.py
git commit -m "feat: route transfer workflows through transfer categories"
```

## Task 3: Add Migration and Historical Rebuild for Transfer Categories

**Files:**
- Create: `backend/app/migrations/migrate_transfer_categories.py`
- Modify: `backend/app/migrations/run_migrations.py`
- Test: `backend/tests/test_transfer_analytics.py`

- [ ] **Step 1: Write the failing migration regression**

```python
def test_transfer_category_migration_backfills_legacy_internal_transfer_rows():
    _reset_database()
    db = SessionLocal()
    try:
        row = Transaction(
            account_number="BE_TEST",
            transaction_date=date(2026, 4, 1),
            amount=-50.0,
            currency="EUR",
            description="Legacy internal transfer",
            transaction_type=TransactionType.TRANSFER,
            expense_category=ExpenseCategory.INTERNAL_TRANSFER,
            source_bank="Belfius",
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    migrate_transfer_categories()

    db = SessionLocal()
    try:
        migrated = db.query(Transaction).filter(Transaction.description == "Legacy internal transfer").first()
        assert migrated.transfer_category == TransferCategory.INTERNAL_TRANSFER
        assert migrated.expense_category is None
        assert migrated.income_category is None
    finally:
        db.close()
```

- [ ] **Step 2: Run the migration test and confirm it fails before the new migration exists**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q -k migration_backfills'
```

- [ ] **Step 3: Add the migration and force derived-table regeneration**

```python
# backend/app/migrations/migrate_transfer_categories.py
def migrate_transfer_categories():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(transactions)")).fetchall()]
        if "transfer_category" not in columns:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN transfer_category VARCHAR(100)"))

    db = SessionLocal()
    try:
        rows = db.query(Transaction).filter(Transaction.transaction_type == TransactionType.TRANSFER).all()
        for row in rows:
            if row.transfer_category is None:
                row.transfer_category = TransferCategory.INTERNAL_TRANSFER
            row.expense_category = None
            row.income_category = None
        db.commit()

        StatisticsService.initialize_statistics(db)
        StatisticsService.initialize_category_statistics(db)
        FinancialHealthService.initialize_financial_health(db)
    finally:
        db.close()
```

```python
# backend/app/migrations/run_migrations.py
from app.migrations.migrate_transfer_categories import migrate_transfer_categories

...
migrate_classification_assistant()
migrate_transfer_categories()
migrate_expense_type_values()
```

- [ ] **Step 4: Re-run the migration test and confirm the row is backfilled and aggregates are reinitialized**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q -k migration_backfills'
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/migrations/migrate_transfer_categories.py backend/app/migrations/run_migrations.py backend/tests/test_transfer_analytics.py
git commit -m "feat: migrate legacy transfers to transfer categories"
```

## Task 4: Fix Statistics, Health, Projections, and Add Transfer Summary API

**Files:**
- Modify: `backend/app/services/statistics_service.py`
- Modify: `backend/app/routers/statistics.py`
- Modify: `backend/app/schemas/statistics.py`
- Test: `backend/tests/test_transfer_analytics.py`

- [ ] **Step 1: Write failing analytics regression tests**

```python
def test_transfer_transactions_are_excluded_from_financial_statistics_totals():
    _reset_database()
    _restore_transaction(description="Salary", amount=3000.0, transaction_type=TransactionType.INCOME.value)
    _restore_transaction(description="Rent", amount=-1200.0, transaction_type=TransactionType.EXPENSE.value, expense_category=ExpenseCategory.HOUSING.value)
    _restore_transaction(
        description="Card settlement",
        amount=-500.0,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
    )

    db = SessionLocal()
    try:
        StatisticsService.initialize_statistics(db)
        monthly = db.query(FinancialStatistics).filter(FinancialStatistics.period == StatisticsPeriod.MONTHLY).first()
        assert monthly.period_income == 3000.0
        assert monthly.period_expenses == 1200.0
        assert monthly.period_net_savings == 1800.0
    finally:
        db.close()


def test_transfer_summary_endpoint_returns_outgoing_and_incoming_by_subtype():
    _reset_database()
    _restore_transaction(
        description="Settlement out",
        amount=-500.0,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.CREDIT_CARD_SETTLEMENT.value,
    )
    _restore_transaction(
        description="Brother repaid",
        amount=150.0,
        transaction_type=TransactionType.TRANSFER.value,
        transfer_category=TransferCategory.LOAN_REPAYMENT_RECEIVED.value,
    )

    response = client.get("/statistics/transfers/summary")

    assert response.status_code == 200
    payload = response.json()
    settlement = next(item for item in payload["items"] if item["subtype"] == "Credit Card Settlement")
    assert settlement["total_outgoing_eur"] == 500.0
    assert settlement["total_incoming_eur"] == 0.0
```

- [ ] **Step 2: Run the backend tests and confirm transfers still leak into expense totals**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q -k "financial_statistics_totals or transfers_summary"'
```

- [ ] **Step 3: Fix the three accumulation loops and add a dedicated transfer-summary query**

```python
# backend/app/services/statistics_service.py
for trans in period_transactions:
    if trans.transaction_type == TransactionType.INCOME:
        period_stats["period_income"] += trans.amount
        period_stats["income_count"] += 1
    elif trans.transaction_type == TransactionType.EXPENSE:
        period_stats["period_expenses"] += abs(trans.amount)
        period_stats["expense_count"] += 1

for trans in cumulative_transactions:
    if trans.transaction_type == TransactionType.INCOME:
        cumulative_stats["total_income"] += trans.amount
    elif trans.transaction_type == TransactionType.EXPENSE:
        cumulative_stats["total_expenses"] += abs(trans.amount)

for trans in yearly_transactions:
    if trans.transaction_type == TransactionType.INCOME:
        yearly_stats["yearly_income"] += trans.amount
    elif trans.transaction_type == TransactionType.EXPENSE:
        yearly_stats["yearly_expenses"] += abs(trans.amount)
```

```python
# backend/app/services/statistics_service.py
@staticmethod
def get_transfer_summary(db: Session, start: date, end: date) -> list[dict]:
    rows = (
        db.query(Transaction.transfer_category, Transaction.amount)
        .filter(
            Transaction.transaction_type == TransactionType.TRANSFER,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .all()
    )
    summary: dict[str, dict[str, float | int | str]] = {}
    for category, amount in rows:
        key = category.value if category else TransferCategory.INTERNAL_TRANSFER.value
        item = summary.setdefault(
            key,
            {
                "subtype": key,
                "transaction_count": 0,
                "total_outgoing_eur": 0.0,
                "total_incoming_eur": 0.0,
            },
        )
        item["transaction_count"] += 1
        if amount < 0:
            item["total_outgoing_eur"] += abs(amount)
        elif amount > 0:
            item["total_incoming_eur"] += abs(amount)
    return list(summary.values())
```

- [ ] **Step 4: Add the dedicated statistics response and endpoint**

```python
# backend/app/schemas/statistics.py
class TransferSummaryItem(BaseModel):
    subtype: str
    transaction_count: int
    total_outgoing_eur: float
    total_incoming_eur: float


class TransferSummaryResponse(BaseModel):
    start_date: str
    end_date: str
    items: list[TransferSummaryItem]
```

```python
# backend/app/routers/statistics.py
@router.get("/transfers/summary", response_model=TransferSummaryResponse)
def get_transfer_summary(
    db: Session = Depends(get_db),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    latest_transaction = db.query(func.max(Transaction.transaction_date)).scalar()
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else latest_transaction
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else end.replace(day=1)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "items": StatisticsService.get_transfer_summary(db, start, end),
    }
```

- [ ] **Step 5: Re-run the backend tests and confirm transfers disappear from savings math but remain visible in the transfer summary**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py -q -k "financial_statistics_totals or transfers_summary"'
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/statistics_service.py backend/app/routers/statistics.py backend/app/schemas/statistics.py backend/tests/test_transfer_analytics.py
git commit -m "feat: add transfer-safe analytics and summary api"
```

## Task 5: Update Frontend Types, Filters, Editing, and Undo for Transfer Categories

**Files:**
- Modify: `frontend/src/types/transaction.ts`
- Modify: `frontend/src/services/transactionService.ts`
- Modify: `frontend/src/hooks/useTransactions.ts`
- Modify: `frontend/src/hooks/useActionHistory.ts`
- Modify: `frontend/src/components/TransactionFilters.tsx`
- Modify: `frontend/src/components/TransactionList.tsx`
- Test: `frontend/src/components/TransactionList.test.tsx`

- [ ] **Step 1: Write the failing frontend tests for transfer category display and editing**

```tsx
test('transfer rows show transfer category instead of legacy expense category', () => {
  render(
    <TransactionList
      transactions={[
        {
          id: 1,
          account_number: 'BE_TEST',
          transaction_date: '2026-04-01',
          amount: -240,
          currency: 'EUR',
          description: 'Card settlement',
          transaction_type: TransactionType.TRANSFER,
          transfer_category: TransferCategory.CREDIT_CARD_SETTLEMENT,
          source_bank: 'Belfius',
        },
      ]}
      {...defaultProps}
    />
  );

  expect(screen.getByDisplayValue('Credit Card Settlement')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend test and confirm TypeScript/test failures around the missing union member**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/TransactionList.test.tsx
```

- [ ] **Step 3: Add `TransferCategory` to the frontend model and route update/undo by transaction type**

```ts
// frontend/src/types/transaction.ts
export enum TransferCategory {
  INTERNAL_TRANSFER = "Internal Transfer",
  CREDIT_CARD_SETTLEMENT = "Credit Card Settlement",
  LOAN_TO_PERSON = "Loan to Person",
  LOAN_REPAYMENT_RECEIVED = "Loan Repayment Received",
  LOAN_FROM_PERSON = "Loan from Person",
  DEBT_REPAYMENT_SENT = "Debt Repayment Sent",
}

export interface Transaction {
  ...
  transfer_category?: TransferCategory;
}

export interface UpdateCategoryAction {
  type: ActionType.UPDATE_CATEGORY;
  transactionId: number;
  oldCategory: ExpenseCategory | IncomeCategory | TransferCategory | undefined;
  newCategory: ExpenseCategory | IncomeCategory | TransferCategory;
  transactionType: TransactionType;
}
```

```ts
// frontend/src/hooks/useTransactions.ts
const [categoryFilter, setCategoryFilter] = useState<
  ExpenseCategory | IncomeCategory | TransferCategory | 'all'
>('all');

const oldCategory =
  transactionType === TransactionType.EXPENSE
    ? transaction.expense_category
    : transactionType === TransactionType.INCOME
      ? transaction.income_category
      : transaction.transfer_category;
```

```ts
// frontend/src/services/transactionService.ts
updateCategory: async (
  transactionId: number,
  category: ExpenseCategory | IncomeCategory | TransferCategory,
  transactionType: TransactionType
): Promise<Transaction> => {
  const response = await axios.patch(
    `${API_BASE_URL}/transactions/${transactionId}/category`,
    null,
    {
      params: {
        category,
        transaction_type: transactionType,
      },
    }
  );
  return response.data;
},
```

```ts
// frontend/src/hooks/useActionHistory.ts
const restoreCategory = async (
  transactionId: number,
  oldCategory: ExpenseCategory | IncomeCategory | TransferCategory | undefined,
  transactionType: TransactionType
): Promise<boolean> => {
  if (!oldCategory) return false;
  await transactionService.updateCategory(transactionId, oldCategory, transactionType);
  return true;
};
```

```ts
// frontend/src/components/TransactionList.tsx
const getDisplayedCategory = (transaction: Transaction) => {
  if (transaction.transaction_type === TransactionType.EXPENSE) return transaction.expense_category;
  if (transaction.transaction_type === TransactionType.INCOME) return transaction.income_category;
  return transaction.transfer_category;
};

const getCategoryOptions = (transaction: Transaction) => {
  if (transaction.transaction_type === TransactionType.EXPENSE) return Object.values(ExpenseCategory);
  if (transaction.transaction_type === TransactionType.INCOME) return Object.values(IncomeCategory);
  return Object.values(TransferCategory);
};
```

```tsx
// frontend/src/components/TransactionFilters.tsx
const categoryOptions = [
  ...Object.values(ExpenseCategory),
  ...Object.values(IncomeCategory),
  ...Object.values(TransferCategory),
];
```

- [ ] **Step 4: Re-run the frontend test and confirm transfer rows edit/render through the correct category family**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/TransactionList.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/transaction.ts frontend/src/services/transactionService.ts frontend/src/hooks/useTransactions.ts frontend/src/hooks/useActionHistory.ts frontend/src/components/TransactionFilters.tsx frontend/src/components/TransactionList.tsx frontend/src/components/TransactionList.test.tsx
git commit -m "feat: support transfer categories in transaction editing"
```

## Task 6: Add the Analytics `Transfers & Settlements` Section

**Files:**
- Create: `frontend/src/components/dashboard/TransferSummary.tsx`
- Create: `frontend/src/components/dashboard/TransferSummary.test.tsx`
- Modify: `frontend/src/services/statisticService.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing dashboard test**

```tsx
jest.mock('../../services/statisticService', () => ({
  statisticService: {
    getTransferSummary: jest.fn().mockResolvedValue({
      start_date: '2026-04-01',
      end_date: '2026-04-30',
      items: [
        {
          subtype: 'Credit Card Settlement',
          transaction_count: 2,
          total_outgoing_eur: 740,
          total_incoming_eur: 0,
        },
      ],
    }),
  },
}));

test('renders outgoing and incoming transfer totals by subtype', async () => {
  render(<TransferSummary />);
  expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();
  expect(screen.getByText('Credit Card Settlement')).toBeInTheDocument();
  expect(screen.getByText(/€740\.00/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused dashboard test and confirm the component does not exist yet**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx
```

- [ ] **Step 3: Add the service call and compact dashboard component**

```ts
// frontend/src/services/statisticService.ts
getTransferSummary: async (start_date?: string, end_date?: string) => {
  const params: Record<string, string> = {};
  if (start_date) params.start_date = start_date;
  if (end_date) params.end_date = end_date;
  const response = await axios.get(`${API_BASE_URL}/statistics/transfers/summary`, { params });
  return response.data;
},
```

```tsx
// frontend/src/components/dashboard/TransferSummary.tsx
export const TransferSummary: React.FC = () => {
  const [data, setData] = useState<TransferSummaryResponse | null>(null);

  useEffect(() => {
    statisticService.getTransferSummary().then(setData).catch(console.error);
  }, []);

  return (
    <section className="rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <h3 className="text-lg font-medium text-gray-700 dark:text-gray-200">Transfers & Settlements</h3>
      <div className="mt-4 space-y-3">
        {data?.items.map((item) => (
          <div key={item.subtype} className="flex items-center justify-between text-sm">
            <span>{item.subtype}</span>
            <span>
              Out {item.total_outgoing_eur.toFixed(2)} / In {item.total_incoming_eur.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
};
```

- [ ] **Step 4: Mount the new section in the analytics dashboard and re-run the frontend tests**

```tsx
// frontend/src/App.tsx
import { TransferSummary } from './components/dashboard/TransferSummary';

...

<FinancialOverview />
<TransferSummary />
```

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx src/components/TransactionList.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/statisticService.ts frontend/src/components/dashboard/TransferSummary.tsx frontend/src/components/dashboard/TransferSummary.test.tsx frontend/src/App.tsx
git commit -m "feat: add transfer summary to analytics dashboard"
```

## Task 7: Full Verification and Manual Smoke Check

**Files:**
- Modify: none
- Test: `backend/tests/test_transfer_analytics.py`
- Test: `backend/tests/test_classification_api.py`
- Test: `backend/tests/test_upload_trust_order.py`
- Test: `frontend/src/components/TransactionList.test.tsx`
- Test: `frontend/src/components/dashboard/TransferSummary.test.tsx`

- [ ] **Step 1: Run the full touched backend suite**

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_transfer_analytics.py tests/test_classification_api.py tests/test_upload_trust_order.py -q'
```

- [ ] **Step 2: Run the touched frontend suite**

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/TransactionList.test.tsx src/components/dashboard/TransferSummary.test.tsx
```

- [ ] **Step 3: Rebuild and smoke test the app manually**

```bash
cd /Users/aaat/myfinance && docker compose up --build -d
```

Expected manual checks:

- classify a settlement as `Transfer / Credit Card Settlement`
- verify `/analytics` expense totals do not change from that settlement alone
- verify the `Transfers & Settlements` section shows the settlement
- verify a transfer row in `/transactions` shows the transfer category dropdown
- verify undo restores a transfer category change

- [ ] **Step 4: Commit the verification-only follow-up if any fixture or assertion needed adjustment**

```bash
git add -A
git commit -m "test: finalize transfer analytics verification"
```

## Self-Review

### Spec coverage

- `TransferCategory` model, API, UI, and undo flow: covered by Tasks 1, 2, and 5.
- transfer exclusion from main analytics: covered by Task 4.
- dedicated transfer summary section: covered by Tasks 4 and 6.
- historical statistics and financial-health regeneration: covered by Task 3.
- category-suggestion / similar-preview compatibility: covered by Task 2.
- FX implementation: intentionally excluded from this plan; requires a follow-on plan once the rate source decision is made.

### Placeholder scan

- No `TODO`, `TBD`, or “appropriate handling” placeholders remain.
- Every code-changing step includes concrete code blocks.
- Every verification step includes an exact command.

### Type consistency

- The plan consistently uses `TransferCategory` as the third category family.
- Transaction responses always expose `transfer_category` explicitly.
- The frontend update/undo flow uses `ExpenseCategory | IncomeCategory | TransferCategory`.

## Follow-on Plan

After this transfer-core plan ships, write a second plan for historical FX normalization:

- FX rate source selection
- FX-table population/backfill
- EUR-normalized transfer summary values for non-`EUR` rows
- incomplete-rate UI handling in analytics
