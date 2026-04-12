# Classification Assistant Polish Design

Date: 2026-04-11
Status: Draft for review

## Goal

Polish the transaction table and AI classification modal so the flow is clearer, safer, and more stable for everyday use.

This pass focuses on:

1. preserving table layout when the AI action state changes
2. allowing deletion of classified transactions without integrity errors
3. making the assistant's selected category obvious and editable before save
4. keeping recurrence controls layout-stable
5. making `Save & Next` behave like a natural workflow close when there is no next item
6. making `Apply All` much more conservative and transparent

## Scope

### In scope

- Transaction list action-column alignment
- Show `Ask AI` for all transactions, not only uncategorized ones
- Backend fix for deleting transactions that have classification sessions or recurrence-related records
- Modal clarity improvements around selected category and confidence wording
- Layout stability for recurrence controls
- `Save & Next` end-of-list behavior
- More conservative matching and clearer preview for batch apply

### Out of scope

- New queue view or multi-step wizard
- Full redesign of the transactions page
- Provider/prompt changes for classification quality beyond what is needed to support safer batch apply
- New recurrence management page

## UX Design

### 1. Transactions table actions

The actions column keeps a stable width on every row.

- The trash button remains in a fixed position.
- The AI button uses the same reserved slot on every row.
- When the row is already classified, the AI action still exists and stays aligned with uncategorized rows.

Behavior:

- `Ask AI` opens the assistant for any transaction.
- Classified rows can be re-reviewed with the assistant instead of being locked out.

This avoids the current shifting layout where removing the AI button changes icon alignment.

### 2. Assistant proposal card

The modal must make the chosen category unmistakable.

Proposal area shows:

- selected transaction type
- selected category
- `AI confidence` label instead of a bare percentage
- rationale text
- optional follow-up question

The selected category is also editable in a dropdown in the modal, prefilled with the assistant proposal.

Rules:

- The dropdown is the authoritative selection shown to the user.
- The rationale supports the proposed choice; it does not replace clear category display.
- If the user changes the dropdown manually before save, the saved category is the dropdown value.
- The dropdown options come from the existing frontend enums so the modal and transaction table use the same category vocabulary.
- In degraded fallback mode, the label changes from `AI confidence` to `Similarity` because the preview is embedding-based, not LLM-based.

### 3. Recurrence controls

The recurrence container keeps a stable height and structure.

- The frequency row is always reserved within the recurrence section.
- If recurrence is disabled, the row remains visually collapsed without changing surrounding layout.
- Checking the box must not cause the container to jump in size.

### 4. Save flow

`Save` keeps current behavior and closes the modal after saving.

`Save & Next` behavior:

- If there is a next transaction in the current filtered/sorted view, save and open the next one.
- If there is no next transaction, save and close the modal immediately.

The temporary completion screen is removed from this flow.

### 5. Apply All preview

Batch apply becomes conservative and category-explicit.

Preview shows:

- the category that will be applied
- each candidate description
- similarity percentage
- a clear indication that the chosen category will be copied to those candidates if the user confirms

The preview must make it obvious what category will be batch-applied.

## Matching and Safety Rules

`Apply All` should prefer false negatives over false positives.

### Conservative filter rules

A candidate can appear in the preview only if all of these hold:

1. uncategorized
2. same currency
3. same sign and same transaction family
4. similarity score above a stricter threshold than the current one
5. description does not look like a conflicting family compared with the seed

Initial stricter behavior:

- raise the threshold from `0.5` to `0.8`
- reduce the preview cap from `8` to `3`
- require the same `source_bank` when both transactions have a bank tag
- filter out obvious transfer-like descriptions when the seed appears merchant or bill-like
- filter out obvious merchant/bill-like descriptions when the seed appears transfer-like

This is intentionally heuristic and conservative in v1.

### Conflicting-family heuristics

Examples:

- `ENERGIE`, `PROXIMUS`, `RENT`, known invoice/biller phrasing should not batch with personal transfers
- `Arne P2P`, `Bancontact transfer`, own-name transfers, internal-account patterns should not batch with utilities or rent

The heuristic is only used to exclude risky candidates, never to include extra ones.

Implementation shape:

- keep the heuristic in a small, testable helper module
- use simple normalized substring checks, not regex-heavy matching
- define explicit keyword groups such as `TRANSFER_LIKE_TERMS` and `MERCHANT_OR_BILL_LIKE_TERMS`
- expose small predicates like `looks_like_transfer()` and `looks_like_bill_or_merchant()`

Known trade-off:

- this conservative filter will miss some valid batch candidates; that is acceptable in this pass

## Backend Design

### 1. Delete behavior

Deleting a transaction must not fail because classification records point to it.

Current failure:

- deleting a transaction causes SQLAlchemy to null out `classification_sessions.transaction_id`
- that column is non-nullable
- commit fails with `NOT NULL constraint failed`

Required behavior:

- deleting a transaction also deletes dependent classification sessions, turns, and seeded recurrence records tied to that transaction
- no nullable detachment path should be used for required foreign keys
- deleting a seed transaction must not leave other transactions pointing at a recurrence pattern that is about to be removed

Implementation direction:

- add delete-orphan cascade on `Transaction.classification_sessions`
- add delete-orphan cascade on `Transaction.seeded_recurrence_patterns`
- keep explicit cleanup in the delete endpoint for cross-row recurrence references

Delete sequence:

1. load the recurrence pattern ids seeded by the transaction being deleted
2. set `transactions.recurrence_pattern_id = NULL` for any transaction currently pointing at those soon-to-be-deleted patterns
3. delete those recurrence patterns
4. delete the transaction's classification sessions so their turns cascade away with them
5. delete anomaly records already tied to the transaction
6. delete the transaction itself
7. commit and refresh downstream statistics

This sequence preserves required foreign keys while still cleaning up assistant-side artifacts.

### 2. Modal save contract

Backend accept endpoint can stay structurally the same, but frontend save payload must send the dropdown-selected category rather than assuming the original AI proposal is still selected.

### 3. Batch preview

The existing preview endpoint remains, but matching logic becomes stricter.

Response shape can remain compatible, with optional additions if needed for UI clarity.

At minimum, the UI must know which category is about to be applied so the preview is understandable without reading the rationale card above it.

## Frontend Design

### Components affected

- `frontend/src/components/TransactionList.tsx`
- `frontend/src/components/transactions/ClassificationAssistantModal.tsx`
- related tests

### UI updates

- fixed action-slot layout in the table
- AI button available on all rows
- explicit selected category dropdown in modal
- `AI confidence` text label for LLM proposals
- `Similarity` text label for degraded fallback suggestions
- stable recurrence section
- remove end-of-list completion state from `Save & Next`
- clearer apply-preview header with chosen category

Dropdown behavior:

- initialize the modal dropdown from the proposal category
- populate expense categories from the existing `ExpenseCategory` enum and income categories from the existing `IncomeCategory` enum
- keep the selected value visible even if the user is focused on the rationale text

## Testing

### Backend

- deleting a classified transaction succeeds
- deleting a transaction with related classification sessions no longer raises integrity errors
- conservative batch preview excludes risky cross-family matches
- explicit regression covering the transfer-vs-utility mismatch case

### Frontend

- AI action remains aligned for both categorized and uncategorized rows
- AI button appears for categorized rows
- modal displays selected category clearly
- dropdown starts with the predicted category selected
- recurrence toggle does not change outer section size unexpectedly
- `Save & Next` closes when no next transaction exists
- apply-preview clearly shows the category being applied

## Risks

- Over-tightening batch rules may reduce useful preview candidates; this is acceptable in this pass.
- Delete cascade changes need careful regression coverage so recurrence data is not left inconsistent.
- The delete path touches both ORM cascade rules and explicit cleanup order; tests must cover both classified and recurrence-linked transactions.

## Acceptance Criteria

1. The actions column stays aligned regardless of row classification state.
2. Any transaction can be opened in the AI assistant.
3. Any transaction can be deleted without the classification-session integrity error.
4. The modal clearly shows the selected category and `AI confidence`.
5. The recurrence section remains layout-stable when toggled.
6. `Save & Next` closes when there is no next row.
7. `Apply All` is visibly category-explicit and materially more conservative.
