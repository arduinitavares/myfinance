"""Module for backend tests services test_category_suggestion_service."""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
from app.services.category_suggestion_service import CategorySuggestionService
from qdrant_client import QdrantClient
from qdrant_client.http import models


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


def test_similarity_scores_returns_empty_list_for_no_candidates() -> None:
    """Verify similarity scores returns empty list for no candidates."""
    service = CategorySuggestionService.__new__(CategorySuggestionService)

    assert service.similarity_scores("seed merchant", []) == []


def test_similarity_scores_batches_candidates_in_input_order() -> None:
    """Verify similarity scores batches candidates in input order."""
    service = CategorySuggestionService.__new__(CategorySuggestionService)
    service._preprocess_description = lambda text: text

    encode_calls: list[tuple[list[str], bool]] = []
    vectors = {
        "seed merchant": np.array([1.0, 0.0]),
        "same merchant": np.array([1.0, 0.0]),
        "other merchant": np.array([0.0, 1.0]),
    }

    def fake_encode(
        texts: Sequence[str],
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        encode_calls.append((list(texts), show_progress_bar))
        return np.array([vectors[text] for text in texts])

    service.model = SimpleNamespace(encode=fake_encode)

    scores = service.similarity_scores(
        "seed merchant",
        ["same merchant", "other merchant"],
    )

    assert encode_calls == [
        (["seed merchant", "same merchant", "other merchant"], False)
    ]
    assert scores == [1.0, 0.0]


def test_similarity_scores_skips_empty_preprocessed_candidates() -> None:
    """Verify similarity scores skips empty preprocessed candidates."""
    service = CategorySuggestionService.__new__(CategorySuggestionService)
    service._preprocess_description = lambda text: "" if text == "drop me" else text

    encode_calls: list[tuple[list[str], bool]] = []
    vectors = {
        "seed merchant": np.array([1.0, 0.0]),
        "same merchant": np.array([1.0, 0.0]),
    }

    def fake_encode(
        texts: Sequence[str],
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        encode_calls.append((list(texts), show_progress_bar))
        return np.array([vectors[text] for text in texts])

    service.model = SimpleNamespace(encode=fake_encode)

    scores = service.similarity_scores(
        "seed merchant",
        ["same merchant", "drop me"],
    )

    assert encode_calls == [(["seed merchant", "same merchant"], False)]
    assert scores == [1.0, 0.0]


def test_similarity_scores_raises_when_encode_returns_too_few_embeddings() -> None:
    """Verify similarity scores raises when encode returns too few embeddings."""
    service = CategorySuggestionService.__new__(CategorySuggestionService)
    service._preprocess_description = lambda text: text

    def fake_encode(
        texts: Sequence[str],
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        assert texts == ["seed merchant", "same merchant", "other merchant"]
        assert show_progress_bar is False
        return np.array(
            [
                np.array([1.0, 0.0]),
                np.array([1.0, 0.0]),
            ]
        )

    service.model = SimpleNamespace(encode=fake_encode)

    with pytest.raises(
        RuntimeError,
        match=r"similarity_scores expected 3 embeddings from model\.encode, got 2",
    ):
        service.similarity_scores(
            "seed merchant",
            ["same merchant", "other merchant"],
        )
