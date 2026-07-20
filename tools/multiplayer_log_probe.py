#!/usr/bin/env python3
"""Byte-positioned reads for multiplayer logs shared across Windows and Wine."""

from __future__ import annotations

import errno
import time
from pathlib import Path


def _read_log_bytes(path: Path, offset: int = 0) -> bytes:
    for attempt in range(5):
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                return stream.read()
        except FileNotFoundError:
            return b""
        except OSError as exc:
            # DrvFs can report ENODATA for a read racing a Wine append. Reopen
            # the same file; no alternate evidence path is accepted.
            if exc.errno != errno.ENODATA or attempt == 4:
                raise
            time.sleep(0.01)
    raise AssertionError("unreachable log-read retry state")


def read_log(path: Path) -> str:
    return _read_log_bytes(path).decode("utf-8", errors="replace")


def log_position(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def log_after(path: Path, offset: int) -> str:
    return _read_log_bytes(path, offset).decode("utf-8", errors="replace")
