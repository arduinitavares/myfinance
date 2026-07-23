"""Explicit migration, restore, and development reset commands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from app.config import settings
from app.database import engine
from app.database_backups import restore_verified_backup
from app.database_manager import reset_database
from app.migrations.run_migrations import run_migrations

RESET_SCOPES: tuple[str, ...] = (
    "all",
    "transactions",
    "statistics",
    "financial_health",
    "projections",
    "anomalies",
    "imports",
    "classification",
)
RESET_ENVIRONMENTS: frozenset[str] = frozenset({"development", "test"})


def build_parser() -> argparse.ArgumentParser:
    """Build the local database administration parser."""
    parser = argparse.ArgumentParser(prog="myfinance-database")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Apply pending verified migrations")

    restore = commands.add_parser("restore", help="Restore a verified backup")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--yes", action="store_true")

    reset = commands.add_parser("reset", help="Reset development or test data")
    reset.add_argument("--scope", choices=RESET_SCOPES, default="all")
    reset.add_argument("--yes", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicitly selected database administration command."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        run_migrations()
        return 0

    if not args.yes:
        parser.error("--yes is required for restore and reset")

    if args.command == "restore":
        backup_path = Path(args.backup).expanduser().resolve()
        engine.dispose()
        restore_verified_backup(backup_path, settings.database_path)
        engine.dispose()
        return 0

    if settings.environment not in RESET_ENVIRONMENTS:
        raise RuntimeError(
            "Database reset is available only in development or test"
        )
    reset_database(str(args.scope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
