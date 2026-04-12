# Bank Files Batch Import Design

Date: 2026-04-12
Status: Draft

## Goal

Add an app button that immediately processes every supported statement file inside the configured `bank_files` folder, reusing the existing import-session review flow, while skipping files that were already processed before.

This is a local-operator workflow. The folder already exists on the same machine as the app. The user does not want to pick files one by one and does not want a terminal command for v1.

## User Outcome

From the app, the user clicks one button and the system:

1. scans the configured `bank_files` folder
2. lists direct child files in stable filename order
3. reports unsupported files in the batch result
4. skips PDF files already known by file hash
5. creates import sessions only for new supported PDF files
6. runs the existing detect/extract workflow for each new PDF
7. shows a persisted batch results screen with one row per file and links into normal per-session review

The button must not silently create duplicate import sessions for the same file content.

## Scope

In scope:

- app button to trigger folder import
- backend route to scan and process the configured folder
- file-hash based skipping of already known PDF import sessions
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

It is the smallest design that stays true to the existing codebase and preserves the user promise that previously processed files are skipped safely. CSV batch import should come later, after CSV ingestion is moved onto import sessions or intentionally designed as a separate lane.

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
6. skips PDFs whose hash already exists in `import_sessions.file_hash`
7. creates import sessions only for new PDFs
8. immediately runs PDF extraction exactly like the current single-file import route
9. persists one batch-item row per discovered file
10. marks the batch run complete and returns the full summary

`GET /imports/batches/{batch_id}` returns the persisted batch summary.

`GET /imports/batches/latest` returns the most recent batch summary so the UI can recover after refresh or a dropped client request.

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

## Duplicate-Skip Rule

The duplicate rule is file-content based, not filename based.

For each supported PDF file:

- compute SHA-256 from file bytes
- query `ImportSession.file_hash`
- if a row already exists with the same hash, do not create a new import session
- instead emit a batch item with status `skipped_existing`

The batch item must include:

- `filename`
- `file_hash`
- `status = skipped_existing`
- `existing_session_id`
- `existing_session_status`

This rule is valid in v1 precisely because supported batch files are limited to the import-session lane.

## Processing Contract

### New PDF files

For each new supported PDF file:

- create a normal `ImportSession`
- persist the original artifact
- run detector
- if strategy is `pdf_statement`, immediately run extraction via `ImportWorkflowService.extract_detected_session`
- persist the batch item with the resulting session id and session status

### Skipped existing PDF files

Do not create a new session.

Persist a batch item with:

- `status = skipped_existing`
- existing session linkage

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

## Error Handling

Frontend button errors:

- missing configured folder
- batch guardrail violation
- backend unavailable
- malformed batch response

These should appear inline in the upload dialog or page area as short operational messages.

Per-file failures must never collapse the whole batch unless the route itself cannot preflight or scan the folder at all.

## Testing

### Backend

Add tests for:

- folder scan with mixed PDF, CSV, and unsupported files
- PDF files are processed and CSV files are reported as unsupported
- file-hash skipping when an existing import session already has the same PDF content
- successful processing creates sessions only for new PDFs
- PDF files still run extraction immediately
- unsupported files are reported but do not fail batch
- batch run and batch items are persisted
- latest-batch route returns the most recent run
- missing folder returns `400`
- too many files returns `400`

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
2. PDF files already seen before, identified by file hash in `ImportSession`, are skipped without creating duplicate sessions.
3. New PDF files create normal import sessions and reuse the existing per-file review flow.
4. PDF statements still run extraction immediately, exactly like single-file upload.
5. CSV files inside the folder are surfaced clearly as unsupported in v1 and are not imported silently.
6. The user sees one persisted batch results screen with enough detail to open each relevant review session.
7. Refreshing or reopening the batch results page still shows truthful per-file outcomes from backend state.
8. Unsupported or failed files do not block other files in the same batch.
9. No file in the configured folder is deleted, renamed, or moved by this feature.
10. Backend runtime resolves the folder through `MYFINANCE_BATCH_IMPORT_DIR`, not by guessing repo-root paths.
