export interface ImportSession {
  id: number;
  file_name: string;
  mime_type: string;
  status: string;
  strategy_key: string | null;
  provider_hint: string | null;
  language_hint: string | null;
  charset_hint: string | null;
  extractor_id: string | null;
  raw_artifact_ref: string | null;
  error_stage: string | null;
  error_message: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
}

export interface ImportStatementDraft {
  id: number;
  attempt_number: number;
  statement_period_start: string | null;
  statement_period_end: string | null;
  transaction_count: number | null;
  account_number_hint: string | null;
  card_number_hint: string | null;
  currency: string | null;
  overall_confidence: number;
  review_status: string;
}

export interface ImportTransactionDraft {
  id: number;
  transaction_date: string | null;
  source_description: string;
  canonical_description_en: string | null;
  signed_amount: number;
  currency: string;
  debit_credit: string | null;
  source_locator: string;
  inferred_category: string | null;
  category_source: string | null;
  confidence: number | null;
  field_confidence: Record<string, number> | null;
  raw_fields: Record<string, unknown> | null;
  edit_source: string;
}

export interface ImportIssue {
  id: number;
  attempt_number: number;
  severity: string;
  blocking: boolean;
  issue_code: string;
  issue_message: string;
  transaction_ref: string | null;
}

export interface ImportEvidenceTextBlock {
  page_number: number;
  raw_text: string;
  lines: string[];
}

export interface ImportEvidence {
  text_blocks?: ImportEvidenceTextBlock[];
  ocr_blocks?: unknown[];
  snippets?: unknown[];
  [key: string]: unknown;
}

export interface ImportReviewPayload {
  session: ImportSession;
  statement: ImportStatementDraft | null;
  transactions: ImportTransactionDraft[];
  issues: ImportIssue[];
  evidence: ImportEvidence | null;
}
