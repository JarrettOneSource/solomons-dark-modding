#!/usr/bin/env python3
"""Reject diagnostic overlay surface registration in normal gameplay logs."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


STATE_PATTERN = re.compile(
    r"Debug UI diagnostic surface set\. "
    r"enabled=(?P<enabled>\d+) "
    r"registered=(?P<registered>\d+) "
    r"rendered=(?P<rendered>\d+)"
)


def _local_path(path_text: str) -> Path:
    if os.name == "nt":
        return Path(path_text)
    match = re.fullmatch(
        r"(?P<drive>[A-Za-z]):[\\/](?P<tail>.*)",
        path_text,
    )
    if match is None:
        return Path(path_text)
    tail = match.group("tail").replace("\\", "/")
    return Path("/mnt") / match.group("drive").lower() / tail


def assert_debug_surfaces_empty(
    log_paths: Iterable[Path],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for log_path in log_paths:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        states = [
            {
                key: int(value)
                for key, value in match.groupdict().items()
            }
            for match in STATE_PATTERN.finditer(text)
        ]
        if not states:
            raise AssertionError(
                "normal gameplay log did not report its diagnostic surface "
                f"state: {log_path}"
            )
        leaked = [
            state
            for state in states
            if (
                state["enabled"] != 0
                or state["registered"] != 0
                or state["rendered"] != 0
            )
        ]
        if leaked:
            raise AssertionError(
                "normal gameplay registered or rendered diagnostic overlay "
                f"surfaces: {log_path}: {leaked}"
            )
        results.append(
            {
                "log": str(log_path),
                "state_samples": states,
            }
        )
    return {
        "logs_checked": results,
        "all_states_empty": True,
    }


def assert_launch_debug_surfaces_empty(
    launch: Mapping[str, object],
    *,
    roles: Iterable[str] = ("host", "client"),
) -> dict[str, Any]:
    log_paths: list[Path] = []
    for role in roles:
        key = f"{role}Log"
        value = launch.get(key)
        if not isinstance(value, str) or not value:
            raise AssertionError(
                f"pair launch did not report {key}"
            )
        log_paths.append(_local_path(value))
    return assert_debug_surfaces_empty(log_paths)
