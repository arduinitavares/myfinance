# Reporting Currency Core Surfaces Design

Date: 2026-04-18
Status: Draft for review

## Goal

Complete the reporting-currency rollout for the app's most important money surfaces so the user can rely on the product now for day-to-day use.

This phase covers:

- transactions
- core analytics and dashboard surfaces
- import review
- AI classification modal

This phase must remove legacy EUR-only behavior from those scoped surfaces. The selected reporting currency becomes the only intended display behavior for them.

## Product Intent

The app must become trustworthy before broader importer work continues.

The immediate user workflow is:

1. upload more Belgium files
2. upload future Nexo files
3. upload future Brazil files
4. use the app right away for transactions and analytics

That means the system cannot wait for a full all-feature reporting-currency completion before becoming useful. The scoped surfaces in this document are the minimum set that must become correct now.

## Scope

### In scope

- transaction list and transaction-facing money displays
- core analytics and dashboard money surfaces
- import review money displays
- AI classification modal money displays
- backend normalization for a bounded set of raw imported aliases:
  - `xUSD -> USD`
  - `EURX -> EUR`
  - `USDC -> USD`
- explicit unavailable states for currencies still unsupported after normalization
- removal of legacy fixed-EUR display behavior from scoped analytics surfaces

### Out of scope

- full Nexo importer behavior
- arbitrary currency support
- broad crypto-native asset support
- preserving lower-priority product areas during this phase
- legacy compatibility for old EUR-only dashboard behavior
- importer rules for cashback, exchange mechanics, credit-line internals, or other bounded Nexo row semantics

## Non-Goals

This phase does not try to solve the full Nexo problem.

It prepares the path for the next Nexo importer phase by making the important user-facing display system correct first. Full Nexo CSV support remains a separate design effort.

## Design Principles

1. No legacy behavior on scoped surfaces.
2. Correctness and consistency beat reuse of stale aggregate tables.
3. Raw ledger truth remains immutable.
4. The backend owns normalization and FX conversion.
5. The frontend renders display-ready values and does not invent currency behavior.
6. Unsupported conversions fail explicitly; they never silently fall back to mislabeled EUR.

## Surface Scope

### Transactions

The transaction list and related transaction-facing views must show money using the selected reporting currency whenever conversion is available.

If conversion is unavailable, the UI must show an explicit unavailable state while preserving raw amount context.

### Core Analytics

Core dashboard and analytics surfaces must stop mixing:

- reporting-currency-aware values
- persisted EUR-only values

The user should never have to guess whether one chart or tooltip is still fixed to EUR.

### Import Review

Import review must use the same display-money rules as transactions so the user can inspect imported files in the currently selected reporting currency before finalizing work.

### AI Classification Modal

The AI classification modal must show the same money interpretation as the transaction list. The user must not see one amount in the table and a different meaning in the classification flow.

## Scoped Surface Inventory

The implementation plan for this phase should treat the following surfaces as the required target set.

### Transaction-facing surfaces

- transaction list and transaction detail rendering paths backed by the transactions API
- transaction payloads shown inside the AI classification flow

### Import review surfaces

- import review page transaction rows
- import batch flows that link into review and summarize supported versus unsupported files

### Analytics and dashboard surfaces

- overview cards backed by `/statistics/overview`
- transfer summary backed by `/statistics/transfers/summary`
- category breakdown backed by `/statistics/by-category`
- category trends backed by `/statistics/by-category`, `/statistics/timeseries`, and `/statistics/category/timeseries`
- category averages backed by `/statistics/category/averages`
- timeseries and monthly heatmap views backed by `/statistics/timeseries`
- expense-type breakdowns and charts backed by `/statistics/by-expense-type` and `/statistics/expense-type/timeseries`

The current known fixed-EUR frontend surfaces inside this scope are:

- `CategoryBreakdown`
- `CategoryTrends`
- `CategoryAverages`
- `CategoryTimeseriesChart`
- `ExpenseTypeTimeseriesChart`
- `TimeseriesChart`
- `MonthlyHeatmap`

These views are explicitly in scope for removing `PERSISTED_STATISTICS_CURRENCY` behavior.

## Architecture

The scoped surfaces move to one backend-owned money pipeline:

1. raw truth stays unchanged in storage
2. backend applies bounded currency normalization where agreed
3. backend converts to the selected reporting currency when possible
4. backend returns display-ready money or an explicit unavailable state
5. frontend renders that state consistently across all scoped surfaces

This keeps importer logic separate from display logic while still providing immediate product value.

## Raw Truth Model

Transactions and import drafts remain stored with source-native raw fields such as:

- `amount`
- `currency`
- `transaction_date`

Those values remain the ledger truth. Switching reporting currency must never mutate them.

## Bounded Currency Normalization

For this phase, the backend adds a small normalization step before conversion for the scoped surfaces only.

Allowed normalizations:

- `xUSD -> USD`
- `EURX -> EUR`
- `USDC -> USD`

These mappings are a best-effort usability choice for this phase. They are not a claim that the original instrument was literally fiat cash in all business contexts.

Everything else remains unsupported unless already covered by the existing FX support set.

## Conversion Contract

For scoped line-item surfaces, the backend should return display-money fields using one consistent path:

- `display_amount`
- `display_currency`
- `display_fx_rate`
- `display_rate_date`
- explicit availability metadata such as `display_is_available`
- explicit unavailable metadata such as `display_unavailable_reason`

Behavior:

- if the normalized raw currency equals the selected reporting currency, display is identity
- if the normalized raw currency is supported, convert through the existing historical FX layer
- if the normalized raw currency is still unsupported, return an explicit unavailable state

Raw fields remain available for context, but the frontend should not infer conversion logic from them.

## Aggregate Contract

For scoped analytics surfaces, API responses must:

- include `reporting_currency`
- expose currency-neutral field names
- represent already-converted values in the selected reporting currency
- include a `conversion_summary`-style metadata object for any partially convertible result set

The aggregate conversion metadata should be sufficient for the UI to stay truthful without reconstructing backend decisions. At minimum it should communicate:

- `converted_transaction_count`
- `unavailable_transaction_count`
- `unavailable_currencies`

After this phase, the frontend for scoped analytics must not need to decide whether a value is:

- selected-currency-aware
- secretly still EUR-backed

That decision belongs in the backend only.

## Backend Changes

### 1. Add normalization utility

Introduce a focused backend utility that normalizes the bounded alias set before conversion for the scoped surfaces.

Responsibilities:

- accept raw imported currency code
- map supported aliases to reporting-currency-foundation currencies
- preserve unsupported values as unsupported

### 2. Route line-item serializers through normalization plus conversion

The following APIs must use the same normalized conversion path for scoped responses:

- transactions API
- import review API
- AI modal transaction payload path

The existing serializer path already emits `display_amount`, `display_currency`, `display_fx_rate`, and `display_rate_date`. This phase must extend that contract to also emit explicit availability metadata so unsupported rows can be rendered honestly instead of disappearing into `null` display fields.

### 3. Remove scoped analytics dependence on legacy EUR-only aggregates

The backend must calculate reporting-currency-aware analytics from raw transactions for the scoped views.

That means replacing or bypassing the old persisted aggregate-table reads where they are still EUR-bound for these surfaces.

Persisted statistics rows may continue to exist for other product areas or background refresh behavior, but they cannot remain the money source of truth for the scoped analytics surfaces in this phase.

Correctness requirement:

- selected `USD` or `BRL` must not be represented by stale EUR values on any scoped analytics view
- scoped endpoints must either return selected-currency values or an explicit partial/unavailable state

### 4. Explicit unavailable outcomes

If a row or value cannot be converted after normalization:

- line-item APIs return explicit unavailable display metadata
- aggregate APIs avoid lying about totals

For this phase:

- line items show an unavailable state per row
- aggregates exclude unconvertible rows from money totals
- counts should remain truthful where feasible
- responses should expose enough metadata for the UI to avoid fake precision

## Frontend Changes

### Transactions

Transaction-facing components must prefer backend display fields over raw money fields whenever display fields are present.

The transaction UI must stop assuming raw `amount` plus raw `currency` is the correct display behavior.

### Analytics

Scoped dashboard components must consume only reporting-currency-aware analytics responses from the backend.

The temporary fixed-EUR branch represented by `PERSISTED_STATISTICS_CURRENCY` must disappear from the scoped analytics views.

### Import Review

Import review rows must render display-ready amounts using the same shared money-display behavior as the transaction list.

### AI Classification Modal

The classification modal must render the same transaction money interpretation as the transaction list.

## UX Rules

1. The global reporting-currency selector remains the single control point.
2. Changing the selected reporting currency should update every scoped surface without per-screen caveats.
3. If conversion is unavailable, the UI should say so clearly and preserve raw context.
4. No scoped surface should silently show fixed EUR while implying another reporting currency.

## Error Handling

### Unsupported or unconvertible line item

The UI should show:

- explicit unavailable state
- raw amount and raw currency context when useful

It should not:

- invent a converted amount
- silently fall back to EUR while labeling the value as another reporting currency

### Partially convertible aggregate set

Aggregate endpoints must avoid pretending the response is complete if some rows were excluded from conversion-sensitive totals.

The response should expose enough information for the frontend to remain truthful, even if the initial UI treatment is minimal.

## Testing Strategy

### Backend tests

- normalization unit tests for `xUSD`, `EURX`, and `USDC`
- conversion tests proving normalized currencies flow through the current reporting-currency conversion path
- API tests for:
  - transactions
  - import review
  - scoped analytics endpoints
  - AI modal transaction payloads
- regression tests showing scoped analytics no longer return mislabeled EUR-backed values under `USD` or `BRL`

### Frontend tests

- transaction rendering tests for reporting-currency display and unavailable-state handling
- import review tests for converted display behavior
- AI modal tests for amount consistency with the transaction list
- focused analytics tests for the currently known broken surfaces

## Manual Success Criteria

After this phase:

1. Switching between `EUR`, `USD`, and `BRL` updates all scoped surfaces consistently.
2. No scoped analytics surface silently renders fixed EUR values when another reporting currency is selected.
3. Transaction list, import review, and AI modal all follow the same display-money rules.
4. `xUSD`, `EURX`, and `USDC` behave according to the bounded normalization rules for this phase.
5. Unsupported currencies outside that set fail explicitly rather than deceptively.

## Relationship To The Next Nexo Phase

This phase is intentionally upstream of bounded Nexo CSV import work.

Once this design is implemented:

- the app will have trustworthy transactions, analytics, import review, and AI modal displays
- the next Nexo importer design can focus on row semantics instead of compensating for inconsistent display behavior

That next phase should separately define:

- which Nexo row types become real app transactions
- which rows are skipped as internal mechanics
- how cash-out rows map to transfers
- how cashback or crypto-native assets should appear, if at all

## Implementation Boundary

This spec is intentionally narrow enough for one implementation plan:

- one display-correctness phase
- one bounded normalization layer
- one set of target surfaces

It does not attempt to solve the full importer problem at the same time.
