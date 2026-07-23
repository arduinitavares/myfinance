"""Tests for the local application network and destructive-operation boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from app.config import load_settings, settings
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _cors_middleware() -> Middleware:
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return middleware
    raise AssertionError("CORS middleware is not configured")


def test_normal_api_has_no_database_reset_route() -> None:
    """Keep destructive reset outside the HTTP application."""
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/debug/reset-database" not in route_paths


def test_cors_uses_only_the_configured_frontend_origin() -> None:
    """Reject wildcard browser origins even for a local deployment."""
    middleware = _cors_middleware()

    assert middleware.kwargs["allow_origins"] == [settings.frontend_origin]
    assert middleware.kwargs["allow_credentials"] is True


def test_frontend_origin_can_be_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYFINANCE_FRONTEND_ORIGIN", "https://finance.local")

    loaded = load_settings()

    assert loaded.frontend_origin == "https://finance.local"


def test_frontend_origin_trailing_slash_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYFINANCE_FRONTEND_ORIGIN", "http://localhost:8080/")

    loaded = load_settings()

    assert loaded.frontend_origin == "http://localhost:8080"


@pytest.mark.parametrize(
    "unsafe_origin",
    [
        "",
        "*",
        "https://*.finance.local",
        "finance.local",
        "ftp://finance.local",
        "https://user@finance.local",
        "https://user:password@finance.local",
        "https://finance.local/path",
        "https://finance.local?mode=unsafe",
        "https://finance.local#fragment",
        "https://finance.local,https://other.local",
        "https://finance.local https://other.local",
        "https://",
        "https://-finance.local",
        "https://finance..local",
        "https://finance_local",
        "https://finance.local:invalid",
        "http://[::1",
    ],
)
def test_unsafe_frontend_origin_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_origin: str,
) -> None:
    monkeypatch.setenv("MYFINANCE_FRONTEND_ORIGIN", unsafe_origin)

    with pytest.raises(ValueError, match="must be one exact origin"):
        load_settings()


def test_compose_binds_backend_and_frontend_to_loopback() -> None:
    """Keep Docker services off externally reachable host interfaces."""
    with (PROJECT_ROOT / "docker-compose.yaml").open(encoding="utf-8") as stream:
        compose = yaml.safe_load(stream)

    assert compose["services"]["backend"]["ports"] == [
        "127.0.0.1:8000:8000"
    ]
    assert compose["services"]["frontend"]["ports"] == [
        "127.0.0.1:8080:8080"
    ]


def test_compose_sets_production_frontend_origin() -> None:
    """Keep the container's exact browser origin explicit."""
    with (PROJECT_ROOT / "docker-compose.yaml").open(encoding="utf-8") as stream:
        compose = yaml.safe_load(stream)

    backend_environment = compose["services"]["backend"]["environment"]
    assert "MYFINANCE_ENV=production" in backend_environment
    assert (
        "MYFINANCE_FRONTEND_ORIGIN=http://localhost:8080"
        in backend_environment
    )
