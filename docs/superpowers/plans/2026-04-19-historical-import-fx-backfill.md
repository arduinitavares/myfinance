# Historical Import FX Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure that approving an import with historical supported-currency transactions backfills missing ECB FX coverage in the same runtime so the first post-approval transaction read can show converted reporting-currency amounts.

**Architecture:** Extend `ECBExchangeRateService` with three focused capabilities: a coverage-floor query, a publication-day walk-back helper, and a configurable timeout that is honored at the actual HTTP call site. Keep `ImportWorkflowService` responsible for deciding when to trigger a targeted backfill after `_commit_session_state(...)`, after the existing in-process post-commit hooks, with warning-only failure handling so approval success stays independent of ECB availability.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, pytest, monkeypatch, Docker Compose, Python datetime/date utilities

---

## File Structure

### Backend Code

- Modify: `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`
  - Add `earliest_covered_date()`.
  - Add `latest_publication_day_on_or_before(day)`.
  - Add a configurable timeout field on the service and use it in `_get_xml_response(...)`.
- Modify: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
  - Import `ECBExchangeRateService`.
  - Add `FX_BACKFILL_TIMEOUT_SECONDS = 10.0`.
  - Add `_try_backfill_fx_for_dates(...)`.
  - Wire the new helper into `approve_session()` after `_sync_category_suggestion_index(...)` and `_run_anomaly_detection(...)`.

### Tests

- Modify: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`
  - Add unit tests for `earliest_covered_date()`.
  - Add direct unit coverage for `latest_publication_day_on_or_before()`.
  - Add a timeout pass-through test that asserts the value used at the actual HTTP call site.
- Modify: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`
  - Add a direct helper test for `_try_backfill_fx_for_dates(set())`.
  - Add post-approval integration coverage for historical-gap backfill, no-gap skip, empty-FX-table end-date selection, warning-only failure, and hook order.

### Read-Only Verification References

- Read-only: `/Users/aaat/myfinance/docs/superpowers/specs/2026-04-19-historical-import-fx-backfill-design.md`
- Read-only: `/Users/aaat/myfinance/backend/tests/imports/test_import_review_api.py`
- Read-only: `/Users/aaat/myfinance/backend/tests/test_transaction_listing.py`

### Explicitly Out Of Scope

- `/Users/aaat/myfinance/backend/app/services/currency_conversion.py`
- `/Users/aaat/myfinance/backend/app/main.py`
- Import review pre-approval behavior
- Startup FX seeding policy changes

## Task 1: Extend The ECB Exchange Rate Service Surface

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py`
- Test: `/Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py`

- [ ] **Step 1: Write the failing ECB service tests**

```python
import httpx
import pytest


def test_earliest_covered_date_returns_none_for_empty_table(db_session):
    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() is None


def test_earliest_covered_date_returns_minimum_rate_date(db_session):
    db_session.add_all(
        [
            FXDailyReferenceRate(
                rate_date=date(2026, 3, 6),
                base_currency="EUR",
                quoted_currency="USD",
                units_per_base=Decimal("1.0800"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 3, 6, 8, 30, 0),
                updated_at=datetime(2026, 3, 6, 8, 30, 0),
            ),
            FXDailyReferenceRate(
                rate_date=date(2026, 3, 25),
                base_currency="EUR",
                quoted_currency="BRL",
                units_per_base=Decimal("6.2200"),
                source_name="ECB_EXR",
                fetched_at=datetime(2026, 3, 25, 8, 30, 0),
                updated_at=datetime(2026, 3, 25, 8, 30, 0),
            ),
        ]
    )
    db_session.commit()

    service = ECBExchangeRateService(db_session)

    assert service.earliest_covered_date() == date(2026, 3, 6)


@pytest.mark.parametrize(
    ("source_day", "expected_day"),
    [
        (date(2026, 4, 15), date(2026, 4, 15)),
        (date(2026, 4, 18), date(2026, 4, 17)),
        (date(2026, 4, 19), date(2026, 4, 17)),
        (date(2026, 4, 6), date(2026, 4, 2)),
        (date(2026, 1, 1), date(2025, 12, 31)),
    ],
)
def test_latest_publication_day_on_or_before_handles_weekends_and_closing_days(
    db_session, source_day, expected_day
):
    service = ECBExchangeRateService(
        db_session,
        now_provider=lambda: datetime(2026, 4, 17, 8, 30, 0),
    )

    assert service.latest_publication_day_on_or_before(source_day) == expected_day


def test_get_xml_response_uses_configured_timeout_for_injected_http_client(db_session):
    calls = []

    class RecordingClient:
        def get(self, url, timeout=None, follow_redirects=None):
            calls.append((url, timeout, follow_redirects))
            return httpx.Response(
                200,
                text="<Envelope />",
                request=httpx.Request("GET", url),
            )

    service = ECBExchangeRateService(
        db_session,
        http_client=RecordingClient(),
        timeout=10.0,
    )

    service._get_xml_response("https://example.test/fx.xml")

    assert calls == [("https://example.test/fx.xml", 10.0, True)]
```

- [ ] **Step 2: Run the focused ECB service tests and verify they fail**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/services/test_ecb_exchange_rates.py::test_earliest_covered_date_returns_none_for_empty_table \
  backend/tests/services/test_ecb_exchange_rates.py::test_earliest_covered_date_returns_minimum_rate_date \
  backend/tests/services/test_ecb_exchange_rates.py::test_latest_publication_day_on_or_before_handles_weekends_and_closing_days \
  backend/tests/services/test_ecb_exchange_rates.py::test_get_xml_response_uses_configured_timeout_for_injected_http_client -q
```

Expected: FAIL with missing `earliest_covered_date`, missing `latest_publication_day_on_or_before`, and a timeout assertion failure because `_get_xml_response(...)` still hardcodes `30.0`.

- [ ] **Step 3: Implement the ECB service changes**

```python
class ECBExchangeRateService:
    SOURCE_NAME = "ECB_EXR"
    BASE_CURRENCY = "EUR"
    SUPPORTED_QUOTES = ("USD", "BRL")
    ECB_XML_NAMESPACE = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}

    def __init__(
        self,
        db: Session,
        *,
        http_client: httpx.Client | None = None,
        now_provider=None,
        timeout: float = 30.0,
    ) -> None:
        self.db = db
        self._http_client = http_client
        self._now_provider = now_provider or datetime.utcnow
        self._timeout = timeout

    def earliest_covered_date(self) -> date | None:
        return self.db.execute(
            select(func.min(FXDailyReferenceRate.rate_date)).where(
                FXDailyReferenceRate.source_name == self.SOURCE_NAME,
                FXDailyReferenceRate.base_currency == self.BASE_CURRENCY,
                FXDailyReferenceRate.quoted_currency.in_(self.SUPPORTED_QUOTES),
            )
        ).scalar_one_or_none()

    def latest_publication_day_on_or_before(self, day: date) -> date:
        current_day = day
        while not self._is_ecb_publication_day(current_day):
            current_day -= timedelta(days=1)
        return current_day

    def _get_xml_response(self, url: str) -> httpx.Response:
        if self._http_client is None:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(url)
        else:
            response = self._http_client.get(url, timeout=self._timeout, follow_redirects=True)

        response.raise_for_status()
        return response
```

- [ ] **Step 4: Re-run the focused ECB service tests and verify they pass**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/services/test_ecb_exchange_rates.py::test_earliest_covered_date_returns_none_for_empty_table \
  backend/tests/services/test_ecb_exchange_rates.py::test_earliest_covered_date_returns_minimum_rate_date \
  backend/tests/services/test_ecb_exchange_rates.py::test_latest_publication_day_on_or_before_handles_weekends_and_closing_days \
  backend/tests/services/test_ecb_exchange_rates.py::test_get_xml_response_uses_configured_timeout_for_injected_http_client -q
```

Expected: PASS for all four tests.

- [ ] **Step 5: Commit the ECB service changes**

```bash
git -C /Users/aaat/myfinance add \
  /Users/aaat/myfinance/backend/app/services/ecb_exchange_rates.py \
  /Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py
git -C /Users/aaat/myfinance commit -m "feat: add targeted ECB backfill helpers"
```

## Task 2: Add The Workflow Helper And Direct Guard Coverage

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- Test: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`

- [ ] **Step 1: Write the failing direct helper test for the empty-date guard**

```python
def test_try_backfill_fx_for_dates_returns_early_for_empty_date_set(db_session, monkeypatch):
    constructed = []

    class FailIfConstructed:
        def __init__(self, *args, **kwargs):
            constructed.append((args, kwargs))
            raise AssertionError("ECBExchangeRateService should not be constructed")

    monkeypatch.setattr("app.imports.workflow.ECBExchangeRateService", FailIfConstructed)

    ImportWorkflowService(db_session)._try_backfill_fx_for_dates(set())

    assert constructed == []
```

- [ ] **Step 2: Run the direct helper test and verify it fails**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/imports/test_import_workflow.py::test_try_backfill_fx_for_dates_returns_early_for_empty_date_set -q
```

Expected: FAIL with `AttributeError` because `ImportWorkflowService` does not yet define `_try_backfill_fx_for_dates(...)`.

- [ ] **Step 3: Implement the workflow helper and timeout constant**

```python
from datetime import date, datetime, timedelta, timezone

from app.services.ecb_exchange_rates import ECBExchangeRateService

logger = logging.getLogger(__name__)

FX_BACKFILL_TIMEOUT_SECONDS = 10.0


class ImportWorkflowService:
    ...

    def _try_backfill_fx_for_dates(self, affected_dates: set[date]) -> None:
        if not affected_dates:
            return

        fx_service = ECBExchangeRateService(
            self.db,
            timeout=FX_BACKFILL_TIMEOUT_SECONDS,
        )
        coverage_floor = fx_service.earliest_covered_date()
        min_affected_date = min(affected_dates)

        if coverage_floor is not None and min_affected_date >= coverage_floor:
            return

        start_date = fx_service.latest_publication_day_on_or_before(min_affected_date)
        # Use the service's clock so tests can control "today" through now_provider.
        end_date = fx_service._today() if coverage_floor is None else coverage_floor - timedelta(days=1)

        try:
            fx_service.refresh_range(start_date, end_date)
        except Exception:
            logger.warning(
                "FX backfill failed for %s to %s",
                start_date,
                end_date,
                exc_info=True,
            )
```

- [ ] **Step 4: Re-run the direct helper test and verify it passes**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/imports/test_import_workflow.py::test_try_backfill_fx_for_dates_returns_early_for_empty_date_set -q
```

Expected: PASS, proving the empty-date guard fires before service construction.

- [ ] **Step 5: Commit the workflow helper scaffold**

```bash
git -C /Users/aaat/myfinance add \
  /Users/aaat/myfinance/backend/app/imports/workflow.py \
  /Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py
git -C /Users/aaat/myfinance commit -m "feat: add import FX backfill helper"
```

## Task 3: Wire Approval To The Backfill Hook And Cover The Post-Commit Behavior

**Files:**
- Modify: `/Users/aaat/myfinance/backend/app/imports/workflow.py`
- Test: `/Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py`

- [ ] **Step 1: Write the failing post-approval workflow tests**

```python
from datetime import date

from app.services.ecb_exchange_rates import FXRefreshResult


class StubSingleTransactionNexoExtractor:
    def __init__(self, *, transaction_date: str):
        self.transaction_date = transaction_date

    def extract(self, *, file_path, session_id, attempt_number):
        return _nexo_successful_result(
            int(session_id),
            attempt_number,
            transactions=[
                ExtractedTransaction(
                    transaction_date=self.transaction_date,
                    source_description="Historical restaurant",
                    signed_amount=-97.79,
                    currency="xUSD",
                    debit_credit="debit",
                    proposed_transaction_type="Expense",
                    proposed_expense_category="Eating Out",
                    classification_source="deterministic_nexo_csv",
                    source_locator="csv:r1:NXT_HIST_1",
                    edit_source="deterministic_extracted",
                )
            ],
        )


def test_approve_session_runs_fx_backfill_after_other_post_commit_hooks_when_gap_exists(
    db_session, monkeypatch
):
    calls = []

    monkeypatch.setattr(
        "app.imports.workflow.category_suggestion_service.add_transaction",
        lambda transaction: calls.append(("index", transaction.id)),
    )
    monkeypatch.setattr(
        "app.imports.workflow.AnomalyDetectionService.detect_anomalies",
        lambda db, transaction_ids, force_redetection=False: calls.append(("anomaly", list(transaction_ids))),
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.earliest_covered_date",
        lambda self: date(2026, 3, 6),
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.latest_publication_day_on_or_before",
        lambda self, day: date(2026, 1, 2),
    )

    def fake_refresh_range(self, start_date, end_date):
        calls.append(("fx", start_date, end_date))
        return FXRefreshResult(
            start_date=start_date,
            end_date=end_date,
            inserted_or_updated_rows=2,
            missing_publication_days=[],
            missing_working_days=[],
        )

    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.refresh_range",
        fake_refresh_range,
    )

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="nexo.csv",
        content_type="text/csv",
        file_bytes=_minimal_nexo_header_bytes(),
    )
    ImportWorkflowService(
        db_session,
        nexo_csv_extractor=StubSingleTransactionNexoExtractor(transaction_date="2026-01-03"),
    ).extract_detected_session(session.id)

    approved_session = ImportWorkflowService(db_session).approve_session(session.id)
    committed_transaction = db_session.query(Transaction).one()

    assert approved_session.status == ImportSessionStatus.COMMITTED.value
    assert calls == [
        ("index", committed_transaction.id),
        ("anomaly", [committed_transaction.id]),
        ("fx", date(2026, 1, 2), date(2026, 3, 5)),
    ]


def test_approve_session_skips_fx_backfill_when_dates_are_already_covered(db_session, monkeypatch):
    def fail_publication_day(*args, **kwargs):
        raise AssertionError("publication-day helper should not be used when there is no gap")

    def fail_refresh_range(*args, **kwargs):
        raise AssertionError("refresh_range should not be called when there is no gap")

    monkeypatch.setattr("app.imports.workflow.category_suggestion_service.add_transaction", lambda transaction: None)
    monkeypatch.setattr(
        "app.imports.workflow.AnomalyDetectionService.detect_anomalies",
        lambda db, transaction_ids, force_redetection=False: None,
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.earliest_covered_date",
        lambda self: date(2026, 3, 6),
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.latest_publication_day_on_or_before",
        fail_publication_day,
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.refresh_range",
        fail_refresh_range,
    )

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="nexo.csv",
        content_type="text/csv",
        file_bytes=_minimal_nexo_header_bytes(),
    )
    ImportWorkflowService(
        db_session,
        nexo_csv_extractor=StubSingleTransactionNexoExtractor(transaction_date="2026-03-08"),
    ).extract_detected_session(session.id)

    approved_session = ImportWorkflowService(db_session).approve_session(session.id)

    assert approved_session.status == ImportSessionStatus.COMMITTED.value


def test_approve_session_uses_service_today_when_fx_table_is_empty(db_session, monkeypatch):
    calls = []

    monkeypatch.setattr("app.imports.workflow.category_suggestion_service.add_transaction", lambda transaction: None)
    monkeypatch.setattr(
        "app.imports.workflow.AnomalyDetectionService.detect_anomalies",
        lambda db, transaction_ids, force_redetection=False: None,
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.earliest_covered_date",
        lambda self: None,
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.latest_publication_day_on_or_before",
        lambda self, day: date(2026, 1, 2),
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService._today",
        lambda self: date(2026, 4, 19),
    )

    def fake_refresh_range(self, start_date, end_date):
        calls.append((start_date, end_date))
        return FXRefreshResult(
            start_date=start_date,
            end_date=end_date,
            inserted_or_updated_rows=2,
            missing_publication_days=[],
            missing_working_days=[],
        )

    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.refresh_range",
        fake_refresh_range,
    )

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="nexo.csv",
        content_type="text/csv",
        file_bytes=_minimal_nexo_header_bytes(),
    )
    ImportWorkflowService(
        db_session,
        nexo_csv_extractor=StubSingleTransactionNexoExtractor(transaction_date="2026-01-03"),
    ).extract_detected_session(session.id)

    approved_session = ImportWorkflowService(db_session).approve_session(session.id)

    assert approved_session.status == ImportSessionStatus.COMMITTED.value
    assert calls == [(date(2026, 1, 2), date(2026, 4, 19))]


def test_approve_session_commits_even_when_fx_backfill_raises(db_session, monkeypatch):
    monkeypatch.setattr("app.imports.workflow.category_suggestion_service.add_transaction", lambda transaction: None)
    monkeypatch.setattr(
        "app.imports.workflow.AnomalyDetectionService.detect_anomalies",
        lambda db, transaction_ids, force_redetection=False: None,
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.earliest_covered_date",
        lambda self: date(2026, 3, 6),
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.latest_publication_day_on_or_before",
        lambda self, day: date(2026, 1, 2),
    )
    monkeypatch.setattr(
        "app.imports.workflow.ECBExchangeRateService.refresh_range",
        lambda self, start_date, end_date: (_ for _ in ()).throw(RuntimeError("fx backfill failed")),
    )

    session, _ = ImportPipelineService(db_session).start_upload(
        filename="nexo.csv",
        content_type="text/csv",
        file_bytes=_minimal_nexo_header_bytes(),
    )
    ImportWorkflowService(
        db_session,
        nexo_csv_extractor=StubSingleTransactionNexoExtractor(transaction_date="2026-01-03"),
    ).extract_detected_session(session.id)

    approved_session = ImportWorkflowService(db_session).approve_session(session.id)

    assert approved_session.status == ImportSessionStatus.COMMITTED.value
    assert db_session.query(Transaction).count() == 1
```

- [ ] **Step 2: Run the focused workflow tests and verify they fail before wiring**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/imports/test_import_workflow.py::test_approve_session_runs_fx_backfill_after_other_post_commit_hooks_when_gap_exists \
  backend/tests/imports/test_import_workflow.py::test_approve_session_skips_fx_backfill_when_dates_are_already_covered \
  backend/tests/imports/test_import_workflow.py::test_approve_session_uses_service_today_when_fx_table_is_empty \
  backend/tests/imports/test_import_workflow.py::test_approve_session_commits_even_when_fx_backfill_raises -q
```

Expected: FAIL because `approve_session()` does not yet call `_try_backfill_fx_for_dates(...)`.

- [ ] **Step 3: Wire the backfill helper into the approval flow after the existing post-commit hooks**

```python
try:
    self.db.flush()
    self._refresh_statistics_in_transaction(affected_dates)

    assert_transition_allowed(current, ImportSessionStatus.COMMITTED)
    session.status = ImportSessionStatus.COMMITTED.value
    committed_session = self._commit_session_state(session, meta_state=session.status)
    self._sync_category_suggestion_index(committed_transactions)
    self._run_anomaly_detection(committed_transactions)
    self._try_backfill_fx_for_dates(affected_dates)
    return committed_session
except Exception:
    self.db.rollback()
    raise
```

- [ ] **Step 4: Re-run the focused workflow tests and then the full import/ECB suites**

Run:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/imports/test_import_workflow.py::test_try_backfill_fx_for_dates_returns_early_for_empty_date_set \
  backend/tests/imports/test_import_workflow.py::test_approve_session_runs_fx_backfill_after_other_post_commit_hooks_when_gap_exists \
  backend/tests/imports/test_import_workflow.py::test_approve_session_skips_fx_backfill_when_dates_are_already_covered \
  backend/tests/imports/test_import_workflow.py::test_approve_session_uses_service_today_when_fx_table_is_empty \
  backend/tests/imports/test_import_workflow.py::test_approve_session_commits_even_when_fx_backfill_raises \
  backend/tests/services/test_ecb_exchange_rates.py -q
```

Expected: PASS for the new helper/integration tests and the full ECB service test file.

Then run the nearby regression files that should stay green without modification:

```bash
cd /Users/aaat/myfinance && PYTHONPATH=/Users/aaat/myfinance/backend uv run pytest \
  backend/tests/imports/test_import_review_api.py \
  backend/tests/test_transaction_listing.py -q
```

Expected: PASS, confirming that review payload and transaction listing contracts still hold.

- [ ] **Step 5: Commit the approval wiring and regression coverage**

```bash
git -C /Users/aaat/myfinance add \
  /Users/aaat/myfinance/backend/app/imports/workflow.py \
  /Users/aaat/myfinance/backend/tests/imports/test_import_workflow.py \
  /Users/aaat/myfinance/backend/tests/services/test_ecb_exchange_rates.py
git -C /Users/aaat/myfinance commit -m "feat: backfill FX coverage after import approval"
```
