import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { TransactionList } from './TransactionList';
import { ExpenseCategory, TransactionType, TransferCategory } from '../types/transaction';

jest.mock('./transactions/ClassificationAssistantModal', () => ({
  ClassificationAssistantModal: ({
    open,
    transaction,
    onSaved,
    getNextTransaction,
  }: {
    open: boolean;
    transaction: { id: number; description: string } | null;
    onSaved: (nextTransaction: { id: number; description: string } | null) => Promise<void>;
    getNextTransaction: (currentId: number) => { id: number; description: string } | null;
  }) =>
    open ? (
      <div data-testid="assistant-modal">
        <div>{transaction?.description}</div>
        <button
          type="button"
          onClick={() => {
            void onSaved(transaction ? getNextTransaction(transaction.id) : null);
          }}
        >
          Save Next
        </button>
      </div>
    ) : null,
}));

jest.mock('@radix-ui/react-select', () => {
  const React = require('react') as typeof import('react');

  const SelectContext = React.createContext<{
    value: string;
    onValueChange: (value: string) => void;
  } | null>(null);

  const Root = ({ value, onValueChange, children }: {
    value: string;
    onValueChange: (value: string) => void;
    children: React.ReactNode;
  }) => (
    <SelectContext.Provider value={{ value, onValueChange }}>
      <div>{children}</div>
    </SelectContext.Provider>
  );

  const Trigger = ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>
      {children}
    </button>
  );

  const Value = ({ placeholder }: { placeholder?: string }) => {
    const context = React.useContext(SelectContext);
    return <span>{context?.value || placeholder}</span>;
  };

  const Portal = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Content = ({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) => {
    const context = React.useContext(SelectContext);
    return (
      <select
        aria-label={props['aria-label'] ?? 'category-select'}
        value={context?.value ?? ''}
        onChange={(event) => context?.onValueChange(event.target.value)}
      >
        {children}
      </select>
    );
  };
  const Viewport = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Group = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Label = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Item = ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  );
  const ItemText = ({ children }: { children: React.ReactNode }) => <>{children}</>;

  return {
    Root,
    Trigger,
    Value,
    Portal,
    Content,
    Viewport,
    Group,
    Label,
    Item,
    ItemText,
  };
});

describe('TransactionList', () => {
  test('shows Ask AI for every row and keeps action buttons fixed-width', () => {
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
          {
            id: 3,
            account_number: 'BE003',
            transaction_date: '2026-04-13',
            amount: -545,
            currency: 'EUR',
            description: 'Transfer to savings',
            transaction_type: TransactionType.TRANSFER,
            transfer_category: TransferCategory.INTERNAL_TRANSFER,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={3}
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

    const askAiButtons = screen.getAllByRole('button', { name: /ask ai/i });
    expect(askAiButtons).toHaveLength(3);
    askAiButtons.forEach((button) => {
      expect(button).toHaveClass('w-[88px]');
    });

    fireEvent.click(screen.getAllByRole('button', { name: /ask ai/i })[2]);

    expect(screen.getByTestId('assistant-modal')).toHaveTextContent('Transfer to savings');
  });

  test('tints uncategorized rows and category trigger to make review targets easy to spot', () => {
    render(
      <TransactionList
        transactions={[
          {
            id: 1,
            account_number: 'BE001',
            transaction_date: '2026-04-11',
            amount: -45.99,
            currency: 'EUR',
            description: 'Needs category',
            transaction_type: TransactionType.EXPENSE,
            source_bank: 'Belfius',
          },
          {
            id: 2,
            account_number: 'BE002',
            transaction_date: '2026-04-12',
            amount: -12.5,
            currency: 'EUR',
            description: 'Already done',
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

    const uncategorizedRow = screen.getByText('Needs category').closest('tr');
    const categorizedRow = screen.getByText('Already done').closest('tr');
    const triggers = screen.getAllByRole('button', { name: /select category|eating out/i });

    expect(uncategorizedRow).toHaveClass('bg-amber-50/80');
    expect(categorizedRow).not.toHaveClass('bg-amber-50/80');
    expect(triggers[0]).toHaveClass('border-amber-300');
    expect(triggers[1]).not.toHaveClass('border-amber-300');
  });

  test('shows Internal Transfer for transfer rows that store the category on transfer_category', () => {
    render(
      <TransactionList
        transactions={[
          {
            id: 3,
            account_number: 'BE003',
            transaction_date: '2026-04-13',
            amount: -545,
            currency: 'EUR',
            description: 'Transfer to my other account',
            transaction_type: TransactionType.TRANSFER,
            transfer_category: TransferCategory.INTERNAL_TRANSFER,
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
        onTransactionsRefresh={async () => {}}
      />
    );

    expect(screen.getByRole('button', { name: 'Internal Transfer' })).toBeInTheDocument();
  });

  test('renders converted display amounts when the API supplies reporting-currency fields', () => {
    render(
      <TransactionList
        transactions={[
          {
            id: 11,
            account_number: 'BE011',
            transaction_date: '2026-04-13',
            amount: -52.3,
            currency: 'EUR',
            display_amount: -59.71,
            display_currency: 'USD',
            description: 'OPENAI *CHATGPT SUBSCR DUBLIN IE',
            transaction_type: TransactionType.EXPENSE,
            expense_category: ExpenseCategory.ENTERTAINMENT,
            source_bank: 'Beobank',
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
        onTransactionsRefresh={async () => {}}
      />
    );

    expect(screen.getByText('$59.71')).toBeInTheDocument();
    expect(screen.queryByText(/FX unavailable/i)).not.toBeInTheDocument();
  });

  test('updates transfer rows using transfer categories', () => {
    const onTransactionUpdate = jest.fn().mockResolvedValue(undefined);

    render(
      <TransactionList
        transactions={[
          {
            id: 3,
            account_number: 'BE003',
            transaction_date: '2026-04-13',
            amount: -545,
            currency: 'EUR',
            description: 'Transfer to my other account',
            transaction_type: TransactionType.TRANSFER,
            transfer_category: TransferCategory.INTERNAL_TRANSFER,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={1}
        currentPage={1}
        totalPages={1}
        onPageChange={() => {}}
        sortParams={{ field: 'date', direction: 'desc' }}
        onSortChange={() => {}}
        onTransactionUpdate={onTransactionUpdate}
        onTransactionDelete={async () => {}}
        onTransactionsRefresh={async () => {}}
      />
    );

    fireEvent.change(screen.getByLabelText('category-select-3'), {
      target: { value: TransferCategory.CREDIT_CARD_SETTLEMENT },
    });
    fireEvent.click(screen.getByRole('button', { name: /apply row 3/i }));

    expect(onTransactionUpdate).toHaveBeenCalledWith(
      3,
      TransferCategory.CREDIT_CARD_SETTLEMENT,
      TransactionType.TRANSFER
    );
  });

  test('lets a row change type and category together before applying', async () => {
    const onTransactionUpdate = jest.fn().mockResolvedValue(undefined);

    render(
      <TransactionList
        transactions={[
          {
            id: 8,
            account_number: 'BE008',
            transaction_date: '2026-04-13',
            amount: -240,
            currency: 'EUR',
            description: 'Card settlement row',
            transaction_type: TransactionType.EXPENSE,
            expense_category: ExpenseCategory.HEALTH,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={1}
        currentPage={1}
        totalPages={1}
        onPageChange={() => {}}
        sortParams={{ field: 'date', direction: 'desc' }}
        onSortChange={() => {}}
        onTransactionUpdate={onTransactionUpdate}
        onTransactionDelete={async () => {}}
        onTransactionsRefresh={async () => {}}
      />
    );

    fireEvent.change(screen.getByLabelText('type-select-8'), {
      target: { value: TransactionType.TRANSFER },
    });
    fireEvent.change(screen.getByLabelText('category-select-8'), {
      target: { value: TransferCategory.CREDIT_CARD_SETTLEMENT },
    });
    fireEvent.click(screen.getByRole('button', { name: /apply row 8/i }));

    await waitFor(() => {
      expect(onTransactionUpdate).toHaveBeenCalledWith(
        8,
        TransferCategory.CREDIT_CARD_SETTLEMENT,
        TransactionType.TRANSFER
      );
    });
  });

  test('save and next advances to the next uncategorized non-transfer row', async () => {
    render(
      <TransactionList
        transactions={[
          {
            id: 1,
            account_number: 'BE001',
            transaction_date: '2026-04-11',
            amount: -45.99,
            currency: 'EUR',
            description: 'Uncategorized one',
            transaction_type: TransactionType.EXPENSE,
            source_bank: 'Belfius',
          },
          {
            id: 2,
            account_number: 'BE002',
            transaction_date: '2026-04-12',
            amount: -12.5,
            currency: 'EUR',
            description: 'Already categorized',
            transaction_type: TransactionType.EXPENSE,
            expense_category: ExpenseCategory.EATING_OUT,
            source_bank: 'Belfius',
          },
          {
            id: 3,
            account_number: 'BE003',
            transaction_date: '2026-04-13',
            amount: -30,
            currency: 'EUR',
            description: 'Uncategorized two',
            transaction_type: TransactionType.EXPENSE,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={3}
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

    fireEvent.click(screen.getAllByRole('button', { name: /ask ai/i })[0]);
    fireEvent.click(screen.getByRole('button', { name: /save next/i }));

    await waitFor(() => {
      expect(screen.getByTestId('assistant-modal')).toHaveTextContent('Uncategorized two');
    });
  });

  test('keeps the pagination area in a stable list shell and clamps long descriptions', () => {
    render(
      <TransactionList
        transactions={[
          {
            id: 9,
            account_number: 'BE009',
            transaction_date: '2026-01-06',
            amount: -65,
            currency: 'EUR',
            description:
              'Domiciliëringsopdracht voor SEPA STADIUM COUPURE VIA MOLL AUTOMATIC PAYMENT FOR MEMBER 427817SD24-5290-3117-3890Automatic payment for member 427817-Stadium Coupure and period 13/01',
            transaction_type: TransactionType.EXPENSE,
            expense_category: ExpenseCategory.PERSONAL,
            source_bank: 'Belfius',
          },
        ]}
        totalTransactions={1}
        currentPage={2}
        totalPages={25}
        onPageChange={() => {}}
        sortParams={{ field: 'date', direction: 'desc' }}
        onSortChange={() => {}}
        onTransactionUpdate={async () => {}}
        onTransactionDelete={async () => {}}
        onTransactionsRefresh={async () => {}}
      />
    );

    expect(screen.getByTestId('transaction-list-scroll-region')).toHaveClass('h-[520px]');
    expect(screen.getByTestId('transaction-list-pagination')).toHaveClass('mt-4', 'shrink-0');

    const description = screen.getByText(/Domiciliëringsopdracht voor SEPA STADIUM COUPURE/i);
    expect(description).toHaveAttribute(
      'title',
      'Domiciliëringsopdracht voor SEPA STADIUM COUPURE VIA MOLL AUTOMATIC PAYMENT FOR MEMBER 427817SD24-5290-3117-3890Automatic payment for member 427817-Stadium Coupure and period 13/01'
    );
    expect(description).toHaveClass('line-clamp-2');
  });
});
