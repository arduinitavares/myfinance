from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from .config import settings
from .database import SessionLocal
from .database_manager import init_database, reset_database
from .services.ecb_exchange_rates import ECBExchangeRateService
from .services.fx_refresh_scheduler import build_fx_refresh_scheduler


fx_scheduler = None


@contextmanager
def _fx_refresh_lock():
    lock_path = Path(f"{settings.database_path}.fx-refresh.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    acquired = False

    try:
        if fcntl is None:
            acquired = True
        else:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                yield False
                return

        yield True
    finally:
        if acquired and fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _run_fx_refresh(*, reason: str, allow_historical_seed: bool) -> None:
    try:
        with _fx_refresh_lock() as acquired:
            if not acquired:
                logger.info("Skipping FX %s refresh because another process holds the lock", reason)
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
                    "FX %s catch-up completed for %s to %s: %s rows upserted, %s working-day gaps",
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global fx_scheduler

    _run_startup_fx_refresh()
    fx_scheduler = build_fx_refresh_scheduler(
        _run_scheduled_fx_refresh,
        hour=settings.fx_refresh_hour_utc,
        minute=settings.fx_refresh_minute_utc,
    )
    fx_scheduler.start()

    try:
        yield
    finally:
        if fx_scheduler is not None and fx_scheduler.running:
            fx_scheduler.shutdown(wait=False)
        fx_scheduler = None


# Initialize the database BEFORE importing routers to ensure tables exist
init_database()

# Import routers
from .routers import transactions, statistics, suggestions, financial_health, projections, anomalies, imports
from .routers.classification import router as classification_router

app = FastAPI(title="MyFinance API", lifespan=lifespan)

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
def debug_reset_database(reset_type: str = "all"):
    try:
        reset_database(reset_type)
        return {"message": "Database reset successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
