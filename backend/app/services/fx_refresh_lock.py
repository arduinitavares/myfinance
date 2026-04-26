"""Module for backend app services fx_refresh_lock."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterator


class FcntlModule(Protocol):
    """Subset of fcntl used by the refresh lock."""

    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None:
        """Apply or release an advisory lock."""
        ...


try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover
    _fcntl_module: FcntlModule | None = None
else:
    _fcntl_module = cast("FcntlModule", _fcntl)

MIN_POLL_SECONDS: float = 0.01


def fx_refresh_lock_path(database_path: str) -> Path:
    """Handle fx refresh lock path."""
    return Path(f"{database_path}.fx-refresh.lock")


@contextmanager
def acquire_fx_refresh_lock(
    database_path: str,
    *,
    timeout_seconds: float = 0.0,
    poll_seconds: float = 0.1,
) -> Iterator[bool]:
    """Handle acquire fx refresh lock."""
    lock_path = fx_refresh_lock_path(database_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    acquired = False

    try:
        if _fcntl_module is None:
            acquired = True
            yield True
        else:
            effective_timeout_seconds = max(timeout_seconds, 0.0)
            effective_poll_seconds = (
                poll_seconds if poll_seconds > 0.0 else MIN_POLL_SECONDS
            )
            deadline = time.monotonic() + effective_timeout_seconds
            while not acquired:
                try:
                    _fcntl_module.flock(
                        lock_file.fileno(),
                        _fcntl_module.LOCK_EX | _fcntl_module.LOCK_NB,
                    )
                    acquired = True
                except BlockingIOError:
                    now = time.monotonic()
                    if effective_timeout_seconds <= 0.0 or now >= deadline:
                        yield False
                        return
                    time.sleep(min(effective_poll_seconds, deadline - now))
            yield True
    finally:
        if acquired and _fcntl_module is not None:
            _fcntl_module.flock(lock_file.fileno(), _fcntl_module.LOCK_UN)
        lock_file.close()
