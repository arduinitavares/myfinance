import axios from 'axios';

import { API_BASE_URL } from '../config';
import { ClassificationProposal, ClassificationSession } from '../types/classification';

export const classificationService = {
  async createSession(transactionId: number): Promise<ClassificationSession> {
    const response = await axios.post(`${API_BASE_URL}/classification/sessions`, {
      transaction_id: transactionId,
    });
    return response.data;
  },

  async propose(sessionId: number): Promise<ClassificationProposal> {
    const response = await axios.post(
      `${API_BASE_URL}/classification/sessions/${sessionId}/propose`
    );
    return response.data;
  },

  async feedback(sessionId: number, payload: { feedback_tag: string; feedback_note: string | null }) {
    const response = await axios.post(
      `${API_BASE_URL}/classification/sessions/${sessionId}/feedback`,
      payload
    );
    return response.data;
  },

  async accept(sessionId: number, payload: Record<string, unknown>) {
    const response = await axios.post(
      `${API_BASE_URL}/classification/sessions/${sessionId}/accept`,
      payload
    );
    return response.data;
  },

  async previewSimilar(sessionId: number) {
    const response = await axios.post(
      `${API_BASE_URL}/classification/sessions/${sessionId}/similar-preview`
    );
    return response.data;
  },

  async applyBatch(sessionId: number, transactionIds: number[]) {
    const response = await axios.post(
      `${API_BASE_URL}/classification/sessions/${sessionId}/apply-batch`,
      { transaction_ids: transactionIds }
    );
    return response.data;
  },
};

