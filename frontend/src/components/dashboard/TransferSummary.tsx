import React, { useEffect, useState } from 'react';
import { statisticService, TransferSummaryResponse } from '../../services/statisticService';
import { Loading } from '../common/Loading';
import { formatDisplayDate } from '../../utils/date';

const EUR_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
});

export const TransferSummary: React.FC = () => {
  const [summary, setSummary] = useState<TransferSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    const loadTransferSummary = async () => {
      try {
        setLoading(true);
        const data = await statisticService.getTransferSummary();
        if (!isMounted) {
          return;
        }

        setSummary(data);
        setError(null);
      } catch (err) {
        console.error('Error fetching transfer summary:', err);
        if (!isMounted) {
          return;
        }

        setError('Failed to load transfer summary');
        setSummary(null);
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    loadTransferSummary();

    return () => {
      isMounted = false;
    };
  }, []);

  const formatCurrency = (amount: number) => EUR_FORMATTER.format(amount);

  if (loading) {
    return <Loading variant="progress" size="medium" />;
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-md hover:shadow-lg transition-all duration-300 border border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-center text-gray-500 dark:text-gray-400">
          {error}
        </div>
      </div>
    );
  }

  if (!summary) {
    return null;
  }

  const items = summary.items ?? [];

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-md hover:shadow-lg transition-all duration-300 border border-gray-100 dark:border-gray-700">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-lg font-medium dark:text-gray-200">Transfers & Settlements</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {summary.start_date && summary.end_date
              ? `Showing ${formatDisplayDate(summary.start_date)} to ${formatDisplayDate(summary.end_date)}`
              : 'Showing transfer activity for the selected period'}
          </p>
        </div>
        <div className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
          {items.length} subtype{items.length === 1 ? '' : 's'}
        </div>
      </div>

      {items.length === 0 ? (
        <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 px-4 py-8 text-sm text-gray-500 dark:text-gray-400">
          No transfer summary data available.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead>
              <tr className="text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <th className="py-2 pr-4">Subtype</th>
                <th className="py-2 px-4 text-right">Outgoing</th>
                <th className="py-2 px-4 text-right">Incoming</th>
                <th className="py-2 pl-4 text-right">Transactions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {items.map((item) => (
                <tr key={item.subtype} className="text-sm">
                  <td className="py-3 pr-4 font-medium text-gray-900 dark:text-gray-100">
                    {item.subtype}
                  </td>
                  <td className="py-3 px-4 text-right text-gray-600 dark:text-gray-300">
                    {formatCurrency(item.total_outgoing_eur)}
                  </td>
                  <td className="py-3 px-4 text-right text-gray-600 dark:text-gray-300">
                    {formatCurrency(item.total_incoming_eur)}
                  </td>
                  <td className="py-3 pl-4 text-right text-gray-600 dark:text-gray-300">
                    {item.transaction_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
