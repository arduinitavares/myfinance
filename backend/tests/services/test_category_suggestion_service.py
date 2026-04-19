from types import SimpleNamespace

import numpy as np

from app.services.category_suggestion_service import CategorySuggestionService


def test_similarity_scores_returns_empty_list_for_no_candidates():
    service = CategorySuggestionService.__new__(CategorySuggestionService)

    assert service.similarity_scores("seed merchant", []) == []


def test_similarity_scores_batches_candidates_in_input_order():
    service = CategorySuggestionService.__new__(CategorySuggestionService)
    service._preprocess_description = lambda text: text

    encode_calls: list[tuple[list[str], bool]] = []
    vectors = {
        "seed merchant": np.array([1.0, 0.0]),
        "same merchant": np.array([1.0, 0.0]),
        "other merchant": np.array([0.0, 1.0]),
    }

    def fake_encode(texts, show_progress_bar=False):
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
