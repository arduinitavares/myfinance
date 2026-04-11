import React, { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';

import { useClassificationSession } from '../../hooks/useClassificationSession';
import { classificationService } from '../../services/classificationService';
import { Transaction } from '../../types/transaction';

interface ClassificationAssistantModalProps {
  open: boolean;
  transaction: Transaction | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (nextTransaction: Transaction | null) => Promise<void>;
  getNextTransaction: (currentId: number) => Transaction | null;
}

const FEEDBACK_OPTIONS = [
  { value: 'close', label: 'Close' },
  { value: 'wrong_category', label: 'Wrong Category' },
  { value: 'wrong_type', label: 'Wrong Type' },
  { value: 'missing_context', label: 'Missing Context' },
  { value: 'explain_reasoning', label: 'Explain Reasoning' },
  { value: 'accept', label: 'Accept' },
] as const;

const RECURRENCE_FREQUENCIES = ['weekly', 'monthly', 'quarterly', 'yearly', 'unknown'] as const;

export const ClassificationAssistantModal: React.FC<ClassificationAssistantModalProps> = ({
  open,
  transaction,
  onOpenChange,
  onSaved,
  getNextTransaction,
}) => {
  const { phase, proposal, fallbackSuggestions, sessionId, setPhase, setProposal } = useClassificationSession(
    open,
    transaction?.id
  );
  const [feedbackTag, setFeedbackTag] = useState<string>('close');
  const [feedbackNote, setFeedbackNote] = useState('');
  const [savingError, setSavingError] = useState<string | null>(null);
  const [similarMatches, setSimilarMatches] = useState<
    Array<{ transaction_id: number; description: string; amount: number; currency: string; score: number }>
  >([]);
  const [pendingAdvanceToNext, setPendingAdvanceToNext] = useState(false);
  const [recurrenceEnabled, setRecurrenceEnabled] = useState(false);
  const [recurrenceFrequency, setRecurrenceFrequency] = useState<string>('monthly');

  useEffect(() => {
    setFeedbackTag('close');
    setFeedbackNote('');
    setSavingError(null);
    setSimilarMatches([]);
    setPendingAdvanceToNext(false);
  }, [transaction?.id]);

  useEffect(() => {
    if (!proposal) {
      return;
    }

    if (proposal.recurrence_frequency) {
      setRecurrenceEnabled(true);
      setRecurrenceFrequency(proposal.recurrence_frequency);
      return;
    }

    setRecurrenceEnabled(false);
    setRecurrenceFrequency('monthly');
  }, [proposal]);

  const finalizeSave = async (advanceToNext: boolean) => {
    if (!transaction) {
      return;
    }

    const nextTransaction = advanceToNext ? getNextTransaction(transaction.id) : null;
    await onSaved(nextTransaction);

    if (advanceToNext) {
      if (!nextTransaction) {
        setPhase('complete_no_more_uncategorized');
      }
      return;
    }

    onOpenChange(false);
  };

  const finishSave = async (advanceToNext: boolean, confirmTypeChange: boolean) => {
    if (!transaction || !proposal || !sessionId) {
      return;
    }

    setSavingError(null);
    setPhase('saving');

    try {
      await classificationService.accept(sessionId, {
        transaction_type: proposal.transaction_type,
        category: proposal.category,
        classification_source: 'assistant',
        confirm_type_change: confirmTypeChange,
        recurrence: {
          is_recurrent: recurrenceEnabled,
          frequency: recurrenceEnabled ? recurrenceFrequency : null,
        },
      });

      const preview = await classificationService.previewSimilar(sessionId);
      if (preview.matches.length > 0) {
        setSimilarMatches(preview.matches);
        setPendingAdvanceToNext(advanceToNext);
        setPhase('preview_similar');
        return;
      }
      await finalizeSave(advanceToNext);
    } catch (error) {
      console.error(error);
      setSavingError('Could not save this proposal right now.');
      setPhase('waiting_for_feedback');
    }
  };

  const handleSave = async (advanceToNext: boolean) => {
    if (!transaction || !proposal) {
      return;
    }

    if (proposal.transaction_type !== transaction.transaction_type) {
      setPendingAdvanceToNext(advanceToNext);
      setPhase('confirm_type_change');
      return;
    }

    await finishSave(advanceToNext, false);
  };

  const handleRetry = async () => {
    if (!sessionId) {
      return;
    }

    setSavingError(null);
    setPhase('retrying_with_feedback');

    try {
      const nextProposal = await classificationService.feedback(sessionId, {
        feedback_tag: feedbackTag,
        feedback_note: feedbackNote.trim() || null,
      });
      setProposal(nextProposal);
      setFeedbackNote('');
      setPhase('waiting_for_feedback');
    } catch (error) {
      console.error(error);
      setSavingError('Could not retry this proposal right now.');
      setPhase('waiting_for_feedback');
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(720px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 text-gray-900 shadow-xl dark:bg-gray-900 dark:text-gray-100">
          <Dialog.Title className="text-lg font-semibold">
            AI Classification Assistant
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Review the proposed category, leave feedback if needed, and save when it looks right.
          </Dialog.Description>

          {phase === 'generating_proposal' && (
            <p className="mt-4 text-sm text-gray-600 dark:text-gray-300">
              Generating proposal...
            </p>
          )}

          {phase === 'provider_unavailable_degraded' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm font-medium">Fallback suggestions</p>
              <div className="space-y-2">
                {fallbackSuggestions.map((suggestion) => (
                  <div
                    key={suggestion.category}
                    className="rounded-md border border-gray-200 px-3 py-2 text-sm dark:border-gray-700"
                  >
                    <div className="font-medium">{suggestion.category}</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {Math.round(suggestion.confidence * 100)}% confidence
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {phase === 'error' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm text-red-600 dark:text-red-400">
                Something went wrong while talking to the assistant.
              </p>
              <button
                type="button"
                className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </button>
            </div>
          )}

          {phase === 'waiting_for_feedback' && proposal && (
            <div className="mt-4 space-y-4">
              <div className="rounded-md border border-gray-200 p-4 dark:border-gray-700">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium">{proposal.category}</p>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      {proposal.transaction_type} · {Math.round(proposal.confidence * 100)}%
                    </p>
                  </div>
                  {proposal.recurrence_frequency && (
                    <span className="rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 dark:bg-blue-950 dark:text-blue-200">
                      {proposal.recurrence_frequency}
                    </span>
                  )}
                </div>

                {proposal.rationale && (
                  <p className="mt-3 text-sm text-gray-700 dark:text-gray-200">
                    {proposal.rationale}
                  </p>
                )}

                {proposal.follow_up_question && (
                  <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">
                    {proposal.follow_up_question}
                  </p>
                )}
              </div>

              <div className="rounded-md border border-gray-200 p-4 dark:border-gray-700">
                <label className="flex items-center gap-3 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={recurrenceEnabled}
                    onChange={(event) => setRecurrenceEnabled(event.target.checked)}
                  />
                  <span>Create recurrence rule</span>
                </label>
                {recurrenceEnabled && (
                  <div className="mt-3 flex items-center gap-3">
                    <label htmlFor="recurrence-frequency" className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                      Frequency
                    </label>
                    <select
                      id="recurrence-frequency"
                      value={recurrenceFrequency}
                      onChange={(event) => setRecurrenceFrequency(event.target.value)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                    >
                      {RECURRENCE_FREQUENCIES.map((frequency) => (
                        <option key={frequency} value={frequency}>
                          {frequency}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Feedback
                </p>
                <div className="flex flex-wrap gap-2">
                  {FEEDBACK_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={
                        feedbackTag === option.value
                          ? 'rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white'
                          : 'rounded-md border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 dark:border-gray-600 dark:text-gray-200'
                      }
                      onClick={() => setFeedbackTag(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <textarea
                  value={feedbackNote}
                  onChange={(event) => setFeedbackNote(event.target.value)}
                  className="min-h-[96px] w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
                  placeholder="Add context for the next try"
                />
                {savingError && (
                  <p className="text-sm text-red-600 dark:text-red-400">{savingError}</p>
                )}
              </div>

              <div className="flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600"
                  onClick={() => {
                    void handleRetry();
                  }}
                >
                  Try Again
                </button>
                <button
                  type="button"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600"
                  onClick={() => {
                    void handleSave(true);
                  }}
                >
                  Save & Next
                </button>
                <button
                  type="button"
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white"
                  onClick={() => {
                    void handleSave(false);
                  }}
                >
                  Save
                </button>
              </div>
            </div>
          )}

          {phase === 'saving' && (
            <p className="mt-4 text-sm text-gray-600 dark:text-gray-300">Saving proposal...</p>
          )}

          {phase === 'retrying_with_feedback' && (
            <p className="mt-4 text-sm text-gray-600 dark:text-gray-300">
              Trying again with your feedback...
            </p>
          )}

          {phase === 'confirm_type_change' && proposal && transaction && (
            <div className="mt-4 space-y-4">
              <div className="rounded-md border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/40">
                <p className="text-sm font-semibold text-amber-900 dark:text-amber-100">
                  Confirm type change
                </p>
                <p className="mt-2 text-sm text-amber-800 dark:text-amber-200">
                  The assistant wants to change this transaction from {transaction.transaction_type} to{' '}
                  {proposal.transaction_type}.
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600"
                  onClick={() => setPhase('waiting_for_feedback')}
                >
                  Go Back
                </button>
                <button
                  type="button"
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white"
                  onClick={() => {
                    void finishSave(pendingAdvanceToNext, true);
                  }}
                >
                  Confirm and Save
                </button>
              </div>
            </div>
          )}

          {phase === 'preview_similar' && (
            <div className="mt-4 space-y-4">
              <div className="rounded-md border border-gray-200 p-4 dark:border-gray-700">
                <p className="text-sm font-semibold">Apply to similar</p>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                  These uncategorized transactions look close enough to batch with the same answer.
                </p>
              </div>
              <div className="space-y-2">
                {similarMatches.map((match) => (
                  <div
                    key={match.transaction_id}
                    className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm dark:border-gray-700"
                  >
                    <span>{match.description}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {Math.round(match.score * 100)}%
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600"
                  onClick={() => {
                    void finalizeSave(pendingAdvanceToNext);
                  }}
                >
                  Skip
                </button>
                <button
                  type="button"
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white"
                  onClick={() => {
                    if (!sessionId) {
                      return;
                    }
                    void (async () => {
                      try {
                        await classificationService.applyBatch(
                          sessionId,
                          similarMatches.map((match) => match.transaction_id)
                        );
                        await finalizeSave(pendingAdvanceToNext);
                      } catch (error) {
                        console.error(error);
                        setSavingError('Could not apply this proposal to similar transactions.');
                      }
                    })();
                  }}
                >
                  Apply All
                </button>
              </div>
              {savingError && (
                <p className="text-sm text-red-600 dark:text-red-400">{savingError}</p>
              )}
            </div>
          )}

          {phase === 'complete_no_more_uncategorized' && (
            <div className="mt-4 space-y-3">
              <p className="text-sm text-gray-700 dark:text-gray-200">
                No more uncategorized transactions in this view.
              </p>
              <div className="flex justify-end">
                <button
                  type="button"
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white"
                  onClick={() => onOpenChange(false)}
                >
                  Close
                </button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
