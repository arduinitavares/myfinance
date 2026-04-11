from app.imports.pipeline import ImportPipelineService
from app.imports.state_machine import ImportSessionStatus


def test_pipeline_creates_session_persists_upload_and_records_detection(db_session):
    service = ImportPipelineService(db_session)
    session, detection = service.start_upload(
        filename="statement.pdf",
        content_type="application/pdf",
        file_bytes=b"%PDF-1.7\nhello",
    )

    assert session.status == ImportSessionStatus.DETECTED.value
    assert session.strategy_key == detection.strategy_key.value
    assert session.file_name == "statement.pdf"
