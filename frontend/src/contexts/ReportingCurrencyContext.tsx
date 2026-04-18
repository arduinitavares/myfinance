import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
  DEFAULT_REPORTING_CURRENCY,
  type ReportingCurrency,
  REPORTING_CURRENCIES,
  readStoredReportingCurrency,
  setReportingCurrency as persistReportingCurrency,
  syncReportingCurrencyFromStorage,
} from '../services/apiClient';

type ReportingCurrencyContextValue = {
  reportingCurrency: ReportingCurrency;
  setReportingCurrency: (currency: ReportingCurrency) => void;
  supportedCurrencies: readonly ReportingCurrency[];
};

const ReportingCurrencyContext = createContext<ReportingCurrencyContextValue | undefined>(undefined);

export const ReportingCurrencyProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [reportingCurrency, setReportingCurrencyState] = useState<ReportingCurrency>(() => {
    const initialCurrency = readStoredReportingCurrency();
    syncReportingCurrencyFromStorage();
    return initialCurrency;
  });

  const setReportingCurrency = useCallback((currency: ReportingCurrency) => {
    const nextCurrency = persistReportingCurrency(currency);
    setReportingCurrencyState((currentCurrency) =>
      currentCurrency === nextCurrency ? currentCurrency : nextCurrency
    );
  }, []);

  const value = useMemo(
    () => ({
      reportingCurrency,
      setReportingCurrency,
      supportedCurrencies: REPORTING_CURRENCIES,
    }),
    [reportingCurrency, setReportingCurrency]
  );

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== 'reporting_currency') {
        return;
      }

      const nextCurrency = syncReportingCurrencyFromStorage();
      setReportingCurrencyState((currentCurrency) =>
        currentCurrency === nextCurrency ? currentCurrency : nextCurrency
      );
    };

    window.addEventListener('storage', handleStorage);
    return () => {
      window.removeEventListener('storage', handleStorage);
    };
  }, []);

  return (
    <ReportingCurrencyContext.Provider value={value}>
      {children}
    </ReportingCurrencyContext.Provider>
  );
};

export const useReportingCurrency = (): ReportingCurrencyContextValue => {
  const context = useContext(ReportingCurrencyContext);
  if (!context) {
    throw new Error('useReportingCurrency must be used within a ReportingCurrencyProvider');
  }

  return context;
};

export { DEFAULT_REPORTING_CURRENCY, REPORTING_CURRENCIES };
export type { ReportingCurrency };
