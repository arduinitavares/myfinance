# Application Warning Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the existing backend, frontend-test, and frontend-build warnings before the quality and database-safety implementation begins.

**Architecture:** Replace the one deprecated Qdrant collection-reset API with a small service-owned helper that preserves current in-memory behavior. Then update the React test adapter and browser-capability data, explicitly declare the Babel compatibility plugin that Create React App imports without declaring, settle the asynchronous tests that currently finish early, and give the chart test a deterministic JSDOM container. Production finance behavior remains unchanged.

**Tech Stack:** Python 3.13.12, qdrant-client 1.7-compatible API, pytest 8.3.5, React 18.3.1, Create React App 5.0.1, Jest 27, React Testing Library 14.3.1, Recharts 2.13, `@babel/plugin-proposal-private-property-in-object` 7.21.11

## Global Constraints

- Work only in `/Users/aaat/myfinance/.worktrees/quality-database-safety` on `dev/quality-database-safety`.
- Keep the application single-operator and local-first. Do not add hosted or multi-user behavior.
- Do not change Financial Health, Projection, Anomaly, advice, or route-optimization behavior.
- Do not change transaction, expense, transfer, income, liability, classification, or reporting semantics.
- Use the smallest focused failing warning check before each change.
- Do not add or change production frontend behavior for test-environment limitations.
- Do not raise the `qdrant-client>=1.7.0` dependency floor.
- Do not upgrade React, React DOM, Create React App, Recharts, Jest, or unrelated frontend dependencies.
- The only new frontend package allowed is the exact
  `@babel/plugin-proposal-private-property-in-object@7.21.11` development
  dependency that Create React App 5 explicitly asks consumers to declare.
- `npm ci` must exit successfully. Its third-party deprecation and audit notices are separate dependency-modernization work; do not run `npm audit fix`.
- Do not hide warnings with global console suppression, warning filters, `noqa`, `type: ignore`, `nosec`, disabled rules, or configuration rule skips.
- A test may capture an expected `console.error` only inside the error-path test that asserts the exact logged error, and it must restore the console afterward.
- Never read, copy, log, commit, or attach files under `bank_files/`, the live database, or backups.
- Do not stage or commit `.codegraph/`, frontend build output, audit reports, or `.superpowers/sdd/`.
- Every task ends with focused and full verification output free of application/test/build warnings and a small commit.

## Deferred Install Notices

The current locked frontend dependency tree prints transitive package
deprecation notices and npm audit findings during `npm ci`. This plan records
them as separate dependency-modernization work. They are not evidence of an
application, test, or build warning, and this plan must not rewrite the
dependency tree broadly to remove them.

---

### Task 1: Replace Deprecated Qdrant Collection Recreation

**Files:**

- Modify: `backend/app/services/category_suggestion_service.py:46-68`
- Modify: `backend/tests/services/test_category_suggestion_service.py`
- Modify: `backend/tests/services/test_ecb_exchange_rates.py:49-65`
- Modify: `backend/tests/test_classification_api.py:47-55`
- Modify: `backend/tests/test_manual_edit_updates_index.py:18-29`
- Modify: `backend/tests/test_upload_trust_order.py:49-57`

**Interfaces:**

- Consumes: the existing local `QdrantClient(":memory:")` and
  `models.VectorParams(size=384, distance=models.Distance.COSINE)` collection
  configuration.
- Produces:
  `CategorySuggestionService.reset_collection(*, collection_name: str) -> None`,
  which deletes and then creates one empty local collection.

- [ ] **Step 1: Write the failing reset-order test**

In `backend/tests/services/test_category_suggestion_service.py`, extend the
imports:

```python
from typing import cast

from qdrant_client import QdrantClient
from qdrant_client.http import models
```

Add this recording client and focused test before the similarity tests:

```python
class RecordingQdrantClient:
    """Record collection lifecycle calls without creating a vector store."""

    def __init__(self) -> None:
        """Initialize an empty call list."""
        self.calls: list[tuple[str, str, object | None]] = []

    def delete_collection(self, *, collection_name: str) -> bool:
        """Record collection deletion."""
        self.calls.append(("delete", collection_name, None))
        return True

    def create_collection(
        self,
        *,
        collection_name: str,
        vectors_config: object,
    ) -> bool:
        """Record collection creation."""
        self.calls.append(("create", collection_name, vectors_config))
        return True


def test_reset_collection_deletes_before_recreating_with_cosine_vectors() -> None:
    """Reset one collection with the service's canonical vector shape."""
    service = CategorySuggestionService.__new__(CategorySuggestionService)
    client = RecordingQdrantClient()
    service.client = cast(QdrantClient, client)

    service.reset_collection(collection_name="test_embeddings")

    assert len(client.calls) == 2
    assert client.calls[0] == ("delete", "test_embeddings", None)
    operation, collection_name, vectors_config = client.calls[1]
    assert operation == "create"
    assert collection_name == "test_embeddings"
    assert isinstance(vectors_config, models.VectorParams)
    assert vectors_config.size == 384
    assert vectors_config.distance == models.Distance.COSINE
```

- [ ] **Step 2: Run the test and verify RED**

Run from the worktree root:

```bash
PYTHONPATH=backend uv run --no-sync python -m pytest \
  backend/tests/services/test_category_suggestion_service.py::test_reset_collection_deletes_before_recreating_with_cosine_vectors \
  -q
```

Expected: FAIL with `AttributeError` because
`CategorySuggestionService.reset_collection` does not exist.

- [ ] **Step 3: Add the service-owned reset operation**

In `backend/app/services/category_suggestion_service.py`, replace both
`recreate_collection` calls in `__init__` with:

```python
        self.reset_collection(collection_name="expense_embeddings")
        self.reset_collection(collection_name="income_embeddings")
```

Add this method immediately after `__init__`:

```python
    def reset_collection(self, *, collection_name: str) -> None:
        """Delete and recreate one empty local embedding collection."""
        self.client.delete_collection(collection_name=collection_name)
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
            ),
        )
```

The project uses only local in-memory Qdrant here. Do not add remote-client
error handling or use `collection_exists`, which is not available at the
declared `qdrant-client>=1.7.0` floor.

- [ ] **Step 4: Update the fake-client contract and test reset helpers**

In `backend/tests/services/test_ecb_exchange_rates.py`, replace
`FakeQdrantClient.recreate_collection` with:

```python
    def delete_collection(self, *_args: object, **_kwargs: object) -> None:
        """Pretend to delete a vector collection."""
        return

    def create_collection(self, *_args: object, **_kwargs: object) -> None:
        """Pretend to create a vector collection."""
        return
```

In each of these files:

- `backend/tests/test_classification_api.py`
- `backend/tests/test_manual_edit_updates_index.py`
- `backend/tests/test_upload_trust_order.py`

replace the two direct client `recreate_collection(...)` calls in
`_clear_vector_collections` with:

```python
    category_suggestion_service.reset_collection(
        collection_name="expense_embeddings"
    )
    category_suggestion_service.reset_collection(
        collection_name="income_embeddings"
    )
```

Remove each now-unused `from qdrant_client.http import models` import.

- [ ] **Step 5: Verify GREEN with deprecations treated as errors**

Run:

```bash
PYTHONPATH=backend uv run --no-sync python -m pytest \
  -W error::DeprecationWarning \
  backend/tests/services/test_category_suggestion_service.py \
  backend/tests/services/test_ecb_exchange_rates.py \
  backend/tests/test_classification_api.py \
  backend/tests/test_manual_edit_updates_index.py \
  backend/tests/test_upload_trust_order.py \
  -q
```

Expected: all focused tests PASS with no warnings.

- [ ] **Step 6: Run the complete backend suite**

Run:

```bash
PYTHONPATH=backend uv run --no-sync python -m pytest \
  -W error::DeprecationWarning \
  backend/tests \
  -q
```

Expected: all backend tests PASS with no warnings.

- [ ] **Step 7: Commit the Qdrant warning cleanup**

```bash
git add \
  backend/app/services/category_suggestion_service.py \
  backend/tests/services/test_category_suggestion_service.py \
  backend/tests/services/test_ecb_exchange_rates.py \
  backend/tests/test_classification_api.py \
  backend/tests/test_manual_edit_updates_index.py \
  backend/tests/test_upload_trust_order.py
git commit -m "fix: replace deprecated qdrant collection reset"
```

---

### Task 2: Clean Frontend Test and Build Output

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/components/FileUpload.test.tsx`
- Modify: `frontend/src/components/dashboard/CategoryTrends.test.tsx`
- Modify: `frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`

**Interfaces:**

- Consumes: React 18.3.1, Create React App 5.0.1, the existing
  `npm run test:ci` and `npm run build` commands, and existing component
  behavior.
- Produces: React Testing Library 14.3.1 compatibility, current locked
  Browserslist capability data, the explicitly declared Create React App Babel
  compatibility plugin, fully settled async component tests, locally
  deterministic Recharts test dimensions, and quiet test/build logs.

- [ ] **Step 1: Capture the failing warning baseline**

From `frontend/`, run the test command into a temporary log and fail when the
known warning/noise patterns are present:

```bash
test_log="$(mktemp)"
npm run test:ci >"$test_log" 2>&1
test_exit=$?
if [ "$test_exit" -ne 0 ]; then
  sed -n '1,160p' "$test_log"
  exit "$test_exit"
fi
if rg -n \
  "ReactDOMTestUtils\\.act|not wrapped in act|width\\(0\\)|console\\.error|console\\.warn|failed to exit gracefully" \
  "$test_log"; then
  exit 1
fi
```

Expected: FAIL because the log contains the deprecated act adapter, unsettled
state updates, Recharts zero dimensions, expected-but-uncaptured error logging,
and/or the Jest worker exit warning.

Capture the build warning baseline:

```bash
build_log="$(mktemp)"
npm run build >"$build_log" 2>&1
build_exit=$?
if [ "$build_exit" -ne 0 ]; then
  sed -n '1,160p' "$build_log"
  exit "$build_exit"
fi
if rg -n \
  "Browserslist:|Compiled with warnings|babel-preset-react-app|plugin-proposal-private-property-in-object" \
  "$build_log"; then
  exit 1
fi
```

Expected: FAIL because the locked `caniuse-lite` data is stale. In a freshly
installed dependency tree, the cold build may also report that
`babel-preset-react-app` imports
`@babel/plugin-proposal-private-property-in-object` without declaring it.

- [ ] **Step 2: Update the test adapter, CRA compatibility declaration, and browser data**

From `frontend/`, run:

```bash
npm install --save @testing-library/react@14.3.1
npm install --save-dev @babel/plugin-proposal-private-property-in-object@7.21.11
npx update-browserslist-db@latest
```

This must update `frontend/package.json` to
`"@testing-library/react": "^14.3.1"`, add
`"@babel/plugin-proposal-private-property-in-object": "^7.21.11"` under
`devDependencies`, and refresh only the necessary lockfile entries. The Babel
proposal package is deprecated upstream, but Create React App 5 imports that
exact package name; migrating CRA/Babel is separate modernization work. Do not
run `npm audit fix` and do not upgrade unrelated packages.

- [ ] **Step 3: Make successful FileUpload tests await the terminal UI**

In `frontend/src/components/FileUpload.test.tsx`, add this assertion after the
existing final success assertion in each successful file-upload test:

```typescript
    await waitFor(() => {
      expect(screen.queryByText(/selected file:/i)).not.toBeInTheDocument();
    });
```

Apply it to:

- `uploads pdf statements through import service and navigates to review page`
- `allows pdf uploads with application/octet-stream when the filename is .pdf`
- `routes csv uploads into import review`

This waits for both `setSelectedFileName(null)` and the `finally` state update
instead of allowing the test to finish while React still has pending work.

- [ ] **Step 4: Capture and assert expected FileUpload error logging**

Add this helper above `describe('FileUpload', ...)`:

```typescript
const captureExpectedConsoleError = () =>
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
```

Add cleanup inside the suite:

```typescript
  afterEach(() => {
    jest.restoreAllMocks();
  });
```

In `shows pdf-specific upload errors for pdf failures`, use:

```typescript
    const consoleError = captureExpectedConsoleError();
    const uploadError = {
      response: {
        status: 415,
        data: {
          detail: 'Unsupported media type.',
        },
      },
    };
    mockedImportService.uploadFile.mockRejectedValue(uploadError as never);
```

In `keeps selected filename visible after a pdf upload error`, use:

```typescript
    const consoleError = captureExpectedConsoleError();
    const uploadError = new Error('network down');
    mockedImportService.uploadFile.mockRejectedValue(uploadError as never);
```

In `offers open existing when pdf upload returns a duplicate session conflict`,
use:

```typescript
    const consoleError = captureExpectedConsoleError();
    const uploadError = {
      response: {
        status: 409,
        data: {
          message: 'Import session with this file hash already exists.',
          file_hash: 'abc123',
          existing_session: {
            id: 14,
          },
        },
      },
    };
    mockedImportService.uploadFile.mockRejectedValue(uploadError as never);
```

Keep each test's existing render, interaction, and UI assertions. Append this
as the final assertion in all three tests:

```typescript
    expect(consoleError).toHaveBeenCalledWith(uploadError);
```

Do not add a global console mock. These tests must still prove that the expected
error is logged.

- [ ] **Step 5: Give the CategoryTrends test a local deterministic container**

In `frontend/src/components/dashboard/CategoryTrends.test.tsx`, add this mock
after the local mock functions and before the hook mocks:

```typescript
jest.mock('recharts', () => {
  const recharts = jest.requireActual('recharts');
  const react = require('react') as typeof import('react');

  return {
    ...recharts,
    ResponsiveContainer: ({
      children,
    }: {
      children: import('react').ReactNode;
    }) =>
      react.createElement(
        'div',
        { style: { width: 800, height: 400 } },
        children
      ),
  };
});
```

Keep the production `CategoryTrends` and all production Recharts components
unchanged. JSDOM has no layout engine; the limitation belongs in this one test.

- [ ] **Step 6: Await the terminal proposal state in modal context tests**

In
`frontend/src/components/transactions/ClassificationAssistantModal.test.tsx`,
add this final assertion to both context-only tests:

```typescript
    expect(await screen.findByText(/ai proposal/i)).toBeInTheDocument();
```

Apply it to:

- `renders exchange-fee transactions with the related merchant context`
- `shows unavailable FX context for unsupported currencies`

Those tests currently finish after their synchronous context appears while the
session/proposal effect is still updating four state values.

- [ ] **Step 7: Verify focused tests and the dependency contract**

Run:

```bash
npm ls \
  @testing-library/react \
  @babel/plugin-proposal-private-property-in-object \
  react \
  react-dom \
  --depth=0
npm run test:ci -- --runInBand \
  src/components/FileUpload.test.tsx \
  src/components/dashboard/CategoryTrends.test.tsx \
  src/components/transactions/ClassificationAssistantModal.test.tsx
```

Expected:

- React Testing Library resolves to `14.3.1`.
- The CRA compatibility plugin resolves to `7.21.11`.
- React and React DOM remain `18.3.1`.
- All focused tests PASS without warning or console noise.

- [ ] **Step 8: Verify the full test and build logs are clean**

Repeat the two warning-check commands from Step 1.

Expected:

- all 16 suites and 77 tests PASS;
- no deprecated act, unwrapped update, zero-dimension chart, uncaptured console,
  or forced-worker-exit output appears;
- the production build exits 0 with `Compiled successfully`;
- no Browserslist, CRA/Babel undeclared-dependency, or build warning appears,
  including on the first build after `npm ci`.

Then run:

```bash
npm run check:bundle
git diff --check
```

Expected: both commands PASS.

- [ ] **Step 9: Commit the frontend warning cleanup**

```bash
git add \
  frontend/package.json \
  frontend/package-lock.json \
  frontend/src/components/FileUpload.test.tsx \
  frontend/src/components/dashboard/CategoryTrends.test.tsx \
  frontend/src/components/transactions/ClassificationAssistantModal.test.tsx
git commit -m "test: clean frontend warning output"
```

---

## Plan Verification

After both tasks:

```bash
cd /Users/aaat/myfinance/.worktrees/quality-database-safety
PYTHONPATH=backend uv run --no-sync python -m pytest \
  -W error::DeprecationWarning \
  backend/tests \
  -q
cd frontend
npm run test:ci
npm run build
npm run check:bundle
cd ..
git diff --check
git status --short
```

Expected:

- backend tests pass with deprecations treated as errors and no warnings;
- frontend tests pass with no application/test warning or console noise;
- the frontend build and bundle check pass with no build warning;
- `npm ci` install notices remain documented as separate modernization work;
- only planned commits and ignored scratch artifacts exist;
- no private financial file or live database content appears in the diff.
