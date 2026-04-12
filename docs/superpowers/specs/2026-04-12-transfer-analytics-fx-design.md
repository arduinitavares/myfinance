# Transfer Analytics and FX Design

Date: 2026-04-12
Status: Draft for review

## Goal

Make transaction modeling, analytics, and future reconciliation honest for a multi-account, multi-currency setup where:

- card purchases and card settlements both appear in imports
- own-account movements should not be counted as spending
- loans to people should be distinguishable from gifts or support
- analytics must support `EUR`, `BRL`, and `USD` while keeping `EUR` as the fixed reporting currency

The design must preserve the user's core outcome: know what is safe to spend without double-counting the same money movement.

## Problem Statement

The current system stores imported ledger entries as transactions and classifies each one directly into `Income`, `Expense`, or `Transfer`. This is not sufficient when multiple files describe the same underlying money flow at different points in time.

Examples:

- card purchases appear as detailed card-statement expenses
- a later bank payment settles those same purchases as one aggregate movement
- Belgium-to-Brazil own-account movements are real cash transfers but not spending
- loans to a family member are neither regular expenses nor own-account movements

Without a clearer model, the app double-counts spending, overstates expenses in analytics, and makes the AI assistant fight the schema.

## Product Principles

1. Raw imported entries stay visible and auditable.
2. Real consumption should count once.
3. Movements between the user's own buckets must not distort spending metrics.
4. Reporting is fixed in `EUR`, but the original currency and amount are always preserved.
5. Settlement and transfer flows remain visible in a separate control section so the user can verify money movement coverage.

## Scope

### In scope

- Correct `/analytics` semantics for `Transfer`
- Add transfer subtypes for settlement and loan flows
- Add a small `Transfers & Settlements` analytics section
- Add historical FX conversion for normalized reporting in `EUR`
- Preserve original transaction currency and amount
- Prepare the system for later Belgium/Brazil reconciliation and card-settlement linking

### Out of scope

- Full double-entry accounting engine
- Automatic transfer-to-transfer reconciliation across banks in this PR set
- Loan ledger UI beyond classification support and future-safe schema
- Configurable reporting currency
- Full credit-card liability dashboard in v1

## Core Model

The app keeps three top-level movement types:

- `Income`
- `Expense`
- `Transfer`

### Meaning of each type

#### `Expense`

Use for real consumption or obligations that should reduce spending capacity and count in expense analytics.

Examples:

- groceries
- rent
- utilities
- insurance
- card purchases listed individually in card statements

#### `Income`

Use for real inflows that should count in income analytics.

Examples:

- salary
- refunds
- benefits
- investment income

#### `Transfer`

Use for movements of money that are not new consumption and not new earnings.

Examples:

- moving money between own accounts
- paying off a credit card when underlying purchases are already tracked elsewhere
- lending money to another person
- receiving repayment of that loan

Transfers are visible and auditable but excluded from main income and expense totals.

## Transfer Subtypes

The transfer type needs purpose-level distinctions.

### Initial transfer categories

The v1 transfer subtype set should be:

- `Internal Transfer`
- `Credit Card Settlement`
- `Loan to Person`
- `Loan Repayment Received`

### Semantics

#### `Internal Transfer`

Use for own-account movements, including Belgium-to-Brazil transfers between the user's own accounts.

#### `Credit Card Settlement`

Use for paying a card balance after the underlying purchases are already represented as expense transactions elsewhere.

This is not a new expense. It is a settlement movement.

#### `Loan to Person`

Use when money is sent to another person with the expectation of repayment.

This is not a normal expense and should not appear in spending totals.

#### `Loan Repayment Received`

Use when money is received back from a previously issued personal loan.

This is not salary or new earned income.

### Non-goal for v1

Do not auto-default family transfers to loan vs. support. The user will classify those explicitly with the assistant or manual controls.

## Credit Card Rule Set

This design adopts one explicit rule:

### Rule

When detailed card purchases exist, they are the real expenses.

The later bank-side payment that settles the card should be modeled as:

- `Transfer`
- subtype `Credit Card Settlement`

### Consequence

Main spending analytics must count the detailed purchases and exclude the later settlement movement.

This matches the user's goal of seeing spending pressure when the purchase happens, not only when the bank account is charged later.

## Analytics Design

### Main analytics cards

The main `/analytics` cards must use only:

- `Income` for income totals
- `Expense` for expense totals

`Transfer` is excluded from:

- total income
- total expenses
- net savings
- savings rate
- essential vs discretionary expense breakdown
- category expense totals

### Separate control section

Add a small separate section on `/analytics`:

- `Transfers & Settlements`

Purpose:

- provide visibility into cash movements that are intentionally excluded from spending metrics
- let the user verify that important transfers are being captured
- provide confidence that "ignored in totals" does not mean "hidden"

### Initial section contents

The first version should include:

- total outgoing transfers for the current period, normalized to `EUR`
- total incoming transfers for the current period, normalized to `EUR`
- breakdown by transfer subtype
- a short list or compact summary of recent transfer totals by subtype

The section should be clearly distinct from spending analytics.

### `/analytics` behavior summary

- expenses card: excludes all transfers
- income card: excludes all transfers
- category charts: exclude all transfers
- transfer section: includes only transfers

## FX Design

The reporting currency is fixed to `EUR`.

### Rules

1. Keep original imported values immutable:
   - `amount`
   - `currency`
   - `transaction_date`
2. Add historical FX conversion for reporting.
3. Use the transaction date's FX rate for normalized historical reporting.
4. Do not overwrite original transaction values.

### Data model additions

Each transaction should eventually have access to:

- `fx_rate_to_eur`
- `amount_eur`

These can be stored or materialized during statistics generation, but the design requirement is that historical reports use date-appropriate conversion, not today's rate.

### FX source table

Add a daily FX table keyed by:

- `rate_date`
- `source_currency`
- `target_currency` (`EUR` in practice)

At minimum support:

- `EUR`
- `BRL`
- `USD`

`EUR -> EUR` should be treated as `1.0`.

### UI behavior

Transactions continue to show original currency and amount in the transaction list.

Analytics uses `EUR`-normalized values.

Optionally, later UI can show:

- original amount
- converted `EUR` amount
- rate date used

## Reconciliation Readiness

The design should prepare for, but not yet fully implement, linkages between related entries.

### Future reconciliation targets

- Belgium outgoing own-account transfer <-> Brazil incoming own-account transfer
- credit card purchase set <-> later bank-side card settlement
- `Loan to Person` <-> `Loan Repayment Received`

### v1 requirement

The classification and analytics model must not block this future linking.

That means:

- transfers remain first-class records, not silently discarded
- settlement transfers stay visible
- FX normalization uses transaction date so cross-country movement analysis remains historically coherent

## Data Model Changes

### Transaction categories

The current schema stores transfer classifications by forcing transfer rows into `Internal Transfer`. This must be generalized.

Add transfer-specific category support rather than forcing all transfers into the existing income/expense enums.

Recommended shape:

- add `TransferCategory` enum in backend and frontend
- add a `transfer_category` column to `transactions`
- preserve `expense_category` for `Expense`
- preserve `income_category` for `Income`
- use `transfer_category` for `Transfer`

Initial `TransferCategory` values:

- `Internal Transfer`
- `Credit Card Settlement`
- `Loan to Person`
- `Loan Repayment Received`

### Classification commit rules

Current transfer normalization always rewrites transfers to `Internal Transfer`. That must change.

New rule:

- `Expense` -> use `expense_category`
- `Income` -> use `income_category`
- `Transfer` -> use `transfer_category`

### Statistics rules

Statistics generation must stop treating "not income" as expense.

Explicit logic is required:

- if `transaction_type == Income`, add to income totals
- if `transaction_type == Expense`, add to expense totals
- if `transaction_type == Transfer`, exclude from main totals and include only in transfer metrics

This rule must be applied consistently to:

- overview cards
- net savings
- savings rate
- yearly averages
- category statistics
- essential vs discretionary calculations
- time-series charts

## Classification Assistant Changes

The assistant must follow the app contract, not invent its own ontology.

### Required changes

- allowed type/category options must be passed explicitly
- transfer proposals must use only valid transfer subtypes
- invalid model outputs must be rejected at the provider boundary

This is already partially aligned with the current provider-hardening work and must remain true after transfer subtypes are added.

### UX implication

When classifying a transfer, the modal should show transfer subtype options, not expense or income categories.

## Loan Tracking Readiness

The user wants to later track how much has been lent to a brother.

This design does not require a full loan dashboard yet, but it should preserve the necessary semantics.

### Minimum readiness requirement

`Transfer / Loan to Person` and `Transfer / Loan Repayment Received` must exist so future outstanding-balance logic can be built on top of real categorized history.

### Future direction

Later phases can add:

- person entity
- outstanding balance by person
- original-currency and EUR-equivalent loan views

## Migration and Rollout

### Recommended order

1. Add `TransferCategory` and update commit logic.
2. Fix statistics so transfers no longer count as expenses.
3. Update `/analytics` to show the small `Transfers & Settlements` section.
4. Add historical FX data model and EUR-normalized reporting.
5. Extend the assistant and transaction UI to support transfer subtypes cleanly.
6. Later add reconciliation and person-level loan tracking.

### Backfill policy

Existing transfer rows with `Internal Transfer` semantics should migrate to:

- `transaction_type = Transfer`
- `transfer_category = Internal Transfer`

No attempt is required in the first migration to auto-detect which historical transfers were really card settlements or person loans.

## Testing

### Backend

- transfer transactions are excluded from main statistics totals
- transfer transactions appear in separate transfer metrics
- transfer subtype persists correctly via commit flow
- invalid assistant response values outside the transfer contract are rejected
- FX conversion uses transaction-date rate, not current-day rate

### Frontend

- analytics main cards remain unchanged by transfer-only imports
- transfer section shows transfer totals separately
- transfer rows show transfer category correctly
- classification modal shows transfer subtype options for transfer rows

## Acceptance Criteria

1. A card settlement can be classified as `Transfer / Credit Card Settlement`.
2. That settlement no longer inflates expense totals in `/analytics`.
3. Main income, expense, and net-savings metrics ignore all transfers.
4. `/analytics` includes a separate `Transfers & Settlements` section for verification.
5. Transactions in `BRL`, `USD`, and `EUR` can be reported in normalized `EUR` values using historical daily rates.
6. Own-account Belgium/Brazil movements can remain visible without counting as spending.
7. Loans to a person can be classified separately from internal transfers and normal expenses.

## Open Questions

1. Should the transfer section show both original-currency totals and EUR-normalized totals in v1, or only EUR-normalized totals with drill-down later?
2. What FX source should be used for daily rates in local/offline-friendly development?
3. Should `Loan to Person` require a person link in v1, or stay as a pure transfer subtype until the person model lands?
