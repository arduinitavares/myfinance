"""Deterministic fallback classifier provider for tests and local development."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ClassificationProposal, ClassifierProvider

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ...models.classification import ClassificationTurn
    from ...models.transaction import Transaction


class StubClassifierProvider(ClassifierProvider):
    """Classifier provider that returns deterministic local proposals."""

    def propose(
        self,
        *,
        transaction: Transaction,
        allowed_options_by_type: Mapping[str, Sequence[str]],
        conversation_history: Sequence[ClassificationTurn],
        feedback_tag: str | None,
        feedback_note: str | None,
    ) -> ClassificationProposal:
        """Return a deterministic proposal for a transaction."""
        del conversation_history, feedback_tag, feedback_note

        description = transaction.description.lower()
        if "proximus" in description:
            return ClassificationProposal(
                transaction_type="Expense",
                category="Utilities",
                confidence=0.91,
                recurrence_frequency="monthly",
                rationale=(
                    "Proximus is typically a telecom utility billed on a "
                    "monthly cycle."
                ),
                prompt_tokens=32,
                completion_tokens=18,
            )

        allowed_categories = list(
            allowed_options_by_type.get(transaction.transaction_type.value, [])
        )
        fallback_category = (
            allowed_categories[0]
            if allowed_categories
            else transaction.transaction_type.value
        )
        return ClassificationProposal(
            transaction_type=transaction.transaction_type.value,
            category=fallback_category,
            confidence=0.5,
            rationale=(
                "The fallback proposal mirrors the current transaction type "
                "until the user clarifies it."
            ),
            follow_up_question=(
                "Is this an own account movement or money that should stay "
                "classified as a regular transaction?"
            ),
            prompt_tokens=20,
            completion_tokens=16,
        )
