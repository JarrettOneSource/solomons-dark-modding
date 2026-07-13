#!/usr/bin/env python3
"""Verify Regenerate's timed healing and mana hoard for either owner."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_persistent_status_harness import (
    PERSISTENT_REGENERATE,
    query_persistent_status,
)
from multiplayer_progression_probe import query_ranked_numeric_stat
from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
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
)
from verify_multiplayer_persistent_status_sync import toggle_once
from verify_player_health_death_sync import set_local_player_vitals


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_regenerate_behavior_sync.json"
REGENERATE_ROW = 0x4F
START_HP = 25.0
MAX_HP = 50.0
START_MP = 100.0
MAX_MP = 100.0
BASELINE_SECONDS = 1.8
ACTIVE_SECONDS = 3.8
RESTORED_SECONDS = 1.8
EXPECTED_NATIVE_HEAL_PER_SECOND = 1.5
HEAL_RATE_TOLERANCE = 0.20


def observer_pipe(direction: Direction) -> str:
    return HOST_PIPE if direction.source_pipe == CLIENT_PIPE else CLIENT_PIPE


def wait_for_vitals(
    direction: Direction,
    expected_hp: float | None,
    expected_mp: float,
    timeout: float,
    *,
    hp_tolerance: float = 0.20,
    mp_tolerance: float = 0.75,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts = 0
    owner: dict[str, Any] = {}
    observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        owner = query_persistent_status(direction.source_pipe)
        observer = query_persistent_status(
            observer_pipe(direction),
            participant_id=direction.source_id,
        )
        hp_matches = (
            abs(owner["hp"] - observer["hp"]) <= hp_tolerance
            if expected_hp is None
            else math.isclose(owner["hp"], expected_hp, abs_tol=hp_tolerance)
            and math.isclose(observer["hp"], expected_hp, abs_tol=hp_tolerance)
        )
        if (
            hp_matches
            and math.isclose(owner["mp"], expected_mp, abs_tol=mp_tolerance)
            and math.isclose(observer["mp"], expected_mp, abs_tol=mp_tolerance)
            and math.isclose(owner["max_hp"], MAX_HP, abs_tol=0.20)
            and math.isclose(observer["max_hp"], MAX_HP, abs_tol=0.20)
            and math.isclose(owner["max_mp"], MAX_MP, abs_tol=0.20)
            and math.isclose(observer["max_mp"], MAX_MP, abs_tol=0.20)
        ):
            return {
                "attempt_count": attempts,
                "owner": owner,
                "observer": observer,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} vitals did not converge to hp={expected_hp} "
        f"mp={expected_mp}: owner={owner} observer={observer}"
    )


def sample_vitals_for(
    direction: Direction,
    duration: float,
) -> dict[str, Any]:
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    while True:
        elapsed = time.monotonic() - started
        owner = query_persistent_status(direction.source_pipe)
        observer = query_persistent_status(
            observer_pipe(direction),
            participant_id=direction.source_id,
        )
        samples.append(
            {
                "elapsed": elapsed,
                "owner_hp": owner["hp"],
                "observer_hp": observer["hp"],
                "owner_mp": owner["mp"],
                "observer_mp": observer["mp"],
            }
        )
        if elapsed >= duration:
            break
        time.sleep(0.10)
    return {
        "duration": time.monotonic() - started,
        "sample_count": len(samples),
        "first": samples[0],
        "last": samples[-1],
        "max_owner_observer_hp_error": max(
            abs(sample["owner_hp"] - sample["observer_hp"])
            for sample in samples
        ),
        "max_owner_observer_mp_error": max(
            abs(sample["owner_mp"] - sample["observer_mp"])
            for sample in samples
        ),
        "samples": samples,
    }


def assert_stable_hp(
    direction: Direction,
    label: str,
    trial: dict[str, Any],
    tolerance: float = 0.20,
) -> None:
    owner_delta = trial["last"]["owner_hp"] - trial["first"]["owner_hp"]
    observer_delta = (
        trial["last"]["observer_hp"] - trial["first"]["observer_hp"]
    )
    if abs(owner_delta) > tolerance or abs(observer_delta) > tolerance:
        raise VerifyFailure(
            f"{direction.name} {label} HP changed while Regenerate was off: "
            f"owner_delta={owner_delta} observer_delta={observer_delta}"
        )


def assert_regeneration(
    direction: Direction,
    trial: dict[str, Any],
) -> dict[str, Any]:
    elapsed = trial["last"]["elapsed"] - trial["first"]["elapsed"]
    owner_delta = trial["last"]["owner_hp"] - trial["first"]["owner_hp"]
    observer_delta = (
        trial["last"]["observer_hp"] - trial["first"]["observer_hp"]
    )
    owner_rate = owner_delta / elapsed
    observer_rate = observer_delta / elapsed
    if not math.isclose(
        owner_rate,
        EXPECTED_NATIVE_HEAL_PER_SECOND,
        abs_tol=HEAL_RATE_TOLERANCE,
    ):
        raise VerifyFailure(
            f"{direction.name} Regenerate did not heal at the native cadence: "
            f"owner_rate={owner_rate} trial={trial}"
        )
    if not math.isclose(
        observer_rate,
        owner_rate,
        abs_tol=HEAL_RATE_TOLERANCE,
    ):
        raise VerifyFailure(
            f"{direction.name} observer Regenerate healing diverged: "
            f"owner_rate={owner_rate} observer_rate={observer_rate}"
        )
    if trial["max_owner_observer_hp_error"] > 1.05:
        raise VerifyFailure(
            f"{direction.name} Regenerate observer lag exceeded one native tick: "
            f"{trial['max_owner_observer_hp_error']}"
        )
    return {
        "owner_healed": owner_delta,
        "observer_healed": observer_delta,
        "owner_heal_per_second": owner_rate,
        "observer_heal_per_second": observer_rate,
        "expected_native_heal_per_second": EXPECTED_NATIVE_HEAL_PER_SECOND,
        "configured_description": "1 HP every 1.5 seconds",
        "description_matches_native_rate": False,
        "max_owner_observer_hp_error": trial["max_owner_observer_hp_error"],
        "ok": True,
    }


def run_direction(
    direction: Direction,
    acquisition: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    resource_reset = set_local_player_vitals(
        direction.source_pipe,
        START_HP,
        MAX_HP,
        mp=START_MP,
        max_mp=MAX_MP,
    )
    baseline_convergence = wait_for_vitals(
        direction,
        START_HP,
        START_MP,
        timeout,
    )
    baseline = sample_vitals_for(direction, BASELINE_SECONDS)
    assert_stable_hp(direction, "baseline", baseline)

    activated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=PERSISTENT_REGENERATE,
        timeout=timeout,
    )
    hoard_property = query_ranked_numeric_stat(
        direction.source_pipe,
        REGENERATE_ROW,
        "mHoard",
    )
    if not hoard_property["property_found"]:
        raise VerifyFailure(
            f"{direction.name} Regenerate mHoard is unavailable: {hoard_property}"
        )
    expected_mp = MAX_MP * (
        1.0 - float(hoard_property["value"]) / 100.0
    )
    activation_convergence = wait_for_vitals(
        direction,
        None,
        expected_mp,
        timeout,
        hp_tolerance=1.05,
    )
    active_resource_reset = set_local_player_vitals(
        direction.source_pipe,
        START_HP,
        MAX_HP,
        mp=START_MP,
        max_mp=MAX_MP,
    )
    active_convergence = wait_for_vitals(
        direction,
        START_HP,
        expected_mp,
        timeout,
        hp_tolerance=1.05,
    )
    active = sample_vitals_for(direction, ACTIVE_SECONDS)
    behavior = assert_regeneration(direction, active)

    deactivated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=0,
        timeout=timeout,
    )
    restored = sample_vitals_for(direction, RESTORED_SECONDS)
    assert_stable_hp(direction, "restored", restored)
    return {
        "resource_reset": resource_reset,
        "baseline_convergence": baseline_convergence,
        "baseline": baseline,
        "activated": activated,
        "hoard_property": hoard_property,
        "expected_active_mp": expected_mp,
        "activation_convergence": activation_convergence,
        "active_resource_reset": active_resource_reset,
        "active_convergence": active_convergence,
        "active": active,
        "behavior": behavior,
        "deactivated": deactivated,
        "restored": restored,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0)
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
        )
        output["launch"] = startup["launch"]
        output["combat_prelude"] = enable_unsuppressed_combat_prelude(
            args.timeout
        )
        output["post_run_progression_ready"] = (
            wait_for_post_run_progression_ready(args.timeout)
        )
        acquisitions = {
            direction.name: acquire_secondary_to_rank(
                direction,
                REGENERATE_ROW,
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
                f"new crash artifacts during Regenerate test: {crashes}"
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
