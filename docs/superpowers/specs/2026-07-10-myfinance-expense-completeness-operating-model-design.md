# MyFinance Expense Completeness Operating Model

Date: 2026-07-10
Status: Approved
Amended: 2026-07-23 (application/test/build warning boundary)

## Goal

MyFinance gives one Operator a trustworthy view of every Household Expense under the approved tracking policies from January 2026 onward. The application must preserve source evidence, keep internal money movement out of Income and Expense totals, prevent credit-card double counting, expose missing monthly records, and show the evidence quality behind each report.

The first milestone is **2026 Expense Completeness**.

## Product Boundary

MyFinance remains a private, local-first React, FastAPI, and SQLite application. One Operator uses it. The Financial Perimeter may include the Operator's accounts, the spouse's relevant accounts, joint accounts, credit cards, Wise, Nexo, and later Financial Institutions needed for Household expense coverage.

The existing Financial Health, Projection, and Anomaly features remain intact but frozen. The team will reconsider them after the first milestone.

This design excludes:

- multi-user or hosted SaaS behavior
- direct bank-app integrations
- a new ledger or event-store rewrite
- transfer-route comparison or optimization
- new financial advice and forecasting work
- physical-cash tracking after withdrawal
- loan-balance accounting
- changes to the existing refund model

## Domain Language

[CONTEXT.md](../../../CONTEXT.md) defines the canonical domain language. Code, tests, UI copy, and future specs must use those terms.

The central distinctions are:

- Source Record versus extracted Financial Event
- Source Complete versus Reviewed Slot versus Reconciled Slot
- Expense versus Income versus Transfer
- Credit Card Purchase versus Credit Card Settlement
- Original Amount versus Reporting Currency
- Applied Rate versus Reference Rate
- Classification Proposal versus Operator-approved classification

## Chosen Architecture

The design extends the current application in place:

```text
Local Source Records
  -> Statement Stream registry and Coverage Calendar
  -> institution-specific detection and extraction
  -> evidence-backed import review
  -> Operator-approved classification
  -> consolidated SQLite record
  -> Working and Verified expense reports
```

The application keeps FastAPI, React, SQLite, the current import workflow, local similarity, and the classification assistant. New modules own Statement Stream configuration, monthly coverage, and reconciliation. Existing import adapters continue to own institution and format knowledge.

## Local Source Record Layout

Raw financial files remain under the Git-ignored `bank_files/` directory:

```text
bank_files/
  statement-streams.yml
  supported/
    <institution>/
      <account-alias>/
        <YYYY>/
          <YYYY-MM>/
            <source files>
  pending-support/
    <institution>/
      <account-alias>/
        <source files>
```

The `YYYY-MM` folder names the Statement Slot by the month in which the Statement Period ends. A statement covering March 10 through April 9 belongs to `2026/2026-04/`.

Aliases must not contain full account numbers, card numbers, IBANs, names, or credentials. Raw filenames may remain unchanged inside local storage, but the application must not expose them in logs or external requests.

The batch importer scans `supported/` and its descendants. It leaves `pending-support/` untouched. A new institution or format starts with a local sample and a GitHub issue. The issue contains metadata and redacted examples. Tests use sanitized or synthetic fixtures.

## Statement Stream Registry

`bank_files/statement-streams.yml` is the sole configuration interface for Statement Streams. The application validates the file before it scans or imports source files.

The first schema version has this shape:

```yaml
version: 1
streams:
  - id: belfius-checking-eur
    status: supported
    institution: belfius
    account_alias: checking-eur
    holder: operator
    product_type: bank_account
    source_format: belfius_csv
    currency: EUR
    coverage_start: 2026-01
    closing_day: 4
    grace_days: 2

  - id: brazil-bank-checking-brl
    status: pending_support
    institution: brazil-bank
    account_alias: checking-brl
    holder: operator
    product_type: bank_account
    currency: BRL
```

Contract rules:

- `version` equals `1`.
- Each `id` is unique and stable.
- `status` is `supported` or `pending_support`.
- `holder` is `operator`, `spouse`, or `joint`.
- The first milestone supports `bank_account`, `credit_card`, and `wallet` product types.
- Supported streams require a stable `source_format` that selects the expected institution format, such as `belfius_csv` or `beobank_mastercard_pdf`.
- `currency` is `EUR`, `USD`, or `BRL` after alias normalization. Source evidence retains its raw currency code.
- Supported streams require `coverage_start`, `closing_day`, and `grace_days`.
- Existing supported streams use `coverage_start: 2026-01` unless the account opened later.
- `closing_day` ranges from 1 through 31. A shorter month uses its final day.
- `grace_days` counts calendar days and absorbs normal publication delays.
- Pending streams do not generate coverage obligations or import attempts.
- The application derives the expected folder path from status, institution, and account alias. It rejects path traversal and duplicate derived paths.
- Unknown fields fail validation. Schema changes require an additive versioned migration.

The registry contains no secrets or full financial identifiers. A committed example file may use synthetic aliases, but the live registry remains local and Git-ignored.

## Coverage Calendar

The Coverage Calendar evaluates each Statement Stream from its Coverage Start.

Coverage uses three separate dimensions:

1. **Source coverage**
   - `not_due`: the stream has not reached its closing day plus grace period
   - `unresolved`: the due date passed without a Source Record or no-activity confirmation
   - `received`: the expected Source Record exists
   - `no_activity`: the Operator confirmed that the institution produced no activity and no file
2. **Review state**
   - `not_started`
   - `pending`
   - `reviewed`
3. **Reconciliation state**
   - `not_available`: the source provides no Control Evidence
   - `pending`
   - `reconciled`
   - `mismatch`

The UI may combine these dimensions into short labels, but the database and API keep them separate.

`received` or `no_activity` satisfies source coverage. Operator approval produces a Reviewed Slot. A slot becomes Reconciled when available balances and control totals agree with the imported Financial Events. A source without Control Evidence may reach `reviewed` but not `reconciled`.

An empty folder never proves no activity. The Operator must confirm a No-Activity Slot.

## Import and Review

Each institution and source format has a versioned adapter and Institution Profile. The adapter detects the format, preserves evidence, and creates proposals. It does not decide domain truth from debit or credit direction alone.

The import workflow follows these rules:

1. Hash and preserve the Source Record.
2. Detect the institution and source format.
3. Stop without Financial Events when no adapter supports the format.
4. Extract statement metadata, itemized rows, source locators, Original Amounts, currencies, and Control Evidence.
5. Create Classification Proposals with field-level confidence and provenance.
6. Show evidence and proposals for review.
7. Commit the approved statement in one database transaction.
8. Re-importing the same file returns the existing import result and creates no duplicates.

The Operator may correct extracted fields and classifications. Corrections update the normalized record and learning data. They never change the original Source Record.

## Expense Semantics

The application retains the current top-level transaction types:

```text
Expense
Income
Transfer
```

The Operator confirms type and category during review. The following rules govern proposals and reports:

- Internal movements inside the Financial Perimeter are Transfers.
- Borrowed money is not Income.
- Current known Income originates in Belgium. This is a current Household fact, not a sign-based or institution-based classification rule.
- Cash withdrawals are Expenses because this product does not track physical cash after withdrawal.
- Debt Repayments are Expenses under the Household's practical tracking policy unless they are Credit Card Settlements.
- Credit Card Purchases are itemized Expenses.
- Credit Card Settlements are Transfers and never create a second Expense.
- Fees, taxes, interest, penalties, overdraft charges, and exchange-rate loss are Expenses.
- Transferred principal is not an Expense.
- The application keeps the current refund behavior for this milestone.

Movement Chains support correctness inside the import and reconciliation layers. They link related money movements, splits, and settlements when that connection prevents false Income, false Expense, or missing Financial Costs. The product does not expose route analytics.

## Credit Card Reconciliation

The card statement owns the itemized Expense evidence. A payment from a bank account uses `Transfer -> Credit Card Settlement`.

Card Statement Reconciliation checks:

- itemized purchases
- fees and interest
- credits
- the statement amount due
- one or more settlement payments

Settlement Coverage reports `unpaid`, `partially_settled`, `fully_settled`, or `overpaid` plus the remaining difference. The implementation links settlements to the statement. It does not create a payment allocation for each purchase.

## Classification and Learning

The classification flow uses local evidence first:

1. Institution rules and confirmed recurrence patterns produce deterministic proposals.
2. Local cosine similarity proposes categories from confirmed historical classifications.
3. The UI asks for consent before an external LLM request.
4. The sanitizer removes IBANs, account and card numbers, reference numbers, names, full Source Records, and raw statement text.
5. The request contains the minimum description, amount, currency, current type, and allowed categories.
6. The external response remains a Classification Proposal.
7. The Operator approves or corrects the proposal.

Confirmed classifications update the local similarity index and prefill future proposals. The application never changes historical records or future imports without review. Batch application shows the exact candidate set and requires Operator selection.

The application does not log raw descriptions, prompts, amounts, account identifiers, or statement text. Logs may contain internal IDs, counts, statuses, timing, and stable error codes.

## Currency and Financial Costs

The database preserves each Original Amount and currency. Reporting conversion never replaces source evidence.

EUR is the default Reporting Currency because current Income originates in Belgium. The Operator may select BRL or USD. Each conversion retains the Reference Rate source, rate date, rate, and date-selection basis.

The first milestone uses the existing ECB daily EUR-based rates. The service selects the rate date from:

1. conversion date
2. value date
3. booking date
4. latest earlier ECB publication when the selected date has no rate

An Applied Rate comes from a Source Record or from linked source and destination amounts after the service separates Explicit Costs. When neither form of evidence exists, the Movement Chain remains Cost Pending. The service never substitutes the Reference Rate as the Applied Rate.

Realized Cost contains Explicit Costs plus Exchange-Rate Cost without double counting. Expense reports include these costs. The product does not rank transfer routes.

## Reporting

The primary dashboard answers:

- How much did the Household spend?
- Which categories consumed the money?
- Which Expenses need classification?
- Which Statement Slots remain unresolved or unreconciled?
- Did card settlements reconcile without duplicate Expenses?

The Working View includes Financial Events from Reviewed Slots and displays a provisional label plus coverage gaps. The Verified View includes Financial Events from Reconciled Slots. Each report shows the selected Reporting Currency and exposes Original Amounts in transaction detail.

## Data Safety

MyFinance protects the live SQLite database:

- Create and verify a timestamped SQLite backup before each migration.
- Run idempotent migrations inside a controlled transaction where SQLite permits it.
- Keep the original database usable when a migration fails.
- Test migrations against a realistic database copy.
- Provide one documented restore command and test it.
- Remove destructive reset from the normal API.
- Keep reset as a development and test CLI action with confirmation.

The application treats raw Source Records, the live database, backups, local configuration, and secrets as private. Git ignores them. Docker mounts `bank_files/` read-only.

## Network and Application Security

MyFinance runs as a local application. The backend accepts the known frontend origin instead of wildcard CORS. The deployment does not expose the API to the public internet.

The current hardcoded PIN provides no security boundary. The first milestone relies on device and network access controls. Remote access uses a trusted tunnel or VPN. A future authentication project must replace the PIN if deployment requirements change.

## Failure Handling

- Unsupported source: preserve the file under `pending-support/` and create no Financial Events.
- Extraction failure: retain evidence and error details, then commit nothing.
- Duplicate source: return the existing import reference.
- Reconciliation mismatch: retain reviewed data in the Working View and show the difference.
- Missing Control Evidence: mark the source reviewed without claiming reconciliation.
- Missing FX evidence: preserve Original Amounts and mark conversion or cost pending.
- External LLM failure: continue with local similarity and manual review.
- Approval failure: roll back the whole statement commit.
- Migration failure: preserve the pre-migration database and report the restore path.

For an existing database, migration errors expose the retained verified backup
as `backup_path` and include that exact path in the operator-facing message.
Recovery failure reports the same retained path while stating that database
state is unknown. Cancellation keeps its original exception identity and adds a
note with the restored backup path. Failure while creating a new database
reports that the new file was removed and exposes `backup_path=None`.

The Europe/IBAN transfer cleanup is named recurring startup maintenance, not a
one-time schema migration. It runs after versioned migrations inside the same
verified-backup, recovery, validation, cancellation, and restore-path reporting
boundary. A successful maintenance-only startup deletes its newly created
safety backup so daily startup does not accumulate backup files. A failed or
cancelled maintenance run restores from that backup and retains its path for
the operator. Recurring maintenance never creates missing schema.

Errors use stable codes and concise messages. Logs exclude private financial content.

## Repository Workflow

Changes use this path:

```text
GitHub issue
  -> dev/<slug> branch
  -> focused change and test
  -> pull request
  -> required green checks
  -> merge to main
```

Each pull request addresses one coherent behavior change. Engineers avoid unrelated refactors and new dependencies. They update `CONTEXT.md` when domain language changes and add an ADR only for a costly decision with a real trade-off.

Non-trivial behavior changes and bug fixes start with the smallest focused failing test. Adapter tests use sanitized or synthetic fixtures. Tests run at the lowest layer that proves the behavior. The project has no arbitrary coverage-percentage target.

## Required Quality Gates

The Python gate is:

```text
pyrepo-check --all
```

The repository must configure this command to audit owned Python:

- Ruff and annotation checks cover application code and tests.
- `ty` covers application code and tests.
- Bandit covers runtime application code and operational scripts.
- pytest runs `backend/tests` with the correct import path.
- Environments, dependencies, generated files, and worktrees stay outside the owned-code target set.

Owned-code suppression checks tokenize `.py` and `.pyi` comments and case-insensitively reject `noqa`, `nosec`, `type: ignore`, and `ty: ignore` directives after any Python comment hash boundary, including repeated or later delimiters. Identifiers, strings, docstrings, and ordinary comment words such as “nanoseconds” are not directives. Owned code may not use disabled rules or configuration suppressions in place of a fix.

The frontend gate is:

```text
npm ci
npm run test:ci
npm run build
npm run check:bundle
```

The merge gate accepts no ignored failures, application/test warnings, or build
warnings. `npm ci` must exit successfully. Third-party deprecation and audit
notices printed while npm installs the locked dependency tree are recorded as
separate dependency-modernization work; they do not fail this slice and must
not be rewritten automatically with `npm audit fix`. The project adds no
frontend quality tool until the current gate fails to cover a demonstrated
risk.

## Current-Code Gaps

The implementation plan must address these observed gaps:

- `ImportBatchFolderService._preflight_batch_folder` scans only direct children of one folder.
- `ImportDetector` supports Belfius, Beobank, Nexo, and a PDF chain with Belfius and Beobank extractors. It has no Brazilian institution adapter.
- `BeobankCsvExtractor._signed_amount_and_type` maps every debit to Expense and every credit to Income.
- The current external classifier prompt includes the raw transaction description, amount, currency, and source bank.
- `CategorySuggestionService` keeps its vector database in memory and rebuilds it from confirmed database rows.
- `main.py` allows wildcard CORS and exposes `/debug/reset-database`.
- Startup code performs schema compatibility changes and migrations without the approved backup contract.
- `pyrepo-check --all` scans the repository root, including unowned local trees, and root-level pytest cannot import `app`.
- Existing backend CI runs pytest only. It does not run the approved Python gate.

These gaps describe implementation work. They do not authorize unrelated cleanup.

## Alternatives Considered

### Incremental expense foundation

Selected. It reuses the current application and limits work to Expense completeness, source coverage, reconciliation, safety, and quality gates.

### New ledger core

Rejected. A new accounting model would require a broad migration and would delay the Expense Coverage goal.

### File-first reporting

Rejected. Regenerating reports from files would discard durable review decisions, classification learning, card settlement state, and much of the current application.

## Acceptance Criteria

The 2026 Expense Completeness milestone is complete when:

1. The registry contains every active Statement Stream from `2026-01` or its later opening month.
2. Each due Statement Slot has a Source Record or Operator-confirmed no-activity state.
3. The batch importer scans supported nested folders and leaves pending-support folders untouched.
4. Every imported transaction has an Operator-reviewed type and category.
5. Institution adapters no longer infer Income or Expense from sign alone.
6. Credit Card Settlements reconcile statements without duplicating itemized Expenses.
7. Working and Verified Views display their source coverage and reconciliation basis.
8. Original Amounts remain intact across EUR, USD, and BRL reporting.
9. Financial Costs enter Expense totals without counting transferred principal.
10. External classification follows the consent and sanitization policy.
11. Migration backup and restore pass an end-to-end verification.
12. The normal API exposes no destructive database reset.
13. `pyrepo-check --all` and all frontend gate commands pass without
    suppressions, application/test warnings, or build warnings. Install-time
    third-party deprecation and audit notices from `npm ci` are recorded
    separately as dependency-modernization work.
14. The implementation adds no Health, Projection, Anomaly, advisory, or route-optimization scope.
