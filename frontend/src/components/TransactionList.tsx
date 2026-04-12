import React, { useEffect, useState } from 'react';
import * as Select from '@radix-ui/react-select';
import { Transaction, TransactionType, ExpenseCategory, IncomeCategory, TransferCategory, SortParams } from '../types/transaction';
import { format } from 'date-fns';
import { SparklesIcon, TrashIcon } from '@heroicons/react/24/outline';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { Pagination } from './common/Pagination';
import { ClassificationAssistantModal } from './transactions/ClassificationAssistantModal';

interface TransactionListProps {
  transactions: Transaction[];
  totalTransactions: number;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  sortParams: SortParams;
  onSortChange: (params: SortParams) => void;
  onTransactionUpdate: (
    transactionId: number,
    category: ExpenseCategory | IncomeCategory | TransferCategory,
    transactionType: TransactionType
  ) => Promise<void>;
  onTransactionDelete: (transactionId: number) => Promise<void>;
  onTransactionsRefresh: () => Promise<void>;
}

type SortField = 'date' | 'description' | 'amount' | 'type';
type RowDraft = {
  transactionType: TransactionType;
  category: string;
};

export const TransactionList: React.FC<TransactionListProps> = ({
  transactions,
  totalTransactions,
  currentPage,
  totalPages,
  onPageChange,
  sortParams,
  onSortChange,
  onTransactionUpdate,
  onTransactionDelete,
  onTransactionsRefresh,
}) => {
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(null);

  const getDisplayedCategory = (transaction: Transaction) => {
    if (transaction.transaction_type === TransactionType.EXPENSE) {
      return transaction.expense_category;
    }
    if (transaction.transaction_type === TransactionType.INCOME) {
      return transaction.income_category;
    }
    return transaction.transfer_category;
  };

  const isUncategorized = (transaction: Transaction) => {
    if (transaction.transaction_type === TransactionType.EXPENSE) {
      return !transaction.expense_category;
    }
    if (transaction.transaction_type === TransactionType.INCOME) {
      return !transaction.income_category;
    }
    return !transaction.transfer_category;
  };

  const getCategoryOptionsForType = (transactionType: TransactionType): string[] => {
    if (transactionType === TransactionType.EXPENSE) {
      return Object.values(ExpenseCategory);
    }
    if (transactionType === TransactionType.INCOME) {
      return Object.values(IncomeCategory);
    }
    return Object.values(TransferCategory);
  };

  const buildDraft = (transaction: Transaction): RowDraft => ({
    transactionType: transaction.transaction_type,
    category: getDisplayedCategory(transaction) ?? '',
  });

  const [drafts, setDrafts] = useState<Record<number, RowDraft>>({});

  useEffect(() => {
    setDrafts(
      Object.fromEntries(transactions.map((transaction) => [transaction.id, buildDraft(transaction)]))
    );
  }, [transactions]);

  const getDraft = (transaction: Transaction): RowDraft => drafts[transaction.id] ?? buildDraft(transaction);

  const isDirty = (transaction: Transaction, draft: RowDraft) =>
    draft.transactionType !== transaction.transaction_type ||
    draft.category !== (getDisplayedCategory(transaction) ?? '');

  const updateDraft = (transactionId: number, nextDraft: RowDraft) => {
    setDrafts((current) => ({
      ...current,
      [transactionId]: nextDraft,
    }));
  };

  const handleDraftTypeChange = (transaction: Transaction, nextType: TransactionType) => {
    const currentDraft = getDraft(transaction);
    const options = getCategoryOptionsForType(nextType);
    const nextCategory = options.includes(currentDraft.category) ? currentDraft.category : (options[0] ?? '');
    updateDraft(transaction.id, {
      transactionType: nextType,
      category: nextCategory,
    });
  };

  const handleDraftCategoryChange = (transaction: Transaction, nextCategory: string) => {
    const currentDraft = getDraft(transaction);
    updateDraft(transaction.id, {
      ...currentDraft,
      category: nextCategory,
    });
  };

  const handleApplyRow = async (transaction: Transaction) => {
    const draft = getDraft(transaction);
    if (!draft.category) {
      return;
    }

    await onTransactionUpdate(
      transaction.id,
      draft.category as ExpenseCategory | IncomeCategory | TransferCategory,
      draft.transactionType
    );
  };

  const handleSort = (field: SortField) => {
    if (field === sortParams.field) {
      onSortChange({
        field,
        direction: sortParams.direction === 'asc' ? 'desc' : 'asc'
      });
    } else {
      onSortChange({
        field,
        direction: 'asc'
      });
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (field !== sortParams.field) return null;
    return sortParams.direction === 'asc' ? 
      <ChevronUp className="w-4 h-4" /> : 
      <ChevronDown className="w-4 h-4" />;
  };

  const TableHeader = ({ field, label }: { field: SortField; label: string }) => (
    <th
      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center space-x-1">
        <span>{label}</span>
        <SortIcon field={field} />
      </div>
    </th>
  );

  const getNextTransaction = (currentId: number): Transaction | null => {
    const uncategorized = transactions.filter((item) => isUncategorized(item));
    const currentIndex = uncategorized.findIndex((item) => item.id === currentId);
    if (currentIndex === -1) {
      return null;
    }
    return uncategorized[currentIndex + 1] ?? null;
  };

  const handleAssistantSaved = async (nextTransaction: Transaction | null) => {
    await onTransactionsRefresh();
    if (nextTransaction) {
      setSelectedTransaction(nextTransaction);
    }
  };

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-800">
            <tr>
              <TableHeader field="date" label="Date" />
              <TableHeader field="description" label="Description" />
              <TableHeader field="amount" label="Amount" />
              <TableHeader field="type" label="Type" />
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Category
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white text-xs dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
            {transactions.map((transaction) => {
              const uncategorized = isUncategorized(transaction);
              const draft = getDraft(transaction);
              const rowDirty = isDirty(transaction, draft);

              return (
                <tr
                  key={transaction.id}
                  className={
                    uncategorized
                      ? 'bg-amber-50/80 hover:bg-amber-50 dark:bg-amber-500/10 dark:hover:bg-amber-500/15'
                      : 'hover:bg-gray-50 dark:hover:bg-gray-800/60'
                  }
                >
                  <td className="px-6 py-4 whitespace-nowrap text-gray-900 dark:text-gray-200">
                    {format(new Date(transaction.transaction_date), 'dd/MM/yyyy')}
                  </td>
                  <td className="px-6 py-4 text-gray-900 dark:text-gray-200">
                    {transaction.description}
                  </td>
                  <td className={`px-6 py-4 whitespace-nowrap ${
                    transaction.transaction_type === TransactionType.INCOME 
                      ? 'text-green-600' 
                      : 'text-red-600'
                  }`}>
                    {new Intl.NumberFormat('en-US', {
                      style: 'currency',
                      currency: transaction.currency,
                    }).format(Math.abs(transaction.amount))}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-gray-900 dark:text-gray-200">
                    <label className="sr-only" htmlFor={`type-select-${transaction.id}`}>
                      {`type-select-${transaction.id}`}
                    </label>
                    <select
                      id={`type-select-${transaction.id}`}
                      aria-label={`type-select-${transaction.id}`}
                      value={draft.transactionType}
                      onChange={(event) =>
                        handleDraftTypeChange(transaction, event.target.value as TransactionType)
                      }
                      className="w-[126px] rounded-md border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
                    >
                      {Object.values(TransactionType).map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <Select.Root
                      value={draft.category}
                      onValueChange={(value) => handleDraftCategoryChange(transaction, value)}
                    >
                      <Select.Trigger
                        className={`inline-flex w-[176px] items-center justify-between px-3 py-2 border rounded-md shadow-sm text-xs leading-4 font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 dark:focus:ring-offset-gray-800 ${
                          uncategorized
                            ? 'border-amber-300 bg-amber-100 text-amber-900 hover:bg-amber-200 focus:ring-amber-500 dark:border-amber-400/60 dark:bg-amber-500/20 dark:text-amber-100 dark:hover:bg-amber-500/30'
                            : 'border-gray-300 text-gray-700 bg-white hover:bg-gray-50 focus:ring-blue-500 dark:border-gray-600 dark:text-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600'
                        }`}
                      >
                        <Select.Value placeholder="Select category" />
                      </Select.Trigger>

                      <Select.Portal>
                        <Select.Content
                          aria-label={`category-select-${transaction.id}`}
                          className="overflow-hidden bg-white dark:bg-gray-800 rounded-md shadow-lg border dark:border-gray-700"
                        >
                          <Select.Viewport className="p-1">
                            {getCategoryOptionsForType(draft.transactionType).map((category) => (
                              <Select.Item
                                key={category}
                                value={category}
                                className="relative flex items-center px-8 py-2 text-xs text-gray-700 dark:text-gray-200 hover:bg-blue-500 hover:text-white rounded-md outline-none cursor-default"
                              >
                                <Select.ItemText>{category}</Select.ItemText>
                              </Select.Item>
                            ))}
                          </Select.Viewport>
                        </Select.Content>
                      </Select.Portal>
                    </Select.Root>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex min-w-[228px] items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setSelectedTransaction(transaction)}
                        className="inline-flex w-[88px] items-center justify-center gap-1 rounded-md border border-blue-500 px-2 py-1 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-50 dark:border-blue-400 dark:text-blue-300 dark:hover:bg-blue-950/40"
                      >
                        <SparklesIcon className="h-3.5 w-3.5" />
                        <span>Ask AI</span>
                      </button>
                      <button
                        type="button"
                        aria-label={`apply row ${transaction.id}`}
                        disabled={!rowDirty || !draft.category}
                        onClick={() => {
                          void handleApplyRow(transaction);
                        }}
                        className="inline-flex w-[88px] items-center justify-center rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700"
                      >
                        Apply
                      </button>
                      <button
                        onClick={() => onTransactionDelete(transaction.id)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-full p-2 text-red-600 transition-colors hover:bg-red-100 hover:text-red-900 dark:text-red-500 dark:hover:bg-red-900/30 dark:hover:text-red-400"
                      >
                        <TrashIcon className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={onPageChange}
      />
      <ClassificationAssistantModal
        open={selectedTransaction !== null}
        transaction={selectedTransaction}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setSelectedTransaction(null);
          }
        }}
        onSaved={handleAssistantSaved}
        getNextTransaction={getNextTransaction}
      />
    </div>
  );
}; 
