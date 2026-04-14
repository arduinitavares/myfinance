from datetime import date

import pytest

from app.models.transaction import Transaction, TransactionType
from app.services.classifier_providers.openai_compatible import OpenAICompatibleClassifierProvider


class FakeCompletions:
    def create(self, **kwargs):
        class Usage:
            prompt_tokens = 111
            completion_tokens = 37

        class Message:
            content = (
                '{"transaction_type":"Expense","category":"Utilities","confidence":0.88,'
                '"recurrence_frequency":"monthly","rationale":"Telecom bill.",'
                '"follow_up_question":null}'
            )

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]
            usage = Usage()

        self.kwargs = kwargs
        return Response()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


def test_openai_compatible_provider_parses_json_and_exposes_usage():
    transaction = Transaction(
        id=1,
        account_number="BE10000000000001",
        transaction_date=date(2026, 4, 11),
        amount=-86.99,
        currency="EUR",
        description="PROXIMUS telecom invoice",
        transaction_type=TransactionType.EXPENSE,
        source_bank="belfius",
    )

    provider = OpenAICompatibleClassifierProvider(
        name="openai",
        model_name="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        client=FakeClient(),
    )

    proposal = provider.propose(
        transaction=transaction,
        allowed_options_by_type={
            "Expense": ["Utilities", "Housing", "Others"],
            "Transfer": ["Internal Transfer"],
        },
        conversation_history=[],
        feedback_tag=None,
        feedback_note=None,
    )

    assert proposal.category == "Utilities"
    assert proposal.transaction_type == "Expense"
    assert proposal.prompt_tokens == 111
    assert proposal.completion_tokens == 37


def test_openai_compatible_provider_prompt_calls_out_exchange_fee_descriptions():
    transaction = Transaction(
        id=2,
        account_number="BE10000000000001",
        transaction_date=date(2026, 1, 8),
        amount=-1.44,
        currency="EUR",
        description="WISSELKOSTEN - EBN*ADOBE CURITIBA BR",
        transaction_type=TransactionType.EXPENSE,
        source_bank="beobank",
    )

    client = FakeClient()
    provider = OpenAICompatibleClassifierProvider(
        name="openrouter",
        model_name="openai/gpt-4.1-mini",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        client=client,
    )

    with pytest.raises(RuntimeError):
        provider.propose(
            transaction=transaction,
            allowed_options_by_type={
                "Expense": ["Financial Fees", "Entertainment"],
            },
            conversation_history=[],
            feedback_tag=None,
            feedback_note=None,
        )

    assert (
        "Descriptions containing WISSELKOSTEN indicate a currency-exchange fee."
        in client.chat.completions.kwargs["messages"][0]["content"]
    )


def test_openai_compatible_provider_raises_runtime_error_on_invalid_json():
    class BrokenCompletions:
        def create(self, **kwargs):
            class Message:
                content = "not json"

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]
                usage = None

            return Response()

    class BrokenClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": BrokenCompletions()})()

    transaction = Transaction(
        id=1,
        account_number="BE10000000000001",
        transaction_date=date(2026, 4, 11),
        amount=-86.99,
        currency="EUR",
        description="PROXIMUS telecom invoice",
        transaction_type=TransactionType.EXPENSE,
        source_bank="belfius",
    )

    provider = OpenAICompatibleClassifierProvider(
        name="openai",
        model_name="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        client=BrokenClient(),
    )

    with pytest.raises(RuntimeError):
        provider.propose(
            transaction=transaction,
            allowed_options_by_type={
                "Expense": ["Utilities", "Housing", "Others"],
                "Transfer": ["Internal Transfer"],
            },
            conversation_history=[],
            feedback_tag=None,
            feedback_note=None,
        )


def test_openai_compatible_provider_defaults_missing_confidence_to_midpoint():
    class MissingConfidenceCompletions:
        def create(self, **kwargs):
            class Message:
                content = (
                    '{"transaction_type":"Expense","category":"Utilities",'
                    '"rationale":"Telecom bill.","follow_up_question":null}'
                )

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]
                usage = None

            return Response()

    class MissingConfidenceClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": MissingConfidenceCompletions()})()

    transaction = Transaction(
        id=1,
        account_number="BE10000000000001",
        transaction_date=date(2026, 4, 11),
        amount=-86.99,
        currency="EUR",
        description="PROXIMUS telecom invoice",
        transaction_type=TransactionType.EXPENSE,
        source_bank="belfius",
    )

    provider = OpenAICompatibleClassifierProvider(
        name="openrouter",
        model_name="openai/gpt-4.1-mini",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        client=MissingConfidenceClient(),
    )

    proposal = provider.propose(
        transaction=transaction,
        allowed_options_by_type={
            "Expense": ["Utilities", "Housing", "Others"],
            "Transfer": ["Internal Transfer"],
        },
        conversation_history=[],
        feedback_tag=None,
        feedback_note=None,
    )

    assert proposal.category == "Utilities"
    assert proposal.confidence == 0.5


def test_openai_compatible_provider_logs_prompt_response_and_sign_type_mismatch(caplog):
    class IncomeTransferCompletions:
        def create(self, **kwargs):
            class Message:
                content = (
                    '{"transaction_type":"Income","category":"Internal Transfer","confidence":0.5,'
                    '"rationale":"This is a payment towards a credit card bill.",'
                    '"follow_up_question":null}'
                )

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]
                usage = None

            return Response()

    class IncomeTransferClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": IncomeTransferCompletions()})()

    transaction = Transaction(
        id=7,
        account_number="BE10000000000001",
        transaction_date=date(2026, 3, 26),
        amount=-1850.48,
        currency="EUR",
        description="Overschrijving naar Mr ALEXANDRE ARDUINI TAVARES",
        transaction_type=TransactionType.TRANSFER,
        source_bank="belfius",
    )

    provider = OpenAICompatibleClassifierProvider(
        name="openrouter",
        model_name="openai/gpt-4.1-mini",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        client=IncomeTransferClient(),
    )

    with caplog.at_level("INFO", logger="app.services.classifier_providers.openai_compatible"):
        proposal = provider.propose(
            transaction=transaction,
            allowed_options_by_type={
                "Income": ["Internal Transfer"],
                "Transfer": ["Internal Transfer"],
            },
            conversation_history=[],
            feedback_tag="wrong_type",
            feedback_note="This is money leaving the account.",
        )

    assert proposal.transaction_type == "Income"
    assert "Classification provider request:" in caplog.text
    assert '"amount": -1850.48' in caplog.text
    assert '"feedback_tag": "wrong_type"' in caplog.text
    assert "Classification provider raw response:" in caplog.text
    assert '"allowed_options_by_type"' in caplog.text
    assert '"transaction_type": "Income"' in caplog.text or '\\"transaction_type\\":\\"Income\\"' in caplog.text
    assert "Classification provider sign/type mismatch:" in caplog.text


def test_openai_compatible_provider_rejects_response_outside_allowed_contract():
    class OutsideContractCompletions:
        def create(self, **kwargs):
            class Message:
                content = (
                    '{"transaction_type":"Payment","category":"Credit Card Payment","confidence":0.5,'
                    '"rationale":"This is a payment.","follow_up_question":null}'
                )

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]
                usage = None

            return Response()

    class OutsideContractClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": OutsideContractCompletions()})()

    transaction = Transaction(
        id=27,
        account_number="BE10000000000001",
        transaction_date=date(2026, 3, 26),
        amount=-2855.74,
        currency="EUR",
        description="Overschrijving naar Mr ALEXANDRE ARDUINI TAVARES",
        transaction_type=TransactionType.TRANSFER,
        source_bank="beobank",
    )

    provider = OpenAICompatibleClassifierProvider(
        name="openrouter",
        model_name="openai/gpt-4.1-mini",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        client=OutsideContractClient(),
    )

    with pytest.raises(RuntimeError):
        provider.propose(
            transaction=transaction,
            allowed_options_by_type={"Transfer": ["Internal Transfer"]},
            conversation_history=[],
            feedback_tag="wrong_category",
            feedback_note="This is how I pay for credit card bills.",
        )
