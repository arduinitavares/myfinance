jest.mock('axios', () => {
  const create = jest.fn(() => ({
    interceptors: {
      request: {
        use: jest.fn(),
      },
    },
  }));

  return {
    __esModule: true,
    create,
    default: {
      create,
    },
    AxiosHeaders: {
      from: (headers?: HeadersInit) => {
        const normalized = new Headers(headers);

        return {
          get: (name: string) => normalized.get(name),
          set: (name: string, value: string) => normalized.set(name, value),
        };
      },
    },
  };
});

import {
  apiFetch,
  applyReportingCurrencyHeader,
  DEFAULT_REPORTING_CURRENCY,
  REPORTING_CURRENCY_HEADER,
  REPORTING_CURRENCY_STORAGE_KEY,
  setReportingCurrency,
  syncReportingCurrencyFromStorage,
} from './apiClient';

describe('apiClient', () => {
  beforeEach(() => {
    window.localStorage.clear();
    syncReportingCurrencyFromStorage();
    jest.restoreAllMocks();
  });

  test('attaches the reporting currency header to axios-style request configs', () => {
    setReportingCurrency('BRL');

    const config = applyReportingCurrencyHeader({
      headers: {
        Accept: 'application/json',
      },
    });

    const headers = config.headers as unknown as {
      get: (name: string) => string | null;
    };
    expect(headers.get(REPORTING_CURRENCY_HEADER)).toBe('BRL');
    expect(headers.get('Accept')).toBe('application/json');
  });

  test('apiFetch adds the reporting currency header and preserves existing headers', async () => {
    window.localStorage.setItem(REPORTING_CURRENCY_STORAGE_KEY, 'USD');
    syncReportingCurrencyFromStorage();

    const fetchSpy = jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({}),
    } as Response);

    await apiFetch('/projections/scenarios', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: '{}',
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('http://localhost:8000/projections/scenarios');
    const headers = new Headers(init?.headers);
    expect(headers.get(REPORTING_CURRENCY_HEADER)).toBe('USD');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  test('falls back to EUR for axios-style request configs when storage is invalid', () => {
    window.localStorage.setItem(REPORTING_CURRENCY_STORAGE_KEY, 'JPY');
    syncReportingCurrencyFromStorage();

    const config = applyReportingCurrencyHeader({
      headers: undefined,
    });

    const headers = config.headers as unknown as {
      get: (name: string) => string | null;
    };
    expect(headers.get(REPORTING_CURRENCY_HEADER)).toBe(
      DEFAULT_REPORTING_CURRENCY
    );
  });
});
