import type { AxiosInstance } from 'axios';
import { API_BASE_URL } from '../config';

const axiosModule = require('axios') as any;

const axios =
  (axiosModule?.create
    ? axiosModule
    : axiosModule?.default?.create
      ? axiosModule.default
      : axiosModule?.default?.default?.create
        ? axiosModule.default.default
        : axiosModule) as any;

const AxiosHeaders =
  axiosModule?.AxiosHeaders ??
  axiosModule?.default?.AxiosHeaders ??
  axiosModule?.default?.default?.AxiosHeaders;

export const REPORTING_CURRENCIES = ['EUR', 'USD', 'BRL'] as const;
export type ReportingCurrency = (typeof REPORTING_CURRENCIES)[number];

export const DEFAULT_REPORTING_CURRENCY: ReportingCurrency = 'EUR';
export const REPORTING_CURRENCY_STORAGE_KEY = 'reporting_currency';
export const REPORTING_CURRENCY_HEADER = 'X-Reporting-Currency';

const isReportingCurrency = (value: unknown): value is ReportingCurrency =>
  typeof value === 'string' &&
  (REPORTING_CURRENCIES as readonly string[]).includes(value);

export const readStoredReportingCurrency = (): ReportingCurrency => {
  if (typeof window === 'undefined') {
    return DEFAULT_REPORTING_CURRENCY;
  }

  const storedValue = window.localStorage.getItem(REPORTING_CURRENCY_STORAGE_KEY);
  return isReportingCurrency(storedValue) ? storedValue : DEFAULT_REPORTING_CURRENCY;
};

let activeReportingCurrency: ReportingCurrency = readStoredReportingCurrency();

export const syncReportingCurrencyFromStorage = (): ReportingCurrency => {
  activeReportingCurrency = readStoredReportingCurrency();
  return activeReportingCurrency;
};

export const getReportingCurrency = (): ReportingCurrency => activeReportingCurrency;

export const setReportingCurrency = (currency: ReportingCurrency): ReportingCurrency => {
  activeReportingCurrency = isReportingCurrency(currency) ? currency : DEFAULT_REPORTING_CURRENCY;

  if (typeof window !== 'undefined') {
    window.localStorage.setItem(REPORTING_CURRENCY_STORAGE_KEY, activeReportingCurrency);
  }

  return activeReportingCurrency;
};

syncReportingCurrencyFromStorage();

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
}) as AxiosInstance;

export const applyReportingCurrencyHeader = <T extends { headers?: unknown }>(
  config: T
): T => {
  const headers = AxiosHeaders.from(config.headers);
  headers.set(REPORTING_CURRENCY_HEADER, getReportingCurrency());
  config.headers = headers;
  return config;
};

apiClient.interceptors.request.use((config: any) => applyReportingCurrencyHeader(config));

const buildApiUrl = (path: string): string => {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  return `${API_BASE_URL}${path}`;
};

export const apiFetch = (path: string, init: RequestInit = {}) => {
  const headers = new Headers(init.headers);
  headers.set(REPORTING_CURRENCY_HEADER, getReportingCurrency());

  return fetch(buildApiUrl(path), {
    ...init,
    headers,
  });
};
