"""Module for backend app services fx_refresh_scheduler."""

from collections.abc import Callable
from datetime import UTC

from apscheduler.schedulers.background import BackgroundScheduler

FX_DAILY_REFRESH_JOB_ID: str = "fx-daily-refresh"
FX_MISFIRE_GRACE_SECONDS: int = 3600


def build_fx_refresh_scheduler(
    refresh_callable: Callable[[], object],
    *,
    hour: int = 2,
    minute: int = 0,
) -> BackgroundScheduler:
    """Build fx refresh scheduler."""
    scheduler = BackgroundScheduler(timezone=UTC)
    scheduler.add_job(
        refresh_callable,
        trigger="cron",
        hour=hour,
        minute=minute,
        id=FX_DAILY_REFRESH_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=FX_MISFIRE_GRACE_SECONDS,
    )
    return scheduler
