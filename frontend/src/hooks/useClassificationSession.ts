import { useEffect, useState } from 'react';

import { classificationService } from '../services/classificationService';
import {
  ClassificationModalPhase,
  ClassificationProposal,
} from '../types/classification';

export const useClassificationSession = (open: boolean, transactionId?: number) => {
  const [phase, setPhase] = useState<ClassificationModalPhase>('idle');
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [proposal, setProposal] = useState<ClassificationProposal | null>(null);
  const [fallbackSuggestions, setFallbackSuggestions] = useState<
    Array<{ category: string; confidence: number }>
  >([]);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      if (!open || !transactionId) {
        setPhase('idle');
        setSessionId(null);
        setProposal(null);
        setFallbackSuggestions([]);
        return;
      }

      try {
        setPhase('generating_proposal');
        const session = await classificationService.createSession(transactionId);
        if (cancelled) return;
        setSessionId(session.id);

        const nextProposal = await classificationService.propose(session.id);
        if (cancelled) return;
        setProposal(nextProposal);
        setFallbackSuggestions([]);
        setPhase('waiting_for_feedback');
      } catch (error: any) {
        if (cancelled) return;
        const suggestions = error?.response?.data?.detail?.suggestions;
        if (Array.isArray(suggestions)) {
          setFallbackSuggestions(suggestions);
          setPhase('provider_unavailable_degraded');
          return;
        }
        setPhase('error');
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, [open, transactionId]);

  return {
    phase,
    sessionId,
    proposal,
    fallbackSuggestions,
    setPhase,
    setProposal,
  };
};

