# Classification Similarity Batching Design

Date: 2026-04-19
Status: Draft for review

## Goal

Remove redundant embedding work from the classification similar-preview flow while preserving the current matching rules and user-visible behavior.

This pass focuses on:

1. batching one-to-many similarity scoring for preview and batch-apply candidate selection
2. preserving all current business filters, thresholding, sorting, and result limits
3. silencing sentence-transformer progress bars across the category suggestion service
4. keeping the change narrow to the observed hot path rather than refactoring unrelated indexing flows

## User Outcome

When a classification is accepted and the app previews similar transactions:

1. the backend should still return the same kind of preview matches
2. the matching rules should remain conservative and unchanged
3. the similar-preview response should no longer trigger repeated single-item embedding work for every candidate
4. Docker and backend logs should no longer fill with repeated `Batches: 1/1` lines from sentence-transformers

The same improvement should apply to `apply-batch`, because it already reuses the same candidate-selection path.

## Problem Statement

The current similar-preview path re-embeds the same seed description for every candidate transaction and also embeds each candidate one at a time. That creates two sentence-transformer encode calls per surviving candidate in an interactive backend request path.

The observed runtime trace confirms this pattern:

- one encode call occurs during accepted-transaction indexing, which is expected
- the similar-preview request then emits repeated `Batches: 1/1` lines in pairs
- those pairs map to `similarity_score(seed, candidate)` being called inside the `_similar_candidates(...)` loop

The affected code path is:

- [classification_session_service.py](/Users/aaat/myfinance/backend/app/services/classification_session_service.py)
- [category_suggestion_service.py](/Users/aaat/myfinance/backend/app/services/category_suggestion_service.py)

This matters because:

1. the preview path does avoidable embedding work in a user-triggered flow
2. the same redundant work is repeated again when `apply-batch` reuses the preview logic
3. service logs are noisy because sentence-transformers prints a progress bar for each single-item encode call

The problem is not the accepted-transaction indexing call itself. That single encode is expected because the vector must be stored for future suggestions.

## Product Principles

1. Fix the observed hot path first.
2. Keep business matching rules unchanged unless the problem demands otherwise.
3. Keep embedding and cosine math inside the suggestion service, not the session service.
4. Avoid introducing a broad bulk-embedding contract without a demonstrated need.
5. Silence progress-bar noise wherever this service calls the transformer.

## Decision

Add a narrow one-to-many batching method to `CategorySuggestionService` and route `_similar_candidates(...)` through it.

This means:

- `similarity_score(left, right)` stays as the single-pair utility
- a new `similarity_scores(source, candidates)` method handles one-to-many batched scoring
- `_similar_candidates(...)` becomes a two-pass flow: filter first, score survivors second
- every `model.encode(...)` call in `CategorySuggestionService` sets `show_progress_bar=False`

No broader service-wide bulk API is introduced in this phase.

## Scope

### In scope

- adding a one-to-many batched similarity method to `CategorySuggestionService`
- switching `_similar_candidates(...)` to use a two-pass filter-then-score flow
- preserving the existing threshold, sorting, and preview limit behavior
- preserving the existing business filters in `_similar_candidates(...)`
- updating preview/apply-batch tests to patch the new scoring seam
- adding one focused service-level unit test for the new batching method
- silencing tqdm progress output on all `model.encode(...)` calls in `CategorySuggestionService`

### Out of scope

- batching Qdrant indexing during import approval
- refactoring `add_transaction(...)` or `sync_transaction(...)` into bulk write APIs
- changing category suggestion ranking behavior
- changing similarity thresholds, bank rules, or conflict-family heuristics
- benchmarking or tuning import-time approval performance in this phase

## Approaches Considered

### Approach A: Only suppress progress bars

Pros:

- smallest possible diff
- removes visible log noise immediately

Cons:

- leaves redundant preview-path embedding work intact
- does not improve the interactive request path

### Approach B: Introduce a broad bulk-embedding API for the whole service

Pros:

- could support future batching in import-time indexing paths
- centralizes more embedding behavior

Cons:

- adds new API surface without a current demonstrated need outside the preview path
- would encourage refactoring unrelated flows in the same change
- does not fit the current evidence, which is specific to preview/apply-batch

### Approach C: Add a narrow one-to-many similarity method and use it only in the preview/apply-batch path

Pros:

- directly targets the observed problem
- keeps the service boundary clean
- improves both preview and batch-apply because they share `_similar_candidates(...)`
- keeps the change small and easy to test

Cons:

- does not address latent batching opportunities in unrelated import-time flows

### Recommendation

Use Approach C, and include service-wide `show_progress_bar=False` updates in the same change.

The batching change should stay narrow. The logging-flag sweep should be included because it is a mechanical, zero-risk cleanup in the same file.

## Architecture

The current `_similar_candidates(...)` flow interleaves filtering and scoring in one loop:

`query candidates -> apply business filters -> score each candidate immediately -> threshold -> sort -> limit`

The target flow becomes:

`query candidates -> apply business filters -> collect survivors -> batch score survivors -> threshold -> sort -> limit`

The architectural boundary stays:

- `ClassificationSessionService` owns candidate eligibility and result selection
- `CategorySuggestionService` owns preprocessing, embedding, and cosine similarity math

The session service should not know about numpy arrays, batching details, or sentence-transformer configuration.

## Service Design

### CategorySuggestionService

Keep:

- `similarity_score(source_description, candidate_description) -> float`

Add:

- `similarity_scores(source_description, candidate_descriptions) -> list[float]`

`similarity_scores(...)` should:

1. return `[]` when no candidate descriptions are supplied
2. preprocess the source description once
3. preprocess candidate descriptions in input order
4. call `self.model.encode([source_text] + candidate_texts, show_progress_bar=False)` once
5. compute cosine similarity for each candidate vector against the source vector
6. return scores in the same order as the input candidate descriptions
7. normalize `NaN` and zero-norm cases to `0.0`

All existing single-item `model.encode(...)` calls in this file should also set `show_progress_bar=False`.

### ClassificationSessionService

`_similar_candidates(...)` should intentionally become a two-pass method:

1. filter pass
   - iterate the queried transactions
   - apply `_compatible_candidate_family(...)`
   - apply `shares_source_bank(...)`
   - apply `has_conflicting_family(...)`
   - collect surviving transactions in list order
2. score pass
   - build a descriptions list from those surviving transactions in the same order
   - call `category_suggestion_service.similarity_scores(...)` once
   - zip the returned scores back onto the surviving transactions by position
3. result selection
   - apply `SIMILARITY_THRESHOLD`
   - sort by descending score and then transaction id
   - return the first `SIMILARITY_PREVIEW_LIMIT` matches

The position-based pairing is safe because both the survivor list and descriptions list are built from the same ordered source, and the batched scoring method returns scores in input order.

## Call Sites

After this design lands:

- `preview_similar` benefits through `_similar_candidates(...)`
- `apply_batch` benefits through `_similar_candidates(...)`
- `similarity_score(...)` remains available for direct single-pair use and tests
- `suggest_category(...)`, `add_transaction(...)`, and `train_on_existing_transactions(...)` remain single-item or looped flows, but they no longer emit progress bars

This phase intentionally does not batch:

- accepted-transaction indexing after commit
- import-approval index synchronization
- category suggestion lookups across multiple draft transactions

## Testing Design

### API-level behavior tests

Existing tests in:

- [test_classification_api.py](/Users/aaat/myfinance/backend/tests/test_classification_api.py)
- [test_upload_trust_order.py](/Users/aaat/myfinance/backend/tests/test_upload_trust_order.py)

should keep proving preview and batch-apply behavior.

Their monkeypatch seam changes from:

- `similarity_score`

to:

- `similarity_scores`

That migration is mechanical because those tests already define a description-to-score map and can return scores in candidate-list order.

### Service-level unit test

Add a new test file:

- `tests/services/test_category_suggestion_service.py`

This test should verify `similarity_scores(...)` directly with a deterministic fake model.

Requirements:

1. do not use the real transformer model
2. monkeypatch `service.model` with an object whose `encode(...)` method returns predictable vectors
3. verify output order matches input order
4. verify the method handles one-to-many scoring correctly
5. verify `show_progress_bar=False` is passed into the fake `encode(...)` call

The unit test should validate the batching contract and score plumbing, while API-level tests keep validating business behavior.

## Verification

Success for this phase means:

1. preview/apply-batch behavior remains unchanged from the caller's point of view
2. the preview path no longer performs repeated single-item encode calls per candidate
3. sentence-transformer progress bars no longer appear in backend logs for any `CategorySuggestionService` encode call

Focused verification should include:

- the new service-level unit test
- the updated preview/apply-batch API tests
- a quick local run that confirms no `Batches: 1/1` lines are emitted from these service calls

## Risks And Trade-offs

### Risk: silent test seam drift

If preview/apply-batch tests continue patching `similarity_score`, they will no longer control scoring behavior after the new method is introduced.

Mitigation:

- update all affected monkeypatch sites to patch `similarity_scores`

### Risk: ordering mismatch between survivors and scores

If candidate descriptions are reordered independently from the survivor list, scores could attach to the wrong transaction.

Mitigation:

- build the descriptions list directly from the survivor list and zip results back in order

### Trade-off: unrelated batching opportunities remain

Import-time indexing and startup training still perform one encode per transaction.

This is accepted in this phase because those flows are not the currently observed interactive hot path, and batching them would require a separate design around Qdrant writes and import-time workflow boundaries.
