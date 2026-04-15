# Transfer Summary Card Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a card-local period filter to `Transfers & Settlements` so the user can inspect transfer activity for anchor-based presets and a specific month without affecting the rest of the analytics page.

**Architecture:** Keep this as a frontend-only slice. Reuse the existing `GET /statistics/transfers/summary` endpoint, derive the anchor date from the first no-arg response, move preset/date math into a tiny pure helper, and keep the card shell mounted during filtered refetches so the dashboard layout stays stable.

**Tech Stack:** React 18, TypeScript, date-fns, Axios, React Testing Library, Jest, Tailwind CSS.

---

## Scope Check

This plan intentionally covers only the transfer summary card:

- local preset selector for `This month`, `Last month`, `Last 3 months`, `Year to date`, and `Specific month`
- anchor-date range math derived from the first backend response
- explicit `start_date` / `end_date` requests for filtered fetches
- stable card rendering while filters change
- component and helper test coverage

This plan does **not** change:

- backend statistics behavior
- any analytics widgets outside `Transfers & Settlements`
- page-wide date filters
- transfer aggregation semantics

## File Map

### Frontend create

- `frontend/src/components/dashboard/transferSummaryRange.ts` — pure preset/range helpers for anchor-based period calculation.
- `frontend/src/components/dashboard/transferSummaryRange.test.ts` — focused unit tests for the helper’s date math and invalid-input guards.

### Frontend modify

- `frontend/src/components/dashboard/TransferSummary.tsx` — add local filter state, filter controls, anchor bootstrapping, explicit filtered fetches, and stable in-card loading/error behavior.
- `frontend/src/components/dashboard/TransferSummary.test.tsx` — update coverage for initial anchor bootstrapping, preset changes, specific month input, and stable rendering during refetch.

### Existing files to inspect but not change

- `frontend/src/services/statisticService.ts` — already supports `getTransferSummary(start_date?, end_date?)`.
- `frontend/src/utils/date.ts` — existing `dd/MM/yyyy` display formatting for the subtitle.

## Verification Commands

- Helper unit tests:
  - `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/transferSummaryRange.test.ts`
- Transfer summary component tests:
  - `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx`
- Final focused frontend regression pass:
  - `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/transferSummaryRange.test.ts src/components/dashboard/TransferSummary.test.tsx`

## Task 1: Extract Anchor-Based Range Math into a Pure Helper

**Files:**
- Create: `frontend/src/components/dashboard/transferSummaryRange.ts`
- Create: `frontend/src/components/dashboard/transferSummaryRange.test.ts`

- [ ] **Step 1: Write the failing helper tests**

```ts
import {
  DEFAULT_TRANSFER_SUMMARY_PRESET,
  buildTransferSummaryRange,
  buildSpecificMonthRange,
} from './transferSummaryRange';

describe('transferSummaryRange', () => {
  test('uses the backend anchor date for open-ended presets', () => {
    expect(DEFAULT_TRANSFER_SUMMARY_PRESET).toBe('this_month');

    expect(buildTransferSummaryRange('this_month', '2026-04-10')).toEqual({
      startDate: '2026-04-01',
      endDate: '2026-04-10',
    });

    expect(buildTransferSummaryRange('last_month', '2026-04-10')).toEqual({
      startDate: '2026-03-01',
      endDate: '2026-03-31',
    });

    expect(buildTransferSummaryRange('last_3_months', '2026-04-10')).toEqual({
      startDate: '2026-02-01',
      endDate: '2026-04-10',
    });

    expect(buildTransferSummaryRange('year_to_date', '2026-04-10')).toEqual({
      startDate: '2026-01-01',
      endDate: '2026-04-10',
    });
  });

  test('builds a full calendar month for specific month selection', () => {
    expect(buildSpecificMonthRange('2026-02')).toEqual({
      startDate: '2026-02-01',
      endDate: '2026-02-28',
    });
  });

  test('returns null for missing or invalid specific month input', () => {
    expect(buildSpecificMonthRange('')).toBeNull();
    expect(buildSpecificMonthRange('2026-2')).toBeNull();
    expect(buildSpecificMonthRange('wat')).toBeNull();
  });
});
```

- [ ] **Step 2: Run the helper tests to confirm they fail because the helper does not exist yet**

Run: `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/transferSummaryRange.test.ts`

Expected: FAIL with `Cannot find module './transferSummaryRange'` or missing export errors.

- [ ] **Step 3: Write the minimal range helper**

```ts
import { endOfMonth, format, parse, parseISO, startOfMonth, subMonths } from 'date-fns';

export type TransferSummaryPreset =
  | 'this_month'
  | 'last_month'
  | 'last_3_months'
  | 'year_to_date'
  | 'specific_month';

export interface TransferSummaryRange {
  startDate: string;
  endDate: string;
}

export const DEFAULT_TRANSFER_SUMMARY_PRESET: TransferSummaryPreset = 'this_month';

const toIsoDate = (value: Date) => format(value, 'yyyy-MM-dd');

export const buildTransferSummaryRange = (
  preset: Exclude<TransferSummaryPreset, 'specific_month'>,
  anchorDate: string
): TransferSummaryRange => {
  const anchor = parseISO(anchorDate);

  if (preset === 'this_month') {
    return {
      startDate: toIsoDate(startOfMonth(anchor)),
      endDate: toIsoDate(anchor),
    };
  }

  if (preset === 'last_month') {
    const previousMonth = subMonths(anchor, 1);
    return {
      startDate: toIsoDate(startOfMonth(previousMonth)),
      endDate: toIsoDate(endOfMonth(previousMonth)),
    };
  }

  if (preset === 'last_3_months') {
    return {
      startDate: toIsoDate(startOfMonth(subMonths(anchor, 2))),
      endDate: toIsoDate(anchor),
    };
  }

  return {
    startDate: `${anchor.getFullYear()}-01-01`,
    endDate: toIsoDate(anchor),
  };
};

export const buildSpecificMonthRange = (monthValue: string): TransferSummaryRange | null => {
  if (!/^\d{4}-\d{2}$/.test(monthValue)) {
    return null;
  }

  const monthDate = parse(`${monthValue}-01`, 'yyyy-MM-dd', new Date());

  return {
    startDate: toIsoDate(startOfMonth(monthDate)),
    endDate: toIsoDate(endOfMonth(monthDate)),
  };
};
```

- [ ] **Step 4: Re-run the helper tests and confirm they pass**

Run: `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/transferSummaryRange.test.ts`

Expected: PASS with 3 passing tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/transferSummaryRange.ts frontend/src/components/dashboard/transferSummaryRange.test.ts
git commit -m "feat: add transfer summary range helpers"
```

## Task 2: Add Preset Controls and Explicit Filtered Requests to the Card

**Files:**
- Modify: `frontend/src/components/dashboard/TransferSummary.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.test.tsx`
- Inspect: `frontend/src/services/statisticService.ts`

- [ ] **Step 1: Write the failing component tests for anchor bootstrapping and filter requests**

```tsx
test('boots with backend defaults, then requests last month with explicit dates', async () => {
  mockedGetTransferSummary
    .mockResolvedValueOnce({
      start_date: '2026-04-01',
      end_date: '2026-04-10',
      items: [],
    })
    .mockResolvedValueOnce({
      start_date: '2026-03-01',
      end_date: '2026-03-31',
      items: [],
    });

  render(<TransferSummary />);

  const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
  expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(1);
  expect(presetSelect).toHaveValue('this_month');

  fireEvent.change(presetSelect, { target: { value: 'last_month' } });

  await waitFor(() => {
    expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(2, '2026-03-01', '2026-03-31');
  });
});

test('shows the month picker for specific month and waits for a valid month before fetching', async () => {
  mockedGetTransferSummary
    .mockResolvedValueOnce({
      start_date: '2026-04-01',
      end_date: '2026-04-10',
      items: [],
    })
    .mockResolvedValueOnce({
      start_date: '2026-02-01',
      end_date: '2026-02-28',
      items: [],
    });

  render(<TransferSummary />);

  const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
  fireEvent.change(presetSelect, { target: { value: 'specific_month' } });

  expect(screen.getByLabelText(/transfer summary month/i)).toBeInTheDocument();
  expect(mockedGetTransferSummary).toHaveBeenCalledTimes(1);

  fireEvent.change(screen.getByLabelText(/transfer summary month/i), {
    target: { value: '2026-02' },
  });

  await waitFor(() => {
    expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(2, '2026-02-01', '2026-02-28');
  });
});
```

- [ ] **Step 2: Run the component tests and confirm they fail because the controls and request flow do not exist yet**

Run: `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx`

Expected: FAIL with missing labeled controls and wrong `getTransferSummary()` call assertions.

- [ ] **Step 3: Implement the card-local preset state and explicit filtered fetches**

```tsx
import React, { useEffect, useState } from 'react';
import { statisticService, TransferSummaryResponse } from '../../services/statisticService';
import { Loading } from '../common/Loading';
import { formatDisplayDate } from '../../utils/date';
import {
  buildSpecificMonthRange,
  buildTransferSummaryRange,
  DEFAULT_TRANSFER_SUMMARY_PRESET,
  TransferSummaryPreset,
} from './transferSummaryRange';

const PRESET_OPTIONS: Array<{ value: TransferSummaryPreset; label: string }> = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_3_months', label: 'Last 3 months' },
  { value: 'year_to_date', label: 'Year to date' },
  { value: 'specific_month', label: 'Specific month' },
];

export const TransferSummary: React.FC = () => {
  const [summary, setSummary] = useState<TransferSummaryResponse | null>(null);
  const [anchorDate, setAnchorDate] = useState<string | null>(null);
  const [preset, setPreset] = useState<TransferSummaryPreset>(DEFAULT_TRANSFER_SUMMARY_PRESET);
  const [specificMonth, setSpecificMonth] = useState('');
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = async (range?: { startDate: string; endDate: string }) => {
    const data = range
      ? await statisticService.getTransferSummary(range.startDate, range.endDate)
      : await statisticService.getTransferSummary();

    setSummary(data);
    setAnchorDate((current) => current ?? data.end_date);
    setError(null);
  };

  useEffect(() => {
    let isMounted = true;

    const loadInitialSummary = async () => {
      try {
        await loadSummary();
      } catch (err) {
        console.error('Error fetching transfer summary:', err);
        if (isMounted) {
          setError('Failed to load transfer summary');
          setSummary(null);
        }
      } finally {
        if (isMounted) {
          setInitialLoading(false);
        }
      }
    };

    void loadInitialSummary();

    return () => {
      isMounted = false;
    };
  }, []);

  const handlePresetChange = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    const nextPreset = event.target.value as TransferSummaryPreset;
    setPreset(nextPreset);

    if (!anchorDate || nextPreset === 'specific_month') {
      return;
    }

    await loadSummary(buildTransferSummaryRange(nextPreset, anchorDate));
  };

  const handleSpecificMonthChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextMonth = event.target.value;
    setSpecificMonth(nextMonth);

    if (preset !== 'specific_month') {
      return;
    }

    const range = buildSpecificMonthRange(nextMonth);
    if (!range) {
      return;
    }

    await loadSummary(range);
  };

  if (initialLoading) {
    return <Loading variant="progress" size="medium" />;
  }

  if (error && !summary) {
    return <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">{error}</div>;
  }

  if (!summary) {
    return null;
  }

  const items = summary.items ?? [];

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-6 shadow-md dark:border-gray-700 dark:bg-gray-800">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-medium dark:text-gray-200">Transfers & Settlements</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {`Showing ${formatDisplayDate(summary.start_date)} to ${formatDisplayDate(summary.end_date)}`}
          </p>
        </div>

        <div className="flex flex-col items-end gap-2">
          <select
            aria-label="transfer summary preset"
            className="min-w-[160px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            value={preset}
            onChange={handlePresetChange}
            disabled={!anchorDate}
          >
            {PRESET_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          {preset === 'specific_month' && (
            <input
              aria-label="transfer summary month"
              type="month"
              value={specificMonth}
              onChange={handleSpecificMonthChange}
              className="min-w-[160px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            />
          )}

          <div className="text-xs text-gray-500 dark:text-gray-400">
            {items.length} subtype{items.length === 1 ? '' : 's'}
          </div>
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Re-run the component tests and confirm the preset flow passes**

Run: `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx`

Expected: PASS for the new preset and specific-month tests, even if one stable-layout case still fails.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/TransferSummary.tsx frontend/src/components/dashboard/TransferSummary.test.tsx
git commit -m "feat: add transfer summary card filters"
```

## Task 3: Keep the Card Stable During Refetch and Show In-Card Errors

**Files:**
- Modify: `frontend/src/components/dashboard/TransferSummary.tsx`
- Modify: `frontend/src/components/dashboard/TransferSummary.test.tsx`

- [ ] **Step 1: Add failing tests for stable refetch rendering and in-card errors**

```tsx
test('keeps the card mounted while a filtered request is in flight', async () => {
  let resolveSecondRequest: ((value: TransferSummaryResponse) => void) | undefined;

  mockedGetTransferSummary
    .mockResolvedValueOnce({
      start_date: '2026-04-01',
      end_date: '2026-04-10',
      items: [],
    })
    .mockImplementationOnce(
      () =>
        new Promise<TransferSummaryResponse>((resolve) => {
          resolveSecondRequest = resolve;
        })
    );

  render(<TransferSummary />);

  fireEvent.change(await screen.findByLabelText(/transfer summary preset/i), {
    target: { value: 'last_month' },
  });

  expect(screen.getByText('Transfers & Settlements')).toBeInTheDocument();
  expect(screen.queryByText(/loading\.\.\./i)).not.toBeInTheDocument();

  resolveSecondRequest?.({
    start_date: '2026-03-01',
    end_date: '2026-03-31',
    items: [],
  });

  expect(await screen.findByText(/showing 01\/03\/2026 to 31\/03\/2026/i)).toBeInTheDocument();
});

test('shows the transfer-summary error inside the existing card shell after a filtered request fails', async () => {
  mockedGetTransferSummary
    .mockResolvedValueOnce({
      start_date: '2026-04-01',
      end_date: '2026-04-10',
      items: [],
    })
    .mockRejectedValueOnce(new Error('network failed'));

  render(<TransferSummary />);

  fireEvent.change(await screen.findByLabelText(/transfer summary preset/i), {
    target: { value: 'last_month' },
  });

  expect(await screen.findByText(/failed to load transfer summary/i)).toBeInTheDocument();
  expect(screen.getByText('Transfers & Settlements')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the component tests again and confirm the new stability/error tests fail**

Run: `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/TransferSummary.test.tsx`

Expected: FAIL because the component still swaps to the top-level loading indicator and does not keep an in-card error body after the first successful load.

- [ ] **Step 3: Split initial loading from filtered refreshing and keep the card shell mounted**

```tsx
const [initialLoading, setInitialLoading] = useState(true);
const [refreshing, setRefreshing] = useState(false);

const loadSummary = async (
  range?: { startDate: string; endDate: string },
  options: { preserveCardShell?: boolean } = {}
) => {
  if (options.preserveCardShell) {
    setRefreshing(true);
  }

  try {
    const data = range
      ? await statisticService.getTransferSummary(range.startDate, range.endDate)
      : await statisticService.getTransferSummary();

    setSummary(data);
    setAnchorDate((current) => current ?? data.end_date);
    setError(null);
  } catch (err) {
    console.error('Error fetching transfer summary:', err);
    setError('Failed to load transfer summary');
    if (!options.preserveCardShell) {
      setSummary(null);
    }
  } finally {
    setRefreshing(false);
  }
};

const handlePresetChange = async (event: React.ChangeEvent<HTMLSelectElement>) => {
  const nextPreset = event.target.value as TransferSummaryPreset;
  setPreset(nextPreset);

  if (!anchorDate || nextPreset === 'specific_month') {
    return;
  }

  await loadSummary(buildTransferSummaryRange(nextPreset, anchorDate), {
    preserveCardShell: true,
  });
};

const body = error ? (
  <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
    {error}
  </div>
) : items.length === 0 ? (
  <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/40 dark:text-gray-400">
    No transfer summary data available.
  </div>
) : (
  <div className="overflow-x-auto">{/* existing table */}</div>
);

return (
  <div
    aria-busy={refreshing}
    className="rounded-xl border border-gray-100 bg-white p-6 shadow-md dark:border-gray-700 dark:bg-gray-800"
  >
    <div className="mb-4 flex items-start justify-between gap-4">{/* existing header */}</div>
    {body}
  </div>
);
```

- [ ] **Step 4: Run the focused regression pass and confirm everything passes**

Run: `cd /Users/aaat/myfinance/frontend && CI=true npm test -- --runInBand --watch=false src/components/dashboard/transferSummaryRange.test.ts src/components/dashboard/TransferSummary.test.tsx`

Expected: PASS with helper math, explicit request, specific month, stable refetch, and in-card error coverage all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/transferSummaryRange.ts frontend/src/components/dashboard/transferSummaryRange.test.ts frontend/src/components/dashboard/TransferSummary.tsx frontend/src/components/dashboard/TransferSummary.test.tsx
git commit -m "feat: keep transfer summary filters stable during refresh"
```

## Self-Review

- Spec coverage:
  - card-local selector: Tasks 2 and 3
  - anchor date from first response: Tasks 1 and 2
  - explicit request params: Task 2
  - specific month input: Task 2
  - empty state and truthful subtitle: Tasks 2 and 3
  - stable header/card rendering while switching filters: Task 3
  - isolated card-level error behavior: Task 3
- Placeholder scan:
  - no `TODO`, `TBD`, or “handle appropriately” placeholders remain
  - every code-changing step includes concrete code
- Type consistency:
  - `TransferSummaryPreset`, `TransferSummaryRange`, `buildTransferSummaryRange`, and `buildSpecificMonthRange` are defined once in Task 1 and reused consistently later

