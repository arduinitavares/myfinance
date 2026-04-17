import React, { useEffect, useRef, useState } from 'react';
import { statisticService, TransferSummaryResponse } from '../../services/statisticService';
import { Loading } from '../common/Loading';
import { formatDisplayDate } from '../../utils/date';
import {
  buildSpecificMonthRange,
  buildTransferSummaryRange,
  DEFAULT_TRANSFER_SUMMARY_PRESET,
  TransferSummaryPreset,
} from './transferSummaryRange';

const EUR_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
});

export const TransferSummary: React.FC = () => {
  const [summary, setSummary] = useState<TransferSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [anchorDate, setAnchorDate] = useState<string | null>(null);
  const [preset, setPreset] = useState<TransferSummaryPreset>(DEFAULT_TRANSFER_SUMMARY_PRESET);
  const [specificMonth, setSpecificMonth] = useState('');
  const isMountedRef = useRef(true);
  const requestSequenceRef = useRef(0);

  const startTransferSummaryRequest = () => {
    requestSequenceRef.current += 1;
    return requestSequenceRef.current;
  };

  const isLatestTransferSummaryRequest = (requestId: number) =>
    isMountedRef.current && requestSequenceRef.current === requestId;

  const executeFilteredRequest = async (range: { startDate: string; endDate: string }) => {
    const requestId = startTransferSummaryRequest();
    setRefreshing(true);
    setError(null);

    try {
      await loadTransferSummary(requestId, range.startDate, range.endDate);
    } catch (err) {
      if (!isLatestTransferSummaryRequest(requestId)) {
        return;
      }

      console.error('Error fetching transfer summary:', err);
      setError('Failed to load transfer summary');
    } finally {
      if (isLatestTransferSummaryRequest(requestId)) {
        setRefreshing(false);
      }
    }
  };

  const loadTransferSummary = async (requestId: number, startDate?: string, endDate?: string) => {
    const data = await statisticService.getTransferSummary(startDate, endDate);
    if (!isLatestTransferSummaryRequest(requestId)) {
      return;
    }

    setSummary(data);
    setAnchorDate((current) => current ?? data.end_date);
    setError(null);
    setHasLoadedOnce(true);
  };

  useEffect(() => {
    isMountedRef.current = true;

    const loadInitialTransferSummary = async () => {
      const requestId = startTransferSummaryRequest();
      try {
        setLoading(true);
        const data = await statisticService.getTransferSummary();
        if (!isLatestTransferSummaryRequest(requestId)) {
          return;
        }

        setSummary(data);
        setAnchorDate(data.end_date);
        setError(null);
        setHasLoadedOnce(true);
      } catch (err) {
        if (!isLatestTransferSummaryRequest(requestId)) {
          return;
        }

        console.error('Error fetching transfer summary:', err);
        setError('Failed to load transfer summary');
        setSummary(null);
      } finally {
        if (isLatestTransferSummaryRequest(requestId)) {
          setLoading(false);
        }
      }
    };

    loadInitialTransferSummary();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const formatCurrency = (amount: number) => EUR_FORMATTER.format(amount);

  const handlePresetChange = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    const nextPreset = event.target.value as TransferSummaryPreset;
    setPreset(nextPreset);

    if (!anchorDate) {
      return;
    }

    const range =
      nextPreset === 'specific_month'
        ? buildSpecificMonthRange(specificMonth)
        : buildTransferSummaryRange(nextPreset, anchorDate);

    if (!range) {
      return;
    }

    await executeFilteredRequest(range);
  };

  const handleSpecificMonthChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextMonth = event.target.value;
    setSpecificMonth(nextMonth);

    if (preset !== 'specific_month') {
      return;
    }

    const range = buildSpecificMonthRange(nextMonth);
    if (!range) {
      return;
    }

    await executeFilteredRequest(range);
  };

  if (loading && !hasLoadedOnce) {
    return <Loading variant="progress" size="medium" />;
  }

  if (error && !hasLoadedOnce) {
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
  const body = error ? (
    <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 px-4 py-8 text-sm text-gray-500 dark:text-gray-400">
      {error}
    </div>
  ) : items.length === 0 ? (
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
  );

  return (
    <div
      aria-busy={refreshing}
      className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-md hover:shadow-lg transition-all duration-300 border border-gray-100 dark:border-gray-700"
    >
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

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="transfer-summary-preset" className="text-xs font-medium text-gray-600 dark:text-gray-300">
            Transfer summary preset
          </label>
          <select
            id="transfer-summary-preset"
            aria-label="transfer summary preset"
            className="min-w-[180px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            value={preset}
            onChange={handlePresetChange}
            disabled={!anchorDate}
          >
            <option value="this_month">This month</option>
            <option value="last_month">Last month</option>
            <option value="last_3_months">Last 3 months</option>
            <option value="year_to_date">Year to date</option>
            <option value="specific_month">Specific month</option>
          </select>
        </div>

        {preset === 'specific_month' && (
          <div className="flex flex-col gap-1">
            <label htmlFor="transfer-summary-month" className="text-xs font-medium text-gray-600 dark:text-gray-300">
              Transfer summary month
            </label>
            <input
              id="transfer-summary-month"
              aria-label="transfer summary month"
              type="month"
              value={specificMonth}
              onChange={handleSpecificMonthChange}
              className="min-w-[180px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            />
          </div>
        )}
      </div>

      {body}
    </div>
  );
};
