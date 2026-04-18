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
from .belfius_csv import BelfiusCsvExtractor
from .beobank_csv import BeobankCsvExtractor
from .nexo_csv import NexoCsvExtractor

__all__: list[str] = [
    "BelfiusCsvExtractor",
    "BeobankCsvExtractor",
    "DetectionResult",
    "ExtractedTransaction",
    "ExtractionResult",
    "ImportIssue",
    "ImportStrategyKey",
    "NexoCsvExtractor",
    "ProviderDescription",
    "RawEvidence",
]
