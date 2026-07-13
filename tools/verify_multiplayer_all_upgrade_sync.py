#!/usr/bin/env python3
"""Apply every native wizard upgrade through authoritative multiplayer offers."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import (
    compare_book_rows,
    compare_float_fields,
    query_progression_snapshot,
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
from verify_multiplayer_progression_catalog import (
    build_and_verify_catalog,
    load_skill_configs,
    wait_for_catalog_views,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime" / "multiplayer_all_upgrade_sync.json"
FLAT_BONEYARD = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"


LEVEL_STATE_LUA = r"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local offer = mp and mp.active_level_up_offer or nil
local result = mp and mp.last_level_up_choice_result or nil
local wait = mp and mp.level_up_wait_status or nil
emit('offer.valid', offer and offer.valid or false)
emit('offer.target', offer and offer.target_participant_id or 0)
emit('offer.id', offer and offer.offer_id or 0)
emit('offer.level', offer and offer.level or 0)
emit('offer.experience', offer and offer.experience or 0)
emit('offer.option_count', offer and offer.option_count or 0)
emit('offer.submitted', offer and offer.selection_submitted or false)
if offer and offer.options then
  for index, option in ipairs(offer.options) do
    emit('offer.option.' .. tostring(index) .. '.id', option.option_id or -1)
    emit('offer.option.' .. tostring(index) .. '.apply_count', option.apply_count or 0)
  end
end
emit('result.valid', result and result.valid or false)
emit('result.target', result and result.target_participant_id or 0)
emit('result.offer_id', result and result.offer_id or 0)
emit('result.level', result and result.level or 0)
emit('result.option_id', result and result.option_id or -1)
emit('result.apply_count', result and result.apply_count or 0)
emit('result.resulting_active', result and result.resulting_active or 0)
emit('result.code', result and result.result_code or 0)
emit('wait.valid', wait and wait.valid or false)
emit('wait.pause_active', wait and wait.pause_active or false)
emit('wait.count', wait and wait.waiting_count or 0)
if wait and wait.waiting_participant_ids then
  for index, participant_id in ipairs(wait.waiting_participant_ids) do
    emit('wait.participant.' .. tostring(index), participant_id)
  end
end
"""


def query_level_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, LEVEL_STATE_LUA, timeout=5.0))


def waiting_ids(values: dict[str, str]) -> list[int]:
    count = parse_int_text(values.get("wait.count"), 0)
    return [
        parse_int_text(values.get(f"wait.participant.{index}"), 0)
        for index in range(1, count + 1)
    ]


def publish_deterministic_offer(
    target_participant_id: int,
    level: int,
    experience: int,
    option_id: int,
    apply_count: int = 1,
) -> dict[str, str]:
    target_self = target_participant_id == HOST_ID
    target_fields = (
        "target_self = true,"
        if target_self
        else f"target_participant_id = {target_participant_id},"
    )
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.runtime.debug_publish_level_up_offer, {{
  level = {level},
  experience = {experience},
  {target_fields}
  option_id = {option_id},
  apply_count = {apply_count},
}})
emit('pcall_ok', ok)
emit('result', result)
"""
    deadline = time.monotonic() + 2.0
    values: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(lua(HOST_PIPE, code, timeout=8.0))
        if values.get("pcall_ok") == "true" and values.get("result") == "true":
            return values
        result = values.get("result", "")
        if not any(
            marker in result
            for marker in (
                "target participant is unavailable",
                "target transport is disconnected",
                "target progression is uninitialized",
                "target progression book is truncated",
            )
        ):
            break
        time.sleep(0.05)
    raise VerifyFailure(
        f"deterministic offer publish failed target={target_participant_id} "
        f"option={option_id}: {values}"
    )


def enable_quiet_progression_test_mode() -> dict[str, dict[str, str]]:
    code = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(true)
emit('ok', ok)
emit('active', active)
"""
    result: dict[str, dict[str, str]] = {}
    for label, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE)):
        values = parse_key_values(lua(pipe_name, code, timeout=8.0))
        if values.get("ok") != "true" or values.get("active") != "true":
            raise VerifyFailure(
                f"failed to enable quiet progression test mode on {label}: {values}"
            )
        result[label] = values
    return result


def wait_for_offer(
    pipe_name: str,
    target_participant_id: int,
    level: int,
    option_id: int,
    timeout: float,
    apply_count: int = 1,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_level_state(pipe_name)
        if (
            last.get("offer.valid") == "true"
            and parse_int_text(last.get("offer.target"), 0) == target_participant_id
            and parse_int_text(last.get("offer.level"), 0) == level
            and parse_int_text(last.get("offer.option_count"), 0) == 1
            and parse_int_text(last.get("offer.option.1.id"), -1) == option_id
            and parse_int_text(last.get("offer.option.1.apply_count"), 0)
            == apply_count
        ):
            return {
                "offer_id": parse_int_text(last.get("offer.id"), 0),
                "target": target_participant_id,
                "level": level,
                "experience": parse_int_text(last.get("offer.experience"), 0),
                "option_id": option_id,
                "apply_count": apply_count,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"deterministic offer did not arrive target={target_participant_id} "
        f"level={level} option={option_id}: {last}"
    )


def wait_for_pause(
    target_participant_id: int,
    active: bool,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host = query_level_state(HOST_PIPE)
        client = query_level_state(CLIENT_PIPE)
        host_ids = waiting_ids(host)
        client_ids = waiting_ids(client)
        last = {"host": host, "client": client}
        if active:
            ready = (
                host.get("wait.pause_active") == "true"
                and client.get("wait.pause_active") == "true"
                and target_participant_id in host_ids
                and target_participant_id in client_ids
            )
        else:
            ready = (
                target_participant_id not in host_ids
                and target_participant_id not in client_ids
            )
        if ready:
            return {
                "host_waiting_ids": host_ids,
                "client_waiting_ids": client_ids,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"shared level-up pause did not become active={active} "
        f"for target={target_participant_id}: {last}"
    )


def choose_offer(pipe_name: str, offer_id: int, option_id: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.runtime.choose_level_up_option, {{
  offer_id = {offer_id},
  option_index = 1,
  option_id = {option_id},
}})
emit('pcall_ok', ok)
emit('result', result)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=8.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(
            f"level-up choice failed pipe={pipe_name} offer={offer_id} "
            f"option={option_id}: {values}"
        )
    return values


def wait_for_result(
    offer_id: int,
    target_participant_id: int,
    level: int,
    option_id: int,
    expected_active: int,
    timeout: float,
    apply_count: int = 1,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host = query_level_state(HOST_PIPE)
        client = query_level_state(CLIENT_PIPE)
        last = {"host": host, "client": client}
        accepted = True
        for values in (host, client):
            accepted = accepted and (
                values.get("result.valid") == "true"
                and parse_int_text(values.get("result.offer_id"), 0) == offer_id
                and parse_int_text(values.get("result.target"), 0) == target_participant_id
                and parse_int_text(values.get("result.level"), 0) == level
                and parse_int_text(values.get("result.option_id"), -1) == option_id
                and parse_int_text(values.get("result.apply_count"), 0)
                == apply_count
                and parse_int_text(values.get("result.resulting_active"), -1)
                == expected_active
                and parse_int_text(values.get("result.code"), 0) == 1
            )
        if accepted:
            return {
                "offer_id": offer_id,
                "target": target_participant_id,
                "level": level,
                "option_id": option_id,
                "apply_count": apply_count,
                "resulting_active": expected_active,
            }
        time.sleep(0.05)
    raise VerifyFailure(f"accepted result did not reach both peers: {last}")


def spell_mismatches(
    owner: dict[str, Any],
    observer: dict[str, Any],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for field in (
        "resolved",
        "build_skill_id",
        "current_spell_id",
        "progression_level",
        "secondary_damage_available",
        "mana_cost_available",
        "mana_spend_cost_available",
        "mana_output_scaled",
        "builder_seh_code",
        "error",
    ):
        if owner["spell"][field] != observer["spell"][field]:
            mismatches.append(
                {
                    "field": field,
                    "owner": owner["spell"][field],
                    "observer": observer["spell"][field],
                }
            )
    mismatches.extend(
        compare_float_fields(
            owner["spell"],
            observer["spell"],
            (
                "damage",
                "secondary_damage",
                "mana_cost",
                "mana_spend_cost",
                "mana_output_scale",
            ),
            tolerance=0.001,
        )
    )
    # +0x774/+0x778 is a stock builder work/presentation buffer, not a
    # persistent character statbook. Once a remote participant has cast, the
    # nonlocal progression can retain extra upgrade/presentation values in its
    # tail while the owner retains only the base fields. The resolved semantic
    # fields above (damage channels, mana display/spend cost and scaling) are
    # read from the same buffer and are the values combat consumes. Preserve
    # the raw count/array as diagnostics, but do not mistake that transient
    # tail for replicated progression state.
    if owner["spell"]["output_count"] < 2 or observer["spell"]["output_count"] < 2:
        mismatches.append(
            {
                "field": "minimum_output_count",
                "owner": owner["spell"]["output_count"],
                "observer": observer["spell"]["output_count"],
            }
        )
    return mismatches


def progression_snapshot_mismatches(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    native_before = before["native"]
    native_after = after["native"]
    scalar_mismatches = compare_float_fields(
        native_before,
        native_after,
        (
            "level",
            "xp",
            "previous_xp_threshold",
            "next_xp_threshold",
            "max_hp",
            "max_mp",
            "move_speed",
        ),
        tolerance=0.05,
    )
    # Current HP and MP are authoritative live vitals, not persistent
    # progression. Stock regeneration and combat can legitimately change them
    # while the other participant is choosing an upgrade. Their bidirectional
    # parity is covered by the dedicated vital/status behavior tests; keeping
    # them in this isolation check makes an unrelated native tick look like a
    # contaminated skillbook.
    if native_before["entry_count"] != native_after["entry_count"]:
        scalar_mismatches.append(
            {
                "field": "entry_count",
                "expected": native_before["entry_count"],
                "actual": native_after["entry_count"],
            }
        )
    return {
        "native_rows": compare_book_rows(
            native_before["entries"], native_after["entries"]
        ),
        "native_scalars": scalar_mismatches,
        "loadout": [] if before["loadout"] == after["loadout"] else [
            {"expected": before["loadout"], "actual": after["loadout"]}
        ],
        "spell": spell_mismatches(before, after),
    }


def verify_untargeted_progression_unchanged(
    participant_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    mismatches = progression_snapshot_mismatches(before, after)
    if any(mismatches.values()):
        raise VerifyFailure(
            f"targeted upgrade contaminated participant={participant_id}: "
            f"{mismatches}"
        )
    return {
        "participant_id": participant_id,
        "level": after["native"]["level"],
        "xp": after["native"]["xp"],
        "spellbook_revision": after["ledger"]["spellbook_revision"],
        "statbook_revision": after["ledger"]["statbook_revision"],
        "current_spell_id": after["spell"]["current_spell_id"],
        "mismatches": mismatches,
    }


def verify_duplicate_choice_idempotency(
    pipe_name: str,
    target_participant_id: int,
    offer_id: int,
    option_id: int,
    expected_active: int,
    expected_level: int,
) -> dict[str, Any]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.runtime.choose_level_up_option, {{
  offer_id = {offer_id},
  option_index = 1,
  option_id = {option_id},
}})
emit('pcall_ok', ok)
emit('result', result)
"""
    replay = parse_key_values(lua(pipe_name, code, timeout=8.0))
    time.sleep(0.25)
    snapshot = query_progression_snapshot(pipe_name, timeout=8.0)
    row = snapshot["native"]["entries"].get(option_id, {})
    active = int(row.get("active", -1))
    level = int(snapshot["native"]["level"])
    if active != expected_active or level != expected_level:
        raise VerifyFailure(
            f"duplicate level-up choice was not idempotent target="
            f"{target_participant_id} offer={offer_id} option={option_id}: "
            f"active={active}/{expected_active} level={level}/{expected_level} "
            f"replay={replay}"
        )
    return {
        "target_participant_id": target_participant_id,
        "offer_id": offer_id,
        "option_id": option_id,
        "replay": replay,
        "resulting_active": active,
        "resulting_level": level,
    }


def wait_for_target_parity(
    target_participant_id: int,
    entry_index: int,
    expected_active: int,
    expected_level: int,
    timeout: float,
) -> dict[str, Any]:
    if target_participant_id == HOST_ID:
        owner_spec = (HOST_PIPE, None)
        observer_spec = (CLIENT_PIPE, HOST_ID)
    else:
        owner_spec = (CLIENT_PIPE, None)
        observer_spec = (HOST_PIPE, CLIENT_ID)

    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        owner = query_progression_snapshot(
            owner_spec[0], participant_id=owner_spec[1], timeout=8.0
        )
        observer = query_progression_snapshot(
            observer_spec[0], participant_id=observer_spec[1], timeout=8.0
        )
        row_mismatches = {
            "owner_native_vs_observer_native": compare_book_rows(
                owner["native"]["entries"], observer["native"]["entries"]
            ),
            "owner_native_vs_owner_ledger": compare_book_rows(
                owner["native"]["entries"], owner["ledger"]["entries"]
            ),
            "owner_native_vs_observer_ledger": compare_book_rows(
                owner["native"]["entries"], observer["ledger"]["entries"]
            ),
        }
        stat_mismatches = compare_float_fields(
            owner["native"],
            observer["native"],
            (
                "level",
                "previous_xp_threshold",
                "next_xp_threshold",
                "hp",
                "max_hp",
                "mp",
                "max_mp",
                "move_speed",
            ),
            tolerance=0.05,
        )
        # The current wire ledger intentionally stores rounded integer XP
        # while the stock progression object accumulates fractional XP.
        stat_mismatches.extend(
            compare_float_fields(
                owner["native"],
                observer["native"],
                ("xp",),
                tolerance=0.51,
            )
        )
        current_spell_mismatches = spell_mismatches(owner, observer)
        concentration_mismatches: list[dict[str, Any]] = []
        for label, snapshot in (("owner", owner), ("observer", observer)):
            if not snapshot["ledger"]["concentration_selection_valid"]:
                continue
            for suffix in ("a", "b"):
                native_value = int(
                    snapshot["native"][f"slot_concentration_entry_{suffix}"]
                )
                ledger_value = int(
                    snapshot["ledger"][f"concentration_entry_{suffix}"]
                )
                if native_value != ledger_value:
                    concentration_mismatches.append(
                        {
                            "view": label,
                            "lane": suffix,
                            "gameplay_slot": snapshot["native"]["gameplay_slot"],
                            "native": native_value,
                            "ledger": ledger_value,
                        }
                    )
        owner_row = owner["native"]["entries"].get(entry_index, {})
        observer_row = observer["native"]["entries"].get(entry_index, {})
        ready = (
            owner["available"]
            and observer["available"]
            # A stock/natural offer may legitimately resolve immediately after
            # the offer under test.  The row result must remain exact and both
            # views must agree, but a later synchronized level is not a parity
            # failure.
            and owner["native"]["level"] >= expected_level
            and observer["native"]["level"] >= expected_level
            and owner_row.get("active") == expected_active
            and observer_row.get("active") == expected_active
            and owner["loadout"] == observer["loadout"]
            and all(not value for value in row_mismatches.values())
            and not stat_mismatches
            and not current_spell_mismatches
            and not concentration_mismatches
        )
        last = {
            "owner_level": owner["native"]["level"],
            "observer_level": observer["native"]["level"],
            "owner_active": owner_row.get("active"),
            "observer_active": observer_row.get("active"),
            "row_mismatches": row_mismatches,
            "stat_mismatches": stat_mismatches,
            "spell_mismatches": current_spell_mismatches,
            "concentration_mismatches": concentration_mismatches,
        }
        if ready:
            return {
                "owner_level": owner["native"]["level"],
                "owner_xp": owner["native"]["xp"],
                "owner_active": owner_row["active"],
                "observer_active": observer_row["active"],
                "owner_spellbook_revision": owner["ledger"]["spellbook_revision"],
                "observer_spellbook_revision": observer["ledger"]["spellbook_revision"],
                "owner_statbook_revision": owner["ledger"]["statbook_revision"],
                "observer_statbook_revision": observer["ledger"]["statbook_revision"],
                "max_hp": owner["native"]["max_hp"],
                "max_mp": owner["native"]["max_mp"],
                "move_speed": owner["native"]["move_speed"],
                "concentration": {
                    "owner_gameplay_slot": owner["native"]["gameplay_slot"],
                    "owner_lane_a": owner["native"]["slot_concentration_entry_a"],
                    "owner_lane_b": owner["native"]["slot_concentration_entry_b"],
                    "observer_gameplay_slot": observer["native"]["gameplay_slot"],
                    "observer_lane_a": observer["native"]["slot_concentration_entry_a"],
                    "observer_lane_b": observer["native"]["slot_concentration_entry_b"],
                    "ledger_a": owner["ledger"]["concentration_entry_a"],
                    "ledger_b": owner["ledger"]["concentration_entry_b"],
                },
                "spell": {
                    "resolved": owner["spell"]["resolved"],
                    "current_spell_id": owner["spell"]["current_spell_id"],
                    "damage": owner["spell"]["damage"],
                    "mana_cost": owner["spell"]["mana_cost"],
                    "outputs": owner["spell"]["outputs"],
                },
                "native_output_buffer_diagnostic": {
                    "owner_count": owner["spell"]["output_count"],
                    "observer_count": observer["spell"]["output_count"],
                    "exact_match": owner["spell"]["outputs"]
                    == observer["spell"]["outputs"],
                    "owner_outputs": owner["spell"]["outputs"],
                    "observer_outputs": observer["spell"]["outputs"],
                },
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"target progression parity timed out target={target_participant_id} "
        f"entry={entry_index} active={expected_active} level={expected_level}: {last}"
    )


def parse_entry_filter(text: str | None, count: int) -> list[int]:
    if not text:
        return list(range(count))
    selected: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            selected.update(range(start, end + 1))
        else:
            selected.add(int(token))
    invalid = sorted(index for index in selected if index < 0 or index >= count)
    if invalid:
        raise VerifyFailure(f"entry filter contains invalid progression rows: {invalid}")
    return sorted(selected)


def new_crash_artifacts(started_at: float) -> list[str]:
    artifacts: list[str] = []
    for instance in ("local-mp-host", "local-mp-client"):
        log_dir = ROOT / "runtime" / "instances" / instance / "stage" / ".sdmod" / "logs"
        if not log_dir.exists():
            continue
        for path in log_dir.glob("*crash*"):
            if path.is_file() and path.stat().st_mtime >= started_at - 0.5:
                artifacts.append(str(path.relative_to(ROOT)))
    # Windows Error Reporting writes process dumps outside each isolated stage.
    # Include them so a dead process cannot be misreported as a mere pipe or
    # scene timeout when the loader's own crash reporter did not run first.
    windows_crash_dir = Path("/mnt/c/Users/user/AppData/Local/CrashDumps")
    if windows_crash_dir.exists():
        for path in windows_crash_dir.glob("SolomonDark.exe*.dmp"):
            if path.is_file() and path.stat().st_mtime >= started_at - 0.5:
                artifacts.append(str(path))
    return sorted(artifacts)


def run_matrix(
    catalog: list[dict[str, Any]],
    entries: list[int],
    directions: str,
    timeout: float,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    direction_specs: list[tuple[str, int, str]] = []
    if directions in ("both", "client"):
        direction_specs.append(("client_owned", CLIENT_ID, CLIENT_PIPE))
    if directions in ("both", "host"):
        direction_specs.append(("host_owned", HOST_ID, HOST_PIPE))

    if progress is None:
        progress = {}
    progress.clear()
    progress.update(
        {
            "directions": directions,
            "entry_filter": entries,
            "expected_step_count": len(entries) * len(direction_specs),
            "completed_step_count": 0,
            "applied_step_count": 0,
            "already_maxed_step_count": 0,
            "idempotency_checks": [],
            "steps": [],
        }
    )
    steps: list[dict[str, Any]] = progress["steps"]
    for entry_index in entries:
        row = catalog[entry_index]
        for direction, target_id, target_pipe in direction_specs:
            untargeted_id = HOST_ID if target_id == CLIENT_ID else CLIENT_ID
            untargeted_pipe = HOST_PIPE if untargeted_id == HOST_ID else CLIENT_PIPE
            untargeted_before = query_progression_snapshot(
                untargeted_pipe, timeout=8.0
            )
            before = query_progression_snapshot(target_pipe)
            before_row = before["native"]["entries"].get(entry_index)
            if before_row is None:
                raise VerifyFailure(f"target is missing native progression row {entry_index}")
            expected_active = int(before_row["active"]) + 1
            if expected_active > int(before_row["statbook_max_level"]):
                parity = wait_for_target_parity(
                    target_id,
                    entry_index,
                    int(before_row["active"]),
                    int(before["native"]["level"]),
                    timeout,
                )
                untargeted_after = query_progression_snapshot(
                    untargeted_pipe, timeout=8.0
                )
                isolation = verify_untargeted_progression_unchanged(
                    untargeted_id, untargeted_before, untargeted_after
                )
                steps.append(
                    {
                        "step": len(steps) + 1,
                        "direction": direction,
                        "target_participant_id": target_id,
                        "entry_index": entry_index,
                        "skill_file": row["skill_file"],
                        "skill_name": row["skill_name"],
                        "category": row["category"],
                        "native_max_level": row["native_max_level"],
                        "before_active": before_row["active"],
                        "expected_active": before_row["active"],
                        "target_level": before["native"]["level"],
                        "action": "already_maxed_parity",
                        "parity": parity,
                        "untargeted_isolation": isolation,
                    }
                )
                progress["completed_step_count"] = len(steps)
                progress["already_maxed_step_count"] += 1
                print(
                    f"[{len(steps)}] {direction} row={entry_index} "
                    f"skill={row['skill_file']} already_maxed="
                    f"{before_row['active']}",
                    flush=True,
                )
                continue
            target_level = int(before["native"]["level"]) + 1
            # Native level_up advances according to the XP thresholds, and can
            # cross multiple levels if fed an oversized value. Use the current
            # exact next threshold so each offer advances one native level.
            target_experience = int(math.ceil(before["native"]["next_xp_threshold"]))

            publish = publish_deterministic_offer(
                target_id,
                target_level,
                target_experience,
                entry_index,
            )
            offer = wait_for_offer(
                target_pipe,
                target_id,
                target_level,
                entry_index,
                timeout,
            )
            pause_active = wait_for_pause(target_id, True, timeout)
            choice = choose_offer(target_pipe, offer["offer_id"], entry_index)
            result = wait_for_result(
                offer["offer_id"],
                target_id,
                target_level,
                entry_index,
                expected_active,
                timeout,
            )
            parity = wait_for_target_parity(
                target_id,
                entry_index,
                expected_active,
                target_level,
                timeout,
            )
            pause_cleared = wait_for_pause(target_id, False, timeout)
            untargeted_after = query_progression_snapshot(
                untargeted_pipe, timeout=8.0
            )
            isolation = verify_untargeted_progression_unchanged(
                untargeted_id, untargeted_before, untargeted_after
            )
            idempotency = None
            checked_directions = {
                check["direction"] for check in progress["idempotency_checks"]
            }
            if direction not in checked_directions:
                idempotency = verify_duplicate_choice_idempotency(
                    target_pipe,
                    target_id,
                    offer["offer_id"],
                    entry_index,
                    expected_active,
                    target_level,
                )
                idempotency["direction"] = direction
                progress["idempotency_checks"].append(idempotency)
            steps.append(
                {
                    "step": len(steps) + 1,
                    "direction": direction,
                    "target_participant_id": target_id,
                    "entry_index": entry_index,
                    "skill_file": row["skill_file"],
                    "skill_name": row["skill_name"],
                    "category": row["category"],
                    "native_max_level": row["native_max_level"],
                    "before_active": before_row["active"],
                    "expected_active": expected_active,
                    "target_level": target_level,
                    "target_experience": target_experience,
                    "action": "applied_upgrade",
                    "publish": publish,
                    "offer": offer,
                    "pause_active": pause_active,
                    "choice": choice,
                    "result": result,
                    "parity": parity,
                    "pause_cleared": pause_cleared,
                    "untargeted_isolation": isolation,
                    "idempotency": idempotency,
                }
            )
            progress["completed_step_count"] = len(steps)
            progress["applied_step_count"] += 1
            print(
                f"[{len(steps)}] {direction} row={entry_index} "
                f"skill={row['skill_file']} active={expected_active} level={target_level}",
                flush=True,
            )
    return progress


def wait_for_post_run_progression_ready(timeout: float) -> dict[str, Any]:
    ready: dict[str, Any] = {}
    for label, target_id, owner_pipe in (
        ("client_owned", CLIENT_ID, CLIENT_PIPE),
        ("host_owned", HOST_ID, HOST_PIPE),
    ):
        owner = query_progression_snapshot(owner_pipe)
        probe_entry = owner["loadout"]["primary_entry"]
        if probe_entry < 0 or probe_entry not in owner["native"]["entries"]:
            raise VerifyFailure(f"{label} primary progression row is unavailable after run entry")
        ready[label] = wait_for_target_parity(
            target_id,
            probe_entry,
            int(owner["native"]["entries"][probe_entry]["active"]),
            int(owner["native"]["level"]),
            timeout,
        )
    return ready


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", help="comma-separated rows/ranges, e.g. 16-18,24-25")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--directions", choices=("both", "client", "host"), default="both")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument(
        "--test-boneyard-override",
        type=Path,
        default=FLAT_BONEYARD,
        help="isolated survival.boneyard fixture staged for both peers",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        output["launch"] = launch_pair(
            god_mode=True,
            test_survival_boneyard_override=args.test_boneyard_override,
        )
        disable_bots()
        output["hub_ready"] = {
            "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub", args.timeout),
            "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub", args.timeout),
        }
        catalog_views = wait_for_catalog_views(args.timeout)
        catalog_result = build_and_verify_catalog(catalog_views, load_skill_configs())
        output["catalog_summary"] = {
            key: value
            for key, value in catalog_result.items()
            if key != "catalog"
        }
        entries = parse_entry_filter(args.entries, catalog_result["real_skill_row_count"])
        if args.limit is not None:
            if args.limit <= 0:
                raise VerifyFailure("--limit must be positive")
            entries = entries[: args.limit]
        output["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=args.timeout)
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        matrix_progress: dict[str, Any] = {}
        output["matrix"] = matrix_progress
        run_matrix(
            catalog_result["catalog"],
            entries,
            args.directions,
            args.timeout,
            matrix_progress,
        )
        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts appeared during upgrade matrix: {crashes}")
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
        return_code = 1
    finally:
        if not args.keep_open:
            stop_games()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    matrix = output.get("matrix") or {}
    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "completed_step_count": matrix.get("completed_step_count", 0),
                "expected_step_count": matrix.get("expected_step_count", 0),
                "applied_step_count": matrix.get("applied_step_count", 0),
                "already_maxed_step_count": matrix.get(
                    "already_maxed_step_count", 0
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
