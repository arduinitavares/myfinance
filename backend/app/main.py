"""Module for backend app main."""

import logging
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .database import SessionLocal
from .database_manager import reset_database
from .migrations.run_migrations import run_migrations
from .routers import (
    anomalies,
    financial_health,
    imports,
    projections,
    statistics,
    suggestions,
    transactions,
)
from .routers.classification import (
    router as classification_router,
)
from .services.ecb_exchange_rates import (
    ECBExchangeRateService,
)
from .services.fx_refresh_lock import (
    acquire_fx_refresh_lock,
)
from .services.fx_refresh_scheduler import (
    build_fx_refresh_scheduler,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class FxSchedulerState:
    """Track the process-local FX refresh scheduler."""

    scheduler: BackgroundScheduler | None = None


fx_scheduler_state: FxSchedulerState = FxSchedulerState()


@contextmanager
def _fx_refresh_lock() -> Iterator[bool]:
    with acquire_fx_refresh_lock(
        settings.database_path, timeout_seconds=0.0
    ) as acquired:
        yield acquired


def _run_fx_refresh(*, reason: str, allow_historical_seed: bool) -> None:
    try:
        with _fx_refresh_lock() as acquired:
            if not acquired:
                logger.info(
                    "Skipping FX %s refresh because another process holds the lock",
                    reason,
                )
                return

            with SessionLocal() as db:
                service = ECBExchangeRateService(db)
                if allow_historical_seed and not service.has_historical_seed_coverage():
                    seed_result = service.seed_historical_rates()
                    logger.info(
                        "FX historical seed completed for %s to %s: %s rows upserted",
                        seed_result.start_date,
                        seed_result.end_date,
                        seed_result.inserted_or_updated_rows,
                    )

                result = service.catch_up_recent_days(
                    window_days=settings.fx_startup_catchup_days
                )
                logger.info(
                    "FX %s catch-up completed for %s to %s: %s rows "
                    "upserted, %s working-day gaps",
                    reason,
                    result.start_date,
                    result.end_date,
                    result.inserted_or_updated_rows,
                    len(result.missing_working_days),
                )
    except Exception:
        logger.exception("FX %s refresh failed", reason)


def _run_startup_fx_refresh() -> None:
    _run_fx_refresh(reason="startup", allow_historical_seed=True)


def _run_scheduled_fx_refresh() -> None:
    _run_fx_refresh(reason="scheduled", allow_historical_seed=False)


def _start_background_fx_refresh() -> threading.Thread:
    thread = threading.Thread(
        target=_run_startup_fx_refresh,
        name="fx-startup-refresh",
        daemon=True,
    )
    thread.start()
    return thread


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Handle lifespan."""
    _start_background_fx_refresh()
    scheduler: BackgroundScheduler = build_fx_refresh_scheduler(
        _run_scheduled_fx_refresh,
        hour=settings.fx_refresh_hour_utc,
        minute=settings.fx_refresh_minute_utc,
    )
    fx_scheduler_state.scheduler = scheduler
    scheduler.start()

    try:
        yield
    finally:
        active_scheduler: BackgroundScheduler | None = fx_scheduler_state.scheduler
        if active_scheduler is not None and active_scheduler.running:
            active_scheduler.shutdown(wait=False)
        fx_scheduler_state.scheduler = None


# Apply recoverable schema migrations before startup-only data loading.
run_migrations()
suggestions.initialize_category_suggestion_model()

app: FastAPI = FastAPI(title="MyFinance API", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers
app.include_router(suggestions.router)
app.include_router(transactions.router)
app.include_router(statistics.router)
app.include_router(financial_health.router)
app.include_router(projections.router)
app.include_router(anomalies.router)
app.include_router(imports.router)
app.include_router(classification_router)


# Add a debug endpoint to reset the database
# pass statistics or transactions to reset only statistics or transactions
@app.post("/debug/reset-database")
def debug_reset_database(reset_type: str = "all") -> dict[str, str]:
    """Handle debug reset database."""
    try:
        reset_database(reset_type)
    except (RuntimeError, SQLAlchemyError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        return {"message": "Database reset successfully"}
