# Historical Import FX Backfill Design

Date: 2026-04-19
Status: Draft for review

## Goal

Ensure that approved imports with historical supported-currency transactions show converted reporting-currency amounts in the same runtime, without requiring an application restart.

This pass focuses on:

1. repairing missing FX coverage for newly approved historical imports
2. keeping import approval success independent of ECB availability
3. preserving the existing review-screen behavior for now
4. keeping FX writing responsibility inside `ECBExchangeRateService`

## User Outcome

When an import is approved:

1. transactions that use a supported currency such as `xUSD` should show converted EUR amounts on the first post-approval transaction read when the missing FX range can be fetched successfully
2. approval should still succeed if the ECB fetch fails or times out
3. the import review screen may still show `FX unavailable` before approval in this iteration

## Problem Statement

Historical supported-currency imports can commit transactions whose dates are earlier than the oldest date currently covered by `FXDailyReferenceRate`. After approval, `CurrencyConversionService` looks for the most recent FX row on or before each transaction date. If no covered date exists that early, conversion returns `missing_rate`, and the UI shows `FX unavailable`.

The problem is not currency support. `xUSD` already normalizes to `USD` and passes the supported-currency guard. The problem is that import approval commits older transactions without extending FX coverage during the same runtime.

Startup FX seeding does repair historical gaps eventually because it re-queries the live minimum transaction date on each run. The missing behavior is runtime repair immediately after approval.

## Product Boundary

This design fixes the permanent post-approval gap first.

It does not change the pre-approval import review screen in this pass. That screen is transient and does not block the review task of choosing type and category. The permanent transaction listing is the higher-value surface and is the first guaranteed corrected read.

## Decision

Add a synchronous, post-commit FX backfill hook to `ImportWorkflowService.approve_session()`.

The hook will:

1. run only after `_commit_session_state(...)` completes successfully
2. exit immediately when there is no historical FX gap to repair
3. compute a targeted missing historical window
4. call `ECBExchangeRateService.refresh_range(...)` with a shorter timeout than startup refresh uses
5. catch and log failures without failing approval

No startup-policy change is required for this fix. Existing startup seeding remains the fallback repair path if runtime backfill fails.

## Scope

### In scope

- adding a post-commit FX backfill hook in `approve_session()`
- adding an FX coverage-floor query to `ECBExchangeRateService`
- adding a publication-day boundary helper to `ECBExchangeRateService`
- adding an overridable timeout to `ECBExchangeRateService`
- keeping the backfill window narrowly scoped to the missing historical slice
- adding workflow and ECB service tests for the new behavior

### Out of scope

- changing import review payload behavior before approval
- moving FX refresh into `get_review_payload()`
- changing startup FX seeding policy
- changing `CurrencyConversionService` conversion logic
- changing supported quote lists or FX data sources

## Approaches Considered

### Approach A: Deferred repair on next restart or scheduled refresh

Pros:

- very small change
- no network I/O associated with approval

Cons:

- leaves the permanent post-approval listing incorrect until later
- does not meet the requirement for same-runtime correction

### Approach B: Post-approval synchronous backfill outside the transaction

Pros:

- guarantees the first post-approval read can use repaired FX coverage
- keeps approval rollback independent from ECB availability
- fits the existing post-commit hook pattern already used by category-index sync and anomaly detection

Cons:

- slows approval responses when a historical gap must be fetched
- adds one external network dependency to the approval path

### Approach C: Background-thread backfill after approval

Pros:

- keeps approval responses fast
- avoids blocking the request on ECB latency

Cons:

- creates a race with the first post-approval transaction read
- does not guarantee converted amounts on the first listing load

### Recommendation

Use Approach B.

The requirement is about correctness on the first post-approval read, not eventual correction seconds later. A synchronous hook after commit is the smallest design that provides that guarantee while keeping approval success independent of ECB success.

## Architecture

The architectural boundaries stay clean:

- `ImportWorkflowService` decides whether newly approved transactions require FX coverage repair
- `ECBExchangeRateService` remains the only writer of `FXDailyReferenceRate` rows and owns ECB calendar logic
- `CurrencyConversionService` remains a pure reader of FX coverage

The new flow becomes:

`approve import -> commit session state -> sync suggestion index -> run anomaly detection -> backfill missing historical FX window if needed -> return response`

The hook is intentionally post-commit. It should not run inside the transaction that persists approved transactions.

## Workflow Design

### Trigger point

In `ImportWorkflowService.approve_session()`:

1. build committed transactions and collect `affected_dates`
2. `db.flush()`
3. refresh statistics in-transaction
4. set status to committed
5. commit through `_commit_session_state(...)`
6. sync suggestion index
7. run anomaly detection
8. run the new FX backfill hook
9. return response

The FX hook should run last among the post-commit hooks because it is the only one that performs external network I/O. The in-process post-commit hooks should complete before the best-effort ECB fetch begins.

### Hook contract

Add a workflow helper with a shape similar to:

- `_try_backfill_fx_for_dates(affected_dates: set[date]) -> None`

Its responsibilities are:

1. return immediately if `affected_dates` is empty
2. instantiate `ECBExchangeRateService` with a shorter timeout for approval-time use
3. load the current FX coverage floor
4. return immediately if there is no historical gap
5. compute the missing window
6. call `refresh_range(start, end)`
7. catch exceptions, log a warning with the attempted bounds, and return

The helper should not contain ECB publication-day rules directly. Those belong in the ECB service.

## ECB Service Design

Add three pieces of ECB-specific surface to `ECBExchangeRateService`:

### `earliest_covered_date() -> date | None`

Returns the minimum `FXDailyReferenceRate.rate_date` for the ECB source, or `None` when no FX rows exist yet.

This method provides the workflow layer with the current FX coverage floor without exposing table queries outside the ECB service.

### `latest_publication_day_on_or_before(day: date) -> date`

Walks backward until it finds a day for which `_is_ecb_publication_day(...)` is true.

This method ensures that:

- regular weekdays stay unchanged
- weekends resolve to the previous Friday
- ECB closing days resolve to the previous publication day
- year-boundary walk-back stays inside ECB calendar rules

### `timeout` constructor parameter

Add a constructor parameter that defaults to the current behavior of `30.0` seconds.

The service should store that timeout and use it in both `_get_xml_response(...)` branches so approval-time callers can shorten the network wait without affecting startup callers.

The approval-time hook should use a named constant:

- `FX_BACKFILL_TIMEOUT_SECONDS = 10.0`

and instantiate the service with that timeout.

## Backfill Window Rules

The workflow hook must guard before computing the window:

1. if `affected_dates` is empty, return
2. load `coverage_floor = earliest_covered_date()`
3. let `min_affected_date = min(affected_dates)`
4. if `coverage_floor is not None` and `min_affected_date >= coverage_floor`, return
5. only then compute `start` and `end`

The backfill window is:

- `start = latest_publication_day_on_or_before(min_affected_date)`
- `end = coverage_floor - 1 day` when FX rows already exist
- `end = the ECB service's effective today` when no FX rows exist yet

The `today` value in this rule should come from the ECB service's own clock, derived from its `now_provider`, so tests remain deterministic.

This start-date adjustment is required because `refresh_range(start_date, end_date)` only persists rows whose `rate_date` falls inside the requested window. Starting on a weekend or ECB closing day would exclude the previous publication day that conversion depends on.

## Failure Behavior

Approval success must not depend on the ECB call succeeding.

If the backfill call fails due to timeout, HTTP error, XML parse error, or any other exception:

1. the import remains approved and committed
2. the workflow logs a warning with the attempted backfill bounds
3. existing UI behavior remains in place for affected rows, meaning `missing_rate` can still surface temporarily
4. the next startup seed remains the existing recovery path because startup seeding re-queries the live minimum transaction date

This keeps the user-visible failure mode limited to current fallback behavior rather than turning ECB availability into an approval blocker.

## Testing Design

### Workflow tests

Add focused tests in `backend/tests/imports/test_import_workflow.py` for:

1. `approve_session()` triggers post-commit backfill when approved dates extend earlier than current FX coverage
2. `approve_session()` skips backfill when `min(affected_dates) >= coverage_floor`
3. `approve_session()` uses the ECB service's effective `today` as the backfill end when the FX table is empty
4. `approve_session()` still succeeds when the backfill call raises
5. `_try_backfill_fx_for_dates()` returns immediately without calling ECB when passed an empty date set

These tests should assert behavior through the workflow seam rather than through unrelated API endpoints.

### ECB service tests

Add focused tests in `backend/tests/services/test_ecb_exchange_rates.py` for:

1. `earliest_covered_date()` returns `None` when no rows exist
2. `earliest_covered_date()` returns the minimum covered date when rows exist
3. `latest_publication_day_on_or_before()` returns:
   - same day for a normal weekday
   - previous Friday for Saturday
   - previous Friday for Sunday
   - previous Thursday for Easter Monday because Good Friday and Easter Monday are both closed
   - previous year boundary day for New Year’s Day
4. approval-time timeout is honored at the actual HTTP call site, using a recording client so the test proves the value passed into `.get(...)`

### What does not need new tests

- `CurrencyConversionService` conversion rules
- import review payload behavior before approval
- startup seed policy

Those behaviors are intentionally unchanged in this design.

## Rollout Notes

This design intentionally leaves one visible limitation in place for now:

- the pre-approval review screen may still show `FX unavailable` for historical supported-currency drafts

If that becomes a real product issue later, it can be addressed with a separate trigger earlier in the import lifecycle. That is intentionally deferred so this change remains focused on the permanent post-approval gap.
