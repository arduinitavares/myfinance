"""Artifact storage management for import sessions.

This module provides the ArtifactStore class for managing file artifacts
and metadata during the import process, including:
- Session and attempt directory initialization
- Storage of detection results and extraction evidence
- JSON serialization of import data
- Filename validation for security
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import settings

from .contracts import DetectionResult, ExtractionResult, RawEvidence


class ArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.imports_dir

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def init_session(self, session_id: str) -> Path:
        session_dir = self.session_dir(session_id)
        (session_dir / "original").mkdir(parents=True, exist_ok=True)
        return session_dir

    def attempt_dir(self, session_id: str, attempt_number: int) -> Path:
        attempt_dir = self.session_dir(session_id) / "attempts" / str(attempt_number)
        (attempt_dir / "evidence").mkdir(parents=True, exist_ok=True)
        (attempt_dir / "ai").mkdir(parents=True, exist_ok=True)
        (attempt_dir / "normalized").mkdir(parents=True, exist_ok=True)
        return attempt_dir

    def write_meta(self, session_id: str, payload: dict) -> None:
        self._write_json(self.session_dir(session_id) / "meta.json", payload)

    def read_meta(self, session_id: str) -> dict:
        path = self.session_dir(session_id) / "meta.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_detection(self, session_id: str, detection: DetectionResult) -> None:
        self._write_json(
            self.session_dir(session_id) / "detection.json",
            detection.model_dump(mode="json"),
        )

    def write_raw_evidence(
        self, session_id: str, attempt_number: int, evidence: RawEvidence
    ) -> None:
        attempt_dir = self.attempt_dir(session_id, attempt_number)
        self._write_json(
            attempt_dir / "evidence" / "raw.json", evidence.model_dump(mode="json")
        )

    def write_normalized_result(
        self, session_id: str, attempt_number: int, result: ExtractionResult
    ) -> None:
        attempt_dir = self.attempt_dir(session_id, attempt_number)
        self._write_json(
            attempt_dir / "normalized" / "extraction_result.json",
            result.model_dump(mode="json"),
        )

    def write_original_file(
        self, session_id: str, filename: str, file_bytes: bytes
    ) -> Path:
        self._validate_original_filename(filename)
        target = self.session_dir(session_id) / "original" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)
        return target

    def existing_attempt_numbers(self, session_id: str) -> list[int]:
        attempts_root = self.session_dir(session_id) / "attempts"
        if not attempts_root.exists():
            return []
        attempt_numbers = []
        for child in attempts_root.iterdir():
            if child.is_dir() and child.name.isdigit():
                attempt_numbers.append(int(child.name))
        return sorted(attempt_numbers)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _validate_original_filename(filename: str) -> None:
        path = Path(filename)
        if (
            not filename
            or path.is_absolute()
            or any(part == ".." for part in path.parts)
            or "/" in filename
            or "\\" in filename
        ):
            raise ValueError(f"unsafe filename: {filename!r}")
