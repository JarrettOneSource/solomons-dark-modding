#!/usr/bin/env python3
"""Verify exact-native Resist Magic/Poison and natural Deflect sync."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_defense_behavior_harness import (
    invoke_native_magic_hit_trial,
)
from multiplayer_progression_probe import query_progression_snapshot
from multiplayer_transient_status_harness import (
    clear_local_native_poison_status,
    inject_native_poison_status,
    query_poison_status,
    wait_for_poison_state,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    stop_games,
)
from verify_multiplayer_all_stat_sync import (
    compact_snapshot,
    load_stat_contract_values,
    wait_for_derived_parity,
)
from verify_multiplayer_all_upgrade_sync import (
    build_and_verify_catalog,
    enable_quiet_progression_test_mode,
    load_skill_configs,
    new_crash_artifacts,
    wait_for_catalog_views,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_battle_siege_behavior_sync import max_stat_for_target
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime/multiplayer_defense_behavior_sync.json"
RESIST_MAGIC_ROW = 62
DEFLECT_ROW = 68
RESIST_POISON_ROW = 69
POISON_DURATION_TICKS = 1200
POISON_DAMAGE_PER_TICK = 0.125
# PlayerActor's downstream damage path caps a single hit at 25% of current
# native max life. Keep this below the stock test character's 25-point cap so
# the trial isolates the +0xA4 Resist Magic multiplier.
MAGIC_DAMAGE = 20.0
DEFLECT_TRIAL_DAMAGE = 1.0
DEFLECT_TRIAL_ATTEMPTS = 128


@dataclass(frozen=True)
class Direction:
    name: str
    participant_id: int
    owner_pipe: str
    observer_pipe: str


DIRECTIONS = (
    Direction("host_owned", HOST_ID, HOST_PIPE, CLIENT_PIPE),
    Direction("client_owned", CLIENT_ID, CLIENT_PIPE, HOST_PIPE),
)


def prepare_progression_session(
    timeout: float,
    *,
    wave_override: Path | None,
) -> dict[str, Any]:
    startup = launch_pair_ready(
        timeout,
        god_mode=False,
        manual_combat=False,
        prearm_manual_spawner=True,
        wave_override=wave_override,
    )
    quiet = enable_quiet_progression_test_mode()
    ready = wait_for_post_run_progression_ready(timeout)
    catalog_result = build_and_verify_catalog(
        wait_for_catalog_views(timeout),
        load_skill_configs(),
    )
    catalog = catalog_result["catalog"]
    return {
        "startup": startup,
        "quiet": quiet,
        "ready": ready,
        "catalog_result": catalog_result,
        "catalog": catalog,
        "contract_values": load_stat_contract_values(catalog),
        "initial": {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        },
    }


def max_stat_for_both(
    session: dict[str, Any],
    row: int,
    timeout: float,
) -> dict[str, Any]:
    return {
        direction.name: max_stat_for_target(
            session["catalog"],
            row,
            direction.participant_id,
            session["initial"],
            session["contract_values"],
            timeout,
        )
        for direction in DIRECTIONS
    }


def capture_derived_views(row: int, timeout: float) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for direction in DIRECTIONS:
        owner, observer = wait_for_derived_parity(direction.participant_id, timeout)
        views[direction.name] = {
            "owner": compact_snapshot(owner, row),
            "observer": compact_snapshot(observer, row),
            "derived": owner["native"]["derived"],
        }
    return views


def run_natural_stat_direction(
    *,
    direction: Direction,
    timeout: float,
    row: int,
    wave_override: Path,
    sample_seconds: float,
    sample_count: int,
    derived_field: str,
    attack_distance: float,
) -> dict[str, Any]:
    session = prepare_progression_session(timeout, wave_override=wave_override)
    result: dict[str, Any] = {
        "startup": session["startup"],
        "quiet": session["quiet"],
        "ready": session["ready"],
        "wave": start_natural_enemy_wave(),
    }
    result["baseline"] = measure_natural_damage(
        owner_pipe=direction.owner_pipe,
        observer_pipe=direction.observer_pipe,
        participant_id=direction.participant_id,
        seconds=sample_seconds,
        samples=sample_count,
        timeout=timeout,
        attack_distance=attack_distance,
    )
    set_enemy_mode("park")
    result["upgrade"] = max_stat_for_target(
        session["catalog"],
        row,
        direction.participant_id,
        session["initial"],
        session["contract_values"],
        timeout,
    )
    owner, observer = wait_for_derived_parity(direction.participant_id, timeout)
    result["view"] = {
        "owner": compact_snapshot(owner, row),
        "observer": compact_snapshot(observer, row),
        "derived": owner["native"]["derived"],
    }
    result["upgraded"] = measure_natural_damage(
        owner_pipe=direction.owner_pipe,
        observer_pipe=direction.observer_pipe,
        participant_id=direction.participant_id,
        seconds=sample_seconds,
        samples=sample_count,
        timeout=timeout,
        attack_distance=attack_distance,
    )
    set_enemy_mode("park")

    baseline_rate = float(result["baseline"]["damage_per_second"])
    upgraded_rate = float(result["upgraded"]["damage_per_second"])
    ratio = upgraded_rate / baseline_rate
    derived_value = float(result["view"]["derived"][derived_field])
    contract = {
        "baseline_damage_per_second": baseline_rate,
        "upgraded_damage_per_second": upgraded_rate,
        "upgraded_to_baseline_ratio": ratio,
        derived_field: derived_value,
    }
    if row == DEFLECT_ROW:
        chance_percent = derived_value
        chance = max(0, min(int(round(chance_percent)), 100))
        expected_deflected = (chance + min(chance, 28)) / 128.0
        expected_ratio = 1.0 - expected_deflected
        contract["expected_ratio"] = expected_ratio
        if chance_percent < 9.0 or ratio >= 0.98 or ratio <= 0.60:
            raise VerifyFailure(
                f"{direction.name} natural Deflect damage frequency was not "
                f"materially stock-like: {contract}"
            )
        if abs(ratio - expected_ratio) > 0.20:
            raise VerifyFailure(
                f"{direction.name} natural Deflect ratio missed the recovered RNG "
                f"contract: {contract}"
            )
    result["contract"] = contract
    return result


def run_natural_stat_matrix(**kwargs: Any) -> dict[str, Any]:
    directions: dict[str, Any] = {}
    for direction in DIRECTIONS:
        directions[direction.name] = run_natural_stat_direction(
            direction=direction,
            **kwargs,
        )
        stop_games()
    return {
        "directions": directions,
        "contracts": {
            name: value["contract"] for name, value in directions.items()
        },
        "baseline": {
            name: value["baseline"] for name, value in directions.items()
        },
        "upgraded": {
            name: value["upgraded"] for name, value in directions.items()
        },
    }


def wait_for_owner_mirror_life(
    direction: Direction,
    expected: float,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    owner: dict[str, Any] = {}
    mirror: dict[str, Any] = {}
    while time.monotonic() < deadline:
        owner = query_poison_status(direction.owner_pipe)
        mirror = query_poison_status(
            direction.observer_pipe,
            participant_id=direction.participant_id,
        )
        if (
            abs(owner["hp"] - expected) <= 0.2
            and abs(mirror["hp"] - owner["hp"]) <= 0.2
        ):
            return owner, mirror
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} life did not settle before defense trial: "
        f"owner={owner} mirror={mirror}"
    )


def wait_for_owner_mirror_damage_convergence(
    direction: Direction,
    hp_before: float,
    minimum_damage: float,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    owner: dict[str, Any] = {}
    mirror: dict[str, Any] = {}
    while time.monotonic() < deadline:
        owner = query_poison_status(direction.owner_pipe)
        mirror = query_poison_status(
            direction.observer_pipe,
            participant_id=direction.participant_id,
        )
        if (
            owner["hp"] <= hp_before - minimum_damage
            and abs(mirror["hp"] - owner["hp"]) <= 0.2
        ):
            return owner, mirror
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} damaged owner/mirror life did not converge: "
        f"before={hp_before:.3f} minimum_damage={minimum_damage:.3f} "
        f"owner_hp={owner.get('hp')} mirror_hp={mirror.get('hp')}"
    )


def run_magic_trial(direction: Direction, label: str, timeout: float) -> dict[str, Any]:
    set_local_player_vitals(direction.owner_pipe, 1000.0, 1000.0)
    owner_before, mirror_before = wait_for_owner_mirror_life(
        direction, 1000.0, timeout
    )
    trial = invoke_native_magic_hit_trial(
        direction.owner_pipe,
        projectile_damage=0.0,
        magic_damage=MAGIC_DAMAGE,
        attempts=1,
        label=f"{direction.name}_{label}",
        timeout=timeout,
    )
    exact_delta = float(trial["hp_delta"])
    owner_after, mirror_after = wait_for_owner_mirror_damage_convergence(
        direction,
        float(trial["hp_before"]),
        max(0.25, exact_delta * 0.25),
        timeout,
    )
    return {
        "owner_before": owner_before,
        "mirror_before": mirror_before,
        "trial": trial,
        "owner_after": owner_after,
        "mirror_after": mirror_after,
    }


def run_magic_stat_session(timeout: float) -> dict[str, Any]:
    session = prepare_progression_session(timeout, wave_override=None)
    result: dict[str, Any] = {
        "startup": session["startup"],
        "quiet": session["quiet"],
        "ready": session["ready"],
    }
    result["baseline"] = {
        direction.name: run_magic_trial(direction, "baseline", timeout)
        for direction in DIRECTIONS
    }
    result["upgrades"] = max_stat_for_both(session, RESIST_MAGIC_ROW, timeout)
    result["views"] = capture_derived_views(RESIST_MAGIC_ROW, timeout)
    result["upgraded"] = {
        direction.name: run_magic_trial(direction, "upgraded", timeout)
        for direction in DIRECTIONS
    }

    contracts: dict[str, Any] = {}
    for direction in DIRECTIONS:
        fraction = float(
            result["views"][direction.name]["derived"]["resist_magic_fraction"]
        )
        baseline_delta = float(
            result["baseline"][direction.name]["trial"]["hp_delta"]
        )
        upgraded_delta = float(
            result["upgraded"][direction.name]["trial"]["hp_delta"]
        )
        expected_upgraded_delta = MAGIC_DAMAGE * (1.0 - fraction)
        ratio = upgraded_delta / baseline_delta
        contract = {
            "resist_fraction": fraction,
            "baseline_damage": baseline_delta,
            "upgraded_damage": upgraded_delta,
            "expected_upgraded_damage": expected_upgraded_delta,
            "upgraded_to_baseline_ratio": ratio,
            "expected_ratio": 1.0 - fraction,
        }
        contracts[direction.name] = contract
        if abs(baseline_delta - MAGIC_DAMAGE) > 0.5:
            raise VerifyFailure(
                f"{direction.name} baseline stock magic damage drifted: {contract}"
            )
        if fraction < 0.75 or abs(upgraded_delta - expected_upgraded_delta) > 0.5:
            raise VerifyFailure(
                f"{direction.name} Resist Magic behavior was not stock-like: {contract}"
            )
    result["contracts"] = contracts
    return result


def run_deflect_trial(direction: Direction, label: str, timeout: float) -> dict[str, Any]:
    set_local_player_vitals(direction.owner_pipe, 1000.0, 1000.0)
    owner_before, mirror_before = wait_for_owner_mirror_life(
        direction, 1000.0, timeout
    )
    trial = invoke_native_magic_hit_trial(
        direction.owner_pipe,
        projectile_damage=DEFLECT_TRIAL_DAMAGE,
        magic_damage=0.0,
        attempts=DEFLECT_TRIAL_ATTEMPTS,
        label=f"{direction.name}_{label}",
        timeout=timeout,
    )
    exact_delta = float(trial["hp_delta"])
    owner_after, mirror_after = wait_for_owner_mirror_damage_convergence(
        direction,
        float(trial["hp_before"]),
        max(1.0, exact_delta * 0.25),
        timeout,
    )
    return {
        "owner_before": owner_before,
        "mirror_before": mirror_before,
        "trial": trial,
        "owner_after": owner_after,
        "mirror_after": mirror_after,
    }


def run_deflect_stat_direction(
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    session = prepare_progression_session(timeout, wave_override=None)
    result: dict[str, Any] = {
        "startup": session["startup"],
        "quiet": session["quiet"],
        "ready": session["ready"],
    }
    result["baseline"] = run_deflect_trial(direction, "baseline", timeout)
    result["upgrade"] = max_stat_for_target(
        session["catalog"],
        DEFLECT_ROW,
        direction.participant_id,
        session["initial"],
        session["contract_values"],
        timeout,
    )
    owner, observer = wait_for_derived_parity(direction.participant_id, timeout)
    result["view"] = {
        "owner": compact_snapshot(owner, DEFLECT_ROW),
        "observer": compact_snapshot(observer, DEFLECT_ROW),
        "derived": owner["native"]["derived"],
    }
    result["upgraded"] = run_deflect_trial(direction, "upgraded", timeout)

    chance_percent = float(result["view"]["derived"]["deflect_chance"])
    chance = max(0, min(int(round(chance_percent)), 100))
    expected_deflected_fraction = (chance + min(chance, 28)) / 128.0
    baseline_damage = float(result["baseline"]["trial"]["hp_delta"])
    upgraded_damage = float(result["upgraded"]["trial"]["hp_delta"])
    baseline_average_damage = baseline_damage / DEFLECT_TRIAL_ATTEMPTS
    actual_deflected = (
        baseline_damage - upgraded_damage
    ) / baseline_average_damage
    expected_deflected = DEFLECT_TRIAL_ATTEMPTS * expected_deflected_fraction
    contract = {
        "deflect_chance": chance_percent,
        "attempts": DEFLECT_TRIAL_ATTEMPTS,
        "baseline_damage": baseline_damage,
        "baseline_average_damage": baseline_average_damage,
        "upgraded_damage": upgraded_damage,
        "actual_deflected_hits": actual_deflected,
        "expected_deflected_hits": expected_deflected,
        "actual_deflected_fraction": actual_deflected / DEFLECT_TRIAL_ATTEMPTS,
        "expected_deflected_fraction": expected_deflected_fraction,
    }
    if (
        baseline_damage <= DEFLECT_TRIAL_ATTEMPTS * 0.75
        or baseline_damage > DEFLECT_TRIAL_ATTEMPTS * 1.05
    ):
        raise VerifyFailure(
            f"{direction.name} baseline native projectile accounting drifted: "
            f"{contract}"
        )
    if (
        chance_percent < 9.0
        or actual_deflected < 5.0
        or abs(actual_deflected - expected_deflected) > 16
    ):
        raise VerifyFailure(
            f"{direction.name} native Deflect behavior was not stock-like: "
            f"{contract}"
        )
    result["contract"] = contract
    return result


def run_deflect_stat_session(timeout: float) -> dict[str, Any]:
    directions: dict[str, Any] = {}
    for direction in DIRECTIONS:
        directions[direction.name] = run_deflect_stat_direction(
            direction,
            timeout,
        )
        stop_games()
    return {
        "directions": directions,
        "contracts": {
            name: value["contract"] for name, value in directions.items()
        },
        "baseline": {
            name: value["baseline"] for name, value in directions.items()
        },
        "upgraded": {
            name: value["upgraded"] for name, value in directions.items()
        },
    }


def run_poison_trial(direction: Direction, label: str, timeout: float) -> dict[str, Any]:
    owner_before = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=False,
        timeout=timeout,
    )
    mirror_before = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=False,
        timeout=timeout,
    )
    set_local_player_vitals(direction.owner_pipe, 1000.0, 1000.0)
    owner_before, mirror_before = wait_for_owner_mirror_life(
        direction, 1000.0, timeout
    )
    injection_pipe = direction.owner_pipe
    injection_participant_id: int | None = None
    if direction.participant_id == CLIENT_ID:
        injection_pipe = direction.observer_pipe
        injection_participant_id = direction.participant_id
    injection = inject_native_poison_status(
        injection_pipe,
        participant_id=injection_participant_id,
        duration_ticks=POISON_DURATION_TICKS,
        damage_per_tick=POISON_DAMAGE_PER_TICK,
        source_slot=0,
        label=f"{direction.name}_{label}",
    )
    owner_active = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=True,
        timeout=timeout,
    )
    mirror_active = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=True,
        timeout=timeout,
    )
    if not math.isclose(
        owner_active["damage_per_tick"], POISON_DAMAGE_PER_TICK, abs_tol=1e-6
    ):
        raise VerifyFailure(
            f"{direction.name} owner poison lost real damage behavior: {owner_active}"
        )
    if not math.isclose(mirror_active["damage_per_tick"], 0.0, abs_tol=1e-7):
        raise VerifyFailure(
            f"{direction.name} observer poison was not inert: {mirror_active}"
        )

    deadline = time.monotonic() + min(timeout, 8.0)
    owner_damage_observed: dict[str, Any] = {}
    while time.monotonic() < deadline:
        owner_damage_observed = query_poison_status(direction.owner_pipe)
        if owner_damage_observed["hp"] < owner_before["hp"] - 0.01:
            break
        time.sleep(0.05)
    else:
        raise VerifyFailure(
            f"{direction.name} owner poison did not deal native damage: "
            f"owner={owner_damage_observed}"
        )

    clear = clear_local_native_poison_status(direction.owner_pipe)
    owner_cleared = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=False,
        timeout=timeout,
    )
    mirror_cleared = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=False,
        timeout=timeout,
    )
    owner_damaged, mirror_damaged = wait_for_owner_mirror_damage_convergence(
        direction,
        owner_before["hp"],
        0.01,
        timeout,
    )
    return {
        "owner_before": owner_before,
        "mirror_before": mirror_before,
        "injection": injection,
        "owner_active": owner_active,
        "mirror_active": mirror_active,
        "owner_damage_observed": owner_damage_observed,
        "owner_damaged": owner_damaged,
        "mirror_damaged": mirror_damaged,
        "owner_hp_delta": owner_before["hp"] - owner_damaged["hp"],
        "clear": clear,
        "owner_cleared": owner_cleared,
        "mirror_cleared": mirror_cleared,
    }


def run_poison_stat_session(timeout: float) -> dict[str, Any]:
    session = prepare_progression_session(timeout, wave_override=None)
    result: dict[str, Any] = {
        "startup": session["startup"],
        "quiet": session["quiet"],
        "ready": session["ready"],
    }
    result["baseline"] = {
        direction.name: run_poison_trial(direction, "baseline", timeout)
        for direction in DIRECTIONS
    }
    result["upgrades"] = max_stat_for_both(
        session, RESIST_POISON_ROW, timeout
    )
    result["views"] = capture_derived_views(RESIST_POISON_ROW, timeout)
    result["upgraded"] = {
        direction.name: run_poison_trial(direction, "upgraded", timeout)
        for direction in DIRECTIONS
    }
    contracts: dict[str, Any] = {}
    for direction in DIRECTIONS:
        fraction = float(
            result["views"][direction.name]["derived"]["resist_poison_fraction"]
        )
        baseline_ticks = int(
            result["baseline"][direction.name]["injection"]["duration_after_apply"]
        )
        upgraded_ticks = int(
            result["upgraded"][direction.name]["injection"]["duration_after_apply"]
        )
        expected_ticks = POISON_DURATION_TICKS - math.trunc(
            POISON_DURATION_TICKS * fraction
        )
        contract = {
            "resist_fraction": fraction,
            "baseline_duration_ticks": baseline_ticks,
            "upgraded_duration_ticks": upgraded_ticks,
            "expected_duration_ticks": expected_ticks,
        }
        contracts[direction.name] = contract
        if abs(baseline_ticks - POISON_DURATION_TICKS) > 3:
            raise VerifyFailure(
                f"{direction.name} baseline poison duration was not stock: {contract}"
            )
        if abs(upgraded_ticks - expected_ticks) > 3:
            raise VerifyFailure(
                f"{direction.name} Resist Poison duration was not stock-like: {contract}"
            )
    result["contracts"] = contracts
    return result


def compact_natural_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "contracts": session.get("contracts", {}),
        "baseline_damage": {
            name: result.get("total_damage")
            for name, result in session.get("baseline", {}).items()
        },
        "upgraded_damage": {
            name: result.get("total_damage")
            for name, result in session.get("upgraded", {}).items()
        },
    }


def compact_magic_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "contracts": session.get("contracts", {}),
        "baseline_damage": {
            name: result.get("trial", {}).get("hp_delta")
            for name, result in session.get("baseline", {}).items()
        },
        "upgraded_damage": {
            name: result.get("trial", {}).get("hp_delta")
            for name, result in session.get("upgraded", {}).items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=35.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["resist_magic"] = run_magic_stat_session(args.timeout)
        stop_games()
        output["deflect"] = run_deflect_stat_session(args.timeout)
        stop_games()
        output["resist_poison"] = run_poison_stat_session(args.timeout)
        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts during defense test: {crashes}")
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
                "resist_magic": compact_magic_session(
                    output.get("resist_magic", {})
                ),
                "deflect": compact_magic_session(output.get("deflect", {})),
                "resist_poison": output.get("resist_poison", {}).get(
                    "contracts", {}
                ),
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
