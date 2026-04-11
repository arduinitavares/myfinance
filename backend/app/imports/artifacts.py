import json
from pathlib import Path

from app.config import settings

from .contracts import DetectionResult, RawEvidence


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

    def write_detection(self, session_id: str, detection: DetectionResult) -> None:
        self._write_json(self.session_dir(session_id) / "detection.json", detection.model_dump(mode="json"))

    def write_raw_evidence(self, session_id: str, attempt_number: int, evidence: RawEvidence) -> None:
        attempt_dir = self.attempt_dir(session_id, attempt_number)
        self._write_json(attempt_dir / "evidence" / "raw.json", evidence.model_dump(mode="json"))

    def write_original_file(self, session_id: str, filename: str, file_bytes: bytes) -> Path:
        target = self.session_dir(session_id) / "original" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)
        return target

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
