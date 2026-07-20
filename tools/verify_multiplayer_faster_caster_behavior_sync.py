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
from datetime import datetime
from pathlib import Path
from typing import Any

from multiplayer_log_probe import log_after, log_position
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
from verify_multiplayer_battle_siege_behavior_sync import (
    AIR_PRIMARY_ENTRY,
    read_local_cast_observation,
    reset_local_cast_observation,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    clear_local_cast_state,
)
from verify_multiplayer_primary_kill_stress import (
    CLIENT_TARGET,
    HOST_TARGET,
    SETUP_TARGET_HP,
    cleanup_live_enemies,
    find_target_or_last,
    parse_float,
    parse_int,
    place_pair_on_clear_lane,
    prepare_and_queue_caster,
    spawn_one_enemy,
    wait_for_target_hp_at_least,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_faster_caster_behavior_sync.json"
FASTER_CASTER_ROW = 70
PRIMARY_HOLD_FRAMES_PER_CAST = 180
DISCRETE_PRIMARY_ENTRIES = frozenset((8, 16))
CONTINUOUS_PRIMARY_ENTRIES = frozenset((AIR_PRIMARY_ENTRY,))
WARMUP_INTERVAL_COUNT = 1
MEASURED_INTERVAL_COUNT = 10
CADENCE_RATIO_TOLERANCE = 0.12
CONTINUOUS_HOLD_FRAMES = 360
CONTINUOUS_RATE_RATIO_TOLERANCE = 0.45
MINIMUM_CONTINUOUS_DAMAGE_CLAIMS = 5
TARGET_CLEANUP_TIMEOUT_SECONDS = 8.0


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


def arm_cadence_burst(
    direction: Direction,
    target_actor: int,
    target_x: float,
    target_y: float,
    required_casts: int,
) -> dict[str, Any]:
    """Queue one continuous hold with one manual-combat allowance per cast."""
    initial = prepare_and_queue_caster(
        direction,
        target_actor,
        target_x,
        target_y,
        PRIMARY_HOLD_FRAMES_PER_CAST,
    )
    additional = parse_key_values(
        lua(
            direction.source_pipe,
            f"""
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local ok = true
for _ = 2, {required_casts} do
  ok = sd.input.hold_mouse_left_frames({PRIMARY_HOLD_FRAMES_PER_CAST}) and ok
end
emit('ok', ok)
emit('allowances', {required_casts})
emit('frames_per_allowance', {PRIMARY_HOLD_FRAMES_PER_CAST})
""",
            timeout=5.0,
        )
    )
    if additional.get("ok") != "true":
        raise VerifyFailure(
            f"{direction.name} could not arm sustained primary allowances: "
            f"{additional}"
        )
    return {"initial": initial, "additional": additional}


def wait_for_client_enemy_cleanup(
    direction: Direction,
    timeout: float = TARGET_CLEANUP_TIMEOUT_SECONDS,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = find_target_or_last(CLIENT_PIPE, 0.0, 0.0, 0)
        if (
            parse_int(last.get("live_local_count")) == 0
            and parse_int(last.get("rep.tracked_actor_count")) == 0
            and parse_int(last.get("rep.binding_count")) == 0
            and parse_int(last.get("rep.local_actor_count")) == 0
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"{direction.name} client did not retire the primary target: {last}"
    )


def cleanup_primary_target(direction: Direction) -> dict[str, Any]:
    return {
        "host": cleanup_live_enemies(),
        "client": wait_for_client_enemy_cleanup(direction),
    }


def prepare_primary_target(direction: Direction) -> dict[str, Any]:
    """Build one unique replicated, frozen target for primary behavior."""
    cleanup = cleanup_primary_target(direction)
    anchor = HOST_TARGET if direction.source_pipe == HOST_PIPE else CLIENT_TARGET
    lane = place_pair_on_clear_lane(direction, anchor)
    target_x = float(lane["x"])
    target_y = float(lane["y"])
    spawn = spawn_one_enemy(target_x, target_y, setup_hp=SETUP_TARGET_HP)
    network_id = int(spawn["network_actor_id"])
    host_target = wait_for_target_hp_at_least(
        HOST_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=6.0,
        require_local_binding=False,
    )
    client_target = wait_for_target_hp_at_least(
        CLIENT_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=6.0,
    )
    source_target = (
        host_target if direction.source_pipe == HOST_PIPE else client_target
    )
    target_actor = (
        int(spawn["actor_address"])
        if direction.source_pipe == HOST_PIPE
        else parse_int(source_target.get("local.actor_address"))
    )
    if target_actor == 0:
        raise VerifyFailure(
            f"{direction.name} primary target had no source-local actor: "
            f"{source_target}"
        )
    return {
        "cleanup_before": cleanup,
        "lane": lane,
        "spawn": spawn,
        "network_id": network_id,
        "x": target_x,
        "y": target_y,
        "source_actor_address": target_actor,
        "host_target": host_target,
        "client_target": client_target,
    }


def measure_cadence(direction: Direction, timeout: float) -> dict[str, Any]:
    initial_snapshot = query_progression_snapshot(direction.source_pipe)
    primary_entry = int(initial_snapshot["loadout"]["primary_entry"])
    combo_entry = int(initial_snapshot["loadout"]["combo_entry"])
    if (
        primary_entry != combo_entry
        or primary_entry not in DISCRETE_PRIMARY_ENTRIES
    ):
        raise VerifyFailure(
            f"{direction.name} Faster Caster cadence requires a discrete "
            f"pure-primary loadout; primary={primary_entry} combo={combo_entry}"
        )
    resources = set_local_player_vitals(direction.source_pipe, 10000.0, 10000.0)
    pre_clear = clear_local_cast_state(direction)
    target = prepare_primary_target(direction)
    source_offset = log_position(direction.source_log)
    observer_offset = log_position(direction.observer_log)

    required_casts = (
        WARMUP_INTERVAL_COUNT + MEASURED_INTERVAL_COUNT + 1
    )
    queued = arm_cadence_burst(
        direction,
        int(target["source_actor_address"]),
        float(target["x"]),
        float(target["y"]),
        required_casts,
    )
    deadline = time.monotonic() + timeout
    ticks: list[int] = []
    while time.monotonic() < deadline:
        ticks = local_cast_ticks(direction, source_offset)
        if len(ticks) >= required_casts:
            break
        time.sleep(0.02)
    cleared = clear_local_cast_state(direction)
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
    measured_intervals = intervals[WARMUP_INTERVAL_COUNT:]
    accepted = local_accept_count(direction, source_offset)

    remote_count = wait_for_remote_delivery(
        direction,
        observer_offset,
        required_casts,
    )
    snapshot = query_progression_snapshot(direction.source_pipe)
    target_after = wait_for_target_hp_at_least(
        direction.source_pipe,
        float(target["x"]),
        float(target["y"]),
        int(target["network_id"]),
        1.0,
        timeout=4.0,
        require_local_binding=direction.source_pipe != HOST_PIPE,
    )
    cleanup_after = cleanup_primary_target(direction)
    return {
        "primary_entry": primary_entry,
        "combo_entry": combo_entry,
        "resources": resources,
        "pre_clear": pre_clear,
        "target_fixture": target,
        "input_queue": queued,
        "input_clear": cleared,
        "native_tick_ms": sample_ticks,
        "intervals_seconds": intervals,
        "warmup_interval_count": WARMUP_INTERVAL_COUNT,
        "measured_intervals_seconds": measured_intervals,
        "median_seconds": statistics.median(measured_intervals),
        "accepted_count": accepted,
        "remote_delivery_count": remote_count,
        "target_after": target_after,
        "cleanup_after": cleanup_after,
        "cast_speed_multiplier": snapshot["native"]["derived"][
            "cast_speed_multiplier"
        ],
    }


def parse_continuous_channel_window(
    log_text: str,
    primary_entry: int,
) -> dict[str, Any] | None:
    pattern = re.compile(
        r"^\[(?P<timestamp>[^\]]+)\] Multiplayer local cast sent\. "
        r".*?cast_sequence=(?P<sequence>\d+) kind=primary "
        r"secondary_slot=-1 phase=(?P<phase>pressed|released) "
        rf"skill_id={primary_entry}\b",
        re.MULTILINE,
    )
    pressed: dict[str, datetime] = {}
    for match in pattern.finditer(log_text):
        sequence = match.group("sequence")
        timestamp = datetime.fromisoformat(match.group("timestamp"))
        if match.group("phase") == "pressed":
            pressed.setdefault(sequence, timestamp)
            continue
        started = pressed.get(sequence)
        if started is None or timestamp <= started:
            continue
        return {
            "duration_seconds": (timestamp - started).total_seconds(),
            "pressed_count": 1,
            "released_count": 1,
        }
    return None


def wait_for_continuous_channel_window(
    direction: Direction,
    source_offset: int,
    primary_entry: int,
    timeout: float,
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_log = ""
    while time.monotonic() < deadline:
        last_log = log_after(direction.source_log, source_offset)
        window = parse_continuous_channel_window(last_log, primary_entry)
        if window is not None:
            return last_log, window
        time.sleep(0.03)
    raise VerifyFailure(
        f"{direction.name} continuous primary did not complete one native "
        f"pressed/held/released channel within {timeout:.1f}s"
    )


def wait_for_authoritative_damage(
    direction: Direction,
    target: dict[str, Any],
    before_hp: float,
    timeout: float = 6.0,
) -> tuple[dict[str, str], float]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    previous_damage = 0.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = find_target_or_last(
            HOST_PIPE,
            float(target["x"]),
            float(target["y"]),
            int(target["network_id"]),
        )
        after_hp = parse_float(last.get("snapshot.hp"), before_hp)
        damage = before_hp - after_hp
        now = time.monotonic()
        if damage > 0.0:
            if abs(damage - previous_damage) <= 0.0005:
                stable_since = stable_since or now
                if now - stable_since >= 0.5:
                    return last, damage
            else:
                stable_since = None
                previous_damage = damage
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} continuous primary produced no stable authoritative "
        f"damage: before_hp={before_hp} last={last}"
    )


def measure_continuous_damage_rate(
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    initial_snapshot = query_progression_snapshot(direction.source_pipe)
    primary_entry = int(initial_snapshot["loadout"]["primary_entry"])
    combo_entry = int(initial_snapshot["loadout"]["combo_entry"])
    if (
        primary_entry != combo_entry
        or primary_entry not in CONTINUOUS_PRIMARY_ENTRIES
    ):
        raise VerifyFailure(
            f"{direction.name} Faster Caster continuous-rate measurement "
            f"requires a continuous primary; primary={primary_entry} "
            f"combo={combo_entry}"
        )

    resources = set_local_player_vitals(direction.source_pipe, 10000.0, 10000.0)
    pre_clear = clear_local_cast_state(direction)
    target = prepare_primary_target(direction)
    network_id = int(target["network_id"])
    observation_reset = reset_local_cast_observation(
        direction.source_pipe,
        network_id,
    )
    before_hp = parse_float(target["host_target"].get("snapshot.hp"), 0.0)
    if before_hp <= 0.0:
        raise VerifyFailure(
            f"{direction.name} continuous target had invalid authoritative HP: "
            f"{target['host_target']}"
        )

    source_offset = log_position(direction.source_log)
    observer_offset = log_position(direction.observer_log)
    queued = prepare_and_queue_caster(
        direction,
        int(target["source_actor_address"]),
        float(target["x"]),
        float(target["y"]),
        CONTINUOUS_HOLD_FRAMES,
    )
    source_log, channel_window = wait_for_continuous_channel_window(
        direction,
        source_offset,
        primary_entry,
        timeout,
    )
    cleared = clear_local_cast_state(direction)
    remote_count = wait_for_remote_delivery(
        direction,
        observer_offset,
        1,
    )
    target_after, authoritative_damage = wait_for_authoritative_damage(
        direction,
        target,
        before_hp,
    )
    observation = read_local_cast_observation(
        direction.source_pipe,
        network_id,
    )
    if direction.source_pipe == CLIENT_PIPE:
        if (
            not observation["damage_claim_valid"]
            or observation["damage_associated_claim_count"]
            < MINIMUM_CONTINUOUS_DAMAGE_CLAIMS
            or observation["damage_unassociated_claim_count"] != 0
            or not observation["damage_associated_skill_consistent"]
            or observation["damage_associated_skill_id"] != primary_entry
        ):
            raise VerifyFailure(
                f"{direction.name} continuous Air damage claims were not "
                f"cleanly associated with the active primary: {observation}"
            )

    duration_seconds = float(channel_window["duration_seconds"])
    if duration_seconds <= 0.0:
        raise VerifyFailure(
            f"{direction.name} continuous channel duration was invalid: "
            f"{channel_window}"
        )
    snapshot = query_progression_snapshot(direction.source_pipe)
    cleanup_after = cleanup_primary_target(direction)
    return {
        "primary_entry": primary_entry,
        "combo_entry": combo_entry,
        "resources": resources,
        "pre_clear": pre_clear,
        "target_fixture": target,
        "observation_reset": observation_reset,
        "input_queue": queued,
        "input_clear": cleared,
        "channel_window": channel_window,
        "local_pressed_count": source_log.count(
            f"phase=pressed skill_id={primary_entry}"
        ),
        "local_released_count": source_log.count(
            f"phase=released skill_id={primary_entry}"
        ),
        "remote_delivery_count": remote_count,
        "authoritative_damage": authoritative_damage,
        "authoritative_damage_per_second": (
            authoritative_damage / duration_seconds
        ),
        "cast_observation": observation,
        "target_after": target_after,
        "cleanup_after": cleanup_after,
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
    """Measure a clean manual-spawner combat phase for both participant owners.

    The stock wave state is primed without ambient enemies. This keeps native
    primary control available while preventing one owner's acquired target from
    contaminating the next owner's cadence or targeted-progression assertions.
    """
    phase: dict[str, Any] = {"upgraded": upgraded}
    try:
        startup = launch_pair_ready(
            timeout,
            god_mode=False,
            manual_combat=True,
        )
        phase["launch"] = startup["launch"]
        phase["manual_combat"] = startup["manual_combat"]
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
        phase["cadence"] = {
            direction.name: measure_cadence(direction, timeout)
            for direction in DIRECTIONS
        }
        return phase
    finally:
        if retire_pair:
            stop_games()


def verify_cadence_contracts(
    directions: tuple[Direction, ...],
    baseline: dict[str, dict[str, Any]],
    upgraded: dict[str, dict[str, Any]],
) -> dict[str, float]:
    ratios: dict[str, float] = {}
    for direction in directions:
        baseline_seconds = float(baseline[direction.name]["median_seconds"])
        upgraded_seconds = float(upgraded[direction.name]["median_seconds"])
        ratio = upgraded_seconds / baseline_seconds
        ratios[direction.name] = ratio
        baseline_multiplier = float(
            baseline[direction.name]["cast_speed_multiplier"]
        )
        multiplier = float(upgraded[direction.name]["cast_speed_multiplier"])
        if multiplier < 1.99:
            raise VerifyFailure(
                f"{direction.name} Faster Caster native multiplier is not maxed: "
                f"{multiplier}"
            )
        expected_ratio = baseline_multiplier / multiplier
        if abs(ratio - expected_ratio) > CADENCE_RATIO_TOLERANCE:
            raise VerifyFailure(
                f"{direction.name} Faster Caster cadence does not match its "
                f"native multiplier: "
                f"baseline={baseline_seconds:.3f}s "
                f"upgraded={upgraded_seconds:.3f}s ratio={ratio:.3f} "
                f"expected={expected_ratio:.3f}"
            )
    if abs(ratios["host_owned"] - ratios["client_owned"]) > 0.12:
        raise VerifyFailure(f"Faster Caster behavior diverged by owner: {ratios}")
    return ratios


def verify_continuous_rate_contracts(
    directions: tuple[Direction, ...],
    baseline: dict[str, dict[str, Any]],
    upgraded: dict[str, dict[str, Any]],
) -> dict[str, float]:
    ratios: dict[str, float] = {}
    for direction in directions:
        baseline_rate = float(
            baseline[direction.name]["authoritative_damage_per_second"]
        )
        upgraded_rate = float(
            upgraded[direction.name]["authoritative_damage_per_second"]
        )
        if baseline_rate <= 0.0 or upgraded_rate <= 0.0:
            raise VerifyFailure(
                f"{direction.name} Faster Caster continuous damage rate was "
                f"invalid: baseline={baseline_rate} upgraded={upgraded_rate}"
            )
        ratio = upgraded_rate / baseline_rate
        ratios[direction.name] = ratio
        baseline_multiplier = float(
            baseline[direction.name]["cast_speed_multiplier"]
        )
        upgraded_multiplier = float(
            upgraded[direction.name]["cast_speed_multiplier"]
        )
        if upgraded_multiplier < 1.99:
            raise VerifyFailure(
                f"{direction.name} Faster Caster native multiplier is not "
                f"maxed: {upgraded_multiplier}"
            )
        expected_ratio = upgraded_multiplier / baseline_multiplier
        if abs(ratio - expected_ratio) > CONTINUOUS_RATE_RATIO_TOLERANCE:
            raise VerifyFailure(
                f"{direction.name} Faster Caster continuous damage rate does "
                f"not match its native multiplier: baseline={baseline_rate:.4f} "
                f"upgraded={upgraded_rate:.4f} ratio={ratio:.3f} "
                f"expected={expected_ratio:.3f}"
            )
    if abs(ratios["host_owned"] - ratios["client_owned"]) > 0.50:
        raise VerifyFailure(
            f"Faster Caster continuous behavior diverged by owner: {ratios}"
        )
    return ratios


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

        output["cadence_ratios"] = verify_cadence_contracts(
            DIRECTIONS,
            output["baseline"],
            output["upgraded"],
        )

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
