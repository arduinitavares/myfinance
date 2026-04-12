import json
import logging
from typing import Mapping, Sequence

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from ...models.classification import ClassificationTurn
from ...models.transaction import Transaction
from .base import ClassificationProposal, ClassifierProvider, ProviderDescription
from .prompts import PROMPT_FINGERPRINT, SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class ClassificationLLMResponse(BaseModel):
    transaction_type: str
    category: str
    confidence: float | None = None
    recurrence_frequency: str | None = None
    rationale: str | None = None
    follow_up_question: str | None = None


class OpenAICompatibleClassifierProvider(ClassifierProvider):
    def __init__(
        self,
        *,
        name: str,
        model_name: str,
        api_key: str,
        base_url: str,
        client=None,
    ):
        super().__init__(name=name, model_name=model_name)
        self.base_url = base_url
        self.client = client or OpenAI(api_key=api_key, base_url=base_url)

    @property
    def description(self) -> ProviderDescription:
        return ProviderDescription(
            name=self.name,
            model_name=self.model_name,
            base_url=self.base_url,
            prompt_fingerprint=PROMPT_FINGERPRINT,
        )

    def propose(
        self,
        *,
        transaction: Transaction,
        allowed_options_by_type: Mapping[str, Sequence[str]],
        conversation_history: Sequence[ClassificationTurn],
        feedback_tag: str | None,
        feedback_note: str | None,
    ) -> ClassificationProposal:
        user_prompt = build_user_prompt(
            transaction=transaction,
            allowed_options_by_type=allowed_options_by_type,
            conversation_history=conversation_history,
            feedback_tag=feedback_tag,
            feedback_note=feedback_note,
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            "Classification provider request: %s",
            json.dumps(
                {
                    "provider": self.name,
                    "model": self.model_name,
                    "transaction_id": transaction.id,
                    "description": transaction.description,
                    "amount": transaction.amount,
                    "currency": transaction.currency,
                    "current_type": transaction.transaction_type.value,
                    "source_bank": transaction.source_bank,
                    "allowed_options_by_type": {
                        transaction_type: list(categories)
                        for transaction_type, categories in allowed_options_by_type.items()
                    },
                    "feedback_tag": feedback_tag,
                    "feedback_note": feedback_note,
                    "conversation_turns": len(conversation_history),
                    "messages": messages,
                },
                ensure_ascii=False,
            ),
        )

        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            response_format={"type": "json_object"},
            messages=messages,
        )
        raw_content = response.choices[0].message.content
        logger.info(
            "Classification provider raw response: %s",
            json.dumps(
                {
                    "provider": self.name,
                    "model": self.model_name,
                    "transaction_id": transaction.id,
                    "content": raw_content,
                },
                ensure_ascii=False,
            ),
        )
        try:
            payload = json.loads(raw_content)
            parsed = ClassificationLLMResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "Classification provider response parse failed: %s",
                json.dumps(
                    {
                        "provider": self.name,
                        "model": self.model_name,
                        "transaction_id": transaction.id,
                        "content": raw_content,
                    },
                    ensure_ascii=False,
                ),
                exc_info=exc,
            )
            raise RuntimeError("invalid classification provider response") from exc

        allowed_transaction_types = set(allowed_options_by_type.keys())
        if parsed.transaction_type not in allowed_transaction_types:
            logger.warning(
                "Classification provider response outside allowed contract: %s",
                json.dumps(
                    {
                        "transaction_id": transaction.id,
                        "description": transaction.description,
                        "amount": transaction.amount,
                        "allowed_options_by_type": {
                            transaction_type: list(categories)
                            for transaction_type, categories in allowed_options_by_type.items()
                        },
                        "proposed_type": parsed.transaction_type,
                        "proposed_category": parsed.category,
                    },
                    ensure_ascii=False,
                ),
            )
            raise RuntimeError("classification provider response outside allowed contract")

        allowed_categories = set(allowed_options_by_type[parsed.transaction_type])
        if parsed.category not in allowed_categories:
            logger.warning(
                "Classification provider response outside allowed contract: %s",
                json.dumps(
                    {
                        "transaction_id": transaction.id,
                        "description": transaction.description,
                        "amount": transaction.amount,
                        "allowed_options_by_type": {
                            transaction_type: list(categories)
                            for transaction_type, categories in allowed_options_by_type.items()
                        },
                        "proposed_type": parsed.transaction_type,
                        "proposed_category": parsed.category,
                    },
                    ensure_ascii=False,
                ),
            )
            raise RuntimeError("classification provider response outside allowed contract")

        logger.info(
            "Classification provider parsed proposal: %s",
            json.dumps(
                {
                    "provider": self.name,
                    "model": self.model_name,
                    "transaction_id": transaction.id,
                    "transaction_type": parsed.transaction_type,
                    "category": parsed.category,
                    "confidence": parsed.confidence,
                    "recurrence_frequency": parsed.recurrence_frequency,
                },
                ensure_ascii=False,
            ),
        )
        if (
            (transaction.amount < 0 and parsed.transaction_type == "Income")
            or (transaction.amount > 0 and parsed.transaction_type == "Expense")
        ):
            logger.warning(
                "Classification provider sign/type mismatch: %s",
                json.dumps(
                    {
                        "transaction_id": transaction.id,
                        "description": transaction.description,
                        "amount": transaction.amount,
                        "current_type": transaction.transaction_type.value,
                        "proposed_type": parsed.transaction_type,
                        "proposed_category": parsed.category,
                    },
                    ensure_ascii=False,
                ),
            )

        usage = getattr(response, "usage", None)
        return ClassificationProposal(
            transaction_type=parsed.transaction_type,
            category=parsed.category,
            confidence=parsed.confidence if parsed.confidence is not None else 0.5,
            recurrence_frequency=parsed.recurrence_frequency,
            rationale=parsed.rationale,
            follow_up_question=parsed.follow_up_question,
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
        )
