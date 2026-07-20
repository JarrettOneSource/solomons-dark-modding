#!/usr/bin/env python3
"""Verify native Firewalker trail behavior is replicated for either owner."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_persistent_status_harness import (
    FIREWALKER_TRAIL_NATIVE_TYPE,
    PERSISTENT_FIREWALKER,
    arm_native_factory_trace,
    clear_native_factory_trace,
    query_firewalker_native_actors,
    query_replicated_firewalker_sync,
    sample_native_factory_trace,
)
from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    parse_int_text,
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
)
from verify_multiplayer_persistent_status_sync import toggle_once
from verify_multiplayer_rush_behavior_sync import (
    configure_native_movement_drive,
    query_native_movement_drive,
)
from verify_player_health_death_sync import set_local_player_vitals


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_firewalker_effect_sync.json"
FIREWALKER_ROW = 0x17
MOVEMENT_TICKS = 180
MINIMUM_TRAIL_COUNT = 3


def observer_pipe(direction: Direction) -> str:
    return HOST_PIPE if direction.source_pipe == CLIENT_PIPE else CLIENT_PIPE


def as_float(values: dict[str, str], key: str, default: float) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default


def sync_score(sample: dict[str, str]) -> tuple[int, ...]:
    return (
        parse_int_text(sample.get("apply.max_matched_firewalker_effect_count"), 0),
        parse_int_text(sample.get("apply.cumulative_firewalker_create_count"), 0),
        parse_int_text(sample.get("apply.cumulative_firewalker_runtime_write_count"), 0),
        parse_int_text(sample.get("snapshot.active_count"), 0),
        parse_int_text(sample.get("binding.matched_count"), 0),
        parse_int_text(sample.get("native.count"), 0),
    )


def active_sample_ready(
    owner: dict[str, Any],
    observer: dict[str, str],
) -> bool:
    active_count = parse_int_text(observer.get("snapshot.active_count"), 0)
    return (
        owner["count"] >= MINIMUM_TRAIL_COUNT
        and owner["positive_lifetime_count"] >= MINIMUM_TRAIL_COUNT
        and owner["finite_position_count"] >= MINIMUM_TRAIL_COUNT
        and owner["max_damage"] > 0.0
        and observer.get("available") == "true"
        and active_count >= MINIMUM_TRAIL_COUNT
        and parse_int_text(observer.get("snapshot.runtime_count"), 0) >= active_count
        and parse_int_text(
            observer.get("apply.max_matched_firewalker_effect_count"),
            0,
        )
        >= MINIMUM_TRAIL_COUNT
        and parse_int_text(
            observer.get("apply.cumulative_firewalker_create_count"),
            0,
        )
        >= MINIMUM_TRAIL_COUNT
        and parse_int_text(
            observer.get("apply.cumulative_firewalker_runtime_write_count"),
            0,
        )
        > 0
        and parse_int_text(observer.get("binding.matched_count"), 0)
        >= MINIMUM_TRAIL_COUNT
        and parse_int_text(observer.get("binding.source_mismatch_count"), 0) == 0
        and parse_int_text(observer.get("binding.runtime_mismatch_count"), 0) == 0
        and parse_int_text(observer.get("native.count"), 0) >= MINIMUM_TRAIL_COUNT
        and as_float(observer, "binding.max_position_error", 9999.0) <= 0.05
        and as_float(observer, "binding.max_phase_error", 9999.0) <= 0.50
        and as_float(observer, "binding.max_lifetime_error", 9999.0) <= 0.25
    )


def drive_and_wait_for_active_sync(
    direction: Direction,
    *,
    timeout: float,
) -> dict[str, Any]:
    drive_start = configure_native_movement_drive(
        direction.source_pipe,
        MOVEMENT_TICKS,
    )
    deadline = time.monotonic() + timeout
    attempts = 0
    best_owner: dict[str, Any] = {}
    best_observer: dict[str, str] = {}
    last_drive: dict[str, str] = {}
    while time.monotonic() < deadline:
        attempts += 1
        owner = query_firewalker_native_actors(direction.source_pipe)
        observer = query_replicated_firewalker_sync(
            observer_pipe(direction),
            direction.source_id,
        )
        last_drive = query_native_movement_drive(direction.source_pipe)
        if owner.get("count", 0) > best_owner.get("count", 0):
            best_owner = owner
        if not best_observer or sync_score(observer) > sync_score(best_observer):
            best_observer = observer
        if active_sample_ready(owner, observer):
            return {
                "ok": True,
                "attempt_count": attempts,
                "drive_start": drive_start,
                "drive": last_drive,
                "owner": owner,
                "observer": observer,
                "best_owner": best_owner,
                "best_observer": best_observer,
            }
        if last_drive.get("error"):
            raise VerifyFailure(
                f"{direction.name} Firewalker movement drive failed: {last_drive}"
            )
        time.sleep(0.04)
    raise VerifyFailure(
        f"{direction.name} Firewalker trails did not converge while moving: "
        f"drive={last_drive} owner={best_owner} observer={best_observer}"
    )


def wait_for_drive_complete(direction: Direction, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_native_movement_drive(direction.source_pipe)
        if last.get("error"):
            raise VerifyFailure(
                f"{direction.name} Firewalker movement drive failed: {last}"
            )
        if (
            parse_int_text(last.get("remaining"), -1) == 0
            and parse_int_text(last.get("applied"), -1) == MOVEMENT_TICKS
            and last.get("write_ok") == "true"
            and last.get("clear_ok") == "true"
            and last.get("cleared") == "true"
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} Firewalker movement drive did not complete: {last}"
    )


def wait_for_post_drive_active_sync(
    direction: Direction,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Prove active trails still outrank accumulated terminal tombstones."""

    deadline = time.monotonic() + timeout
    attempts = 0
    best_owner: dict[str, Any] = {}
    best_observer: dict[str, str] = {}
    while time.monotonic() < deadline:
        attempts += 1
        owner = query_firewalker_native_actors(direction.source_pipe)
        observer = query_replicated_firewalker_sync(
            observer_pipe(direction),
            direction.source_id,
        )
        if owner.get("positive_lifetime_count", 0) > best_owner.get(
            "positive_lifetime_count",
            0,
        ):
            best_owner = owner
        if not best_observer or sync_score(observer) > sync_score(best_observer):
            best_observer = observer

        owner_active = int(owner.get("positive_lifetime_count", 0))
        observer_active = parse_int_text(
            observer.get("snapshot.active_count"),
            0,
        )
        observer_matched = parse_int_text(
            observer.get("binding.matched_count"),
            0,
        )
        if (
            owner_active >= MINIMUM_TRAIL_COUNT
            and observer_active >= owner_active
            and observer_matched >= owner_active
            and parse_int_text(observer.get("snapshot.runtime_count"), 0)
            >= observer_active
            and parse_int_text(observer.get("binding.source_mismatch_count"), 0)
            == 0
            and parse_int_text(observer.get("binding.runtime_mismatch_count"), 0)
            == 0
            and as_float(observer, "binding.max_position_error", 9999.0) <= 0.05
            and as_float(observer, "binding.max_phase_error", 9999.0) <= 0.50
            and as_float(observer, "binding.max_lifetime_error", 9999.0) <= 0.25
        ):
            return {
                "ok": True,
                "attempt_count": attempts,
                "owner": owner,
                "observer": observer,
                "active_effects_preferred": True,
            }
        time.sleep(0.04)

    raise VerifyFailure(
        f"{direction.name} active Firewalker trails were starved by terminal "
        f"history after movement completed: owner={best_owner} "
        f"observer={best_observer}"
    )


def wait_for_trail_cleanup(
    direction: Direction,
    *,
    minimum_terminal_count: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts = 0
    last_owner: dict[str, Any] = {}
    last_observer: dict[str, str] = {}
    while time.monotonic() < deadline:
        attempts += 1
        last_owner = query_firewalker_native_actors(direction.source_pipe)
        last_observer = query_replicated_firewalker_sync(
            observer_pipe(direction),
            direction.source_id,
        )
        if (
            last_owner["count"] == 0
            and parse_int_text(last_observer.get("native.count"), -1) == 0
            and parse_int_text(last_observer.get("snapshot.active_count"), -1) == 0
            and parse_int_text(last_observer.get("binding.count"), -1) == 0
            and parse_int_text(
                last_observer.get("apply.cumulative_firewalker_create_count"),
                0,
            )
            >= minimum_terminal_count
            and parse_int_text(
                last_observer.get("apply.cumulative_terminal_write_count"),
                0,
            )
            >= minimum_terminal_count
        ):
            return {
                "ok": True,
                "attempt_count": attempts,
                "owner": last_owner,
                "observer": last_observer,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} Firewalker trail lifecycle did not terminate cleanly: "
        f"owner={last_owner} observer={last_observer}"
    )


def wait_for_factory_parity(
    owner_pipe: str,
    owner_trace_name: str,
    observer_pipe_name: str,
    observer_trace_name: str,
    timeout: float,
) -> dict[str, Any]:
    """Allow the final owner frame to cross UDP before comparing creations."""

    deadline = time.monotonic() + timeout
    attempts = 0
    samples: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        samples = {
            "owner": sample_native_factory_trace(owner_pipe, owner_trace_name),
            "observer": sample_native_factory_trace(
                observer_pipe_name,
                observer_trace_name,
            ),
        }
        owner_created = samples["owner"]["type_counts"].get(
            FIREWALKER_TRAIL_NATIVE_TYPE,
            0,
        )
        observer_created = samples["observer"]["type_counts"].get(
            FIREWALKER_TRAIL_NATIVE_TYPE,
            0,
        )
        if (
            owner_created >= MINIMUM_TRAIL_COUNT
            and observer_created == owner_created
        ):
            return {
                "attempt_count": attempts,
                "owner_created": owner_created,
                "observer_created": observer_created,
                "samples": samples,
            }
        time.sleep(0.04)
    raise VerifyFailure(
        "Firewalker factory creation counts did not converge after the final "
        f"movement frame: attempts={attempts} samples={samples}"
    )


def wait_for_empty_baseline(
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    owner_pipe = direction.source_pipe
    remote_pipe = observer_pipe(direction)
    deadline = time.monotonic() + timeout
    baseline: dict[str, Any] = {}
    while time.monotonic() < deadline:
        baseline = {
            "owner": query_firewalker_native_actors(owner_pipe),
            "observer": query_replicated_firewalker_sync(
                remote_pipe,
                direction.source_id,
            ),
        }
        if baseline["owner"]["count"] == 0 and parse_int_text(
            baseline["observer"].get("native.count"),
            -1,
        ) == 0:
            return baseline
        time.sleep(0.04)
    raise VerifyFailure(
        f"{direction.name} Firewalker baseline did not quiesce: {baseline}"
    )


def run_direction(
    direction: Direction,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    owner_trace_name = f"firewalker.{direction.name}.owner"
    observer_trace_name = f"firewalker.{direction.name}.observer"
    owner_pipe = direction.source_pipe
    remote_pipe = observer_pipe(direction)
    baseline = wait_for_empty_baseline(direction, min(timeout, 4.0))

    arms = {
        "owner": arm_native_factory_trace(owner_pipe, owner_trace_name),
        "observer": arm_native_factory_trace(remote_pipe, observer_trace_name),
    }
    samples: dict[str, Any] = {}
    clears: dict[str, Any] = {}
    try:
        activated = toggle_once(
            direction,
            belt_slot=int(acquisition["belt_slot"]),
            expected_values=PERSISTENT_FIREWALKER,
            timeout=timeout,
        )
        active_sync = drive_and_wait_for_active_sync(direction, timeout=timeout)
        drive_complete = wait_for_drive_complete(direction, timeout)
        post_drive_sync = wait_for_post_drive_active_sync(
            direction,
            timeout=min(timeout, 4.0),
        )
        factory_parity = wait_for_factory_parity(
            owner_pipe,
            owner_trace_name,
            remote_pipe,
            observer_trace_name,
            min(timeout, 4.0),
        )
        samples = factory_parity["samples"]
        owner_created = int(factory_parity["owner_created"])
        observer_created = int(factory_parity["observer_created"])
        deactivated = toggle_once(
            direction,
            belt_slot=int(acquisition["belt_slot"]),
            expected_values=0,
            timeout=timeout,
        )
        cleanup = wait_for_trail_cleanup(
            direction,
            minimum_terminal_count=owner_created,
            timeout=max(timeout, 8.0),
        )
        return {
            "baseline": baseline,
            "activated": activated,
            "active_sync": active_sync,
            "drive_complete": drive_complete,
            "post_drive_sync": post_drive_sync,
            "factory_trace": {
                "native_type": FIREWALKER_TRAIL_NATIVE_TYPE,
                "owner_created": owner_created,
                "observer_created": observer_created,
                "parity_attempt_count": factory_parity["attempt_count"],
                "samples": samples,
                "clear": clears,
            },
            "deactivated": deactivated,
            "cleanup": cleanup,
        }
    finally:
        for side, pipe_name, trace_name in (
            ("owner", owner_pipe, owner_trace_name),
            ("observer", remote_pipe, observer_trace_name),
        ):
            try:
                clears[side] = clear_native_factory_trace(pipe_name, trace_name)
            except Exception as exc:
                clears[side] = {"error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=22.0)
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
        output["combat_prelude"] = enable_unsuppressed_combat_prelude(
            args.timeout
        )
        output["post_run_progression_ready"] = (
            wait_for_post_run_progression_ready(args.timeout)
        )
        output["resources"] = {
            direction.name: set_local_player_vitals(
                direction.source_pipe,
                500.0,
                500.0,
            )
            for direction in DIRECTIONS
        }
        acquisitions = {
            direction.name: acquire_secondary_to_rank(
                direction,
                FIREWALKER_ROW,
                1,
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["acquisitions"] = acquisitions
        output["directions"] = {}
        for direction in DIRECTIONS:
            output["directions"][direction.name] = run_direction(
                direction,
                acquisitions[direction.name],
                args.timeout,
            )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts during Firewalker test: {crashes}"
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
