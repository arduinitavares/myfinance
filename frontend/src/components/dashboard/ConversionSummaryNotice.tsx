import React from 'react';
import type { ConversionSummary } from '../../types/statistics';

interface ConversionSummaryNoticeProps {
  summary?: ConversionSummary | null;
}

export const ConversionSummaryNotice: React.FC<ConversionSummaryNoticeProps> = ({ summary }) => {
  if (!summary || summary.unavailable_transaction_count === 0) {
    return null;
  }

  const currencies = summary.unavailable_currencies.join(', ');

  return (
    <p className="mb-3 text-sm text-amber-700 dark:text-amber-300">
      Some totals exclude unsupported currencies: {currencies}.
    </p>
  );
};
