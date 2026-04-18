import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';

jest.mock('axios', () => ({
  __esModule: true,
  create: jest.fn(() => ({
    interceptors: {
      request: {
        use: jest.fn(),
      },
    },
  })),
  default: {
    create: jest.fn(() => ({
      interceptors: {
        request: {
          use: jest.fn(),
        },
      },
    })),
  },
  AxiosHeaders: {
    from: () => ({
      set: jest.fn(),
    }),
  },
}));

import {
  DEFAULT_REPORTING_CURRENCY,
  ReportingCurrencyProvider,
  useReportingCurrency,
} from './ReportingCurrencyContext';
import {
  REPORTING_CURRENCY_STORAGE_KEY,
  getReportingCurrency,
  syncReportingCurrencyFromStorage,
} from '../services/apiClient';

const TestHarness = () => {
  const { reportingCurrency, setReportingCurrency, supportedCurrencies } = useReportingCurrency();

  return (
    <div>
      <span data-testid="current-currency">{reportingCurrency}</span>
      <span data-testid="supported-currencies">{supportedCurrencies.join(',')}</span>
      <button type="button" onClick={() => setReportingCurrency('USD')}>
        Set USD
      </button>
    </div>
  );
};

describe('ReportingCurrencyContext', () => {
  beforeEach(() => {
    window.localStorage.clear();
    syncReportingCurrencyFromStorage();
  });

  test('defaults to EUR when storage is empty', () => {
    render(
      <ReportingCurrencyProvider>
        <TestHarness />
      </ReportingCurrencyProvider>
    );

    expect(screen.getByTestId('current-currency')).toHaveTextContent(DEFAULT_REPORTING_CURRENCY);
    expect(screen.getByTestId('supported-currencies')).toHaveTextContent('EUR,USD,BRL');
    expect(getReportingCurrency()).toBe(DEFAULT_REPORTING_CURRENCY);
  });

  test('loads a valid stored reporting currency', () => {
    window.localStorage.setItem(REPORTING_CURRENCY_STORAGE_KEY, 'BRL');

    render(
      <ReportingCurrencyProvider>
        <TestHarness />
      </ReportingCurrencyProvider>
    );

    expect(screen.getByTestId('current-currency')).toHaveTextContent('BRL');
    expect(getReportingCurrency()).toBe('BRL');
  });

  test('falls back to EUR when storage is invalid', () => {
    window.localStorage.setItem(REPORTING_CURRENCY_STORAGE_KEY, 'JPY');

    render(
      <ReportingCurrencyProvider>
        <TestHarness />
      </ReportingCurrencyProvider>
    );

    expect(screen.getByTestId('current-currency')).toHaveTextContent(DEFAULT_REPORTING_CURRENCY);
    expect(getReportingCurrency()).toBe(DEFAULT_REPORTING_CURRENCY);
  });

  test('persists updates and syncs the request currency', () => {
    render(
      <ReportingCurrencyProvider>
        <TestHarness />
      </ReportingCurrencyProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Set USD' }));

    expect(screen.getByTestId('current-currency')).toHaveTextContent('USD');
    expect(window.localStorage.getItem(REPORTING_CURRENCY_STORAGE_KEY)).toBe('USD');
    expect(getReportingCurrency()).toBe('USD');
  });

  test('syncs currency changes from another tab via the storage event', () => {
    render(
      <ReportingCurrencyProvider>
        <TestHarness />
      </ReportingCurrencyProvider>
    );

    act(() => {
      window.localStorage.setItem(REPORTING_CURRENCY_STORAGE_KEY, 'BRL');
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: REPORTING_CURRENCY_STORAGE_KEY,
          newValue: 'BRL',
        })
      );
    });

    expect(screen.getByTestId('current-currency')).toHaveTextContent('BRL');
    expect(getReportingCurrency()).toBe('BRL');
  });
});
