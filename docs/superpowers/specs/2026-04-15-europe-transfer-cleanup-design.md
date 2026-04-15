# Europe Transfer Cleanup Design

Date: 2026-04-15
Status: Draft for review

## Goal

Make Europe-side transfer and settlement data trustworthy enough for the `Transfers & Settlements` section to become useful.

This cleanup pass should stop relying on person-name heuristics such as `Mr ALEXANDRE...` and instead use deterministic account-role rules derived from known IBANs.

## Scope

### In scope

- deterministic classification rules for Europe-side movements using known IBANs
- cleanup of existing Europe-side rows that are currently mislabeled as `Internal Transfer` or `Expense`
- explicit support for:
  - own-account cash transfers
  - credit-card settlement transfers
  - loan repayment transfers
- parser correction for Beobank Mastercard `BETALING` rows so settlement amounts are imported correctly
- readiness criteria for `Transfers & Settlements`

### Out of scope

- any `Wise` row cleanup
- Brazil-side bank statement reconciliation
- PIX payment modeling
- brother-loan modeling through Wise
- fuzzy description-only auto-reclassification
- transfer pair matching as a primary v1 rule

## Problem Statement

The current dataset stores multiple Europe-side money movements under `Transfer / Internal Transfer`, even when those rows represent different real-world meanings:

- moving cash between the user's own bank accounts
- paying the credit-card reimbursement account
- paying the loan account

At the same time, some Europe-side settlement rows are still stored as `Expense / Credit Payment`, which keeps them out of `Transfers & Settlements` and risks distorting analytics when the underlying purchases already exist elsewhere.

There is also a parser defect in Beobank Mastercard statement imports: payment rows such as `BETALING ... -2 677,24` are being imported with the wrong amount because the spaced thousands format is not parsed correctly. In the observed live files, the row still imports, but the regex captures only the final token (`677,24` or `855,74`) as the amount and leaves `-2` behind in the description text. That defect must be fixed before transfer cleanup can be trusted.

## Known Europe Account Roles

The system should treat these accounts as explicit, deterministic identities:

- `BE11 9502 1298 4548` = Beobank normal cash account
- `BE46 0636 5194 6836` = Belfius cash account
- `BE36 9502 6303 0181` = credit-card reimbursement account
- `BE74 9502 2623 0607` = loan account

These roles are the source of truth for the Europe-only cleanup pass.

## Account Role Model

The cleanup logic should not classify directly from raw IBAN to final category. Instead, it should map:

`IBAN -> account role -> classification rule`

This keeps the model understandable and extensible.

### Roles

- `cash_account`
- `credit_reimbursement_account`
- `loan_account`

### v1 rule matrix

- `cash_account -> cash_account`
  - classify as `Transfer / Internal Transfer`

- `cash_account -> credit_reimbursement_account`
  - classify as `Transfer / Credit Card Settlement`

- `cash_account -> loan_account`
  - classify as `Transfer / Debt Repayment Sent`

### Same rule on both legs

If both sides of the same movement are present in imports, both rows should use the same transfer subtype.

Examples:

- money leaving `BE11` toward `BE36`
  - `Transfer / Credit Card Settlement`
- money arriving into `BE36` from `BE11`
  - `Transfer / Credit Card Settlement`

The direction should be represented by transaction sign, not by changing the subtype name.

## Classification Principles

1. Prefer exact IBAN/account-role evidence over names in descriptions.
2. Do not auto-classify Europe rows from free-text names alone.
3. Do not touch `Wise` rows in this pass.
4. Do not silently reclassify rows when no known destination/source account is present.
5. If a row already matches the correct deterministic outcome, leave it unchanged.

## Signal Availability by Import Source

The cleanup pass must use the strongest signal actually available from each import source.

| Import source | Structured `counterparty_account` available? | Primary Europe cleanup signal |
| --- | --- | --- |
| Belfius CSV | Yes | exact `counterparty_account` match |
| Beobank CSV / compact CSV | No | exact known IBAN substring in description |
| Beobank Mastercard PDF | No | exact known IBAN substring in description |

This means the pass must not assume structured counterparty-account matching is available for all Europe-side rows.

## Parser Fix Prerequisite

Before Europe cleanup runs, Beobank Mastercard statement parsing must correctly import payment rows such as:

- `-2 677,24`
- `-2 855,74`

### Required parser behavior

- spaced thousands amounts in `BETALING` rows must be parsed as full amounts, not truncated to the last token
- the sign semantics for card-account payment rows must remain correct at the transaction layer
- imported settlement rows for the card/reimbursement account must reflect the full amount

### Required parser change

The Beobank Mastercard parser must accept both:

- dot-separated thousands amounts
- space-separated thousands amounts

That requires:

- extending `AMOUNT_RE`
- extending `ROW_RE`
- normalizing spaces as well as dots inside `_parse_amount_text`

Without this correction, settlement classification would be built on corrupted values.

## Cleanup Strategy

### Step 1: fix import correctness

Repair the Beobank Mastercard parser so future and re-imported `BETALING` rows are numerically correct.

### Step 2: deterministic Europe reclassification

Run a Europe-only cleanup pass over existing transactions using known account roles.

The pass identity should be:

- `europe_iban_reclassification_v1`

The pass should:

- exclude rows whose description contains `Wise`
- inspect counterparty account fields when present
- inspect exact known IBAN strings when they appear in imported descriptions
- reclassify only when the rule outcome is unambiguous

### Step 3: leave ambiguous rows untouched

Rows that do not expose a known liability or own-account IBAN should not be auto-rewritten in this pass.

That means:

- no guesswork from `Alexandre` alone
- no description-only inference for Europe rows unless the exact known IBAN is present

## Delivery Mechanism

This should ship as a re-runnable migration-style data cleanup function in `backend/app/migrations`.

### Requirements

- the pass must be idempotent
- it must be safe to rerun on already-correct rows
- it must run only after the parser fix for Beobank Mastercard `BETALING` rows is in place

### Why migration-style delivery is preferred

This codebase already uses re-runnable migration functions for data/model transitions. Europe transfer cleanup belongs in the same operational path instead of introducing a separate admin-only endpoint.

### After the pass runs

Because rows will move from `Expense` to `Transfer`, the app must recompute derived analytics tables that depend on transaction type and category semantics, including at minimum:

- financial statistics
- category statistics
- financial health summaries that depend on those aggregates

## Existing Dataset Targets

The following Europe-side rows should become deterministic targets:

### Credit-card settlement targets

Any row showing movement from a cash account to `BE36 9502 6303 0181` should become:

- `transaction_type = Transfer`
- `transfer_category = Credit Card Settlement`
- `expense_category = NULL`
- `income_category = NULL`

This includes both:

- current-account outgoing payment rows
- card-account incoming payment rows, if imported

### Loan repayment targets

Any row showing movement from a cash account to `BE74 9502 2623 0607` should become:

- `transaction_type = Transfer`
- `transfer_category = Debt Repayment Sent`
- `expense_category = NULL`
- `income_category = NULL`

### Own cash-account transfers

Any row showing movement between:

- `BE11 9502 1298 4548`
- `BE46 0636 5194 6836`

should remain:

- `transaction_type = Transfer`
- `transfer_category = Internal Transfer`

## Safety Rules

The cleanup pass must be fail-closed.

### Allowed automatic rewrite cases

- exact known IBAN match in structured account field
- exact known IBAN match in imported description text

### Disallowed automatic rewrite cases

- `Wise` rows
- rows identified only by person name
- rows with missing or conflicting evidence
- rows where the parser fix has not yet been applied to the underlying import source

## Write Invariants

For any row rewritten by this pass:

- `transaction_type` must be set to `Transfer`
- `transfer_category` must be set to the deterministic transfer subtype
- `expense_category` must be set to `NULL`
- `income_category` must be set to `NULL`

The cleanup pass must not leave corrected rows in a mixed legacy state.

## Recurrence Safety

The cleanup pass must not allow an active recurrence rule to immediately reassign corrected Europe-side rows back to legacy expense categories such as `Credit Payment` or `Loan Repayment`.

Implementation may satisfy this by:

- updating matching recurrence patterns to the new transfer semantics, or
- deactivating conflicting recurrence patterns, or
- detaching corrected rows from conflicting recurrence-pattern links

The important invariant is that deterministic Europe settlement rows stay corrected after the pass.

If the implementation deactivates or detaches conflicting patterns rather than migrating them, it must verify that no active recurrence pattern pointing at corrected rows remains after the pass completes. A post-pass assertion is required.

## Analytics Consequences

After this cleanup:

- true own-account cash movements stay in `Internal Transfer`
- card settlements move into `Credit Card Settlement`
- loan repayments move into `Debt Repayment Sent`
- these flows remain visible in `Transfers & Settlements`
- they stay excluded from ordinary expense totals

This gives the section operational meaning instead of lumping everything into one generic bucket.

## Readiness Criteria

`Transfers & Settlements` is considered ready for Europe-side use when all of the following are true:

1. Beobank Mastercard `BETALING` rows import with correct full amounts.
2. Europe-side cash-to-credit-account movements are no longer stored as `Expense / Credit Payment`.
3. Europe-side cash-to-loan-account movements are no longer mixed into `Internal Transfer`.
4. Own-account `BE11 <-> BE46` movements remain `Internal Transfer`.
5. `Wise` rows remain untouched and are explicitly left for a later cleanup phase.

## Non-Goals for This Pass

- no attempt to solve all transfer semantics at once
- no global reconciliation engine
- no automatic loan-to-brother cleanup
- no cross-border transfer correctness guarantees
- no hidden “best guess” rewrite for ambiguous rows

## Recommendation

Implement this as a narrow, deterministic Europe-only cleanup.

Use the known IBANs as the source of truth, keep the rules explicit, and leave `Wise` for a later dedicated pass.
