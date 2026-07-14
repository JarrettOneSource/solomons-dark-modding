#!/usr/bin/env python3
"""Exhaustively verify per-participant native stat state and behavior contracts."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import (
    query_progression_snapshot,
    query_ranked_numeric_stat,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_int_text,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_all_upgrade_sync import (
    FLAT_BONEYARD,
    build_and_verify_catalog,
    choose_offer,
    enable_quiet_progression_test_mode,
    load_skill_configs,
    new_crash_artifacts,
    publish_deterministic_offer,
    query_level_state,
    wait_for_catalog_views,
    wait_for_offer,
    wait_for_pause,
    wait_for_post_run_progression_ready,
    wait_for_result,
    wait_for_target_parity,
    waiting_ids,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_all_stat_sync.json"
STAT_ROWS = tuple(range(56, 72))
SECONDARY_ROWS = tuple(range(48, 56)) + tuple(range(72, 80))
FLOAT_TOLERANCE = 0.002
DERIVED_FLOAT_FIELDS = (
    "cast_speed_multiplier",
    "mana_recovery_multiplier",
    "resist_magic_fraction",
    "resist_poison_fraction",
    "deflect_chance",
    "staff_melee_damage_a",
    "staff_melee_damage_b",
    "pickup_range",
    "secondary_recharge_multiplier",
    "offensive_damage_multiplier",
    "offensive_mana_multiplier",
    "meditation_recovery_bonus",
)
RANKED_PROPERTY_FIELDS = {
    56: ("mValue",),
    57: ("mValue",),
    58: ("mValue", "mSeconds"),
    59: ("mValue",),
    60: ("mValue",),
    61: ("mValue",),
    62: ("mValue",),
    64: ("mValue",),
    65: ("mDamage",),
    66: ("mValue",),
    67: ("mValue",),
    68: ("mValue",),
    69: ("mValue",),
    70: ("mValue",),
    71: ("mChance",),
}


def close_enough(left: float, right: float, tolerance: float = FLOAT_TOLERANCE) -> bool:
    return math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance


def require_close(label: str, actual: float, expected: float, tolerance: float = FLOAT_TOLERANCE) -> None:
    if not close_enough(actual, expected, tolerance):
        raise VerifyFailure(
            f"{label} mismatch: actual={actual:.6f} expected={expected:.6f} "
            f"tolerance={tolerance:.6f}"
        )


def parse_config_array(path: Path, field: str) -> list[float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"\b{re.escape(field)}\s*=\s*\{{(.*?)\}}\s*;", text, re.DOTALL)
    if match is None:
        raise VerifyFailure(f"{path.name} has no {field} array")
    values = [
        float(token)
        for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", match.group(1))
    ]
    if not values:
        raise VerifyFailure(f"{path.name} has an empty {field} array")
    return values


def parse_config_scalar(path: Path, field: str) -> float:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        rf"\b{re.escape(field)}\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*;",
        text,
    )
    if match is None:
        raise VerifyFailure(f"{path.name} has no scalar {field}")
    return float(match.group(1))


def load_stat_contract_values(
    catalog: list[dict[str, Any]],
    config_root: Path | None = None,
) -> dict[int, dict[str, list[float]]]:
    if config_root is None:
        config_root = (
            ROOT
            / "runtime/instances/local-mp-host/stage/data/wizardskills"
        )
    fields_by_row = {
        56: ("mValue",),
        57: ("mValue",),
        58: ("mValue", "mSeconds"),
        59: ("mValue",),
        60: ("mValue",),
        61: ("mValue",),
        62: ("mValue",),
        64: ("mValue",),
        65: ("mDamage",),
        66: ("mValue",),
        67: ("mValue",),
        68: ("mValue",),
        69: ("mValue",),
        70: ("mValue",),
        71: ("mChance",),
    }
    result: dict[int, dict[str, list[float]]] = {}
    for row, fields in fields_by_row.items():
        path = config_root / str(catalog[row]["skill_file"])
        result[row] = {field: parse_config_array(path, field) for field in fields}
        expected_length = int(catalog[row]["native_max_level"]) + 1
        for field, values in result[row].items():
            if len(values) not in (expected_length - 1, expected_length):
                raise VerifyFailure(
                    f"{path.name} {field} length={len(values)} "
                    f"expected={expected_length - 1} or {expected_length}"
                )
        if row in (57, 59, 61, 62, 67, 69, 70):
            result[row]["mConcentration"] = [
                parse_config_scalar(path, "mConcentration")
            ]
    return result


def view_specs(target_id: int) -> tuple[tuple[str, int | None], tuple[str, int | None]]:
    if target_id == HOST_ID:
        return (HOST_PIPE, None), (CLIENT_PIPE, HOST_ID)
    return (CLIENT_PIPE, None), (HOST_PIPE, CLIENT_ID)


def query_target_views(target_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    owner_spec, observer_spec = view_specs(target_id)
    return (
        query_progression_snapshot(owner_spec[0], participant_id=owner_spec[1]),
        query_progression_snapshot(observer_spec[0], participant_id=observer_spec[1]),
    )


def verify_ranked_property_matrix(
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
) -> dict[str, Any]:
    locations = {
        "host_owner": (HOST_PIPE, None),
        "client_observes_host": (CLIENT_PIPE, HOST_ID),
        "client_owner": (CLIENT_PIPE, None),
        "host_observes_client": (HOST_PIPE, CLIENT_ID),
    }
    views: dict[str, dict[int, dict[str, Any]]] = {}
    checked_values = 0
    for label, (pipe_name, participant_id) in locations.items():
        rows: dict[int, dict[str, Any]] = {}
        for row, property_fields in RANKED_PROPERTY_FIELDS.items():
            expected_rank = int(catalog[row]["native_max_level"])
            properties: dict[str, Any] = {}
            for property_name in property_fields:
                actual = query_ranked_numeric_stat(
                    pipe_name,
                    row,
                    property_name,
                    participant_id=participant_id,
                )
                expected_values = contract_values[row][property_name]
                expected_value = expected_values[
                    min(expected_rank, len(expected_values) - 1)
                ]
                if not actual["available"] or not actual["property_found"]:
                    raise VerifyFailure(
                        f"{label} row={row} native {property_name} is unavailable: {actual}"
                    )
                if int(actual["rank"]) != expected_rank:
                    raise VerifyFailure(
                        f"{label} row={row} native rank mismatch: "
                        f"actual={actual['rank']} expected={expected_rank}"
                    )
                require_close(
                    f"{label} row={row} native {property_name}",
                    float(actual["value"]),
                    float(expected_value),
                )
                properties[property_name] = {
                    **actual,
                    "expected_value": expected_value,
                }
                checked_values += 1
            rows[row] = {
                "skill_file": catalog[row]["skill_file"],
                "expected_rank": expected_rank,
                "properties": properties,
            }
        views[label] = rows
    return {
        "view_count": len(views),
        "row_count_per_view": len(RANKED_PROPERTY_FIELDS),
        "checked_value_count": checked_values,
        "views": views,
        "mismatches": [],
    }


def derived_mismatches(owner: dict[str, Any], observer: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    left = owner["native"]["derived"]
    right = observer["native"]["derived"]
    for field in DERIVED_FLOAT_FIELDS:
        if not close_enough(float(left[field]), float(right[field])):
            mismatches.append({"field": field, "owner": left[field], "observer": right[field]})
    if int(left["meditation_idle_ticks"]) != int(right["meditation_idle_ticks"]):
        mismatches.append(
            {
                "field": "meditation_idle_ticks",
                "owner": left["meditation_idle_ticks"],
                "observer": right["meditation_idle_ticks"],
            }
        )
    for field in ("concentration_entry_a", "concentration_entry_b"):
        owner_value = int(owner["ledger"][field])
        observer_value = int(observer["ledger"][field])
        if owner_value != observer_value:
            mismatches.append(
                {"field": field, "owner": owner_value, "observer": observer_value}
            )
    if owner["ledger"]["concentration_selection_valid"]:
        for suffix in ("a", "b"):
            native_value = int(
                owner["native"][f"process_concentration_entry_{suffix}"]
            )
            ledger_value = int(owner["ledger"][f"concentration_entry_{suffix}"])
            if native_value != ledger_value:
                mismatches.append(
                    {
                        "field": f"owner.native_ledger_concentration_{suffix}",
                        "native": native_value,
                        "ledger": ledger_value,
                    }
                )
    for label, snapshot in (("owner", owner), ("observer", observer)):
        if snapshot["ledger"]["concentration_selection_valid"]:
            for suffix in ("a", "b"):
                native_value = int(
                    snapshot["native"][f"slot_concentration_entry_{suffix}"]
                )
                ledger_value = int(
                    snapshot["ledger"][f"concentration_entry_{suffix}"]
                )
                if native_value != ledger_value:
                    mismatches.append(
                        {
                            "field": f"{label}.slot_concentration_{suffix}",
                            "native": native_value,
                            "ledger": ledger_value,
                            "gameplay_slot": snapshot["native"]["gameplay_slot"],
                        }
                    )
    for label, snapshot in (("owner", owner), ("observer", observer)):
        ledger_derived = snapshot["ledger"]["derived"]
        if not ledger_derived["valid"]:
            mismatches.append({"field": f"{label}.ledger_derived_valid", "value": False})
            continue
        for field in DERIVED_FLOAT_FIELDS:
            native_value = float(snapshot["native"]["derived"][field])
            ledger_value = float(ledger_derived[field])
            if not close_enough(native_value, ledger_value):
                mismatches.append(
                    {
                        "field": f"{label}.native_ledger_derived.{field}",
                        "native": native_value,
                        "ledger": ledger_value,
                    }
                )
        native_ticks = int(snapshot["native"]["derived"]["meditation_idle_ticks"])
        ledger_ticks = int(ledger_derived["meditation_idle_ticks"])
        if native_ticks != ledger_ticks:
            mismatches.append(
                {
                    "field": f"{label}.native_ledger_derived.meditation_idle_ticks",
                    "native": native_ticks,
                    "ledger": ledger_ticks,
                }
            )
    return mismatches


def wait_for_derived_parity(target_id: int, timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last: tuple[dict[str, Any], dict[str, Any]] | None = None
    while time.monotonic() < deadline:
        last = query_target_views(target_id)
        if not derived_mismatches(last[0], last[1]):
            return last
        time.sleep(0.05)
    assert last is not None
    raise VerifyFailure(
        f"derived stat parity timed out target={target_id}: "
        f"{derived_mismatches(last[0], last[1])}"
    )


def compact_snapshot(snapshot: dict[str, Any], row: int | None = None) -> dict[str, Any]:
    native = snapshot["native"]
    result: dict[str, Any] = {
        "level": native["level"],
        "xp": native["xp"],
        "hp": native["hp"],
        "max_hp": native["max_hp"],
        "mp": native["mp"],
        "max_mp": native["max_mp"],
        "move_speed": native["move_speed"],
        "gameplay_slot": native["gameplay_slot"],
        "process_concentration_entry_a": native["process_concentration_entry_a"],
        "process_concentration_entry_b": native["process_concentration_entry_b"],
        "slot_concentration_entry_a": native["slot_concentration_entry_a"],
        "slot_concentration_entry_b": native["slot_concentration_entry_b"],
        "derived": native["derived"],
        "spell": {
            key: snapshot["spell"][key]
            for key in (
                "resolved",
                "current_spell_id",
                "damage",
                "secondary_damage",
                "mana_cost",
                "mana_spend_cost",
                "error",
            )
        },
        "spellbook_revision": snapshot["ledger"]["spellbook_revision"],
        "statbook_revision": snapshot["ledger"]["statbook_revision"],
        "concentration_revision": snapshot["ledger"]["concentration_revision"],
        "derived_stat_revision": snapshot["ledger"]["derived_stat_revision"],
        "authoritative_derived": snapshot["ledger"]["derived"],
        "ledger_concentration_entry_a": snapshot["ledger"]["concentration_entry_a"],
        "ledger_concentration_entry_b": snapshot["ledger"]["concentration_entry_b"],
    }
    if row is not None:
        result["row"] = snapshot["native"]["entries"].get(row)
    return result


def assert_untargeted_unchanged(
    participant_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for field in ("level", "xp", "max_hp", "max_mp", "move_speed"):
        if not close_enough(float(before["native"][field]), float(after["native"][field]), 0.05):
            mismatches.append(
                {"field": field, "before": before["native"][field], "after": after["native"][field]}
            )
    if before["native"]["entries"] != after["native"]["entries"]:
        changed_rows = [
            row
            for row in sorted(set(before["native"]["entries"]) | set(after["native"]["entries"]))
            if before["native"]["entries"].get(row) != after["native"]["entries"].get(row)
        ]
        mismatches.append({"field": "native_entries", "changed_rows": changed_rows})
    for field in DERIVED_FLOAT_FIELDS:
        left = float(before["native"]["derived"][field])
        right = float(after["native"]["derived"][field])
        if not close_enough(left, right):
            mismatches.append({"field": f"derived.{field}", "before": left, "after": right})
    if (
        int(before["native"]["derived"]["meditation_idle_ticks"])
        != int(after["native"]["derived"]["meditation_idle_ticks"])
    ):
        mismatches.append(
            {
                "field": "derived.meditation_idle_ticks",
                "before": before["native"]["derived"]["meditation_idle_ticks"],
                "after": after["native"]["derived"]["meditation_idle_ticks"],
            }
        )
    if before["loadout"] != after["loadout"]:
        mismatches.append({"field": "loadout", "before": before["loadout"], "after": after["loadout"]})
    for field in ("concentration_entry_a", "concentration_entry_b"):
        if int(before["ledger"][field]) != int(after["ledger"][field]):
            mismatches.append(
                {
                    "field": f"ledger.{field}",
                    "before": before["ledger"][field],
                    "after": after["ledger"][field],
                }
            )
    if mismatches:
        raise VerifyFailure(
            f"stat apply contaminated untargeted participant={participant_id}: {mismatches}"
        )
    return {"participant_id": participant_id, "mismatches": []}


def assert_stat_contract(
    row: int,
    active: int,
    snapshot: dict[str, Any],
    initial: dict[str, Any],
    values: dict[int, dict[str, list[float]]],
) -> dict[str, Any]:
    native = snapshot["native"]
    derived = native["derived"]
    expected: dict[str, float | int] = {}
    concentrated = row in (
        int(snapshot["ledger"]["concentration_entry_a"]),
        int(snapshot["ledger"]["concentration_entry_b"]),
    )
    def value(field: str) -> float:
        field_values = values[row][field]
        return field_values[min(active, len(field_values) - 1)]

    if row == 56:
        expected["max_mp"] = float(initial["native"]["max_mp"]) + value("mValue")
    elif row == 57:
        expected["mana_recovery_multiplier"] = (
            float(initial["native"]["derived"]["mana_recovery_multiplier"])
            * (1.0 + value("mValue") / 100.0)
        )
        if concentrated:
            expected["mana_recovery_multiplier"] *= (
                1.0 + value("mConcentration") / 100.0
            )
    elif row == 58:
        expected["meditation_idle_ticks"] = int(round(value("mSeconds") * 100.0))
        expected["meditation_recovery_bonus"] = value("mValue") - 1.0
    elif row == 59:
        expected["offensive_mana_multiplier"] = 1.0 - value("mValue") / 100.0
        if concentrated:
            expected["offensive_mana_multiplier"] -= value("mConcentration") / 100.0
    elif row == 60:
        expected["secondary_recharge_multiplier"] = 1.0 + value("mValue") / 100.0
    elif row == 61:
        expected["offensive_damage_multiplier"] = 1.0 + value("mValue") / 100.0
        if concentrated:
            expected["offensive_damage_multiplier"] += value("mConcentration") / 100.0
    elif row == 62:
        expected["resist_magic_fraction"] = value("mValue") / 100.0
        if concentrated:
            expected["resist_magic_fraction"] += value("mConcentration") / 100.0
    elif row == 64:
        expected["max_hp"] = float(initial["native"]["max_hp"]) + value("mValue")
    elif row == 65:
        expected["staff_melee_damage_a"] = (
            float(initial["native"]["derived"]["staff_melee_damage_a"])
            + value("mDamage")
        )
        expected["staff_melee_damage_b"] = (
            float(initial["native"]["derived"]["staff_melee_damage_b"])
            + value("mDamage")
        )
    elif row == 66:
        base_value = values[row]["mValue"][0]
        expected["pickup_range"] = (
            float(initial["native"]["derived"]["pickup_range"])
            * value("mValue")
            / base_value
        )
        if concentrated:
            expected["pickup_range"] *= 2.0
    elif row == 67:
        # Rush's ranked mValue is consumed by the stock movement path at run
        # time; it is not baked into progression+0x90 by stat refresh. Only
        # Rush's selected Concentrate bonus modifies that standing field.
        expected["move_speed"] = float(initial["native"]["move_speed"])
        if concentrated:
            expected["move_speed"] *= 1.0 + value("mConcentration") / 100.0
    elif row == 68:
        expected["deflect_chance"] = value("mValue")
    elif row == 69:
        expected["resist_poison_fraction"] = value("mValue") / 100.0
        if concentrated:
            expected["resist_poison_fraction"] += value("mConcentration") / 100.0
    elif row == 70:
        expected["cast_speed_multiplier"] = 1.0 + value("mValue") / 100.0
        if concentrated:
            expected["cast_speed_multiplier"] += value("mConcentration") / 100.0

    actual_by_field: dict[str, float | int] = {
        "max_hp": native["max_hp"],
        "max_mp": native["max_mp"],
        "move_speed": native["move_speed"],
        **derived,
    }
    for field, expected_value in expected.items():
        actual_value = actual_by_field[field]
        if isinstance(expected_value, int):
            if int(actual_value) != expected_value:
                raise VerifyFailure(
                    f"row={row} active={active} {field} mismatch: "
                    f"actual={actual_value} expected={expected_value}"
                )
        else:
            require_close(f"row={row} active={active} {field}", float(actual_value), expected_value)
    return {
        "row": row,
        "active": active,
        "concentrated": concentrated,
        "concentration_entry_a": snapshot["ledger"]["concentration_entry_a"],
        "concentration_entry_b": snapshot["ledger"]["concentration_entry_b"],
        "expected": expected,
    }


def apply_stat_batch(
    catalog: list[dict[str, Any]],
    row: int,
    target_id: int,
    apply_count: int,
    initial_by_target: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    untargeted_id = CLIENT_ID if target_id == HOST_ID else HOST_ID
    untargeted_pipe = CLIENT_PIPE if target_id == HOST_ID else HOST_PIPE
    before = query_progression_snapshot(target_pipe)
    untargeted_before = query_progression_snapshot(untargeted_pipe)
    before_active = int(before["native"]["entries"][row]["active"])
    expected_active = before_active + apply_count
    target_level = int(before["native"]["level"]) + 1
    target_experience = int(math.ceil(before["native"]["next_xp_threshold"]))

    publish = publish_deterministic_offer(
        target_id,
        target_level,
        target_experience,
        row,
        apply_count,
    )
    offer = wait_for_offer(
        target_pipe,
        target_id,
        target_level,
        row,
        timeout,
        apply_count,
    )
    pause_active = wait_for_pause(target_id, True, timeout)
    choice = choose_offer(target_pipe, offer["offer_id"], row)
    result = wait_for_result(
        offer["offer_id"],
        target_id,
        target_level,
        row,
        expected_active,
        timeout,
        apply_count,
    )
    parity = wait_for_target_parity(
        target_id,
        row,
        expected_active,
        target_level,
        timeout,
    )
    pause_cleared = wait_for_pause(target_id, False, timeout)
    owner, observer = wait_for_derived_parity(target_id, timeout)
    contract = assert_stat_contract(
        row,
        expected_active,
        owner,
        initial_by_target[target_id],
        contract_values,
    )
    assert_stat_contract(
        row,
        expected_active,
        observer,
        initial_by_target[target_id],
        contract_values,
    )
    untargeted_after = query_progression_snapshot(untargeted_pipe)
    isolation = assert_untargeted_unchanged(
        untargeted_id,
        untargeted_before,
        untargeted_after,
    )
    return {
        "direction": "host_owned" if target_id == HOST_ID else "client_owned",
        "target_participant_id": target_id,
        "row": row,
        "skill_file": catalog[row]["skill_file"],
        "skill_name": catalog[row]["skill_name"],
        "apply_count": apply_count,
        "before_active": before_active,
        "resulting_active": expected_active,
        "target_level": target_level,
        "target_experience": target_experience,
        "publish": publish,
        "offer": offer,
        "pause_active": pause_active,
        "choice": choice,
        "result": result,
        "parity": {
            "owner_active": parity["owner_active"],
            "observer_active": parity["observer_active"],
            "owner_level": parity["owner_level"],
            "observer_spell": parity["spell"],
        },
        "pause_cleared": pause_cleared,
        "derived_parity_mismatches": derived_mismatches(owner, observer),
        "contract": contract,
        "owner": compact_snapshot(owner, row),
        "observer": compact_snapshot(observer, row),
        "untargeted_isolation": isolation,
    }


def publish_natural_offer(target_id: int, level: int, experience: int) -> dict[str, str]:
    target = (
        "target_self = true,"
        if target_id == HOST_ID
        else f"target_participant_id = {target_id},"
    )
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.runtime.debug_publish_level_up_offer, {{
  level = {level},
  experience = {experience},
  {target}
}})
emit('pcall_ok', ok)
emit('result', result)
"""
    values = parse_key_values(lua(HOST_PIPE, code, timeout=8.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(f"natural offer publish failed target={target_id}: {values}")
    return values


def wait_for_natural_offer(
    pipe_name: str,
    target_id: int,
    expected_count: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_level_state(pipe_name)
        count = parse_int_text(last.get("offer.option_count"), 0)
        if (
            last.get("offer.valid") == "true"
            and parse_int_text(last.get("offer.target"), 0) == target_id
            and count == expected_count
        ):
            options = [
                {
                    "id": parse_int_text(last.get(f"offer.option.{index}.id"), -1),
                    "apply_count": parse_int_text(
                        last.get(f"offer.option.{index}.apply_count"), 0
                    ),
                }
                for index in range(1, count + 1)
            ]
            return {
                "offer_id": parse_int_text(last.get("offer.id"), 0),
                "target": target_id,
                "level": parse_int_text(last.get("offer.level"), 0),
                "experience": parse_int_text(last.get("offer.experience"), 0),
                "options": options,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"natural offer count did not settle target={target_id} "
        f"expected={expected_count}: {last}"
    )


def parse_matching_natural_offer(
    values: dict[str, str],
    target_id: int,
    expected_count: int,
) -> dict[str, Any] | None:
    count = parse_int_text(values.get("offer.option_count"), 0)
    if (
        values.get("offer.valid") != "true"
        or parse_int_text(values.get("offer.target"), 0) != target_id
        or count != expected_count
    ):
        return None
    return {
        "offer_id": parse_int_text(values.get("offer.id"), 0),
        "target": target_id,
        "level": parse_int_text(values.get("offer.level"), 0),
        "experience": parse_int_text(values.get("offer.experience"), 0),
        "options": [
            {
                "id": parse_int_text(values.get(f"offer.option.{index}.id"), -1),
                "apply_count": parse_int_text(
                    values.get(f"offer.option.{index}.apply_count"), 0
                ),
            }
            for index in range(1, count + 1)
        ],
    }


def exercise_natural_offer(target_id: int, expected_count: int, timeout: float) -> dict[str, Any]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    before = query_progression_snapshot(target_pipe)
    existing = parse_matching_natural_offer(
        query_level_state(target_pipe),
        target_id,
        expected_count,
    )
    if existing is not None:
        offer = existing
        publish: dict[str, Any] = {"reused_pending_offer": True}
    else:
        level = int(before["native"]["level"]) + 1
        experience = int(math.ceil(before["native"]["next_xp_threshold"]))
        publish = publish_natural_offer(target_id, level, experience)
        offer = wait_for_natural_offer(target_pipe, target_id, expected_count, timeout)
    level = int(offer["level"])
    pause_active = wait_for_pause(target_id, True, timeout)
    selected = offer["options"][0]
    before_active = int(before["native"]["entries"][selected["id"]]["active"])
    expected_active = before_active + int(selected["apply_count"])
    choice = choose_offer(target_pipe, offer["offer_id"], selected["id"])
    result = wait_for_result(
        offer["offer_id"],
        target_id,
        level,
        selected["id"],
        expected_active,
        timeout,
        int(selected["apply_count"]),
    )
    parity = wait_for_target_parity(
        target_id,
        selected["id"],
        expected_active,
        level,
        timeout,
    )
    pause_cleared = wait_for_pause(target_id, False, timeout)
    owner, observer = wait_for_derived_parity(target_id, timeout)
    return {
        "target_participant_id": target_id,
        "expected_option_count": expected_count,
        "publish": publish,
        "offer": offer,
        "pause_active": pause_active,
        "selected": selected,
        "choice": choice,
        "result": result,
        "parity": {
            "owner_active": parity["owner_active"],
            "observer_active": parity["observer_active"],
        },
        "pause_cleared": pause_cleared,
        "derived_parity_mismatches": derived_mismatches(owner, observer),
    }


def parse_pending_natural_offer(
    values: dict[str, str],
    target_id: int,
) -> dict[str, Any] | None:
    count = parse_int_text(values.get("offer.option_count"), 0)
    if (
        values.get("offer.valid") != "true"
        or values.get("offer.submitted") == "true"
        or parse_int_text(values.get("offer.target"), 0) != target_id
        or count <= 0
    ):
        return None
    return {
        "offer_id": parse_int_text(values.get("offer.id"), 0),
        "target": target_id,
        "level": parse_int_text(values.get("offer.level"), 0),
        "experience": parse_int_text(values.get("offer.experience"), 0),
        "options": [
            {
                "id": parse_int_text(values.get(f"offer.option.{index}.id"), -1),
                "apply_count": parse_int_text(
                    values.get(f"offer.option.{index}.apply_count"), 0
                ),
            }
            for index in range(1, count + 1)
        ],
    }


def resolve_pending_natural_offer(
    target_id: int,
    offer: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    before = query_progression_snapshot(target_pipe)
    selected = offer["options"][0]
    before_active = int(before["native"]["entries"][selected["id"]]["active"])
    expected_active = before_active + int(selected["apply_count"])
    choice = choose_offer(target_pipe, offer["offer_id"], selected["id"])
    result = wait_for_result(
        offer["offer_id"],
        target_id,
        int(offer["level"]),
        selected["id"],
        expected_active,
        timeout,
        int(selected["apply_count"]),
    )
    parity = wait_for_target_parity(
        target_id,
        selected["id"],
        expected_active,
        int(offer["level"]),
        timeout,
    )
    target_pause_cleared = wait_for_pause(target_id, False, timeout)
    owner, observer = wait_for_derived_parity(target_id, timeout)
    return {
        "target_participant_id": target_id,
        "offer": offer,
        "selected": selected,
        "choice": choice,
        "result": result,
        "parity": {
            "owner_active": parity["owner_active"],
            "observer_active": parity["observer_active"],
        },
        "target_pause_cleared": target_pause_cleared,
        "derived_parity_mismatches": derived_mismatches(owner, observer),
    }


def drain_pending_natural_offers(timeout: float, max_offers: int = 12) -> dict[str, Any]:
    resolved: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host_state = query_level_state(HOST_PIPE)
        client_state = query_level_state(CLIENT_PIPE)
        last = {
            "host_waiting_ids": waiting_ids(host_state),
            "client_waiting_ids": waiting_ids(client_state),
            "host_pause_active": host_state.get("wait.pause_active") == "true",
            "client_pause_active": client_state.get("wait.pause_active") == "true",
        }

        pending = (
            parse_pending_natural_offer(host_state, HOST_ID),
            parse_pending_natural_offer(client_state, CLIENT_ID),
        )
        made_progress = False
        for target_id, offer in zip((HOST_ID, CLIENT_ID), pending):
            if offer is None:
                continue
            if len(resolved) >= max_offers:
                raise VerifyFailure(
                    f"natural-offer drain exceeded {max_offers} offers: {last}"
                )
            resolved.append(resolve_pending_natural_offer(target_id, offer, timeout))
            made_progress = True
            break

        if made_progress:
            continue
        if (
            not last["host_waiting_ids"]
            and not last["client_waiting_ids"]
            and not last["host_pause_active"]
            and not last["client_pause_active"]
        ):
            return {"resolved": resolved, "final": last}
        time.sleep(0.05)
    raise VerifyFailure(f"shared level-up pause did not fully drain: {last}")


def query_secondary_costs(pipe_name: str, participant_id: int | None) -> dict[int, dict[str, Any]]:
    participant_selector = "nil" if participant_id is None else str(participant_id)
    row_list = ",".join(str(row) for row in SECONDARY_ROWS)
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value == nil and '' or value)) end
local requested = {participant_selector}
local progression = 0
if requested == nil then
  local player = sd.player.get_state()
  progression = tonumber(player and player.progression_address) or 0
else
  local bot = sd.bots.get_participant_state(requested)
  progression = tonumber(bot and bot.progression_runtime_state_address) or 0
end
emit('progression', progression)
for _, row in ipairs({{{row_list}}}) do
  local stats = sd.debug.resolve_native_secondary_mana_stats(progression, row)
  local prefix = 'row.' .. tostring(row) .. '.'
  emit(prefix .. 'resolved', stats and stats.resolved or false)
  emit(prefix .. 'level', stats and stats.progression_level or 0)
  emit(prefix .. 'base_cost', stats and stats.base_cost or 0)
  emit(prefix .. 'spend_cost', stats and stats.spend_cost or 0)
  emit(prefix .. 'seh', stats and stats.resolver_seh_code or 0)
  emit(prefix .. 'error', stats and stats.error or '')
end
"""
    raw = parse_key_values(lua(pipe_name, code, timeout=10.0))
    result: dict[int, dict[str, Any]] = {}
    for row in SECONDARY_ROWS:
        prefix = f"row.{row}."
        result[row] = {
            "resolved": raw.get(prefix + "resolved") == "true",
            "level": parse_int_text(raw.get(prefix + "level"), 0),
            "base_cost": float(raw.get(prefix + "base_cost", "0") or 0.0),
            "spend_cost": float(raw.get(prefix + "spend_cost", "0") or 0.0),
            "resolver_seh_code": parse_int_text(raw.get(prefix + "seh"), 0),
            "error": raw.get(prefix + "error", ""),
        }
    return result


def capture_secondary_cost_matrix() -> dict[str, dict[int, dict[str, Any]]]:
    return {
        "host_owner": query_secondary_costs(HOST_PIPE, None),
        "client_observes_host": query_secondary_costs(CLIENT_PIPE, HOST_ID),
        "client_owner": query_secondary_costs(CLIENT_PIPE, None),
        "host_observes_client": query_secondary_costs(HOST_PIPE, CLIENT_ID),
    }


def verify_secondary_cost_parity(matrix: dict[str, dict[int, dict[str, Any]]]) -> dict[str, Any]:
    pairs = (
        ("host_owner", "client_observes_host"),
        ("client_owner", "host_observes_client"),
    )
    resolved = 0
    mismatches: list[dict[str, Any]] = []
    for owner_label, observer_label in pairs:
        for row in SECONDARY_ROWS:
            owner = matrix[owner_label][row]
            observer = matrix[observer_label][row]
            if owner["resolved"] != observer["resolved"]:
                mismatches.append(
                    {"pair": [owner_label, observer_label], "row": row, "field": "resolved", "owner": owner, "observer": observer}
                )
                continue
            if not owner["resolved"]:
                continue
            resolved += 1
            for field in ("base_cost", "spend_cost"):
                if not close_enough(float(owner[field]), float(observer[field])):
                    mismatches.append(
                        {"pair": [owner_label, observer_label], "row": row, "field": field, "owner": owner[field], "observer": observer[field]}
                    )
    if mismatches:
        raise VerifyFailure(f"secondary mana stat parity failed: {mismatches}")
    return {"resolved_pair_rows": resolved, "mismatches": []}


def set_local_mana(pipe_name: str, value: float) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local player = sd.player.get_state()
local progression = tonumber(player and player.progression_address) or 0
local offset = sd.debug.layout_offset('progression_mp')
emit('progression', progression)
emit('before', progression ~= 0 and sd.debug.read_float(progression + offset) or -1)
emit('write', progression ~= 0 and sd.debug.write_float(progression + offset, {value}) or false)
emit('after', progression ~= 0 and sd.debug.read_float(progression + offset) or -1)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    if values.get("write") != "true":
        raise VerifyFailure(f"failed to set local mana on {pipe_name}: {values}")
    return values


def sample_mana_recovery(target_id: int, duration: float = 2.25) -> dict[str, Any]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    before, _ = query_target_views(target_id)
    precondition_max_mp = float(before["native"]["max_mp"])
    set_result = set_local_mana(target_pipe, 0.0)
    settle_deadline = time.monotonic() + 4.0
    settle_samples: list[dict[str, Any]] = []
    settle_ceiling = max(5.0, precondition_max_mp * 0.25)
    while time.monotonic() < settle_deadline:
        owner, observer = query_target_views(target_id)
        settle_sample = {
            "owner_mp": owner["native"]["mp"],
            "observer_native_mp": observer["native"]["mp"],
            "observer_runtime_mp": observer["runtime"]["mana_current"],
        }
        settle_samples.append(settle_sample)
        if (
            float(settle_sample["observer_native_mp"]) < settle_ceiling
            and float(settle_sample["observer_runtime_mp"]) < settle_ceiling
        ):
            break
        time.sleep(0.05)
    else:
        raise VerifyFailure(
            f"target={target_id} forced mana precondition did not replicate: "
            f"ceiling={settle_ceiling:.3f} samples={settle_samples}"
        )

    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    while True:
        elapsed = time.monotonic() - started
        owner, observer = query_target_views(target_id)
        samples.append(
            {
                "elapsed": elapsed,
                "owner_mp": owner["native"]["mp"],
                "observer_native_mp": observer["native"]["mp"],
                "observer_runtime_mp": observer["runtime"]["mana_current"],
            }
        )
        if elapsed >= duration:
            break
        time.sleep(0.2)
    owner_gain = float(samples[-1]["owner_mp"]) - float(samples[0]["owner_mp"])
    native_runtime_errors = [
        abs(float(sample["observer_native_mp"]) - float(sample["observer_runtime_mp"]))
        for sample in samples
    ]
    owner_observer_errors = [
        abs(float(sample["owner_mp"]) - float(sample["observer_native_mp"]))
        for sample in samples
    ]
    # Owner and observer snapshots are queried sequentially while mana is
    # changing.  Bound allowed skew by half a second of the measured recovery
    # rate.  The observer runtime ledger and native clone are also refreshed on
    # distinct service/gameplay ticks, so allow 150 ms of the same measured
    # rate there instead of a fixed epsilon that rejects ordinary recovery.
    observed_rate = max(0.0, owner_gain / max(duration, 0.001))
    replication_tolerance = max(2.0, observed_rate * 0.5)
    native_runtime_tolerance = max(1.0, observed_rate * 0.15)
    if max(native_runtime_errors, default=0.0) > native_runtime_tolerance:
        raise VerifyFailure(
            f"target={target_id} observer native/runtime mana diverged: "
            f"errors={native_runtime_errors} "
            f"tolerance={native_runtime_tolerance:.3f}"
        )
    if max(owner_observer_errors, default=0.0) > replication_tolerance:
        raise VerifyFailure(
            f"target={target_id} live mana recovery did not replicate within bounded skew: "
            f"errors={owner_observer_errors} tolerance={replication_tolerance:.3f}"
        )
    return {
        "target_participant_id": target_id,
        "set": set_result,
        "precondition_max_mp": precondition_max_mp,
        "settle_ceiling": settle_ceiling,
        "settle_samples": settle_samples,
        "gain": owner_gain,
        "observed_rate": observed_rate,
        "replication_tolerance": replication_tolerance,
        "native_runtime_tolerance": native_runtime_tolerance,
        "max_owner_observer_error": max(owner_observer_errors, default=0.0),
        "max_observer_native_runtime_error": max(native_runtime_errors, default=0.0),
        "samples": samples,
    }


def verify_final_maxima(
    catalog: list[dict[str, Any]],
    initial_by_target: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, target_id in (("host", HOST_ID), ("client", CLIENT_ID)):
        owner, observer = wait_for_derived_parity(target_id, timeout)
        for row in STAT_ROWS:
            active = int(owner["native"]["entries"][row]["active"])
            maximum = int(catalog[row]["native_max_level"])
            if active != maximum:
                raise VerifyFailure(
                    f"{label} stat row={row} ended active={active} max={maximum}"
                )
            assert_stat_contract(
                row,
                active,
                owner,
                initial_by_target[target_id],
                contract_values,
            )
        result[label] = {
            "owner": compact_snapshot(owner),
            "observer": compact_snapshot(observer),
            "derived_parity_mismatches": derived_mismatches(owner, observer),
            "maxed_rows": list(STAT_ROWS),
        }
    return result


def run_stat_matrix(
    catalog: list[dict[str, Any]],
    initial_by_target: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
    output: dict[str, Any],
) -> None:
    steps: list[dict[str, Any]] = output.setdefault("steps", [])
    for row in STAT_ROWS:
        maximum = int(catalog[row]["native_max_level"])
        for target_id in (HOST_ID, CLIENT_ID):
            target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
            while True:
                snapshot = query_progression_snapshot(target_pipe)
                active = int(snapshot["native"]["entries"][row]["active"])
                if active >= maximum:
                    break
                apply_count = min(2, maximum - active)
                step = apply_stat_batch(
                    catalog,
                    row,
                    target_id,
                    apply_count,
                    initial_by_target,
                    contract_values,
                    timeout,
                )
                steps.append(step)
                output["completed_step_count"] = len(steps)
                print(
                    f"[{len(steps)}] {step['direction']} row={row} "
                    f"{step['skill_file']} active={step['resulting_active']}/{maximum}",
                    flush=True,
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--test-boneyard-override",
        type=Path,
        default=FLAT_BONEYARD,
    )
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        stop_games()
        output["launch"] = launch_pair(
            preset="map_create_fire_mind_hub",
            god_mode=False,
            test_survival_boneyard_override=args.test_boneyard_override,
        )
        disable_bots()
        output["hub_ready"] = {
            "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub", args.timeout),
            "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub", args.timeout),
        }
        catalog_views = wait_for_catalog_views(args.timeout)
        catalog_result = build_and_verify_catalog(catalog_views, load_skill_configs())
        catalog = catalog_result["catalog"]
        output["catalog_summary"] = {
            key: value for key, value in catalog_result.items() if key != "catalog"
        }
        output["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=args.timeout)
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(args.timeout)

        initial_by_target = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }
        output["initial"] = {
            "host": compact_snapshot(initial_by_target[HOST_ID]),
            "client": compact_snapshot(initial_by_target[CLIENT_ID]),
        }
        for target_id in (HOST_ID, CLIENT_ID):
            owner, observer = wait_for_derived_parity(target_id, args.timeout)
            if derived_mismatches(owner, observer):
                raise VerifyFailure(f"initial derived parity failed target={target_id}")

        contract_values = load_stat_contract_values(catalog)
        output["stat_contract_values"] = contract_values
        output["baseline_secondary_costs"] = capture_secondary_cost_matrix()
        output["baseline_secondary_cost_parity"] = verify_secondary_cost_parity(
            output["baseline_secondary_costs"]
        )
        output["baseline_mana_recovery"] = {
            "host": sample_mana_recovery(HOST_ID),
            "client": sample_mana_recovery(CLIENT_ID),
        }

        # The unranked native picker must remain participant-specific: a
        # Creativity-free client receives the stock three choices.
        output["creativity_baseline_client"] = exercise_natural_offer(
            CLIENT_ID,
            3,
            args.timeout,
        )

        matrix: dict[str, Any] = {
            "stat_rows": list(STAT_ROWS),
            "completed_step_count": 0,
            "steps": [],
        }
        output["matrix"] = matrix
        run_stat_matrix(
            catalog,
            initial_by_target,
            contract_values,
            args.timeout,
            matrix,
        )

        # Both participants now own Creativity independently, and each native
        # picker must roll four choices through that participant's progression.
        # The last client-owned matrix level can leave its legitimate native
        # four-choice offer pending. Resolve that participant first and reuse
        # the offer instead of overlapping it with a newly-issued host offer.
        creativity_client = exercise_natural_offer(CLIENT_ID, 4, args.timeout)
        creativity_host = exercise_natural_offer(HOST_ID, 4, args.timeout)
        output["creativity_upgraded"] = {
            "host": creativity_host,
            "client": creativity_client,
        }
        output["post_creativity_offer_drain"] = drain_pending_natural_offers(
            args.timeout
        )
        output["final"] = verify_final_maxima(
            catalog,
            initial_by_target,
            contract_values,
            args.timeout,
        )
        output["final_ranked_property_matrix"] = verify_ranked_property_matrix(
            catalog,
            contract_values,
        )
        output["final_secondary_costs"] = capture_secondary_cost_matrix()
        output["final_secondary_cost_parity"] = verify_secondary_cost_parity(
            output["final_secondary_costs"]
        )
        output["final_mana_recovery"] = {
            "host": sample_mana_recovery(HOST_ID),
            "client": sample_mana_recovery(CLIENT_ID),
        }
        for label in ("host", "client"):
            baseline_gain = float(output["baseline_mana_recovery"][label]["gain"])
            final_gain = float(output["final_mana_recovery"][label]["gain"])
            if final_gain <= baseline_gain + 0.5:
                raise VerifyFailure(
                    f"{label} max Channel/Meditation did not improve live mana recovery: "
                    f"baseline={baseline_gain:.3f} final={final_gain:.3f}"
                )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts appeared during stat matrix: {crashes}")
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

    matrix = output.get("matrix", {})
    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "completed_step_count": matrix.get("completed_step_count", 0),
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
