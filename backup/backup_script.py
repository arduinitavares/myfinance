#!/usr/bin/env python3
"""Database backup script for MyFinance application.

Backs up the database and uploads it to Google Drive.
"""

import argparse
import importlib
import os
import shutil
import sys
import zlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast


def _module_attr(module: object, attr_name: str) -> object:
    """Get a dynamically named module attribute."""
    return getattr(module, attr_name)


def _method0(target: object, method_name: str) -> Callable[[], object]:
    """Get a no-argument method from a dynamic object."""
    return cast("Callable[[], object]", getattr(target, method_name))


def _method1(target: object, method_name: str) -> Callable[[str], object]:
    """Get a one-string-argument method from a dynamic object."""
    return cast("Callable[[str], object]", getattr(target, method_name))


def _attribute(target: object, attr_name: str) -> object:
    """Get a dynamically named object attribute."""
    return getattr(target, attr_name)


def _load_pydrive2() -> tuple[Callable[[], object], Callable[[object], object]]:
    """Load PyDrive2 classes without making it a static type-check dependency."""
    auth_module = importlib.import_module("pydrive2.auth")
    drive_module = importlib.import_module("pydrive2.drive")
    return (
        cast("Callable[[], object]", _module_attr(auth_module, "GoogleAuth")),
        cast("Callable[[object], object]", _module_attr(drive_module, "GoogleDrive")),
    )


def _git_dir(repo_root: Path) -> Path:
    """Resolve the repository git directory."""
    git_path = repo_root / ".git"
    if git_path.is_dir():
        return git_path
    gitdir_prefix = "gitdir: "
    git_reference = git_path.read_text(encoding="utf-8").strip()
    if not git_reference.startswith(gitdir_prefix):
        raise ValueError
    resolved_git_dir = Path(git_reference.removeprefix(gitdir_prefix))
    if resolved_git_dir.is_absolute():
        return resolved_git_dir
    return repo_root / resolved_git_dir


def _packed_ref(git_dir: Path, ref_name: str) -> str:
    """Read a ref from packed-refs."""
    packed_refs = git_dir / "packed-refs"
    for raw_line in packed_refs.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith(("#", "^")):
            continue
        commit_sha, packed_ref = raw_line.split(" ", 1)
        if packed_ref == ref_name:
            return commit_sha
    raise FileNotFoundError


def _head_sha(git_dir: Path) -> str:
    """Resolve HEAD to a commit SHA."""
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    ref_prefix = "ref: "
    if not head.startswith(ref_prefix):
        return head

    ref_name = head.removeprefix(ref_prefix)
    ref_path = git_dir / ref_name
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8").strip()
    return _packed_ref(git_dir, ref_name)


def _commit_message(git_dir: Path, commit_sha: str) -> str:
    """Read the first non-empty line of a loose commit object."""
    object_path = git_dir / "objects" / commit_sha[:2] / commit_sha[2:]
    commit_object = zlib.decompress(object_path.read_bytes()).decode("utf-8")
    _header, commit_body = commit_object.split("\x00", 1)
    _metadata, message = commit_body.split("\n\n", 1)
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if line:
            return line
    raise ValueError


def _read_git_commit_message(repo_root: Path) -> str:
    """Read the last commit message directly from .git storage."""
    git_dir = _git_dir(repo_root)
    return _commit_message(git_dir, _head_sha(git_dir))


def get_last_commit_message(repo_root: Path | None = None) -> str:
    """Get the last commit message from git."""
    root = repo_root or Path(__file__).resolve().parent.parent
    try:
        commit_msg = _read_git_commit_message(root)
    except (OSError, UnicodeDecodeError, ValueError, zlib.error):
        return datetime.now(UTC).strftime("%H%M%S")
    return commit_msg.removeprefix("v")


def backup_database(source_path: Path, backup_dir: Path) -> Path:
    """Create a backup of the database file."""
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    backup_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    commit_msg = get_last_commit_message()
    backup_path = backup_dir / f"myfinance-{date_str}-{commit_msg}.db"
    shutil.copy2(source_path, backup_path)
    return backup_path


def _write_service_account_settings(
    settings_path: Path,
    service_account_file: Path,
) -> None:
    """Create PyDrive2 service-account settings."""
    settings_path.write_text(
        f"""client_config_backend: settings
client_config:
  client_type: service
  auth_uri: https://accounts.google.com/o/oauth2/auth
  token_uri: https://accounts.google.com/o/oauth2/token
  revoke_uri: https://accounts.google.com/o/oauth2/revoke
  client_id: placeholder
  client_secret: placeholder
service_config:
  client_json_file_path: {service_account_file.resolve()}
save_credentials: False
oauth_scope:
  - https://www.googleapis.com/auth/drive
""",
        encoding="utf-8",
    )


def _write_oauth_settings(settings_path: Path, client_secrets_path: Path) -> None:
    """Create PyDrive2 OAuth settings."""
    settings_path.write_text(
        f"""client_config_backend: file
client_config_file: {client_secrets_path}
save_credentials: True
save_credentials_backend: file
save_credentials_file: mycreds.txt
get_refresh_token: True
oauth_scope:
  - https://www.googleapis.com/auth/drive.file
  - https://www.googleapis.com/auth/drive.appdata
  - https://www.googleapis.com/auth/drive.metadata
""",
        encoding="utf-8",
    )


def authenticate_google_drive() -> object:
    """Authenticate with Google Drive."""
    google_auth_cls, google_drive_cls = _load_pydrive2()
    script_dir = Path(__file__).resolve().parent
    settings_path = script_dir / "settings.yaml"
    service_account_file = Path("service-account.json")
    client_secrets_file = Path("client_secrets.json")

    if service_account_file.exists():
        try:
            gauth = google_auth_cls()
            if not settings_path.exists():
                _write_service_account_settings(settings_path, service_account_file)
            _method0(gauth, "ServiceAuth")()
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            if not client_secrets_file.exists():
                raise RuntimeError from exc
        else:
            return google_drive_cls(gauth)

    if not client_secrets_file.exists():
        raise FileNotFoundError(client_secrets_file)

    gauth = google_auth_cls()
    client_secrets_path = client_secrets_file.resolve()
    if not settings_path.exists():
        _write_oauth_settings(settings_path, client_secrets_path)

    _method1(gauth, "LoadClientConfigFile")(str(client_secrets_path))
    _method1(gauth, "LoadCredentialsFile")("mycreds.txt")

    if _attribute(gauth, "credentials") is None:
        _method0(gauth, "LocalWebserverAuth")()
    elif bool(_attribute(gauth, "access_token_expired")):
        _method0(gauth, "Refresh")()
    else:
        _method0(gauth, "Authorize")()

    _method1(gauth, "SaveCredentialsFile")("mycreds.txt")
    return google_drive_cls(gauth)


def load_env_vars(env_path: Path) -> dict[str, str]:
    """Load environment variables from a .env file."""
    if not env_path.exists():
        return {}

    env_vars: dict[str, str] = {}
    with env_path.open(encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key] = value
    return env_vars


def upload_to_drive(
    drive: object,
    file_path: Path,
    folder_id: str | None = None,
) -> str:
    """Upload the backup file to Google Drive."""
    file_metadata: dict[str, object] = {"title": file_path.name}
    if folder_id:
        file_metadata["parents"] = [{"id": folder_id}]

    create_file = cast(
        "Callable[[dict[str, object]], object]",
        _module_attr(drive, "CreateFile"),
    )
    gfile = create_file(file_metadata)
    _method1(gfile, "SetContentFile")(str(file_path))
    _method0(gfile, "Upload")()
    return str(cast("Mapping[str, object]", gfile)["id"])


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(
        description="Backup MyFinance database to Google Drive"
    )
    parser.add_argument("--folder-id", help="Google Drive folder ID to upload to")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    db_path = project_root / "backend" / "app" / "data" / "myfinance.db"
    backup_dir = project_root / "backup"
    env_path = project_root / ".env"
    original_dir = Path.cwd()
    folder_id = cast("str | None", args.folder_id)

    os.chdir(script_dir)
    try:
        if folder_id is None:
            folder_id = load_env_vars(env_path).get("MYFINANCE_BACKUP_FOLDER")

        backup_path = backup_database(db_path, backup_dir)
        drive = authenticate_google_drive()
        upload_to_drive(drive, backup_path, folder_id)
    except (
        AttributeError,
        ImportError,
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        sys.exit(1)
    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
