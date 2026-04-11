# AI Classification Assistant Design

Date: 2026-04-11
Status: Draft for review
Scope: AI-assisted transaction classification with human review, optional recurrence tagging, and safe batch application to similar uncategorized transactions

## Goals

- Help the user classify uncategorized transactions with a conversational AI review loop.
- Keep the human in control: AI proposes, the user approves.
- Support retries with structured feedback and optional follow-up questions.
- Allow the assistant to suggest transaction type, category, and recurrence metadata.
- Allow safe `Apply to similar` only for uncategorized matching transactions.
- Preserve provenance for every classification decision.
- Reuse the existing lightweight suggester instead of replacing it.
- Keep providers configurable and CI-safe.

## Non-Goals

- No reminder or due-date popups in this feature.
- No dedicated review queue page in v1.
- No fuzzy recurrence matching in v1.
- No silent AI mutation of categorized transactions.
- No live provider calls in default CI.

## Current Codebase Context

The current categorization flow has one lightweight statistical suggester:

- [category_suggestion_service.py](/Users/aaat/myfinance/backend/app/services/category_suggestion_service.py)
  - sentence-transformer embeddings
  - in-memory Qdrant collections
  - ranked suggestions only
  - no conversation state
  - no explanation or retry loop
- [transactions.py](/Users/aaat/myfinance/backend/app/routers/transactions.py)
  - auto-assigns a category during CSV upload when the suggester confidence is above threshold
  - updates the suggester when the user manually changes a category

This feature adds a second, higher-trust assistant flow. The embedding suggester remains as a lightweight background system and fallback.

## User Experience

### Entry point

V1 starts only from the transactions table:

- add an `Ask AI` action for uncategorized transactions in [TransactionList.tsx](/Users/aaat/myfinance/frontend/src/components/TransactionList.tsx)
- no dedicated inbox page yet
- no assistant entry point for already categorized rows in v1

### Modal flow

Opening `Ask AI` launches a modal for the selected transaction.

The modal shows:

- transaction details
- proposed transaction type
- proposed category
- confidence
- short rationale
- top alternatives
- optional follow-up question
- recurrence suggestion
  - `is_recurrent`
  - `frequency`
  - `reason`

The user can:

- accept the proposal
- give structured feedback
- add an optional note
- retry the assistant
- save
- save and move to the next uncategorized transaction in the current table view

### Feedback input

V1 feedback is structured-first:

- quick tags:
  - `wrong_category`
  - `wrong_type`
  - `close`
  - `missing_context`
  - `explain_reasoning`
  - `accept`
- optional free-text note

The modal may also expose helper chips for common user intent such as:

- `internal transfer`
- `interest/fees`
- `salary`
- `my own account`

These map to structured feedback and optional note content. The backend receives normalized feedback turns, not raw UI chip labels.

### Save semantics

- Category-only proposals can be accepted in the normal save flow.
- If the assistant proposes a transaction type change, the modal must show an explicit confirmation step before saving.
- `Save & Next` means the next uncategorized transaction in the current filtered and sorted transactions table.
- If there is no next uncategorized transaction in the current view, the modal shows a completion state with a close action.

### Apply to similar

After the user accepts a proposal, the modal may show `Apply to similar`.

Rules:

- preview is mandatory
- only uncategorized transactions are eligible
- the preview shows the matched rows before anything is applied
- the user can uncheck rows before confirming
- `Apply all` applies the accepted result to the currently eligible preview matches

This is an explicit user-approved batch action, not background automation.

## Modal States

The frontend modal should use explicit states:

- `idle`
- `generating_proposal`
- `waiting_for_feedback`
- `retrying_with_feedback`
- `confirm_type_change`
- `preview_similar`
- `saving`
- `saved_next`
- `complete_no_more_uncategorized`
- `provider_unavailable_degraded`
- `error`

`provider_unavailable_degraded` is for known degraded behavior where embedding-based suggestions can still be shown without rationale.

`error` is for unexpected failures such as:

- network interruption
- backend 500 during accept
- expired session during feedback or retry

The `error` state must offer:

- clear error message
- retry
- cancel and close

The transaction must remain unchanged on error.

## Assistant Output Contract

The backend returns a proposal, not a mutation.

### `ClassificationProposal`

- `transaction_type`
- `category`
- `confidence`
- `rationale`
- `alternative_categories`
  - `category`
  - `confidence`
  - `rationale`
- `follow_up_question` nullable
- `recurrence_suggestion`
  - `is_recurrent`
  - `frequency` (`weekly | monthly | yearly | unknown`)
  - `reason`

The assistant exposes a short rationale suitable for the user. It must not expose raw chain-of-thought.

If the provider is unavailable and the system falls back to the embedding suggester, the UI may show ranked suggestions but must not invent rationale or follow-up questions.

## Backend-Owned Session Model

The assistant conversation is backend-owned and auditable.

### `classification_sessions`

- `id`
- `transaction_id`
- `status` (`open | accepted | cancelled | expired`)
- `provider_name`
- `model_name`
- `created_at`
- `updated_at`
- `final_transaction_type`
- `final_category`
- `final_recurrence_frequency`

Rules:

- at most one `open` session per transaction
- if an open session already exists for the transaction, resume it
- if the open session is older than the configured timeout, mark it `expired` and create a new session

### `classification_turns`

- `id`
- `session_id`
- `turn_index`
- `proposal_type`
- `proposal_category`
- `proposal_confidence`
- `proposal_rationale`
- `proposal_alternatives_json`
- `proposal_follow_up_question`
- `proposal_recurrence_json`
- `feedback_tag`
- `feedback_note`
- `token_count_prompt` nullable
- `token_count_completion` nullable
- `created_at`

This table stores each assistant round trip and the feedback that led to the next proposal.

### `recurrence_patterns`

- `id`
- `source_session_id`
- `seed_transaction_id`
- `normalized_description_key`
- `source_bank` nullable
- `currency`
- `transaction_type`
- `category`
- `frequency`
- `active`
- `created_at`

This is recurrence metadata only. It does not schedule reminders in v1.

### Transaction provenance

The `transactions` table gains:

- `classification_source` nullable
- `recurrence_pattern_id` nullable

`classification_source` allowed values:

- `manual`
- `assistant`
- `assistant_batch`
- `upload_suggester`
- `recurrence_pattern`

Existing rows remain `NULL`, which means legacy provenance unknown.

## Provider Model

The assistant provider must be provider-agnostic from day one.

### `ClassifierProvider`

Minimal behavior:

- `classify(transaction, allowed_types, allowed_categories, conversation_history) -> ClassificationProposal`
- `describe() -> ProviderDescription`

Rules:

- allowed categories are provided by the backend explicitly
- the provider does not infer the category enum surface on its own
- conversation history is passed as structured turns, not provider-specific raw chat messages
- prompt and schema live in provider code, not in config

### `ProviderDescription`

At minimum:

- `provider_name`
- `model_name`
- `schema_version`
- `prompt_fingerprint`
- optional `cost_tier`

### Test provider

Ship a `StubClassifierProvider` for:

- CI
- local development without API keys
- deterministic API and integration tests

Live provider tests must not run in the default test suite.

## Matching and Normalization

### Shared text normalization module

Create a shared module:

- [text_normalization.py](/Users/aaat/myfinance/backend/app/utils/text_normalization.py)

It should own:

- shared regex pattern constants for dates, card numbers, IBANs, BICs, and references
- `normalize_for_matching(description)`
- future `normalize_for_dedup(description)`

`CategorySuggestionService` should import the shared pattern constants instead of keeping its own private copies.

### `normalize_for_matching(description)`

For v1 this function must:

- lowercase
- strip common dates
- strip card numbers
- strip IBANs and BICs
- strip transaction references
- collapse whitespace
- trim
- preserve word order
- avoid merchant extraction or text reordering

It must not remove amounts as a matching rule. Amount and currency stay separate match dimensions.

### Known v1 limitation

Recurrence matching is exact on the normalized key. If a provider embeds changing amounts directly inside the description text, variable-amount recurring transactions may not match in v1. This limitation is acceptable for the first version.

## Trust Order

The classification trust order is:

1. recurrence pattern exact match
2. existing embedding suggester high-confidence match
3. leave uncategorized

This applies especially to the upload flow.

## Upload Flow Change

The existing CSV upload behavior changes from:

1. embedding suggester auto-assign if confidence is above threshold

to:

1. recurrence-pattern exact match
2. embedding suggester auto-assign if confidence is above threshold
3. leave uncategorized

The recurrence pattern wins if both it and the embedding suggester could apply.

This requires explicit test coverage.

## Similar-Match Rules

`Apply to similar` must not call the LLM for each candidate.

Candidate discovery uses the existing embedding suggester plus hard filters:

- uncategorized only
- same currency
- same sign / compatible transaction type family
- capped preview size

Recurrence patterns use exact normalized-key matching. `Apply to similar` may use embeddings for discovery because it remains human-reviewed before commit.

At batch commit time, the backend re-queries eligible rows and skips anything already categorized. The response should report what was skipped.

## Manual Override and Pattern Conflict

Manual always wins.

If a user manually changes a transaction in a way that contradicts an active recurrence pattern:

- save the manual classification
- set `classification_source = manual`
- keep the recurrence pattern active
- log the contradiction

V1 does not auto-disable patterns.

## Shared Commit Helper

All category mutations should use a shared helper such as:

- `commit_category_change(db, transaction, transaction_type, category, classification_source, recurrence_pattern_id=None, session_id=None)`

The helper is the single entry point for:

- manual category edits
- assistant accept
- assistant batch apply
- upload suggester auto-assign
- recurrence-pattern auto-assign

The helper must:

1. set transaction type and category fields
2. set `classification_source`
3. attach `recurrence_pattern_id` if applicable
4. commit and refresh
5. update statistics
6. feed the learner index

This avoids divergent post-commit behavior across call sites.

## API Shape

Use backend endpoints consistent with the current router style:

- `POST /classification/sessions`
  - create or resume a session for a transaction
- `POST /classification/sessions/{id}/propose`
  - get an initial or retried proposal
- `POST /classification/sessions/{id}/feedback`
  - append structured feedback for the next proposal
- `POST /classification/sessions/{id}/similar-preview`
  - preview eligible similar uncategorized rows
- `POST /classification/sessions/{id}/accept`
  - commit the accepted proposal to the current transaction
- `POST /classification/sessions/{id}/apply-batch`
  - apply the accepted proposal to checked preview rows

`Save & Next` stays a frontend flow:

1. accept current session
2. locate next uncategorized transaction from the current table view
3. create a new session for that transaction

No special backend `next` endpoint is needed in v1.

## Error Handling and Fallback

If the classifier provider is unavailable:

- show degraded fallback state
- optionally show embedding-based suggestions
- clearly label them as fallback suggestions
- do not display rationale
- do not mutate the transaction automatically

If an unexpected error occurs:

- enter `error` state
- show retry and cancel options
- preserve transaction state unchanged

## Testing Strategy

### Backend unit tests

- `normalize_for_matching()`
- trust-order selection
- session open/resume/expire logic
- recurrence exact-match resolution
- manual conflict logging

### Backend API tests

- create session
- propose and retry after feedback
- accept proposal
- require explicit type-change confirmation
- similar-preview returns only uncategorized rows
- apply-batch skips rows categorized in the meantime

### Frontend tests

- modal renders proposal, rationale, alternatives, follow-up question
- structured feedback chips and note
- retry loop
- type-change confirmation
- degraded fallback without rationale
- explicit error state
- save and `Save & Next`
- terminal `no more uncategorized` state

### End-to-end integration scenario

The headline integration test should cover the full lifecycle:

1. upload a transaction with no recurrence pattern and no strong suggester match
2. leave it uncategorized
3. classify it through the assistant
4. confirm recurrence
5. verify assistant provenance and recurrence pattern creation
6. upload a later matching transaction
7. verify recurrence pattern auto-classifies it before the embedding suggester is consulted
8. manually override the later transaction
9. verify manual provenance is stored and the recurrence pattern remains active

### CI rules

- CI uses `StubClassifierProvider`
- no live provider calls in default `pytest` or frontend test runs
- live-provider tests, if added later, must be explicitly marked and excluded from default CI

## Migration Strategy

This project currently uses hand-rolled migrations.

For this feature:

- add a migration script to introduce `classification_source` and `recurrence_pattern_id` on `transactions`
- add new tables for `classification_sessions`, `classification_turns`, and `recurrence_patterns`
- register the migration in the existing migration runner

Existing rows remain with `classification_source = NULL`.

## Rollout Scope

V1 ships only:

- from the transactions table
- for uncategorized transactions
- with one modal assistant flow
- with optional recurrence tagging
- with previewed `Apply to similar`

V1 does not include:

- reminders
- due-date popups
- a dedicated AI queue page
- fuzzy recurrence matching

## Future Follow-Ups

Natural next steps after this feature:

- recurrence reminder system built on stored patterns
- dedicated uncategorized review queue
- pattern management UI
- smarter conflict handling when patterns are repeatedly overridden
- provider-specific cost dashboards
