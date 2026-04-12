import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { FileUpload } from './FileUpload';
import { importService } from '../services/importService';
import { transactionService } from '../services/transactionService';

let mockIsAxiosError = false;

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    isAxiosError: () => mockIsAxiosError,
  },
}), { virtual: true });

const mockNavigate = jest.fn();

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}), { virtual: true });

jest.mock('../services/importService', () => ({
  importService: {
    uploadStatement: jest.fn(),
    getReview: jest.fn(),
    approve: jest.fn(),
    reject: jest.fn(),
    retry: jest.fn(),
  },
}));

jest.mock('../services/transactionService', () => ({
  transactionService: {
    uploadCSV: jest.fn(),
  },
}));

jest.mock('@radix-ui/react-dialog', () => {
  const React = require('react') as typeof import('react');

  return {
    Root: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    Trigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Overlay: () => null,
    Content: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    Title: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
    Close: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  };
});

jest.mock('@radix-ui/react-progress', () => ({
  Root: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Indicator: () => <div />,
}));

jest.mock('@radix-ui/react-toast', () => ({
  Provider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Root: ({ children, open }: { children: React.ReactNode; open?: boolean }) => (open ? <div>{children}</div> : null),
  Title: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Description: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Viewport: () => null,
}));

const mockedImportService = importService as jest.Mocked<typeof importService>;
const mockedTransactionService = transactionService as jest.Mocked<typeof transactionService>;

describe('FileUpload', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    mockIsAxiosError = false;
  });

  test('uploads pdf statements through import service and navigates to review page', async () => {
    mockedImportService.uploadStatement.mockResolvedValue({
      id: 12,
      status: 'awaiting_review',
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' })],
      },
    });

    await waitFor(() => {
      expect(mockedImportService.uploadStatement).toHaveBeenCalledTimes(1);
    });
    expect(mockedImportService.uploadStatement).toHaveBeenCalledWith(expect.any(File));
    expect(mockedTransactionService.uploadCSV).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/imports/12/review');
    });
  });

  test('allows pdf uploads with application/octet-stream when the filename is .pdf', async () => {
    mockedImportService.uploadStatement.mockResolvedValue({
      id: 22,
      status: 'awaiting_review',
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/octet-stream' })],
      },
    });

    await waitFor(() => {
      expect(mockedImportService.uploadStatement).toHaveBeenCalledTimes(1);
    });
    expect(mockedTransactionService.uploadCSV).not.toHaveBeenCalled();
    expect(screen.queryByText(/unsupported file type/i)).not.toBeInTheDocument();
  });

  test('keeps csv uploads on the transaction import path', async () => {
    const onUploadSuccess = jest.fn();
    mockedTransactionService.uploadCSV.mockResolvedValue([] as never);

    render(<FileUpload onUploadSuccess={onUploadSuccess} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['date,description\n'], 'transactions.csv', { type: 'text/csv' })],
      },
    });

    await waitFor(() => {
      expect(mockedTransactionService.uploadCSV).toHaveBeenCalledTimes(1);
    });
    expect(mockedImportService.uploadStatement).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onUploadSuccess).toHaveBeenCalledTimes(1);
    });
  });

  test('shows pdf-specific upload errors for pdf failures', async () => {
    mockIsAxiosError = true;
    mockedImportService.uploadStatement.mockRejectedValue({
      response: {
        status: 415,
        data: {
          detail: 'Unsupported media type.',
        },
      },
    } as never);

    render(<FileUpload onUploadSuccess={jest.fn()} />);

    fireEvent.change(screen.getByLabelText(/upload transaction file/i), {
      target: {
        files: [new File(['%PDF-1.7'], 'statement.pdf', { type: 'application/pdf' })],
      },
    });

    expect(await screen.findByText(/please upload a pdf statement/i)).toBeInTheDocument();
    expect(screen.queryByText(/please upload a csv file/i)).not.toBeInTheDocument();
  });
});
