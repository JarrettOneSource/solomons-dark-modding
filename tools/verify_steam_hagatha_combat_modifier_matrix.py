#!/usr/bin/env python3
"""Verify Hagatha combat modifiers on both owners of a real Steam pair."""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
import multiplayer_progression_probe as progression
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    CLIENT_INSTANCE,
    HOST_INSTANCE,
    configure_behavior_context,
    reset_quiet_arena,
)
import verify_multiplayer_battle_siege_behavior_sync as battle_siege
import verify_multiplayer_primary_kill_stress as primary
import verify_player_health_death_sync as health
import verify_steam_friend_run_exit_reentry as run_driver
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_run_reconnect import new_crash_artifacts
from verify_steam_friend_real_input_control import windows_process_id
from verify_steam_hagatha_derived_stat_matrix import reset_pair_to_fresh_hub
from verify_steam_hagatha_perk_sync import apply_selector, capture


CURING_SELECTOR = 11
GLASS_CANNON_SELECTOR = 16
CURSE_BOSSES_SELECTOR = 22
SKELETON_NATIVE_TYPE_ID = 0x3E9
HEARTMONGER_NATIVE_TYPE_ID = 0x3F3
PROBE_DAMAGE = 10.0
PROBE_LIFE = 500.0
LIFE_TOLERANCE = 0.25
RATIO_TOLERANCE = 0.15
CLIENT_DAMAGE_CLAIM_QUANTUM = 1.0 / 128.0
ONBOARDING_TIMEOUT = 90.0
DEFAULT_OUTPUT = ROOT / "runtime/steam_hagatha_combat_modifier_matrix.json"
CRASH_DUMP_ROOT = Path("/mnt/c/Users/user/AppData/Local/CrashDumps")


@dataclass(frozen=True)
class Direction:
    name: str
    owner_key: str
    owner_endpoint: str
    owner_participant_id: int
    observer_endpoint: str
    observer_participant_id: int
    authority_target_participant_id: int
    cast_direction: battle_siege.Direction


def wait_until(
    description: str,
    timeout: float,
    sample: Callable[[], tuple[bool, Any]],
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        ready, last = sample()
        if ready:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"timed out waiting for {description}: {last}")


def compact_hagatha(native: dict[str, Any]) -> dict[str, Any]:
    return {
        "selectors": list(native.get("native_selector_list", [])),
        "capacity": int(native.get("capacity", 0)),
        "cheat_death_charges": int(native.get("cheat_death_charges", 0)),
        "serendipity_active": bool(native.get("serendipity_active", False)),
        "reverie_active": bool(native.get("reverie_active", False)),
    }


def owner_fingerprint(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, Any]:
    owner = capture(pair, endpoint)["owner_native"]
    native_progression = progression.query_progression_snapshot(endpoint)["native"]
    return {
        "hagatha": compact_hagatha(owner),
        "derived": dict(native_progression["derived"]),
    }


def capture_selector_replication(
    pair: SteamFriendActivePair,
    direction: Direction,
) -> dict[str, Any]:
    owner = capture(pair, direction.owner_endpoint)["owner_native"]
    observer = capture(pair, direction.observer_endpoint)
    ledger = observer["participants"].get(direction.owner_participant_id)
    return {
        "owner": compact_hagatha(owner),
        "observer_ledger": None
        if ledger is None
        else {
            "selectors": list(ledger.get("selectors", [])),
            "capacity": int(ledger.get("capacity", 0)),
        },
        "observer_native": None
        if ledger is None
        else compact_hagatha(ledger["native"]),
    }


def apply_selector_with_isolation(
    pair: SteamFriendActivePair,
    direction: Direction,
    selector: int,
    timeout: float,
) -> dict[str, Any]:
    before = capture_selector_replication(pair, direction)
    expected = [*before["owner"]["selectors"], selector]
    if selector in before["owner"]["selectors"]:
        raise VerifyFailure(
            f"{direction.name} selector {selector} was already present in a fresh save"
        )
    unrelated_before = owner_fingerprint(pair, direction.observer_endpoint)
    apply_result = apply_selector(pair, direction.owner_endpoint, selector)

    def sample() -> tuple[bool, dict[str, Any]]:
        state = capture_selector_replication(pair, direction)
        ready = (
            state["owner"]["selectors"] == expected
            and state["observer_ledger"] is not None
            and state["observer_ledger"]["selectors"] == expected
            and state["observer_native"] is not None
            and state["observer_native"]["selectors"] == expected
        )
        return ready, state

    converged = wait_until(
        f"{direction.name} selector {selector} replication",
        timeout,
        sample,
    )
    unrelated_after = owner_fingerprint(pair, direction.observer_endpoint)
    unrelated_owner_unchanged = unrelated_before == unrelated_after
    if not unrelated_owner_unchanged:
        raise VerifyFailure(
            f"{direction.name} selector {selector} mutated the unrelated owner"
        )
    return {
        "selector": selector,
        "owner_participant_id": direction.owner_participant_id,
        "observer_participant_id": direction.observer_participant_id,
        "apply": apply_result,
        "converged": converged,
        "unrelated_owner_unchanged": unrelated_owner_unchanged,
    }


def prepare_phase(
    pair: SteamFriendActivePair,
    phase_name: str,
    assignments: tuple[tuple[Direction, int], ...],
    timeout: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": phase_name,
        "fresh_hub": reset_pair_to_fresh_hub(
            pair,
            max(timeout, ONBOARDING_TIMEOUT),
        ),
        "selectors": [],
    }
    for direction, selector in assignments:
        result["selectors"].append(
            apply_selector_with_isolation(pair, direction, selector, timeout)
        )
    result["run_entry"] = run_driver.start_shared_run(
        pair,
        test_manual_enemy_mode=True,
    )
    result["combat_bootstrap"] = primary.enable_manual_stock_spawner_combat()
    result["arena_reset"] = reset_quiet_arena()
    result["pair"] = pair.discover()
    return result


def wait_for_probe_life(
    pair: SteamFriendActivePair,
    direction: Direction,
    timeout: float,
    *,
    reset_life: bool = True,
) -> dict[str, Any]:
    reset = None
    if reset_life:
        reset = health.set_local_player_vitals(
            direction.owner_endpoint,
            PROBE_LIFE,
            PROBE_LIFE,
            mp=PROBE_LIFE,
            max_mp=PROBE_LIFE,
        )

    def sample() -> tuple[bool, dict[str, Any]]:
        owner = health.query_local_player_vitals(direction.owner_endpoint)
        authority = (
            health.query_local_player_vitals(HOST_ENDPOINT)
            if direction.authority_target_participant_id == 0
            else health.query_remote_participant(
                HOST_ENDPOINT,
                direction.owner_participant_id,
            )
        )
        try:
            owner_hp = float(owner.get("hp", "nan"))
            owner_max = float(owner.get("max_hp", "nan"))
            authority_hp = float(authority.get("hp", "nan"))
            authority_max = float(authority.get("max_hp", "nan"))
        except ValueError:
            return False, {"owner": owner, "authority": authority}
        if reset_life:
            ready = all(
                math.isfinite(value)
                and abs(value - PROBE_LIFE) <= LIFE_TOLERANCE
                for value in (owner_hp, owner_max, authority_hp, authority_max)
            )
        else:
            ready = (
                all(
                    math.isfinite(value)
                    for value in (owner_hp, owner_max, authority_hp, authority_max)
                )
                and min(owner_hp, authority_hp) > PROBE_DAMAGE * 4.0
                and abs(owner_hp - authority_hp) <= LIFE_TOLERANCE
                and abs(owner_max - authority_max) <= LIFE_TOLERANCE
            )
        return ready, {"owner": owner, "authority": authority}

    return {
        "reset_life": reset_life,
        "reset": reset,
        "converged": wait_until(
            f"{direction.name} authoritative probe life",
            timeout,
            sample,
        ),
    }


def incoming_trial(
    pair: SteamFriendActivePair,
    direction: Direction,
    *,
    label: str,
    magic_damage: float = 0.0,
    poison_damage: float = 0.0,
    timeout: float,
    reset_life: bool = True,
) -> dict[str, Any]:
    primed = wait_for_probe_life(
        pair,
        direction,
        timeout,
        reset_life=reset_life,
    )
    trial = invoke_native_magic_hit_trial(
        HOST_ENDPOINT,
        projectile_damage=0.0,
        magic_damage=magic_damage,
        poison_damage=poison_damage,
        attempts=1,
        label=f"{direction.name}_{label}",
        timeout=timeout,
        target_participant_id=direction.authority_target_participant_id,
    )
    return {
        "owner_participant_id": direction.owner_participant_id,
        "observer_participant_id": direction.observer_participant_id,
        "primed": primed,
        "trial": trial,
        "damage": float(trial["hp_delta"]),
    }


def outgoing_trial(
    direction: Direction,
    *,
    label: str,
    native_type_id: int,
) -> dict[str, Any]:
    trial = battle_siege.run_cast_trial(
        direction.cast_direction,
        f"{direction.name}_{label}",
        native_type_id=native_type_id,
    )
    return {
        "owner_participant_id": direction.owner_participant_id,
        "observer_participant_id": direction.observer_participant_id,
        "native_type_id": native_type_id,
        "trial": trial,
        "damage": float(trial["native_damage_quantum"]),
    }


def scoped_new_crash_artifacts(
    started_at: float,
    instances: tuple[str, ...],
    host_process_id: int,
) -> list[str]:
    expected_host_dump = f"SolomonDark.exe.{host_process_id}.dmp"
    artifacts: list[str] = []
    for artifact in new_crash_artifacts(started_at, instances):
        path = Path(artifact)
        if path.parent == CRASH_DUMP_ROOT and path.name != expected_host_dump:
            continue
        artifacts.append(artifact)
    return artifacts


def ratio_contract(
    label: str,
    baseline: float,
    observed: float,
    expected_ratio: float,
    *,
    absolute_tolerance: float = 0.0,
) -> dict[str, Any]:
    if (
        not math.isfinite(baseline)
        or baseline <= 0.0
        or not math.isfinite(observed)
        or observed <= 0.0
    ):
        raise VerifyFailure(
            f"{label} has invalid positive damage: baseline={baseline} observed={observed}"
        )
    if not math.isfinite(absolute_tolerance) or absolute_tolerance < 0.0:
        raise VerifyFailure(
            f"{label} has invalid absolute tolerance: {absolute_tolerance}"
        )
    actual_ratio = observed / baseline
    expected_observed = baseline * expected_ratio
    absolute_delta = abs(observed - expected_observed)
    allowed_absolute_delta = max(
        baseline * RATIO_TOLERANCE,
        absolute_tolerance,
    )
    ok = absolute_delta <= allowed_absolute_delta
    if not ok:
        raise VerifyFailure(
            f"{label} ratio mismatch: expected={expected_ratio:.3f} "
            f"actual={actual_ratio:.3f} baseline={baseline:.6f} "
            f"observed={observed:.6f} absolute_delta={absolute_delta:.6f} "
            f"allowed_absolute_delta={allowed_absolute_delta:.6f}"
        )
    return {
        "ok": ok,
        "baseline": baseline,
        "observed": observed,
        "expected_ratio": expected_ratio,
        "actual_ratio": actual_ratio,
        "tolerance": RATIO_TOLERANCE,
        "absolute_tolerance": absolute_tolerance,
        "absolute_delta": absolute_delta,
        "allowed_absolute_delta": allowed_absolute_delta,
    }


def damage_ratio_absolute_tolerance(outgoing: dict[str, Any]) -> float:
    method = outgoing["trial"]["damage_measurement"]["method"]
    return (
        CLIENT_DAMAGE_CLAIM_QUANTUM
        if method == "client_air_damage_claim_quantum"
        else 0.0
    )


def run(pair: SteamFriendActivePair, timeout: float) -> dict[str, Any]:
    run_driver.configure_pair(pair)
    configure_behavior_context(pair)
    source_pids = {"host": 0, "client": 0}
    directions = (
        Direction(
            "host_to_client",
            "host",
            HOST_ENDPOINT,
            pair.host_participant_id,
            CLIENT_ENDPOINT,
            pair.client_participant_id,
            0,
            battle_siege.direction_for_owner("host", source_pids),
        ),
        Direction(
            "client_to_host",
            "client",
            CLIENT_ENDPOINT,
            pair.client_participant_id,
            HOST_ENDPOINT,
            pair.host_participant_id,
            pair.client_participant_id,
            battle_siege.direction_for_owner("client", source_pids),
        ),
    )
    by_name = {direction.name: direction for direction in directions}
    phases: dict[str, Any] = {}

    phases["baseline"] = prepare_phase(
        pair,
        "baseline",
        (),
        timeout,
    )
    baseline: dict[str, Any] = {}
    for direction in directions:
        baseline[direction.name] = {
            "magic_incoming": incoming_trial(
                pair,
                direction,
                label="baseline_magic",
                magic_damage=PROBE_DAMAGE,
                timeout=timeout,
            ),
            "poison_incoming": incoming_trial(
                pair,
                direction,
                label="baseline_poison",
                poison_damage=PROBE_DAMAGE,
                timeout=timeout,
                reset_life=False,
            ),
            "nonboss_outgoing": outgoing_trial(
                direction,
                label="baseline_nonboss",
                native_type_id=SKELETON_NATIVE_TYPE_ID,
            ),
            "boss_outgoing": outgoing_trial(
                direction,
                label="baseline_boss",
                native_type_id=HEARTMONGER_NATIVE_TYPE_ID,
            ),
        }

    curing_poison_incoming: dict[str, Any] = {}
    glass_cannon_incoming: dict[str, Any] = {}
    glass_cannon_outgoing: dict[str, Any] = {}
    mixed_assignments = (
        (
            "host_curing_client_glass",
            (
                (by_name["host_to_client"], CURING_SELECTOR),
                (by_name["client_to_host"], GLASS_CANNON_SELECTOR),
            ),
        ),
        (
            "host_glass_client_curing",
            (
                (by_name["host_to_client"], GLASS_CANNON_SELECTOR),
                (by_name["client_to_host"], CURING_SELECTOR),
            ),
        ),
    )
    for phase_name, assignments in mixed_assignments:
        phases[phase_name] = prepare_phase(
            pair,
            phase_name,
            assignments,
            timeout,
        )
        for direction, selector in assignments:
            if selector == CURING_SELECTOR:
                curing_poison_incoming[direction.name] = incoming_trial(
                    pair,
                    direction,
                    label="curing_poison",
                    poison_damage=PROBE_DAMAGE,
                    timeout=timeout,
                )
            elif selector == GLASS_CANNON_SELECTOR:
                glass_cannon_incoming[direction.name] = incoming_trial(
                    pair,
                    direction,
                    label="glass_magic",
                    magic_damage=PROBE_DAMAGE,
                    timeout=timeout,
                )
                glass_cannon_outgoing[direction.name] = outgoing_trial(
                    direction,
                    label="glass_nonboss",
                    native_type_id=SKELETON_NATIVE_TYPE_ID,
                )

    phases["curse_bosses"] = prepare_phase(
        pair,
        "curse_bosses",
        tuple((direction, CURSE_BOSSES_SELECTOR) for direction in directions),
        timeout,
    )
    curse_bosses_boss_damage: dict[str, Any] = {}
    curse_bosses_nonboss_damage: dict[str, Any] = {}
    for direction in directions:
        curse_bosses_nonboss_damage[direction.name] = outgoing_trial(
            direction,
            label="curse_nonboss",
            native_type_id=SKELETON_NATIVE_TYPE_ID,
        )
        curse_bosses_boss_damage[direction.name] = outgoing_trial(
            direction,
            label="curse_boss",
            native_type_id=HEARTMONGER_NATIVE_TYPE_ID,
        )

    contracts: dict[str, Any] = {
        "curing_poison_incoming": {},
        "glass_cannon_incoming": {},
        "glass_cannon_outgoing": {},
        "curse_bosses_boss_damage": {},
        "curse_bosses_nonboss_damage": {},
        "unrelated_owner_unchanged": all(
            selector["unrelated_owner_unchanged"]
            for phase in phases.values()
            for selector in phase["selectors"]
        ),
    }
    for direction in directions:
        name = direction.name
        contracts["curing_poison_incoming"][name] = ratio_contract(
            f"{name} Curing poison incoming",
            baseline[name]["poison_incoming"]["damage"],
            curing_poison_incoming[name]["damage"],
            0.5,
        )
        contracts["glass_cannon_incoming"][name] = ratio_contract(
            f"{name} Glass Cannon incoming",
            baseline[name]["magic_incoming"]["damage"],
            glass_cannon_incoming[name]["damage"],
            2.0,
        )
        contracts["glass_cannon_outgoing"][name] = ratio_contract(
            f"{name} Glass Cannon outgoing",
            baseline[name]["nonboss_outgoing"]["damage"],
            glass_cannon_outgoing[name]["damage"],
            2.0,
            absolute_tolerance=damage_ratio_absolute_tolerance(
                baseline[name]["nonboss_outgoing"]
            ),
        )
        contracts["curse_bosses_boss_damage"][name] = ratio_contract(
            f"{name} Curse Bosses boss damage",
            baseline[name]["boss_outgoing"]["damage"],
            curse_bosses_boss_damage[name]["damage"],
            3.0,
            absolute_tolerance=damage_ratio_absolute_tolerance(
                baseline[name]["boss_outgoing"]
            ),
        )
        contracts["curse_bosses_nonboss_damage"][name] = ratio_contract(
            f"{name} Curse Bosses nonboss damage",
            baseline[name]["nonboss_outgoing"]["damage"],
            curse_bosses_nonboss_damage[name]["damage"],
            1.0,
        )
    if not contracts["unrelated_owner_unchanged"]:
        raise VerifyFailure("a Hagatha combat selector mutated the unrelated owner")

    return {
        "ok": True,
        "transport": "steam_friend",
        "pair_backend": PAIR_BACKEND,
        "pair": pair.discover(),
        "phases": phases,
        "baseline": baseline,
        "measurements": {
            "curing_poison_incoming": curing_poison_incoming,
            "glass_cannon_incoming": glass_cannon_incoming,
            "glass_cannon_outgoing": glass_cannon_outgoing,
            "curse_bosses_boss_damage": curse_bosses_boss_damage,
            "curse_bosses_nonboss_damage": curse_bosses_nonboss_damage,
        },
        "contracts": contracts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    instances = (HOST_INSTANCE, CLIENT_INSTANCE)
    host_process_id = windows_process_id(HOST_INSTANCE)
    result: dict[str, Any] = {"ok": False}
    try:
        result = run(pair, args.timeout)
        crashes = scoped_new_crash_artifacts(
            started_at,
            instances,
            host_process_id,
        )
        result["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts appeared during the combat matrix: {crashes}"
            )
    except Exception as exc:  # noqa: BLE001 - preserve the partial matrix.
        result["ok"] = False
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["new_crash_artifacts"] = scoped_new_crash_artifacts(
            started_at,
            instances,
            host_process_id,
        )
    finally:
        pair.close()

    result = pair.redact(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "contracts": result.get("contracts"),
                "new_crash_artifacts": result.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
