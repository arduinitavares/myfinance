"""Module for backend app services category_suggestion_service."""

import logging
import re

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from ..models.transaction import (
    Transaction,
    TransactionType,
)
from ..utils import (
    CARD_NUMBER_PATTERNS,
    IBAN_BIC_PATTERNS,
    REFERENCE_PATTERNS,
    TRANSACTION_DATE_PATTERNS,
)

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

QDRANT_ERRORS: tuple[type[Exception], ...] = (
    ResponseHandlingException,
    UnexpectedResponse,
    ValueError,
)


def _strip_patterns(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text


SERVICE_DOT_TIME_PATTERN: str = r"\b(?:[01]?\d|2[0-3])\.[0-5]\d(?:\s?(?:am|pm))?\b"


class CategorySuggestionService:
    """Represent category suggestion service."""

    def __init__(self) -> None:
        # Initialize the sentence transformer model
        """Initialize the instance."""
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

        # Initialize Qdrant client (vector database)
        self.client = QdrantClient(":memory:")  # For production, use persistent storage

        # Create collections for expense and income categories
        self.client.recreate_collection(
            collection_name="expense_embeddings",
            vectors_config=models.VectorParams(
                size=384,  # Output dimension of the model
                distance=models.Distance.COSINE,
            ),
        )

        self.client.recreate_collection(
            collection_name="income_embeddings",
            vectors_config=models.VectorParams(
                size=384, distance=models.Distance.COSINE
            ),
        )

    def _preprocess_description(self, description: str) -> str:
        """
        Preprocess transaction description by cleaning and normalizing the text.

        Args:
            description: Raw transaction description

        Returns:
            Cleaned and normalized description
        """
        # Convert to lowercase
        text = description.lower()

        # Remove common transaction prefixes
        prefixes = [
            r"payment via \w+\s+",
            r"european direct debit\s+",
            r"instant credit transfer from\s+",
            r"charge\s+",
            r"payment\s+",
        ]
        for prefix in prefixes:
            text = re.sub(prefix, "", text, flags=re.IGNORECASE)

        # Remove dates in various formats
        text = _strip_patterns(text, TRANSACTION_DATE_PATTERNS)
        text = re.sub(SERVICE_DOT_TIME_PATTERN, "", text, flags=re.IGNORECASE)

        # Remove card information
        text = _strip_patterns(text, CARD_NUMBER_PATTERNS)
        text = re.sub(r"cardholder:\s*[^\n]+", "", text, flags=re.IGNORECASE)

        # Remove transaction references and IDs
        text = _strip_patterns(text, REFERENCE_PATTERNS)
        text = re.sub(r"ordering bank\s*:\s*[\w\s]+", "", text, flags=re.IGNORECASE)

        # Remove account numbers and BIC codes
        text = _strip_patterns(text, IBAN_BIC_PATTERNS)

        # Remove postal codes and addresses
        text = re.sub(r"\d{4,5}\s*[-\s]*[a-z]{2,3}", "", text)
        text = re.sub(r"\d{3,4}\s+\d{4}\s+[a-zA-Z\s]+", "", text)

        # Remove multiple spaces and trim
        text = re.sub(r"\s+", " ", text).strip()

        # Extract merchant name (usually in caps or after specific keywords)
        merchant_patterns = [
            r"([A-Z][A-Z &]+)",  # All caps merchant names
            r"creditor\s*:\s*([^\.]+)",  # After "creditor:"
            r"(?:at|to|from)\s+([^\.]+)",  # After "at", "to", or "from"
        ]

        merchant_name = None
        for pattern in merchant_patterns:
            match = re.search(pattern, description)
            if match:
                merchant_name = match.group(1).strip()
                break

        if merchant_name:
            # Add merchant name to the beginning of the processed text for emphasis
            text = f"{merchant_name.lower()} {text}"

        return text

    def _create_transaction_text(self, transaction: Transaction) -> str:
        """Create a text representation of the transaction for embedding."""
        description = self._preprocess_description(transaction.description)
        transaction_text = f"{description} {abs(transaction.amount)}"
        logger.info("Creating transaction text: %s", transaction_text)
        return transaction_text

    def _cosine_similarity(
        self, source_embedding: np.ndarray, candidate_embedding: np.ndarray
    ) -> float:
        source_norm = float(np.linalg.norm(source_embedding))
        candidate_norm = float(np.linalg.norm(candidate_embedding))
        if source_norm == 0.0 or candidate_norm == 0.0:
            return 0.0

        score = float(
            np.dot(source_embedding, candidate_embedding)
            / (source_norm * candidate_norm)
        )
        return 0.0 if np.isnan(score) else score

    def similarity_score(
        self, source_description: str, candidate_description: str
    ) -> float:
        """Handle similarity score."""
        source_text = self._preprocess_description(source_description)
        candidate_text = self._preprocess_description(candidate_description)
        if not source_text or not candidate_text:
            return 0.0

        source_embedding = self.model.encode(source_text, show_progress_bar=False)
        candidate_embedding = self.model.encode(candidate_text, show_progress_bar=False)
        return self._cosine_similarity(source_embedding, candidate_embedding)

    def similarity_scores(
        self,
        source_description: str,
        candidate_descriptions: list[str],
    ) -> list[float]:
        """Handle similarity scores."""
        if not candidate_descriptions:
            return []

        source_text = self._preprocess_description(source_description)
        if not source_text:
            return [0.0] * len(candidate_descriptions)

        candidate_texts = [
            self._preprocess_description(description)
            for description in candidate_descriptions
        ]
        non_empty_candidates = [
            (index, candidate_text)
            for index, candidate_text in enumerate(candidate_texts)
            if candidate_text
        ]
        if not non_empty_candidates:
            return [0.0] * len(candidate_descriptions)

        candidate_indices = [index for index, _ in non_empty_candidates]
        candidate_texts_to_encode = [
            candidate_text for _, candidate_text in non_empty_candidates
        ]
        embeddings = self.model.encode(
            [source_text, *candidate_texts_to_encode],
            show_progress_bar=False,
        )
        expected_embedding_count = 1 + len(non_empty_candidates)
        if len(embeddings) != expected_embedding_count:
            msg = (
                "similarity_scores expected "
                f"{expected_embedding_count} embeddings from model.encode, "
                f"got {len(embeddings)}"
            )
            raise RuntimeError(msg)

        source_embedding = embeddings[0]
        scores: list[float] = [0.0] * len(candidate_descriptions)
        for index, candidate_embedding in zip(
            candidate_indices, embeddings[1:], strict=False
        ):
            scores[index] = self._cosine_similarity(
                source_embedding, candidate_embedding
            )
        return scores

    def _get_collection_name(self, transaction_type: TransactionType) -> str:
        if transaction_type == TransactionType.EXPENSE:
            return "expense_embeddings"
        if transaction_type == TransactionType.INCOME:
            return "income_embeddings"
        msg = f"Unsupported transaction type for suggestions: {transaction_type}"
        raise ValueError(msg)

    def train_on_existing_transactions(self, db: Session) -> None:
        """Train the model on existing transactions."""
        transactions = db.query(Transaction).all()

        for transaction in transactions:
            if transaction.transaction_type == TransactionType.TRANSFER:
                continue
            if transaction.transfer_category is not None:
                continue
            if not transaction.expense_category and not transaction.income_category:
                continue
            if transaction.transaction_type not in {
                TransactionType.EXPENSE,
                TransactionType.INCOME,
            }:
                continue

            text = self._create_transaction_text(transaction)
            embedding = self.model.encode(text, show_progress_bar=False)

            collection_name = self._get_collection_name(transaction.transaction_type)
            category = (
                transaction.expense_category
                if transaction.transaction_type == TransactionType.EXPENSE
                else transaction.income_category
            )
            if category is None:
                continue

            self.client.upsert(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=transaction.id,
                        vector=embedding.tolist(),
                        payload={"category": category.value},
                    )
                ],
            )

    def suggest_category(
        self,
        description: str,
        amount: float,
        transaction_type: TransactionType,
        top_k: int = 3,
    ) -> list[tuple[str, float]]:
        """Suggest categories for a new transaction."""
        if transaction_type == TransactionType.TRANSFER:
            return []
        text = f"{self._preprocess_description(description)} {abs(amount)}"
        logger.info("Suggesting category for text: %s", text)
        embedding = self.model.encode(text, show_progress_bar=False)

        collection_name = self._get_collection_name(transaction_type)

        # Check if collection has any points
        try:
            collection_info = self.client.get_collection(collection_name)
            if collection_info.points_count == 0:
                logger.warning(
                    "No points in %s collection, returning empty suggestions",
                    collection_name,
                )
                return []
        except QDRANT_ERRORS as exc:
            logger.warning(
                "Error checking collection: %s, returning empty suggestions",
                exc,
            )
            return []

        # Search for similar transactions using query_points (qdrant-client >= 1.7)
        try:
            search_result = self.client.query_points(
                collection_name=collection_name,
                query=embedding.tolist(),
                limit=top_k,
            )
        except QDRANT_ERRORS:
            logger.exception("Error searching for similar transactions")
            return []

        # Return categories with confidence scores.
        suggestions: list[tuple[str, float]] = []
        for hit in search_result.points:
            payload = hit.payload or {}
            category = payload.get("category")
            if isinstance(category, str):
                suggestions.append((category, float(hit.score)))
        return suggestions

    def add_transaction(self, transaction: Transaction) -> None:
        """Add a new transaction to the vector database."""
        if transaction.transaction_type == TransactionType.TRANSFER:
            return
        if transaction.transfer_category is not None:
            return
        if not transaction.expense_category and not transaction.income_category:
            return

        text = self._create_transaction_text(transaction)
        embedding = self.model.encode(text, show_progress_bar=False)

        collection_name = self._get_collection_name(transaction.transaction_type)
        category = (
            transaction.expense_category
            if transaction.transaction_type == TransactionType.EXPENSE
            else transaction.income_category
        )
        if category is None:
            return

        self.client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=transaction.id,
                    vector=embedding.tolist(),
                    payload={"category": category.value},
                )
            ],
        )

    def remove_transaction(self, transaction_id: int | None) -> None:
        """Remove a transaction from all embedding collections."""
        if transaction_id is None:
            return

        for collection_name in ("expense_embeddings", "income_embeddings"):
            self.client.delete(
                collection_name=collection_name, points_selector=[transaction_id]
            )

    def sync_transaction(self, transaction: Transaction) -> None:
        """Synchronize the indexed representation for a transaction."""
        self.remove_transaction(transaction.id)
        self.add_transaction(transaction)
