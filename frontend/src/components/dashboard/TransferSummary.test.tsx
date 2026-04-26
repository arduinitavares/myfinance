import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { TransferSummary } from './TransferSummary';
import {
  statisticService,
  TransferSummaryItem,
  TransferSummaryResponse,
} from '../../services/statisticService';
import { ReportingCurrencyProvider } from '../../contexts/ReportingCurrencyContext';
import type { ConversionSummary } from '../../types/statistics';

jest.mock('../../services/apiClient', () => {
  const REPORTING_CURRENCIES = ['EUR', 'USD', 'BRL'] as const;
  const DEFAULT_REPORTING_CURRENCY = 'EUR';
  const STORAGE_KEY = 'reporting_currency';

  const readStoredReportingCurrency = () => {
    const storedValue = globalThis.localStorage.getItem(STORAGE_KEY);
    return REPORTING_CURRENCIES.includes(storedValue as (typeof REPORTING_CURRENCIES)[number])
      ? storedValue
      : DEFAULT_REPORTING_CURRENCY;
  };

  return {
    REPORTING_CURRENCIES,
    DEFAULT_REPORTING_CURRENCY,
    readStoredReportingCurrency,
    setReportingCurrency: (currency: string) => {
      globalThis.localStorage.setItem(STORAGE_KEY, currency);
      return currency;
    },
    syncReportingCurrencyFromStorage: readStoredReportingCurrency,
  };
});

jest.mock('../../services/statisticService', () => ({
  statisticService: {
    getTransferSummary: jest.fn(),
  },
}));

const mockedGetTransferSummary = statisticService.getTransferSummary as jest.MockedFunction<
  typeof statisticService.getTransferSummary
>;

const buildTransferSummaryResponse = (
  overrides: Partial<TransferSummaryResponse> = {},
  items: TransferSummaryItem[] = []
): TransferSummaryResponse => ({
  start_date: '2026-03-01',
  end_date: '2026-03-31',
  reporting_currency: 'EUR',
  conversion_summary: {
    converted_transaction_count: 0,
    unavailable_transaction_count: 0,
    unavailable_currencies: [],
  } satisfies ConversionSummary,
  items,
  ...overrides,
});

const renderTransferSummary = () =>
  render(
    <ReportingCurrencyProvider>
      <TransferSummary />
    </ReportingCurrencyProvider>
  );

describe('TransferSummary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
  });

  test('shows loading state while transfer summary is being fetched', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce(
      buildTransferSummaryResponse({}, [
        {
          subtype: 'Internal Transfer',
          transaction_count: 3,
          total_outgoing: 1200,
          total_incoming: 950,
        },
      ])
    );

    renderTransferSummary();

    expect(screen.getByText(/loading\.\.\./i)).toBeInTheDocument();

    expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();
  });

  test('renders transfer summary rows', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce(
      buildTransferSummaryResponse({}, [
        {
          subtype: 'Internal Transfer',
          transaction_count: 3,
          total_outgoing: 1200,
          total_incoming: 950,
        },
        {
          subtype: 'Credit Card Settlement',
          transaction_count: 2,
          total_outgoing: 500,
          total_incoming: 0,
        },
      ])
    );

    renderTransferSummary();

    expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();
    expect(screen.getByText('Internal Transfer')).toBeInTheDocument();
    expect(screen.getByText('Credit Card Settlement')).toBeInTheDocument();
    expect(screen.getByText('€1,200')).toBeInTheDocument();
    expect(screen.getByText('€950')).toBeInTheDocument();
    expect(screen.getByText('€500')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  test('formats transfer summary rows using the response reporting currency', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce(
      buildTransferSummaryResponse(
        { reporting_currency: 'USD' },
        [
          {
            subtype: 'International Transfer',
            transaction_count: 2,
            total_outgoing: 1200,
            total_incoming: 950,
          },
        ]
      )
    );

    renderTransferSummary();

    expect(await screen.findByText('International Transfer')).toBeInTheDocument();
    expect(screen.getByText('$1,200')).toBeInTheDocument();
    expect(screen.getByText('$950')).toBeInTheDocument();
    expect(screen.queryByText('€1,200')).not.toBeInTheDocument();
  });

  test('shows a partial-data warning when some transfer currencies are unavailable', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce(
      buildTransferSummaryResponse(
        {
          reporting_currency: 'USD',
          conversion_summary: {
            converted_transaction_count: 1,
            unavailable_transaction_count: 1,
            unavailable_currencies: ['NEXO'],
          },
        },
        [
          {
            subtype: 'International Transfer',
            transaction_count: 2,
            total_outgoing: 1200,
            total_incoming: 950,
          },
        ]
      )
    );

    renderTransferSummary();

    expect(await screen.findByText(/some totals exclude unsupported currencies: nexo\./i)).toBeInTheDocument();
  });

  test('shows an empty state when no transfer rows are returned', async () => {
    mockedGetTransferSummary.mockResolvedValueOnce(buildTransferSummaryResponse());

    renderTransferSummary();

    expect(await screen.findByText(/no transfer summary data available/i)).toBeInTheDocument();
  });

  test('shows an error state when the fetch fails', async () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockedGetTransferSummary.mockRejectedValueOnce(new Error('network failed'));

    renderTransferSummary();

    expect(await screen.findByText(/failed to load transfer summary/i)).toBeInTheDocument();
    await waitFor(() => expect(mockedGetTransferSummary).toHaveBeenCalledTimes(1));

    consoleSpy.mockRestore();
  });

  test('boots with backend defaults, then requests last month with explicit dates', async () => {
    mockedGetTransferSummary
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
      }))
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-03-01',
        end_date: '2026-03-31',
      }));

    renderTransferSummary();

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    expect(presetSelect).toHaveValue('this_month');
    // The backend should be invoked with no explicit date arguments here so defaults are used.
    expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(1);

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'last_month' } });
    });

    await waitFor(() => {
      expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(2, '2026-03-01', '2026-03-31');
    });
  });

  test('shows the month picker for specific month and waits for a valid month before fetching', async () => {
    mockedGetTransferSummary
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
      }))
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-02-01',
        end_date: '2026-02-28',
      }));

    renderTransferSummary();

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'specific_month' } });
    });

    expect(screen.getByLabelText(/transfer summary month/i)).toBeInTheDocument();
    expect(mockedGetTransferSummary).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/transfer summary month/i), {
        target: { value: '2026-02' },
      });
    });

    await waitFor(() => {
      expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(2, '2026-02-01', '2026-02-28');
    });
  });

  test('re-applies the saved specific month when switching back to that preset', async () => {
    mockedGetTransferSummary
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
        items: [
          {
            subtype: 'Default summary',
            transaction_count: 1,
            total_outgoing: 100,
            total_incoming: 50,
          },
        ],
      }))
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-02-01',
        end_date: '2026-02-28',
        items: [
          {
            subtype: 'Specific month summary',
            transaction_count: 2,
            total_outgoing: 200,
            total_incoming: 100,
          },
        ],
      }))
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-03-01',
        end_date: '2026-03-31',
        items: [
          {
            subtype: 'Last month summary',
            transaction_count: 3,
            total_outgoing: 300,
            total_incoming: 150,
          },
        ],
      }))
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-02-01',
        end_date: '2026-02-28',
        items: [
          {
            subtype: 'Specific month summary',
            transaction_count: 2,
            total_outgoing: 200,
            total_incoming: 100,
          },
        ],
      }));

    renderTransferSummary();

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'specific_month' } });
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/transfer summary month/i), {
        target: { value: '2026-02' },
      });
    });

    expect(await screen.findByText('Specific month summary')).toBeInTheDocument();

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'last_month' } });
    });

    expect(await screen.findByText('Last month summary')).toBeInTheDocument();

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'specific_month' } });
    });

    await waitFor(() => {
      expect(mockedGetTransferSummary).toHaveBeenNthCalledWith(4, '2026-02-01', '2026-02-28');
    });

    expect(await screen.findByText('Specific month summary')).toBeInTheDocument();
  });

  test('keeps the card mounted while a filtered request is in flight', async () => {
    let resolveSecondRequest: ((value: Awaited<ReturnType<typeof statisticService.getTransferSummary>>) => void) | undefined;

    mockedGetTransferSummary
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
        items: [
          {
            subtype: 'Internal Transfer',
            transaction_count: 1,
            total_outgoing: 100,
            total_incoming: 50,
          },
        ],
      }))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecondRequest = resolve;
          })
      );

    renderTransferSummary();

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'last_month' } });
    });

    expect(screen.getByText('Transfers & Settlements')).toBeInTheDocument();
    expect(screen.getByText('Internal Transfer')).toBeInTheDocument();
    expect(screen.queryByText(/loading\.\.\./i)).not.toBeInTheDocument();

    await act(async () => {
      resolveSecondRequest?.(buildTransferSummaryResponse({
        start_date: '2026-03-01',
        end_date: '2026-03-31',
      }));
    });

    expect(await screen.findByText(/showing 01\/03\/2026 to 31\/03\/2026/i)).toBeInTheDocument();
  });

  test('shows the transfer-summary error inside the existing card shell after a filtered request fails', async () => {
    mockedGetTransferSummary
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
        items: [
          {
            subtype: 'Internal Transfer',
            transaction_count: 1,
            total_outgoing: 100,
            total_incoming: 50,
          },
        ],
      }))
      .mockRejectedValueOnce(new Error('network failed'));

    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);

    renderTransferSummary();

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    expect(await screen.findByText('Transfers & Settlements')).toBeInTheDocument();

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'last_month' } });
    });

    expect(await screen.findByText(/failed to load transfer summary/i)).toBeInTheDocument();
    expect(screen.getByText('Transfers & Settlements')).toBeInTheDocument();
    expect(screen.getByText(/showing 01\/04\/2026 to 10\/04\/2026/i)).toBeInTheDocument();

    consoleSpy.mockRestore();
  });

  test('keeps the newest filtered response when overlapping requests resolve out of order', async () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    let resolveLastMonth:
      | ((value: Awaited<ReturnType<typeof statisticService.getTransferSummary>>) => void)
      | undefined;
    let resolveLast3Months:
      | ((value: Awaited<ReturnType<typeof statisticService.getTransferSummary>>) => void)
      | undefined;

    mockedGetTransferSummary
      .mockResolvedValueOnce(buildTransferSummaryResponse({
        start_date: '2026-04-01',
        end_date: '2026-04-10',
        items: [
          {
            subtype: 'Initial summary',
            transaction_count: 1,
            total_outgoing: 100,
            total_incoming: 50,
          },
        ],
      }))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveLastMonth = resolve;
          })
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveLast3Months = resolve;
          })
      );

    renderTransferSummary();

    const presetSelect = await screen.findByLabelText(/transfer summary preset/i);
    expect(await screen.findByText('Initial summary')).toBeInTheDocument();

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'last_month' } });
    });

    await act(async () => {
      fireEvent.change(presetSelect, { target: { value: 'last_3_months' } });
    });

    await act(async () => {
      resolveLast3Months?.(buildTransferSummaryResponse({
        start_date: '2026-02-01',
        end_date: '2026-04-10',
        items: [
          {
            subtype: 'Latest summary',
            transaction_count: 4,
            total_outgoing: 400,
            total_incoming: 250,
          },
        ],
      }));
    });

    expect(await screen.findByText('Latest summary')).toBeInTheDocument();
    expect(screen.getByText(/showing 01\/02\/2026 to 10\/04\/2026/i)).toBeInTheDocument();

    await act(async () => {
      resolveLastMonth?.(buildTransferSummaryResponse({
        start_date: '2026-03-01',
        end_date: '2026-03-31',
        items: [
          {
            subtype: 'Stale summary',
            transaction_count: 2,
            total_outgoing: 200,
            total_incoming: 150,
          },
        ],
      }));
    });

    expect(screen.getByText('Latest summary')).toBeInTheDocument();
    expect(screen.queryByText('Stale summary')).not.toBeInTheDocument();

    consoleSpy.mockRestore();
  });
});
