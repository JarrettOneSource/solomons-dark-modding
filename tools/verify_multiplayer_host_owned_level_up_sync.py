#!/usr/bin/env python3
"""Verify a host-owned level-up choice reaches every native participant view."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

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
from verify_multiplayer_level_up_offer_sync import (
    capture,
    choose_client_option,
    participant_row,
    query_progression_entry,
    query_progression_stats,
    wait_for_choice_result,
    wait_for_pair_ready,
    wait_for_wait_status,
)
from multiplayer_progression_probe import (
    compare_book_rows,
    compare_float_fields,
    query_progression_snapshot,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime" / "multiplayer_host_owned_level_up_sync.json"
HOST_LIVE_STAT_OPTION_ID = 67  # Rush; exercises transient movement-speed parity.


def _without_raw(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key != "raw"}


def wait_for_bidirectional_progression_parity(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host_local = query_progression_snapshot(HOST_PIPE)
        client_remote_host = query_progression_snapshot(
            CLIENT_PIPE,
            participant_id=HOST_ID,
        )
        client_local = query_progression_snapshot(CLIENT_PIPE)
        host_remote_client = query_progression_snapshot(
            HOST_PIPE,
            participant_id=CLIENT_ID,
        )
        views = {
            "host": (host_local, client_remote_host),
            "client": (client_local, host_remote_client),
        }
        mismatches: dict[str, Any] = {}
        for label, (owner, observer) in views.items():
            owner_native = owner["native"]["entries"]
            observer_native = observer["native"]["entries"]
            owner_ledger = owner["ledger"]["entries"]
            observer_ledger = observer["ledger"]["entries"]
            row_mismatches = {
                "owner_native_vs_observer_native": compare_book_rows(
                    owner_native,
                    observer_native,
                ),
                "owner_native_vs_owner_ledger": compare_book_rows(
                    owner_native,
                    owner_ledger,
                ),
                "owner_native_vs_observer_ledger": compare_book_rows(
                    owner_native,
                    observer_ledger,
                ),
            }
            stat_mismatches = compare_float_fields(
                owner["native"],
                observer["native"],
                (
                    "level",
                    "xp",
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
            spell_mismatches: list[dict[str, Any]] = []
            for field in (
                "resolved",
                "build_skill_id",
                "current_spell_id",
                "progression_level",
                "output_count",
                "secondary_damage_available",
                "mana_cost_available",
                "mana_spend_cost_available",
                "mana_output_scaled",
                "builder_seh_code",
            ):
                if owner["spell"][field] != observer["spell"][field]:
                    spell_mismatches.append(
                        {
                            "field": field,
                            "owner": owner["spell"][field],
                            "observer": observer["spell"][field],
                        }
                    )
            spell_mismatches.extend(
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
            if owner["spell"]["outputs"] != observer["spell"]["outputs"]:
                spell_mismatches.append(
                    {
                        "field": "outputs",
                        "owner": owner["spell"]["outputs"],
                        "observer": observer["spell"]["outputs"],
                    }
                )
            mismatches[label] = {
                "rows": row_mismatches,
                "stats": stat_mismatches,
                "spell": spell_mismatches,
            }

        last = {
            "views": {
                "host_local": _without_raw(host_local),
                "client_remote_host": _without_raw(client_remote_host),
                "client_local": _without_raw(client_local),
                "host_remote_client": _without_raw(host_remote_client),
            },
            "mismatches": mismatches,
        }
        if all(
            not detail["stats"]
            and not detail["spell"]
            and all(not rows for rows in detail["rows"].values())
            for detail in mismatches.values()
        ):
            return last
        time.sleep(0.25)
    raise VerifyFailure(f"bidirectional native progression parity timed out: {last}")


def publish_host_self_offer(
    level: int,
    experience: int,
    option_id: int | None = None,
) -> dict[str, str]:
    deterministic_fields = (
        f"option_id = {option_id},\n  apply_count = 1,"
        if option_id is not None
        else ""
    )
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.runtime.debug_publish_level_up_offer, {{
  level = {level},
  experience = {experience},
  target_self = true,
  {deterministic_fields}
}})
emit('pcall_ok', ok)
emit('result', result)
"""
    values = parse_key_values(lua(HOST_PIPE, code, timeout=5.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(f"host failed to publish a self level-up offer: {values}")
    return values


def wait_for_host_offer(
    level: int,
    timeout: float,
    expected_option_id: int | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        option_count = parse_int_text(last.get("offer.option_count"), 0)
        if (
            last.get("offer.valid") == "true"
            and parse_int_text(last.get("offer.authority"), 0) == HOST_ID
            and parse_int_text(last.get("offer.target"), 0) == HOST_ID
            and parse_int_text(last.get("offer.level"), 0) == level
            and option_count > 0
            and (
                expected_option_id is None
                or (
                    option_count == 1
                    and parse_int_text(last.get("offer.option.1.id"), -1)
                        == expected_option_id
                )
            )
        ):
            return {
                "offer_id": parse_int_text(last.get("offer.id"), 0),
                "level": level,
                "experience": parse_int_text(last.get("offer.experience"), 0),
                "option_count": option_count,
                "option_ids": [
                    parse_int_text(last.get(f"offer.option.{index}.id"), -1)
                    for index in range(1, option_count + 1)
                ],
                "apply_counts": [
                    parse_int_text(last.get(f"offer.option.{index}.apply_count"), 1)
                    for index in range(1, option_count + 1)
                ],
                "raw": last,
            }
        time.sleep(0.1)
    raise VerifyFailure(f"host-self level-up offer did not become active: {last}")


def choose_host_option(offer_id: int, option_index: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.runtime.choose_level_up_option, {{
  offer_id = {offer_id},
  option_index = {option_index},
}})
emit('pcall_ok', ok)
emit('result', result)
"""
    values = parse_key_values(lua(HOST_PIPE, code, timeout=5.0))
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(f"host failed to resolve its own level-up choice: {values}")
    return values


def wait_for_broadcast_result(offer_id: int, level: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        if (
            parse_int_text(last_host.get("result.offer_id"), 0) == offer_id
            and parse_int_text(last_client.get("result.offer_id"), 0) == offer_id
            and parse_int_text(last_host.get("result.target"), 0) == HOST_ID
            and parse_int_text(last_client.get("result.target"), 0) == HOST_ID
            and parse_int_text(last_host.get("result.code"), 0) == 1
            and parse_int_text(last_client.get("result.code"), 0) == 1
            and parse_int_text(last_client.get("result.level"), 0) == level
            and last_host.get("offer.valid") == "false"
        ):
            return {
                "host": last_host,
                "client": last_client,
                "option_id": parse_int_text(last_client.get("result.option_id"), -1),
                "apply_count": parse_int_text(last_client.get("result.apply_count"), 0),
                "client_remote_host": participant_row(last_client, HOST_ID),
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "host-owned accepted result did not reach both peers: "
        f"host={last_host} client={last_client}"
    )


def wait_for_host_progression_views(timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    host_stats: dict[str, Any] = {}
    client_remote_host_stats: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host_stats = query_progression_stats(HOST_PIPE)
        client_remote_host_stats = query_progression_stats(
            CLIENT_PIPE,
            participant_id=HOST_ID,
        )
        if host_stats["available"] and client_remote_host_stats["available"]:
            return host_stats, client_remote_host_stats
        time.sleep(0.2)
    raise VerifyFailure(
        "host progression is unavailable on one participant view: "
        f"host={host_stats} client_remote={client_remote_host_stats}"
    )


def corrupt_remote_progression_entry(
    pipe_name: str,
    participant_id: int,
    entry_index: int,
    active: int,
    visible: int,
) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local participant = sd.bots.get_participant_state({participant_id})
local progression = tonumber(participant and participant.progression_runtime_state_address) or 0
local table_address = progression ~= 0 and sd.debug.read_u32(
  progression + sd.debug.layout_offset('standalone_wizard_progression_table_base')) or 0
local stride = sd.debug.layout_offset('standalone_wizard_progression_entry_stride')
local entry = table_address ~= 0 and table_address + ({entry_index} * stride) or 0
local active_address = entry ~= 0 and entry + sd.debug.layout_offset(
  'standalone_wizard_progression_active_flag') or 0
local visible_address = entry ~= 0 and entry + sd.debug.layout_offset(
  'standalone_wizard_progression_visible_flag') or 0
emit('progression', progression)
emit('entry', entry)
emit('active.before', active_address ~= 0 and sd.debug.read_u16(active_address) or -1)
emit('visible.before', visible_address ~= 0 and sd.debug.read_u16(visible_address) or -1)
emit('active.write', active_address ~= 0 and sd.debug.write_u16(active_address, {active}) or false)
emit('visible.write', visible_address ~= 0 and sd.debug.write_u16(visible_address, {visible}) or false)
emit('active.after', active_address ~= 0 and sd.debug.read_u16(active_address) or -1)
emit('visible.after', visible_address ~= 0 and sd.debug.read_u16(visible_address) or -1)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=5.0))
    if (
        values.get("active.write") != "true"
        or values.get("visible.write") != "true"
        or parse_int_text(values.get("active.after"), -1) != active
        or parse_int_text(values.get("visible.after"), -1) != visible
    ):
        raise VerifyFailure(
            f"failed to corrupt remote progression entry for recovery proof: {values}"
        )
    return values


def verify(timeout: float) -> dict[str, Any]:
    ready = wait_for_pair_ready(timeout)
    baseline_parity = wait_for_bidirectional_progression_parity(timeout)
    host_stats, client_remote_host_stats = wait_for_host_progression_views(timeout)

    target_level = max(host_stats["level"], client_remote_host_stats["level"]) + 1
    target_experience = int(
        max(
            host_stats["next_xp_threshold"],
            client_remote_host_stats["next_xp_threshold"],
            125.0,
        )
        + 10.0
    )
    publish = publish_host_self_offer(
        target_level,
        target_experience,
        option_id=HOST_LIVE_STAT_OPTION_ID,
    )
    offer = wait_for_host_offer(
        target_level,
        timeout,
        expected_option_id=HOST_LIVE_STAT_OPTION_ID,
    )
    wait_active = wait_for_wait_status(
        participant_id=HOST_ID,
        pause_active=True,
        timeout=timeout,
    )

    option_index = 1
    option_id = offer["option_ids"][0]
    apply_count = offer["apply_counts"][0]
    before = {
        "host_local": query_progression_entry(HOST_PIPE, option_id=option_id),
        "client_remote_host": query_progression_entry(
            CLIENT_PIPE,
            option_id=option_id,
            participant_id=HOST_ID,
        ),
    }
    choice = choose_host_option(offer["offer_id"], option_index)
    result = wait_for_broadcast_result(offer["offer_id"], target_level, timeout)
    client_offer_raw = capture(CLIENT_PIPE)
    client_offer_resolution: dict[str, Any] | None = None
    if (
        client_offer_raw.get("offer.valid") == "true"
        and parse_int_text(client_offer_raw.get("offer.target"), 0) == CLIENT_ID
    ):
        client_offer_id = parse_int_text(client_offer_raw.get("offer.id"), 0)
        client_offer_resolution = {
            "offer_id": client_offer_id,
            "option_id": parse_int_text(client_offer_raw.get("offer.option.1.id"), -1),
            "choice": choose_client_option(client_offer_id, 1),
            "result": wait_for_choice_result(client_offer_id, target_level, timeout),
        }
    wait_cleared = wait_for_wait_status(
        participant_id=HOST_ID,
        pause_active=False,
        timeout=timeout,
    )
    after = {
        "host_local": query_progression_entry(HOST_PIPE, option_id=option_id),
        "client_remote_host": query_progression_entry(
            CLIENT_PIPE,
            option_id=option_id,
            participant_id=HOST_ID,
        ),
    }
    post_choice_parity = wait_for_bidirectional_progression_parity(timeout)

    host_expected_entry = post_choice_parity["views"]["host_local"]["native"][
        "entries"
    ][option_id]
    client_option_id = (
        client_offer_resolution["option_id"]
        if client_offer_resolution is not None
        else -1
    )
    client_expected_entry = (
        post_choice_parity["views"]["client_local"]["native"]["entries"].get(
            client_option_id
        )
        if client_option_id >= 0
        else None
    )
    recovery_mutations = {
        "client_remote_host": corrupt_remote_progression_entry(
            CLIENT_PIPE,
            HOST_ID,
            option_id,
            max(0, host_expected_entry["active"] - apply_count),
            1 if host_expected_entry["active"] - apply_count > 0 else 0,
        )
    }
    if client_expected_entry is not None:
        recovery_mutations["host_remote_client"] = corrupt_remote_progression_entry(
            HOST_PIPE,
            CLIENT_ID,
            client_option_id,
            max(0, client_expected_entry["active"] - 1),
            1 if client_expected_entry["active"] - 1 > 0 else 0,
        )
    recovered_snapshot_parity = wait_for_bidirectional_progression_parity(timeout)

    expected_active = before["host_local"]["active"] + apply_count
    if after["host_local"]["active"] != expected_active:
        raise VerifyFailure(
            f"host local progression active count did not advance exactly: before={before} after={after}"
        )
    if after["client_remote_host"]["active"] != after["host_local"]["active"]:
        raise VerifyFailure(
            f"client native host clone did not receive the host-owned choice: before={before} after={after}"
        )
    if result["option_id"] != option_id or result["apply_count"] != apply_count:
        raise VerifyFailure(f"broadcast result option payload mismatch: offer={offer} result={result}")
    if result["client_remote_host"] is None or result["client_remote_host"]["level"] < target_level:
        raise VerifyFailure(f"client did not retain the host target level: {result}")

    return {
        "ready": ready,
        "baseline_parity": baseline_parity,
        "stats_before": {
            "host_local": host_stats,
            "client_remote_host": client_remote_host_stats,
        },
        "target_level": target_level,
        "target_experience": target_experience,
        "publish": publish,
        "offer": offer,
        "wait_active": {
            "host_count": parse_int_text(wait_active["host"].get("wait.waiting_count"), 0),
            "client_count": parse_int_text(wait_active["client"].get("wait.waiting_count"), 0),
        },
        "choice": choice,
        "result": result,
        "client_offer_resolution": client_offer_resolution,
        "wait_cleared": {
            "host_count": parse_int_text(wait_cleared["host"].get("wait.waiting_count"), 0),
            "client_count": parse_int_text(wait_cleared["client"].get("wait.waiting_count"), 0),
        },
        "selected_entry": {"before": before, "after": after},
        "post_choice_parity": post_choice_parity,
        "snapshot_recovery": {
            "mutations": recovery_mutations,
            "recovered_parity": recovered_snapshot_parity,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    output: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        output["launch"] = launch_pair()
        disable_bots()
        output["hub_ready"] = {
            "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
            "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
        }
        output["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=args.timeout)
        output["verification"] = verify(args.timeout)
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired) as exc:
        output["error"] = str(exc)
        return_code = 1
    finally:
        if not args.keep_open:
            stop_games()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verification = output.get("verification") or {}
    selected_entry = verification.get("selected_entry") or {}
    snapshot_recovery = verification.get("snapshot_recovery") or {}
    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "summary": {
                    "target_level": verification.get("target_level"),
                    "target_experience": verification.get("target_experience"),
                    "host_offer_id": (verification.get("offer") or {}).get("offer_id"),
                    "host_option_id": (verification.get("result") or {}).get("option_id"),
                    "client_offer_id": (verification.get("client_offer_resolution") or {}).get("offer_id"),
                    "client_option_id": (verification.get("client_offer_resolution") or {}).get("option_id"),
                    "wait_active": verification.get("wait_active"),
                    "wait_cleared": verification.get("wait_cleared"),
                    "selected_entry_before": selected_entry.get("before"),
                    "selected_entry_after": selected_entry.get("after"),
                    "baseline_mismatches": (verification.get("baseline_parity") or {}).get("mismatches"),
                    "post_choice_mismatches": (verification.get("post_choice_parity") or {}).get("mismatches"),
                    "recovery_mutations": snapshot_recovery.get("mutations"),
                    "recovered_mismatches": (snapshot_recovery.get("recovered_parity") or {}).get("mismatches"),
                },
                "output": str(OUTPUT),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
