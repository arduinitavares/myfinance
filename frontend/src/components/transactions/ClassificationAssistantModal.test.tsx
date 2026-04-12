import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { classificationService } from '../../services/classificationService';
import { ClassificationAssistantModal } from './ClassificationAssistantModal';

jest.mock('../../services/classificationService', () => ({
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

describe('ClassificationAssistantModal', () => {
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

  test('renders proposal rationale, recurrence, and retry controls', async () => {
    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          transaction_date: '2026-04-11',
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
          expense_category: 'Health',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    expect(await screen.findByText(/transaction under review/i)).toBeInTheDocument();
    expect(screen.getByText('SEPA PROXIMUS')).toBeInTheDocument();
    expect(screen.getByText('11/04/2026')).toBeInTheDocument();
    expect(screen.getByText(/-\€45\.99/)).toBeInTheDocument();
    expect(screen.getByText(/saved now · expense · health/i)).toBeInTheDocument();
    expect(await screen.findByText(/utilities/i)).toBeInTheDocument();
    expect(screen.getByText(/ai confidence/i)).toBeInTheDocument();
    expect(screen.getByText(/telecom or household bill/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText(/category/i)).toHaveValue('Utilities');
    });
    await waitFor(() => {
      expect(
        screen.getByRole('checkbox', { name: /create recurrence rule/i })
      ).toBeChecked();
    });
    expect(screen.getByDisplayValue('monthly')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /quarterly/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save & next/i })).toBeInTheDocument();
  });

  test('save and next closes the modal when there is no next row', async () => {
    const onOpenChange = jest.fn();

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={onOpenChange}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /save & next/i }));

    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  test('save and next hands off to the next transaction without closing the modal', async () => {
    const onOpenChange = jest.fn();
    const onSaved = jest.fn().mockResolvedValue(undefined);
    const nextTransaction = {
      id: 2,
      description: 'Next uncategorized row',
      amount: -12.0,
      currency: 'EUR',
      transaction_type: 'Expense',
    };

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={onOpenChange}
        onSaved={onSaved}
        getNextTransaction={() => nextTransaction as any}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /save & next/i }));

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(nextTransaction);
    });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  test('renders degraded fallback without rationale when the provider is unavailable', async () => {
    mockedService.propose.mockRejectedValueOnce({
      response: {
        data: {
          detail: {
            message: 'Classification provider unavailable',
            suggestions: [
              { category: 'Utilities', confidence: 0.77 },
              { category: 'Personal', confidence: 0.32 },
            ],
          },
        },
      },
    });

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 2,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    expect(await screen.findByText(/fallback suggestions/i)).toBeInTheDocument();
    expect(screen.getAllByText(/similarity/i)).toHaveLength(2);
    expect(screen.queryByText(/telecom or household bill/i)).not.toBeInTheDocument();
  });

  test('uses the selected category when saving', async () => {
    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.change(screen.getByLabelText(/category/i), {
      target: { value: 'Personal' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(mockedService.accept).toHaveBeenCalledWith(
        10,
        expect.objectContaining({
          category: 'Personal',
        })
      );
    });
  });

  test('preview similar shows the category being applied', async () => {
    mockedService.previewSimilar.mockResolvedValueOnce({
      session: {
        id: 10,
        transaction_id: 1,
        status: 'accepted',
      },
      seed_transaction_id: 1,
      matches: [
        {
          transaction_id: 7,
          description: 'Overschrijving naar OCTA+ ENERGIE SA',
          amount: -56.0,
          currency: 'EUR',
          score: 0.83,
        },
      ],
    } as never);

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(await screen.findByText(/apply category/i)).toBeInTheDocument();
    expect(screen.getByText(/utilities/i)).toBeInTheDocument();
  });

  test('retries with structured feedback and replaces the proposal', async () => {
    mockedService.feedback.mockResolvedValueOnce({
      id: 100,
      session_id: 10,
      turn_index: 1,
      transaction_type: 'Expense',
      category: 'Personal',
      confidence: 0.82,
      recurrence_frequency: null,
      rationale: 'This looks more like a personal subscription than a household utility.',
      follow_up_question: 'Is this a shared household bill or a personal service?',
      feedback_tag: 'wrong_category',
      feedback_note: 'This is a phone app subscription.',
      prompt_tokens: 12,
      completion_tokens: 25,
      created_at: '2026-04-11T12:02:00Z',
    } as never);

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /wrong category/i }));
    fireEvent.change(screen.getByPlaceholderText(/add context for the next try/i), {
      target: { value: 'This is a phone app subscription.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    expect(await screen.findByText(/^personal$/i)).toBeInTheDocument();
    expect(
      screen.getByText(/personal subscription than a household utility/i)
    ).toBeInTheDocument();
    expect(mockedService.feedback).toHaveBeenCalledWith(10, {
      feedback_tag: 'wrong_category',
      feedback_note: 'This is a phone app subscription.',
    });
  });

  test('requires confirmation before saving a type change', async () => {
    mockedService.propose.mockResolvedValueOnce({
      id: 101,
      session_id: 10,
      turn_index: 0,
      transaction_type: 'Transfer',
      category: 'Internal Transfer',
      confidence: 0.88,
      recurrence_frequency: null,
      rationale: 'The note looks like a movement between your own accounts.',
      follow_up_question: null,
      feedback_tag: null,
      feedback_note: null,
      prompt_tokens: 10,
      completion_tokens: 20,
      created_at: '2026-04-11T12:00:00Z',
    } as never);

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 3,
          description: 'Own account transfer',
          amount: -1000,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/internal transfer/i);
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(await screen.findByText(/confirm type change/i)).toBeInTheDocument();
    expect(mockedService.accept).not.toHaveBeenCalled();
  });

  test('shows apply-to-similar preview before a batch action', async () => {
    mockedService.previewSimilar.mockResolvedValueOnce({
      session: {
        id: 10,
        transaction_id: 1,
        status: 'accepted',
      },
      seed_transaction_id: 1,
      matches: [
        {
          transaction_id: 11,
          description: 'SEPA PROXIMUS APRIL',
          amount: -50.1,
          currency: 'EUR',
          score: 0.93,
        },
      ],
    } as never);

    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(await screen.findByText(/apply to similar/i)).toBeInTheDocument();
    expect(screen.getByText(/sepa proximus april/i)).toBeInTheDocument();
  });

  test('lets you turn off recurrence before saving', async () => {
    render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    const recurrenceCheckbox = screen.getByRole('checkbox', {
      name: /create recurrence rule/i,
    });
    await waitFor(() => {
      expect(recurrenceCheckbox).toBeChecked();
    });
    fireEvent.click(recurrenceCheckbox);
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(mockedService.accept).toHaveBeenCalledWith(10, {
      transaction_type: 'Expense',
      category: 'Utilities',
      classification_source: 'assistant',
      confirm_type_change: false,
      recurrence: {
        is_recurrent: false,
        frequency: null,
      },
    });
  });

  test('resets feedback state when a different transaction is loaded', async () => {
    const { rerender } = render(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 1,
          description: 'SEPA PROXIMUS',
          amount: -45.99,
          currency: 'EUR',
          transaction_type: 'Expense',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/utilities/i);
    fireEvent.click(screen.getByRole('button', { name: /wrong category/i }));
    fireEvent.change(screen.getByPlaceholderText(/add context for the next try/i), {
      target: { value: 'Old feedback should not leak.' },
    });

    mockedService.propose.mockResolvedValueOnce({
      id: 120,
      session_id: 10,
      turn_index: 0,
      transaction_type: 'Income',
      category: 'Salary',
      confidence: 0.95,
      recurrence_frequency: 'monthly',
      rationale: 'This reads like payroll income.',
      follow_up_question: null,
      feedback_tag: null,
      feedback_note: null,
      prompt_tokens: 8,
      completion_tokens: 16,
      created_at: '2026-04-11T12:03:00Z',
    } as never);

    rerender(
      <ClassificationAssistantModal
        open
        transaction={{
          id: 2,
          description: 'Payroll',
          amount: 2500,
          currency: 'EUR',
          transaction_type: 'Income',
        } as any}
        onOpenChange={() => {}}
        onSaved={async () => {}}
        getNextTransaction={() => null}
      />
    );

    await screen.findByText(/salary/i);
    expect(screen.getByPlaceholderText(/add context for the next try/i)).toHaveValue('');
    expect(screen.getByRole('button', { name: /^close$/i })).toHaveClass('bg-blue-600');
  });
});
