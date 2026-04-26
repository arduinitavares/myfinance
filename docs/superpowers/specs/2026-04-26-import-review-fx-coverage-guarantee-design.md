# Import Review FX Coverage Guarantee Design

Date: 2026-04-26
Status: Draft for review

## Goal

Make supported-currency import review rows show converted reporting-currency amounts whenever ECB reference data can provide the rate, even on a fresh startup or when the imported dates are earlier than committed transaction history.

The target user-visible outcome is simple:

1. `xUSD` rows are recognized as `USD`
2. import review attempts a narrow ECB fill when local rates are missing
3. the review response returns converted amounts after a successful fill
4. `FX unavailable` remains only when conversion is genuinely unsupported or the targeted fill cannot produce a usable rate

## Background

The current display-money path is structurally correct but operationally incomplete.

`CurrencyConversionService` already normalizes raw currencies before conversion, so `xUSD` becomes `USD`. `USD` is in the supported reporting-currency set. The `FX unavailable` state on the Nexo import review screenshot is therefore not an unsupported-currency problem.

The failure is `missing_rate`. The conversion service looks for the latest stored ECB quote on or before the transaction date. If the local `fx_daily_reference_rates` table does not contain a usable prior row, the backend returns:

- `display_is_available = false`
- `display_unavailable_reason = "missing_rate"`
- `display_amount = null`
- `display_fx_rate = null`
- `display_rate_date = null`

Startup seeding does not fully guarantee review-time coverage because:

1. the seed anchor currently uses committed `transactions.transaction_date`
2. pending import drafts live in `import_transaction_drafts`
3. startup FX work runs in a background thread and can still be in progress when import review is opened

## Product Decision

Import review should be a product guarantee, not a best-effort side effect of startup seeding.

For supported raw currencies and supported reporting currencies, the import review endpoint should ensure local FX coverage for the draft date range before serializing money fields. The endpoint may wait on a narrow ECB request the first time a missing range is reviewed.

The existing startup seed and scheduled refresh remain useful warm-up and maintenance paths, but import review must not depend on their timing.

## Scope

### In scope

- import review display-money coverage for supported currency pairs
- startup seed anchor expansion to include import draft dates
- a reusable FX coverage check inside the FX service layer
- targeted ECB range refresh when review coverage is missing
- graceful degradation when ECB is unavailable
- tests for coverage semantics, draft-date seeding, review-time refresh, and unsupported currencies

### Out of scope

- arbitrary currency support
- new FX data providers beyond ECB
- frontend FX math
- changing raw stored draft currency values from `xUSD` to `USD`
- blocking import review if ECB is unavailable
- changing the global reporting-currency preference model

## Definitions

### Supported currency

A currency is supported for this design when `normalize_currency_code(...)` maps it into the allowed reporting-currency set and the ECB service can provide any required quote for it.

Examples:

- `xUSD -> USD`
- `USDC -> USD`
- `EURX -> EUR`

Unsupported raw currencies must not trigger ECB fetch attempts. They remain unavailable with `display_unavailable_reason = "unsupported_currency"`.

### Usable rate

A usable rate means the same thing in coverage checks and conversion:

- for each required quote, there is a stored ECB row with `rate_date <= transaction_date`
- if the transaction date is a weekend or TARGET closing day, the most recent prior ECB publication day is valid
- exact-date rows are not required for non-publication days

This definition prevents spurious ECB fetches for weekend and holiday transactions.

### Targeted fill range

When local coverage is missing, the ECB fill range must include a short lookback before the earliest affected transaction date. This is necessary because a transaction on a non-publication day such as January 1 can require the prior business day's rate.

The implementation should use a named constant such as `FX_COVERAGE_LOOKBACK_DAYS = 10`, then fetch:

- `start = earliest_missing_transaction_date - FX_COVERAGE_LOOKBACK_DAYS`
- `end = latest_missing_transaction_date`

After the fetch, coverage should be checked again through the normal usable-rate rule.

## Architecture

### FX service ownership

`ECBExchangeRateService` should own the coverage and fetch-if-missing behavior. `ImportWorkflowService` should not duplicate FX table lookup rules.

Add a reusable service method with behavior equivalent to:

```text
ensure_conversion_coverage(
  transactions: iterable of raw currency, reporting currency, transaction date
) -> coverage result
```

The method should:

1. normalize raw and reporting currencies
2. discard identity conversions that need no FX row
3. short-circuit unsupported currencies without fetching
4. derive required ECB quotes using the same pair rules as `CurrencyConversionService`
5. check usable prior-rate coverage for each needed date
6. fetch the narrow missing range when coverage is absent
7. re-check coverage after the fetch
8. report whether coverage is available, unsupported, or still missing

The exact return type can be a small dataclass or enum-backed result. It should avoid a vague boolean so callers can distinguish:

- already covered
- fetched and covered
- unsupported
- attempted fetch but still missing
- fetch failed

### Shared quote derivation

The quote-derivation rule must not diverge between coverage and conversion.

The current conversion rule is:

- `EUR -> USD` requires `USD`
- `USD -> EUR` requires `USD`
- `USD -> BRL` requires both `USD` and `BRL`
- `USD -> USD` requires no quote

Move this rule into a shared helper or make it a public method used by both conversion and coverage. Do not leave a second ad hoc implementation in the import workflow.

### Import review path

`ImportWorkflowService.get_review_payload(...)` should ensure coverage after loading the latest statement draft and before serializing transaction rows.

The workflow should:

1. load the draft transactions for the session
2. build coverage requests from rows with a transaction date
3. call the FX service coverage method with the active reporting currency
4. log coverage failures at warning level
5. serialize rows through the existing `CurrencyConversionService`

Rows with `transaction_date = null` still return the existing unavailable state for missing transaction date and do not participate in the coverage call.

### Startup seed anchor

`ECBExchangeRateService._historical_seed_start_date(...)` should consider both committed transaction dates and import draft dates.

The effective start date is the earliest non-null date from:

- `Transaction.transaction_date`
- `ImportTransactionDraft.transaction_date`

If neither exists, keep the existing fallback of `today - settings.fx_seed_years`.

Draft sessions may be abandoned or superseded. This design accepts the harmless extra coverage caused by old draft dates. Filtering by session lifecycle can be added later if stale drafts become large enough to matter.

### Refresh locking and idempotency

Targeted review refresh should reuse the same lock semantics as startup and scheduled refresh so concurrent refreshes do not race unnecessarily.

The current file lock is local to `main.py`. The implementation should move the lock helper into a small service module, then have both startup refresh and review-time coverage use it.

The user-facing review path needs stricter behavior than the background paths:

- startup and scheduled refreshes may keep their current skip-if-locked behavior
- import review should use a bounded wait for the lock
- after acquiring the lock, import review must re-check coverage before fetching because another refresh may already have filled the rows
- if the bounded wait expires, import review should log a warning and continue with the current unavailable display state

Rate writes are already protected by the unique constraint on:

- `rate_date`
- `base_currency`
- `quoted_currency`
- `source_name`

The refresh path should remain idempotent. If two overlapping refreshes happen anyway, duplicate rows must not be created. The implementation should either prevent overlapping writers through the shared lock or handle duplicate-key conflicts by re-reading the existing row and continuing.

## Error Handling

### ECB fetch failure

If the targeted ECB fetch fails, import review should still return the session payload. The failure should be logged at warning level with:

- session id
- attempted date range
- required quotes
- exception summary

Display-money serialization remains unchanged. Rows that still lack coverage return `missing_rate`.

### Unsupported raw currency

Unsupported raw currencies must not trigger ECB fetches. They should continue through the conversion service and return `unsupported_currency`.

This avoids repeated guaranteed-failing ECB calls for crypto assets or other non-fiat values that cannot be mapped to the supported quote set.

### Non-publication days

Weekends and TARGET closing days should not be treated as exact-date failures. A prior stored publication date is valid.

If the prior publication date is missing locally, the targeted fetch should include enough lookback to retrieve it.

### Partial ECB data

For cross-rate conversions such as `USD -> BRL`, both quotes are required on the selected prior publication date. If only one quote is available after the targeted fill, conversion remains unavailable with `missing_rate`.

## Testing

### ECB service tests

Add coverage tests for:

- supported alias normalization before quote derivation, such as `xUSD -> USD`
- identity conversions requiring no FX rows
- weekend and holiday transaction dates using a prior publication date
- missing coverage triggering a targeted refresh range with lookback
- unsupported raw currency returning an unsupported result without fetch
- refresh failure returning a failed coverage result without raising to import review

### Startup seed tests

Add tests that prove historical seed start date uses the earliest of:

- committed transaction date
- import draft transaction date

Include the case where only import drafts exist.

### Import review API tests

Add tests that prove:

- missing draft-date coverage triggers a targeted ECB refresh before serialization
- review rows show converted display fields after successful targeted refresh
- no refresh occurs when usable prior-rate coverage already exists
- unsupported raw currencies do not trigger refresh and serialize as `unsupported_currency`
- ECB failure does not fail the review response and still serializes missing rows as `missing_rate`

## Migration And Compatibility

No database migration is required.

The design uses existing tables and the existing FX unique constraint. The API response shape does not change. Existing frontend rendering continues to work because it already consumes the explicit display-money fields.

## Relationship To Earlier Specs

This design expands the narrower historical import FX backfill design from post-approval repair to review-time coverage. Post-approval backfill remains useful, but it is no longer sufficient as the primary user-facing guarantee.

## Acceptance Criteria

The implementation is complete when:

1. a fresh database with an import draft dated before committed history can return converted import-review amounts after a successful targeted ECB fill
2. a transaction on a weekend or TARGET closing day uses the prior publication day's rate instead of triggering a needless refresh
3. unsupported raw currencies do not call ECB and remain explicitly unsupported
4. startup historical seed covers pending import drafts as well as committed transactions
5. targeted ECB failure does not prevent loading the import review page
6. backend tests cover successful, already-covered, unsupported, non-publication-day, and fetch-failure paths
