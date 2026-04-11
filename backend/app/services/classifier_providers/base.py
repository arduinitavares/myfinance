from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from ...models.transaction import Transaction


@dataclass(frozen=True)
class ClassificationProposal:
    transaction_type: str
    category: str
    confidence: float
    recurrence_frequency: str | None = None
    rationale: str | None = None
    follow_up_question: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class ProviderDescription:
    name: str
    model_name: str


class ClassifierProvider(ABC):
    def __init__(self, name: str, model_name: str):
        self.name = name
        self.model_name = model_name

    @property
    def description(self) -> ProviderDescription:
        return ProviderDescription(name=self.name, model_name=self.model_name)

    @abstractmethod
    def propose(
        self,
        *,
        transaction: Transaction,
        allowed_categories: Sequence[str],
        feedback_tag: str | None,
        feedback_note: str | None,
    ) -> ClassificationProposal:
        raise NotImplementedError
