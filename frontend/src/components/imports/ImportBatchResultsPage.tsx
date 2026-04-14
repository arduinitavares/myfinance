import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';

import { importService } from '../../services/importService';
import { ImportBatchItem, ImportBatchRun } from '../../types/import';
import { formatDisplayDate } from '../../utils/date';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;

    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }

    if (typeof detail?.message === 'string' && detail.message.trim()) {
      return detail.message;
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return fallback;
};

const getItemAction = (
  item: ImportBatchItem
): { label: 'Review' | 'Open Existing' | 'Open'; sessionId: number } | null => {
  if (item.status === 'skipped_existing' && item.existing_session_id != null) {
    return { label: 'Open Existing', sessionId: item.existing_session_id };
  }

  if (item.session_id == null) {
    return null;
  }

  if (item.session_status === 'awaiting_review') {
    return { label: 'Review', sessionId: item.session_id };
  }

  return { label: 'Open', sessionId: item.session_id };
};

const statusClasses: Record<ImportBatchRun['status'] | ImportBatchItem['status'], string> = {
  running: 'bg-blue-50 text-blue-700 dark:bg-blue-500/20 dark:text-blue-200',
  completed: 'bg-green-50 text-green-700 dark:bg-green-500/20 dark:text-green-200',
  failed: 'bg-red-50 text-red-700 dark:bg-red-500/20 dark:text-red-200',
  processed: 'bg-green-50 text-green-700 dark:bg-green-500/20 dark:text-green-200',
  skipped_existing: 'bg-blue-50 text-blue-700 dark:bg-blue-500/20 dark:text-blue-200',
  unsupported: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
};

export const ImportBatchResultsPage: React.FC = () => {
  const navigate = useNavigate();
  const { batchId } = useParams();
  const parsedBatchId = Number(batchId);
  const [batch, setBatch] = useState<ImportBatchRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBatch = useCallback(async () => {
    if (!Number.isInteger(parsedBatchId) || parsedBatchId <= 0) {
      setBatch(null);
      setError('Invalid import batch run.');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const payload = await importService.getBatchRun(parsedBatchId);
      setBatch(payload);
    } catch (loadError) {
      setBatch(null);
      setError(getErrorMessage(loadError, 'Could not load this batch run.'));
    } finally {
      setLoading(false);
    }
  }, [parsedBatchId]);

  useEffect(() => {
    void loadBatch();
  }, [loadBatch]);

  const summaryItems = useMemo(
    () =>
      batch
        ? [
            { label: 'Processed', value: batch.processed_count },
            { label: 'Skipped', value: batch.skipped_existing_count },
            { label: 'Unsupported', value: batch.unsupported_count },
            { label: 'Failed', value: batch.failed_count },
            { label: 'Total', value: batch.total_files },
          ]
        : [],
    [batch]
  );

  if (loading) {
    return <div className="py-10 text-sm text-gray-600 dark:text-gray-300">Loading batch results...</div>;
  }

  if (error) {
    return (
      <div className="space-y-4 py-10">
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Import Batch Results</h1>
        <p className="text-sm text-red-600 dark:text-red-300">{error}</p>
        <button
          type="button"
          onClick={() => {
            void loadBatch();
          }}
          className="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!batch) {
    return null;
  }

  return (
    <div className="space-y-8 pb-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Import Batch Results</h1>
          <p className="text-sm text-gray-600 dark:text-gray-300">{batch.folder_path}</p>
          <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <span className={`rounded-md px-2 py-1 ${statusClasses[batch.status]}`}>Status: {batch.status}</span>
            <span>Created {formatDisplayDate(batch.created_at)}</span>
            {batch.completed_at ? <span>Completed {formatDisplayDate(batch.completed_at)}</span> : null}
          </div>
          {batch.message ? <p className="text-sm text-gray-600 dark:text-gray-300">{batch.message}</p> : null}
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Summary</h2>
        <dl className="grid gap-3 text-sm text-gray-700 dark:text-gray-300 md:grid-cols-2 xl:grid-cols-5">
          {summaryItems.map((item) => (
            <div key={item.label}>
              <dt className="font-medium text-gray-500 dark:text-gray-400">{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Files</h2>
          <span className="text-sm text-gray-500 dark:text-gray-400">{batch.items.length} rows</span>
        </div>
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  File
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Message
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white text-sm dark:divide-gray-700 dark:bg-gray-900">
              {batch.items.map((item) => {
                const action = getItemAction(item);

                return (
                  <tr key={item.id}>
                    <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{item.filename}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${statusClasses[item.status]}`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{item.message ?? 'Ready for review.'}</td>
                    <td className="px-4 py-3">
                      {action ? (
                        <button
                          type="button"
                          onClick={() => navigate(`/imports/${action.sessionId}/review`)}
                          className="inline-flex items-center rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 dark:text-blue-200 dark:hover:bg-blue-500/10"
                        >
                          {action.label}
                        </button>
                      ) : (
                        <span className="text-sm text-gray-400 dark:text-gray-500">No action</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};
