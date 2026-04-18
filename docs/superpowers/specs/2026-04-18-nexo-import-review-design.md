# Nexo Import Review Design

Date: 2026-04-18
Status: Draft for review

## Goal

Add a proper Nexo CSV importer on the import-session review pipeline so the user can upload Nexo exports, review the real expense and cash-out rows, and approve them into transactions and analytics without routing through the legacy direct-commit CSV lane.

## User Outcome

When the user uploads a Nexo CSV, the app should:

1. detect that it is a supported Nexo export
2. create an `ImportSession`
3. extract only reviewable money-out rows
4. show those rows in the normal import-review UI with raw and display money
5. commit them with the correct transaction type on approval

The user should not see:

- cashback rows
- Nexo internal credit-line plumbing
- synthetic loan-withdrawal rows
- accidental income created from cashing out to a Belgian bank account

## Problem Statement

The current system has two incompatible CSV paths:

- the new import-review pipeline used by `ImportSession`
- the legacy CSV upload/import lane that commits directly

Nexo must land on the first lane, not the second one.

If Nexo is added to the legacy parser, the app loses the core guarantees already established by statement import:

- explicit review before commit
- persisted artifacts and evidence
- retryable extraction
- uniform duplicate checks at approval
- trustworthy draft rows for import review

The Nexo import problem is not generic CSV parsing. It is bounded row semantics on top of the import-review workflow.

## Product Principles

1. Recognized Nexo CSVs must use the import-review pipeline only.
2. Raw imported ledger fields remain immutable in storage.
3. Deterministic Nexo row semantics beat sign-based guessing.
4. Cash-outs to the user's bank account are transfers, not income.
5. Internal Nexo bookkeeping rows do not become app transactions.
6. Approval commits the extractor's typed proposal contract, not a silent fallback guess.

## Approaches Considered

### Approach A: Add Nexo to the legacy CSV parser

Pros:

- smallest code change
- reuses existing CSV parsing helpers

Cons:

- bypasses import review
- commits directly
- loses evidence and retry flow
- encourages more legacy CSV branching
- does not match the target architecture

### Approach B: Migrate every CSV importer onto import review first, then add Nexo

Pros:

- one CSV architecture for everything
- cleanest long-term ingestion story

Cons:

- much larger scope
- delays the immediate Nexo outcome
- forces unrelated Belfius/Beobank CSV work into this feature

### Approach C: Add a dedicated `nexo_csv` strategy inside the import-review pipeline

Pros:

- solves the real user problem now
- keeps Nexo on the same review lane as PDFs
- preserves artifact, retry, and approval invariants
- does not require a full CSV migration first

Cons:

- import architecture remains mixed for non-Nexo CSVs in the short term
- requires a focused contract migration for typed transaction proposals

### Recommendation

Use Approach C.

This feature adds a proper Nexo lane to the import-review pipeline and explicitly forbids recognized Nexo files from falling back to `CsvImportService` or `CSVParser`.

## Scope

### In scope

- Nexo CSV detection for single-file upload and batch-folder import
- deterministic Nexo extraction on the import-review pipeline
- typed proposal fields on extraction, draft persistence, review response, and approval
- Nexo draft review in the existing import-review page
- correct commit behavior for:
  - Nexo card purchases
  - Nexo card fees
  - cash-outs to the user's bank account
- explicit skipping of non-transaction Nexo mechanics
- raw evidence capture for Nexo CSV attempts
- focused tests for detection, extraction, review, approval, and batch routing

### Out of scope

- migrating all existing CSV importers onto import review
- supporting arbitrary crypto-native row families
- cashback handling as income or rewards
- wallet-level Nexo account modeling
- line-by-line editing inside import review
- AI-based Nexo extraction

## Relationship To Prior Currency Work

This design depends on the reporting-currency foundation already established in:

- [2026-04-17-global-reporting-currency-foundation-design.md](/Users/aaat/myfinance/docs/superpowers/specs/2026-04-17-global-reporting-currency-foundation-design.md)
- [2026-04-18-reporting-currency-core-surfaces-design.md](/Users/aaat/myfinance/docs/superpowers/specs/2026-04-18-reporting-currency-core-surfaces-design.md)

That earlier work made `xUSD`, `EURX`, and `USDC` display correctly through backend-owned alias normalization without rewriting stored ledger truth.

This Nexo importer therefore preserves the raw imported `Input Currency` on drafts and committed transactions. It does not normalize `xUSD`, `EURX`, or `USDC` at write time.

## High-Level Architecture

The Nexo import flow is:

`upload or batch scan -> detect -> extract -> persist draft -> review -> approve -> commit`

The pipeline remains extractor-oriented:

- detection decides `strategy_key`
- workflow dispatches by `strategy_key`
- extractor returns a shared `ExtractionResult`
- approval commits from persisted draft proposals

No recognized Nexo CSV may branch into the legacy direct-import path.

`ImportWorkflowService.extract_detected_session` must therefore dispatch:

- `pdf_statement` -> `PdfStatementExtractor`
- `nexo_csv` -> `NexoCsvExtractor`

## Detection And Routing

### New strategy key

Add a new `ImportStrategyKey` member:

- `NEXO_CSV = "nexo_csv"`

### Detection rule

`ImportDetector` must detect Nexo from file content, not filename alone.

Detection steps:

1. decode the sample using the existing charset hint flow
2. parse the first non-empty row as comma-delimited CSV
3. match the ordered header exactly against:
   - `Transaction`
   - `Type`
   - `Input Currency`
   - `Input Amount`
   - `Output Currency`
   - `Output Amount`
   - `USD Equivalent`
   - `Fee`
   - `Fee Currency`
   - `Details`
   - `Date / Time (UTC)`
   - `normalizedDisplayDetails`

If the header matches, detection returns:

- `strategy_key = nexo_csv`
- `provider_hint = "nexo"`
- `charset_hint` from the detector
- `confidence = 1.0`
- note that the file is a deterministic Nexo CSV export

Otherwise normal detection behavior continues.

### Upload routing

`POST /imports/upload` must auto-extract both:

- `pdf_statement`
- `nexo_csv`

### Batch-folder routing

Batch-folder import must detect CSV files before routing them.

Rules:

- if a CSV file detects as `nexo_csv`, route it through `ImportPipelineService` + `ImportWorkflowService`
- if a CSV file does not detect as `nexo_csv`, this feature does not change its existing behavior
- a recognized Nexo CSV must never be handed to `CsvImportService`

This keeps Nexo off the legacy lane without forcing a broad CSV migration.

## Extractor Design

### Extractor type

Add a deterministic extractor:

- `NexoCsvExtractor`

Recommended shape:

- `extract(file_path, session_id, attempt_number) -> tuple[RawEvidence, ExtractionResult]`

This matches the existing workflow pattern used by `PdfStatementExtractor`.

### Extractor identity

`ExtractionResult.extractor_id` should be:

- `nexo_csv_v1`

### Source metadata

`ExtractionResult.source_metadata` should include:

- `provider_hint = "nexo"`
- `file_type = "csv"`
- `charset`

### Statement metadata

`ExtractionResult.statement_metadata` should include:

- `account_number_hint = "NEXO"`
- `card_number_hint = None`
- `currency = None`
- `statement_period_start` = minimum parsed row date in the recognized file
- `statement_period_end` = maximum parsed row date in the recognized file

`currency` is intentionally `None` because a Nexo export is a mixed-currency file.

### Nexo account identity

All committed Nexo rows use:

- `provider_hint = "nexo"`
- `source_bank = "Nexo"`
- `account_number = "NEXO"`

This is an explicit v1 simplification. The system is not modeling separate Nexo wallets or sub-accounts in this phase.

## Shared Contract Migration

This feature introduces a real import-review contract migration.

The current pipeline can persist free-text category hints, but approval ignores them and commits with `transaction_type=None`. That is not sufficient for Nexo, because cash-outs must land as transfers and fees should land as expenses from day one.

### New proposal fields on `ExtractedTransaction`

Add these nullable typed fields to `ExtractedTransaction`:

- `proposed_transaction_type: TransactionType | None`
- `proposed_expense_category: ExpenseCategory | None`
- `proposed_income_category: IncomeCategory | None`
- `proposed_transfer_category: TransferCategory | None`
- `proposal_source: Literal["deterministic_extracted", "ai_extracted", "user_edited"] | None`

`proposal_source` uses the same vocabulary family as `edit_source`.

For Nexo rows emitted by the deterministic extractor:

- `proposal_source = "deterministic_extracted"`

If an extractor leaves every proposal field null, `proposal_source` should also be `None`.

### Draft persistence migration

`ImportTransactionDraft` gets matching nullable columns using the same enum families as committed transactions:

- `proposed_transaction_type`
- `proposed_expense_category`
- `proposed_income_category`
- `proposed_transfer_category`
- `proposal_source`

These proposal columns become the authoritative review-and-approval contract.

### Fate of `inferred_category` and `category_source`

`inferred_category` and `category_source` stop being part of the authoritative importer contract for this feature.

Rules:

- new Nexo extraction does not write them
- approval does not read them
- import-review API responses for the new contract should expose the typed proposal fields instead

If the backing database columns remain temporarily for migration convenience, they are out of contract and ignored by the new workflow.

### Existing extractors

Existing PDF extractors are migrated onto the same proposal fields.

They may set:

- explicit proposal values when known
- or `None` for all proposal fields when they do not know the correct classification yet

The important invariant is that approval reads only the typed proposal fields and never reconstructs transaction meaning from free-text hints.

## Approval Contract

`ImportWorkflowService._build_committed_transaction` must change from:

- hardcoding `transaction_type=None`
- hardcoding all category fields to `None`

to:

- committing the draft's proposal fields exactly as persisted

### Commit rules

If `ImportTransactionDraft` contains:

- `proposed_transaction_type = Expense`
  - commit `transaction_type = Expense`
  - commit only `proposed_expense_category`
- `proposed_transaction_type = Income`
  - commit `transaction_type = Income`
  - commit only `proposed_income_category`
- `proposed_transaction_type = Transfer`
  - commit `transaction_type = Transfer`
  - commit only `proposed_transfer_category`
- all proposal fields null
  - commit as currently supported for proposal-less imports that intentionally defer classification

### Invalid combinations

Approval must reject invalid draft combinations before commit, for example:

- `Transfer` with an expense category
- `Expense` with a transfer category
- `Income` with a transfer or expense category
- a category proposal present while `proposed_transaction_type` is null

These should fail the approval attempt with an import-session state error instead of silently coercing the row.

### Old drafts

Existing draft sessions created before this contract migration should be retried and re-extracted if they need the new behavior.

Approval must not invent missing Nexo type/category proposals from sign alone.

For this feature, new Nexo extraction is expected to populate proposal fields for every imported row.

## Raw Currency Rule

For Nexo, imported currency remains the raw `Input Currency` code from the file after trimming surrounding whitespace only.

Examples:

- `xUSD` remains `xUSD`
- `USDC` remains `USDC`
- `EURX` remains `EURX`

The importer does not rewrite these to fiat currency codes.

Display normalization remains a backend presentation concern handled by the reporting-currency conversion layer.

## Date And Description Rules

### Date parsing

Nexo exports the value column as:

- `YYYY-MM-DD HH:MM:SS`

The `UTC` marker lives in the column header, not inside the value.

V1 rule:

- parse the value as exported
- take the calendar-date portion only
- do not reinterpret the timestamp into another timezone

### Description source

Use:

1. `normalizedDisplayDetails` when present and non-empty
2. otherwise `Details`

Then:

- trim whitespace
- strip leading `approved /` or `rejected /`
- preserve the remaining merchant or transfer text as-is

### Source locator

Use:

- `csv:r{row_number}:{transaction_id}`

Example:

- `csv:r42:NXT4dVnP...`

## Transfer Detection Rules

The Nexo `Type` value `Transfer Out` is ambiguous and must be disambiguated by `Details` content.

### Internal-plumbing matcher

Skip the row as internal Nexo bookkeeping if normalized details contain any of:

- `auto transfer`
- `savings wallet`
- `credit line wallet`

These rows do not represent a user-visible external transaction.

### External cash-out matcher

Import the row as an external cash-out if normalized details contain either:

- `bank transfer`
- `sepa`
- an IBAN-like token

An IBAN-like token is any token that matches this rule after uppercasing and removing spaces:

- `[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}`

### Ambiguous `Transfer Out`

If a `Transfer Out` row matches neither the internal-plumbing matcher nor the external cash-out matcher:

- do not import it
- record a non-blocking issue for that row

This keeps the extractor deterministic and conservative.

## Deterministic Nexo Row Semantics

### Import as expense

#### `Nexo Card Purchase`

Import when:

- `Type = "Nexo Card Purchase"`
- `Input Amount` is negative

Commit proposal:

- `proposed_transaction_type = Expense`
- no proposed expense category

#### `Nexo Card Transaction Fee`

Import when:

- `Type = "Nexo Card Transaction Fee"`
- `Input Amount` is negative

Commit proposal:

- `proposed_transaction_type = Expense`
- `proposed_expense_category = Financial Fees`

### Import as transfer

#### External `Transfer Out`

Import when:

- `Type = "Transfer Out"`
- `Input Amount` is negative
- details match the external cash-out matcher

Commit proposal:

- `proposed_transaction_type = Transfer`
- `proposed_transfer_category = Internal Transfer`

From the app's point of view, this is money leaving Nexo to the user's own bank account to pay bills. It is not income.

### Always skip

Skip these rows without creating draft transactions:

- `Cashback`
- `Exchange Credit`
- `Credit Card Withdrawal Credit`
- `Transfer Out` rows matched as internal plumbing
- rows whose details begin with `rejected /`

### Unknown Nexo row types

If a row has a recognized Nexo header but an unsupported or unknown `Type`:

- do not import it
- record a non-blocking row issue

### Zero-reviewable-row outcome

If the file is recognized as Nexo but extraction produces zero reviewable rows after deterministic skips:

- fail the session
- record a blocking issue with:
  - `issue_code = "no_importable_nexo_rows"`

This is better than a fake successful session with an empty review.

## Evidence Contract

Nexo extraction remains fully auditable.

### Original file

The original uploaded CSV is already stored under the session artifact directory and remains the source of truth.

### Raw evidence

`RawEvidence` for Nexo should include:

- `text_blocks` with one CSV pseudo-page:
  - `page_number = 1`
  - `raw_text` = the decoded CSV text
  - `lines` = the decoded file split into CSV lines
- `snippets` with per-row structured evidence such as:
  - `row_number`
  - `transaction_id`
  - `type`
  - `details`
  - `decision`
  - `reason`

`ocr_blocks` remains empty.

This keeps the current review UI useful without inventing a separate CSV evidence viewer in v1.

## Review API And UI

The import-review payload for Nexo rows must expose the typed proposal fields directly.

Each review row should therefore include:

- raw date, amount, currency, and description
- display money fields from the reporting-currency system
- `proposed_transaction_type`
- any matching proposed category field
- `proposal_source`
- `source_locator`

The review page does not need line-by-line editing in this phase. It only needs to show what will be committed when the session is approved.

## Duplicate Behavior

No new Nexo-specific duplicate algorithm is required.

The existing approval-time duplicate check remains the last line of defense and should continue to compare:

- `account_number`
- `transaction_date`
- `amount`
- `currency`
- `source_bank`
- normalized description

For Nexo v1, all committed rows share:

- `account_number = "NEXO"`
- `source_bank = "Nexo"`

That is acceptable in this phase.

## Error Handling

### Extraction-time blocking failures

Block the session for:

- malformed Nexo header after positive detection
- unreadable required columns
- zero importable rows after deterministic skipping

### Extraction-time warnings

Record non-blocking issues for:

- unknown `Type` values
- ambiguous `Transfer Out` rows
- reviewable row candidates with invalid sign or missing required cell values

The presence of warnings must not prevent review when at least one valid draft row exists.

## Testing Strategy

### Backend unit tests

- detector test for exact Nexo header recognition
- detector test proving non-Nexo CSVs do not detect as `nexo_csv`
- extractor tests for:
  - purchase rows
  - fee rows
  - external cash-out rows
  - internal credit-line transfers skipped
  - cashback skipped
  - rejected rows skipped
  - ambiguous `Transfer Out` warning
  - `no_importable_nexo_rows`
- contract tests for typed proposal-field serialization
- workflow tests proving approval commits proposal fields
- workflow tests proving invalid proposal combinations fail approval

### API tests

- `/imports/upload` accepts Nexo CSV and returns `awaiting_review`
- `/imports/{id}` exposes draft rows plus proposal fields
- `/imports/{id}/approve` commits:
  - purchases as `Expense`
  - fees as `Expense / Financial Fees`
  - cash-outs as `Transfer / Internal Transfer`

### Batch-folder tests

- recognized Nexo CSV routes through import review instead of legacy CSV import
- non-Nexo CSV behavior remains unchanged
- batch result links to the created import session for Nexo files

### Frontend tests

- import-review page renders Nexo proposal fields and display-money values
- warning-state rendering for Nexo row issues

## Manual Success Criteria

After this phase:

1. Uploading a Nexo CSV from the app opens a normal import-review session.
2. The review page shows Nexo purchases, fees, and bank cash-outs only.
3. Cashback and internal credit-line mechanics do not appear as draft transactions.
4. Approving the session commits:
   - purchases as expenses
   - fees as expenses with `Financial Fees`
   - bank cash-outs as transfers with `Internal Transfer`
5. The committed transactions appear in transactions and analytics without needing a legacy CSV import path.
6. Imported Nexo purchases remain available for later AI or manual categorization where category was intentionally left blank.

## Implementation Boundary

This spec is intentionally focused on one bounded importer slice:

- one new `nexo_csv` strategy
- one deterministic extractor
- one shared typed-proposal contract migration
- one review-and-approval path

It does not attempt to solve:

- all CSV import unification
- wallet-level Nexo modeling
- cashback product semantics
- arbitrary crypto asset treatment
