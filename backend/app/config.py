"""Module for backend app config."""

import os
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

APP_DIR: Any = Path(__file__).resolve().parent
BACKEND_DIR: Any = APP_DIR.parent


@dataclass(frozen=True)
class Settings:
    """Represent settings."""

    data_dir: Path
    database_path: Path
    backup_dir: Path
    environment: str
    frontend_origin: str
    imports_dir: Path
    batch_import_dir: Path
    provider_config_path: Path
    provider_example_path: Path
    fx_seed_years: int
    fx_startup_catchup_days: int
    fx_refresh_hour_utc: int
    fx_refresh_minute_utc: int
    ecb_history_url: str
    ecb_history_90d_url: str


def load_settings() -> Settings:
    """Load settings."""
    data_dir = Path(os.environ.get("MYFINANCE_DATA_DIR", APP_DIR / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)

    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    environment = os.environ.get("MYFINANCE_ENV", "production").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise ValueError(
            "MYFINANCE_ENV must be development, test, or production"
        )

    frontend_origin = os.environ.get(
        "MYFINANCE_FRONTEND_ORIGIN",
        "http://localhost:3000",
    ).strip()
    try:
        parsed_origin = urlsplit(frontend_origin)
        parsed_origin.port
    except ValueError as exc:
        raise ValueError(
            "MYFINANCE_FRONTEND_ORIGIN must be one exact origin"
        ) from exc
    hostname = parsed_origin.hostname
    valid_hostname = False
    if hostname is not None:
        try:
            ip_address(hostname)
        except ValueError:
            labels = hostname.split(".")
            valid_hostname = (
                hostname.isascii()
                and len(hostname) <= 253
                and not all(label.isdigit() for label in labels)
                and all(
                    label
                    and len(label) <= 63
                    and label[0].isalnum()
                    and label[-1].isalnum()
                    and all(
                        character.isalnum() or character == "-"
                        for character in label
                    )
                    for label in labels
                )
            )
        else:
            valid_hostname = True
    if (
        not frontend_origin
        or frontend_origin == "*"
        or parsed_origin.scheme not in {"http", "https"}
        or not valid_hostname
        or parsed_origin.username is not None
        or parsed_origin.password is not None
        or parsed_origin.path not in {"", "/"}
        or parsed_origin.query
        or parsed_origin.fragment
        or parsed_origin.netloc.endswith(":")
        or "," in frontend_origin
        or "\\" in frontend_origin
        or any(character.isspace() for character in frontend_origin)
    ):
        raise ValueError(
            "MYFINANCE_FRONTEND_ORIGIN must be one exact origin"
        )
    frontend_origin = frontend_origin.removesuffix("/")

    batch_import_dir = Path(
        os.environ.get("MYFINANCE_BATCH_IMPORT_DIR", "/bank_files")
    ).resolve()

    database_path = Path(
        os.environ.get("MYFINANCE_DB_PATH", data_dir / "myfinance.db")
    ).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    provider_config_path = Path(
        os.environ.get("MYFINANCE_PROVIDER_CONFIG", BACKEND_DIR / "config.local.yaml")
    ).resolve()
    provider_example_path = (BACKEND_DIR / "config.example.yaml").resolve()
    fx_seed_years = int(os.environ.get("MYFINANCE_FX_SEED_YEARS", "5"))
    fx_startup_catchup_days = int(
        os.environ.get("MYFINANCE_FX_STARTUP_CATCHUP_DAYS", "45")
    )
    fx_refresh_hour_utc = int(os.environ.get("MYFINANCE_FX_REFRESH_HOUR_UTC", "2"))
    fx_refresh_minute_utc = int(os.environ.get("MYFINANCE_FX_REFRESH_MINUTE_UTC", "0"))
    ecb_history_url = os.environ.get(
        "MYFINANCE_ECB_HISTORY_URL",
        "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml",
    )
    ecb_history_90d_url = os.environ.get(
        "MYFINANCE_ECB_HISTORY_90D_URL",
        "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml",
    )

    return Settings(
        data_dir=data_dir,
        database_path=database_path,
        backup_dir=backup_dir,
        environment=environment,
        frontend_origin=frontend_origin,
        imports_dir=imports_dir,
        batch_import_dir=batch_import_dir,
        provider_config_path=provider_config_path,
        provider_example_path=provider_example_path,
        fx_seed_years=fx_seed_years,
        fx_startup_catchup_days=fx_startup_catchup_days,
        fx_refresh_hour_utc=fx_refresh_hour_utc,
        fx_refresh_minute_utc=fx_refresh_minute_utc,
        ecb_history_url=ecb_history_url,
        ecb_history_90d_url=ecb_history_90d_url,
    )


settings: Any = load_settings()
