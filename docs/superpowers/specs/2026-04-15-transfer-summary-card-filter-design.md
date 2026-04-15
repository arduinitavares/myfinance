# Transfer Summary Card Filter Design

## Goal

Make the `Transfers & Settlements` dashboard card useful even when the current month has no transfer activity by giving that card its own local period selector.

This filter applies only to the transfer summary card. It does not change the rest of the analytics page.

## Problem

The current transfer summary card always calls the backend without explicit dates. The backend then defaults the range to the first day of the latest transaction month through the latest transaction date.

That behavior is technically correct, but it is often operationally unhelpful:

- the card can appear empty even when the system has many transfer rows
- the user cannot inspect last month, last 3 months, or another specific month
- the card gives no control surface to explain or change the shown range

## Scope

### In scope

- add a card-local period selector to `Transfers & Settlements`
- support the preset options:
  - `This month`
  - `Last month`
  - `Last 3 months`
  - `Year to date`
  - `Specific month`
- show a month picker input when `Specific month` is selected
- send explicit `start_date` and `end_date` to the existing transfer-summary endpoint
- keep the rest of the analytics page unchanged

### Out of scope

- adding a page-wide analytics filter
- changing the other cards to use the same period selector
- creating a new backend endpoint
- changing transfer-summary aggregation semantics

## User Experience

The `Transfers & Settlements` card keeps its current table and empty state, but gains a compact filter control in the top-right of the card header.

The left side of the header continues to show:

- title: `Transfers & Settlements`
- subtitle: the actual date range currently shown

The right side of the header shows:

- a preset dropdown
- a month picker input only when `Specific month` is active
- a small subtype count label beneath the controls in the same right-side cluster

The card must remain layout-stable when switching presets. The header should not jump vertically or push surrounding content around in distracting ways.

## Visual Direction

The control should feel native to the dashboard card instead of looking like a bolt-on filter bar.

Design principles:

- compact, utility-first header controls
- no extra card-in-card treatment
- restrained spacing and alignment
- obvious active range through the subtitle, not through decorative chrome

## Preset Behavior

The transfer summary card owns its own local filter state.

The default selected preset is `This month`.

Open-ended presets are anchored to the dataset's latest transaction date, not the browser's current date.

The component establishes this anchor from the first successful `GET /statistics/transfers/summary` response:

- on initial mount, fetch with no explicit dates
- read `end_date` from the backend response
- store that `end_date` as the card's local anchor date

All preset ranges are then computed relative to that anchor date.

### `This month`

- `start_date`: first day of the anchor date's month
- `end_date`: anchor date

This keeps the card aligned with the freshest imported data instead of the browser calendar.

### `Last month`

- full previous calendar month relative to the anchor date's month

Example:

- if anchor date is `2026-04-10`
- range becomes `2026-03-01` through `2026-03-31`

### `Last 3 months`

- `start_date`: first day of the month two months before the anchor date's month
- `end_date`: anchor date

Example:

- if anchor date is `2026-04-10`
- range becomes `2026-02-01` through `2026-04-10`

### `Year to date`

- `start_date`: January 1 of the anchor date's year
- `end_date`: anchor date

### `Specific month`

- show a month picker input in `YYYY-MM` style
- the chosen month maps to the full calendar month

Example:

- selected month `2026-03`
- range becomes `2026-03-01` through `2026-03-31`

## Data Flow

### Frontend

`TransferSummary.tsx` manages:

- anchor date derived from the backend's first response
- selected preset
- selected month when `Specific month` is active
- derived `start_date`
- derived `end_date`

On first mount, the component performs its current default fetch with no explicit dates. That response provides the anchor date through `response.end_date`.

Until that first successful response establishes the anchor date, the existing loading state remains active and the filter controls stay disabled or hidden, so preset changes cannot run against a null anchor.

After the anchor date is known:

- preset changes compute explicit `start_date` and `end_date` from the anchor date
- `Specific month` computes explicit month start and month end dates
- every non-default filtered request uses explicit date params

### Backend

Reuse the existing endpoint:

- `GET /statistics/transfers/summary`

No new API shape is required. The frontend simply stops relying on the endpoint's default date fallback behavior for this card.

## Empty State Behavior

If the selected range has no transfer rows:

- keep the existing empty state message
- keep showing the chosen range in the subtitle

This ensures the card stays truthful and understandable:

- empty because there is no data in that selected period
- not empty because the card is broken or misconfigured

## Error Handling

If the transfer summary request fails:

- preserve the existing card-level error state
- do not affect any other analytics widgets

If `Specific month` is selected but the month input is empty or invalid:

- do not issue a malformed request
- keep the component in a valid local state before fetching

## Implementation Notes

### Frontend changes

- update `frontend/src/components/dashboard/TransferSummary.tsx`
- add local preset state
- add month picker rendering for `Specific month`
- compute explicit `start_date` and `end_date`
- call `statisticService.getTransferSummary()` with those params

### Backend changes

- no behavioral backend change is required
- the frontend reuses the existing `start_date` and `end_date` query parameters already supported by `GET /statistics/transfers/summary`

## Testing

Add or update tests to cover:

- default preset rendering
- initial mount deriving the anchor date from the backend response
- switching from `This month` to `Last month`
- switching to `Last 3 months`
- switching to `Year to date`
- selecting `Specific month` and sending the expected range
- empty-state rendering for a valid range with no transfer rows
- stable subtitle updates that match the selected range

Existing tests that assert `getTransferSummary()` is called exactly once on mount should be updated to assert the expected request arguments after filter changes.

## Acceptance Criteria

The change is complete when all of the following are true:

1. The `Transfers & Settlements` card has a local preset selector.
2. The rest of the analytics page is unaffected by that selector.
3. `Specific month` reveals a month picker input.
4. The card sends explicit date ranges to the existing backend endpoint.
5. The subtitle always reflects the actual range in use.
6. Empty states remain accurate and understandable.
7. The card header remains visually stable while switching filters.
