# Expense Completeness Implementation Roadmap

Date: 2026-07-10
Status: Approved design, implementation not started
Design: [MyFinance Expense Completeness Operating Model](../specs/2026-07-10-myfinance-expense-completeness-operating-model-design.md)

## Delivery Strategy

The approved design crosses database safety, file intake, expense semantics, classification, currency conversion, and reporting. Implementing all of it in one branch would make review and recovery unsafe. Delivery is split into five ordered slices. Each slice must leave working, testable software and pass the repository gates before the next slice begins.

```text
1. Quality and database safety
   -> 2. Statement streams and coverage
      -> 3. Expense and card correctness
         -> 4. Private classification and financial costs
            -> 5. Working and Verified expense reporting
```

## Slice 1: Quality and Database Safety

Detailed plan: [Quality and Database Safety Implementation Plan](2026-07-10-quality-and-database-safety.md)

Deliverables:

- `pyrepo-check --all` audits repository-owned Python and runs from the repository root.
- CI runs the same Python gate used locally.
- Owned Python contains no `noqa`, `type: ignore`, `nosec`, disabled-rule, or configuration-rule suppressions.
- SQLite migrations create and verify a backup before changing an existing database.
- Failed migrations restore the pre-migration database.
- One tested CLI command restores a selected backup.
- Database reset is available only from an explicitly confirmed development or test CLI command.
- `/debug/reset-database` no longer exists.
- CORS accepts only the configured local frontend origin.

This slice satisfies acceptance criteria 11 and 12 and establishes the Python half of criterion 13.

## Slice 2: Statement Streams and Coverage

Primary code boundaries:

- `backend/app/statement_streams/contracts.py`: registry value objects and enums.
- `backend/app/statement_streams/registry.py`: strict `statement-streams.yml` loading and validation.
- `backend/app/statement_streams/coverage.py`: due-date and slot-state calculation.
- `backend/app/models/statement_stream.py`: persisted streams, slots, and source links.
- `backend/app/imports/batch_folder.py`: supported-tree recursive discovery.
- `backend/app/imports/detection.py`: adapter selection by registered `source_format`.
- `backend/app/routers/coverage.py` and `backend/app/schemas/coverage.py`: coverage API.
- `frontend/src/components/coverage/`: Coverage Calendar and manual no-activity confirmation.

Deliverables:

- Strict version-1 registry validation for safe aliases, holders, products, currencies, source formats, schedules, and coverage start.
- Derived `supported/<institution>/<account-alias>/<YYYY>/<YYYY-MM>/` paths, where `YYYY-MM` is the Statement Period end month.
- Recursive scanning only under `bank_files/supported/`.
- No import attempts under `bank_files/pending-support/`.
- New institution support starts from a local pending file and a GitHub issue containing only metadata plus redacted or synthetic evidence.
- Statement Slots labeled by Statement Period end month.
- Separate source, review, and reconciliation states.
- Explicit no-activity confirmation; empty folders never imply no activity.
- Sign-neutral import proposals, including removal of Beobank debit-equals-Expense and credit-equals-Income shortcuts.

This slice satisfies acceptance criteria 1, 2, 3, and 5.

## Slice 3: Expense and Card Correctness

Primary code boundaries:

- `backend/app/services/expense_policy.py`: canonical report inclusion rules.
- `backend/app/models/reconciliation.py`: card statements, settlement links, Movement Chains, and Event Allocations.
- `backend/app/services/card_reconciliation.py`: unpaid, partial, full, and overpaid settlement calculation.
- `backend/app/services/movement_chain.py`: links used only to prevent false Income, duplicate Expenses, missing Expenses, or missing Financial Costs.
- Existing transaction schemas, import approval, and classification commit services.
- Card reconciliation API and review UI.

Deliverables:

- Internal movements remain Transfers.
- Borrowed funds never become Income.
- Cash withdrawals and Debt Repayments are Expenses under the approved policy.
- Credit Card Purchases remain itemized Expenses.
- Credit Card Settlements reconcile one or more payments without creating another Expense.
- Every imported transaction requires an Operator-reviewed type and category.

This slice satisfies acceptance criteria 4 and 6 and establishes the principal-versus-cost boundary required by criterion 9.

## Slice 4: Private Classification and Financial Costs

Primary code boundaries:

- `backend/app/services/category_suggestion_service.py`: local similarity without private-content logging.
- `backend/app/services/classifier_providers/prompts.py`: minimum sanitized external request.
- `backend/app/services/classification_session_service.py`: explicit external-request consent and proposal-only results.
- `backend/app/services/financial_costs.py`: Applied Rate, Reference Rate, Explicit Cost, Exchange-Rate Cost, Realized Cost, and Cost Pending.
- Existing ECB, currency conversion, and Reporting Currency services.

Deliverables:

- Local deterministic evidence and cosine similarity run before external classification.
- External classification requires Operator consent and receives no full statements, identifiers, references, or names.
- Logs contain no descriptions, prompts, amounts, identifiers, or statement text.
- Confirmed corrections update local suggestions without silently changing historical or future records.
- Original Amounts remain intact for EUR, USD, and BRL.
- Applied Rates come only from provider evidence or linked origin and destination amounts.
- Missing conversion evidence produces Cost Pending rather than a false cost.
- Financial Costs enter Expense totals without transferred principal.

This slice satisfies acceptance criteria 8, 9, and 10.

## Slice 5: Working and Verified Expense Reporting

Primary code boundaries:

- `backend/app/services/expense_reporting.py`: evidence-aware expense queries.
- Existing statistics and Reporting Currency services for aggregation only.
- `backend/app/routers/statistics.py` and new coverage endpoints.
- `frontend/src/components/dashboard/FinancialOverview.tsx` and focused coverage/reconciliation components.

Deliverables:

- Working View includes only Operator-reviewed events and labels unreconciled data as provisional.
- Verified View includes only Reconciled Slots.
- Reports expose coverage gaps, reconciliation basis, selected Reporting Currency, and Original Amount detail.
- Dashboard prioritizes spend total, category consumption, unclassified Expenses, unresolved slots, and card settlement mismatches.
- Financial Health, Projection, Anomaly, advice, and route-optimization behavior remains frozen.
- The 2026 completion check proves every active stream and due slot from January 2026 or its later opening month.
- Python and frontend gates pass together.

This slice satisfies acceptance criteria 7, 13, and 14 and runs the final milestone acceptance check.

## Planning Rule

The detailed plan for each later slice is written from the live repository after the preceding slice merges. This prevents stale file paths and interfaces from being treated as executable instructions. The approved design and the boundaries above remain fixed unless a new decision is recorded in `CONTEXT.md` and an ADR.
