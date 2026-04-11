import json

from app.imports.artifacts import ArtifactStore
from app.imports.contracts import DetectionResult, ImportStrategyKey, RawEvidence


def test_artifact_store_writes_manifest_detection_and_raw_evidence():
    store = ArtifactStore()
    session_dir = store.init_session("session-001")
    store.write_meta("session-001", {"state": "uploaded", "attempt_count": 1})
    store.write_detection(
        "session-001",
        DetectionResult(
            strategy_key=ImportStrategyKey.UNKNOWN,
            provider_hint=None,
            language_hint="nl",
            charset_hint="latin-1",
            confidence=0.2,
            page_count=None,
            password_protected=False,
            notes=["headers not registered"],
        ),
    )
    store.write_raw_evidence(
        "session-001",
        1,
        RawEvidence(text_blocks=[{"page": 1, "text": "Statement header"}]),
    )

    assert session_dir.exists()
    assert json.loads((session_dir / "meta.json").read_text())["state"] == "uploaded"
    evidence_path = session_dir / "attempts" / "1" / "evidence" / "raw.json"
    assert json.loads(evidence_path.read_text())["text_blocks"][0]["text"] == "Statement header"
