# CSV Import Review Consolidation Design

Date: 2026-04-18
Status: Draft for review

## Goal

Replace the legacy direct-commit CSV import stack with one import-review pipeline for all supported CSV providers so Belfius CSV, Beobank CSV, and Nexo CSV all follow the same detect -> extract -> review -> approve -> commit flow.

## User Outcome

When the user uploads or batch-imports a supported CSV file, the app should:

1. detect the provider from file content
2. create an `ImportSession`
3. extract reviewable draft transactions with raw evidence
4. show those rows in the normal import-review UI
5. commit approved rows through the same approval path already used by PDF imports

The user should no longer see CSV files bypass review and land directly in committed transactions.

## Problem Statement

The current repository still has two import architectures:

- the import-review pipeline built around `ImportSession`, `ImportDetector`, and `ImportWorkflowService`
- the legacy CSV lane built around `CSVParser`, `CsvImportService`, and `POST /transactions/upload/`

Keeping both paths has three costs:

1. new providers can be added to the wrong path
2. the product has inconsistent review and approval behavior across file types
3. maintenance work is duplicated across detection, parsing, duplicate handling, classification, and post-commit hooks

The user no longer needs ING or KBC support. The current Belgian CSV providers are Belfius and Beobank, and upcoming providers are ITAU, WISE, and NuBank. This is the right point to delete the old CSV stack instead of extending it again.

## Product Principles

1. One import architecture for PDFs and CSVs.
2. No new provider support in `CSVParser` or `CsvImportService`.
3. Raw imported ledger fields remain immutable in storage.
4. Detection happens from file content, not filenames alone.
5. Extractors own provider semantics; approval owns committing.
6. Approval is the only path that creates committed transactions from imported files.
7. Future CSV providers must add detector + extractor support, not a parallel import lane.

## Decision

Use provider-specific CSV extractors on the import-review pipeline and delete the legacy CSV importer after Belfius, Beobank, and Nexo are migrated.

This means:

- Belfius CSV moves onto import review now
- Beobank CSV moves onto import review now
- Nexo CSV is added only on import review
- ING and KBC CSV support are deleted
- `CSVParser`, `CsvImportService`, and `POST /transactions/upload/` are removed

## Scope

### In scope

- migrating supported CSV imports onto `ImportDetector` + `ImportWorkflowService`
- adding `nexo_csv` strategy support
- activating the existing `belfius_csv` and `beobank_csv` strategy keys
- provider-specific deterministic CSV extractors for Belfius, Beobank, and Nexo
- moving CSV upload and batch-folder routing onto import sessions
- moving CSV upload guardrails off `/transactions/upload/` and onto the import flow
- extending draft and approval contracts so typed transaction proposals survive review
- preserving the needed post-commit behavior after approval
- deleting the old CSV lane and unused ING/KBC support

### Out of scope

- implementing ITAU, WISE, or NuBank extractors in this phase
- adding line-by-line editing inside import review
- keeping backwards compatibility for `/transactions/upload/`
- preserving immediate “upload CSV and get committed transactions back” UX
- generic abstraction for arbitrary tabular imports beyond the current provider set

## Relationship To Prior Designs

This design depends on:

- [2026-04-17-global-reporting-currency-foundation-design.md](/Users/aaat/myfinance/docs/superpowers/specs/2026-04-17-global-reporting-currency-foundation-design.md)
- [2026-04-18-reporting-currency-core-surfaces-design.md](/Users/aaat/myfinance/docs/superpowers/specs/2026-04-18-reporting-currency-core-surfaces-design.md)

It also supersedes the mixed-architecture parts of:

- [2026-04-18-nexo-import-review-design.md](/Users/aaat/myfinance/docs/superpowers/specs/2026-04-18-nexo-import-review-design.md)

That earlier Nexo-only design chose a temporary split where non-Nexo CSVs stayed on the legacy lane. This document intentionally replaces that choice. After this phase, there is no supported legacy CSV lane left in the repository.

## Approaches Considered

### Approach A: Keep the legacy CSV lane and add Nexo elsewhere

Pros:

- smaller immediate diff
- less frontend and test churn

Cons:

- preserves two architectures
- keeps future CSV providers ambiguous
- leaves deletion work for later
- does not satisfy the “no legacy CSV code” requirement

### Approach B: Build a generic CSV engine with pluggable provider rules

Pros:

- potentially less repeated parsing code
- could absorb many future providers

Cons:

- premature abstraction
- current providers differ in header shape, metadata prefaces, account identity, and semantic rules
- risks rebuilding another framework before the product path is stable

### Approach C: Use provider-specific CSV extractors on the review pipeline

Pros:

- matches the existing PDF import architecture
- keeps provider semantics local and testable
- deletes the legacy stack immediately
- leaves a clear extension point for ITAU, WISE, and NuBank

Cons:

- more extractor modules
- requires API and test migration away from `/transactions/upload/`

### Recommendation

Use Approach C.

Small shared helpers are allowed for CSV decoding, header scanning, and evidence capture, but provider semantics stay inside provider extractors rather than a generic CSV parser registry.

## Architecture

The target flow for all supported imported files becomes:

`upload or batch scan -> detect strategy -> extractor -> persist draft -> review -> approve -> commit`

The key architectural boundaries are:

- `ImportDetector` decides strategy from file content
- provider extractors return `ExtractionResult`
- `ImportWorkflowService` persists drafts and proposals
- approval commits from persisted draft data only
- downstream post-commit work runs after approval, not during upload

There is no direct-commit CSV path after this migration.

## Strategy Keys

### Active in this phase

- `pdf_statement`
- `belfius_csv`
- `beobank_csv`
- `nexo_csv`
- `unknown`

### Deferred to later providers

- `itau_csv`
- `wise_csv`
- `nubank_csv`

Those later keys are not required in this implementation, but this phase must leave a clear place to add them without changing the architecture again.

## Detection And Routing

### Detection rules

`ImportDetector` must detect supported CSV providers from file content, not filename alone.

Expected rules:

- Belfius CSV: detect the known semicolon-delimited transaction header even when metadata rows precede it
- Beobank CSV: detect the existing supported Beobank export header shapes
- Nexo CSV: detect the exact ordered comma-delimited Nexo header

For bounded scanning behavior, detector and header-search helpers may scan up to the first 20 physical lines of the file looking for a supported header row. If no supported header is found in that window, detection should return `unknown` rather than scanning the entire file unbounded.

Detection returns:

- `strategy_key`
- `provider_hint`
- `charset_hint`
- `confidence`
- notes explaining the match

Unknown CSVs remain `unknown`, preserving the current charset hint behavior.

### Upload routing

`POST /imports/upload` becomes the only supported file-upload entry point for imported PDFs and CSVs.

Rules:

- PDFs continue to auto-extract after detection
- supported CSVs also auto-extract after detection
- unsupported CSVs fail as import sessions with a clear unsupported strategy error
- the response remains an `ImportSession` snapshot, not committed transactions

### Batch-folder routing

Batch-folder import must detect CSV files before choosing a handler.

Rules:

- supported CSVs create import sessions and extract to `awaiting_review`
- unsupported CSVs are reported as unsupported or failed at the batch-item level
- batch items for CSV review sessions now look like PDF batch items, with `session_id`, `session_status`, `strategy_key`, and `extractor_id`
- batch folder no longer calls `CsvImportService`

### Frontend routing

The frontend CSV upload flow must stop calling `/transactions/upload/`.

Instead it should:

1. upload the file to `/imports/upload`
2. inspect the returned session state
3. navigate to import review when the session is `awaiting_review`
4. show normal import failure states when the session is `failed`

Immediate transaction-list updates on CSV upload are intentionally removed.

## Guardrail Migration

The current CSV upload guardrails on `/transactions/upload/` must move with the feature instead of disappearing.

This phase must preserve:

- content-type filtering for CSV uploads
- file-size limits
- rate limiting
- row-count caps for supported CSV extractors

Guardrails should live with the import-upload flow, not in a deleted endpoint.

Batch preflight limits already live in the batch service and should remain there.

## Extractor Design

### Provider-specific extractor modules

Add deterministic extractor modules under `backend/app/imports/`:

- `belfius_csv.py`
- `beobank_csv.py`
- `nexo_csv.py`

Each extractor should expose the same shape used by PDF extraction:

- `extract(file_path, session_id, attempt_number) -> tuple[RawEvidence, ExtractionResult]`

### Shared helper boundary

A small shared CSV support module is acceptable for:

- charset-aware reading
- delimiter-aware row loading
- scanning for the header row
- building row snapshots for evidence

It must not become a provider registry or own bank-specific semantics.

The preferred implementation uses the Python standard library (`csv`, `io`, and small helper functions) rather than `pandas`. If no runtime code still needs `pandas` after the legacy CSV stack is removed, this migration should drop it from backend dependencies as part of the deletion step.

### Raw evidence

CSV evidence should remain auditable like PDF evidence.

For CSV imports, raw evidence should include enough structured information to explain:

- which header row matched
- which rows were parsed
- which rows were skipped
- the raw field values used by the extractor

The exact representation can use `RawEvidence.snippets` or similarly structured payloads. The key requirement is that review and debugging can inspect the source rows without re-reading the original file manually.

## Draft Contract

The current import draft model is too weak for CSV migration because it stores only:

- raw row values
- `inferred_category`
- `category_source`

That is not enough once approval must commit explicit typed proposals from CSV extractors and imported classification helpers.

### Required draft proposal fields

`ImportTransactionDraft` should carry persisted proposal data for approval-time commit:

- proposed transaction type
- proposed expense category
- proposed income category
- proposed transfer category
- classification source
- recurrence pattern id when a live pattern matched

These fields must be visible in:

- persisted draft rows
- review payloads
- approval commit logic

### Proposal precedence

Proposal precedence should be:

1. deterministic extractor proposal
2. recurrence-pattern proposal
3. upload-suggester proposal
4. no proposal

This keeps strong provider semantics from being overwritten by generic heuristics.

The enrichment step is gap-filling only. It may add missing proposal fields, but it must not overwrite an explicit deterministic extractor proposal that is already present on the draft.

Examples:

- Nexo fee rows keep their deterministic expense and category proposal
- Belfius and Beobank rows can still receive recurrence or suggester proposals where no extractor-specific category exists
- manual user review remains able to override everything before final classification workflows later

## Enrichment Before Review

Deleting the legacy CSV path should not silently discard the useful automation that used to happen there.

The review pipeline must therefore gain a bounded draft-enrichment step for CSV sessions after extraction and before `awaiting_review`.

This step should:

- try recurrence-pattern matching on extracted draft rows
- apply upload-suggester proposals when recurrence did not match and no stronger deterministic proposal exists
- persist the chosen proposal fields on the drafts

This keeps the automation reviewable instead of committing it blindly.

This is also the intentional relocation point for recurrence-pattern matching. In the legacy CSV stack, recurrence matching happened during direct import before commit. After consolidation, recurrence matching moves into pre-review enrichment and is no longer treated as a post-commit hook.

The review page should surface these proposals as imported suggestions, not as final truth.

## Approval And Commit Behavior

### Approval source of truth

`ImportWorkflowService.approve_session()` must commit from persisted draft proposal fields, not by re-deriving meaning from sign alone when stronger proposals exist.

Fallback sign-based type inference remains acceptable only when the draft truly has no explicit proposal.

### Account identity

Provider account identity rules must remain explicit:

- Belfius CSV uses the detected account number hint from the file
- Beobank compact CSV infers the account number from a numeric filename stem, matching the current compact-import behavior
- Beobank debit/credit CSV keeps an empty account number when the file itself does not provide one, matching the current non-compact importer behavior
- Nexo uses the v1 simplified identity `account_number = "NEXO"` and `source_bank = "Nexo"`

### Duplicate checks

Duplicate detection should remain centralized at approval time through the existing workflow duplicate check so CSVs and PDFs follow the same duplicate policy.

### Post-commit hooks

After approval commits transactions, the workflow must handle the downstream effects currently split between the old CSV lane and review approval.

Recurrence-pattern matching is intentionally not in this list because it has moved earlier into pre-review enrichment.

Required post-commit behavior:

- refresh statistics for affected dates
- run anomaly detection for committed transactions
- update the category suggestion index for committed classified income/expense rows

This preserves the needed product behavior without reviving direct commit during upload.

## Provider Rules

### Belfius CSV

The Belfius extractor must support the current export shape with metadata preface rows before the transaction header.

Behavior:

- scan until the known Belfius transaction header row within the bounded detector/header-search window
- parse statement rows deterministically
- preserve raw amount and raw currency from the file
- set explicit account number hints from the statement data
- emit deterministic transaction type proposals from signed amount
- leave category proposals empty unless later enrichment adds them

### Beobank CSV

The Beobank extractor must support the Beobank CSV formats currently accepted by the repository.

This includes:

- the compact semicolon export
- the debit/credit export currently represented by the existing parser support

Behavior:

- preserve the current split account identity behavior:
  - compact export -> numeric filename stem becomes `account_number`
  - debit/credit export -> `account_number` remains empty when the file has no account identifier
- emit deterministic transaction type proposals from debit/credit semantics
- leave category proposals empty unless later enrichment adds them

### Nexo CSV

The Nexo extractor follows the Nexo import review rules already established, with one important difference: it now lives inside the same full CSV consolidation rather than a mixed architecture.

Required behavior:

- preserve raw imported currency codes such as `xUSD`, `USDC`, and `EURX`
- skip internal bookkeeping rows and rejected rows
- emit deterministic typed proposals for purchases, fees, and cash-outs
- keep raw evidence for row-level inspection
- never route through a legacy parser

### Future providers

When ITAU, WISE, or NuBank are added later, they must each implement:

1. detection rule
2. provider extractor
3. account identity rule
4. proposal semantics
5. tests

They must not add code to a deleted generic CSV importer.

## Deletion Plan

Once Belfius, Beobank, and Nexo are working on the review pipeline, delete:

- `backend/app/services/csv_parser.py`
- `backend/app/services/csv_import_service.py`
- `POST /transactions/upload/` in `backend/app/routers/transactions.py`
- frontend code that calls `/transactions/upload/`
- ING and KBC CSV support and related tests
- legacy CSV direct-upload tests whose behavior is no longer part of the product

This deletion is part of the migration, not a later cleanup task.

## Testing Strategy

### Detection tests

Add or update tests proving:

- Belfius CSV detection works with metadata-prefaced files
- Beobank CSV detection works for each supported Beobank shape
- Nexo CSV detection works on exact header match
- unknown CSVs keep charset hints and do not detect falsely

### Workflow tests

Add or update tests proving:

- supported CSV uploads create `ImportSession`s and reach `awaiting_review`
- approval commits the right `source_bank`, account identity, transaction type, and typed proposal fields
- duplicate approval conflicts still block commit
- recurrence and suggester enrichment apply at the draft level rather than during upload
- post-commit hooks run after approval

### Batch tests

Add or update tests proving:

- supported CSV files in the batch folder create review sessions instead of direct imports
- batch items for CSVs now carry session metadata
- unsupported CSVs are reported cleanly

### API and frontend tests

Add or update tests proving:

- `/transactions/upload/` is gone
- the frontend upload flow uses `/imports/upload`
- CSV uploads navigate into import review rather than returning a committed transaction list

### Deletion tests

Remove or rewrite tests that only defend the legacy direct-upload contract, especially tests tied to:

- direct committed transaction responses from upload
- ING or KBC support
- legacy CSV parser internals

## Success Criteria

This phase is successful when:

1. Belfius CSV, Beobank CSV, and Nexo CSV all upload through `/imports/upload`
2. batch CSV imports create review sessions rather than direct commits
3. approving those sessions produces correct committed transactions and downstream analytics effects
4. `CSVParser`, `CsvImportService`, and `/transactions/upload/` are deleted
5. adding a future CSV provider requires only detector + extractor work inside the review pipeline

## Non-Goals

This phase does not try to solve:

- every future CSV provider now
- generic spreadsheet import
- AI-first CSV extraction
- preserving a compatibility facade for the deleted upload endpoint

The point of this design is consolidation, not compatibility.
