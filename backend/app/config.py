from dataclasses import dataclass
from pathlib import Path
import os


APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    imports_dir: Path
    batch_import_dir: Path
    provider_config_path: Path
    provider_example_path: Path


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("MYFINANCE_DATA_DIR", APP_DIR / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)

    batch_import_dir = Path(os.environ.get("MYFINANCE_BATCH_IMPORT_DIR", "/bank_files")).resolve()

    database_path = Path(os.environ.get("MYFINANCE_DB_PATH", data_dir / "myfinance.db")).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    provider_config_path = Path(
        os.environ.get("MYFINANCE_PROVIDER_CONFIG", BACKEND_DIR / "config.local.yaml")
    ).resolve()
    provider_example_path = (BACKEND_DIR / "config.example.yaml").resolve()

    return Settings(
        data_dir=data_dir,
        database_path=database_path,
        imports_dir=imports_dir,
        batch_import_dir=batch_import_dir,
        provider_config_path=provider_config_path,
        provider_example_path=provider_example_path,
    )


settings = load_settings()
