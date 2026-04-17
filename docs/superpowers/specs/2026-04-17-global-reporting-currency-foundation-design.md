# Global Reporting Currency Foundation Design

Date: 2026-04-17
Status: Draft for review

## Goal

Introduce a single, app-wide reporting currency system that:

- defaults to `EUR`
- allows the user to switch globally between `EUR`, `USD`, and `BRL`
- persists that choice across sessions
- displays money consistently in the selected reporting currency across the app
- keeps imported ledger truth immutable underneath

This foundation exists so future import work, including Nexo and later Brazilian bank imports, can rely on one clean currency model instead of inventing importer-specific conversion rules.

## Problem Statement

The app currently assumes the stored transaction currency is the displayed currency. That becomes confusing as soon as imported data spans more than one currency.

The user wants one mental model:

- choose a reporting currency once
- see transaction lists, analytics, import review, and AI classification in that currency
- change the currency anytime without changing ledger truth

Without a shared foundation, each importer or screen would make its own currency decisions. That would create inconsistent displays, duplicated FX logic, and historical totals the user would not trust.

## Product Principles

1. Imported ledger truth remains immutable.
2. Display currency is a user preference, not a data rewrite.
3. All user-facing money surfaces use the same reporting currency.
4. Historical conversion must be deterministic and reproducible.
5. The architecture must stay extensible for future `BRL` bank imports and future Nexo work.

## Approaches Considered

### Approach A: Dynamic conversion everywhere from raw data plus historical FX table

Keep raw transaction values unchanged, store historical daily reference rates, and derive display values on the backend for the selected reporting currency.

Pros:

- single source of truth
- cleanest architecture
- easy to trust historically
- future importers reuse the same foundation

Cons:

- requires explicit backend conversion plumbing
- more response-shaping work

### Approach B: Store cached converted values for all supported reporting currencies

Persist derived amounts such as `amount_eur`, `amount_usd`, and `amount_brl` on transactions and drafts.

Pros:

- simpler reads
- potentially faster rendering

Cons:

- drift risk if FX logic or historical rates are corrected
- more recomputation and cache invalidation work
- derived values start to look like first-class ledger truth

### Approach C: Rewrite transactions into the selected reporting currency

Replace or overload stored transaction amounts with the active reporting currency.

Pros:

- simplest-looking UI

Cons:

- wrong ledger model
- historical values become untrustworthy
- selected currency would mutate business data

### Recommendation

Use **Approach A**.

The system should preserve one canonical raw transaction and one shared FX reference layer, then derive display values consistently for all UI surfaces.

## Scope

### In scope

- global reporting currency preference
- supported reporting currencies:
  - `EUR`
  - `USD`
  - `BRL`
- persisted preference with `EUR` as default
- historical daily FX reference-rate storage
- backend currency conversion service
- converted display values across:
  - transaction lists
  - analytics cards and charts
  - transfer summaries
  - import review pages
  - AI classification modal
- deterministic fallback when a daily rate is missing
- additive API contract for raw and display values

### Out of scope

- arbitrary currency support beyond `EUR`, `USD`, and `BRL`
- user-editable FX rates
- intraday FX conversion
- replacing raw imported values in the database
- dual display of original and converted values in normal UI
- Nexo CSV parsing rules
- reconstructing missing merchant-native currency when an import source does not provide it

## Relationship To Existing FX Work

This design supersedes the earlier fixed-`EUR` reporting assumption in [2026-04-12-transfer-analytics-fx-design.md](/Users/aaat/myfinance/docs/superpowers/specs/2026-04-12-transfer-analytics-fx-design.md).

That earlier spec remains directionally correct about:

- immutable raw amount and currency
- historical daily FX usage
- fallback to most recent prior rate

But this new design changes one core rule:

- reporting currency is no longer fixed to `EUR`
- reporting currency is now a global user preference with a bounded currency set

## Core Architecture

The foundation is split into three layers.

### 1. Ledger truth layer

Transactions and import drafts remain stored exactly as imported:

- `amount`
- `currency`
- `transaction_date`

These fields are canonical business data and are never rewritten when the user switches reporting currency.

### 2. FX reference layer

The backend stores daily official reference rates and exposes one conversion service that can convert any supported source currency into any supported reporting currency for a given historical date.

### 3. Presentation layer

Every UI money surface requests and renders display-ready values in the currently selected reporting currency.

The frontend must not perform FX math itself.

## Supported Currency Model

### Raw transaction currency

A raw transaction can be in any imported currency, but v1 guarantees full display support only for:

- `EUR`
- `USD`
- `BRL`

If later imports introduce another currency, that import work must either extend the supported FX set or block/review unsupported rows explicitly.

### Reporting currency

The active reporting currency is a global app preference.

Allowed values:

- `EUR`
- `USD`
- `BRL`

Default:

- `EUR`

Persistence for v1:

- frontend local persistence, since the app is effectively single-user

Future direction:

- preference can later move to a server-side user profile without changing the conversion model

## FX Source Design

### Source choice

Use the **ECB euro foreign exchange reference rates** as the v1 source of truth.

Rationale:

- official and well-documented
- stable daily reference rates
- provides both `USD` and `BRL`
- has bulk downloads and API access
- cleaner long-term foundation than Yahoo-style unofficial market wrappers

### Source representation

The ECB publishes rates with `EUR` as the reference currency.

For example:

- `1 EUR = 1.1797 USD`
- `1 EUR = 5.8707 BRL`

The system should store source-native daily rates rather than redundant pairwise rates.

## FX Data Model

Add a dedicated table for source-native daily rates.

### `fx_daily_reference_rates`

Columns:

- `rate_date DATE NOT NULL`
- `base_currency VARCHAR(3) NOT NULL`
- `quoted_currency VARCHAR(3) NOT NULL`
- `units_per_base DECIMAL(18,8) NOT NULL`
- `source_name VARCHAR(32) NOT NULL`
- `fetched_at TIMESTAMP NOT NULL`
- `updated_at TIMESTAMP NOT NULL`

Constraints:

- unique on `(rate_date, base_currency, quoted_currency, source_name)`

V1 rules:

- `base_currency` is always `EUR`
- `source_name` is always `ECB_EXR`
- no stored row is required for `EUR -> EUR`; that is handled as a built-in identity conversion

## Conversion Rules

### Identity rule

If raw currency and reporting currency are the same:

- `display_amount = raw_amount`
- `display_currency = raw_currency`
- `display_fx_rate = 1.0`

### Effective-date rule

Use the transaction date's daily reference rate.

If no rate exists for the exact date:

- use the most recent prior available daily rate

If no prior rate exists:

- conversion fails explicitly
- the UI must show an unavailable state instead of fake math

### Pairwise derivation rule

The service derives non-`EUR` pairwise conversions through `EUR`.

Given:

- `eur_to_usd = units_per_base(EUR, USD)`
- `eur_to_brl = units_per_base(EUR, BRL)`

Examples:

- `EUR -> USD = eur_to_usd`
- `USD -> EUR = 1 / eur_to_usd`
- `USD -> BRL = eur_to_brl / eur_to_usd`
- `BRL -> USD = eur_to_usd / eur_to_brl`

### Amount conversion rule

For a raw amount `raw_amount` in `raw_currency`, displayed in `reporting_currency`:

- convert through the effective daily pairwise rate
- preserve the original sign
- perform calculation with `Decimal`
- round only at the display boundary, not in internal conversion steps

### Precision rule

Even though existing transaction amounts are currently stored as floating-point values, all FX rates and all conversion math in the new service must use `Decimal` internally after coercion from raw values.

This avoids compounding binary-floating precision issues across chained conversions.

## Backend Conversion Service

Introduce one dedicated currency-conversion module responsible for:

- resolving the active reporting currency
- locating the effective daily rate date
- deriving pairwise rates across supported currencies
- returning converted display amounts

This service must be the only backend path allowed to perform FX math for user-facing data.

No endpoint or serializer may implement ad hoc conversion logic inline.

## Reporting Currency Resolution

### Request contract

The frontend should send the active reporting currency on every API request through a single shared transport mechanism.

V1 recommendation:

- an HTTP header such as `X-Reporting-Currency`

Reasons:

- avoids adding currency query parameters across many endpoints
- centralizes frontend behavior in one request layer
- keeps endpoint signatures cleaner

### Backend resolution rules

For every request:

1. read `X-Reporting-Currency`
2. validate against allowed values:
   - `EUR`
   - `USD`
   - `BRL`
3. if missing, default to `EUR`
4. if invalid, return a validation error rather than silently guessing

## API Contract Design

### Principle

Do not overload existing raw amount fields to mean display values.

That would silently change API semantics and make downstream logic brittle.

### Line-item responses

For endpoints returning transactions or drafts, keep raw fields unchanged and add display fields.

Required additive fields:

- `display_amount`
- `display_currency`
- `display_fx_rate`

Optional future debug field:

- `display_rate_date`

Examples of affected response shapes:

- transaction list items
- import draft rows
- classification modal transaction payloads

### Aggregate responses

For analytics payloads, values are already aggregate displays rather than raw ledger truth. Those responses should become reporting-currency-aware directly.

Required rule:

- every aggregate response must include `reporting_currency`

Required naming rule:

- avoid hard-coded `*_eur` field names in currency-aware aggregate payloads
- replace or version them with currency-neutral names such as:
  - `total_outgoing`
  - `total_incoming`
  - `total_expenses`
  - `total_income`

This prevents the API from lying about units once the selected reporting currency is not `EUR`.

## Frontend Design

### Global control

Add one global reporting-currency dropdown in app chrome.

V1 options:

- `EUR`
- `USD`
- `BRL`

Default:

- `EUR`

Persistence:

- local storage under one explicit app-owned key, for example `reporting_currency`

### UI rule

All normal user-facing money values render in the active reporting currency only.

That includes:

- transaction rows
- dashboard cards
- charts
- transfer summary card
- import review rows
- AI classification modal

### Non-goal for v1

Do not show original and converted values side by side in the normal UX.

The user explicitly wants one active currency lens at a time.

## Import Review And AI Modal Behavior

Import review and AI classification must use the same display-currency contract as the rest of the app.

This means:

- review screens display `display_amount` and `display_currency`
- AI classification modal shows the converted amount in the active reporting currency
- approval, rejection, and classification writes still commit the raw imported transaction truth

The selected reporting currency affects what the user sees, not what the import pipeline stores.

## Failure Handling

### Missing FX rate

If conversion cannot be completed because no exact or prior daily rate exists:

- backend marks the display amount unavailable
- frontend shows a clear unavailable state
- backend does not fabricate `0`, reuse a future rate, or guess

### Source update failure

If the daily FX refresh job fails:

- existing historical rates remain usable
- imports and UI remain functional for dates already covered
- system logs the failure explicitly

### Unsupported currency

If a raw transaction currency falls outside the supported display set and cannot be converted through the stored rate table:

- the backend returns an explicit unsupported-conversion result
- the UI surfaces that state clearly
- no silent fallback to raw display should occur in normal UX

## Seeding And Refresh Strategy

V1 needs both:

1. a historical seed for the supported currencies
2. a periodic refresh for new dates

Recommended behavior:

- seed historical `USD` and `BRL` ECB daily rates for the date span covered by existing transactions
- run an idempotent startup catch-up that fetches recent missing working-day rates for supported currencies over a bounded window

V1 delivery shape:

1. a re-runnable historical seed path for the existing transaction date span
2. a bounded startup catch-up for recent missing supported rates

The seed and refresh mechanism must be deterministic and re-runnable.

## Interaction With Future Importers

This foundation is intentionally importer-agnostic.

Examples:

- a Belfius EUR import remains raw `EUR`
- a future Brazilian bank BRL import remains raw `BRL`
- a Nexo import can keep its chosen raw transaction currency while still benefiting from app-wide converted display

This is why the FX/UI foundation should be built before the Nexo importer spec.

## Testing Strategy

### Unit tests

- pairwise conversion math for all supported currency pairs
- identity conversion
- prior-date fallback behavior
- missing-rate failure behavior
- header validation for reporting currency

### Service tests

- transaction serializer emits correct `display_*` fields
- analytics services emit `reporting_currency`
- aggregate values use the selected reporting currency, not fixed `EUR`

### Frontend tests

- global dropdown defaults to `EUR`
- currency selection persists across reloads
- request layer sends the reporting currency on API requests
- transaction list rerenders in the new currency
- import review rerenders in the new currency
- AI modal rerenders in the new currency

### Regression tests

- switching reporting currency never mutates raw transaction data
- historical reports remain stable for a fixed FX table snapshot
- existing `EUR`-only transactions still render correctly with identity conversion

## Readiness Criteria

This foundation is ready for implementation when the team can build all of the following without guessing:

1. one canonical raw transaction model remains unchanged
2. one official daily-rate source is chosen and explicit
3. one deterministic conversion service owns all FX math
4. one global reporting currency preference controls the whole app
5. API contracts make raw and display amounts explicit
6. no response field lies about being `EUR` when it may now be `USD` or `BRL`

## Follow-up Work

After this foundation lands, the next spec should define:

- Nexo CSV parsing
- which Nexo row types are true ledger rows
- how Nexo fees and purchases map into raw transaction truth

That follow-up spec should rely on this currency foundation rather than inventing Nexo-specific display rules.
