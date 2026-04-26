from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def fx_refresh_lock_path(database_path: str) -> Path:
    return Path(f"{database_path}.fx-refresh.lock")


@contextmanager
def acquire_fx_refresh_lock(
    database_path: str,
    *,
    timeout_seconds: float = 0.0,
    poll_seconds: float = 0.1,
):
    lock_path = fx_refresh_lock_path(database_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    acquired = False

    try:
        if fcntl is None:
            acquired = True
            yield True
            return

        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                yield True
                return
            except BlockingIOError:
                if timeout_seconds <= 0.0 or time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(max(poll_seconds, 0.0))
    finally:
        if acquired and fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
