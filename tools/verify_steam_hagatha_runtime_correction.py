#!/usr/bin/env python3
"""Verify host-authoritative Hagatha one-shot state on a real Steam pair."""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import verify_player_health_death_sync as health
import verify_steam_friend_run_exit_reentry as run_driver
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_steam_hagatha_perk_sync import apply_selector, capture


CHEAT_DEATH_SELECTOR = 7
SERENDIPITY_SELECTOR = 24
REVERIE_SELECTOR = 25
REQUIRED_SELECTORS = (
    CHEAT_DEATH_SELECTOR,
    SERENDIPITY_SELECTOR,
    REVERIE_SELECTOR,
)
BASELINE_LIFE = 50.0
MODERATE_DAMAGE = 12.0
LETHAL_STARTING_LIFE = 5.0
LETHAL_DAMAGE = 25.0
LIFE_TOLERANCE = 0.25
DEFAULT_OUTPUT = ROOT / "runtime/steam_hagatha_runtime_correction.json"


@dataclass(frozen=True)
class Direction:
    name: str
    owner_endpoint: str
    owner_participant_id: int
    observer_endpoint: str
    authority_target_participant_id: int


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
        time.sleep(0.05)
    raise VerifyFailure(f"timed out waiting for {description}: {last}")


def configure_pair(pair: SteamFriendActivePair) -> dict[str, Any]:
    discovered = run_driver.configure_pair(pair)
    health.lua = pair.lua
    return discovered


def compact_hagatha(state: dict[str, Any]) -> dict[str, Any]:
    return {
        key: state[key]
        for key in (
            "native_selector_list",
            "capacity",
            "cheat_death_charges",
            "serendipity_active",
            "reverie_active",
        )
    }


def direction_state(
    pair: SteamFriendActivePair,
    direction: Direction,
) -> dict[str, Any]:
    owner = capture(pair, direction.owner_endpoint)
    observer = capture(pair, direction.observer_endpoint)
    ledger = observer["participants"].get(direction.owner_participant_id)
    owner_vitals = health.query_local_player_vitals(direction.owner_endpoint)
    observer_vitals = health.query_remote_participant(
        direction.observer_endpoint,
        direction.owner_participant_id,
    )
    return {
        "owner": compact_hagatha(owner["owner_native"]),
        "observer_ledger": ledger,
        "observer_native": ledger and compact_hagatha(ledger["native"]),
        "owner_life": float(owner_vitals.get("hp", "nan")),
        "observer_life": float(observer_vitals.get("hp", "nan")),
        "observer_runtime_life": float(
            observer_vitals.get("runtime.life_current", "nan")
        ),
    }


def ensure_required_perks(
    pair: SteamFriendActivePair,
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    baseline = direction_state(pair, direction)
    selectors = list(baseline["owner"]["native_selector_list"])
    missing = [selector for selector in REQUIRED_SELECTORS if selector not in selectors]
    if missing and (
        len(selectors) + len(missing) > int(baseline["owner"]["capacity"])
    ):
        raise VerifyFailure(
            f"{direction.name} lacks room for the Hagatha fixture: {baseline}"
        )
    for selector in missing:
        apply_selector(pair, direction.owner_endpoint, selector)
        selectors.append(selector)

        def sample() -> tuple[bool, dict[str, Any]]:
            state = direction_state(pair, direction)
            ledger = state["observer_ledger"]
            ready = (
                state["owner"]["native_selector_list"] == selectors
                and ledger is not None
                and ledger["selectors"] == selectors
                and state["observer_native"] is not None
                and state["observer_native"]["native_selector_list"] == selectors
            )
            return ready, state

        wait_until(
            f"{direction.name} Hagatha selector {selector} replication",
            timeout,
            sample,
        )
    return direction_state(pair, direction)


def invoke_authoritative_magic_hit(
    pair: SteamFriendActivePair,
    direction: Direction,
    damage: float,
    timeout: float,
) -> dict[str, Any]:
    queue_values = parse_key_values(
        pair.lua(
            HOST_ENDPOINT,
            f"""
local function emit(k,v) print(k .. '=' .. tostring(v == nil and '' or v)) end
local queued, err, serial = sd.debug.queue_native_magic_hit_behavior_probe(
  0.0, {damage:.9f}, 1, {direction.authority_target_participant_id})
emit('queued', queued)
emit('error', err or '')
emit('serial', serial or 0)
""",
            timeout=15.0,
        )
    )
    serial = int(queue_values.get("serial", "0"), 0)
    if queue_values.get("queued") != "true" or serial <= 0:
        raise VerifyFailure(
            f"{direction.name} native magic hit was rejected: {queue_values}"
        )

    def sample() -> tuple[bool, dict[str, str]]:
        values = parse_key_values(
            pair.lua(
                HOST_ENDPOINT,
                f"""
local function emit(k,v) print(k .. '=' .. tostring(v == nil and '' or v)) end
local completed, success, hp_before, hp_after, err =
  sd.debug.get_native_magic_hit_behavior_probe_result({serial})
emit('completed', completed)
emit('success', success)
emit('hp_before', hp_before)
emit('hp_after', hp_after)
emit('error', err or '')
""",
                timeout=15.0,
            )
        )
        return values.get("completed") == "true", values

    values = wait_until(
        f"{direction.name} native magic hit completion",
        timeout,
        sample,
    )
    if values.get("success") != "true":
        raise VerifyFailure(
            f"{direction.name} native magic hit failed: {values}"
        )
    before = float(values.get("hp_before", "nan"))
    after = float(values.get("hp_after", "nan"))
    if not math.isfinite(before) or not math.isfinite(after):
        raise VerifyFailure(
            f"{direction.name} native magic hit returned invalid life: {values}"
        )
    return {
        "damage": damage,
        "hp_before": before,
        "hp_after": after,
    }


def wait_for_life(
    pair: SteamFriendActivePair,
    direction: Direction,
    expected: float,
    timeout: float,
) -> dict[str, Any]:
    def sample() -> tuple[bool, dict[str, Any]]:
        state = direction_state(pair, direction)
        ready = all(
            math.isfinite(value) and abs(value - expected) <= LIFE_TOLERANCE
            for value in (
                state["owner_life"],
                state["observer_life"],
                state["observer_runtime_life"],
            )
        )
        return ready, state

    return wait_until(
        f"{direction.name} life {expected:.3f}",
        timeout,
        sample,
    )


def set_life(
    pair: SteamFriendActivePair,
    direction: Direction,
    life: float,
    timeout: float,
) -> dict[str, Any]:
    health.set_local_player_vitals(
        direction.owner_endpoint,
        life,
        BASELINE_LIFE,
        mp=BASELINE_LIFE,
        max_mp=BASELINE_LIFE,
    )
    return wait_for_life(pair, direction, life, timeout)


def verify_direction(
    pair: SteamFriendActivePair,
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    initial = direction_state(pair, direction)
    expected_selectors = set(REQUIRED_SELECTORS)
    if not expected_selectors.issubset(initial["owner"]["native_selector_list"]):
        raise VerifyFailure(f"{direction.name} Hagatha fixture is incomplete: {initial}")
    if (
        initial["owner"]["cheat_death_charges"] != 1
        or not initial["owner"]["serendipity_active"]
        or not initial["owner"]["reverie_active"]
    ):
        raise VerifyFailure(f"{direction.name} one-shot fixture is not armed: {initial}")

    moderate_before = set_life(pair, direction, BASELINE_LIFE, timeout)
    moderate_hit = invoke_authoritative_magic_hit(
        pair,
        direction,
        MODERATE_DAMAGE,
        timeout,
    )
    if moderate_hit["hp_after"] >= moderate_hit["hp_before"]:
        raise VerifyFailure(
            f"{direction.name} moderate hit did not reduce native life: {moderate_hit}"
        )
    moderate_life = wait_for_life(
        pair,
        direction,
        moderate_hit["hp_after"],
        timeout,
    )

    def moderate_sample() -> tuple[bool, dict[str, Any]]:
        state = direction_state(pair, direction)
        ledger = state["observer_ledger"]
        states = (
            state["owner"],
            ledger,
            state["observer_native"],
        )
        ready = all(
            value is not None
            and value["cheat_death_charges"] == 1
            and not value["serendipity_active"]
            and not value["reverie_active"]
            for value in states
        )
        return ready, state

    moderate_damage_clears_until_hurt = wait_until(
        f"{direction.name} until-hurt state convergence",
        timeout,
        moderate_sample,
    )

    lethal_before = set_life(pair, direction, LETHAL_STARTING_LIFE, timeout)
    lethal_hit = invoke_authoritative_magic_hit(
        pair,
        direction,
        LETHAL_DAMAGE,
        timeout,
    )
    if lethal_hit["hp_after"] <= LETHAL_STARTING_LIFE:
        raise VerifyFailure(
            f"{direction.name} Cheat Death did not restore native life: {lethal_hit}"
        )
    lethal_life = wait_for_life(
        pair,
        direction,
        lethal_hit["hp_after"],
        timeout,
    )

    def lethal_sample() -> tuple[bool, dict[str, Any]]:
        state = direction_state(pair, direction)
        ledger = state["observer_ledger"]
        states = (
            state["owner"],
            ledger,
            state["observer_native"],
        )
        ready = all(
            value is not None
            and value["cheat_death_charges"] == 0
            and not value["serendipity_active"]
            and not value["reverie_active"]
            for value in states
        )
        return ready, state

    lethal_damage_consumes_cheat_death = wait_until(
        f"{direction.name} Cheat Death consumption convergence",
        timeout,
        lethal_sample,
    )
    return {
        "ok": True,
        "initial": initial,
        "moderate_damage_clears_until_hurt": {
            "before": moderate_before,
            "hit": moderate_hit,
            "life": moderate_life,
            "converged": moderate_damage_clears_until_hurt,
        },
        "lethal_damage_consumes_cheat_death": {
            "before": lethal_before,
            "hit": lethal_hit,
            "life": lethal_life,
            "converged": lethal_damage_consumes_cheat_death,
        },
    }


def run(pair: SteamFriendActivePair, timeout: float) -> dict[str, Any]:
    discovery = configure_pair(pair)
    directions = (
        Direction(
            "host_to_client",
            HOST_ENDPOINT,
            pair.host_participant_id,
            CLIENT_ENDPOINT,
            0,
        ),
        Direction(
            "client_to_host",
            CLIENT_ENDPOINT,
            pair.client_participant_id,
            HOST_ENDPOINT,
            pair.client_participant_id,
        ),
    )
    scenes = {discovery["host"]["scene"], discovery["client"]["scene"]}
    preparation: dict[str, Any] = {}
    if scenes == {"hub"}:
        preparation["perks"] = {
            direction.name: ensure_required_perks(pair, direction, timeout)
            for direction in directions
        }
        preparation["run_entry"] = run_driver.start_shared_run(
            pair,
            test_manual_enemy_mode=True,
        )
        discovery = pair.discover()
    elif scenes != {"testrun"}:
        raise VerifyFailure(
            f"Hagatha runtime verification requires a shared hub or run: {discovery}"
        )
    run_driver.drive.arm_test_manual_enemy_mode(pair, HOST_ENDPOINT)
    run_driver.drive.arm_test_manual_enemy_mode(pair, CLIENT_ENDPOINT)

    results: dict[str, Any] = {}
    direction_error: str | None = None
    for direction in directions:
        try:
            results[direction.name] = verify_direction(
                pair,
                direction,
                timeout,
            )
        except Exception as exc:
            direction_error = str(exc)
            results[direction.name] = {
                "ok": False,
                "error": direction_error,
                "error_type": type(exc).__name__,
            }
            break
    return {
        "ok": direction_error is None,
        "error": direction_error,
        "transport": "steam_friend",
        "pair_backend": PAIR_BACKEND,
        "pair": discovery,
        "preparation": preparation,
        "directions": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    try:
        result = run(pair, args.timeout)
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
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
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
