# Europe Transfer Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Europe-side transfers trustworthy enough for `Transfers & Settlements` by fixing Beobank Mastercard `BETALING` amount parsing, deterministically reclassifying known Europe cash/credit/loan movements, and refreshing downstream analytics so the dashboard reflects the corrected semantics.

**Architecture:** Keep the import pipeline deterministic. First fix Beobank Mastercard PDF parsing so `BETALING ... -2 677,24` style rows import with the full signed amount. Then add a re-runnable migration-style cleanup pass, `europe_iban_reclassification_v1`, that uses exact owned-account signals only: structured `counterparty_account` when available, exact known IBAN substrings in descriptions, and import-source context for Beobank Mastercard card statements. The pass rewrites only unambiguous Europe rows, deactivates conflicting recurrence patterns instead of guessing how to migrate them, and recomputes financial statistics, category statistics, and financial health only when rows actually changed.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, pytest, Docker Compose, React/TypeScript frontend already consuming the corrected backend data.

---

## File Map

### Backend create

- `backend/app/migrations/migrate_europe_iban_reclassification.py` — deterministic Europe cleanup pass, recurrence-safety handling, and aggregate refresh trigger.
- `backend/tests/test_europe_transfer_cleanup_migration.py` — migration tests covering IBAN-role rules, parser-artifact skip behavior, recurrence safety, and aggregate refresh.

### Backend modify

- `backend/app/imports/beobank_mastercard_pdf.py` — accept space-separated thousands in `BETALING` rows and normalize them correctly.
- `backend/app/database_manager.py` — run the new cleanup pass from the real startup path (`init_database()`), and only recompute derived tables when the pass reports changes.
- `backend/app/migrations/run_migrations.py` — add the cleanup pass for CLI parity with existing migration entrypoints.
- `backend/tests/imports/test_beobank_mastercard_pdf.py` — lock the parser bug with a real-world `BETALING ... -2 677,24` case.

### Existing code intentionally reused

- `backend/app/services/statistics_service.py` — reuse `initialize_statistics()` and `initialize_category_statistics()` instead of inventing a second recompute path.
- `backend/app/services/financial_health_service.py` — reuse `initialize_financial_health()` after reclassification.
- `backend/app/services/csv_import_service.py` and `backend/app/services/classification_session_service.py` — left untouched functionally, but the cleanup plan assumes their live recurrence behavior when defining the recurrence-safety guardrail.

## Known Deterministic Signals

### Owned-account role map

- `BE11950212984548` → `cash_account` (Beobank normal cash account)
- `BE46063651946836` → `cash_account` (Belfius cash account)
- `BE36950263030181` → `credit_reimbursement_account`
- `BE74950226230607` → `loan_account`

### Signal precedence

1. `Transaction.counterparty_account` exact normalized IBAN match
2. exact known IBAN substring inside `Transaction.import_source_description` or `Transaction.description`
3. local-account role from `Transaction.account_number` exact normalized IBAN match
4. special deterministic local-role inference for Beobank Mastercard imports:
   - if `transaction.import_session_id` points at an import session with `extractor_id = "beobank_mastercard_pdf_v1"`, treat the local side as `credit_reimbursement_account`

### Rows the pass must skip

- any row whose description or import-source description contains `Wise`
- any row with no exact known IBAN/account-role evidence
- any old Beobank Mastercard `BETALING` row that still shows the known parser artifact pattern (for example, truncated amount with a leftover `-2` token in the description)

## Verification Commands

- Focused parser regression:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/imports/test_beobank_mastercard_pdf.py -q'`
- Focused cleanup migration tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_europe_transfer_cleanup_migration.py -q'`
- End-to-end backend slice:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/imports/test_beobank_mastercard_pdf.py tests/test_europe_transfer_cleanup_migration.py tests/test_transfer_analytics.py -q'`
- Optional manual smoke check after app startup:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. python - <<\"PY\"\nfrom app.database import SessionLocal\nfrom app.models.transaction import Transaction\nfrom app.models.transaction import TransactionType\n\ndb = SessionLocal()\nrows = db.query(Transaction).filter(Transaction.transaction_type == TransactionType.TRANSFER).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()\nfor row in rows[:20]:\n    print(row.id, row.transaction_date, row.amount, row.transfer_category, row.description)\ndb.close()\nPY'`

## Task 1: Lock and fix the Beobank Mastercard `BETALING` parser bug

**Files:**
- Modify: `backend/tests/imports/test_beobank_mastercard_pdf.py`
- Modify: `backend/app/imports/beobank_mastercard_pdf.py`

- [ ] **Step 1: Add the failing regression test for space-separated thousands in `BETALING` rows**

Add a test to `backend/tests/imports/test_beobank_mastercard_pdf.py` that uses a realistic row like:

```text
12/02/2026 BETALING IBAN BE11950212984548 Mr ALEXANDRE ARDUINI TAVARES -2 677,24
```

Assert all of the following:

- the transaction imports successfully
- `source_description` does not retain a trailing `-2`
- `signed_amount == 2677.24`
- `debit_credit == "credit"`
- the row remains a single logical transaction row, not a blocking issue

- [ ] **Step 2: Run the focused parser test and capture the current failure**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/imports/test_beobank_mastercard_pdf.py -q'
```

Expected before the fix: the new test fails because the parser truncates the amount or leaves the `-2` artifact in the description.

- [ ] **Step 3: Extend amount parsing to accept spaces as thousands separators**

Update `backend/app/imports/beobank_mastercard_pdf.py` so that:

- `AMOUNT_RE` accepts:
  - `1.234,56`
  - `1 234,56`
  - `1234,56`
  - `-2 677,24`
- `ROW_RE` uses the same broader amount rule
- `_parse_amount_text()` strips spaces as well as dots before converting the decimal comma

The implementation must preserve existing sign semantics:

- text starting with `-` remains a `credit` row with positive `signed_amount`
- text without `-` remains a `debit` row with negative `signed_amount`

- [ ] **Step 4: Re-run the parser tests until they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/imports/test_beobank_mastercard_pdf.py -q'
```

- [ ] **Step 5: Commit the parser fix**

```bash
git add backend/app/imports/beobank_mastercard_pdf.py backend/tests/imports/test_beobank_mastercard_pdf.py
git commit -m "fix: parse spaced Mastercard settlement amounts"
```

## Task 2: Build the deterministic Europe cleanup pass

**Files:**
- Create: `backend/app/migrations/migrate_europe_iban_reclassification.py`
- Create: `backend/tests/test_europe_transfer_cleanup_migration.py`

- [ ] **Step 1: Write the migration tests first**

Create `backend/tests/test_europe_transfer_cleanup_migration.py` with focused cases that use the real SQLAlchemy models and a test database reset. Cover at minimum:

1. Belfius cash-account row with structured `counterparty_account = BE36950263030181`:
   - rewritten to `TransactionType.TRANSFER`
   - `transfer_category = CREDIT_CARD_SETTLEMENT`
   - `expense_category is None`
   - `income_category is None`

2. Europe-side cash-account row with structured `counterparty_account = BE74950226230607`:
   - rewritten to `Transfer / Debt Repayment Sent`

3. Europe-side cash-account row between `BE11950212984548` and `BE46063651946836`:
   - remains `Transfer / Internal Transfer`

4. Beobank Mastercard imported `BETALING` row:
   - `import_session_id` points at a session whose `extractor_id` is `beobank_mastercard_pdf_v1`
   - description contains `IBAN BE11950212984548`
   - rewritten to `Transfer / Credit Card Settlement` even though `account_number` is only the masked card hint

5. `Wise` row:
   - left unchanged

6. parser-artifact skip case:
   - description still contains leftover `-2`
   - row is left unchanged and counted as skipped, not rewritten

7. recurrence safety:
   - corrected row points at an active recurrence pattern with legacy `Expense / Credit Payment`
   - migration deactivates that pattern and clears `recurrence_pattern_id` on the corrected row
   - post-pass assertion confirms no corrected row still points at an active conflicting pattern

8. aggregate refresh:
   - stale `FinancialStatistics` row exists before migration with settlement counted as expense
   - after migration, refreshed stats exclude that settlement from expenses

- [ ] **Step 2: Run the new test file to confirm it fails before implementation**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_europe_transfer_cleanup_migration.py -q'
```

Expected before the implementation: import error because the migration module does not exist yet.

- [ ] **Step 3: Implement `europe_iban_reclassification_v1` as a re-runnable migration helper**

Create `backend/app/migrations/migrate_europe_iban_reclassification.py` with explicit helpers:

- `_normalize_identifier(value: str | None) -> str | None`
  - uppercase
  - remove spaces
- `_known_role_for_iban(normalized: str | None) -> str | None`
- `_contains_known_iban(text: str | None) -> str | None`
  - exact normalized substring scan over the four known IBANs
- `_local_role_for_transaction(db, transaction) -> str | None`
  - first: normalized `transaction.account_number`
  - second: if the linked import session exists and `extractor_id == "beobank_mastercard_pdf_v1"`, return `credit_reimbursement_account`
- `_counterparty_role_for_transaction(transaction) -> str | None`
  - first: `counterparty_account`
  - second: `import_source_description`
  - third: `description`
- `_desired_transfer_category(local_role, counterparty_role) -> TransferCategory | None`
  - `cash_account -> cash_account` => `INTERNAL_TRANSFER`
  - `cash_account -> credit_reimbursement_account` => `CREDIT_CARD_SETTLEMENT`
  - `cash_account -> loan_account` => `DEBT_REPAYMENT_SENT`
  - reverse-leg cases on the imported destination account should resolve to the same subtype

The migration function should return a summary dict with concrete counts, for example:

```python
{
    "updated_transactions": 0,
    "skipped_wise": 0,
    "skipped_ambiguous": 0,
    "skipped_parser_artifact": 0,
    "deactivated_patterns": 0,
    "detached_transactions": 0,
    "recomputed_aggregates": 0,
}
```

- [ ] **Step 4: Enforce fail-closed rewrite rules**

Inside the migration:

- skip rows containing `Wise` in `description` or `import_source_description`
- skip rows with no exact signal
- skip rows where the parser-artifact pattern still exists
- skip rows already carrying the correct `TransferCategory`
- only rewrite when one deterministic rule outcome exists

For rewritten rows, enforce the invariant:

```python
transaction.transaction_type = TransactionType.TRANSFER
transaction.transfer_category = desired_category
transaction.expense_category = None
transaction.income_category = None
```

- [ ] **Step 5: Choose and implement the safe recurrence default**

For any corrected row whose linked recurrence pattern is active and does not already match the corrected transfer semantics:

- set `pattern.active = False`
- set `transaction.recurrence_pattern_id = None`

Do not attempt to silently migrate a legacy expense recurrence into a new transfer recurrence in this pass.

After processing all rows, run a post-pass assertion:

- no corrected row may still point at an active recurrence pattern whose `transaction_type` or `category` conflicts with the corrected transfer semantics

Raise an exception if that assertion fails.

- [ ] **Step 6: Recompute derived aggregates only when data changed**

If at least one row was rewritten or at least one conflicting recurrence pattern was deactivated:

- call `StatisticsService.initialize_statistics(db)`
- call `StatisticsService.initialize_category_statistics(db)`
- call `FinancialHealthService.initialize_financial_health(db)`

If nothing changed, skip the expensive recompute and return `recomputed_aggregates = 0`.

- [ ] **Step 7: Re-run the migration tests and make them all pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_europe_transfer_cleanup_migration.py -q'
```

- [ ] **Step 8: Commit the migration implementation**

```bash
git add backend/app/migrations/migrate_europe_iban_reclassification.py backend/tests/test_europe_transfer_cleanup_migration.py
git commit -m "feat: add deterministic europe transfer cleanup"
```

## Task 3: Wire the cleanup pass into the actual startup path

**Files:**
- Modify: `backend/app/database_manager.py`
- Modify: `backend/app/migrations/run_migrations.py`

- [ ] **Step 1: Add startup wiring in `init_database()`**

Update `backend/app/database_manager.py` so the new migration runs from the real app startup path:

- import `migrate_europe_iban_reclassification`
- after schema/table setup is complete, open a session and run the cleanup pass
- log the returned summary
- do not rerun the statistics refresh manually in `init_database()` if the migration already performed it

The startup path must stay idempotent: repeated app boots should produce a no-op summary once the data is already corrected.

- [ ] **Step 2: Add CLI parity**

Update `backend/app/migrations/run_migrations.py` to invoke `migrate_europe_iban_reclassification()` as part of the manual migration runner too, so startup and CLI migration entrypoints stay aligned.

- [ ] **Step 3: Run the full backend slice**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/imports/test_beobank_mastercard_pdf.py tests/test_europe_transfer_cleanup_migration.py tests/test_transfer_analytics.py -q'
```

- [ ] **Step 4: Commit the wiring**

```bash
git add backend/app/database_manager.py backend/app/migrations/run_migrations.py
git commit -m "feat: run europe transfer cleanup during startup"
```

## Task 4: Manual validation against the curated Europe data

**Files:**
- No new files required unless a bug is found during validation

- [ ] **Step 1: Start from a known-clean database**

Run:

```bash
docker compose down
rm -f backend/app/data/myfinance.db
docker compose up -d --build
```

If you are using the Docker volume-backed production-like database path instead of the host file, use the app’s existing reset flow or remove the container volume the same way you already do in this repo.

- [ ] **Step 2: Re-import the curated Europe files after the parser fix**

Use the existing upload/batch-import flow so the corrected Beobank Mastercard `BETALING` rows are committed with the full amounts.

- [ ] **Step 3: Verify the three Europe transfer outcomes manually**

Confirm in the transactions list and/or direct DB queries that:

- cash-account to `BE36` rows are `Transfer / Credit Card Settlement`
- cash-account to `BE74` rows are `Transfer / Debt Repayment Sent`
- `BE11 <-> BE46` rows remain `Transfer / Internal Transfer`
- `Wise` rows remain untouched

- [ ] **Step 4: Check `Transfers & Settlements`**

Confirm the dashboard now shows subtype rows instead of lumping every Europe movement into a generic internal-transfer bucket.

- [ ] **Step 5: Commit only if manual validation required code adjustments**

If any extra fixes were needed during manual validation:

```bash
git add <changed files>
git commit -m "fix: polish europe transfer cleanup rollout"
```

## Final Verification

- [ ] Run the complete backend verification command:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/imports/test_beobank_mastercard_pdf.py tests/test_europe_transfer_cleanup_migration.py tests/test_transfer_analytics.py -q'
```

- [ ] Confirm `git status --short` is clean.

## Expected Outcome

After this plan is implemented:

- Beobank Mastercard `BETALING` rows carry the correct full amounts
- Europe-side card settlements stop masquerading as `Expense / Credit Payment`
- Europe-side loan repayments stop hiding inside `Internal Transfer`
- true `BE11 <-> BE46` own-account movements stay `Internal Transfer`
- active legacy recurrence patterns cannot silently undo the deterministic cleanup
- `Transfers & Settlements` becomes trustworthy for Europe-side usage while `Wise` remains intentionally untouched
