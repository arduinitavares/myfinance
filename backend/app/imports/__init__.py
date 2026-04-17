"""Imports package for MyFinance.

This package provides data models and contracts for handling financial data imports,
including detection, extraction, and validation of transactions from various sources.
"""

from .contracts import (
    DetectionResult,
    ExtractedTransaction,
    ExtractionResult,
    ImportIssue,
    ImportStrategyKey,
    ProviderDescription,
    RawEvidence,
)

__all__: list[str] = [
    "DetectionResult",
    "ExtractedTransaction",
    "ExtractionResult",
    "ImportIssue",
    "ImportStrategyKey",
    "ProviderDescription",
    "RawEvidence",
]
