#!/usr/bin/env python3
"""Verify Hagatha-derived gameplay values on both actors of a real Steam pair."""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hagatha_bare_hands_fixture import (
    BARE_HANDS_REFRESH,
    LOADOUT_TABLE,
    query_local_weapon_binding,
    set_local_weapon_presence,
    wait_for_weapon_presence,
)
import multiplayer_progression_probe as progression
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


LIFE_SELECTOR = 0
MANA_SELECTOR = 1
SPEED_SELECTOR = 2
WAR_SELECTOR = 10
FOCUS_SELECTOR = 18
BARE_HANDS_SELECTOR = 20
BRUTE_SELECTOR = 26
TONIC_SELECTOR = 27

DEFAULT_OUTPUT = ROOT / "runtime/steam_hagatha_derived_stat_matrix.json"
FLOAT_TOLERANCE = 0.0001
ONBOARDING_TIMEOUT = 90.0


@dataclass(frozen=True)
class FieldExpectation:
    name: str
    factor: float
    snapshot_paths: tuple[tuple[str, ...], ...]
    native_layout_name: str | None


@dataclass(frozen=True)
class PerkExpectation:
    selector: int
    name: str
    fields: tuple[FieldExpectation, ...] = ()
    capacity_delta: int = 0


@dataclass(frozen=True)
class Direction:
    name: str
    owner_endpoint: str
    owner_participant_id: int
    observer_endpoint: str
    observer_participant_id: int


MAX_LIFE = FieldExpectation(
    "max_life",
    1.25,
    (("native", "max_hp"), ("runtime", "life_max")),
    "progression_max_hp",
)
MAX_MANA = FieldExpectation(
    "max_mana",
    1.25,
    (("native", "max_mp"), ("runtime", "mana_max")),
    "progression_max_mp",
)
MOVE_SPEED = FieldExpectation(
    "move_speed",
    1.10,
    (("native", "move_speed"), ("runtime", "move_speed")),
    "progression_move_speed",
)
CAST_SPEED = FieldExpectation(
    "cast_speed",
    1.10,
    (
        ("native", "derived", "cast_speed_multiplier"),
        ("ledger", "derived", "cast_speed_multiplier"),
    ),
    "progression_cast_speed_multiplier",
)
OFFENSIVE_MANA = FieldExpectation(
    "offensive_mana",
    0.75,
    (
        ("native", "derived", "offensive_mana_multiplier"),
        ("ledger", "derived", "offensive_mana_multiplier"),
    ),
    "progression_offensive_mana_multiplier",
)
SECONDARY_RECHARGE = FieldExpectation(
    "secondary_recharge",
    1.25,
    (
        ("native", "derived", "secondary_recharge_multiplier"),
        ("ledger", "derived", "secondary_recharge_multiplier"),
    ),
    "progression_secondary_recharge_multiplier",
)
BARE_HANDS_DAMAGE = FieldExpectation(
    "bare_hands_damage",
    1.15,
    (
        ("native", "derived", "offensive_damage_multiplier"),
        ("ledger", "derived", "offensive_damage_multiplier"),
    ),
    "progression_offensive_damage_multiplier",
)
BARE_HANDS_MANA = FieldExpectation(
    "bare_hands_mana",
    0.85,
    (
        ("native", "derived", "offensive_mana_multiplier"),
        ("ledger", "derived", "offensive_mana_multiplier"),
    ),
    "progression_offensive_mana_multiplier",
)
MELEE_DAMAGE = FieldExpectation(
    "melee_damage",
    3.0,
    (
        ("native", "derived", "melee_damage_multiplier"),
        ("ledger", "derived", "melee_damage_multiplier"),
    ),
    "progression_melee_damage_multiplier",
)
PUSH_STRENGTH = FieldExpectation(
    "push_strength",
    2.0,
    (
        ("native", "derived", "push_strength"),
        ("ledger", "derived", "push_strength"),
    ),
    "progression_push_strength",
)


GROUPS: dict[str, tuple[PerkExpectation, ...]] = {
    "vitals_speed": (
        PerkExpectation(LIFE_SELECTOR, "Life Charm", (MAX_LIFE,)),
        PerkExpectation(MANA_SELECTOR, "Mana Charm", (MAX_MANA,)),
        PerkExpectation(SPEED_SELECTOR, "Speed Charm", (MOVE_SPEED, CAST_SPEED)),
    ),
    "offense": (
        PerkExpectation(WAR_SELECTOR, "War Charm", (OFFENSIVE_MANA,)),
        PerkExpectation(FOCUS_SELECTOR, "Focus Charm", (SECONDARY_RECHARGE,)),
        PerkExpectation(
            BRUTE_SELECTOR,
            "Brute's Charm",
            (MELEE_DAMAGE, PUSH_STRENGTH),
        ),
    ),
    "conditional_capacity": (
        PerkExpectation(
            BARE_HANDS_SELECTOR,
            "Bare Hands Charm",
            (
                BARE_HANDS_DAMAGE,
                BARE_HANDS_MANA,
            ),
        ),
        PerkExpectation(TONIC_SELECTOR, "Tonic", capacity_delta=3),
    ),
}


def close_float(left: float, right: float) -> bool:
    return math.isfinite(left) and math.isfinite(right) and math.isclose(
        left,
        right,
        rel_tol=FLOAT_TOLERANCE,
        abs_tol=FLOAT_TOLERANCE,
    )


def value_at(snapshot: dict[str, Any], path: tuple[str, ...]) -> float:
    value: Any = snapshot
    for key in path:
        value = value[key]
    result = float(value)
    if not math.isfinite(result):
        raise VerifyFailure(f"non-finite progression value at {'.'.join(path)}")
    return result


def compact_progression(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime": {
            key: snapshot["runtime"][key]
            for key in ("life_max", "mana_max", "move_speed")
        },
        "native": {
            "max_hp": snapshot["native"]["max_hp"],
            "max_mp": snapshot["native"]["max_mp"],
            "move_speed": snapshot["native"]["move_speed"],
            "derived": snapshot["native"]["derived"],
        },
        "ledger": {
            "derived_stat_revision": snapshot["ledger"]["derived_stat_revision"],
            "derived": snapshot["ledger"]["derived"],
        },
        "spell": {
            key: snapshot["spell"][key]
            for key in ("damage", "mana_spend_cost", "resolved")
        },
    }


def compact_hagatha(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "selectors": state.get("native_selector_list", state.get("selectors", [])),
        "capacity": state["capacity"],
        "revision": state.get("revision", 0),
    }


def capture_direction(
    pair: SteamFriendActivePair,
    direction: Direction,
) -> dict[str, Any]:
    owner = progression.query_progression_snapshot(direction.owner_endpoint)
    observer = progression.query_progression_snapshot(
        direction.observer_endpoint,
        participant_id=direction.owner_participant_id,
    )
    observer_owner = progression.query_progression_snapshot(
        direction.observer_endpoint
    )
    owner_perks = capture(pair, direction.owner_endpoint)["owner_native"]
    observer_capture = capture(pair, direction.observer_endpoint)
    observer_ledger = observer_capture["participants"].get(
        direction.owner_participant_id
    )
    if observer_ledger is None:
        raise VerifyFailure(
            f"{direction.name} owner is missing from the observer ledger"
        )
    observer_native = observer_ledger["native"]
    return {
        "owner": owner,
        "observer": observer,
        "observer_owner": observer_owner,
        "owner_hagatha": owner_perks,
        "observer_owner_hagatha": observer_capture["owner_native"],
        "observer_hagatha": observer_ledger,
        "observer_native_hagatha": observer_native,
    }


def owner_fingerprint(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "progression": compact_progression(state["observer_owner"]),
        "hagatha": compact_hagatha(state["observer_owner_hagatha"]),
    }


def assert_channels(
    label: str,
    snapshot: dict[str, Any],
    field: FieldExpectation,
    expected: float,
) -> dict[str, float]:
    channels = {
        ".".join(path): value_at(snapshot, path)
        for path in field.snapshot_paths
    }
    mismatched = {
        channel: value
        for channel, value in channels.items()
        if not close_float(value, expected)
    }
    if mismatched:
        raise VerifyFailure(
            f"{label} {field.name} expected {expected:.9f}: {mismatched}"
        )
    return channels


def assert_relative_effect(
    before: dict[str, Any],
    after: dict[str, Any],
    perk: PerkExpectation,
) -> dict[str, Any]:
    measurements: dict[str, Any] = {}
    for field in perk.fields:
        baseline = value_at(before["owner"], field.snapshot_paths[0])
        expected = baseline * field.factor
        owner_native = assert_channels(
            "owner",
            after["owner"],
            field,
            expected,
        )
        observer_native = assert_channels(
            "observer",
            after["observer"],
            field,
            expected,
        )
        observer_ledger = {
            key: value
            for key, value in observer_native.items()
            if key.startswith("ledger.")
        }
        measurements[field.name] = {
            "baseline": baseline,
            "factor": field.factor,
            "expected": expected,
            "owner_native": owner_native,
            "observer_native": observer_native,
            "observer_ledger": observer_ledger,
        }
    return measurements


def assert_bare_hands_armed_inactive(
    before: dict[str, Any],
    current: dict[str, Any],
    perk: PerkExpectation,
) -> dict[str, Any]:
    measurements: dict[str, Any] = {}
    for field in perk.fields:
        baseline = value_at(before["owner"], field.snapshot_paths[0])
        owner_native = assert_channels(
            "armed owner",
            current["owner"],
            field,
            baseline,
        )
        observer_native = assert_channels(
            "armed observer",
            current["observer"],
            field,
            baseline,
        )
        measurements[field.name] = {
            "baseline": baseline,
            "expected": baseline,
            "owner_native": owner_native,
            "observer_native": observer_native,
        }
    return measurements


def assert_perk_replication(
    before: dict[str, Any],
    after: dict[str, Any],
    perk: PerkExpectation,
) -> dict[str, Any]:
    expected_selectors = list(before["owner_hagatha"]["native_selector_list"])
    expected_selectors.append(perk.selector)
    expected_capacity = int(before["owner_hagatha"]["capacity"]) + perk.capacity_delta
    states = {
        "owner": compact_hagatha(after["owner_hagatha"]),
        "observer_ledger": compact_hagatha(after["observer_hagatha"]),
        "observer_native": compact_hagatha(after["observer_native_hagatha"]),
    }
    for label, state in states.items():
        if state["selectors"] != expected_selectors:
            raise VerifyFailure(
                f"{label} selector list did not converge: {state}"
            )
        if state["capacity"] != expected_capacity:
            raise VerifyFailure(
                f"{label} capacity did not converge: {state}"
            )
    return {
        "expected_selectors": expected_selectors,
        "expected_capacity": expected_capacity,
        "states": states,
    }


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


def corrupt_observer_field(
    pair: SteamFriendActivePair,
    direction: Direction,
    field: FieldExpectation,
    value: float,
) -> dict[str, Any]:
    if field.native_layout_name is None:
        return {"attempted": False, "reason": "computed spell output"}
    values = parse_key_values(
        pair.lua(
            direction.observer_endpoint,
            f"""
local function emit(k,v) print(k .. '=' .. tostring(v == nil and '' or v)) end
local bot = sd.bots.get_participant_state({direction.owner_participant_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
local offset = sd.debug.layout_offset({json.dumps(field.native_layout_name)})
local wrote = progression ~= 0 and offset ~= 0 and
  sd.debug.write_float(progression + offset, {value:.9f}) or false
emit('progression', progression)
emit('offset', offset)
emit('wrote', wrote)
emit('value', progression ~= 0 and offset ~= 0 and
  sd.debug.read_float(progression + offset) or 0)
""",
            timeout=10.0,
        )
    )
    if values.get("wrote") != "true":
        raise VerifyFailure(
            f"failed to corrupt observer {field.name}: {values}"
        )
    observed = float(values.get("value", "nan"))
    if not close_float(observed, value):
        raise VerifyFailure(
            f"observer {field.name} corruption did not stick: {values}"
        )
    return {
        "attempted": True,
        "offset": int(values.get("offset", "0"), 0),
        "value": observed,
    }


def wait_for_effect(
    pair: SteamFriendActivePair,
    direction: Direction,
    before: dict[str, Any],
    perk: PerkExpectation,
    timeout: float,
) -> dict[str, Any]:
    def sample() -> tuple[bool, dict[str, Any]]:
        try:
            current = capture_direction(pair, direction)
            replication = assert_perk_replication(before, current, perk)
            effect = assert_relative_effect(before, current, perk)
            return True, {
                "state": current,
                "replication": replication,
                "effect": effect,
            }
        except (KeyError, TypeError, ValueError, VerifyFailure) as exc:
            return False, {"error": str(exc), "error_type": type(exc).__name__}

    return wait_until(
        f"{direction.name} {perk.name} behavior convergence",
        timeout,
        sample,
    )


def wait_for_bare_hands_armed_inactive(
    pair: SteamFriendActivePair,
    direction: Direction,
    before: dict[str, Any],
    perk: PerkExpectation,
    timeout: float,
) -> dict[str, Any]:
    def sample() -> tuple[bool, dict[str, Any]]:
        try:
            current = capture_direction(pair, direction)
            replication = assert_perk_replication(before, current, perk)
            effect = assert_bare_hands_armed_inactive(before, current, perk)
            return True, {
                "state": current,
                "replication": replication,
                "effect": effect,
            }
        except (KeyError, TypeError, ValueError, VerifyFailure) as exc:
            return False, {"error": str(exc), "error_type": type(exc).__name__}

    return wait_until(
        f"{direction.name} armed Bare Hands inactivity",
        timeout,
        sample,
    )


def verify_self_correction(
    pair: SteamFriendActivePair,
    direction: Direction,
    before: dict[str, Any],
    perk: PerkExpectation,
    converged: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for field in perk.fields:
        expected = converged["effect"][field.name]["expected"]
        poison = expected * 0.5 if abs(expected) > FLOAT_TOLERANCE else 1.0
        corruption = corrupt_observer_field(
            pair,
            direction,
            field,
            poison,
        )
        if not corruption["attempted"]:
            records[field.name] = {
                "corruption": corruption,
                "self_corrected": "computed_from_corrected_native_state",
            }
            continue

        repaired = wait_for_effect(
            pair,
            direction,
            before,
            perk,
            timeout,
        )
        records[field.name] = {
            "corruption": corruption,
            "self_corrected": True,
            "repaired_channels": repaired["effect"][field.name],
        }
    return records


def verify_direction(
    pair: SteamFriendActivePair,
    direction: Direction,
    perk: PerkExpectation,
    timeout: float,
) -> dict[str, Any]:
    before = capture_direction(pair, direction)
    observer_owner_before = owner_fingerprint(before)
    apply_selector(pair, direction.owner_endpoint, perk.selector)
    converged = wait_for_effect(pair, direction, before, perk, timeout)
    self_correction = verify_self_correction(
        pair,
        direction,
        before,
        perk,
        converged,
        timeout,
    )
    after = capture_direction(pair, direction)
    observer_owner_after = owner_fingerprint(after)
    observer_owner_unchanged = observer_owner_before == observer_owner_after
    if not observer_owner_unchanged:
        raise VerifyFailure(
            f"{direction.name} {perk.name} mutated the observer's owned progression"
        )
    return {
        "ok": True,
        "selector": perk.selector,
        "perk": perk.name,
        "replication": converged["replication"],
        "effect": converged["effect"],
        "self_correction": self_correction,
        "observer_owner_unchanged": observer_owner_unchanged,
    }


def verify_bare_hands_direction(
    pair: SteamFriendActivePair,
    direction: Direction,
    perk: PerkExpectation,
    timeout: float,
) -> dict[str, Any]:
    before = capture_direction(pair, direction)
    observer_owner_before = owner_fingerprint(before)
    armed_binding = query_local_weapon_binding(pair, direction.owner_endpoint)
    original_weapon = int(armed_binding["weapon"])
    if original_weapon == 0 or int(armed_binding["lane_type"]) == 0:
        raise VerifyFailure(
            f"{direction.name} Bare Hands fixture started unarmed: {armed_binding}"
        )

    apply_selector(pair, direction.owner_endpoint, perk.selector)
    armed_inactive = wait_for_bare_hands_armed_inactive(
        pair,
        direction,
        before,
        perk,
        timeout,
    )
    armed_weapon = wait_for_weapon_presence(
        pair,
        owner_endpoint=direction.owner_endpoint,
        observer_endpoint=direction.observer_endpoint,
        owner_participant_id=direction.owner_participant_id,
        expected_present=True,
        expected_type=int(armed_binding["lane_type"]),
        expected_recipe=int(armed_binding["lane_recipe"]),
        timeout=timeout,
    )

    unarmed_mutation: dict[str, Any] | None = None
    restored_armed: dict[str, Any] | None = None
    try:
        unarmed_mutation = set_local_weapon_presence(
            pair,
            direction.owner_endpoint,
            expected_weapon=original_weapon,
            target_weapon=0,
        )
        unarmed_weapon = wait_for_weapon_presence(
            pair,
            owner_endpoint=direction.owner_endpoint,
            observer_endpoint=direction.observer_endpoint,
            owner_participant_id=direction.owner_participant_id,
            expected_present=False,
            expected_type=int(armed_binding["lane_type"]),
            expected_recipe=int(armed_binding["lane_recipe"]),
            timeout=timeout,
        )
        unarmed_active = wait_for_effect(
            pair,
            direction,
            before,
            perk,
            timeout,
        )
        self_correction = verify_self_correction(
            pair,
            direction,
            before,
            perk,
            unarmed_active,
            timeout,
        )
    finally:
        if unarmed_mutation is not None:
            restoration = set_local_weapon_presence(
                pair,
                direction.owner_endpoint,
                expected_weapon=0,
                target_weapon=original_weapon,
            )
            restored_weapon = wait_for_weapon_presence(
                pair,
                owner_endpoint=direction.owner_endpoint,
                observer_endpoint=direction.observer_endpoint,
                owner_participant_id=direction.owner_participant_id,
                expected_present=True,
                expected_type=int(armed_binding["lane_type"]),
                expected_recipe=int(armed_binding["lane_recipe"]),
                timeout=timeout,
            )
            restored_effect = wait_for_bare_hands_armed_inactive(
                pair,
                direction,
                before,
                perk,
                timeout,
            )
            restored_armed = {
                "mutation": restoration,
                "weapon": restored_weapon,
                "effect": restored_effect["effect"],
            }

    after = capture_direction(pair, direction)
    observer_owner_unchanged = (
        observer_owner_before == owner_fingerprint(after)
    )
    if not observer_owner_unchanged:
        raise VerifyFailure(
            f"{direction.name} Bare Hands mutated the observer's owned progression"
        )
    return {
        "ok": True,
        "selector": perk.selector,
        "perk": perk.name,
        "stock_predicate": {
            "refresh": BARE_HANDS_REFRESH,
            "loadout_table": LOADOUT_TABLE,
        },
        "armed_inactive": {
            "weapon": armed_weapon,
            "replication": armed_inactive["replication"],
            "effect": armed_inactive["effect"],
        },
        "unarmed_active": {
            "mutation": unarmed_mutation,
            "weapon": unarmed_weapon,
            "replication": unarmed_active["replication"],
            "effect": unarmed_active["effect"],
            "self_correction": self_correction,
        },
        "restored_armed": restored_armed,
        "observer_owner_unchanged": observer_owner_unchanged,
    }


def wait_for_native_release_after_hub_leave(
    pair: SteamFriendActivePair,
    timeout: float,
    endpoints: tuple[str, ...] = (HOST_ENDPOINT, CLIENT_ENDPOINT),
) -> dict[str, dict[str, str]]:
    pending = set(endpoints)
    released: dict[str, dict[str, str]] = {}
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        for endpoint in tuple(pending):
            state = parse_key_values(
                pair.lua(
                    endpoint,
                    r"""
local scene = sd.world.get_scene()
local participants = sd.bots.get_participants()
local native_bound = 0
for _, participant in ipairs(participants) do
    if participant.entity_materialized or
       (participant.actor_address or 0) ~= 0 or
       (participant.world_address or 0) ~= 0 or
       (participant.progression_handle_address or 0) ~= 0 or
       (participant.progression_runtime_state_address or 0) ~= 0 or
       (participant.equip_handle_address or 0) ~= 0 or
       (participant.equip_runtime_state_address or 0) ~= 0 then
        native_bound = native_bound + 1
    end
end
print('scene=' .. tostring(scene and (scene.kind or scene.name) or ''))
print('participants=' .. tostring(#participants))
print('native_bound=' .. tostring(native_bound))
""",
                    timeout=5.0,
                )
            )
            if state.get("scene") in {"hub", "arena", "testrun", "transition"}:
                continue
            if int(state.get("participants", "0")) < 1:
                raise VerifyFailure(
                    f"{endpoint} lost its authenticated participant during hub exit"
                )
            if int(state.get("native_bound", "-1")) != 0:
                continue
            released[endpoint] = state
            pending.remove(endpoint)
        if pending:
            time.sleep(0.05)
    if pending:
        raise VerifyFailure(
            "hub exit did not release native participants on endpoint(s): "
            + ", ".join(sorted(pending))
        )
    return released


def leave_endpoint_to_main_menu(
    pair: SteamFriendActivePair,
    endpoint: str,
    timeout: float,
) -> dict[str, Any]:
    scene = pair.lua(
        endpoint,
        "local s=sd.world.get_scene(); return tostring(s and (s.kind or s.name) or '')",
        timeout=5.0,
    ).strip()
    if scene not in {"hub", "arena", "testrun"}:
        return {"scene_before": scene, "already_released": True}

    deadline = time.monotonic() + min(timeout, 15.0)
    pressed = False
    blocking_dialog_actions: list[dict[str, Any]] = []
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            pair.lua(
                endpoint,
                r"""
local snapshot = sd.ui.get_snapshot()
local action = sd.ui.find_action('pause_menu.leave_game', 'simple_menu')
local dialog = sd.ui.find_action('dialog.primary', 'dialog')
local scene = sd.world.get_scene()
print('scene=' .. tostring(scene and (scene.kind or scene.name) or ''))
print('surface=' .. tostring(snapshot and snapshot.surface_id or ''))
print('action=' .. tostring(action ~= nil))
print('dialog=' .. tostring(dialog ~= nil))
""",
                timeout=5.0,
            )
        )
        if last.get("scene") not in {"hub", "arena", "testrun"}:
            release = wait_for_native_release_after_hub_leave(
                pair,
                min(timeout, 15.0),
                (endpoint,),
            )
            return {
                "scene_before": scene,
                "menu_pressed": pressed,
                "blocking_dialog_actions": blocking_dialog_actions,
                "already_released": True,
                "native_release": release[endpoint],
            }
        if last.get("surface") == "dialog" and last.get("dialog") == "true":
            blocking_dialog_actions.append(
                run_driver.local_sync.activate_native_ui_action(
                    endpoint,
                    "dialog.primary",
                    "dialog",
                )
            )
            pressed = False
            time.sleep(0.1)
            continue
        if last.get("surface") == "simple_menu" and last.get("action") == "true":
            break
        if not pressed:
            accepted = pair.lua(
                endpoint,
                "return tostring(sd.input.press_key('menu'))",
                timeout=5.0,
            ).strip()
            if accepted != "true":
                raise VerifyFailure(
                    f"{endpoint} pause-menu input was rejected: {accepted!r}"
                )
            pressed = True
        time.sleep(0.1)
    else:
        raise VerifyFailure(
            f"{endpoint} Leave Game action did not appear: {last}"
        )

    action = run_driver.local_sync.activate_native_ui_action(
        endpoint,
        "pause_menu.leave_game",
        "simple_menu",
    )
    release = wait_for_native_release_after_hub_leave(
        pair,
        min(timeout, 15.0),
        (endpoint,),
    )
    return {
        "scene_before": scene,
        "menu_pressed": pressed,
        "blocking_dialog_actions": blocking_dialog_actions,
        "action": action,
        "native_release": release[endpoint],
    }


def reset_pair_to_fresh_hub(
    pair: SteamFriendActivePair,
    timeout: float,
) -> dict[str, Any]:
    discovered = pair.discover()
    result: dict[str, Any] = {"before": discovered}
    result["leave"] = {
        endpoint: leave_endpoint_to_main_menu(pair, endpoint, timeout)
        for endpoint in (HOST_ENDPOINT, CLIENT_ENDPOINT)
    }
    result["new_game"] = run_driver.drive_pair_to_hub(
        pair,
        timeout,
        host_element="fire",
        client_element="air",
        discipline="arcane",
    )
    result["after"] = pair.discover()
    for endpoint, label in (
        (HOST_ENDPOINT, "host"),
        (CLIENT_ENDPOINT, "client"),
    ):
        state = capture(pair, endpoint)["owner_native"]
        if state["native_selector_list"] or state["capacity"] != 3:
            raise VerifyFailure(
                f"fresh {label} Hagatha state is not empty capacity three: {state}"
            )
    return result


def run(
    pair: SteamFriendActivePair,
    group_names: tuple[str, ...],
    timeout: float,
) -> dict[str, Any]:
    discovered = run_driver.configure_pair(pair)
    progression.lua = pair.lua
    directions = (
        Direction(
            "host_to_client",
            HOST_ENDPOINT,
            pair.host_participant_id,
            CLIENT_ENDPOINT,
            pair.client_participant_id,
        ),
        Direction(
            "client_to_host",
            CLIENT_ENDPOINT,
            pair.client_participant_id,
            HOST_ENDPOINT,
            pair.host_participant_id,
        ),
    )
    groups: dict[str, Any] = {}
    direction_error: str | None = None
    for group_name in group_names:
        group_result: dict[str, Any] = {"ok": False, "perks": {}}
        groups[group_name] = group_result
        try:
            group_result["fresh_hub"] = reset_pair_to_fresh_hub(
                pair,
                ONBOARDING_TIMEOUT,
            )
        except Exception as exc:
            direction_error = str(exc)
            group_result.update(
                error=direction_error,
                error_type=type(exc).__name__,
            )
            break
        for perk in GROUPS[group_name]:
            direction_results: dict[str, Any] = {}
            group_result["perks"][str(perk.selector)] = {
                "name": perk.name,
                "directions": direction_results,
            }
            for direction in directions:
                try:
                    if perk.selector == BARE_HANDS_SELECTOR:
                        direction_results[direction.name] = (
                            verify_bare_hands_direction(
                                pair,
                                direction,
                                perk,
                                timeout,
                            )
                        )
                    else:
                        direction_results[direction.name] = verify_direction(
                            pair,
                            direction,
                            perk,
                            timeout,
                        )
                except Exception as exc:
                    direction_error = str(exc)
                    direction_results[direction.name] = {
                        "ok": False,
                        "error": direction_error,
                        "error_type": type(exc).__name__,
                    }
                    break
            if direction_error is not None:
                group_result["error"] = direction_error
                break
        if direction_error is not None:
            break
        group_result["ok"] = True
    return {
        "ok": direction_error is None,
        "error": direction_error,
        "transport": "steam_friend",
        "pair_backend": PAIR_BACKEND,
        "pair": discovered,
        "groups": groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        action="append",
        choices=tuple(GROUPS),
        default=[],
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    group_names = tuple(args.group) if args.group else tuple(GROUPS)

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    try:
        result = run(pair, group_names, args.timeout)
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
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
                "groups": group_names,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
