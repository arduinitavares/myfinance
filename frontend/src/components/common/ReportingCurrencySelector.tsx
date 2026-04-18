import React from 'react';

import { useReportingCurrency } from '../../contexts/ReportingCurrencyContext';

export const ReportingCurrencySelector: React.FC = () => {
  const { reportingCurrency, setReportingCurrency, supportedCurrencies } = useReportingCurrency();

  return (
    <div className="relative">
      <label htmlFor="reporting-currency-selector" className="sr-only">
        Reporting currency
      </label>
      <select
        id="reporting-currency-selector"
        aria-label="Reporting currency"
        value={reportingCurrency}
        onChange={(event) => setReportingCurrency(event.target.value as typeof reportingCurrency)}
        className="h-10 w-[96px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:focus:ring-blue-400"
      >
        {supportedCurrencies.map((currency) => (
          <option key={currency} value={currency}>
            {currency}
          </option>
        ))}
      </select>
    </div>
  );
};
