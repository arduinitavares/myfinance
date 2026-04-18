import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';

import { MonthlyHeatmap } from './MonthlyHeatmap';
import { ReportingCurrencyProvider } from '../../contexts/ReportingCurrencyContext';
import { statisticService } from '../../services/statisticService';

jest.mock('../../services/apiClient', () => {
  const REPORTING_CURRENCIES = ['EUR', 'USD', 'BRL'] as const;
  const DEFAULT_REPORTING_CURRENCY = 'EUR';
  const STORAGE_KEY = 'reporting_currency';

  const readStoredReportingCurrency = () => {
    const storedValue = localStorage.getItem(STORAGE_KEY);
    return REPORTING_CURRENCIES.includes(storedValue as (typeof REPORTING_CURRENCIES)[number])
      ? storedValue
      : DEFAULT_REPORTING_CURRENCY;
  };

  return {
    REPORTING_CURRENCIES,
    DEFAULT_REPORTING_CURRENCY,
    readStoredReportingCurrency,
    setReportingCurrency: (currency: string) => {
      localStorage.setItem(STORAGE_KEY, currency);
      return currency;
    },
    syncReportingCurrencyFromStorage: readStoredReportingCurrency,
  };
});

jest.mock('../../services/statisticService', () => ({
  statisticService: {
    getStatisticsTimeseries: jest.fn(),
  },
}));

const mockedGetStatisticsTimeseries =
  statisticService.getStatisticsTimeseries as jest.MockedFunction<
    typeof statisticService.getStatisticsTimeseries
  >;

const renderMonthlyHeatmap = () =>
  render(
    <ReportingCurrencyProvider>
      <MonthlyHeatmap />
    </ReportingCurrencyProvider>
  );

describe('MonthlyHeatmap', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
  });

  test('formats timeseries values in the selected reporting currency', async () => {
    window.localStorage.setItem('reporting_currency', 'USD');
    const items = [
      {
        period: 'monthly',
        date: '2026-03-31',
        period_income: 1200,
        period_expenses: 300,
        period_net_savings: 900,
        savings_rate: 75,
        total_income: 1200,
        total_expenses: 300,
        total_net_savings: 900,
        income_count: 1,
        expense_count: 1,
        average_income: 1200,
        average_expense: 300,
        yearly_income: 1200,
        yearly_expenses: 300,
      },
    ];
    const wrapperResponse = {
      reporting_currency: 'USD',
      conversion_summary: {
        converted_transaction_count: 1,
        unavailable_transaction_count: 0,
        unavailable_currencies: [],
      },
      items,
    };
    mockedGetStatisticsTimeseries.mockResolvedValueOnce(
      wrapperResponse as Awaited<ReturnType<typeof statisticService.getStatisticsTimeseries>>
    );

    const { container } = renderMonthlyHeatmap();

    expect(await screen.findByText(/monthly financial activity/i)).toBeInTheDocument();

    await waitFor(() => {
      const marchCell = container.querySelector('[title^="March 2026"]') as HTMLElement | null;
      expect(marchCell).not.toBeNull();
      expect(marchCell?.title).toContain('Income: $1,200.00');
      expect(marchCell?.title).toContain('Expenses: $300.00');
      expect(marchCell?.title).toContain('Net: $900.00');
      expect(marchCell?.title).not.toContain('€');
    });
  });
});
