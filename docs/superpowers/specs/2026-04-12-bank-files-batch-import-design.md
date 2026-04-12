# Bank Files Batch Import Design

Date: 2026-04-12
Status: Draft

## Goal

Add an app button that immediately processes every supported statement file inside the configured `bank_files` folder, reusing the existing import-session review flow and safely reusing or replacing same-hash sessions when needed.

This is a local-operator workflow. The folder already exists on the same machine as the app. The user does not want to pick files one by one and does not want a terminal command for v1.

## User Outcome

From the app, the user clicks one button and the system:

1. scans the configured `bank_files` folder
2. lists direct child files in stable filename order
3. reports unsupported files in the batch result
4. reuses usable existing PDF sessions already known by file hash
5. creates import sessions only for new supported PDF files
6. runs the existing detect/extract workflow for each new PDF
7. shows a persisted batch results screen with one row per file and links into normal per-session review

The button must not silently create duplicate import sessions for the same file content.

## Scope

In scope:

- app button to trigger folder import
- backend route to scan and process the configured folder
- duplicate-safe reuse or replacement of already known PDF import sessions
- duplicate-safe behavior for the existing single-file PDF upload route
- migration/backfill rule needed to make `ImportSession.file_hash` unique safely
- lightweight persisted batch-run summary
- batch results UI backed by persisted batch data
- links from batch results into existing import review pages
- support for the same file types already on the import-session review path in v1

Out of scope:

- batching the current CSV transaction-upload path
- background jobs or worker queue
- folder picker UI
- deselecting files before start
- auto-approval
- recursive directory scanning
- editing the batch result after it completes

## Current-System Constraint

V1 must be honest about the current architecture.

Today:

- PDF statement upload goes through `/imports/upload`, creates `ImportSession`, stores `file_hash`, and enters review
- CSV upload goes through `/transactions/upload/` and commits transactions directly

Because CSV does not currently create `ImportSession` rows, `import_sessions.file_hash` cannot prove that a CSV was "already processed before" if the user imported it through the existing CSV path.

For that reason, v1 batch import is intentionally limited to the import-session lane only.

This design also owns the shared import-contract change required to make PDF dedupe safe across all import entry points.

## Approaches Considered

### Approach A: PDF-only batch import with persisted batch-run summary

The app calls one backend endpoint. The backend scans the folder, creates a lightweight batch-run record, processes supported PDF files synchronously, persists per-file outcomes, and returns the batch id plus summary. The frontend navigates to a results page backed by backend state.

Pros:

- matches the real import-session architecture
- preserves refresh/retry visibility
- keeps duplicate detection honest
- small enough for v1 while still operationally reliable

Cons:

- CSV files are not batch-imported in v1
- request lasts until all files finish
- still no live streaming progress in v1

### Approach B: Unify CSV onto import sessions first, then batch both PDF and CSV

Pros:

- single ingestion model
- one duplicate rule for all importable files
- cleaner long-term architecture

Cons:

- much larger scope
- delays the immediate folder-import workflow
- forces a separate CSV pipeline redesign before shipping this feature

### Approach C: Hybrid batch endpoint that processes PDFs via import sessions and CSVs via direct transaction upload

Pros:

- imports more file types right away

Cons:

- duplicate semantics differ by file type
- batch results cannot truthfully reuse one review model
- retry/recovery becomes confusing
- higher risk of duplicate CSV imports

### Recommendation

Use Approach A for v1.

It is the smallest design that stays true to the existing codebase and preserves safe duplicate handling for previously seen files. CSV batch import should come later, after CSV ingestion is moved onto import sessions or intentionally designed as a separate lane.

## Runtime Folder Contract

The backend must not guess `repo_root`.

Add a backend setting:

- `MYFINANCE_BATCH_IMPORT_DIR`

Default local/runtime value for the app environment:

- `/bank_files`

Docker/local runtime must mount the host folder read-only into the backend container, for example:

- host `./bank_files`
- container `/bank_files`

If the configured folder does not exist, the route returns `400` with a clear operational message.

The batch scan reads direct children only. No recursive traversal in v1.

## Supported Files

V1 batch import supports only file types that also use the `ImportSession` review flow today:

- `.pdf`

Files such as `.csv` are still surfaced in the batch results, but they are not processed in v1. They must appear as:

- `status = unsupported`
- message such as `CSV batch import is not supported in v1; use Upload File.`

Unsupported files are not fatal to the whole batch.

## Guardrails

To keep the synchronous route operationally safe in v1:

- scan at most 200 direct child files in the configured folder
- process at most 50 supported PDF files in one batch run
- reuse the existing per-file upload size limit of 5 MB

If the folder exceeds these guardrails, the route returns `400` before creating a batch run, with a message explaining which limit was exceeded.

Files are processed in stable filename order using case-insensitive sorting.

## Concurrency And Crash Safety

V1 must make the duplicate-skip promise true even under concurrent requests.

### File-hash dedupe under concurrency

`ImportSession.file_hash` must become database-unique in v1, not only indexed.

Backend rule:

- add a unique constraint on `import_sessions.file_hash`
- continue to pre-check for an existing hash for the common fast path
- treat the database constraint as the final source of truth for both batch import and single-file upload

If two `POST /imports/batch-folder` requests race on the same PDF:

- at most one request may create the new `ImportSession`
- the losing request must catch the uniqueness conflict
- it must re-query the existing session by `file_hash`
- it must apply canonical-session precedence to the re-queried owner
- it must persist the batch item as `skipped_existing` only when that owner is usable
- it may create a replacement session instead when the owner is non-retryable
- it must not surface the conflict as a duplicate-creating success

This keeps dedupe correct without adding a separate batch mutex.

### Shared single-file upload behavior

Because `file_hash` uniqueness applies globally, the existing `POST /imports/upload` route must change as part of this design.

New rule for duplicate single-file PDF upload:

- if upload bytes hash to an existing `ImportSession.file_hash`, the route must not return `500`
- it must catch the uniqueness conflict or fast-path duplicate lookup
- it must re-query the existing session by `file_hash`
- it must apply canonical-session precedence to the returned owner
- it must return `409 Conflict` with a structured duplicate payload only when that owner is usable
- it may create a replacement session instead when the owner is non-retryable

Duplicate response payload:

- `message`
- `file_hash`
- `existing_session` as normal `ImportSessionResponse`

User-facing meaning:

- the file was already uploaded before
- no new session was created
- the frontend should offer an `Open Existing` action that routes to the existing review/session page when the existing session is usable

This replaces the current accidental behavior where duplicate PDF bytes can create a second session and fail only later at approval.

### Canonical session precedence

Hash ownership must point to the most useful session, not simply the oldest session.

Canonical-session precedence for identical PDF bytes:

1. `COMMITTED` or `PARTIALLY_COMMITTED`
2. `AWAITING_REVIEW`
3. retryable `FAILED`
4. all other sessions

Break ties within a precedence tier by oldest `created_at`.

Define a retryable failed session as all of:

- `status = FAILED`
- `strategy_key = pdf_statement`
- original uploaded file still exists in the session artifact directory at `original/<file_name>`

A failed session that does not satisfy all three rules is non-retryable.

### Non-retryable escape hatch

If the current exact-hash owner is non-retryable, the backend must not poison that file hash forever.

Instead, the backend may create a replacement session:

1. rewrite the broken owner's `file_hash` to a legacy non-colliding surrogate
2. set its status to `SUPERSEDED` when the state model allows that transition; otherwise preserve the status and relinquish ownership only through the rewritten `file_hash`
3. create a fresh session that takes ownership of the real SHA-256 hash

This rule applies to both:

- duplicate single-file `/imports/upload`
- batch-folder processing

The result is:

- usable existing owner -> return or skip to the existing session
- non-retryable existing owner -> create a replacement session instead of hard-blocking forever

### Existing-data migration rule

Before adding the unique constraint, the migration must handle any pre-existing duplicate `file_hash` groups.

Migration rule for duplicate groups:

- select the canonical session using canonical-session precedence
- preserve all duplicate session rows for audit/history
- rewrite the non-canonical duplicate rows to a legacy non-colliding `file_hash` form such as `<original_hash>#legacy-duplicate#<session_id>`
- set non-canonical rows to `SUPERSEDED` when the state model allows that transition; if a row is already `COMMITTED` or `PARTIALLY_COMMITTED`, preserve its status and rewrite only the stored `file_hash`

This migration rule exists only to unblock the uniqueness constraint safely. Going forward, real SHA-256 file hashes remain unique across new uploads.

### Batch-run terminalization on uncaught error

Every batch run must end in exactly one terminal state:

- `completed`
- `failed`

Any uncaught processing error after the batch row exists must trigger top-level rescue logic:

- mark the current batch item `failed` when enough context exists to identify it
- preserve already-finished item rows exactly as they were
- update counts to reflect finished work and the failed item when applicable
- mark the batch run `failed`
- set `completed_at`
- persist a human-readable batch-level message

No persisted batch may remain forever in `running` because the request crashed mid-run.

## High-Level Design

### Trigger

Add a new secondary action near the existing upload control:

- primary existing action: `Upload File`
- new action: `Import bank_files`

When clicked, the frontend calls a new backend endpoint and shows a loading state until the batch request returns.

### Backend Batch Routes

Add routes:

- `POST /imports/batch-folder`
- `GET /imports/batches/{batch_id}`
- `GET /imports/batches/latest`

`POST /imports/batch-folder`:

1. resolves the folder from `MYFINANCE_BATCH_IMPORT_DIR`
2. preflights folder existence and guardrails
3. creates a persisted batch-run row
4. scans direct child files in stable order
5. computes SHA-256 hash for supported PDFs
6. reuses usable existing same-hash PDF sessions and replaces non-retryable owners when necessary
7. creates import sessions only for new PDFs or approved replacement cases
8. immediately runs PDF extraction exactly like the current single-file import route
9. persists one batch-item row per discovered file
10. ends the batch in terminal state `completed` or `failed`
11. returns the full summary

`GET /imports/batches/{batch_id}` returns the persisted batch summary.

`GET /imports/batches/latest` returns the most recent batch summary by `created_at DESC` for this backend instance so the UI can recover after refresh or a dropped client request.

Related shared route change:

- `POST /imports/upload` now returns either normal `ImportSessionResponse` for a new upload or `409` duplicate payload for an already-known file hash
- if the exact-hash owner is non-retryable, `POST /imports/upload` may create a replacement session instead of returning `409`

## Persisted Batch Summary

V1 must persist batch outcomes server-side.

Add lightweight persistence models:

### `ImportBatchRun`

- `id`
- `folder_path`
- `status` (`running`, `completed`, `failed`)
- `message`
- `total_files`
- `processed_count`
- `skipped_existing_count`
- `unsupported_count`
- `failed_count`
- `created_at`
- `completed_at`

### `ImportBatchItem`

- `id`
- `batch_run_id`
- `filename`
- `file_hash`
- `status`
- `message`
- `session_id`
- `session_status`
- `existing_session_id`
- `existing_session_status`
- `strategy_key`
- `extractor_id`
- `started_at`
- `completed_at`

This batch persistence is intentionally lightweight. It is for operator recovery and truthful reporting, not for a long-running jobs system.

Retention for v1:

- no automatic cleanup
- batch-run rows remain until a later maintenance feature defines pruning

## Duplicate-Skip Rule

The duplicate rule is file-content based, not filename based.

For each supported PDF file:

- compute SHA-256 from file bytes
- query `ImportSession.file_hash`
- if a usable owner already exists with the same hash, do not create a new import session
- instead emit a batch item with status `skipped_existing`
- if no row exists, attempt session creation under the unique `file_hash` constraint
- if uniqueness is lost to a concurrent request, re-query using canonical-session precedence and either emit `skipped_existing` or create a replacement session when the owner is non-retryable

The batch item must include:

- `filename`
- `file_hash`
- `status = skipped_existing`
- `existing_session_id`
- `existing_session_status`

This rule is valid in v1 precisely because supported batch files are limited to the import-session lane.

The same file-hash rule also applies to the normal single-file PDF upload route.

## Processing Contract

### New PDF files

For each new supported PDF file:

- create a normal `ImportSession`
- persist the original artifact
- run detector
- if strategy is `pdf_statement`, immediately run extraction via `ImportWorkflowService.extract_detected_session`
- if strategy is not `pdf_statement`, do not attempt extraction; persist the item as terminal `failed` with a clear message that this PDF did not match the supported PDF-statement strategy
- persist the batch item with the resulting session id and session status

### Skipped existing PDF files

Do not create a new session.

Persist a batch item with:

- `status = skipped_existing`
- existing session linkage

Report `skipped_existing` only when the exact-hash owner is usable under canonical-session precedence.

If the exact-hash owner is retryable `FAILED`, the user can open the existing session and use the normal retry flow there.

If the exact-hash owner is non-retryable, do not report `skipped_existing`; create a replacement session instead.

### Unsupported files

Do not create a session.

Persist a batch item with:

- `status = unsupported`
- explanatory message

### Extraction failures

These are not fatal to the whole batch.

Persist a batch item with:

- `status = failed`
- `session_id`
- `session_status`
- `message`

If some files fail and others succeed, the batch run still completes with accurate counts.

Unexpected route-level failure after batch creation is different from an expected per-file failure: in that case the batch run itself ends as `failed`, with partial finished items preserved.

### Empty folder

If the configured folder exists but contains no direct child files, return success with:

- `total_files = 0`
- `items = []`
- message explaining that no files were found

If the folder has files but none are supported PDFs, also return success with persisted `unsupported` items and zero processed items.

## API Shape

### `ImportBatchItemResponse`

- `id: int`
- `filename: str`
- `file_hash: str | None`
- `status: str`
- `message: str | None`
- `session_id: int | None`
- `session_status: str | None`
- `existing_session_id: int | None`
- `existing_session_status: str | None`
- `strategy_key: str | None`
- `extractor_id: str | None`
- `started_at: datetime | None`
- `completed_at: datetime | None`

Allowed item statuses for v1:

- `processed`
- `skipped_existing`
- `unsupported`
- `failed`

For v1, `processed` means a new `ImportSession` was created and the route reached a stable per-file outcome. The final `session_status` may still be `awaiting_review` or `failed`, so callers must inspect `session_status` as well as the batch item status.

For v1, a `.pdf` file that reaches detection but does not end up on `pdf_statement` must be reported as terminal `failed`, not silently ignored.

### `ImportBatchResponse`

- `id: int`
- `folder_path: str`
- `status: str`
- `message: str | None`
- `total_files: int`
- `processed_count: int`
- `skipped_existing_count: int`
- `unsupported_count: int`
- `failed_count: int`
- `created_at: datetime`
- `completed_at: datetime | None`
- `items: list[ImportBatchItemResponse]`

Run status semantics:

- `completed` means the route finished scanning and item processing, even if some individual items are `failed`
- `failed` means the batch itself terminated early because of an uncaught route-level processing error after the run was created

### Single-file duplicate response

`POST /imports/upload` duplicate outcome:

- status code `409`
- payload fields:
  - `message: str`
  - `file_hash: str`
  - `existing_session: ImportSessionResponse`

Return this `409` shape only when the exact-hash owner is usable. If the exact-hash owner is non-retryable, the route should create and return a fresh replacement session instead.

## Frontend UX

### Entry point

Extend the current upload UI in `FileUpload.tsx` with a second button:

- `Import bank_files`

When running:

- disable both import buttons
- show clear progress text such as `Processing bank_files...`

### Result surface

Add a new route:

- `/imports/batches/:batchId`

The page shows an operational list, not a decorative panel.

At the top, show:

- batch status
- folder path
- created/completed timestamps
- summary counts

Each row shows:

- filename
- item status
- short message
- action

Actions:

- `Review` when `session_status = awaiting_review`
- `Open` when a session exists but is failed/rejected/other
- `Open Existing` when the item was skipped as already known
- no action for unsupported files with no session

### Navigation model

After `POST /imports/batch-folder` succeeds, the frontend navigates to:

- `/imports/batches/:batchId`

The result page loads its state from `GET /imports/batches/{batch_id}`.

The frontend may use the immediate POST response to avoid a blank first paint, but backend persistence is the source of truth.

To recover from refresh or a dropped request, the frontend may also use:

- `GET /imports/batches/latest`

No `sessionStorage`-only recovery in v1.

The UI should treat `latest` as an operator convenience entry point, not as a replacement for explicit batch ids.

## Error Handling

Frontend button errors:

- missing configured folder
- batch guardrail violation
- backend unavailable
- malformed batch response

These should appear inline in the upload dialog or page area as short operational messages.

Per-file failures must never collapse the whole batch unless the route itself cannot preflight or scan the folder at all.

If the route fails after creating the batch run, the response may still be `500`, but persisted recovery data must show the batch in terminal state `failed` with partial finished items preserved.

## Testing

### Backend

Add tests for:

- folder scan with mixed PDF, CSV, and unsupported files
- PDF files are processed and CSV files are reported as unsupported
- file-hash skipping when an existing import session already has the same PDF content
- uniqueness-conflict path resolves to `skipped_existing` or replacement session according to owner usability
- canonical-session selection prefers useful owner over oldest owner
- non-retryable same-hash owner is superseded and replaced by a fresh session
- duplicate single-file `/imports/upload` returns `409` with existing session payload for usable owners, not `500`
- successful processing creates sessions only for new PDFs
- PDF files still run extraction immediately
- non-`pdf_statement` PDF detection path becomes terminal item `failed`
- unsupported files are reported but do not fail batch
- batch run and batch items are persisted
- uncaught mid-run exception marks the batch run `failed` with `completed_at`
- latest-batch route returns the most recent run
- missing folder returns `400`
- too many files returns `400`
- migration test covers pre-existing duplicate `file_hash` rows before uniqueness is applied, using canonical-session precedence instead of oldest-wins

### Frontend

Add tests for:

- new `Import bank_files` button renders
- clicking it calls the new batch route
- loading state disables repeat clicks
- success navigates to `/imports/batches/:batchId`
- batch results page renders processed, skipped, failed, and unsupported items
- `Review` links navigate to `/imports/:sessionId/review`
- `GET /imports/batches/{batch_id}` powers page reload correctly
- latest-batch recovery path works when the page is reopened without in-memory state

## Acceptance Criteria

1. Clicking `Import bank_files` processes all supported PDF files directly inside the configured folder.
2. PDF files already seen before, identified by file hash in `ImportSession`, either reuse a usable existing session or replace a non-retryable owner without creating duplicate live hash ownership.
3. New PDF files create normal import sessions and reuse the existing per-file review flow.
4. PDF statements still run extraction immediately, exactly like single-file upload.
5. CSV files inside the folder are surfaced clearly as unsupported in v1 and are not imported silently.
6. The user sees one persisted batch results screen with enough detail to open each relevant review session.
7. Refreshing or reopening the batch results page still shows truthful per-file outcomes from backend state.
8. Unsupported or failed files do not block other files in the same batch.
9. No file in the configured folder is deleted, renamed, or moved by this feature.
10. Backend runtime resolves the folder through `MYFINANCE_BATCH_IMPORT_DIR`, not by guessing repo-root paths.
11. Concurrent batch requests do not create duplicate `ImportSession` rows for the same PDF bytes.
12. Every persisted batch run ends in terminal state `completed` or `failed`, never stuck indefinitely in `running`.
13. Duplicate single-file PDF upload returns structured `409` duplicate information for usable owners instead of creating a second session or returning `500`.
14. A non-retryable same-hash session does not poison future uploads; the backend can supersede it and create a replacement session.
