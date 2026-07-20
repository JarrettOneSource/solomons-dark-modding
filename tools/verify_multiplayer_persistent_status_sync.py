#!/usr/bin/env python3
"""Verify native persistent-skill toggles synchronize for either owner."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_persistent_status_harness import (
    PERSISTENT_FIREWALKER,
    PERSISTENT_MINDSTAR,
    PERSISTENT_REGENERATE,
    wait_for_persistent_status,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    stop_games,
)
from verify_multiplayer_all_upgrade_sync import (
    new_crash_artifacts,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_multiplayer_focus_behavior_sync import (
    DIRECTIONS,
    Direction,
    acquire_secondary_to_rank,
    enable_unsuppressed_combat_prelude,
    cast_secondary_belt_slot,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import read_log


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_persistent_status_sync.json"

SKILLS = (
    ("firewalker", 0x17, PERSISTENT_FIREWALKER),
    ("mindstar", 0x4E, PERSISTENT_MINDSTAR),
    ("regenerate", 0x4F, PERSISTENT_REGENERATE),
)


def observer_pipe(direction: Direction) -> str:
    return HOST_PIPE if direction.source_pipe == CLIENT_PIPE else CLIENT_PIPE


def other_owner(direction: Direction) -> tuple[int, str]:
    if direction.source_id == HOST_ID:
        return CLIENT_ID, CLIENT_PIPE
    return HOST_ID, HOST_PIPE


def press_until_cast_delivery(
    direction: Direction,
    source_offset: int,
    observer_offset: int,
    *,
    belt_slot: int,
    timeout: float,
) -> dict[str, Any]:
    local_marker = "Multiplayer local secondary cast queued from native dispatcher."
    remote_marker = (
        "Multiplayer remote secondary cast queued. "
        f"participant_id={direction.source_id}"
    )
    deadline = time.monotonic() + timeout
    local_count = 0
    remote_count = 0
    presses: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        presses.append(
            cast_secondary_belt_slot(
                direction,
                belt_slot,
                deadline - time.monotonic(),
            )
        )
        poll_deadline = min(deadline, time.monotonic() + 0.35)
        while time.monotonic() < poll_deadline:
            local_count = read_log(direction.source_log)[source_offset:].count(
                local_marker
            )
            if local_count >= 1:
                break
            time.sleep(0.03)
        if local_count >= 1:
            break
    if local_count != 1:
        raise VerifyFailure(
            f"{direction.name} persistent cast acceptance count was {local_count}: "
            f"presses={len(presses)}"
        )

    while time.monotonic() < deadline:
        remote_count = read_log(direction.observer_log)[observer_offset:].count(
            remote_marker
        )
        if remote_count >= 1:
            return {
                "press_count": len(presses),
                "presses": presses,
                "local_queued_count": local_count,
                "remote_queued_count": remote_count,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} persistent cast was not delivered: "
        f"local={local_count} remote={remote_count} presses={len(presses)}"
    )


def toggle_once(
    direction: Direction,
    *,
    belt_slot: int,
    expected_values: int,
    timeout: float,
) -> dict[str, Any]:
    source_offset = len(read_log(direction.source_log))
    remote_offset = len(read_log(direction.observer_log))
    delivery = press_until_cast_delivery(
        direction,
        source_offset,
        remote_offset,
        belt_slot=belt_slot,
        timeout=timeout,
    )
    convergence = wait_for_persistent_status(
        direction.source_pipe,
        observer_pipe(direction),
        direction.source_id,
        expected_values,
        timeout=timeout,
    )
    other_id, other_pipe = other_owner(direction)
    isolation = wait_for_persistent_status(
        other_pipe,
        direction.source_pipe,
        other_id,
        0,
        timeout=timeout,
    )
    return {
        "delivery": delivery,
        "convergence": convergence,
        "untargeted_isolation": isolation,
    }


def run_lifecycle(
    direction: Direction,
    acquisitions: dict[str, dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    baseline = wait_for_persistent_status(
        direction.source_pipe,
        observer_pipe(direction),
        direction.source_id,
        0,
        timeout=timeout,
    )
    stages: dict[str, Any] = {}
    for label, _, flag in SKILLS:
        belt_slot = int(acquisitions[label]["belt_slot"])
        activated = toggle_once(
            direction,
            belt_slot=belt_slot,
            expected_values=flag,
            timeout=timeout,
        )
        deactivated = toggle_once(
            direction,
            belt_slot=belt_slot,
            expected_values=0,
            timeout=timeout,
        )
        stages[label] = {
            "belt_slot": belt_slot,
            "activated": activated,
            "deactivated": deactivated,
        }
    return {"baseline": baseline, "skills": stages}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(
            args.timeout,
            god_mode=False,
            manual_combat=False,
            prearm_manual_spawner=True,
        )
        output["launch"] = startup["launch"]
        output["combat_prelude"] = enable_unsuppressed_combat_prelude(args.timeout)
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        output["resources"] = {
            direction.name: set_local_player_vitals(
                direction.source_pipe,
                500.0,
                500.0,
            )
            for direction in DIRECTIONS
        }
        acquisitions: dict[str, dict[str, dict[str, Any]]] = {}
        for direction in DIRECTIONS:
            acquisitions[direction.name] = {
                label: acquire_secondary_to_rank(
                    direction,
                    entry_row,
                    1,
                    args.timeout,
                )
                for label, entry_row, _ in SKILLS
            }
        output["acquisitions"] = acquisitions
        output["lifecycle"] = {
            direction.name: run_lifecycle(
                direction,
                acquisitions[direction.name],
                args.timeout,
            )
            for direction in DIRECTIONS
        }

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts during persistent-status test: {crashes}"
            )
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not args.keep_open:
            stop_games()

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "new_crash_artifacts": output.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
