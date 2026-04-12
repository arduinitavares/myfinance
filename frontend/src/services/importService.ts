import axios from 'axios';

import { API_BASE_URL } from '../config';
import { ImportReviewPayload, ImportSession } from '../types/import';

export const importService = {
  async uploadStatement(file: File): Promise<ImportSession> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`${API_BASE_URL}/imports/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  async getReview(sessionId: number): Promise<ImportReviewPayload> {
    const response = await axios.get(`${API_BASE_URL}/imports/${sessionId}`);
    return response.data;
  },

  async approve(sessionId: number): Promise<ImportSession> {
    const response = await axios.post(`${API_BASE_URL}/imports/${sessionId}/approve`);
    return response.data;
  },

  async reject(sessionId: number): Promise<ImportSession> {
    const response = await axios.post(`${API_BASE_URL}/imports/${sessionId}/reject`);
    return response.data;
  },

  async retry(sessionId: number): Promise<ImportSession> {
    const response = await axios.post(`${API_BASE_URL}/imports/${sessionId}/retry`);
    return response.data;
  },
};
