# Import Review FX Coverage Guarantee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure import review returns converted display-money fields for supported-currency drafts after a narrow ECB coverage fill, while preserving graceful unavailable states when coverage cannot be produced.

**Architecture:** Extract the EUR-base quote derivation into a shared helper used by conversion and coverage. Add an ECB service coverage API that first checks usable prior-rate coverage for the exact draft requests, then performs a locked narrow fetch only when needed. Wire import review to call this API before serializing draft rows, and widen startup historical seeding to include import draft dates.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, pytest, monkeypatch, Python dataclasses/enums, POSIX `flock` through `fcntl`

---

## File Structure

### Backend Code

- Create: `/Users/aaat/myfinance/backend/app/services/fx_pairs.py`
  - Own the shared EUR-base quote derivation rule.
- Create: `/Users/aaat/myfinance/backend/app/services/fx_refresh_lock.py`
  - Own the file-lock helper used by background and import-review FX refreshes.
- Modify: `/Users/aaat/myfinance/backend/app/services/currency_conversion.py`
  - Delegate `_required_quotes(...)` to `fx_pairs.required_fx_quotes(...)`.
- Modify: `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`
  - Add coverage dataclasses and status enum.
  - Add per-request coverage checking.
  - Add fetch-if-missing coverage guarantee with lock, lookback, and warning-free result reporting.
  - Include import draft dates in `_historical_seed_start_date(...)`.
- Modify: `/Users/aaat/myfinance/backend/app/main.py`
  - Replace the private inline lock implementation with the shared lock helper.
- Modify: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
  - Ensure FX coverage before serializing import review rows.
  - Log warning-only coverage failures with session context.

### Tests

- Modify: `/Users/aaat/myfinance/backend/tests/services/test_currency_conversion.py`
  - Assert shared quote helper behavior and conversion compatibility.
- Modify: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`
  - Assert coverage statuses, targeted range selection, unsupported short-circuit, fetch failure, and draft-date seed anchoring.
- Modify: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`
  - Add lock helper tests in the same service-level test file to avoid another small test file.
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`
  - Assert import review calls the coverage API before display serialization and degrades gracefully on coverage failure.
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`
  - Adjust fake ECB service constructors if needed because workflow will instantiate the service for review coverage as well as post-approval backfill.

### Read-Only References

- `/Users/aaat/myfinance/docs/superpowers/specs/2026-04-26-import-review-fx-coverage-guarantee-design.md`
- `/Users/aaat/myfinance/docs/superpowers/specs/2026-04-19-historical-import-fx-backfill-design.md`
- `/Users/aaat/myfinance/backend/app/services/currency_aliases.py`
- `/Users/aaat/myfinance/backend/app/services/reporting_currency.py`

### Explicitly Out Of Scope

- Frontend changes.
- New FX providers.
- Changing raw draft currency storage from `xUSD` to `USD`.
- Blocking import review when ECB is unavailable.
- Changing the import approval post-commit backfill behavior except for shared helpers it can reuse.

## Task 1: Extract Shared FX Quote Derivation

**Files:**
- Create: `/Users/aaat/myfinance/backend/app/services/fx_pairs.py`
- Modify: `/Users/aaat/myfinance/backend/app/services/currency_conversion.py`
- Test: `/Users/aaat/myfinance/backend/tests/services/test_currency_conversion.py`

- [ ] **Step 1: Add failing tests for the shared quote rule**

Append this test to `/Users/aaat/myfinance/backend/tests/services/test_currency_conversion.py`:

```python
def test_required_fx_quotes_matches_eur_base_conversion_pairs():
    from app.services.fx_pairs import required_fx_quotes

    assert required_fx_quotes(raw_currency="EUR", reporting_currency="USD", base_currency="EUR") == ("USD",)
    assert required_fx_quotes(raw_currency="USD", reporting_currency="EUR", base_currency="EUR") == ("USD",)
    assert required_fx_quotes(raw_currency="USD", reporting_currency="BRL", base_currency="EUR") == (
        "BRL",
        "USD",
    )
    assert required_fx_quotes(raw_currency="USD", reporting_currency="USD", base_currency="EUR") == ()
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest tests/services/test_currency_conversion.py::test_required_fx_quotes_matches_eur_base_conversion_pairs -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.fx_pairs'`.

- [ ] **Step 3: Create the shared helper**

Create `/Users/aaat/myfinance/backend/app/services/fx_pairs.py`:

```python
from __future__ import annotations


def required_fx_quotes(
    *,
    raw_currency: str,
    reporting_currency: str,
    base_currency: str,
) -> tuple[str, ...]:
    if raw_currency == reporting_currency:
        return ()
    if raw_currency == base_currency:
        return (reporting_currency,)
    if reporting_currency == base_currency:
        return (raw_currency,)
    return tuple(sorted({raw_currency, reporting_currency}))
```

- [ ] **Step 4: Delegate the conversion service helper to the shared helper**

In `/Users/aaat/myfinance/backend/app/services/currency_conversion.py`, add the import:

```python
from app.services.fx_pairs import required_fx_quotes
```

Replace `_required_quotes(...)` with:

```python
    def _required_quotes(self, *, raw_currency: str, reporting_currency: str) -> tuple[str, ...]:
        return required_fx_quotes(
            raw_currency=raw_currency,
            reporting_currency=reporting_currency,
            base_currency=self.BASE_CURRENCY,
        )
```

- [ ] **Step 5: Run conversion tests**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest tests/services/test_currency_conversion.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/aaat/myfinance
git add backend/app/services/fx_pairs.py backend/app/services/currency_conversion.py backend/tests/services/test_currency_conversion.py
git commit -m "refactor: share fx quote derivation"
```

## Task 2: Add ECB Coverage Check Without Fetching

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`
- Test: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`

- [ ] **Step 1: Add failing coverage-check tests**

Add these imports near the top of `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`:

```python
from app.services.ecb_exchange_rates import FXConversionCoverageRequest
from app.services.ecb_exchange_rates import FXConversionCoverageStatus
```

Append these tests:

```python
def test_check_conversion_coverage_uses_supported_alias_and_prior_rate(db_session):
    db_session.add(
        FXDailyReferenceRate(
            rate_date=date(2025, 12, 31),
            base_currency="EUR",
            quoted_currency="USD",
            units_per_base=Decimal("1.2500"),
            source_name="ECB_EXR",
            fetched_at=datetime(2026, 1, 2, 8, 30, 0),
            updated_at=datetime(2026, 1, 2, 8, 30, 0),
        )
    )
    db_session.commit()

    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.ALREADY_COVERED
    assert result.required_quotes == ("USD",)
    assert result.missing_dates == ()


def test_check_conversion_coverage_treats_identity_as_covered_without_rows(db_session):
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="USD",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.ALREADY_COVERED
    assert result.required_quotes == ()
    assert result.missing_dates == ()


def test_check_conversion_coverage_short_circuits_unsupported_currency(db_session):
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="NEXO",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.UNSUPPORTED
    assert result.required_quotes == ()
    assert result.missing_dates == ()


def test_check_conversion_coverage_reports_missing_date_for_supported_pair(db_session):
    service = ECBExchangeRateService(db_session)

    result = service.check_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ]
    )

    assert result.status == FXConversionCoverageStatus.MISSING
    assert result.required_quotes == ("USD",)
    assert result.missing_dates == (date(2026, 1, 1),)
```

- [ ] **Step 2: Run coverage-check tests and verify they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_uses_supported_alias_and_prior_rate \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_treats_identity_as_covered_without_rows \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_short_circuits_unsupported_currency \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_reports_missing_date_for_supported_pair \
  -q
```

Expected: FAIL with import errors for `FXConversionCoverageRequest` and `FXConversionCoverageStatus`.

- [ ] **Step 3: Add coverage dataclasses and status enum**

In `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`, update imports:

```python
from dataclasses import dataclass
from enum import Enum
```

Add these imports:

```python
from app.services.currency_aliases import normalize_currency_code
from app.services.fx_pairs import required_fx_quotes
from app.services.reporting_currency import ALLOWED_REPORTING_CURRENCIES
```

Add these declarations after `FXRefreshResult`:

```python
@dataclass(frozen=True)
class FXConversionCoverageRequest:
    raw_currency: str
    reporting_currency: str
    transaction_date: date


class FXConversionCoverageStatus(str, Enum):
    ALREADY_COVERED = "already_covered"
    FETCHED_AND_COVERED = "fetched_and_covered"
    UNSUPPORTED = "unsupported"
    MISSING = "missing"
    FETCH_FAILED = "fetch_failed"
    LOCK_TIMEOUT = "lock_timeout"


@dataclass(frozen=True)
class FXConversionCoverageResult:
    status: FXConversionCoverageStatus
    required_quotes: tuple[str, ...] = ()
    missing_dates: tuple[date, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    error: str | None = None
```

- [ ] **Step 4: Add the non-fetching coverage methods**

In `ECBExchangeRateService`, add:

```python
    SUPPORTED_CURRENCIES = frozenset(ALLOWED_REPORTING_CURRENCIES)

    def check_conversion_coverage(
        self,
        requests: list[FXConversionCoverageRequest],
    ) -> FXConversionCoverageResult:
        coverage_inputs = self._coverage_inputs(requests)
        if coverage_inputs is None:
            return FXConversionCoverageResult(status=FXConversionCoverageStatus.UNSUPPORTED)

        if not coverage_inputs:
            return FXConversionCoverageResult(status=FXConversionCoverageStatus.ALREADY_COVERED)

        required_quotes = tuple(
            sorted({quote for _, quotes in coverage_inputs for quote in quotes})
        )
        missing_dates = tuple(
            sorted(
                {
                    transaction_date
                    for transaction_date, quotes in coverage_inputs
                    if self._latest_covered_rate_date(
                        transaction_date=transaction_date,
                        required_quotes=quotes,
                    )
                    is None
                }
            )
        )

        if missing_dates:
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.MISSING,
                required_quotes=required_quotes,
                missing_dates=missing_dates,
            )

        return FXConversionCoverageResult(
            status=FXConversionCoverageStatus.ALREADY_COVERED,
            required_quotes=required_quotes,
        )

    def _coverage_inputs(
        self,
        requests: list[FXConversionCoverageRequest],
    ) -> list[tuple[date, tuple[str, ...]]] | None:
        inputs: list[tuple[date, tuple[str, ...]]] = []
        for request in requests:
            normalized_raw_currency = normalize_currency_code(request.raw_currency)
            normalized_reporting_currency = normalize_currency_code(request.reporting_currency)
            if (
                normalized_raw_currency not in self.SUPPORTED_CURRENCIES
                or normalized_reporting_currency not in self.SUPPORTED_CURRENCIES
            ):
                return None

            quotes = required_fx_quotes(
                raw_currency=normalized_raw_currency,
                reporting_currency=normalized_reporting_currency,
                base_currency=self.BASE_CURRENCY,
            )
            if quotes:
                inputs.append((request.transaction_date, quotes))
        return inputs

    def _latest_covered_rate_date(
        self,
        *,
        transaction_date: date,
        required_quotes: tuple[str, ...],
    ) -> date | None:
        if not required_quotes:
            return transaction_date

        return self.db.execute(
            select(FXDailyReferenceRate.rate_date)
            .where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.rate_date <= transaction_date,
                FXDailyReferenceRate.quoted_currency.in_(required_quotes),
            )
            .group_by(FXDailyReferenceRate.rate_date)
            .having(func.count(func.distinct(FXDailyReferenceRate.quoted_currency)) == len(required_quotes))
            .order_by(FXDailyReferenceRate.rate_date.desc())
            .limit(1)
        ).scalar_one_or_none()
```

- [ ] **Step 5: Run coverage-check tests**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_uses_supported_alias_and_prior_rate \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_treats_identity_as_covered_without_rows \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_short_circuits_unsupported_currency \
  tests/services/test_ecb_exchange_rates.py::test_check_conversion_coverage_reports_missing_date_for_supported_pair \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/aaat/myfinance
git add backend/app/services/ecb_exchange_rates.py backend/tests/services/test_ecb_exchange_rates.py
git commit -m "feat: add fx conversion coverage checks"
```

## Task 3: Add Shared FX Refresh Lock And Targeted Coverage Fill

**Files:**
- Create: `/Users/aaat/myfinance/backend/app/services/fx_refresh_lock.py`
- Modify: `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`
- Modify: `/Users/aaat/myfinance/backend/app/main.py`
- Test: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`

- [ ] **Step 1: Add failing lock and ensure-coverage tests**

Add these imports to `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`:

```python
from contextlib import contextmanager
```

Append these tests:

```python
def test_ensure_conversion_coverage_fetches_missing_range_with_lookback(db_session, monkeypatch):
    service = ECBExchangeRateService(db_session)
    refresh_calls = []

    def fake_refresh_range(start_date, end_date):
        refresh_calls.append((start_date, end_date))
        db_session.add(
            FXDailyReferenceRate(
                rate_date=date(2025, 12, 31),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.2500"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 1, 2, 8, 30, 0),
                updated_at=datetime(2026, 1, 2, 8, 30, 0),
            )
        )
        db_session.commit()
        return FXRefreshResult(
            start_date=start_date,
            end_date=end_date,
            inserted_or_updated_rows=1,
            missing_publication_days=[],
            missing_working_days=[],
        )

    monkeypatch.setattr(service, "refresh_range", fake_refresh_range)

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.FETCHED_AND_COVERED
    assert result.start_date == date(2025, 12, 22)
    assert result.end_date == date(2026, 1, 1)
    assert refresh_calls == [(date(2025, 12, 22), date(2026, 1, 1))]


def test_ensure_conversion_coverage_rechecks_after_lock_before_fetching(db_session, monkeypatch):
    service = ECBExchangeRateService(db_session)
    refresh_calls = []

    @contextmanager
    def fake_lock(*args, **kwargs):
        db_session.add(
            FXDailyReferenceRate(
                rate_date=date(2025, 12, 31),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.2500"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 1, 2, 8, 30, 0),
                updated_at=datetime(2026, 1, 2, 8, 30, 0),
            )
        )
        db_session.commit()
        yield True

    monkeypatch.setattr("app.services.ecb_exchange_rates.acquire_fx_refresh_lock", fake_lock)
    monkeypatch.setattr(service, "refresh_range", lambda start_date, end_date: refresh_calls.append((start_date, end_date)))

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.ALREADY_COVERED
    assert refresh_calls == []


def test_ensure_conversion_coverage_returns_lock_timeout_without_fetch(db_session, monkeypatch):
    service = ECBExchangeRateService(db_session)
    refresh_calls = []

    @contextmanager
    def fake_lock(*args, **kwargs):
        yield False

    monkeypatch.setattr("app.services.ecb_exchange_rates.acquire_fx_refresh_lock", fake_lock)
    monkeypatch.setattr(service, "refresh_range", lambda start_date, end_date: refresh_calls.append((start_date, end_date)))

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.LOCK_TIMEOUT
    assert result.missing_dates == (date(2026, 1, 1),)
    assert refresh_calls == []


def test_ensure_conversion_coverage_returns_fetch_failure_without_raising(db_session, monkeypatch):
    service = ECBExchangeRateService(db_session)

    def fake_refresh_range(start_date, end_date):
        raise RuntimeError("ECB unavailable")

    monkeypatch.setattr(service, "refresh_range", fake_refresh_range)

    result = service.ensure_conversion_coverage(
        [
            FXConversionCoverageRequest(
                raw_currency="xUSD",
                reporting_currency="EUR",
                transaction_date=date(2026, 1, 1),
            )
        ],
        lock_timeout_seconds=0.0,
    )

    assert result.status == FXConversionCoverageStatus.FETCH_FAILED
    assert result.error == "ECB unavailable"
    assert result.missing_dates == (date(2026, 1, 1),)
```

- [ ] **Step 2: Run the new ensure-coverage tests and verify they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_fetches_missing_range_with_lookback \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_rechecks_after_lock_before_fetching \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_returns_lock_timeout_without_fetch \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_returns_fetch_failure_without_raising \
  -q
```

Expected: FAIL with `AttributeError: 'ECBExchangeRateService' object has no attribute 'ensure_conversion_coverage'`.

- [ ] **Step 3: Create the shared lock helper**

Create `/Users/aaat/myfinance/backend/app/services/fx_refresh_lock.py`:

```python
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def fx_refresh_lock_path(database_path: str) -> Path:
    return Path(f"{database_path}.fx-refresh.lock")


@contextmanager
def acquire_fx_refresh_lock(
    database_path: str,
    *,
    timeout_seconds: float = 0.0,
    poll_seconds: float = 0.1,
):
    lock_path = fx_refresh_lock_path(database_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    acquired = False
    deadline = time.monotonic() + max(timeout_seconds, 0.0)

    try:
        if fcntl is None:
            acquired = True
            yield True
            return

        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                yield True
                return
            except BlockingIOError:
                if timeout_seconds <= 0.0 or time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(max(poll_seconds, 0.01))
    finally:
        if acquired and fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
```

- [ ] **Step 4: Use the shared lock in `main.py`**

In `/Users/aaat/myfinance/backend/app/main.py`, remove the local `Path`, `contextmanager`, and `fcntl` imports when they are no longer used. Add:

```python
from .services.fx_refresh_lock import acquire_fx_refresh_lock
```

Replace `_fx_refresh_lock()` with:

```python
@contextmanager
def _fx_refresh_lock():
    with acquire_fx_refresh_lock(settings.database_path, timeout_seconds=0.0) as acquired:
        yield acquired
```

- [ ] **Step 5: Add targeted ensure-coverage implementation**

In `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`, add imports:

```python
from app.services.fx_refresh_lock import acquire_fx_refresh_lock
```

Add class constant:

```python
    FX_COVERAGE_LOOKBACK_DAYS = 10
```

Add method:

```python
    def ensure_conversion_coverage(
        self,
        requests: list[FXConversionCoverageRequest],
        *,
        lock_timeout_seconds: float = 0.0,
        lock_poll_seconds: float = 0.1,
    ) -> FXConversionCoverageResult:
        initial_result = self.check_conversion_coverage(requests)
        if initial_result.status != FXConversionCoverageStatus.MISSING:
            return initial_result

        start_date = min(initial_result.missing_dates) - timedelta(days=self.FX_COVERAGE_LOOKBACK_DAYS)
        end_date = max(initial_result.missing_dates)

        with acquire_fx_refresh_lock(
            settings.database_path,
            timeout_seconds=lock_timeout_seconds,
            poll_seconds=lock_poll_seconds,
        ) as acquired:
            if not acquired:
                return FXConversionCoverageResult(
                    status=FXConversionCoverageStatus.LOCK_TIMEOUT,
                    required_quotes=initial_result.required_quotes,
                    missing_dates=initial_result.missing_dates,
                    start_date=start_date,
                    end_date=end_date,
                )

            after_lock_result = self.check_conversion_coverage(requests)
            if after_lock_result.status != FXConversionCoverageStatus.MISSING:
                return after_lock_result

            try:
                self.refresh_range(start_date, end_date)
            except Exception as exc:
                self.db.rollback()
                return FXConversionCoverageResult(
                    status=FXConversionCoverageStatus.FETCH_FAILED,
                    required_quotes=after_lock_result.required_quotes,
                    missing_dates=after_lock_result.missing_dates,
                    start_date=start_date,
                    end_date=end_date,
                    error=str(exc),
                )

            after_fetch_result = self.check_conversion_coverage(requests)
            if after_fetch_result.status == FXConversionCoverageStatus.MISSING:
                return FXConversionCoverageResult(
                    status=FXConversionCoverageStatus.MISSING,
                    required_quotes=after_fetch_result.required_quotes,
                    missing_dates=after_fetch_result.missing_dates,
                    start_date=start_date,
                    end_date=end_date,
                )

            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCHED_AND_COVERED,
                required_quotes=after_fetch_result.required_quotes,
                start_date=start_date,
                end_date=end_date,
            )
```

- [ ] **Step 6: Run ensure-coverage and existing main import tests**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_fetches_missing_range_with_lookback \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_rechecks_after_lock_before_fetching \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_returns_lock_timeout_without_fetch \
  tests/services/test_ecb_exchange_rates.py::test_ensure_conversion_coverage_returns_fetch_failure_without_raising \
  tests/services/test_ecb_exchange_rates.py::test_get_xml_response_uses_configured_timeout_for_injected_http_client \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/aaat/myfinance
git add backend/app/services/fx_refresh_lock.py backend/app/services/ecb_exchange_rates.py backend/app/main.py backend/tests/services/test_ecb_exchange_rates.py
git commit -m "feat: ensure targeted fx conversion coverage"
```

## Task 4: Include Import Draft Dates In Startup Historical Seeding

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`
- Test: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`

- [ ] **Step 1: Add failing seed-anchor tests**

Add this import to `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`:

```python
from app.models.imports import ImportSession, ImportStatementDraft, ImportTransactionDraft
```

Append helper and tests:

```python
def _store_import_draft_for_fx_seed(db_session, *, transaction_date: date):
    session = ImportSession(
        file_name="nexo.csv",
        file_hash=f"hash-{transaction_date.isoformat()}",
        mime_type="text/csv",
        status="awaiting_review",
        strategy_key="nexo_csv",
    )
    db_session.add(session)
    db_session.flush()

    statement = ImportStatementDraft(
        import_session_id=session.id,
        attempt_number=1,
        overall_confidence=1.0,
        review_status="awaiting_review",
    )
    db_session.add(statement)
    db_session.flush()

    draft = ImportTransactionDraft(
        import_statement_draft_id=statement.id,
        transaction_date=transaction_date,
        source_description="Nexo card purchase",
        signed_amount=-12.34,
        currency="xUSD",
        source_locator="csv:r2:NXT1001",
        edit_source="deterministic_extracted",
    )
    db_session.add(draft)
    db_session.commit()


def test_historical_seed_start_date_uses_import_draft_when_no_committed_transactions(db_session):
    _store_import_draft_for_fx_seed(db_session, transaction_date=date(2026, 1, 1))

    service = ECBExchangeRateService(db_session)

    assert service._historical_seed_start_date(date(2026, 4, 26)) == date(2026, 1, 1)


def test_historical_seed_start_date_uses_earliest_of_committed_and_draft_dates(db_session):
    db_session.add(
        Transaction(
            account_number="BE00",
            transaction_date=date(2026, 2, 1),
            amount=-10.0,
            currency="EUR",
            description="Committed transaction",
            transaction_type=TransactionType.EXPENSE,
            source_bank="Manual",
        )
    )
    db_session.commit()
    _store_import_draft_for_fx_seed(db_session, transaction_date=date(2026, 1, 1))

    service = ECBExchangeRateService(db_session)

    assert service._historical_seed_start_date(date(2026, 4, 26)) == date(2026, 1, 1)
```

- [ ] **Step 2: Run seed-anchor tests and verify they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_ecb_exchange_rates.py::test_historical_seed_start_date_uses_import_draft_when_no_committed_transactions \
  tests/services/test_ecb_exchange_rates.py::test_historical_seed_start_date_uses_earliest_of_committed_and_draft_dates \
  -q
```

Expected: FAIL because `_historical_seed_start_date(...)` ignores `ImportTransactionDraft.transaction_date`.

- [ ] **Step 3: Expand the seed anchor query**

In `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`, add:

```python
from app.models.imports import ImportTransactionDraft
```

Replace `_historical_seed_start_date(...)` with:

```python
    def _historical_seed_start_date(self, end_date: date) -> date:
        earliest_transaction_date = self.db.execute(
            select(func.min(Transaction.transaction_date))
        ).scalar_one_or_none()
        earliest_draft_date = self.db.execute(
            select(func.min(ImportTransactionDraft.transaction_date))
        ).scalar_one_or_none()
        candidate_dates = [
            candidate_date
            for candidate_date in (earliest_transaction_date, earliest_draft_date)
            if candidate_date is not None
        ]
        if candidate_dates:
            return min(candidate_dates)

        try:
            return end_date.replace(year=end_date.year - settings.fx_seed_years)
        except ValueError:
            return end_date.replace(month=2, day=28, year=end_date.year - settings.fx_seed_years)
```

- [ ] **Step 4: Run seed-anchor tests**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_ecb_exchange_rates.py::test_historical_seed_start_date_uses_import_draft_when_no_committed_transactions \
  tests/services/test_ecb_exchange_rates.py::test_historical_seed_start_date_uses_earliest_of_committed_and_draft_dates \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/aaat/myfinance
git add backend/app/services/ecb_exchange_rates.py backend/tests/services/test_ecb_exchange_rates.py
git commit -m "fix: seed fx history from import draft dates"
```

## Task 5: Ensure FX Coverage During Import Review

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- Test: `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`
- Test: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`

- [ ] **Step 1: Add failing import-review coverage success test**

Add these imports to `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`:

```python
from app.services.ecb_exchange_rates import FXConversionCoverageResult
from app.services.ecb_exchange_rates import FXConversionCoverageStatus
```

Append this test:

```python
def test_get_review_payload_fetches_missing_supported_fx_before_display(db_session, monkeypatch):
    coverage_calls = []

    class FakeECBExchangeRateService:
        def __init__(self, db, *, timeout=30.0):
            self.db = db
            self.timeout = timeout

        def ensure_conversion_coverage(self, requests, *, lock_timeout_seconds, lock_poll_seconds):
            coverage_calls.append(
                {
                    "requests": requests,
                    "timeout": self.timeout,
                    "lock_timeout_seconds": lock_timeout_seconds,
                    "lock_poll_seconds": lock_poll_seconds,
                }
            )
            self.db.add(
                FXDailyReferenceRate(
                    rate_date=date(2026, 4, 10),
                    base_currency="EUR",
                    quoted_currency="USD",
                    units_per_base=Decimal("1.2500"),
                    source_name="ECB_EXR",
                    fetched_at=datetime(2026, 4, 10, 8, 30, 0),
                    updated_at=datetime(2026, 4, 10, 8, 30, 0),
                )
            )
            self.db.commit()
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCHED_AND_COVERED,
                required_quotes=("USD",),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 10),
            )

    monkeypatch.setattr("app.imports.workflow.ECBExchangeRateService", FakeECBExchangeRateService)

    session = _upload_nexo_csv()

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "EUR"},
    )

    assert response.status_code == 200
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["currency"] == "xUSD"
    assert first_transaction["display_amount"] == -9.87
    assert first_transaction["display_currency"] == "EUR"
    assert first_transaction["display_fx_rate"] == 0.8
    assert first_transaction["display_rate_date"] == "2026-04-10"
    assert first_transaction["display_is_available"] is True
    assert first_transaction["display_unavailable_reason"] is None
    assert len(coverage_calls) == 1
    assert {request.raw_currency for request in coverage_calls[0]["requests"]} == {"xUSD", "EUR"}
```

- [ ] **Step 2: Add failing import-review coverage failure test**

Append this test:

```python
def test_get_review_payload_keeps_missing_rate_when_review_fx_coverage_fetch_fails(db_session, monkeypatch):
    class FakeECBExchangeRateService:
        def __init__(self, db, *, timeout=30.0):
            self.db = db
            self.timeout = timeout

        def ensure_conversion_coverage(self, requests, *, lock_timeout_seconds, lock_poll_seconds):
            return FXConversionCoverageResult(
                status=FXConversionCoverageStatus.FETCH_FAILED,
                required_quotes=("USD",),
                missing_dates=(date(2026, 4, 10),),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 10),
                error="ECB unavailable",
            )

    monkeypatch.setattr("app.imports.workflow.ECBExchangeRateService", FakeECBExchangeRateService)

    session = _upload_nexo_csv()

    response = client.get(
        f"/imports/{session['id']}",
        headers={"X-Reporting-Currency": "EUR"},
    )

    assert response.status_code == 200
    payload = response.json()
    first_transaction = payload["transactions"][0]
    assert first_transaction["currency"] == "xUSD"
    assert first_transaction["display_amount"] is None
    assert first_transaction["display_currency"] == "EUR"
    assert first_transaction["display_fx_rate"] is None
    assert first_transaction["display_rate_date"] is None
    assert first_transaction["display_is_available"] is False
    assert first_transaction["display_unavailable_reason"] == "missing_rate"
```

- [ ] **Step 3: Run new import-review tests and verify they fail**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/imports/test_import_review_api.py::test_get_review_payload_fetches_missing_supported_fx_before_display \
  tests/imports/test_import_review_api.py::test_get_review_payload_keeps_missing_rate_when_review_fx_coverage_fetch_fails \
  -q
```

Expected: the success test FAILS because import review does not call `ensure_conversion_coverage(...)` before serializing display fields.

- [ ] **Step 4: Wire review coverage into the workflow**

In `/Users/aaat/myfinance/backend/app/imports/workflow.py`, update the import:

```python
from app.services.ecb_exchange_rates import (
    ECBExchangeRateService,
    FXConversionCoverageRequest,
    FXConversionCoverageStatus,
)
```

Add constants under `FX_BACKFILL_TIMEOUT_SECONDS`:

```python
FX_REVIEW_COVERAGE_TIMEOUT_SECONDS = 10.0
FX_REVIEW_LOCK_TIMEOUT_SECONDS = 15.0
FX_REVIEW_LOCK_POLL_SECONDS = 0.1
FX_REVIEW_WARNING_STATUSES = {
    FXConversionCoverageStatus.FETCH_FAILED,
    FXConversionCoverageStatus.LOCK_TIMEOUT,
    FXConversionCoverageStatus.MISSING,
}
```

In `get_review_payload(...)`, insert this call after `transactions` is loaded and before `conversion_service = CurrencyConversionService(self.db)`:

```python
        self._ensure_fx_coverage_for_review(
            session_id=session.id,
            transactions=transactions,
            reporting_currency=reporting_currency,
        )
```

Add this method to `ImportWorkflowService`:

```python
    def _ensure_fx_coverage_for_review(
        self,
        *,
        session_id: int,
        transactions: list[ImportTransactionDraft],
        reporting_currency: str,
    ) -> None:
        requests = [
            FXConversionCoverageRequest(
                raw_currency=transaction.currency,
                reporting_currency=reporting_currency,
                transaction_date=transaction.transaction_date,
            )
            for transaction in transactions
            if transaction.transaction_date is not None
        ]
        if not requests:
            return

        fx_service = ECBExchangeRateService(self.db, timeout=FX_REVIEW_COVERAGE_TIMEOUT_SECONDS)
        result = fx_service.ensure_conversion_coverage(
            requests,
            lock_timeout_seconds=FX_REVIEW_LOCK_TIMEOUT_SECONDS,
            lock_poll_seconds=FX_REVIEW_LOCK_POLL_SECONDS,
        )
        if result.status in FX_REVIEW_WARNING_STATUSES:
            logger.warning(
                "Import review FX coverage unavailable for session %s: status=%s range=%s..%s quotes=%s missing_dates=%s error=%s",
                session_id,
                result.status.value,
                result.start_date,
                result.end_date,
                result.required_quotes,
                result.missing_dates,
                result.error,
            )
```

- [ ] **Step 5: Run new import-review tests**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/imports/test_import_review_api.py::test_get_review_payload_fetches_missing_supported_fx_before_display \
  tests/imports/test_import_review_api.py::test_get_review_payload_keeps_missing_rate_when_review_fx_coverage_fetch_fails \
  -q
```

Expected: PASS.

- [ ] **Step 6: Run import workflow tests to catch fake service constructor drift**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest tests/imports/test_import_workflow.py -q
```

Expected: PASS. If a fake `ECBExchangeRateService` in this file fails because it does not accept the review constructor shape, update that fake constructor to accept `timeout=30.0` and add an `ensure_conversion_coverage(...)` method that returns `FXConversionCoverageResult(status=FXConversionCoverageStatus.ALREADY_COVERED)`.

Use this exact method body for fakes that need it:

```python
        def ensure_conversion_coverage(self, requests, *, lock_timeout_seconds, lock_poll_seconds):
            return FXConversionCoverageResult(status=FXConversionCoverageStatus.ALREADY_COVERED)
```

- [ ] **Step 7: Commit**

```bash
cd /Users/aaat/myfinance
git add backend/app/imports/workflow.py backend/tests/imports/test_import_review_api.py backend/tests/imports/test_import_workflow.py
git commit -m "feat: ensure fx coverage during import review"
```

## Task 6: Run Focused And Regression Verification

**Files:**
- Verify only. No planned source edits.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_currency_conversion.py \
  tests/services/test_ecb_exchange_rates.py \
  tests/imports/test_import_review_api.py \
  tests/imports/test_import_workflow.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests around reporting currency and imports**

Run:

```bash
cd /Users/aaat/myfinance/backend
pytest \
  tests/services/test_reporting_currency.py \
  tests/services/test_reporting_currency_analytics.py \
  tests/services/test_reporting_currency_statistics.py \
  tests/test_transaction_listing.py \
  tests/test_statistics_api.py \
  tests/imports \
  -q
```

Expected: PASS.

- [ ] **Step 3: Check worktree scope**

Run:

```bash
cd /Users/aaat/myfinance
git status --short
```

Expected: only files from this plan are modified or committed. Pre-existing unrelated changes may still appear and must remain untouched.

- [ ] **Step 4: Commit verification-only adjustments if any were required**

If Step 2 found a test fake or import mismatch and a small correction was made, commit it:

```bash
cd /Users/aaat/myfinance
git add backend/app backend/tests
git commit -m "test: verify import review fx coverage"
```

If Step 2 passed with no edits, do not create an empty commit.
