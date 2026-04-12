from .base import ClassificationProposal, ClassifierProvider


class StubClassifierProvider(ClassifierProvider):
    def propose(
        self,
        *,
        transaction,
        allowed_options_by_type,
        conversation_history,
        feedback_tag,
        feedback_note,
    ) -> ClassificationProposal:
        description = transaction.description.lower()
        if "proximus" in description:
            return ClassificationProposal(
                transaction_type="Expense",
                category="Utilities",
                confidence=0.91,
                recurrence_frequency="monthly",
                rationale="Proximus is typically a telecom utility billed on a monthly cycle.",
                prompt_tokens=32,
                completion_tokens=18,
            )

        allowed_categories = list(allowed_options_by_type.get(transaction.transaction_type.value, []))
        fallback_category = allowed_categories[0] if allowed_categories else transaction.transaction_type.value
        return ClassificationProposal(
            transaction_type=transaction.transaction_type.value,
            category=fallback_category,
            confidence=0.5,
            rationale="The fallback proposal mirrors the current transaction type until the user clarifies it.",
            follow_up_question="Is this an own account movement or money that should stay classified as a regular transaction?",
            prompt_tokens=20,
            completion_tokens=16,
        )
