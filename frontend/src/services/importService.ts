import { ImportBatchRun, ImportReviewPayload, ImportSession } from '../types/import';
import { apiClient } from './apiClient';

export const importService = {
  async uploadFile(file: File): Promise<ImportSession> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await apiClient.post('/imports/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  async getReview(sessionId: number): Promise<ImportReviewPayload> {
    const response = await apiClient.get(`/imports/${sessionId}`);
    return response.data;
  },

  async approve(sessionId: number): Promise<ImportSession> {
    const response = await apiClient.post(`/imports/${sessionId}/approve`);
    return response.data;
  },

  async reject(sessionId: number): Promise<ImportSession> {
    const response = await apiClient.post(`/imports/${sessionId}/reject`);
    return response.data;
  },

  async retry(sessionId: number): Promise<ImportSession> {
    const response = await apiClient.post(`/imports/${sessionId}/retry`);
    return response.data;
  },

  async startBatchFolderImport(): Promise<ImportBatchRun> {
    const response = await apiClient.post('/imports/batch-folder');
    return response.data;
  },

  async getBatchRun(batchId: number): Promise<ImportBatchRun> {
    const response = await apiClient.get(`/imports/batches/${batchId}`);
    return response.data;
  },

  async getLatestBatchRun(): Promise<ImportBatchRun> {
    const response = await apiClient.get('/imports/batches/latest');
    return response.data;
  },
};
