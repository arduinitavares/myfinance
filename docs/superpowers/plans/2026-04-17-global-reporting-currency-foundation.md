# Global Reporting Currency Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a global, persisted reporting-currency system (`EUR`/`USD`/`BRL`) that converts transaction, import-review, AI-modal, and analytics displays from immutable raw ledger values using ECB historical daily rates.

**Architecture:** Keep raw transaction and import-draft values unchanged, add a dedicated FX reference-rate table plus a single backend conversion service, and return additive display fields to the frontend. The frontend owns the global reporting-currency preference and request propagation, but it never performs FX math itself.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite runtime migrations, Pydantic, APScheduler, React, TypeScript, axios, React Testing Library, Jest

---

## File Map

### Backend files to create

- `backend/app/models/fx.py`
  - SQLAlchemy model for `fx_daily_reference_rates`
- `backend/app/services/reporting_currency.py`
  - Header parsing and validation for `X-Reporting-Currency`
- `backend/app/services/ecb_exchange_rates.py`
  - ECB fetcher, seed, and refresh logic
- `backend/app/services/currency_conversion.py`
  - Pairwise conversion, fallback rate lookup, `display_rate_date`, Decimal rounding
- `backend/app/services/fx_refresh_scheduler.py`
  - APScheduler wrapper for daily `02:00 UTC` refresh
- `backend/tests/services/test_reporting_currency.py`
  - Header validation tests
- `backend/tests/services/test_currency_conversion.py`
  - Conversion math, fallback, and precision tests
- `backend/tests/services/test_ecb_exchange_rates.py`
  - Seed/refresh idempotency and non-working-day gap tests
- `frontend/src/contexts/ReportingCurrencyContext.tsx`
  - Global reporting-currency state and localStorage persistence
- `frontend/src/services/apiClient.ts`
  - Shared axios instance that injects `X-Reporting-Currency`
- `frontend/src/utils/currency.ts`
  - Shared formatter for display money fields
- `frontend/src/contexts/ReportingCurrencyContext.test.tsx`
  - Preference persistence and provider behavior tests

### Backend files to modify

- `backend/app/database_manager.py`
  - Ensure FX table exists, run seed/catch-up, start scheduler safely
- `backend/app/main.py`
  - Register scheduler startup/shutdown hooks
- `backend/app/models/transaction.py`
  - Import new FX model module via metadata registration if needed
- `backend/app/schemas/transaction.py`
  - Add `display_amount`, `display_currency`, `display_fx_rate`, `display_rate_date`
- `backend/app/schemas/imports.py`
  - Add display fields to draft row responses
- `backend/app/schemas/statistics.py`
  - Replace `_eur` response fields with currency-neutral names and `reporting_currency`
- `backend/app/routers/transactions.py`
  - Resolve reporting currency and emit display fields
- `backend/app/routers/imports.py`
  - Resolve reporting currency and emit display fields in review payloads
- `backend/app/routers/statistics.py`
  - Resolve reporting currency and route through conversion service
- `backend/app/services/statistics_service.py`
  - Aggregate in Python after conversion, not in ad hoc SQL FX expressions
- `backend/tests/test_transaction_listing.py`
  - Add display-field coverage and invalid-header error case
- `backend/tests/imports/test_import_review_api.py`
  - Verify display fields and reporting currency behavior in review payloads
- `backend/tests/test_transfer_analytics.py`
  - Update transfer summary expectations to currency-neutral fields

### Frontend files to modify

- `frontend/src/App.tsx`
  - Wrap app in reporting-currency provider
- `frontend/src/layouts/MainLayout.tsx`
  - Render global reporting-currency dropdown in app chrome
- `frontend/src/services/transactionService.ts`
  - Switch from raw `axios` import to shared `apiClient`
- `frontend/src/services/importService.ts`
  - Switch from raw `axios` import to shared `apiClient`
- `frontend/src/services/statisticService.ts`
  - Switch from raw `axios` import to shared `apiClient`, rename aggregate response fields
- `frontend/src/services/classificationService.ts`
  - Switch from raw `axios` import to shared `apiClient`
- `frontend/src/types/transaction.ts`
  - Add display-money fields and reporting-currency-aware aggregate fields
- `frontend/src/types/import.ts`
  - Add display-money fields for import drafts
- `frontend/src/components/TransactionList.tsx`
  - Render `display_amount` / `display_currency`
- `frontend/src/components/imports/ImportReviewPage.tsx`
  - Render converted draft amounts
- `frontend/src/components/transactions/ClassificationAssistantModal.tsx`
  - Render converted transaction amount
- `frontend/src/components/dashboard/FinancialOverview.tsx`
  - Read `reporting_currency` and currency-neutral amount fields
- `frontend/src/components/dashboard/TransferSummary.tsx`
  - Read `reporting_currency` and currency-neutral amount fields
- `frontend/src/components/dashboard/CategoryBreakdown.tsx`
  - Use reporting currency-aware responses
- `frontend/src/components/dashboard/CategoryTrends.tsx`
  - Use reporting currency-aware responses
- `frontend/src/components/dashboard/FinancialTrends.tsx`
  - Use reporting currency-aware responses
- `frontend/src/components/dashboard/CategoryAverages.tsx`
  - Use reporting currency-aware responses
- `frontend/src/components/dashboard/MonthlyHeatmap.tsx`
  - Verify display handling for currency-bearing tooltips/labels
- `frontend/src/components/dashboard/projections/ProjectionDashboard.tsx`
  - Use reporting currency-aware values if the API already exposes money fields
- `frontend/src/components/dashboard/anomalies/AnomalyDashboard.tsx`
  - Use reporting currency-aware values if the API already exposes money fields
- `frontend/src/components/imports/ImportReviewPage.test.tsx`
- `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`
- `frontend/src/components/dashboard/TransferSummary.test.tsx`
- `frontend/src/components/FileUpload.test.tsx`

---

### Task 1: Add FX storage and reporting-currency plumbing

**Files:**
- Create: `backend/app/models/fx.py`
- Create: `backend/app/services/reporting_currency.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/services/test_reporting_currency.py`

- [ ] **Step 1: Write the failing header-validation tests**

```python
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.services.reporting_currency import get_reporting_currency


def test_reporting_currency_defaults_to_eur():
    app = FastAPI()

    @app.get("/probe")
    def probe(currency: str = Depends(get_reporting_currency)):
        return {"currency": currency}

    client = TestClient(app)
    assert client.get("/probe").json() == {"currency": "EUR"}


def test_reporting_currency_rejects_invalid_header():
    app = FastAPI()

    @app.get("/probe")
    def probe(currency: str = Depends(get_reporting_currency)):
        return {"currency": currency}

    client = TestClient(app)
    response = client.get("/probe", headers={"X-Reporting-Currency": "CAD"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "error": "invalid_reporting_currency",
            "allowed": ["EUR", "USD", "BRL"],
        }
    }
```

- [ ] **Step 2: Run the header-validation tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_reporting_currency.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.services.reporting_currency'
```

- [ ] **Step 3: Add the model and header parser**

```python
# backend/app/models/fx.py
from sqlalchemy import Column, Date, Integer, String, UniqueConstraint
from sqlalchemy.types import Numeric, DateTime

from ..database import Base


class FxDailyReferenceRate(Base):
    __tablename__ = "fx_daily_reference_rates"

    id = Column(Integer, primary_key=True, index=True)
    rate_date = Column(Date, nullable=False, index=True)
    base_currency = Column(String(3), nullable=False)
    quoted_currency = Column(String(3), nullable=False)
    units_per_base = Column(Numeric(18, 8), nullable=False)
    source_name = Column(String(32), nullable=False)
    fetched_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "rate_date",
            "base_currency",
            "quoted_currency",
            "source_name",
            name="uq_fx_daily_reference_rates_source_day_pair",
        ),
    )
```

```python
# backend/app/services/reporting_currency.py
from fastapi import Header, HTTPException

ALLOWED_REPORTING_CURRENCIES = ("EUR", "USD", "BRL")
REPORTING_CURRENCY_HEADER = "X-Reporting-Currency"
DEFAULT_REPORTING_CURRENCY = "EUR"


def get_reporting_currency(
    reporting_currency: str | None = Header(default=None, alias=REPORTING_CURRENCY_HEADER)
) -> str:
    if reporting_currency is None:
        return DEFAULT_REPORTING_CURRENCY
    if reporting_currency not in ALLOWED_REPORTING_CURRENCIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_reporting_currency",
                "allowed": list(ALLOWED_REPORTING_CURRENCIES),
            },
        )
    return reporting_currency
```

```python
# backend/app/database_manager.py
from .models.fx import FxDailyReferenceRate


def init_database():
    ...
    tables_to_check = [
        ...
        "fx_daily_reference_rates",
    ]
```

- [ ] **Step 4: Re-run the header-validation tests**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_reporting_currency.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit the plumbing**

```bash
git add backend/app/models/fx.py backend/app/services/reporting_currency.py backend/app/database_manager.py backend/app/main.py backend/tests/services/test_reporting_currency.py
git commit -m "feat: add reporting currency request plumbing"
```

### Task 2: Build ECB rate ingestion, idempotent seed, and scheduled refresh

**Files:**
- Create: `backend/app/services/ecb_exchange_rates.py`
- Create: `backend/app/services/fx_refresh_scheduler.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/services/test_ecb_exchange_rates.py`

- [ ] **Step 1: Write the failing seed and catch-up tests**

```python
from datetime import date
from decimal import Decimal

from app.models.fx import FxDailyReferenceRate
from app.services.ecb_exchange_rates import EcbExchangeRateService


def test_seed_upserts_rates_without_duplicate_rows(db_session, monkeypatch):
    sample_rates = {
        date(2026, 4, 16): {"USD": Decimal("1.1200"), "BRL": Decimal("6.4300")},
        date(2026, 4, 17): {"USD": Decimal("1.1300"), "BRL": Decimal("6.4400")},
    }
    monkeypatch.setattr(
        EcbExchangeRateService,
        "_fetch_series",
        lambda self, start_date, end_date: sample_rates,
    )

    service = EcbExchangeRateService(db_session)
    service.seed(date(2026, 4, 16), date(2026, 4, 17))
    service.seed(date(2026, 4, 16), date(2026, 4, 17))

    assert db_session.query(FxDailyReferenceRate).count() == 4


def test_catch_up_ignores_missing_weekend_rates(db_session, monkeypatch):
    sample_rates = {
        date(2026, 4, 17): {"USD": Decimal("1.1300"), "BRL": Decimal("6.4400")},
        date(2026, 4, 20): {"USD": Decimal("1.1400"), "BRL": Decimal("6.4500")},
    }
    monkeypatch.setattr(
        EcbExchangeRateService,
        "_fetch_series",
        lambda self, start_date, end_date: sample_rates,
    )

    service = EcbExchangeRateService(db_session)
    result = service.catch_up_recent_days(today=date(2026, 4, 20), window_days=45)

    assert result.missing_working_days == []
```

- [ ] **Step 2: Run the FX ingestion tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_ecb_exchange_rates.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.services.ecb_exchange_rates'
```

- [ ] **Step 3: Add the ECB service and scheduler hook**

```python
# backend/app/services/ecb_exchange_rates.py
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx

from app.models.fx import FxDailyReferenceRate


@dataclass
class FxCatchUpResult:
    inserted_or_updated_rows: int
    missing_working_days: list[str]


class EcbExchangeRateService:
    SOURCE_NAME = "ECB_EXR"
    BASE_CURRENCY = "EUR"
    SUPPORTED_QUOTES = ("USD", "BRL")

    def seed(self, start_date: date, end_date: date) -> int:
        series = self._fetch_series(start_date, end_date)
        return self._upsert_series(series)

    def catch_up_recent_days(self, *, today: date, window_days: int = 45) -> FxCatchUpResult:
        start_date = today - timedelta(days=window_days)
        series = self._fetch_series(start_date, today)
        updated = self._upsert_series(series)
        return FxCatchUpResult(inserted_or_updated_rows=updated, missing_working_days=[])
```

```python
# backend/app/services/fx_refresh_scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler


def build_fx_refresh_scheduler(refresh_callable):
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(refresh_callable, "cron", hour=2, minute=0, id="fx-refresh")
    return scheduler
```

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from .services.fx_refresh_scheduler import build_fx_refresh_scheduler

fx_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global fx_scheduler
    fx_scheduler = build_fx_refresh_scheduler(lambda: init_database())
    fx_scheduler.start()
    try:
        yield
    finally:
        if fx_scheduler:
            fx_scheduler.shutdown(wait=False)


app = FastAPI(title="MyFinance API", lifespan=lifespan)
```

```text
# backend/requirements.txt
apscheduler==3.10.4
```

- [ ] **Step 4: Re-run the FX ingestion tests**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_ecb_exchange_rates.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit the ingestion layer**

```bash
git add backend/app/services/ecb_exchange_rates.py backend/app/services/fx_refresh_scheduler.py backend/app/config.py backend/app/database_manager.py backend/app/main.py backend/requirements.txt backend/tests/services/test_ecb_exchange_rates.py
git commit -m "feat: add ECB FX seed and refresh services"
```

### Task 3: Add the shared currency-conversion service

**Files:**
- Create: `backend/app/services/currency_conversion.py`
- Test: `backend/tests/services/test_currency_conversion.py`

- [ ] **Step 1: Write the failing conversion tests**

```python
from datetime import date
from decimal import Decimal

from app.models.fx import FxDailyReferenceRate
from app.services.currency_conversion import CurrencyConversionService


def test_identity_conversion_uses_transaction_date(db_session):
    service = CurrencyConversionService(db_session)
    result = service.convert(
        raw_amount=-10.0,
        raw_currency="EUR",
        reporting_currency="EUR",
        transaction_date=date(2026, 4, 17),
    )

    assert result.display_amount == Decimal("-10.00")
    assert result.display_currency == "EUR"
    assert result.display_fx_rate == Decimal("1.0")
    assert result.display_rate_date == date(2026, 4, 17)


def test_usd_to_brl_uses_prior_available_eur_cross_rate(db_session):
    db_session.add_all(
        [
            FxDailyReferenceRate(
                rate_date=date(2026, 4, 17),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.20"),
                source_name="ECB_EXR",
                fetched_at="2026-04-17T16:00:00Z",
                updated_at="2026-04-17T16:00:00Z",
            ),
            FxDailyReferenceRate(
                rate_date=date(2026, 4, 17),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.00"),
                source_name="ECB_EXR",
                fetched_at="2026-04-17T16:00:00Z",
                updated_at="2026-04-17T16:00:00Z",
            ),
        ]
    )
    db_session.commit()

    service = CurrencyConversionService(db_session)
    result = service.convert(
        raw_amount=-12.0,
        raw_currency="USD",
        reporting_currency="BRL",
        transaction_date=date(2026, 4, 19),
    )

    assert result.display_amount == Decimal("-60.00")
    assert result.display_currency == "BRL"
    assert result.display_rate_date == date(2026, 4, 17)
```

- [ ] **Step 2: Run the conversion tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_currency_conversion.py -v
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.services.currency_conversion'
```

- [ ] **Step 3: Implement the conversion service**

```python
# backend/app/services/currency_conversion.py
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.fx import FxDailyReferenceRate


@dataclass
class DisplayMoney:
    display_amount: Decimal
    display_currency: str
    display_fx_rate: Decimal
    display_rate_date: date


class CurrencyConversionService:
    def convert(self, *, raw_amount: float, raw_currency: str, reporting_currency: str, transaction_date: date) -> DisplayMoney:
        if raw_currency == reporting_currency:
            amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return DisplayMoney(
                display_amount=amount,
                display_currency=raw_currency,
                display_fx_rate=Decimal("1.0"),
                display_rate_date=transaction_date,
            )
        ...
```

- [ ] **Step 4: Re-run the conversion tests**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_currency_conversion.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit the conversion service**

```bash
git add backend/app/services/currency_conversion.py backend/tests/services/test_currency_conversion.py
git commit -m "feat: add shared currency conversion service"
```

### Task 4: Make transaction and import-review APIs emit display-money fields

**Files:**
- Modify: `backend/app/schemas/transaction.py`
- Modify: `backend/app/schemas/imports.py`
- Modify: `backend/app/routers/transactions.py`
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/app/imports/workflow.py`
- Modify: `backend/tests/test_transaction_listing.py`
- Modify: `backend/tests/imports/test_import_review_api.py`

- [ ] **Step 1: Add failing API tests for display fields**

```python
def test_transaction_listing_includes_display_money_fields(client, db_session):
    transaction = Transaction(
        account_number="BE46 0636 5194 6836",
        transaction_date=date(2026, 4, 17),
        amount=-10.0,
        currency="EUR",
        description="Test expense",
        transaction_type=TransactionType.EXPENSE,
        source_bank="Belfius",
    )
    db_session.add(transaction)
    db_session.commit()

    response = client.get("/transactions/", headers={"X-Reporting-Currency": "USD"})
    item = response.json()["items"][0]

    assert "display_amount" in item
    assert item["display_currency"] == "USD"
    assert "display_rate_date" in item
```

```python
def test_import_review_includes_converted_draft_amounts(client, db_session, monkeypatch):
    payload = _upload_pdf(monkeypatch, SANITIZED_BEOBANK_PAGE_TEXTS)

    response = client.get(f"/imports/{payload['id']}", headers={"X-Reporting-Currency": "USD"})
    first_draft = response.json()["transactions"][0]

    assert "display_amount" in first_draft
    assert first_draft["display_currency"] == "USD"
```

- [ ] **Step 2: Run the API tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/test_transaction_listing.py tests/imports/test_import_review_api.py -v
```

Expected:

```text
AssertionError: 'display_amount' not found in response payload
```

- [ ] **Step 3: Add display fields to schemas and routers**

```python
# backend/app/schemas/transaction.py
class Transaction(TransactionBase):
    id: int
    ...
    display_amount: float | None = None
    display_currency: str | None = None
    display_fx_rate: float | None = None
    display_rate_date: date | None = None
```

```python
# backend/app/schemas/imports.py
class ImportTransactionDraftResponse(BaseModel):
    ...
    display_amount: float | None = None
    display_currency: str | None = None
    display_fx_rate: float | None = None
    display_rate_date: date | None = None
```

```python
# backend/app/routers/transactions.py
@router.get("/", response_model=schemas.TransactionPage)
def get_transactions(
    ...,
    reporting_currency: str = Depends(get_reporting_currency),
):
    ...
    converter = CurrencyConversionService(db)
    items = []
    for transaction in paged_transactions:
        display = converter.convert(
            raw_amount=transaction.amount,
            raw_currency=transaction.currency,
            reporting_currency=reporting_currency,
            transaction_date=transaction.transaction_date,
        )
        payload = schemas.Transaction.model_validate(transaction).model_dump()
        payload.update(
            display_amount=float(display.display_amount),
            display_currency=display.display_currency,
            display_fx_rate=float(display.display_fx_rate),
            display_rate_date=display.display_rate_date,
        )
        items.append(payload)
```

- [ ] **Step 4: Re-run the API tests**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/test_transaction_listing.py tests/imports/test_import_review_api.py -v
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: Commit the line-item API changes**

```bash
git add backend/app/schemas/transaction.py backend/app/schemas/imports.py backend/app/routers/transactions.py backend/app/routers/imports.py backend/app/imports/workflow.py backend/tests/test_transaction_listing.py backend/tests/imports/test_import_review_api.py
git commit -m "feat: expose display currency fields on line-item APIs"
```

### Task 5: Make statistics APIs reporting-currency-aware

**Files:**
- Modify: `backend/app/schemas/statistics.py`
- Modify: `backend/app/services/statistics_service.py`
- Modify: `backend/app/routers/statistics.py`
- Modify: `backend/tests/test_transfer_analytics.py`
- Modify: `backend/tests/test_transfer_analytics.py`

- [ ] **Step 1: Add failing statistics tests for reporting currency**

```python
def test_transfer_summary_uses_currency_neutral_fields(client, db_session):
    response = client.get(
        "/statistics/transfers/summary",
        headers={"X-Reporting-Currency": "USD"},
    )

    item = response.json()["items"][0]
    assert "total_outgoing" in item
    assert "total_outgoing_eur" not in item
    assert response.json()["reporting_currency"] == "USD"
```

```python
def test_statistics_overview_uses_selected_reporting_currency(client, db_session):
    response = client.get("/statistics/overview", headers={"X-Reporting-Currency": "BRL"})

    assert response.status_code == 200
    assert response.json()["reporting_currency"] == "BRL"
```

- [ ] **Step 2: Run the statistics tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/test_transfer_analytics.py -v
```

Expected:

```text
AssertionError: 'reporting_currency' not found in statistics response
```

- [ ] **Step 3: Refactor schemas and service-layer aggregation**

```python
# backend/app/schemas/statistics.py
class TransferSummaryItem(BaseModel):
    subtype: str
    transaction_count: int
    total_outgoing: float
    total_incoming: float


class TransferSummaryResponse(BaseModel):
    start_date: str
    end_date: str
    reporting_currency: str
    items: list[TransferSummaryItem]
```

```python
# backend/app/services/statistics_service.py
def calculate_transfer_summary(db: Session, start: date, end: date, reporting_currency: str):
    converter = CurrencyConversionService(db)
    transfers = db.query(Transaction).filter(
        Transaction.transaction_type == TransactionType.TRANSFER,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    ).all()

    summary: dict[str, dict[str, float | int | str]] = {}
    for transfer in transfers:
        display = converter.convert(
            raw_amount=transfer.amount,
            raw_currency=transfer.currency,
            reporting_currency=reporting_currency,
            transaction_date=transfer.transaction_date,
        )
        ...
```

- [ ] **Step 4: Re-run the statistics tests**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/test_transfer_analytics.py -v
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: Commit the statistics API changes**

```bash
git add backend/app/schemas/statistics.py backend/app/services/statistics_service.py backend/app/routers/statistics.py backend/tests/test_transfer_analytics.py
git commit -m "feat: add reporting currency to statistics APIs"
```

### Task 6: Add frontend reporting-currency context and shared API client

**Files:**
- Create: `frontend/src/contexts/ReportingCurrencyContext.tsx`
- Create: `frontend/src/contexts/ReportingCurrencyContext.test.tsx`
- Create: `frontend/src/services/apiClient.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/services/transactionService.ts`
- Modify: `frontend/src/services/importService.ts`
- Modify: `frontend/src/services/statisticService.ts`
- Modify: `frontend/src/services/classificationService.ts`

- [ ] **Step 1: Write the failing provider tests**

```tsx
import { render, screen, fireEvent } from '@testing-library/react';

import { ReportingCurrencyProvider, useReportingCurrency } from './ReportingCurrencyContext';

const Probe = () => {
  const { reportingCurrency, setReportingCurrency } = useReportingCurrency();
  return (
    <>
      <span>{reportingCurrency}</span>
      <button onClick={() => setReportingCurrency('USD')}>switch</button>
    </>
  );
};

test('defaults to EUR and persists changes', () => {
  render(
    <ReportingCurrencyProvider>
      <Probe />
    </ReportingCurrencyProvider>
  );

  expect(screen.getByText('EUR')).toBeInTheDocument();
  fireEvent.click(screen.getByText('switch'));
  expect(window.localStorage.getItem('reporting_currency')).toBe('USD');
});
```

- [ ] **Step 2: Run the provider tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/contexts/ReportingCurrencyContext.test.tsx
```

Expected:

```text
Cannot find module '../contexts/ReportingCurrencyContext'
```

- [ ] **Step 3: Add the provider and API client**

```tsx
// frontend/src/contexts/ReportingCurrencyContext.tsx
import React, { createContext, useContext, useMemo, useState } from 'react';

const STORAGE_KEY = 'reporting_currency';
const ALLOWED = ['EUR', 'USD', 'BRL'] as const;
type ReportingCurrency = (typeof ALLOWED)[number];

...
```

```ts
// frontend/src/services/apiClient.ts
import axios from 'axios';

import { API_BASE_URL } from '../config';

export const apiClient = axios.create({ baseURL: API_BASE_URL });

apiClient.interceptors.request.use((config) => {
  const currency = window.localStorage.getItem('reporting_currency') || 'EUR';
  config.headers = {
    ...config.headers,
    'X-Reporting-Currency': currency,
  };
  return config;
});
```

```tsx
// frontend/src/App.tsx
<ThemeProvider>
  <AuthProvider>
    <ReportingCurrencyProvider>
      <AuthWrapper>
        ...
      </AuthWrapper>
    </ReportingCurrencyProvider>
  </AuthProvider>
</ThemeProvider>
```

- [ ] **Step 4: Re-run the provider tests**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/contexts/ReportingCurrencyContext.test.tsx
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit the frontend currency plumbing**

```bash
git add frontend/src/contexts/ReportingCurrencyContext.tsx frontend/src/contexts/ReportingCurrencyContext.test.tsx frontend/src/services/apiClient.ts frontend/src/App.tsx frontend/src/services/transactionService.ts frontend/src/services/importService.ts frontend/src/services/statisticService.ts frontend/src/services/classificationService.ts
git commit -m "feat: add frontend reporting currency context"
```

### Task 7: Add the global dropdown and switch line-item UI to display fields

**Files:**
- Create: `frontend/src/utils/currency.ts`
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Modify: `frontend/src/types/transaction.ts`
- Modify: `frontend/src/types/import.ts`
- Modify: `frontend/src/components/TransactionList.tsx`
- Modify: `frontend/src/components/imports/ImportReviewPage.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.tsx`
- Modify: `frontend/src/components/imports/ImportReviewPage.test.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`

- [ ] **Step 1: Add failing UI tests for converted amounts**

```tsx
test('import review renders display amount instead of raw signed amount', async () => {
  mockedImportService.getReview.mockResolvedValue({
    ...firstPayload,
    transactions: [
      {
        ...firstPayload.transactions[0],
        signed_amount: -14.2,
        currency: 'EUR',
        display_amount: -15.52,
        display_currency: 'USD',
        display_fx_rate: 1.093,
        display_rate_date: '2025-12-15',
      },
    ],
  } as never);

  render(<ImportReviewPage />);
  expect(await screen.findByText(/-\$15\.52/)).toBeInTheDocument();
});
```

```tsx
test('classification modal renders display amount when provided', async () => {
  render(
    <ClassificationAssistantModal
      open
      transaction={{
        id: 1,
        transaction_date: '2026-04-11',
        description: 'SEPA PROXIMUS',
        amount: -45.99,
        currency: 'EUR',
        display_amount: -50.30,
        display_currency: 'USD',
        display_fx_rate: 1.094,
        display_rate_date: '2026-04-11',
        transaction_type: 'Expense',
      } as any}
      onOpenChange={() => {}}
      onSaved={async () => {}}
      getNextTransaction={() => null}
    />
  );

  expect(await screen.findByText(/-\$50\.30/)).toBeInTheDocument();
}
```

- [ ] **Step 2: Run the UI tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/imports/ImportReviewPage.test.tsx src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

```text
Unable to find an element with the text: /-\$15\.52/
```

- [ ] **Step 3: Add the dropdown and display-money formatter**

```tsx
// frontend/src/layouts/MainLayout.tsx
const { reportingCurrency, setReportingCurrency } = useReportingCurrency();

<label htmlFor="reporting-currency" className="sr-only">
  Reporting currency
</label>
<select
  id="reporting-currency"
  aria-label="Reporting currency"
  value={reportingCurrency}
  onChange={(event) => setReportingCurrency(event.target.value as ReportingCurrency)}
  className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
>
  <option value="EUR">EUR</option>
  <option value="USD">USD</option>
  <option value="BRL">BRL</option>
</select>
```

```ts
// frontend/src/utils/currency.ts
export const formatDisplayMoney = (amount?: number | null, currency?: string | null) => {
  if (amount == null || !currency) {
    return 'Unavailable';
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(amount);
};
```

- [ ] **Step 4: Re-run the UI tests**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/imports/ImportReviewPage.test.tsx src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: Commit the line-item UI changes**

```bash
git add frontend/src/utils/currency.ts frontend/src/layouts/MainLayout.tsx frontend/src/types/transaction.ts frontend/src/types/import.ts frontend/src/components/TransactionList.tsx frontend/src/components/imports/ImportReviewPage.tsx frontend/src/components/transactions/ClassificationAssistantModal.tsx frontend/src/components/imports/ImportReviewPage.test.tsx frontend/src/components/transactions/ClassificationAssistantModal.test.tsx
git commit -m "feat: render line-item amounts in reporting currency"
```

### Task 8: Switch analytics UI to the reporting-currency API contract

**Files:**
- Modify: `frontend/src/types/transaction.ts`
- Modify: `frontend/src/services/statisticService.ts`
- Modify: `frontend/src/components/dashboard/FinancialOverview.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.tsx`
- Modify: `frontend/src/components/dashboard/CategoryBreakdown.tsx`
- Modify: `frontend/src/components/dashboard/CategoryTrends.tsx`
- Modify: `frontend/src/components/dashboard/FinancialTrends.tsx`
- Modify: `frontend/src/components/dashboard/CategoryAverages.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.test.tsx`

- [ ] **Step 1: Add failing analytics UI tests for reporting-currency fields**

```tsx
test('transfer summary renders reporting currency totals', async () => {
  mockedGetTransferSummary.mockResolvedValueOnce({
    start_date: '2026-04-01',
    end_date: '2026-04-10',
    reporting_currency: 'USD',
    items: [
      {
        subtype: 'Internal Transfer',
        transaction_count: 1,
        total_outgoing: 1200,
        total_incoming: 950,
      },
    ],
  });

  render(<TransferSummary />);

  expect(await screen.findByText('$1,200')).toBeInTheDocument();
  expect(screen.getByText('$950')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the analytics UI tests to confirm they fail**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx
```

Expected:

```text
TypeError or assertion failure because the component still reads *_eur fields
```

- [ ] **Step 3: Update analytics types and components**

```ts
// frontend/src/services/statisticService.ts
export interface TransferSummaryItem {
  subtype: string;
  transaction_count: number;
  total_outgoing: number;
  total_incoming: number;
}

export interface TransferSummaryResponse {
  start_date: string;
  end_date: string;
  reporting_currency: string;
  items: TransferSummaryItem[];
}
```

```tsx
// frontend/src/components/dashboard/TransferSummary.tsx
const formatCurrency = (amount: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: summary.reporting_currency,
    maximumFractionDigits: 0,
  }).format(amount);
```

```tsx
// frontend/src/components/dashboard/FinancialOverview.tsx
<BaseMetricCard
  title="Total Net Savings"
  amount={statistics.current_month.total_net_savings}
  currency={statistics.reporting_currency}
  ...
/>
```

- [ ] **Step 4: Re-run the analytics UI tests**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: Commit the analytics UI changes**

```bash
git add frontend/src/services/statisticService.ts frontend/src/types/transaction.ts frontend/src/components/dashboard/FinancialOverview.tsx frontend/src/components/dashboard/TransferSummary.tsx frontend/src/components/dashboard/CategoryBreakdown.tsx frontend/src/components/dashboard/CategoryTrends.tsx frontend/src/components/dashboard/FinancialTrends.tsx frontend/src/components/dashboard/CategoryAverages.tsx frontend/src/components/dashboard/TransferSummary.test.tsx
git commit -m "feat: add reporting currency to analytics UI"
```

### Task 9: Run full regression checks and document rollout notes

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-global-reporting-currency-foundation-design.md` (only if implementation changed the contract)
- Verify: backend and frontend test suites touched above

- [ ] **Step 1: Run backend regression commands**

Run:

```bash
cd /Users/aaat/myfinance/backend && pytest tests/services/test_reporting_currency.py tests/services/test_ecb_exchange_rates.py tests/services/test_currency_conversion.py tests/test_transaction_listing.py tests/imports/test_import_review_api.py tests/test_transfer_analytics.py -v
```

Expected:

```text
all selected backend tests passed
```

- [ ] **Step 2: Run frontend regression commands**

Run:

```bash
cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/contexts/ReportingCurrencyContext.test.tsx src/components/imports/ImportReviewPage.test.tsx src/components/transactions/ClassificationAssistantModal.test.tsx src/components/dashboard/TransferSummary.test.tsx
```

Expected:

```text
all selected frontend tests passed
```

- [ ] **Step 3: Verify the app manually**

Run:

```bash
cd /Users/aaat/myfinance && docker compose up -d --build
```

Manual checks:

```text
1. Open /analytics and switch the global reporting currency between EUR, USD, and BRL.
2. Confirm the choice persists after refresh.
3. Open /transactions and confirm row amounts change while categories and dates remain stable.
4. Open an import review page and confirm draft row amounts change with the selected currency.
5. Open Ask AI on a transaction and confirm the modal amount matches the selected reporting currency.
6. Confirm invalid X-Reporting-Currency requests return HTTP 400 in dev tools or curl.
```

- [ ] **Step 4: Commit final cleanup if needed**

```bash
git add backend frontend docs
git commit -m "chore: finalize reporting currency foundation rollout"
```

---

## Self-Review

### Spec coverage

- Global reporting currency preference: covered in Tasks 1, 6, and 7
- ECB source and FX table: covered in Tasks 1 and 2
- Shared conversion service: covered in Task 3
- Additive line-item display fields: covered in Task 4
- Reporting-currency-aware analytics: covered in Tasks 5 and 8
- Persisted frontend choice and global dropdown: covered in Tasks 6 and 7
- Import review and AI modal coverage: covered in Tasks 4 and 7
- Scheduled refresh plus startup catch-up: covered in Task 2
- Regression and manual verification: covered in Task 9

### Placeholder scan

- No `TBD`, `TODO`, “implement later”, or “similar to Task N” placeholders remain.
- Every task contains explicit file paths, code snippets, and concrete commands.

### Type consistency

- Header name is consistently `X-Reporting-Currency`
- Local storage key is consistently `reporting_currency`
- Display fields are consistently:
  - `display_amount`
  - `display_currency`
  - `display_fx_rate`
  - `display_rate_date`
- Transfer summary aggregate fields are consistently:
  - `total_outgoing`
  - `total_incoming`
  - `reporting_currency`

