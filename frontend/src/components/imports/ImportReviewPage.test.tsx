import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { importService } from '../../services/importService';
import { ImportReviewPage } from './ImportReviewPage';

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    isAxiosError: () => false,
  },
}), { virtual: true });

const mockNavigate = jest.fn();
let mockSessionId = '12';

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({ sessionId: mockSessionId }),
}), { virtual: true });

jest.mock('../../services/importService', () => ({
  importService: {
    uploadStatement: jest.fn(),
    getReview: jest.fn(),
    approve: jest.fn(),
    reject: jest.fn(),
    retry: jest.fn(),
  },
}));

const mockedImportService = importService as jest.Mocked<typeof importService>;

const firstPayload = {
  session: {
    id: 12,
    file_name: 'statement.pdf',
    mime_type: 'application/pdf',
    status: 'awaiting_review',
    strategy_key: 'pdf_statement',
    provider_hint: 'beobank',
    language_hint: null,
    charset_hint: null,
    extractor_id: 'beobank_mastercard_pdf_v1',
    raw_artifact_ref: 'imports/12/attempts/1/evidence/raw.json',
    error_stage: null,
    error_message: null,
    attempt_count: 1,
    created_at: '2026-04-12T10:00:00Z',
    updated_at: '2026-04-12T10:00:00Z',
  },
  statement: {
    id: 40,
    attempt_number: 1,
    statement_period_start: '2025-12-15',
    statement_period_end: '2026-01-14',
    transaction_count: 1,
    account_number_hint: null,
    card_number_hint: 'xxxx xxxx xxxx 1111',
    currency: 'EUR',
    overall_confidence: 1,
    review_status: 'awaiting_review',
  },
  transactions: [
    {
      id: 1,
      transaction_date: '2025-12-15',
      source_description: 'DE TRAITEUR BV GENT BE',
      canonical_description_en: null,
      signed_amount: -14.2,
      currency: 'EUR',
      debit_credit: 'debit',
      source_locator: 'pdf:p2:l3',
      inferred_category: null,
      category_source: null,
      confidence: 1,
      field_confidence: {},
      raw_fields: {
        source_locator: 'pdf:p2:l3',
      },
      edit_source: 'deterministic_extracted',
    },
  ],
  issues: [
    {
      id: 8,
      attempt_number: 1,
      severity: 'warning',
      blocking: false,
      issue_code: 'warning_only',
      issue_message: 'Minor metadata gap',
      transaction_ref: 'pdf:p2:l3',
    },
  ],
  evidence: {
    text_blocks: [
      {
        page_number: 2,
        raw_text: 'Uw transacties\n15/12/2025 DE TRAITEUR BV GENT BE 14,20',
        lines: ['Uw transacties', '15/12/2025 DE TRAITEUR BV GENT BE 14,20'],
      },
    ],
  },
};

const secondPayload = {
  ...firstPayload,
  session: {
    ...firstPayload.session,
    attempt_count: 2,
    updated_at: '2026-04-12T10:05:00Z',
  },
  statement: {
    ...firstPayload.statement,
    attempt_number: 2,
  },
  transactions: [
    {
      ...firstPayload.transactions[0],
      id: 2,
      source_description: 'WISSELKOSTEN',
      source_locator: 'pdf:p2:l9',
      raw_fields: {
        source_locator: 'pdf:p2:l9',
      },
    },
  ],
};

const blockingPayload = {
  ...firstPayload,
  issues: [
    ...firstPayload.issues,
    {
      id: 9,
      attempt_number: 1,
      severity: 'error',
      blocking: true,
      issue_code: 'blocking_regression',
      issue_message: 'Blocking issue requires manual resolution before approval.',
      transaction_ref: 'pdf:p2:l3',
    },
  ],
};

const committedPayload = {
  ...firstPayload,
  session: {
    ...firstPayload.session,
    status: 'committed',
  },
  statement: {
    ...firstPayload.statement,
    review_status: 'approved',
  },
};

describe('ImportReviewPage', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    mockSessionId = '12';
    mockedImportService.getReview.mockResolvedValue(firstPayload as never);
  });

  test('renders issues and evidence on the import review page', async () => {
    render(<ImportReviewPage />);

    expect(
      await screen.findByText(/not imported yet\. these draft rows will only appear in transactions after you approve this import/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /approve & import 1 transaction/i })).toBeInTheDocument();
    expect(await screen.findByText(/minor metadata gap/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /evidence/i })).toBeInTheDocument();
    expect(screen.getByText('DE TRAITEUR BV GENT BE')).toBeInTheDocument();
    expect(screen.getByText('Uw transacties')).toBeInTheDocument();
    expect(screen.getByText('15/12/2025 DE TRAITEUR BV GENT BE 14,20')).toBeInTheDocument();
  });

  test('approve calls the service and navigates to transactions', async () => {
    mockedImportService.approve.mockResolvedValue({
      ...firstPayload.session,
      status: 'committed',
    } as never);

    render(<ImportReviewPage />);

    fireEvent.click(await screen.findByRole('button', { name: /approve & import 1 transaction/i }));

    await waitFor(() => {
      expect(mockedImportService.approve).toHaveBeenCalledWith(12);
    });
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/transactions');
    });
  });

  test('disables approve when the latest review payload contains a blocking issue', async () => {
    mockedImportService.getReview.mockResolvedValue(blockingPayload as never);

    render(<ImportReviewPage />);

    const approveButton = await screen.findByRole('button', { name: /approve & import 1 transaction/i });
    expect(approveButton).toBeDisabled();

    fireEvent.click(approveButton);

    expect(mockedImportService.approve).not.toHaveBeenCalled();
  });

  test('reject calls the service and navigates to transactions', async () => {
    mockedImportService.reject.mockResolvedValue({
      ...firstPayload.session,
      status: 'rejected',
    } as never);

    render(<ImportReviewPage />);

    fireEvent.click(await screen.findByRole('button', { name: /reject/i }));

    await waitFor(() => {
      expect(mockedImportService.reject).toHaveBeenCalledWith(12);
    });
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/transactions');
    });
  });

  test('retry calls the service and refreshes the latest review payload', async () => {
    mockedImportService.getReview
      .mockResolvedValueOnce(firstPayload as never)
      .mockResolvedValueOnce(secondPayload as never);
    mockedImportService.retry.mockResolvedValue({
      ...secondPayload.session,
      status: 'awaiting_review',
    } as never);

    render(<ImportReviewPage />);

    expect(await screen.findByText(/minor metadata gap/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => {
      expect(mockedImportService.retry).toHaveBeenCalledWith(12);
    });
    expect(await screen.findByText(/wisselkosten/i)).toBeInTheDocument();
    expect(mockedImportService.getReview).toHaveBeenCalledTimes(2);
  });

  test('disables retry when the session is not in a retryable state', async () => {
    mockedImportService.getReview.mockResolvedValue(committedPayload as never);

    render(<ImportReviewPage />);

    expect(await screen.findByRole('button', { name: /retry/i })).toBeDisabled();
    expect(mockedImportService.retry).not.toHaveBeenCalled();
  });
});
