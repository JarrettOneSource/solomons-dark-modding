#!/usr/bin/env python3
"""Parse and assert the player-facing spectator HUD lifecycle marker."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Iterable


STATE_PATTERN = re.compile(
    r"Product spectator HUD surface\. "
    r"active=(?P<active>[01]) "
    r"phase=(?P<phase>[A-Za-z]+) "
    r"registered=(?P<registered>[01]) "
    r"rendered=(?P<rendered>[01]) "
    r"target_participant_id=(?P<target_participant_id>\d+)"
)

PRODUCT_HUD_CONTEXT_EXPECTATIONS = {
    "menu": False,
    "join_lobby": False,
    "alive": False,
    "death_presentation": False,
    "spectating": True,
    "respawned": False,
}


def parse_spectator_product_hud_states(
    text: str,
) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = STATE_PATTERN.search(line)
        if match is None:
            continue
        states.append(
            {
                "active": match.group("active") == "1",
                "phase": match.group("phase"),
                "registered":
                    match.group("registered") == "1",
                "rendered": match.group("rendered") == "1",
                "target_participant_id": int(
                    match.group("target_participant_id")
                ),
                "line": line,
            }
        )
    return states


def _latest_state(log_path: Path) -> dict[str, Any]:
    if not log_path.is_file():
        raise AssertionError(
            f"product spectator HUD log is missing: {log_path}"
        )
    states = parse_spectator_product_hud_states(
        log_path.read_text(encoding="utf-8", errors="replace")
    )
    if not states:
        raise AssertionError(
            "product spectator HUD did not report a surface state: "
            f"{log_path}"
        )
    return states[-1]


def assert_latest_spectator_product_hud_state(
    log_paths: Iterable[Path],
    *,
    context: str,
    expected_active: bool,
    expected_phase: str,
    expected_registered: bool,
    expected_rendered: bool,
    expected_target_participant_id: int | None = None,
) -> dict[str, Any]:
    if context in PRODUCT_HUD_CONTEXT_EXPECTATIONS:
        allowed = PRODUCT_HUD_CONTEXT_EXPECTATIONS[context]
        if expected_registered != allowed or expected_rendered != allowed:
            raise AssertionError(
                "product spectator HUD context expectation contradicts "
                f"the product policy: context={context}"
            )

    results: list[dict[str, Any]] = []
    for log_path in log_paths:
        latest = _latest_state(Path(log_path))
        matches = (
            latest["active"] == expected_active
            and latest["phase"] == expected_phase
            and latest["registered"] == expected_registered
            and latest["rendered"] == expected_rendered
            and (
                expected_target_participant_id is None
                or latest["target_participant_id"]
                    == expected_target_participant_id
            )
        )
        if not matches:
            raise AssertionError(
                "product spectator HUD state mismatch: "
                f"context={context} log={log_path} "
                f"expected_active={expected_active} "
                f"expected_phase={expected_phase} "
                f"expected_registered={expected_registered} "
                f"expected_rendered={expected_rendered} "
                "expected_target_participant_id="
                f"{expected_target_participant_id} latest={latest}"
            )
        results.append(
            {
                "log": str(log_path),
                "latest": latest,
            }
        )
    return {
        "context": context,
        "matches": True,
        "logs_checked": results,
    }


def wait_for_spectator_product_hud_state(
    log_paths: Iterable[Path],
    *,
    context: str,
    expected_active: bool,
    expected_phase: str,
    expected_registered: bool,
    expected_rendered: bool,
    expected_target_participant_id: int | None = None,
    timeout: float,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    paths = [Path(path) for path in log_paths]
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return assert_latest_spectator_product_hud_state(
                paths,
                context=context,
                expected_active=expected_active,
                expected_phase=expected_phase,
                expected_registered=expected_registered,
                expected_rendered=expected_rendered,
                expected_target_participant_id=
                    expected_target_participant_id,
            )
        except AssertionError as exc:
            last_error = str(exc)
        time.sleep(poll_interval)
    raise AssertionError(
        "timed out waiting for product spectator HUD state: "
        f"context={context} timeout={timeout} last_error={last_error}"
    )


def assert_spectator_product_hud_lifecycle(
    log_path: Path,
    *,
    expected_target_participant_id: int,
    require_retired: bool,
) -> dict[str, Any]:
    states = parse_spectator_product_hud_states(
        Path(log_path).read_text(
            encoding="utf-8",
            errors="replace",
        )
    )
    expected = [
        {
            "active": False,
            "phase": "Inactive",
            "registered": False,
            "rendered": False,
            "target_participant_id": 0,
        },
        {
            "active": True,
            "phase": "DeathPresentation",
            "registered": False,
            "rendered": False,
            "target_participant_id": 0,
        },
        {
            "active": True,
            "phase": "Spectating",
            "registered": True,
            "rendered": True,
            "target_participant_id":
                expected_target_participant_id,
        },
    ]
    if require_retired:
        expected.append(
            {
                "active": False,
                "phase": "Inactive",
                "registered": False,
                "rendered": False,
                "target_participant_id": 0,
            }
        )

    matched: list[dict[str, Any]] = []
    search_index = 0
    for expected_state in expected:
        while search_index < len(states):
            candidate = states[search_index]
            search_index += 1
            if all(
                candidate[key] == value
                for key, value in expected_state.items()
            ):
                matched.append(candidate)
                break
        else:
            raise AssertionError(
                "product spectator HUD lifecycle is incomplete: "
                f"expected={expected} matched={matched} states={states}"
            )
    return {
        "matches": True,
        "expected_target_participant_id":
            expected_target_participant_id,
        "require_retired": require_retired,
        "matched_states": matched,
        "all_states": states,
    }


def assert_spectator_product_hud_never_visible(
    log_path: Path,
) -> dict[str, Any]:
    states = parse_spectator_product_hud_states(
        Path(log_path).read_text(
            encoding="utf-8",
            errors="replace",
        )
    )
    if not states:
        raise AssertionError(
            "product spectator HUD did not report a surface state: "
            f"{log_path}"
        )
    visible = [
        state
        for state in states
        if state["registered"] or state["rendered"]
    ]
    if visible:
        raise AssertionError(
            "product spectator HUD became visible for a non-spectating "
            f"peer: log={log_path} visible={visible}"
        )
    return {
        "matches": True,
        "all_states": states,
    }
