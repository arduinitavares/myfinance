# Classification Real API Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stub-only classification assistant backend with a real OpenAI-compatible provider that can talk to OpenAI first, OpenRouter second, and fall back to local suggestions when the remote provider is unavailable.

**Architecture:** Keep the existing `ClassifierProvider` abstraction and add one `OpenAICompatibleClassifierProvider` that uses the OpenAI Python SDK with configurable `api_key` and `base_url`. Put the prompt and response schema in code, not YAML; use one provider class for both OpenAI and OpenRouter; pass prior turns into the provider so retries are genuinely conversational; keep `stub` as the last fallback so the UI still works during outages or local development.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, OpenAI Python SDK, sentence-transformers, Qdrant, React, TypeScript, Docker Compose.

---

## File Map

### Backend create

- `backend/app/services/classifier_providers/openai_compatible.py` — real provider implementation using the OpenAI Python SDK and OpenAI-compatible base URLs.
- `backend/app/services/classifier_providers/prompts.py` — system prompt, user-payload builder, and response model for classification.
- `backend/tests/test_openai_compatible_provider.py` — provider unit tests with a fake SDK client.

### Backend modify

- `backend/requirements.txt` — add the `openai` SDK.
- `backend/app/services/classifier_providers/__init__.py` — export the real provider.
- `backend/app/services/classifier_providers/base.py` — widen `ProviderDescription` for auditability and extend the provider contract to accept prior turns.
- `backend/app/services/classification_session_service.py` — instantiate the real provider from config, pass conversation history, and return degraded fallback suggestions on provider failure.
- `backend/app/imports/providers.py` — keep provider selection unchanged, but rely on `base_url` and `api_key_env` for OpenAI/OpenRouter.
- `backend/config.example.yaml` — document the recommended `classification_assistant` order.
- `backend/config.local.yaml` — local order after implementation: `openai`, `openrouter`, `stub`.
- `backend/tests/test_classifier_provider.py` — extend registry coverage for `openai` and `openrouter`.
- `backend/tests/test_classification_api.py` — add fallback and remote-provider acceptance coverage.

### Frontend modify

- `frontend/src/hooks/useClassificationSession.ts` — no API shape change expected, but keep the degraded fallback path covered if the backend returns suggestion payloads.
- `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx` — confirm degraded fallback still renders without rationale.

## Notes From Current Docs

- OpenAI Python currently supports constructing a client with `OpenAI(api_key=..., base_url=...)`.
- The current SDK docs show JSON/structured output patterns on chat-style endpoints.
- For this feature, use the OpenAI-compatible chat completions path as the common denominator across OpenAI and OpenRouter.
- Keep the degraded fallback contract as `503` with `detail.message` and `detail.suggestions`; the existing frontend hook already branches on that shape.
- Start with a stricter prompt than the stub needs, but treat prompt quality as iterative and refine it after manual evaluation runs.

This plan intentionally does **not** switch the assistant to the OpenAI Responses API yet. That can be a later upgrade once the dual-provider path is stable.
The backend `uv` migration is intentionally out of scope for this plan so packaging work cannot block provider integration; handle it in a separate PR if we still want it.

## Verification Commands

- Provider registry and provider unit tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py tests/test_openai_compatible_provider.py -q'`
- Classification API tests:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'`
- Full backend assistant slice:
  - `docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py tests/test_openai_compatible_provider.py tests/test_classification_api.py tests/test_upload_trust_order.py -q'`
- Frontend modal tests:
  - `cd frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx`

## Task 1: Add the SDK and lock the provider contract

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/services/classifier_providers/base.py`
- Modify: `backend/app/services/classifier_providers/__init__.py`
- Test: `backend/tests/test_classifier_provider.py`

- [ ] **Step 1: Write the failing provider-registry and description tests**

```python
# backend/tests/test_classifier_provider.py
def test_provider_registry_accepts_openai_and_openrouter_for_classification_assistant(tmp_path):
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        """
classification_assistant:
  order: [openai, openrouter, stub]
  fallback_on: []
  providers:
    openai:
      enabled: true
      kind: openai
      model: gpt-4o-mini
      base_url: https://api.openai.com/v1
      api_key_env: OPENAI_API_KEY
    openrouter:
      enabled: true
      kind: openai_compatible
      model: openai/gpt-4.1-mini
      base_url: https://openrouter.ai/api/v1
      api_key_env: OPENROUTER_API_KEY
    stub:
      enabled: true
      kind: stub
      model: stub-classifier-v1
""",
        encoding="utf-8",
    )

    registry = ProviderRegistry.from_path(config_path)
    report = registry.validate()

    assert report["classification_assistant"]["openai"]["available"] is False
    assert report["classification_assistant"]["openrouter"]["available"] is False
    assert report["classification_assistant"]["stub"]["available"] is True
    assert report["classification_assistant"]["__family__"]["selected_provider"] == "stub"


def test_provider_description_includes_base_url_and_prompt_fingerprint():
    description = ProviderDescription(
        name="openai",
        model_name="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        prompt_fingerprint="classification-v1",
    )

    assert description.base_url == "https://api.openai.com/v1"
    assert description.prompt_fingerprint == "classification-v1"
```

- [ ] **Step 2: Run the test to verify it fails for the new description fields**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py -q'
```

Expected:

```text
E   TypeError: ProviderDescription.__init__() got an unexpected keyword argument 'base_url'
```

- [ ] **Step 3: Add the SDK dependency and widen the provider contract**

```text
# backend/requirements.txt
openai>=2.0.0
```

```python
# backend/app/services/classifier_providers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

from ...models.classification import ClassificationTurn

@dataclass(frozen=True)
class ProviderDescription:
    name: str
    model_name: str
    base_url: str | None = None
    prompt_fingerprint: str | None = None


class ClassifierProvider(ABC):
    @abstractmethod
    def propose(
        self,
        *,
        transaction,
        allowed_categories,
        conversation_history: Sequence[ClassificationTurn],
        feedback_tag,
        feedback_note,
    ):
        raise NotImplementedError
```

```python
# backend/app/services/classifier_providers/__init__.py
from .openai_compatible import OpenAICompatibleClassifierProvider
from .base import ClassificationProposal, ClassifierProvider, ProviderDescription
from .stub import StubClassifierProvider

__all__ = [
    "ClassificationProposal",
    "ClassifierProvider",
    "ProviderDescription",
    "OpenAICompatibleClassifierProvider",
    "StubClassifierProvider",
]
```

- [ ] **Step 4: Run the focused provider tests to verify they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py -q'
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt \
  backend/app/services/classifier_providers/base.py \
  backend/app/services/classifier_providers/__init__.py \
  backend/tests/test_classifier_provider.py
git commit -m "feat: prepare classification provider contract for remote APIs"
```

## Task 2: Build the OpenAI-compatible provider and prompt module

**Files:**
- Create: `backend/app/services/classifier_providers/prompts.py`
- Create: `backend/app/services/classifier_providers/openai_compatible.py`
- Test: `backend/tests/test_openai_compatible_provider.py`

- [ ] **Step 1: Write the failing provider test with a fake SDK client**

```python
# backend/tests/test_openai_compatible_provider.py
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
        allowed_categories=["Utilities", "Housing", "Others"],
        conversation_history=[],
        feedback_tag=None,
        feedback_note=None,
    )

    assert proposal.category == "Utilities"
    assert proposal.transaction_type == "Expense"
    assert proposal.prompt_tokens == 111
    assert proposal.completion_tokens == 37


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
            allowed_categories=["Utilities", "Housing", "Others"],
            conversation_history=[],
            feedback_tag=None,
            feedback_note=None,
        )
```

- [ ] **Step 2: Run the new provider test to verify it fails**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_openai_compatible_provider.py -q'
```

Expected:

```text
E   ModuleNotFoundError: No module named 'app.services.classifier_providers.openai_compatible'
```

- [ ] **Step 3: Implement the prompt module and provider**

```python
# backend/app/services/classifier_providers/prompts.py
from pydantic import BaseModel


PROMPT_FINGERPRINT = "classification-v1"


class ClassificationLLMResponse(BaseModel):
    transaction_type: str
    category: str
    confidence: float
    recurrence_frequency: str | None = None
    rationale: str | None = None
    follow_up_question: str | None = None


SYSTEM_PROMPT = """You classify personal finance transactions.
Return JSON only.
Pick exactly one transaction_type from the allowed types.
Pick exactly one category from the allowed categories.
Use Transfer only for own-account movements or clear internal transfers.
Use recurrence_frequency only when the description strongly suggests a recurring pattern.
Never invent unsupported categories.
Keep rationale to one short, user-facing sentence.
Ask a follow_up_question only when the category remains ambiguous after using the available evidence.
"""


def build_user_prompt(*, transaction, allowed_categories, conversation_history, feedback_tag, feedback_note) -> str:
    prior_turns = "\\n".join(
        f"- proposal={turn.proposal_category} type={turn.proposal_transaction_type} feedback={turn.feedback_tag or 'none'} note={turn.feedback_note or 'none'}"
        for turn in conversation_history
    ) or "none"
    return f\"\"\"Transaction:
- description: {transaction.description}
- amount: {transaction.amount}
- currency: {transaction.currency}
- source_bank: {transaction.source_bank}
- current_type: {transaction.transaction_type.value}

Allowed categories:
{", ".join(allowed_categories)}

Prior turns:
{prior_turns}

Feedback tag: {feedback_tag or "none"}
Feedback note: {feedback_note or "none"}
\"\"\"
```

```python
# backend/app/services/classifier_providers/openai_compatible.py
import json

from openai import OpenAI
from pydantic import ValidationError

from .base import ClassificationProposal, ClassifierProvider, ProviderDescription
from .prompts import (
    PROMPT_FINGERPRINT,
    ClassificationLLMResponse,
    SYSTEM_PROMPT,
    build_user_prompt,
)


class OpenAICompatibleClassifierProvider(ClassifierProvider):
    def __init__(self, *, name: str, model_name: str, api_key: str, base_url: str, client=None):
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

    def propose(self, *, transaction, allowed_categories, conversation_history, feedback_tag, feedback_note):
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(
                        transaction=transaction,
                        allowed_categories=allowed_categories,
                        conversation_history=conversation_history,
                        feedback_tag=feedback_tag,
                        feedback_note=feedback_note,
                    ),
                },
            ],
        )
        try:
            payload = json.loads(response.choices[0].message.content)
            parsed = ClassificationLLMResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError("invalid classification provider response") from exc
        usage = getattr(response, "usage", None)
        return ClassificationProposal(
            transaction_type=parsed.transaction_type,
            category=parsed.category,
            confidence=parsed.confidence,
            recurrence_frequency=parsed.recurrence_frequency,
            rationale=parsed.rationale,
            follow_up_question=parsed.follow_up_question,
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
        )
```

- [ ] **Step 4: Run the provider tests to verify they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_openai_compatible_provider.py tests/test_classifier_provider.py -q'
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/classifier_providers/prompts.py \
  backend/app/services/classifier_providers/openai_compatible.py \
  backend/app/services/classifier_providers/__init__.py \
  backend/tests/test_openai_compatible_provider.py
git commit -m "feat: add openai-compatible classification provider"
```

## Task 3: Wire provider selection and degraded fallback into the session service

**Files:**
- Modify: `backend/app/services/classification_session_service.py`
- Modify: `backend/tests/test_classification_api.py`

- [ ] **Step 1: Write the failing API test for degraded fallback**

```python
# backend/tests/test_classification_api.py
def test_propose_returns_degraded_suggestions_when_remote_provider_fails(client, monkeypatch, seeded_expense_transaction):
    class ExplodingProvider:
        def propose(self, **kwargs):
            raise RuntimeError("provider boom")

    monkeypatch.setattr(
        ClassificationSessionService,
        "_build_provider",
        classmethod(lambda cls, provider_name=None, model_name=None: ExplodingProvider()),
    )

    session_response = client.post("/classification/sessions", json={"transaction_id": seeded_expense_transaction.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/classification/sessions/{session_id}/propose")

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "Classification provider unavailable"
    assert "suggestions" in response.json()["detail"]
```

- [ ] **Step 2: Run the API test to verify it fails**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'
```

Expected:

```text
E   AssertionError: assert 'No classification assistant provider configured' == 'Classification provider unavailable'
```

- [ ] **Step 3: Update provider construction and fallback behavior**

```python
# backend/app/services/classification_session_service.py
from openai import APIError, APIConnectionError, APITimeoutError, RateLimitError

from ..services.classifier_providers import (
    OpenAICompatibleClassifierProvider,
    StubClassifierProvider,
)

REMOTE_PROVIDER_ERRORS = (RuntimeError, APIError, APIConnectionError, APITimeoutError, RateLimitError)

@classmethod
def _build_provider(cls, provider_name: str | None = None, model_name: str | None = None):
    resolved_provider_name, resolved_model_name = cls._resolve_provider_selection(
        provider_name=provider_name,
        model_name=model_name,
    )
    registry = ProviderRegistry.from_path(settings.provider_config_path)
    provider_config = registry.family("classification_assistant").providers[resolved_provider_name]

    if resolved_provider_name == "stub":
        return StubClassifierProvider(name=resolved_provider_name, model_name=resolved_model_name)

    if provider_config.kind in {"openai", "openai_compatible"}:
        api_key = os.environ[provider_config.api_key_env]
        return OpenAICompatibleClassifierProvider(
            name=resolved_provider_name,
            model_name=resolved_model_name,
            api_key=api_key,
            base_url=provider_config.base_url or "https://api.openai.com/v1",
        )

    raise HTTPException(status_code=503, detail="Unsupported classification provider configured")

@classmethod
def _propose_with_fallback(
    cls,
    *,
    db: Session,
    transaction: Transaction,
    session: ClassificationSession,
    feedback_tag: str | None,
    feedback_note: str | None,
):
    provider = cls._build_provider(session.provider_name, session.model_name)
    try:
        return provider.propose(
            transaction=transaction,
            allowed_categories=cls._allowed_categories(transaction.transaction_type),
            conversation_history=cls._conversation_history(db, session.id),
            feedback_tag=feedback_tag,
            feedback_note=feedback_note,
        )
    except REMOTE_PROVIDER_ERRORS:
        fallback = cls._fallback_suggestions(transaction)
        raise HTTPException(
            status_code=503,
            detail={"message": "Classification provider unavailable", "suggestions": fallback},
        )

@classmethod
def propose(cls, db: Session, session_id: int) -> ClassificationProposalResponse:
    session = cls._require_open_session(db, session_id)
    transaction = cls._require_transaction(db, session.transaction_id)
    proposal = cls._propose_with_fallback(
        db=db,
        transaction=transaction,
        session=session,
        feedback_tag=None,
        feedback_note=None,
    )

@classmethod
def record_feedback(cls, db: Session, session_id: int, request: SubmitFeedbackRequest):
    session = cls._require_open_session(db, session_id)
    transaction = cls._require_transaction(db, session.transaction_id)
    proposal = cls._propose_with_fallback(
        db=db,
        transaction=transaction,
        session=session,
        feedback_tag=request.feedback_tag,
        feedback_note=request.feedback_note,
    )
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run:

```bash
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classification_api.py -q'
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/classification_session_service.py \
  backend/tests/test_classification_api.py
git commit -m "feat: wire remote classification provider with degraded fallback"
```

## Task 4: Turn on the real provider chain in config and verify the end-to-end path

**Files:**
- Modify: `backend/config.example.yaml`
- Modify: `backend/config.local.yaml`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`

- [ ] **Step 1: Write the failing frontend degraded-fallback assertion**

```tsx
// frontend/src/components/transactions/ClassificationAssistantModal.test.tsx
test('renders degraded fallback suggestions without rationale text', async () => {
  mockedCreateSession.mockResolvedValue({ id: 123, transaction_id: 99, status: 'open' });
  mockedPropose.mockRejectedValue({
    response: {
      data: {
        detail: {
          message: 'Classification provider unavailable',
          suggestions: [{ category: 'Utilities', confidence: 0.61 }],
        },
      },
    },
  });

  renderModal();

  expect(await screen.findByText('Fallback suggestions')).toBeInTheDocument();
  expect(screen.queryByText(/Telecom bill/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend modal test to verify it fails if the fallback path regressed**

Run:

```bash
cd frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

```text
FAIL when fallback suggestions are not rendered
```

- [ ] **Step 3: Update example config and local-only runtime config to prefer real providers**

```yaml
# backend/config.example.yaml
classification_assistant:
  order: [openai, openrouter, stub]
  fallback_on: []
  providers:
    openai:
      enabled: false
      kind: openai
      model: gpt-4o-mini
      base_url: https://api.openai.com/v1
      api_key_env: OPENAI_API_KEY
    openrouter:
      enabled: false
      kind: openai_compatible
      model: openai/gpt-4.1-mini
      base_url: https://openrouter.ai/api/v1
      api_key_env: OPENROUTER_API_KEY
    stub:
      enabled: true
      kind: stub
      model: stub-classifier-v1
```

```yaml
# backend/config.local.yaml
classification_assistant:
  order: [openai, openrouter, stub]
  fallback_on: []
  providers:
    openai:
      enabled: true
      kind: openai
      model: gpt-4o-mini
      base_url: https://api.openai.com/v1
      api_key_env: OPENAI_API_KEY
      timeout_seconds: 30
      max_retries: 2
      supports_json_schema: true
      requires_confirmation: true
    openrouter:
      enabled: true
      kind: openai_compatible
      model: openai/gpt-4.1-mini
      base_url: https://openrouter.ai/api/v1
      api_key_env: OPENROUTER_API_KEY
      timeout_seconds: 30
      max_retries: 2
      supports_json_schema: true
      requires_confirmation: true
    stub:
      enabled: true
      kind: stub
      model: stub-classifier-v1
```

Do not commit `backend/config.local.yaml`; it remains gitignored and local-only.

- [ ] **Step 4: Run backend and frontend verification**

Run:

```bash
docker compose up --build -d
docker compose exec -T backend sh -lc 'cd /app && PYTHONPATH=. pytest tests/test_classifier_provider.py tests/test_openai_compatible_provider.py tests/test_classification_api.py -q'
cd frontend && CI=true npm test -- --runInBand --watch=false src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

```text
backend tests pass
frontend test passes
```

- [ ] **Step 5: Manual smoke test**

Run:

```bash
docker compose logs -f backend
```

Expected:

```text
POST /classification/sessions/.../propose 200 OK
```

Then:

- open the transactions table
- click `Ask AI` on an uncategorized transaction
- confirm the modal shows a real rationale rather than the stub fallback
- temporarily disable `openai` in `backend/config.local.yaml` and retry
- confirm the app falls back to `openrouter`, then to `stub` if both are disabled

- [ ] **Step 6: Commit**

```bash
git add backend/config.example.yaml \
  frontend/src/components/transactions/ClassificationAssistantModal.test.tsx
git commit -m "chore: enable real classification provider chain"
```

## Self-Review

- Spec coverage: this plan covers the missing real-provider slice without reopening the accepted assistant design.
- Placeholder scan: no `TODO` markers or hand-wavy “wire later” steps remain.
- Type consistency: the provider remains `propose(...) -> ClassificationProposal`, but now accepts `conversation_history` so retry turns can actually influence the model output.
