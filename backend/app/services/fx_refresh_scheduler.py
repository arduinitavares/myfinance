from datetime import timezone

from apscheduler.schedulers.background import BackgroundScheduler


FX_DAILY_REFRESH_JOB_ID = "fx-daily-refresh"


def build_fx_refresh_scheduler(
    refresh_callable,
    *,
    hour: int = 2,
    minute: int = 0,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=timezone.utc)
    scheduler.add_job(
        refresh_callable,
        trigger="cron",
        hour=hour,
        minute=minute,
        id=FX_DAILY_REFRESH_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    return scheduler
