import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useNavigate, useParams } from 'react-router-dom';

import { importService } from '../../services/importService';
import { ImportReviewPayload } from '../../types/import';
import { formatDisplayDate } from '../../utils/date';

const formatAmount = (amount: number, currency: string) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(amount);

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

export const ImportReviewPage: React.FC = () => {
  const navigate = useNavigate();
  const { sessionId } = useParams();
  const parsedSessionId = Number(sessionId);
  const [review, setReview] = useState<ImportReviewPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<'approve' | 'reject' | 'retry' | null>(null);

  const loadReview = useCallback(async () => {
    if (!Number.isInteger(parsedSessionId) || parsedSessionId <= 0) {
      setReview(null);
      setError('Invalid import session.');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const payload = await importService.getReview(parsedSessionId);
      setReview(payload);
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Could not load this import review.'));
      setReview(null);
    } finally {
      setLoading(false);
    }
  }, [parsedSessionId]);

  useEffect(() => {
    void loadReview();
  }, [loadReview]);

  const evidenceBlocks = useMemo(() => review?.evidence?.text_blocks ?? [], [review?.evidence]);
  const awaitingReview = review?.session.status === 'awaiting_review';
  const hasBlockingIssues = useMemo(() => review?.issues.some((issue) => issue.blocking) ?? false, [review?.issues]);
  const canApprove = awaitingReview && !hasBlockingIssues;
  const retryable = review?.session.status === 'awaiting_review' || review?.session.status === 'failed';

  const handleApprove = async () => {
    if (!canApprove) {
      return;
    }

    setActiveAction('approve');
    setActionError(null);

    try {
      await importService.approve(parsedSessionId);
      navigate('/transactions');
    } catch (approveError) {
      setActionError(getErrorMessage(approveError, 'Could not approve this import right now.'));
    } finally {
      setActiveAction(null);
    }
  };

  const handleReject = async () => {
    if (!awaitingReview) {
      return;
    }

    setActiveAction('reject');
    setActionError(null);

    try {
      await importService.reject(parsedSessionId);
      navigate('/transactions');
    } catch (rejectError) {
      setActionError(getErrorMessage(rejectError, 'Could not reject this import right now.'));
    } finally {
      setActiveAction(null);
    }
  };

  const handleRetry = async () => {
    if (!retryable) {
      return;
    }

    setActiveAction('retry');
    setActionError(null);

    try {
      await importService.retry(parsedSessionId);
      await loadReview();
    } catch (retryError) {
      setActionError(getErrorMessage(retryError, 'Could not retry this import right now.'));
    } finally {
      setActiveAction(null);
    }
  };

  if (loading) {
    return <div className="py-10 text-sm text-gray-600 dark:text-gray-300">Loading import review...</div>;
  }

  if (error) {
    return (
      <div className="space-y-4 py-10">
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Import Review</h1>
        <p className="text-sm text-red-600 dark:text-red-300">{error}</p>
        <button
          type="button"
          onClick={() => {
            void loadReview();
          }}
          className="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!review) {
    return null;
  }

  return (
    <div className="space-y-8 pb-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Import Review</h1>
          <p className="text-sm text-gray-600 dark:text-gray-300">{review.session.file_name}</p>
          <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <span className="rounded-md bg-blue-50 px-2 py-1 text-blue-700 dark:bg-blue-500/20 dark:text-blue-200">
              Status: {review.session.status}
            </span>
            <span>Attempt {review.session.attempt_count}</span>
            {review.session.extractor_id ? <span>Extractor: {review.session.extractor_id}</span> : null}
          </div>
          {review.session.error_message ? (
            <p className="text-sm text-red-600 dark:text-red-300">{review.session.error_message}</p>
          ) : null}
          {actionError ? (
            <p className="text-sm text-red-600 dark:text-red-300">{actionError}</p>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleApprove}
            disabled={!canApprove || activeAction !== null}
            className="inline-flex items-center rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {activeAction === 'approve' ? 'Approving...' : 'Approve'}
          </button>
          <button
            type="button"
            onClick={handleReject}
            disabled={!awaitingReview || activeAction !== null}
            className="inline-flex items-center rounded-md bg-gray-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {activeAction === 'reject' ? 'Rejecting...' : 'Reject'}
          </button>
          <button
            type="button"
            onClick={handleRetry}
            disabled={!retryable || activeAction !== null}
            className="inline-flex items-center rounded-md border border-blue-600 px-4 py-2 text-sm font-medium text-blue-700 disabled:cursor-not-allowed disabled:border-gray-400 disabled:text-gray-400 dark:text-blue-200"
          >
            {activeAction === 'retry' ? 'Retrying...' : 'Retry'}
          </button>
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Session</h2>
        <dl className="grid gap-3 text-sm text-gray-700 dark:text-gray-300 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <dt className="font-medium text-gray-500 dark:text-gray-400">MIME Type</dt>
            <dd>{review.session.mime_type}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-500 dark:text-gray-400">Strategy</dt>
            <dd>{review.session.strategy_key ?? 'Unknown'}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-500 dark:text-gray-400">Provider</dt>
            <dd>{review.session.provider_hint ?? 'Unknown'}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-500 dark:text-gray-400">Updated</dt>
            <dd>{formatDisplayDate(review.session.updated_at)}</dd>
          </div>
        </dl>
      </section>

      {review.statement ? (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Statement Summary</h2>
          <dl className="grid gap-3 text-sm text-gray-700 dark:text-gray-300 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <dt className="font-medium text-gray-500 dark:text-gray-400">Period</dt>
              <dd>
                {formatDisplayDate(review.statement.statement_period_start)} to{' '}
                {formatDisplayDate(review.statement.statement_period_end)}
              </dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500 dark:text-gray-400">Card</dt>
              <dd>{review.statement.card_number_hint ?? 'Unknown'}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500 dark:text-gray-400">Currency</dt>
              <dd>{review.statement.currency ?? 'Unknown'}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500 dark:text-gray-400">Draft Rows</dt>
              <dd>{review.statement.transaction_count ?? review.transactions.length}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Draft Transactions</h2>
          <span className="text-sm text-gray-500 dark:text-gray-400">{review.transactions.length} rows</span>
        </div>
        {review.transactions.length === 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-300">No draft transactions are available for review.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Date
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Description
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Amount
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Locator
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Source
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white text-sm dark:divide-gray-700 dark:bg-gray-900">
                {review.transactions.map((transaction) => (
                  <tr key={transaction.id}>
                    <td className="px-4 py-3 text-gray-900 dark:text-gray-200">
                      {formatDisplayDate(transaction.transaction_date)}
                    </td>
                    <td className="px-4 py-3 text-gray-900 dark:text-gray-200">
                      <div className="font-medium">{transaction.source_description}</div>
                      {transaction.canonical_description_en ? (
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {transaction.canonical_description_en}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-gray-900 dark:text-gray-200">
                      {formatAmount(transaction.signed_amount, transaction.currency)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600 dark:text-gray-300">
                      {transaction.source_locator}
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{transaction.edit_source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Issues</h2>
        {review.issues.length === 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-300">No issues were raised for this import attempt.</p>
        ) : (
          <ul className="space-y-3">
            {review.issues.map((issue) => (
              <li
                key={issue.id}
                className="rounded-lg border border-gray-200 p-4 text-sm dark:border-gray-700"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-900 dark:text-gray-100">{issue.issue_message}</span>
                  <span className="rounded-md bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900 dark:bg-amber-500/20 dark:text-amber-100">
                    {issue.severity}
                  </span>
                  {issue.blocking ? (
                    <span className="rounded-md bg-red-100 px-2 py-1 text-xs font-medium text-red-800 dark:bg-red-500/20 dark:text-red-200">
                      blocking
                    </span>
                  ) : null}
                </div>
                <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  {issue.issue_code}
                  {issue.transaction_ref ? ` • ${issue.transaction_ref}` : ''}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Evidence</h2>
        {evidenceBlocks.length === 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-300">No raw evidence is available for this attempt.</p>
        ) : (
          <div className="space-y-4">
            {evidenceBlocks.map((block) => (
              <div key={block.page_number} className="space-y-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">Page {block.page_number}</div>
                <div>
                  <div className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Lines
                  </div>
                  <ol className="space-y-1 font-mono text-xs text-gray-700 dark:text-gray-300">
                    {block.lines.map((line, index) => (
                      <li key={`${block.page_number}-${index}`}>{line}</li>
                    ))}
                  </ol>
                </div>
                <div>
                  <div className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Raw Text
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-xs text-gray-700 dark:bg-gray-900 dark:text-gray-300">
                    {block.raw_text}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
