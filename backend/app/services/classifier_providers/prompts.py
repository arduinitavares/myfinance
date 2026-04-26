"""Prompt text and builders for classifier providers."""

from collections.abc import Mapping, Sequence

from ...models.classification import ClassificationTurn
from ...models.transaction import Transaction

PROMPT_FINGERPRINT: str = "classification-v2"

SYSTEM_PROMPT: str = """You classify personal finance transactions.
Return JSON only.
Pick exactly one transaction_type from the allowed types.
Pick exactly one category from the allowed categories.
Use Transfer only for own-account movements or clear internal transfers.
Descriptions containing WISSELKOSTEN indicate a currency-exchange fee.
Classify the fee transaction itself, not the related merchant purchase.
Prefer Financial Fees when that category is allowed.
Use recurrence_frequency only when the description strongly suggests a
recurring pattern.
Never invent unsupported categories.
Keep rationale to one short, user-facing sentence.
Ask a follow_up_question only when the category remains ambiguous after using
the available evidence.
"""


def build_user_prompt(
    *,
    transaction: Transaction,
    allowed_options_by_type: Mapping[str, Sequence[str]],
    conversation_history: Sequence[ClassificationTurn],
    feedback_tag: str | None,
    feedback_note: str | None,
) -> str:
    """Build the user prompt for a single classification request."""
    prior_turns = (
        "\n".join(
            (
                f"- proposal={turn.proposal_category} "
                f"type={turn.proposal_transaction_type} "
                f"feedback={turn.feedback_tag or 'none'} "
                f"note={turn.feedback_note or 'none'}"
            )
            for turn in conversation_history
        )
        or "none"
    )
    allowed_options = (
        "\n".join(
            f"- {transaction_type}: {', '.join(categories)}"
            for transaction_type, categories in allowed_options_by_type.items()
        )
        or "none"
    )

    return f"""Transaction:
- description: {transaction.description}
- amount: {transaction.amount}
- currency: {transaction.currency}
- source_bank: {transaction.source_bank}
- current_type: {transaction.transaction_type.value}

Allowed type/category options:
{allowed_options}

Prior turns:
{prior_turns}

Feedback tag: {feedback_tag or "none"}
Feedback note: {feedback_note or "none"}
"""
