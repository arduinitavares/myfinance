import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { importService } from '../../services/importService';
import { ImportBatchResultsPage } from './ImportBatchResultsPage';

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    isAxiosError: () => false,
  },
}), { virtual: true });

const mockNavigate = jest.fn();
let mockBatchId = '42';

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({ batchId: mockBatchId }),
}), { virtual: true });

jest.mock('../../services/importService', () => ({
  importService: {
    getBatchRun: jest.fn(),
    getLatestBatchRun: jest.fn(),
  },
}));

const mockedImportService = importService as unknown as {
  getBatchRun: jest.Mock;
  getLatestBatchRun: jest.Mock;
};

const batchPayload = {
  id: 42,
  folder_path: '/bank_files',
  status: 'completed',
  message: 'Batch import completed.',
  total_files: 4,
  processed_count: 2,
  skipped_existing_count: 1,
  unsupported_count: 0,
  failed_count: 1,
  created_at: '2026-04-12T17:10:00Z',
  completed_at: '2026-04-12T17:11:00Z',
  items: [
    {
      id: 1,
      filename: 'alpha.pdf',
      file_hash: 'aaa',
      status: 'processed',
      message: null,
      session_id: 101,
      session_status: 'awaiting_review',
      existing_session_id: null,
      existing_session_status: null,
      strategy_key: 'pdf_statement',
      extractor_id: 'beobank_mastercard_pdf_v1',
      started_at: '2026-04-12T17:10:10Z',
      completed_at: '2026-04-12T17:10:20Z',
    },
    {
      id: 2,
      filename: 'beta.pdf',
      file_hash: 'bbb',
      status: 'skipped_existing',
      message: 'Import session with this file hash already exists.',
      session_id: null,
      session_status: null,
      existing_session_id: 88,
      existing_session_status: 'awaiting_review',
      strategy_key: null,
      extractor_id: null,
      started_at: '2026-04-12T17:10:21Z',
      completed_at: '2026-04-12T17:10:21Z',
    },
    {
      id: 3,
      filename: 'gamma.pdf',
      file_hash: 'ccc',
      status: 'failed',
      message: 'The PDF statement does not match a supported deterministic PDF layout',
      session_id: 77,
      session_status: 'failed',
      existing_session_id: null,
      existing_session_status: null,
      strategy_key: 'unknown',
      extractor_id: null,
      started_at: '2026-04-12T17:10:22Z',
      completed_at: '2026-04-12T17:10:25Z',
    },
    {
      id: 4,
      filename: 'delta.csv',
      file_hash: 'ddd',
      status: 'processed',
      message: null,
      session_id: 102,
      session_status: 'awaiting_review',
      existing_session_id: null,
      existing_session_status: null,
      strategy_key: 'beobank_csv',
      extractor_id: 'beobank_csv_v1',
      started_at: '2026-04-12T17:10:26Z',
      completed_at: '2026-04-12T17:10:26Z',
    },
  ],
};

describe('ImportBatchResultsPage', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    mockBatchId = '42';
    mockedImportService.getBatchRun.mockResolvedValue(batchPayload);
  });

  test('loads a persisted batch run from the route id and renders summary rows', async () => {
    render(<ImportBatchResultsPage />);

    expect(screen.getByText(/loading batch results/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(mockedImportService.getBatchRun).toHaveBeenCalledWith(42);
    });

    expect(await screen.findByRole('heading', { name: /import batch results/i })).toBeInTheDocument();
    expect(screen.getByText('/bank_files')).toBeInTheDocument();
    expect(screen.getByText(/batch import completed\./i)).toBeInTheDocument();
    expect(screen.getByText('alpha.pdf')).toBeInTheDocument();
    expect(screen.getByText('beta.pdf')).toBeInTheDocument();
    expect(screen.getByText('gamma.pdf')).toBeInTheDocument();
    expect(screen.getByText('delta.csv')).toBeInTheDocument();
    expect(screen.getAllByText('Draft extracted. Review and approve to import these transactions.').length).toBe(2);
    expect(
      screen.getByText(/some files are still drafts and will not appear in transactions until you review and approve them/i)
    ).toBeInTheDocument();
    expect(screen.getAllByText('Needs Approval').length).toBeGreaterThan(0);
  });

  test('offers row actions for new sessions, existing sessions, and failed sessions', async () => {
    render(<ImportBatchResultsPage />);

    const reviewButtons = await screen.findAllByRole('button', { name: /review & approve/i });
    fireEvent.click(reviewButtons[0]);
    expect(mockNavigate).toHaveBeenCalledWith('/imports/101/review');

    fireEvent.click(screen.getByRole('button', { name: /continue review/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/imports/88/review');

    fireEvent.click(screen.getByRole('button', { name: /^open$/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/imports/77/review');

    fireEvent.click(reviewButtons[1]);
    expect(mockNavigate).toHaveBeenCalledWith('/imports/102/review');
  });
});
