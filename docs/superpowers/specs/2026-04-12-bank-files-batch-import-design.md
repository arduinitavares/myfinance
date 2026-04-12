# Bank Files Batch Import Design

Date: 2026-04-12
Status: Draft

## Goal

Add an app button that immediately processes every supported file inside `./bank_files`, reusing the existing import pipeline and review flow, while skipping files that were already processed before.

This is a local-operator workflow. The folder already exists on the same machine as the app. The user does not want to pick files one by one and does not want a terminal command for v1.

## User Outcome

From the app, the user clicks one button and the system:

1. scans `./bank_files`
2. finds supported files
3. ignores files already known by file hash
4. creates import sessions only for new files
5. runs the existing detect/extract workflow for each file
6. shows a batch results screen with one row per file and links into normal per-session review

The button must not silently create duplicate import sessions for the same file content.

## Scope

In scope:

- app button to trigger folder import
- backend route to scan and process `./bank_files`
- file-hash based skipping of already known files
- batch results UI
- links from batch results into existing import review pages
- support for the same file types already supported by the single-file flow

Out of scope:

- background jobs or worker queue
- folder picker UI
- deselecting files before start
- auto-approval
- recursive directory scanning
- editing the batch result after it completes

## Approaches Considered

### Approach A: Synchronous batch endpoint plus batch results page

The app calls one backend endpoint. The backend scans the folder, processes all files synchronously, and returns a complete summary. The frontend then shows a batch results page.

Pros:

- smallest change set
- reuses current upload/detect/extract workflow
- easy to reason about
- fits monthly local use

Cons:

- request lasts until all files finish
- large batches show one long-running spinner instead of live per-file progress

### Approach B: Persistent batch-run model with polling

The app creates a batch run, backend persists batch state, frontend polls until completion.

Pros:

- stronger long-running UX
- refresh-safe by design
- future-friendly if batches get large

Cons:

- much larger scope
- adds new persistence and state-machine surface

### Approach C: App button that shells out to a local script

The app triggers a local script which performs the import and writes a summary file.

Pros:

- can reuse CLI-style logic

Cons:

- weaker app/backend contract
- fragile deployment assumptions
- harder to test inside existing API architecture

### Recommendation

Use Approach A for v1.

It is the cleanest fit for the current architecture and keeps the workflow inside the existing backend/API model. The user explicitly wants an app button, not a terminal command, and the usage pattern is low-frequency enough that a synchronous run is acceptable.

## High-Level Design

### Trigger

Add a new secondary action near the existing upload control:

- primary existing action: `Upload File`
- new action: `Import bank_files`

When clicked, the frontend calls a new backend endpoint and shows a loading state until the batch finishes.

### Backend Batch Route

Add a route:

- `POST /imports/batch-folder`

This route:

1. resolves the folder path to `${repo_root}/bank_files`
2. lists direct children only
3. keeps only supported files
4. computes SHA-256 hash for each file
5. skips files whose hash already exists in `import_sessions.file_hash`
6. for new files, runs the same import creation flow used by file upload
7. immediately runs PDF extraction for PDF statements, exactly like the current single-file upload route
8. returns one summary object covering every discovered file

This route must not mutate or remove files from the folder.

## Duplicate-Skip Rule

The duplicate rule is file-content based, not filename based.

For each discovered file:

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

This rule applies regardless of whether the same file is still present in the folder under the same name or a different name.

This v1 does not try to distinguish between “already committed” and “already failed.” If the file hash was already seen, it is skipped and the user can open the existing session or use the existing retry flow on that session if needed.

## Supported Files

The batch scan must accept the same file types as the current single-file flow:

- `.csv`
- `.pdf`

Unsupported files inside `./bank_files` are not fatal. They should appear in the batch result as:

- `status = unsupported`
- human-readable message

## Processing Contract

### New files

For each new file:

- create a normal `ImportSession`
- persist original artifact
- run detector
- if strategy is `pdf_statement`, immediately run extraction via `ImportWorkflowService.extract_detected_session`
- return final session snapshot in the batch summary

### Skipped existing files

Do not create a new session.

### Extraction failures

These are not fatal to the whole batch. The item should report:

- `status = failed`
- `session_id`
- `session_status`
- `error_message`

### Empty folder

If `./bank_files` exists but contains no supported files, return success with:

- `total_files = 0`
- `items = []`
- message explaining that no importable files were found

### Missing folder

If `./bank_files` does not exist, return `400` with a clear message.

## API Shape

Add response models:

### `ImportBatchItemResponse`

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

Allowed item statuses for v1:

- `processed`
- `skipped_existing`
- `unsupported`
- `failed`

### `ImportBatchResponse`

- `folder_path: str`
- `message: str | None`
- `total_files: int`
- `processed_count: int`
- `skipped_existing_count: int`
- `unsupported_count: int`
- `failed_count: int`
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

- `/imports/batch-results`

The page shows a plain operational list, not a decorative marketing panel.

Each row shows:

- filename
- item status
- short message
- action

Actions:

- `Review` when `session_status = awaiting_review`
- `Open` when a session exists but is failed/rejected/other
- no action for unsupported files with no session

The page must also show summary counts at the top.

### Navigation model

The frontend may navigate to `/imports/batch-results` using route state with the immediate response payload. To survive refresh in v1, it should also mirror the last batch payload into `sessionStorage` and rehydrate from there when opening the results route without in-memory state.

This avoids adding backend persistence for batch runs in v1.

## Error Handling

Frontend button errors:

- missing folder
- backend unavailable
- malformed batch response

These should appear inline in the upload dialog or page area as short operational messages.

Batch item errors must never collapse the whole batch unless the route itself cannot scan the folder at all.

## Testing

### Backend

Add tests for:

- folder scan with mixed CSV/PDF/unsupported files
- file-hash skipping when an existing import session already has the same content
- successful processing creates sessions only for new files
- PDF files still run extraction immediately
- unsupported files are reported but do not fail batch
- missing folder returns `400`

### Frontend

Add tests for:

- new `Import bank_files` button renders
- clicking it calls the new service route
- loading state disables repeat clicks
- success navigates to batch results page
- batch results page renders processed, skipped, failed, and unsupported items
- `Review` links navigate to `/imports/:sessionId/review`
- rehydration from `sessionStorage` works on refresh

## Acceptance Criteria

1. Clicking `Import bank_files` processes all supported files directly inside `./bank_files`.
2. Files already seen before, identified by file hash, are skipped without creating duplicate sessions.
3. New files create normal import sessions and reuse the existing per-file review flow.
4. PDF statements still run extraction immediately, exactly like single-file upload.
5. The user sees one batch results screen with enough detail to open each relevant review session.
6. Unsupported or failed files do not block other files in the same batch.
7. No file in `./bank_files` is deleted, renamed, or moved by this feature.
