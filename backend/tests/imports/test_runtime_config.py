from app.config import settings


def test_settings_use_isolated_backend_test_paths():
    assert "backend/tests/.tmp/data" in str(settings.data_dir)
    assert settings.database_path.parent == settings.data_dir
    assert settings.imports_dir.parent == settings.data_dir
    assert settings.provider_config_path.name == "config.local.yaml"
