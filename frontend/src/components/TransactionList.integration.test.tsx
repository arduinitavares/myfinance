import { fireEvent, render, screen } from '@testing-library/react';

import { TransactionList } from './TransactionList';
import { classificationService } from '../services/classificationService';
import { TransactionType } from '../types/transaction';

jest.mock('../services/classificationService', () => ({
  classificationService: {
    createSession: jest.fn(),
    propose: jest.fn(),
    feedback: jest.fn(),
    accept: jest.fn(),
    previewSimilar: jest.fn(),
    applyBatch: jest.fn(),
  },
}));

const mockedService = classificationService as jest.Mocked<typeof classificationService>;

describe('TransactionList integration', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    mockedService.createSession.mockResolvedValue({
      id: 10,
      transaction_id: 1,
      status: 'open',
    } as never);
    mockedService.propose.mockResolvedValue({
      id: 99,
      session_id: 10,
      turn_index: 0,
      transaction_type: 'Expense',
      category: 'Utilities',
      confidence: 0.91,
      recurrence_frequency: 'monthly',
      rationale: 'The merchant name suggests a telecom or household bill.',
      follow_up_question: null,
      feedback_tag: null,
      feedback_note: null,
      prompt_tokens: 10,
      completion_tokens: 20,
      created_at: '2026-04-11T12:00:00Z',
    } as never);
    mockedService.accept.mockResolvedValue({
      session: {
        id: 10,
        transaction_id: 1,
        status: 'accepted',
      },
      transaction: {
        id: 1,
        expense_category: 'Utilities',
        classification_source: 'assistant',
      },
      recurrence_pattern_id: null,
    } as never);
    mockedService.previewSimilar.mockResolvedValue({
      session: {
        id: 10,
        transaction_id: 1,
        status: 'accepted',
      },
      seed_transaction_id: 1,
      matches: [],
    } as never);
  });

  test('keeps the completion state visible after Save & Next reaches the end of the list', async () => {
    const onTransactionsRefresh = jest.fn().mockResolvedValue(undefined);

    render(
      <TransactionList
        transactions={[
          {
            id: 1,
            account_number: 'BE001',
            transaction_date: '2026-04-11',
            amount: -45.99,
            currency: 'EUR',
            description: 'SEPA PROXIMUS',
            transaction_type: TransactionType.EXPENSE,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={1}
        currentPage={1}
        totalPages={1}
        onPageChange={() => {}}
        sortParams={{ field: 'date', direction: 'desc' }}
        onSortChange={() => {}}
        onTransactionUpdate={async () => {}}
        onTransactionDelete={async () => {}}
        onTransactionsRefresh={onTransactionsRefresh}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));
    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /save & next/i }));

    expect(
      await screen.findByText(/no more uncategorized transactions/i)
    ).toBeInTheDocument();
    expect(onTransactionsRefresh).toHaveBeenCalled();
  });
});
