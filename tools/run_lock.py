"""Small POSIX advisory lock used to protect generated simulation reports."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import TextIO


def acquire_run_lock(path: Path) -> TextIO:
    """Hold an exclusive non-blocking lock until the returned handle closes."""
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise SystemExit(f"another simulation owns {path}") from error
    return handle
