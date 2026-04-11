import { fireEvent, render, screen } from '@testing-library/react';

import { TransactionList } from './TransactionList';
import { ExpenseCategory, TransactionType } from '../types/transaction';

jest.mock('./transactions/ClassificationAssistantModal', () => ({
  ClassificationAssistantModal: ({
    open,
    transaction,
  }: {
    open: boolean;
    transaction: { description: string } | null;
  }) => (open ? <div data-testid="assistant-modal">{transaction?.description}</div> : null),
}));

describe('TransactionList', () => {
  test('shows Ask AI only for uncategorized transactions and opens the assistant modal', () => {
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
          {
            id: 2,
            account_number: 'BE002',
            transaction_date: '2026-04-12',
            amount: -12.5,
            currency: 'EUR',
            description: 'Bakery',
            transaction_type: TransactionType.EXPENSE,
            expense_category: ExpenseCategory.EATING_OUT,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={2}
        currentPage={1}
        totalPages={1}
        onPageChange={() => {}}
        sortParams={{ field: 'date', direction: 'desc' }}
        onSortChange={() => {}}
        onTransactionUpdate={async () => {}}
        onTransactionDelete={async () => {}}
        onTransactionsRefresh={async () => {}}
      />
    );

    expect(screen.getAllByRole('button', { name: /ask ai/i })).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));

    expect(screen.getByTestId('assistant-modal')).toHaveTextContent('SEPA PROXIMUS');
  });
});
