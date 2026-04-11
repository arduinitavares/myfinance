import json

import pytest

from app.imports.artifacts import ArtifactStore
from app.imports.contracts import DetectionResult, ImportStrategyKey, RawEvidence


def test_artifact_store_writes_manifest_detection_and_raw_evidence():
    store = ArtifactStore()
    session_dir = store.init_session("session-001")
    store.write_meta("session-001", {"state": "uploaded", "attempt_count": 1})
    detection = DetectionResult(
        strategy_key=ImportStrategyKey.UNKNOWN,
        provider_hint=None,
        language_hint="nl",
        charset_hint="latin-1",
        confidence=0.2,
        page_count=None,
        password_protected=False,
        notes=["headers not registered"],
    )
    store.write_detection(
        "session-001",
        detection,
    )
    store.write_raw_evidence(
        "session-001",
        1,
        RawEvidence(text_blocks=[{"page": 1, "text": "Statement header"}]),
    )

    assert session_dir.exists()
    assert json.loads((session_dir / "meta.json").read_text())["state"] == "uploaded"
    assert json.loads((session_dir / "detection.json").read_text()) == detection.model_dump(mode="json")
    evidence_path = session_dir / "attempts" / "1" / "evidence" / "raw.json"
    assert json.loads(evidence_path.read_text())["text_blocks"][0]["text"] == "Statement header"


def test_artifact_store_writes_original_file_bytes():
    store = ArtifactStore()
    session_dir = store.init_session("session-002")

    target = store.write_original_file("session-002", "statement.csv", b"date,amount\n")

    assert target == session_dir / "original" / "statement.csv"
    assert target.read_bytes() == b"date,amount\n"


@pytest.mark.parametrize(
    "filename",
    [
        "/tmp/escape.csv",
        "../escape.csv",
        "nested/escape.csv",
        "nested\\escape.csv",
    ],
)
def test_artifact_store_rejects_unsafe_original_filenames(filename):
    store = ArtifactStore()
    store.init_session("session-003")

    with pytest.raises(ValueError, match="unsafe filename"):
        store.write_original_file("session-003", filename, b"payload")
