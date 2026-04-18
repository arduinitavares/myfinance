# Reporting Currency Core Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transactions, scoped analytics, import review, and the AI classification modal fully reporting-currency aware, with backend-owned conversion and no fixed-EUR fallback on scoped surfaces.

**Architecture:** Add one shared backend money pipeline for alias normalization plus explicit display availability metadata, then move the scoped analytics endpoints off persisted EUR-only aggregates onto raw-transaction aggregation in the selected reporting currency. Update the frontend to consume those explicit line-item and aggregate contracts, render partial-data warnings where conversion is incomplete, and remove `PERSISTED_STATISTICS_CURRENCY` from all scoped dashboard views.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, React Testing Library, Jest, react-scripts

---

## File Structure

### Backend

- Create: `backend/app/services/currency_aliases.py`
  - Single-purpose alias normalization for `xUSD -> USD`, `EURX -> EUR`, `USDC -> USD`.
- Create: `backend/app/services/reporting_currency_analytics.py`
  - Raw-transaction aggregation for scoped `/statistics/*` endpoints, including `conversion_summary`.
- Create: `backend/tests/services/test_reporting_currency_analytics.py`
  - Unit coverage for raw-transaction financial/category aggregation and partial-conversion metadata.
- Create: `backend/tests/test_statistics_api.py`
  - API coverage for the new scoped statistics response contracts.
- Modify: `backend/app/services/currency_conversion.py`
  - Normalize currencies before support checks and keep `DisplayMoney` as the single conversion result shape.
- Modify: `backend/app/schemas/transaction.py`
  - Add `display_is_available` and `display_unavailable_reason` to transaction payloads.
- Modify: `backend/app/schemas/imports.py`
  - Add the same explicit display availability fields to import review draft payloads.
- Modify: `backend/app/schemas/statistics.py`
  - Replace list-only response models with wrapper objects that include `reporting_currency`, `conversion_summary`, and `items`.
- Modify: `backend/app/routers/statistics.py`
  - Delegate scoped endpoints to the new analytics service instead of reading persisted EUR-only tables.

### Frontend

- Create: `frontend/src/types/statistics.ts`
  - Shared reporting-currency-aware response types for overview, timeseries, category, expense-type, and conversion-summary payloads.
- Create: `frontend/src/components/common/DisplayMoney.test.tsx`
  - Unit tests for explicit unavailable states and raw-context fallback.
- Create: `frontend/src/components/dashboard/ConversionSummaryNotice.tsx`
  - Shared warning banner for partial aggregate totals.
- Create: `frontend/src/components/dashboard/CategoryTrends.test.tsx`
  - Regression coverage for consistent currency formatting between tabs.
- Modify: `frontend/src/types/transaction.ts`
  - Extend shared line-item types with explicit display availability fields.
- Modify: `frontend/src/types/import.ts`
  - Mirror the import review display availability fields.
- Modify: `frontend/src/utils/currency.ts`
  - Teach `resolveDisplayMoney` to respect explicit availability metadata and remove scoped legacy EUR assumptions once unused.
- Modify: `frontend/src/services/statisticService.ts`
  - Return wrapped statistics responses instead of raw arrays.
- Modify: `frontend/src/hooks/useStatistics.ts`
- Modify: `frontend/src/hooks/useStatisticsTimeseries.ts`
- Modify: `frontend/src/hooks/useCategoryTimeseries.ts`
- Modify: `frontend/src/hooks/useExpenseTypeStatistics.ts`
- Modify: `frontend/src/hooks/useExpenseTypeTimeseries.ts`
  - Unwrap the new backend response shape and surface `conversion_summary` to components.
- Modify: `frontend/src/components/TransactionList.tsx`
- Modify: `frontend/src/components/imports/ImportReviewPage.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.tsx`
  - Pass explicit display availability fields through `DisplayMoney`.
- Modify: `frontend/src/components/dashboard/FinancialOverview.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.tsx`
- Modify: `frontend/src/components/dashboard/CategoryBreakdown.tsx`
- Modify: `frontend/src/components/dashboard/CategoryTrends.tsx`
- Modify: `frontend/src/components/dashboard/CategoryAverages.tsx`
- Modify: `frontend/src/components/dashboard/CategoryTimeseriesChart.tsx`
- Modify: `frontend/src/components/dashboard/ExpenseTypeTimeseriesChart.tsx`
- Modify: `frontend/src/components/dashboard/TimeseriesChart.tsx`
- Modify: `frontend/src/components/dashboard/MonthlyHeatmap.tsx`
  - Consume reporting-currency-aware aggregate payloads and show partial-data warnings where needed.

### Existing Tests To Update

- Modify: `backend/tests/services/test_currency_conversion.py`
- Modify: `backend/tests/test_transaction_listing.py`
- Modify: `backend/tests/imports/test_import_review_api.py`
- Modify: `backend/tests/test_classification_api.py`
- Modify: `frontend/src/components/TransactionList.test.tsx`
- Modify: `frontend/src/components/imports/ImportReviewPage.test.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`
- Modify: `frontend/src/components/dashboard/MonthlyHeatmap.test.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.test.tsx`

### Explicitly Out Of Scope For This Plan

- `frontend/src/components/dashboard/WeekdayDistribution.tsx`
- `frontend/src/components/dashboard/FinancialHealth.tsx`
- `frontend/src/components/dashboard/projections/**`
- `frontend/src/components/dashboard/anomalies/**`
- Nexo CSV parsing and import detection
- Arbitrary raw currencies beyond the bounded alias set plus existing EUR/USD/BRL support

### Task 1: Normalize Currency Aliases And Expose Explicit Display Availability

**Files:**
- Create: `backend/app/services/currency_aliases.py`
- Modify: `backend/app/services/currency_conversion.py`
- Modify: `backend/app/schemas/transaction.py`
- Modify: `backend/app/schemas/imports.py`
- Test: `backend/tests/services/test_currency_conversion.py`
- Test: `backend/tests/test_transaction_listing.py`
- Test: `backend/tests/imports/test_import_review_api.py`
- Test: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Write the failing backend tests for alias normalization and explicit availability metadata**

```python
def test_convert_normalizes_supported_alias_before_conversion(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 4, 17),
        quoted_currency="USD",
        units_per_base="1.2500",
    )
    service = CurrencyConversionService(db_session)

    result = service.convert(
        raw_amount=Decimal("10.00"),
        raw_currency="xUSD",
        reporting_currency="EUR",
        transaction_date=date(2026, 4, 17),
    )

    assert result == DisplayMoney(
        display_amount=Decimal("8.00"),
        display_currency="EUR",
        display_fx_rate=Decimal("0.8"),
        display_rate_date=date(2026, 4, 17),
        is_available=True,
        unavailable_reason=None,
    )


def test_serialize_display_money_includes_explicit_availability_fields():
    payload = serialize_display_money(
        DisplayMoney.unavailable(display_currency="BRL", reason="unsupported_currency")
    )

    assert payload == {
        "display_amount": None,
        "display_currency": "BRL",
        "display_fx_rate": None,
        "display_rate_date": None,
        "display_is_available": False,
        "display_unavailable_reason": "unsupported_currency",
    }
```

- [ ] **Step 2: Run the failing backend tests**

Run:

```bash
cd backend && pytest tests/services/test_currency_conversion.py tests/test_transaction_listing.py tests/imports/test_import_review_api.py tests/test_classification_api.py -k "normalize or availability or unavailable_reason" -v
```

Expected: FAIL because alias currencies still hit `unsupported_currency` and serialized payloads do not yet expose `display_is_available` or `display_unavailable_reason`.

- [ ] **Step 3: Add the shared alias normalization helper**

```python
# backend/app/services/currency_aliases.py
CURRENCY_ALIASES = {
    "XUSD": "USD",
    "EURX": "EUR",
    "USDC": "USD",
}


def normalize_currency_code(raw_currency: str | None) -> str | None:
    if raw_currency is None:
        return None
    normalized = raw_currency.strip().upper()
    return CURRENCY_ALIASES.get(normalized, normalized)
```

- [ ] **Step 4: Thread alias normalization and explicit availability fields through the display-money contract**

```python
# backend/app/services/currency_conversion.py
from app.services.currency_aliases import normalize_currency_code

normalized_raw_currency = normalize_currency_code(raw_currency)
normalized_reporting_currency = normalize_currency_code(reporting_currency)
decimal_amount = Decimal(str(raw_amount))

if (
    normalized_raw_currency not in self.SUPPORTED_CURRENCIES
    or normalized_reporting_currency not in self.SUPPORTED_CURRENCIES
):
    return DisplayMoney.unavailable(
        display_currency=normalized_reporting_currency or reporting_currency.strip().upper(),
        reason="unsupported_currency",
    )
```

```python
# backend/app/schemas/transaction.py
class Transaction(TransactionBase):
    id: int
    import_session_id: Optional[int] = None
    import_source_locator: Optional[str] = None
    import_source_description: Optional[str] = None
    canonical_description_en: Optional[str] = None
    display_amount: Optional[float] = None
    display_currency: Optional[str] = None
    display_fx_rate: Optional[float] = None
    display_rate_date: Optional[date] = None
    display_is_available: Optional[bool] = None
    display_unavailable_reason: Optional[str] = None


def serialize_display_money(display_money: DisplayMoney) -> dict[str, Any]:
    return {
        "display_amount": display_money.display_amount,
        "display_currency": display_money.display_currency,
        "display_fx_rate": display_money.display_fx_rate,
        "display_rate_date": display_money.display_rate_date,
        "display_is_available": display_money.is_available,
        "display_unavailable_reason": display_money.unavailable_reason,
    }
```

```python
# backend/app/schemas/imports.py
class ImportTransactionDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    transaction_date: date | None = None
    source_description: str
    signed_amount: float
    currency: str
    source_locator: str
    edit_source: str
    display_amount: float | None = None
    display_currency: str | None = None
    display_fx_rate: float | None = None
    display_rate_date: date | None = None
    display_is_available: bool | None = None
    display_unavailable_reason: str | None = None
```

- [ ] **Step 5: Re-run the backend tests and make sure the shared contract passes**

Run:

```bash
cd backend && pytest tests/services/test_currency_conversion.py tests/test_transaction_listing.py tests/imports/test_import_review_api.py tests/test_classification_api.py -k "normalize or availability or unavailable_reason" -v
```

Expected: PASS for alias normalization plus explicit availability fields on transactions, import review payloads, and classification responses.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/currency_aliases.py backend/app/services/currency_conversion.py backend/app/schemas/transaction.py backend/app/schemas/imports.py backend/tests/services/test_currency_conversion.py backend/tests/test_transaction_listing.py backend/tests/imports/test_import_review_api.py backend/tests/test_classification_api.py
git commit -m "feat: normalize display money contract"
```

### Task 2: Adopt The Explicit Line-Item Contract On The Frontend

**Files:**
- Create: `frontend/src/components/common/DisplayMoney.test.tsx`
- Modify: `frontend/src/types/transaction.ts`
- Modify: `frontend/src/types/import.ts`
- Modify: `frontend/src/utils/currency.ts`
- Modify: `frontend/src/components/common/DisplayMoney.tsx`
- Modify: `frontend/src/components/TransactionList.tsx`
- Modify: `frontend/src/components/imports/ImportReviewPage.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.tsx`
- Test: `frontend/src/components/TransactionList.test.tsx`
- Test: `frontend/src/components/imports/ImportReviewPage.test.tsx`
- Test: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`

- [ ] **Step 1: Write the failing frontend tests for unavailable line-item states**

```tsx
test('DisplayMoney shows raw context when the backend marks FX as unavailable', () => {
  render(
    <DisplayMoney
      rawAmount={-42}
      rawCurrency="NEXO"
      displayAmount={null}
      displayCurrency="USD"
      displayIsAvailable={false}
      displayUnavailableReason="unsupported_currency"
    />
  );

  expect(screen.getByText('FX unavailable')).toBeInTheDocument();
  expect(screen.getByText('Raw -NEXO 42.00')).toBeInTheDocument();
});
```

```tsx
test('TransactionList passes explicit display availability fields through to the amount cell', async () => {
  render(
    <TransactionList
      transactions={[
        {
          id: 1,
          transaction_date: '2026-04-11',
          description: 'Unsupported asset',
          amount: -42,
          currency: 'NEXO',
          display_amount: null,
          display_currency: 'USD',
          display_is_available: false,
          display_unavailable_reason: 'unsupported_currency',
          transaction_type: TransactionType.EXPENSE,
          source_bank: 'nexo',
        } as Transaction,
      ]}
      totalTransactions={1}
      currentPage={1}
      totalPages={1}
      onPageChange={jest.fn()}
      sortParams={{ field: 'date', direction: 'desc' }}
      onSortChange={jest.fn()}
      onTransactionUpdate={jest.fn()}
      onTransactionDelete={jest.fn()}
      onTransactionsRefresh={jest.fn()}
    />
  );

  expect(await screen.findByText('FX unavailable')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the failing frontend tests**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand src/components/common/DisplayMoney.test.tsx src/components/TransactionList.test.tsx src/components/imports/ImportReviewPage.test.tsx src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected: FAIL because the shared types and `DisplayMoney` props do not yet accept `display_is_available` or `display_unavailable_reason`.

- [ ] **Step 3: Extend the shared TypeScript types and money resolver**

```ts
// frontend/src/types/transaction.ts
export interface DisplayMoneyFields {
  display_amount?: number | null;
  display_currency?: string | null;
  display_fx_rate?: number | null;
  display_rate_date?: string | null;
  display_is_available?: boolean | null;
  display_unavailable_reason?: string | null;
}
```

```ts
// frontend/src/utils/currency.ts
export interface ResolveDisplayMoneyOptions {
  rawAmount: number;
  rawCurrency: string;
  displayAmount?: number | null;
  displayCurrency?: string | null;
  displayIsAvailable?: boolean | null;
  displayUnavailableReason?: string | null;
  absolute?: boolean;
  showRawWhenConverted?: boolean;
  formatOptions?: Intl.NumberFormatOptions;
}

if (displayIsAvailable === false) {
  return {
    isAvailable: false,
    primaryText: 'FX unavailable',
    secondaryText: `Raw ${rawText}`,
  };
}
```

- [ ] **Step 4: Pass the explicit availability fields through every scoped line-item surface**

```tsx
// frontend/src/components/common/DisplayMoney.tsx
interface DisplayMoneyProps {
  rawAmount: number;
  rawCurrency: string;
  displayAmount?: number | null;
  displayCurrency?: string | null;
  displayIsAvailable?: boolean | null;
  displayUnavailableReason?: string | null;
  absolute?: boolean;
  showRawWhenConverted?: boolean;
  formatOptions?: Intl.NumberFormatOptions;
  primaryClassName?: string;
  unavailableClassName?: string;
  secondaryClassName?: string;
}
```

```tsx
// frontend/src/components/TransactionList.tsx
<DisplayMoney
  rawAmount={transaction.amount}
  rawCurrency={transaction.currency}
  displayAmount={transaction.display_amount}
  displayCurrency={transaction.display_currency}
  displayIsAvailable={transaction.display_is_available}
  displayUnavailableReason={transaction.display_unavailable_reason}
  absolute
  primaryClassName="font-medium"
  unavailableClassName="font-medium text-amber-700 dark:text-amber-300"
  secondaryClassName="text-[11px] text-gray-500 dark:text-gray-400"
/>
```

```tsx
// frontend/src/components/imports/ImportReviewPage.tsx
<DisplayMoney
  rawAmount={transaction.signed_amount}
  rawCurrency={transaction.currency}
  displayAmount={transaction.display_amount}
  displayCurrency={transaction.display_currency}
  displayIsAvailable={transaction.display_is_available}
  displayUnavailableReason={transaction.display_unavailable_reason}
  primaryClassName="text-gray-900 dark:text-gray-200"
  unavailableClassName="font-medium text-amber-700 dark:text-amber-300"
  secondaryClassName="text-xs text-gray-500 dark:text-gray-400"
/>
```

- [ ] **Step 5: Re-run the frontend line-item tests**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand src/components/common/DisplayMoney.test.tsx src/components/TransactionList.test.tsx src/components/imports/ImportReviewPage.test.tsx src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected: PASS with explicit unavailable-state rendering across transactions, import review, and the AI modal.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/transaction.ts frontend/src/types/import.ts frontend/src/utils/currency.ts frontend/src/components/common/DisplayMoney.tsx frontend/src/components/common/DisplayMoney.test.tsx frontend/src/components/TransactionList.tsx frontend/src/components/TransactionList.test.tsx frontend/src/components/imports/ImportReviewPage.tsx frontend/src/components/imports/ImportReviewPage.test.tsx frontend/src/components/transactions/ClassificationAssistantModal.tsx frontend/src/components/transactions/ClassificationAssistantModal.test.tsx
git commit -m "feat: surface explicit line item fx availability"
```

### Task 3: Replace Financial Overview, Transfer Summary, And Timeseries With Raw-Transaction Reporting-Currency Aggregation

**Files:**
- Create: `backend/app/services/reporting_currency_analytics.py`
- Create: `backend/tests/services/test_reporting_currency_analytics.py`
- Create: `backend/tests/test_statistics_api.py`
- Modify: `backend/app/schemas/statistics.py`
- Modify: `backend/app/routers/statistics.py`

- [ ] **Step 1: Write the failing service and API tests for financial aggregates**

```python
def test_build_financial_timeseries_excludes_unconvertible_rows_from_totals_but_reports_them(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    _create_transaction(
        db_session,
        description="Salary",
        amount=5000.0,
        transaction_type=TransactionType.INCOME,
        income_category=IncomeCategory.SALARY,
    )
    unsupported = _create_transaction(
        db_session,
        description="Unsupported token fee",
        amount=-15.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.FINANCIAL_FEES,
    )
    unsupported.currency = "NEXO"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_financial_timeseries(
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        reporting_currency="USD",
    )

    assert payload["reporting_currency"] == "USD"
    assert payload["conversion_summary"]["converted_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_transaction_count"] == 1
    assert payload["conversion_summary"]["unavailable_currencies"] == ["NEXO"]
    assert payload["items"][0]["period_income"] == 6000.0
    assert payload["items"][0]["period_expenses"] == 0.0
```

```python
def test_statistics_timeseries_endpoint_returns_wrapper_payload(client, db_session):
    response = client.get("/statistics/timeseries", headers={"X-Reporting-Currency": "USD"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["reporting_currency"] == "USD"
    assert "conversion_summary" in payload
    assert "items" in payload
```

- [ ] **Step 2: Run the failing financial aggregate tests**

Run:

```bash
cd backend && pytest tests/services/test_reporting_currency_analytics.py tests/test_statistics_api.py -k "financial or overview or timeseries or transfer" -v
```

Expected: FAIL because the service file does not exist and `/statistics/timeseries` still returns a raw list built from `FinancialStatistics`.

- [ ] **Step 3: Implement the raw-transaction financial aggregation service**

```python
# backend/app/services/reporting_currency_analytics.py
@dataclass
class ConversionSummary:
    converted_transaction_count: int = 0
    unavailable_transaction_count: int = 0
    unavailable_currencies: set[str] = field(default_factory=set)

    def record(self, display_money: DisplayMoney, raw_currency: str) -> None:
        if display_money.is_available and display_money.display_amount is not None:
            self.converted_transaction_count += 1
            return
        self.unavailable_transaction_count += 1
        self.unavailable_currencies.add(raw_currency.strip().upper())

    def as_payload(self) -> dict[str, Any]:
        return {
            "converted_transaction_count": self.converted_transaction_count,
            "unavailable_transaction_count": self.unavailable_transaction_count,
            "unavailable_currencies": sorted(self.unavailable_currencies),
        }


class ReportingCurrencyAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.conversion_service = CurrencyConversionService(db)

    @staticmethod
    def resolve_reporting_window(
        *,
        db: Session,
        start_date: str | None,
        end_date: str | None,
        time_period: TimePeriod | None,
    ) -> tuple[date, date]:
        latest_transaction = db.query(func.max(Transaction.transaction_date)).scalar() or date.today()
        reference_date = latest_transaction.replace(
            day=calendar.monthrange(latest_transaction.year, latest_transaction.month)[1]
        )
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else reference_date
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        elif time_period == TimePeriod.THREE_MONTHS:
            start = (reference_date - relativedelta(months=3)).replace(day=1)
        elif time_period == TimePeriod.SIX_MONTHS:
            start = (reference_date - relativedelta(months=6)).replace(day=1)
        elif time_period == TimePeriod.YEAR_TO_DATE:
            start = date(reference_date.year, 1, 1)
        elif time_period == TimePeriod.ONE_YEAR:
            start = (reference_date - relativedelta(years=1)).replace(day=1)
        elif time_period == TimePeriod.TWO_YEARS:
            start = (reference_date - relativedelta(years=2)).replace(day=1)
        else:
            start = db.query(func.min(Transaction.transaction_date)).scalar() or reference_date
        return start, end

    def _converted_transactions(
        self,
        transactions: list[Transaction],
        reporting_currency: str,
        summary: ConversionSummary,
    ) -> list[tuple[Transaction, DisplayMoney]]:
        converted: list[tuple[Transaction, DisplayMoney]] = []
        for transaction in transactions:
            display_money = self.conversion_service.convert(
                raw_amount=transaction.amount,
                raw_currency=transaction.currency,
                reporting_currency=reporting_currency,
                transaction_date=transaction.transaction_date,
            )
            summary.record(display_money, transaction.currency)
            converted.append((transaction, display_money))
        return converted

    def _month_ends_between(self, start: date, end: date) -> list[date]:
        cursor = start.replace(day=1)
        month_ends: list[date] = []
        while cursor <= end:
            month_ends.append(cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1]))
            cursor = (cursor + relativedelta(months=1)).replace(day=1)
        return month_ends

    def _financial_month_item(self, month_end: date, reporting_currency: str, summary: ConversionSummary) -> dict[str, Any]:
        transactions = self.db.query(Transaction).filter(
            extract("year", Transaction.transaction_date) == month_end.year,
            extract("month", Transaction.transaction_date) == month_end.month,
        ).all()
        income_total = Decimal("0")
        expense_total = Decimal("0")
        income_count = 0
        expense_count = 0
        for transaction, display_money in self._converted_transactions(transactions, reporting_currency, summary):
            if transaction.transaction_type == TransactionType.INCOME:
                income_count += 1
                if display_money.is_available and display_money.display_amount is not None:
                    income_total += Decimal(str(display_money.display_amount))
            elif transaction.transaction_type == TransactionType.EXPENSE:
                expense_count += 1
                if display_money.is_available and display_money.display_amount is not None:
                    expense_total += abs(Decimal(str(display_money.display_amount)))
        net = income_total - expense_total
        return {
            "period": StatisticsPeriod.MONTHLY.value,
            "date": month_end.isoformat(),
            "period_income": float(income_total),
            "period_expenses": float(expense_total),
            "period_net_savings": float(net),
            "savings_rate": float(net / income_total * 100) if income_total > 0 else 0.0,
            "total_income": float(income_total),
            "total_expenses": float(expense_total),
            "total_net_savings": float(net),
            "income_count": income_count,
            "expense_count": expense_count,
            "average_income": float(income_total / income_count) if income_count else 0.0,
            "average_expense": float(expense_total / expense_count) if expense_count else 0.0,
            "yearly_income": float(income_total),
            "yearly_expenses": float(expense_total),
        }

    def build_financial_timeseries(self, *, start: date, end: date, reporting_currency: str) -> dict[str, Any]:
        months = self._month_ends_between(start, end)
        summary = ConversionSummary()
        items = [self._financial_month_item(month_end, reporting_currency, summary) for month_end in months]
        return {
            "reporting_currency": reporting_currency,
            "conversion_summary": summary.as_payload(),
            "items": items,
        }
```

- [ ] **Step 4: Switch the scoped financial endpoints to the new service and wrapper schemas**

```python
# backend/app/schemas/statistics.py
class ConversionSummaryResponse(BaseModel):
    converted_transaction_count: int
    unavailable_transaction_count: int
    unavailable_currencies: List[str]


class FinancialStatisticsTimeseriesItemResponse(BaseModel):
    period: str
    date: str | None = None
    period_income: float
    period_expenses: float
    period_net_savings: float
    savings_rate: float
    total_income: float
    total_expenses: float
    total_net_savings: float
    income_count: int
    expense_count: int
    average_income: float
    average_expense: float
    yearly_income: float
    yearly_expenses: float


class FinancialStatisticsTimeseriesResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[FinancialStatisticsTimeseriesItemResponse]
```

```python
# backend/app/routers/statistics.py
@router.get("/timeseries", response_model=FinancialStatisticsTimeseriesResponse)
def get_statistics_timeseries(
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
    start_date: str = Query(None),
    end_date: str = Query(None),
    time_period: TimePeriod = Query(None),
):
    start, end = ReportingCurrencyAnalyticsService.resolve_reporting_window(
        db=db,
        start_date=start_date,
        end_date=end_date,
        time_period=time_period,
    )
    service = ReportingCurrencyAnalyticsService(db)
    return service.build_financial_timeseries(
        start=start,
        end=end,
        reporting_currency=reporting_currency,
    )
```

- [ ] **Step 5: Re-run the financial aggregate tests**

Run:

```bash
cd backend && pytest tests/services/test_reporting_currency_analytics.py tests/test_statistics_api.py -k "financial or overview or timeseries or transfer" -v
```

Expected: PASS for `/statistics/overview`, `/statistics/transfers/summary`, and `/statistics/timeseries` using selected-currency raw aggregation plus `conversion_summary`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/reporting_currency_analytics.py backend/app/schemas/statistics.py backend/app/routers/statistics.py backend/tests/services/test_reporting_currency_analytics.py backend/tests/test_statistics_api.py
git commit -m "feat: add reporting currency financial analytics"
```

### Task 4: Replace Category And Expense-Type Analytics With Raw-Transaction Aggregation

**Files:**
- Modify: `backend/app/services/reporting_currency_analytics.py`
- Modify: `backend/app/schemas/statistics.py`
- Modify: `backend/app/routers/statistics.py`
- Modify: `backend/tests/services/test_reporting_currency_analytics.py`
- Modify: `backend/tests/test_statistics_api.py`

- [ ] **Step 1: Write the failing category and expense-type aggregate tests**

```python
def test_category_breakdown_uses_converted_raw_transactions_instead_of_persisted_eur_rows(db_session):
    _store_rate(
        db_session,
        rate_date=date(2026, 3, 31),
        quoted_currency="USD",
        units_per_base="1.2000",
    )
    groceries = _create_transaction(
        db_session,
        description="Groceries",
        amount=-100.0,
        transaction_type=TransactionType.EXPENSE,
        expense_category=ExpenseCategory.GROCERIES,
    )
    groceries.currency = "EUR"
    db_session.commit()

    payload = ReportingCurrencyAnalyticsService(db_session).build_category_breakdown(
        period=StatisticsPeriod.MONTHLY,
        target_date=date(2026, 3, 31),
        reporting_currency="USD",
    )

    groceries_item = next(item for item in payload["items"] if item["category"] == "Groceries")
    assert groceries_item["period_amount"] == 120.0
    assert payload["reporting_currency"] == "USD"
```

```python
def test_expense_type_timeseries_endpoint_returns_wrapper_payload(client, db_session):
    response = client.get("/statistics/expense-type/timeseries", headers={"X-Reporting-Currency": "BRL"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["reporting_currency"] == "BRL"
    assert "conversion_summary" in payload
    assert isinstance(payload["items"], list)
```

- [ ] **Step 2: Run the failing category and expense-type tests**

Run:

```bash
cd backend && pytest tests/services/test_reporting_currency_analytics.py tests/test_statistics_api.py -k "category or expense_type or averages" -v
```

Expected: FAIL because `/statistics/by-category`, `/statistics/by-expense-type`, `/statistics/category/averages`, `/statistics/category/timeseries`, and `/statistics/expense-type/timeseries` still read `CategoryStatistics` rows directly.

- [ ] **Step 3: Add raw-transaction category and expense-type aggregation methods**

```python
# backend/app/services/reporting_currency_analytics.py
def build_category_breakdown(
    self,
    *,
    period: StatisticsPeriod,
    target_date: date | None,
    reporting_currency: str,
) -> dict[str, Any]:
    transactions = self._transactions_for_period(period=period, target_date=target_date)
    summary = ConversionSummary()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for transaction, display_money in self._converted_transactions(transactions, reporting_currency, summary):
        if transaction.transaction_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
            continue
        category_name = self._category_name_for(transaction)
        key = (category_name, transaction.transaction_type.value)
        bucket = grouped.setdefault(key, self._empty_category_bucket(transaction))
        if display_money.is_available and display_money.display_amount is not None:
            bucket["period_amount"] += abs(float(display_money.display_amount))
        bucket["period_transaction_count"] += 1

    items = self._finalize_category_percentages(grouped)
    return {
        "reporting_currency": reporting_currency,
        "conversion_summary": summary.as_payload(),
        "items": items,
    }


def _transactions_for_period(self, *, period: StatisticsPeriod, target_date: date | None) -> list[Transaction]:
    query = self.db.query(Transaction)
    if period == StatisticsPeriod.MONTHLY and target_date is not None:
        query = query.filter(
            extract("year", Transaction.transaction_date) == target_date.year,
            extract("month", Transaction.transaction_date) == target_date.month,
        )
    elif period == StatisticsPeriod.YEARLY and target_date is not None:
        query = query.filter(extract("year", Transaction.transaction_date) == target_date.year)
    return query.all()


def _transactions_for_month(self, month_end: date) -> list[Transaction]:
    return self.db.query(Transaction).filter(
        extract("year", Transaction.transaction_date) == month_end.year,
        extract("month", Transaction.transaction_date) == month_end.month,
    ).all()


def _category_name_for(self, transaction: Transaction) -> str:
    if transaction.transaction_type == TransactionType.EXPENSE and transaction.expense_category:
        return transaction.expense_category.value
    if transaction.transaction_type == TransactionType.INCOME and transaction.income_category:
        return transaction.income_category.value
    if transaction.transaction_type == TransactionType.TRANSFER and transaction.transfer_category:
        return transaction.transfer_category.value
    return "Uncategorized"


def _empty_category_bucket(self, transaction: Transaction) -> dict[str, Any]:
    expense_type = (
        transaction.expense_category.expense_type.value
        if transaction.transaction_type == TransactionType.EXPENSE and transaction.expense_category
        else None
    )
    return {
        "category": self._category_name_for(transaction),
        "transaction_type": transaction.transaction_type.value,
        "expense_type": expense_type,
        "period_amount": 0.0,
        "period_transaction_count": 0,
        "period_percentage": 0.0,
        "total_amount": 0.0,
        "transaction_count": 0,
        "total_amount_cumulative": 0.0,
        "total_transaction_count": 0,
        "average_transaction_amount": 0.0,
        "yearly_amount": 0.0,
        "yearly_transaction_count": 0,
    }


def _finalize_category_percentages(self, grouped: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    expense_total = sum(
        bucket["period_amount"] for bucket in grouped.values() if bucket["transaction_type"] == TransactionType.EXPENSE.value
    )
    income_total = sum(
        bucket["period_amount"] for bucket in grouped.values() if bucket["transaction_type"] == TransactionType.INCOME.value
    )
    for bucket in grouped.values():
        total = expense_total if bucket["transaction_type"] == TransactionType.EXPENSE.value else income_total
        bucket["period_percentage"] = (bucket["period_amount"] / total * 100) if total > 0 else 0.0
        bucket["total_amount"] = bucket["period_amount"]
        bucket["transaction_count"] = bucket["period_transaction_count"]
        bucket["total_amount_cumulative"] = bucket["period_amount"]
        bucket["total_transaction_count"] = bucket["period_transaction_count"]
        bucket["average_transaction_amount"] = (
            bucket["period_amount"] / bucket["period_transaction_count"]
            if bucket["period_transaction_count"]
            else 0.0
        )
        bucket["yearly_amount"] = bucket["period_amount"]
        bucket["yearly_transaction_count"] = bucket["period_transaction_count"]
    return list(grouped.values())
```

```python
def build_expense_type_timeseries(self, *, start: date, end: date, reporting_currency: str) -> dict[str, Any]:
    summary = ConversionSummary()
    items: list[dict[str, Any]] = []
    for month_end in self._month_ends_between(start, end):
        monthly_transactions = self._transactions_for_month(month_end)
        by_expense_type = self._group_month_by_expense_type(monthly_transactions, reporting_currency, summary)
        items.extend(by_expense_type)
    return {
        "reporting_currency": reporting_currency,
        "conversion_summary": summary.as_payload(),
        "items": items,
    }


def _group_month_by_expense_type(
    self,
    transactions: list[Transaction],
    reporting_currency: str,
    summary: ConversionSummary,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for transaction, display_money in self._converted_transactions(transactions, reporting_currency, summary):
        if transaction.transaction_type != TransactionType.EXPENSE or not transaction.expense_category:
            continue
        expense_type = transaction.expense_category.expense_type.value
        bucket = buckets.setdefault(
            expense_type,
            {
                "date": transaction.transaction_date.replace(
                    day=calendar.monthrange(transaction.transaction_date.year, transaction.transaction_date.month)[1]
                ).isoformat(),
                "expense_type": expense_type,
                "period_amount": 0.0,
                "period_transaction_count": 0,
            },
        )
        if display_money.is_available and display_money.display_amount is not None:
            bucket["period_amount"] += abs(float(display_money.display_amount))
        bucket["period_transaction_count"] += 1
    return list(buckets.values())
```

- [ ] **Step 4: Update the category and expense-type schemas and routers to use wrapper payloads**

```python
# backend/app/schemas/statistics.py
class CategoryStatisticsListResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[CategoryStatisticsResponse]


class ExpenseTypeStatisticsResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    items: List[dict[str, Any]]


class CategoryAveragesResponse(BaseModel):
    reporting_currency: str
    conversion_summary: ConversionSummaryResponse
    start_date: str
    end_date: str
    months_count: int
    categories: List[CategoryAverageItem]
```

```python
# backend/app/routers/statistics.py
@router.get("/by-category", response_model=CategoryStatisticsListResponse)
def get_category_statistics(
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
    period: str = Query("monthly"),
    date: str = Query(None),
):
    stat_period = StatisticsPeriod(period)
    latest_transaction = db.query(Transaction).order_by(Transaction.transaction_date.desc()).first()
    target_date = (
        datetime.strptime(date, "%Y-%m-%d").date()
        if date
        else (latest_transaction.transaction_date if latest_transaction else None)
    )
    service = ReportingCurrencyAnalyticsService(db)
    return service.build_category_breakdown(
        period=stat_period,
        target_date=target_date,
        reporting_currency=reporting_currency,
    )


@router.get("/expense-type/timeseries", response_model=ExpenseTypeStatisticsResponse)
def get_expense_type_statistics_timeseries(
    db: Session = Depends(get_db),
    reporting_currency: str = Depends(get_reporting_currency),
    expense_type: ExpenseType = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    time_period: TimePeriod = Query(None),
):
    start, end = ReportingCurrencyAnalyticsService.resolve_reporting_window(
        db=db,
        start_date=start_date,
        end_date=end_date,
        time_period=time_period,
    )
    service = ReportingCurrencyAnalyticsService(db)
    return service.build_expense_type_timeseries(
        start=start,
        end=end,
        reporting_currency=reporting_currency,
    )
```

- [ ] **Step 5: Re-run the category and expense-type tests**

Run:

```bash
cd backend && pytest tests/services/test_reporting_currency_analytics.py tests/test_statistics_api.py -k "category or expense_type or averages" -v
```

Expected: PASS for every scoped category/expense endpoint using raw transactions, selected-currency totals, and explicit partial-conversion metadata.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/reporting_currency_analytics.py backend/app/schemas/statistics.py backend/app/routers/statistics.py backend/tests/services/test_reporting_currency_analytics.py backend/tests/test_statistics_api.py
git commit -m "feat: convert category analytics to reporting currency"
```

### Task 5: Update Frontend Statistics Types, Hooks, And Scoped Dashboard Components

**Files:**
- Create: `frontend/src/types/statistics.ts`
- Create: `frontend/src/components/dashboard/ConversionSummaryNotice.tsx`
- Create: `frontend/src/components/dashboard/CategoryTrends.test.tsx`
- Modify: `frontend/src/services/statisticService.ts`
- Modify: `frontend/src/hooks/useStatistics.ts`
- Modify: `frontend/src/hooks/useStatisticsTimeseries.ts`
- Modify: `frontend/src/hooks/useCategoryTimeseries.ts`
- Modify: `frontend/src/hooks/useExpenseTypeStatistics.ts`
- Modify: `frontend/src/hooks/useExpenseTypeTimeseries.ts`
- Modify: `frontend/src/components/dashboard/FinancialOverview.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.tsx`
- Modify: `frontend/src/components/dashboard/CategoryBreakdown.tsx`
- Modify: `frontend/src/components/dashboard/CategoryTrends.tsx`
- Modify: `frontend/src/components/dashboard/CategoryAverages.tsx`
- Modify: `frontend/src/components/dashboard/CategoryTimeseriesChart.tsx`
- Modify: `frontend/src/components/dashboard/ExpenseTypeTimeseriesChart.tsx`
- Modify: `frontend/src/components/dashboard/TimeseriesChart.tsx`
- Modify: `frontend/src/components/dashboard/MonthlyHeatmap.tsx`
- Modify: `frontend/src/components/dashboard/MonthlyHeatmap.test.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.test.tsx`

- [ ] **Step 1: Write the failing dashboard tests that prove scoped surfaces still behave like fixed-EUR views**

```tsx
test('MonthlyHeatmap formats timeseries values in the selected reporting currency', async () => {
  window.localStorage.setItem('reporting_currency', 'USD');
  mockedGetStatisticsTimeseries.mockResolvedValueOnce({
    reporting_currency: 'USD',
    conversion_summary: {
      converted_transaction_count: 1,
      unavailable_transaction_count: 0,
      unavailable_currencies: [],
    },
    items: [
      {
        period: 'monthly',
        date: '2026-03-31',
        period_income: 1200,
        period_expenses: 300,
        period_net_savings: 900,
        savings_rate: 75,
        total_income: 1200,
        total_expenses: 300,
        total_net_savings: 900,
        income_count: 1,
        expense_count: 1,
        average_income: 1200,
        average_expense: 300,
        yearly_income: 1200,
        yearly_expenses: 300,
      },
    ],
  } as never);

  const { container } = renderMonthlyHeatmap();

  await waitFor(() => {
    const marchCell = container.querySelector('[title^="March 2026"]') as HTMLElement;
    expect(marchCell.title).toContain('Income: $1,200.00');
    expect(marchCell.title).not.toContain('€');
  });
});
```

```tsx
test('CategoryTrends uses one formatter across both tabs and shows a partial-data warning', async () => {
  render(
    <ReportingCurrencyProvider>
      <CategoryTrends />
    </ReportingCurrencyProvider>
  );

  expect(await screen.findByText(/some totals exclude unsupported currencies/i)).toBeInTheDocument();
  expect(screen.getAllByText(/\$1,200\.00/).length).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run the failing dashboard tests**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand src/components/dashboard/MonthlyHeatmap.test.tsx src/components/dashboard/TransferSummary.test.tsx src/components/dashboard/CategoryTrends.test.tsx
```

Expected: FAIL because the service and hooks still expect raw arrays and the scoped components still format several surfaces with `PERSISTED_STATISTICS_CURRENCY`.

- [ ] **Step 3: Introduce shared statistics response types and unwrap the new backend payloads in the hooks**

```ts
// frontend/src/types/statistics.ts
export interface ConversionSummary {
  converted_transaction_count: number;
  unavailable_transaction_count: number;
  unavailable_currencies: string[];
}

export interface TimeseriesResponse<TItem> {
  reporting_currency: string;
  conversion_summary: ConversionSummary;
  items: TItem[];
}

export interface StatisticsOverviewItem {
  period: string;
  date: string | null;
  reporting_currency: string;
  conversion_summary: ConversionSummary;
  period_income: number;
  period_expenses: number;
  period_net_savings: number;
  savings_rate: number;
  total_income: number;
  total_expenses: number;
  total_net_savings: number;
  income_count: number;
  expense_count: number;
  average_income: number;
  average_expense: number;
  yearly_income: number;
  yearly_expenses: number;
}
```

```ts
// frontend/src/hooks/useStatisticsTimeseries.ts
const [conversionSummary, setConversionSummary] = useState<ConversionSummary | null>(null);
const [reportingCurrency, setReportingCurrency] = useState<string | null>(null);

const data = await statisticService.getStatisticsTimeseries(start_date, end_date, time_period);
setReportingCurrency(data.reporting_currency);
setConversionSummary(data.conversion_summary);
setTimeseriesData(
  data.items.map((item) => ({
    date: item.date,
    period_income: Number(item.period_income) || 0,
    period_expenses: Number(item.period_expenses) || 0,
    period_net_savings: Number(item.period_net_savings) || 0,
    savings_rate: Number(item.savings_rate) || 0,
    total_income: Number(item.total_income) || 0,
    total_expenses: Number(item.total_expenses) || 0,
    total_net_savings: Number(item.total_net_savings) || 0,
  }))
);
```

- [ ] **Step 4: Add a shared partial-data banner and switch every scoped dashboard formatter to the reporting-currency-aware response**

```tsx
// frontend/src/components/dashboard/ConversionSummaryNotice.tsx
export const ConversionSummaryNotice: React.FC<{ summary?: ConversionSummary | null }> = ({ summary }) => {
  if (!summary || summary.unavailable_transaction_count === 0) {
    return null;
  }

  const currencies = summary.unavailable_currencies.join(', ');
  return (
    <p className="text-sm text-amber-700 dark:text-amber-300">
      Some totals exclude unsupported currencies: {currencies}.
    </p>
  );
};
```

```tsx
// frontend/src/components/dashboard/CategoryTrends.tsx
const { timeseriesData, reportingCurrency, conversionSummary } = useStatisticsTimeseries(
  startDate,
  endDate,
  selectedTimePeriod
);

const formatReportingCurrency = (value: number) =>
  formatMoney(value, reportingCurrency ?? statistics.current_month.reporting_currency, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

<ConversionSummaryNotice summary={conversionSummary} />
```

```tsx
// frontend/src/components/dashboard/MonthlyHeatmap.tsx
const formatCurrency = (value: number) => formatMoney(value, reportingCurrency ?? 'EUR');
```

- [ ] **Step 5: Re-run the dashboard tests and verify the scoped fixed-EUR fallback is gone**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand src/components/dashboard/MonthlyHeatmap.test.tsx src/components/dashboard/TransferSummary.test.tsx src/components/dashboard/CategoryTrends.test.tsx
```

Run:

```bash
rg -n "PERSISTED_STATISTICS_CURRENCY" frontend/src/components/dashboard/FinancialOverview.tsx frontend/src/components/dashboard/TransferSummary.tsx frontend/src/components/dashboard/CategoryBreakdown.tsx frontend/src/components/dashboard/CategoryTrends.tsx frontend/src/components/dashboard/CategoryAverages.tsx frontend/src/components/dashboard/CategoryTimeseriesChart.tsx frontend/src/components/dashboard/ExpenseTypeTimeseriesChart.tsx frontend/src/components/dashboard/TimeseriesChart.tsx frontend/src/components/dashboard/MonthlyHeatmap.tsx
```

Expected: tests PASS, and the `rg` command returns no matches in scoped dashboard files.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/statistics.ts frontend/src/components/dashboard/ConversionSummaryNotice.tsx frontend/src/components/dashboard/CategoryTrends.test.tsx frontend/src/services/statisticService.ts frontend/src/hooks/useStatistics.ts frontend/src/hooks/useStatisticsTimeseries.ts frontend/src/hooks/useCategoryTimeseries.ts frontend/src/hooks/useExpenseTypeStatistics.ts frontend/src/hooks/useExpenseTypeTimeseries.ts frontend/src/components/dashboard/FinancialOverview.tsx frontend/src/components/dashboard/TransferSummary.tsx frontend/src/components/dashboard/CategoryBreakdown.tsx frontend/src/components/dashboard/CategoryTrends.tsx frontend/src/components/dashboard/CategoryAverages.tsx frontend/src/components/dashboard/CategoryTimeseriesChart.tsx frontend/src/components/dashboard/ExpenseTypeTimeseriesChart.tsx frontend/src/components/dashboard/TimeseriesChart.tsx frontend/src/components/dashboard/MonthlyHeatmap.tsx frontend/src/components/dashboard/MonthlyHeatmap.test.tsx frontend/src/components/dashboard/TransferSummary.test.tsx
git commit -m "feat: remove scoped fixed-eur analytics formatting"
```

### Task 6: Final Cleanup And Verification Sweep

**Files:**
- Modify: `frontend/src/utils/currency.ts`

- [ ] **Step 1: Narrow the legacy EUR constant to explicitly out-of-scope usage**

```ts
// frontend/src/utils/currency.ts
// Retained only for out-of-scope legacy screens. Scoped reporting-currency surfaces must not import this.
export const PERSISTED_STATISTICS_CURRENCY = 'EUR';

export const formatMoney = (
  amount: number,
  currency: string,
  options: Intl.NumberFormatOptions = {}
): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...options,
  }).format(amount);
```

- [ ] **Step 2: Run the scoped backend verification suite**

Run:

```bash
cd backend && pytest tests/services/test_currency_conversion.py tests/services/test_reporting_currency_statistics.py tests/services/test_reporting_currency_analytics.py tests/test_transaction_listing.py tests/test_classification_api.py tests/test_statistics_api.py tests/imports/test_import_review_api.py -v
```

Expected: PASS for currency conversion, line-item APIs, raw-transaction analytics, and import review.

- [ ] **Step 3: Run the scoped frontend verification suite**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand src/components/common/DisplayMoney.test.tsx src/components/TransactionList.test.tsx src/components/imports/ImportReviewPage.test.tsx src/components/transactions/ClassificationAssistantModal.test.tsx src/components/dashboard/MonthlyHeatmap.test.tsx src/components/dashboard/TransferSummary.test.tsx src/components/dashboard/CategoryTrends.test.tsx
```

Expected: PASS for line-item money rendering, dashboard reporting-currency formatting, and partial-data warnings.

- [ ] **Step 4: Run the final grep checks for legacy scoped behavior**

Run:

```bash
rg -n "PERSISTED_STATISTICS_CURRENCY" frontend/src/components/dashboard frontend/src/hooks
```

Expected: either no matches, or matches only in explicitly out-of-scope files that are not part of this plan. There must be no matches in the scoped files listed in the spec.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/currency.ts
git commit -m "chore: document remaining out-of-scope eur fallback"
```
