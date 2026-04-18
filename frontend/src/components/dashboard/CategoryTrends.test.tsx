import React from 'react';
import { render, screen } from '@testing-library/react';

import { CategoryTrends } from './CategoryTrends';
import { formatMoney } from '../../utils/currency';

const mockSetCategoryPeriod = jest.fn();
const mockSetExpenseTypePeriod = jest.fn();

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

jest.mock('../../hooks/useCategoryStatistics', () => ({
  useCategoryStatistics: () => ({
    setPeriod: mockSetCategoryPeriod,
    loading: false,
    error: null,
  }),
}));

jest.mock('../../hooks/useStatisticsTimeseries', () => ({
  useStatisticsTimeseries: () => ({
    timeseriesData: [
      {
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
        period: 'monthly',
      },
    ],
    loading: false,
    error: null,
    reportingCurrency: 'USD',
    conversionSummary: {
      converted_transaction_count: 1,
      unavailable_transaction_count: 1,
      unavailable_currencies: ['NEXO'],
    },
  }),
}));

jest.mock('../../hooks/useStatistics', () => ({
  useStatistics: () => ({
    statistics: {
      current_month: {
        period: 'monthly',
        date: '2026-03-31',
        reporting_currency: 'USD',
        conversion_summary: {
          converted_transaction_count: 1,
          unavailable_transaction_count: 0,
          unavailable_currencies: [],
        },
        period_income: 1200,
        period_expenses: 300,
        period_net_savings: 900,
        savings_rate: 75,
        total_income: 3600,
        total_expenses: 900,
        total_net_savings: 2700,
        income_count: 1,
        expense_count: 1,
        average_income: 1200,
        average_expense: 300,
        yearly_income: 3600,
        yearly_expenses: 900,
      },
      last_month: {
        period: 'monthly',
        date: '2026-02-28',
        reporting_currency: 'USD',
        conversion_summary: {
          converted_transaction_count: 1,
          unavailable_transaction_count: 0,
          unavailable_currencies: [],
        },
        period_income: 1000,
        period_expenses: 250,
        period_net_savings: 750,
        savings_rate: 75,
        total_income: 2400,
        total_expenses: 600,
        total_net_savings: 1800,
        income_count: 1,
        expense_count: 1,
        average_income: 1000,
        average_expense: 250,
        yearly_income: 2400,
        yearly_expenses: 600,
      },
      previous_year_last_month: {
        period: 'monthly',
        date: '2025-12-31',
        reporting_currency: 'USD',
        conversion_summary: {
          converted_transaction_count: 1,
          unavailable_transaction_count: 0,
          unavailable_currencies: [],
        },
        period_income: 900,
        period_expenses: 200,
        period_net_savings: 700,
        savings_rate: 77.7,
        total_income: 10800,
        total_expenses: 2400,
        total_net_savings: 8400,
        income_count: 1,
        expense_count: 1,
        average_income: 900,
        average_expense: 200,
        yearly_income: 10800,
        yearly_expenses: 2400,
      },
      all_time: {
        period: 'all_time',
        date: null,
        reporting_currency: 'USD',
        conversion_summary: {
          converted_transaction_count: 1,
          unavailable_transaction_count: 0,
          unavailable_currencies: [],
        },
        period_income: 3600,
        period_expenses: 900,
        period_net_savings: 2700,
        savings_rate: 75,
        total_income: 3600,
        total_expenses: 900,
        total_net_savings: 2700,
        income_count: 3,
        expense_count: 3,
        average_income: 1200,
        average_expense: 300,
        yearly_income: 3600,
        yearly_expenses: 900,
      },
    },
    loading: false,
    error: null,
  }),
}));

jest.mock('../../hooks/useExpenseTypeStatistics', () => ({
  useExpenseTypeStatistics: () => ({
    essentialExpenses: { period_amount: 1200 },
    discretionaryExpenses: { period_amount: 300 },
    essentialPercentage: 80,
    discretionaryPercentage: 20,
    topEssentialCategories: [
      {
        category: 'Groceries',
        period_amount: 1200,
        period_transaction_count: 3,
        period_percentage: 80,
      },
    ],
    topDiscretionaryCategories: [
      {
        category: 'Entertainment',
        period_amount: 300,
        period_transaction_count: 2,
        period_percentage: 20,
      },
    ],
    setPeriod: mockSetExpenseTypePeriod,
    loading: false,
    error: null,
    reportingCurrency: 'USD',
    conversionSummary: {
      converted_transaction_count: 1,
      unavailable_transaction_count: 1,
      unavailable_currencies: ['NEXO'],
    },
  }),
}));

describe('CategoryTrends', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (window as typeof window & { ResizeObserver?: typeof ResizeObserverMock }).ResizeObserver =
      ResizeObserverMock;
  });

  test('uses the reporting currency formatter and shows the partial-data warning', async () => {
    render(<CategoryTrends />);

    expect(await screen.findByText(/some totals exclude unsupported currencies: nexo\./i)).toBeInTheDocument();
    expect(screen.getAllByText(formatMoney(1200, 'USD', { notation: 'compact' })).length).toBeGreaterThan(0);
    expect(screen.queryByText(formatMoney(1200, 'EUR', { notation: 'compact' }))).not.toBeInTheDocument();
  });
});
