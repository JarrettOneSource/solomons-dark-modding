#!/usr/bin/env python3
"""Verify Faster Caster changes real primary-cast cadence for both owners."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import query_progression_snapshot
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    lua,
    parse_key_values,
    stop_games,
)
from verify_multiplayer_all_stat_sync import apply_stat_batch, load_stat_contract_values
from verify_multiplayer_all_upgrade_sync import (
    build_and_verify_catalog,
    load_skill_configs,
    new_crash_artifacts,
    wait_for_catalog_views,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    ensure_host_combat_started,
    queue_gameplay_mouse_left,
    read_log,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_faster_caster_behavior_sync.json"
FASTER_CASTER_ROW = 70
PRIMARY_HOLD_FRAMES = 3600
TRIAL_COUNT = 5


@dataclass(frozen=True)
class Direction:
    name: str
    source_id: int
    source_pipe: str
    source_log: Path
    observer_log: Path


DIRECTIONS = (
    Direction("host_owned", HOST_ID, HOST_PIPE, HOST_LOG, CLIENT_LOG),
    Direction("client_owned", CLIENT_ID, CLIENT_PIPE, CLIENT_LOG, HOST_LOG),
)


def log_after(path: Path, offset: int) -> str:
    return read_log(path)[offset:]


def local_accept_count(direction: Direction, offset: int) -> int:
    marker = (
        "Multiplayer local native cast sent. native_queue_id="
    )
    return log_after(direction.source_log, offset).count(marker)


def local_cast_ticks(direction: Direction, offset: int) -> list[int]:
    return [
        int(value)
        for value in re.findall(
            r"Multiplayer local primary cast queued from native pure-primary\. "
            r".*?native_tick_ms=(\d+)",
            log_after(direction.source_log, offset),
        )
    ]


def clear_primary_input(direction: Direction) -> dict[str, str]:
    values = parse_key_values(
        lua(
            direction.source_pipe,
            "local function emit(k,v) print(k .. '=' .. tostring(v)) end; "
            "emit('cleared', sd.input.clear_mouse_left())",
            timeout=5.0,
        )
    )
    if values.get("cleared") != "true":
        raise VerifyFailure(f"{direction.name} primary input clear failed: {values}")
    return values


def wait_for_remote_delivery(
    direction: Direction,
    observer_offset: int,
    expected_count: int,
    timeout: float = 10.0,
) -> int:
    marker = (
        "Multiplayer remote cast queued. "
        f"participant_id={direction.source_id} "
    )
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = log_after(direction.observer_log, observer_offset).count(marker)
        if count >= expected_count:
            return count
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} observer received {count}/{expected_count} primary casts"
    )


def measure_cadence(direction: Direction, timeout: float) -> dict[str, Any]:
    resources = set_local_player_vitals(direction.source_pipe, 10000.0, 10000.0)
    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))

    queued = queue_gameplay_mouse_left(direction, PRIMARY_HOLD_FRAMES)
    if queued.get("mouse_left_frames") != "true":
        raise VerifyFailure(f"{direction.name} primary input queue failed: {queued}")
    required_casts = TRIAL_COUNT + 1
    deadline = time.monotonic() + timeout
    ticks: list[int] = []
    while time.monotonic() < deadline:
        ticks = local_cast_ticks(direction, source_offset)
        if len(ticks) >= required_casts:
            break
        time.sleep(0.02)
    cleared = clear_primary_input(direction)
    if len(ticks) < required_casts:
        raise VerifyFailure(
            f"{direction.name} sustained primary produced {len(ticks)}/{required_casts} "
            f"native casts within {timeout:.1f}s"
        )
    sample_ticks = ticks[:required_casts]
    intervals = [
        (current - previous) / 1000.0
        for previous, current in zip(sample_ticks, sample_ticks[1:])
    ]
    accepted = local_accept_count(direction, source_offset)

    remote_count = wait_for_remote_delivery(
        direction,
        observer_offset,
        required_casts,
    )
    snapshot = query_progression_snapshot(direction.source_pipe)
    return {
        "resources": resources,
        "input_queue": queued,
        "input_clear": cleared,
        "native_tick_ms": sample_ticks,
        "intervals_seconds": intervals,
        "median_seconds": statistics.median(intervals),
        "accepted_count": accepted,
        "remote_delivery_count": remote_count,
        "cast_speed_multiplier": snapshot["native"]["derived"][
            "cast_speed_multiplier"
        ],
    }


def max_faster_caster(
    direction: Direction,
    catalog: list[dict[str, Any]],
    initial: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> list[dict[str, Any]]:
    maximum = int(catalog[FASTER_CASTER_ROW]["native_max_level"])
    steps: list[dict[str, Any]] = []
    while True:
        snapshot = query_progression_snapshot(direction.source_pipe)
        active = int(snapshot["native"]["entries"][FASTER_CASTER_ROW]["active"])
        if active >= maximum:
            return steps
        steps.append(
            apply_stat_batch(
                catalog,
                FASTER_CASTER_ROW,
                direction.source_id,
                min(2, maximum - active),
                initial,
                contract_values,
                timeout,
            )
        )


def run_cadence_phase(
    timeout: float,
    *,
    upgraded: bool,
    retire_pair: bool = True,
) -> dict[str, Any]:
    """Measure a clean normal-combat phase for both participant owners.

    Upgrades are applied before waves begin so background enemy XP cannot trip
    the targeted-progression isolation assertions. Baseline and upgraded
    cadence therefore use fresh profiles but the same stock combat path.
    """
    phase: dict[str, Any] = {"upgraded": upgraded}
    try:
        startup = launch_pair_ready(
            timeout,
            god_mode=False,
            manual_combat=False,
            boneyard_override=None,
        )
        phase["launch"] = startup["launch"]
        phase["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            timeout
        )
        catalog_result = build_and_verify_catalog(
            wait_for_catalog_views(timeout),
            load_skill_configs(),
        )
        catalog = catalog_result["catalog"]
        contract_values = load_stat_contract_values(catalog)
        initial = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }
        if upgraded:
            phase["faster_caster_upgrades"] = {
                direction.name: max_faster_caster(
                    direction,
                    catalog,
                    initial,
                    contract_values,
                    timeout,
                )
                for direction in DIRECTIONS
            }
        phase["combat"] = ensure_host_combat_started()
        phase["cadence"] = {
            direction.name: measure_cadence(direction, timeout)
            for direction in DIRECTIONS
        }
        return phase
    finally:
        if retire_pair:
            stop_games()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["quiet_progression_test_mode"] = {
            "enabled": False,
            "reason": "upgrades apply before normal stock combat starts",
        }
        output["baseline_phase"] = run_cadence_phase(args.timeout, upgraded=False)
        output["baseline"] = output["baseline_phase"]["cadence"]
        output["upgraded_phase"] = run_cadence_phase(
            args.timeout,
            upgraded=True,
            retire_pair=not args.keep_open,
        )
        output["faster_caster_upgrades"] = output["upgraded_phase"][
            "faster_caster_upgrades"
        ]
        output["upgraded"] = output["upgraded_phase"]["cadence"]

        ratios: dict[str, float] = {}
        for direction in DIRECTIONS:
            baseline = float(output["baseline"][direction.name]["median_seconds"])
            upgraded = float(output["upgraded"][direction.name]["median_seconds"])
            ratio = upgraded / baseline
            ratios[direction.name] = ratio
            multiplier = float(output["upgraded"][direction.name]["cast_speed_multiplier"])
            if multiplier < 1.99:
                raise VerifyFailure(
                    f"{direction.name} Faster Caster native multiplier is not maxed: "
                    f"{multiplier}"
                )
            if ratio >= 0.72:
                raise VerifyFailure(
                    f"{direction.name} Faster Caster did not shorten real cast cadence: "
                    f"baseline={baseline:.3f}s upgraded={upgraded:.3f}s ratio={ratio:.3f}"
                )
        if abs(ratios["host_owned"] - ratios["client_owned"]) > 0.15:
            raise VerifyFailure(f"Faster Caster behavior diverged by owner: {ratios}")
        output["cadence_ratios"] = ratios

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts during Faster Caster test: {crashes}")
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
                "cadence_ratios": output.get("cadence_ratios"),
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
