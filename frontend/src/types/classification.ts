export type ClassificationFeedbackTag =
  | 'wrong_category'
  | 'wrong_type'
  | 'close'
  | 'missing_context'
  | 'explain_reasoning'
  | 'accept';

export type ClassificationModalPhase =
  | 'idle'
  | 'generating_proposal'
  | 'waiting_for_feedback'
  | 'retrying_with_feedback'
  | 'confirm_type_change'
  | 'preview_similar'
  | 'saving'
  | 'complete_no_more_uncategorized'
  | 'provider_unavailable_degraded'
  | 'error';

export interface ClassificationSession {
  id: number;
  transaction_id: number;
  status: string;
}

export interface ClassificationProposal {
  id: number;
  session_id: number;
  turn_index: number;
  transaction_type: string;
  category: string;
  confidence: number;
  recurrence_frequency: string | null;
  rationale: string | null;
  follow_up_question: string | null;
  feedback_tag: string | null;
  feedback_note: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  created_at: string;
}

