# Statement Import Design

Date: 2026-04-11
Status: Draft for review
Scope: shared import foundation for Belfius CSV, Beobank CSV, Belfius PDF, and Beobank PDF, with room for future providers such as Nubank

## Goals

- Build a reusable statement-import pipeline for structured CSVs and unstructured PDFs.
- Keep the current one-file upload UX.
- Use deterministic parsing for known CSV formats.
- Use AI-backed extraction for PDFs and other unstructured statement formats.
- Preserve a full local audit trail for every import session.
- Require explicit human review before any imported data is committed.
- Make the system contributor-friendly: mockable tests, no real provider calls in CI, secrets only via environment variables.

## Non-Goals

- Bulk import from folders in v1.
- Direct commit from extraction without review.
- Requiring paid or cloud providers for normal development or CI.
- A single all-in-one importer PR.

## High-Level Architecture

The import pipeline has one invariant flow:

`upload -> detect -> extract -> normalize -> validate -> review -> commit`

Downstream stages must not branch on extractor-specific behavior. They operate only on a shared extraction contract.

### Detection

Detection produces a `DetectionResult`:

- `strategy_key`: one of `belfius_csv`, `beobank_csv`, `pdf_statement`, `unknown`
- `provider_hint`
- `language_hint`
- `charset_hint`
- `confidence`
- `page_count`
- `password_protected`
- `notes`

The pipeline uses only `strategy_key` to choose an extractor. Extractors receive the full `DetectionResult` as soft hints.

### Extraction

Extraction is a strategy interface:

- `BelfiusCsvExtractor`
- `BeobankCsvExtractor`
- `PdfAiExtractor`

Known CSVs are parsed deterministically. PDFs use an AI-backed extractor.

### PDF decomposition

PDF import separates evidence gathering from structured extraction:

`PdfAiExtractor`
- `gather_evidence(file) -> RawEvidence`
  - `TextLayerReader`
  - `OcrReader` fallback
- `extract_structure(evidence) -> ExtractionResult`
  - `AiStructuredExtractor`

This makes OCR and prompt debugging independently inspectable and retryable.

## Shared Contracts

### ExtractionResult

Every extractor returns the same canonical object:

- `extractor_id`
- `raw_artifact_ref`
- source metadata:
  - `provider_hint`
  - `file_type`
  - `language`
- statement metadata:
  - `account_number_hint`
  - `card_number_hint`
  - `statement_period_start`
  - `statement_period_end`
  - `currency`
  - balances and summary fields when available
- `transactions[]`
  - `transaction_date`
  - `source_description`
  - `canonical_description_en` (nullable in early PRs)
  - `signed_amount`
  - `currency`
  - `debit_credit`
  - `inferred_category` (nullable)
  - `category_source`
  - per-field confidence
  - `source_locator`
- `issues[]`
- `warnings[]`
- overall confidence

### RawEvidence

Serializable intermediate evidence gathered before structured extraction:

- CSV parse tree or row/column mapping for deterministic sources
- extracted PDF text
- OCR output
- page snippets
- coordinates / citations / bounding boxes when available

## Data Model and Audit

Artifacts are stored locally on disk and never committed to git.

### Artifact layout

`backend/app/data/imports/<session_id>/`
- `meta.json`
- `original/<filename>`
- `detection.json`
- `evidence/...`
- `ai/request.json`
- `ai/response.json`
- `normalized/extraction_result.json`

`backend/app/data/` must remain gitignored broadly.

`meta.json` should contain the session manifest, including `DetectionResult`, current state, attempt count, and stage timestamps.

### Database tables

#### `import_sessions`

- `id`
- `file_name`
- `file_hash`
- `mime_type`
- `status`
- `strategy_key`
- `provider_hint`
- `language_hint`
- `charset_hint`
- `extractor_id`
- `raw_artifact_ref`
- `error_stage`
- `error_message`
- `approved_by`
- timestamps

#### `import_statement_drafts`

- `id`
- `import_session_id`
- `attempt_number`
- statement metadata
- summary fields
- balances
- `account_number_hint`
- `card_number_hint`
- overall confidence
- review status

#### `import_transaction_drafts`

- `id`
- `import_statement_draft_id`
- raw transaction fields
- `source_description`
- `canonical_description_en`
- `signed_amount`
- `currency`
- `source_locator`
- `inferred_category`
- `category_source`
- confidence fields
- `edit_source`

#### `import_issues`

- `id`
- `import_session_id`
- `attempt_number`
- severity
- `blocking`
- issue code
- issue message
- optional transaction reference

### Committed transaction traceability

Committed transactions should eventually carry:

- `import_session_id`
- `source_locator`
- `source_description`
- `canonical_description_en`

Do not overwrite the original statement text with translated text in v1.

### Duplicate detection

- whole-file duplicate key: `file_hash`
- transaction duplicate fingerprint:
  - `statement_account_or_card_hint`
  - `transaction_date`
  - `signed_amount`
  - `currency`
  - normalized `source_description`
  - `provider_hint`

`source_locator` is supporting evidence only.

Normalized source description means:

- lowercase
- trim outer whitespace
- collapse internal whitespace
- strip inline currency symbols when present

This normalization function must be documented and tested independently.

## Review and Approval

Every import requires explicit review before commit.

### Session state machine

Allowed states:

- `uploaded`
- `detected`
- `extracted`
- `normalized`
- `validated`
- `awaiting_review`
- `approved`
- `committing`
- `committed`
- `failed`
- `rejected`
- `superseded`
- `partially_committed` (reserved for future use)

`committed` is reachable only from `approved`.

State transitions must be enforced through a single transition table, not ad-hoc conditionals.

### Review UI

The upload UI stays simple. After extraction, the user lands on a review screen with:

- statement summary
- issue summary
- transaction table
- evidence panel
- actions: `Approve`, `Reject`, `Retry extraction`, `Edit draft fields`

Blocking issues prevent approval. Warnings remain visible but do not block approval.

For PDF evidence, show the raw text snippet in addition to technical coordinates.

### Retry model

Retries create a new draft attempt under the same `import_session_id`.

- prior attempt artifacts remain intact
- new attempt increments `attempt_number`
- session returns through `extracted -> normalized -> validated -> awaiting_review`
- prior attempts can be marked `superseded`

## Provider Configuration

Provider policy lives in backend config, not the UI.

### Provider families

- `document_extraction`
- `translation_normalization`
- `category_inference`
- `duplicate_detection` (reserved; local-only in v1)

### Config model

Each family defines:

- ordered provider list
- fallback rules
- thresholds for low-confidence fallback

Fallback rules should be explicit objects, for example:

- `condition: low_confidence`
- `threshold: 0.75`

Each provider defines:

- `enabled`
- `kind`
- `model`
- `base_url`
- `api_key_env`
- `timeout_seconds`
- `max_retries`
- `supports_pdf`
- `supports_images`
- `supports_json_schema`
- `cost_tier`
- `requires_confirmation`

`config.example.yaml` must ship with all providers disabled by default. Local overrides live in gitignored config files and env vars.

### Provider registry rules

At startup, `ProviderRegistry.validate()` must:

- warn on missing required credentials
- mark unavailable providers clearly
- allow automatic fallback when later providers are available
- emit non-blocking import issues when configured providers are skipped
- fail only when a required chain has no usable provider

### Prompt ownership

Config answers:

- who runs
- in what order
- under what fallback conditions

Provider implementations own:

- prompts
- schemas
- model-specific formatting

Each provider should expose `describe()` for audit logging of model, schema, and prompt version.

## Testing and CI

Default test suites must not require live provider calls.

### Required testing shape

- unit tests for detection, normalization, duplicate fingerprinting, and state transitions
- fixture-backed parser tests for CSV extractors
- mocked provider tests for AI-backed flows
- live-provider tests isolated under a separate test target and never included in default CI

### CI policy

GitHub Actions should run:

- backend tests
- parser fixture tests
- basic frontend checks

GitHub Actions should not run:

- live OpenAI/OpenRouter/Ollama tests

Fixture sanitization checklist:

- no real account numbers
- no real card numbers
- no real names
- plausible but fake amounts
- shifted or randomized date ranges
- non-traceable file hashes

The repo should include a sanitizer helper script early in the importer effort.

## PR Roadmap

1. `import-foundation`
   - shared pipeline skeleton
   - detection and extraction contracts
   - state machine
   - artifact layout
   - draft tables
   - provider registry
   - fixture-safe test harness

2. `belfius-csv-import`
   - deterministic Belfius CSV support
   - encoding handling
   - fixture-backed tests

3. `beobank-csv-import`
   - deterministic Beobank CSV support
   - fixture-backed tests

4. `pdf-evidence-pipeline`
   - PDF detection
   - text extraction
   - OCR fallback scaffolding
   - `RawEvidence`

5. `pdf-ai-extraction`
   - `PdfAiExtractor`
   - structured extraction via providers
   - confidence handling
   - attempt retries

6. `review-workflow-ui`
   - review screen
   - issue handling
   - approval / rejection / retry / edit flow

7. `category-normalization-and-translation`
   - canonical English description generation
   - category source tracking
   - override tracking

8. `docs-and-contributor-setup`
   - contributor docs
   - provider setup docs
   - fixture guidance
   - importer testing guidance

Notes:

- PRs 2 and 3 can proceed in parallel after PR 1 merges.
- PR 6 can begin early against mock extraction data.
- `canonical_description_en` should remain nullable until PR 7 lands.

## GitHub Workflow

Work in the fork first.

### Daily workflow

1. Create a tracking issue in the fork.
2. Create child issues per PR-sized slice.
3. Branch from fork `main` using `codex/<slug>`.
4. Open a draft PR early from branch to fork `main`.
5. Let GitHub Actions run on each push.
6. Keep each PR tightly scoped.
7. Merge only when green.
8. Promote only mature, generic slices upstream.

### Upstream-worthiness criteria

- generic infrastructure or broadly useful provider support
- fixture-backed tests
- no personal secrets
- no machine-specific assumptions
- no required paid provider for normal development or CI
- no dependency on fork-only internal config that upstream does not have

## Versioning and Upstream Sync Policy

- The fork remains upstream-aware and regularly rebases or merges from `upstream/main`.
- Importer work lands in the fork first.
- Upstream PRs are cut from focused, upstream-safe branches after the slice is stable in the fork.
- The fork does not need independent semver in v1; it tracks upstream plus documented fork-only features.

## Open Questions for Later

- exact schema for committed transaction traceability migration
- how far user editing should go in v1 review UI
- whether semantic duplicate detection should move beyond local rules
- whether LlamaExtract or other provider backends are worth adding after the provider abstraction exists
