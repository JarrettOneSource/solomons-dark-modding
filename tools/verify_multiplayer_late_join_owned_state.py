#!/usr/bin/env python3
"""Verify late-join and same-identity reconnect bootstrap of participant-owned state."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from multiplayer_progression_probe import query_progression_snapshot
from multiplayer_transient_status_harness import (
    TRANSIENT_POISONED,
    TRANSIENT_SNAPSHOT_VALID,
    inject_native_poison_status,
    wait_for_poison_state,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_PIPE,
    THIRD_ID,
    THIRD_PIPE,
    ROOT,
    VerifyFailure,
    _kill_lua_daemon,
    complete_native_create,
    launch_additional_client,
    parse_int_text,
    place_player,
    stop_games,
    wait_for_scene,
)
from verify_multiplayer_inventory_audit import (
    capture as capture_inventory,
    find_participant,
)
from verify_multiplayer_late_join_upgrade_catchup import apply_pair_chaining
from verify_multiplayer_lightning_chaining_effect_sync import (
    CHAINING_OPTION_ID,
    FLAT_BONEYARD,
    launch_pair_ready,
)
from verify_multiplayer_native_item_inventory_sync import (
    HAT_HELPER_TYPE_ID,
    capture_equipment,
    normalized_hex_bytes,
    run as verify_native_item,
)
from verify_multiplayer_native_potion_inventory_sync import find_local_participant
from verify_multiplayer_primary_kill_stress import wait_for_remote_position_convergence
from verify_multiplayer_progression_ledger_sync import (
    set_gold,
    wait_for_participant_gold,
)
from verify_multiplayer_third_observer_upgrade_sync import (
    CLIENT,
    PARTICIPANTS,
    wait_for_all_relationships,
    wait_for_owner_parity,
)
from verify_player_health_death_sync import (
    query_local_player_vitals,
    query_remote_participant,
    set_local_player_vitals,
)
from verify_real_input_spell_cast_sync import detect_instance_pids


OUTPUT = ROOT / "runtime" / "multiplayer_late_join_owned_state_current.json"
CLIENT_GOLD = 4321
CLIENT_HP = 37.0
CLIENT_MAX_HP = 50.0
CLIENT_MP = 61.0
CLIENT_MAX_MP = 100.0
CLIENT_POSITION = (1150.0, 1750.0)
FIRST_THIRD_POSITION = (700.0, 2450.0)
RECONNECTED_THIRD_POSITION = (1450.0, 2450.0)
POSITION_TOLERANCE = 3.0
VITAL_TOLERANCE = 0.25


def inventory_identity(row: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(row["type_id"]),
        int(row["recipe_uid"]),
        int(row["slot"]),
        int(row["stack_count"]),
    )


def compact_inventory(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "gold": row["gold"],
        "gold_revision": row["gold_revision"],
        "inventory_revision": row["inventory_revision"],
        "inventory_host_authoritative": row["inventory_host_authoritative"],
        "inventory_item_total_count": row["inventory_item_total_count"],
        "inventory_items": sorted(inventory_identity(item) for item in row["inventory_items"]),
    }


def require_close(label: str, actual: float, expected: float, tolerance: float) -> None:
    if not math.isfinite(actual) or not math.isclose(
        actual, expected, rel_tol=0.0, abs_tol=tolerance
    ):
        raise VerifyFailure(
            f"{label} mismatch: actual={actual!r} expected={expected!r} "
            f"tolerance={tolerance}"
        )


def equipment_bootstrap(
    *,
    recipe_uid: int,
    expected_color: str,
) -> dict[str, Any]:
    capture = capture_equipment(THIRD_PIPE, HAT_HELPER_TYPE_ID)
    expected_color = normalized_hex_bytes(expected_color)
    identity_fields = {
        "runtime.type_id": HAT_HELPER_TYPE_ID,
        "runtime.recipe_uid": recipe_uid,
        "bot.type_id": HAT_HELPER_TYPE_ID,
        "bot.recipe_uid": recipe_uid,
    }
    for key, expected in identity_fields.items():
        actual = parse_int_text(capture.get(key), 0)
        if actual != expected:
            raise VerifyFailure(
                f"late observer equipment identity mismatch {key}: "
                f"actual={actual} expected={expected} capture={capture}"
            )
    if capture.get("runtime.valid") != "true" or capture.get("bot.valid") != "true":
        raise VerifyFailure(f"late observer equipment was not materialized: {capture}")
    if expected_color:
        for key in ("runtime.color", "bot.color"):
            if normalized_hex_bytes(capture.get(key)) != expected_color:
                raise VerifyFailure(
                    f"late observer wearable color mismatch {key}: "
                    f"expected={expected_color} capture={capture}"
                )
        if capture.get("bot.color_valid") != "true":
            raise VerifyFailure(f"late observer native wearable color is invalid: {capture}")
    return capture


def inventory_bootstrap() -> dict[str, Any]:
    owner_capture = capture_inventory(CLIENT_PIPE)
    observer_capture = capture_inventory(THIRD_PIPE)
    owner = find_local_participant(owner_capture)
    observer = find_participant(observer_capture, CLIENT_ID)
    if owner is None or observer is None:
        raise VerifyFailure(
            f"client inventory bootstrap row missing: owner={owner} observer={observer}"
        )
    if observer["id"] != CLIENT_ID:
        raise VerifyFailure(f"late observer resolved the wrong inventory owner: {observer}")
    owner_compact = compact_inventory(owner)
    observer_compact = compact_inventory(observer)
    if owner_compact != observer_compact:
        raise VerifyFailure(
            f"late observer inventory/gold differs from owner: "
            f"owner={owner_compact} observer={observer_compact}"
        )
    if owner_compact["gold"] != CLIENT_GOLD:
        raise VerifyFailure(f"mutated owner gold was lost: {owner_compact}")
    if owner_compact["gold_revision"] <= 0 or owner_compact["inventory_revision"] <= 0:
        raise VerifyFailure(f"owned-state revisions are not initialized: {owner_compact}")
    return {
        "owner": owner_compact,
        "observer": observer_compact,
    }


def vitals_and_status_bootstrap() -> dict[str, Any]:
    owner = query_local_player_vitals(CLIENT_PIPE)
    remote = query_remote_participant(THIRD_PIPE, CLIENT_ID)
    if remote.get("available") != "true" or remote.get("materialized") != "true":
        raise VerifyFailure(f"late observer client actor unavailable: {remote}")
    expected = {
        "hp": float(owner.get("hp", "nan")),
        "max_hp": float(owner.get("max_hp", "nan")),
        "mp": float(owner.get("mp", "nan")),
        "max_mp": float(owner.get("max_mp", "nan")),
        "runtime.life_current": float(owner.get("hp", "nan")),
        "runtime.life_max": float(owner.get("max_hp", "nan")),
        "runtime.mana_current": float(owner.get("mp", "nan")),
        "runtime.mana_max": float(owner.get("max_mp", "nan")),
    }
    for key, value in expected.items():
        require_close(key, float(remote.get(key, "nan")), value, VITAL_TOLERANCE)
    require_close("x", float(remote.get("x", "nan")), CLIENT_POSITION[0], POSITION_TOLERANCE)
    require_close("y", float(remote.get("y", "nan")), CLIENT_POSITION[1], POSITION_TOLERANCE)

    poison = wait_for_poison_state(
        THIRD_PIPE,
        participant_id=CLIENT_ID,
        poisoned=True,
        timeout=15.0,
    )
    expected_flags = TRANSIENT_SNAPSHOT_VALID | TRANSIENT_POISONED
    for key in ("runtime_flags", "replicated_flags", "native_flags"):
        if poison[key] != expected_flags:
            raise VerifyFailure(
                f"late observer poison flags mismatch {key}: "
                f"expected={expected_flags:#x} poison={poison}"
            )
    return {"owner_vitals": owner, "observer_vitals": remote, "poison": poison}


def progression_bootstrap(timeout: float) -> dict[str, Any]:
    owner = query_progression_snapshot(CLIENT_PIPE)
    row = owner["native"]["entries"].get(CHAINING_OPTION_ID)
    if row is None:
        raise VerifyFailure(f"client Chaining row disappeared: {owner}")
    active = int(row["active"])
    level = int(owner["native"]["level"])
    if active <= 0:
        raise VerifyFailure(f"client Chaining upgrade is not active: {row}")
    return wait_for_owner_parity(CLIENT, CHAINING_OPTION_ID, active, level, timeout)


def verify_bootstrap(
    label: str,
    *,
    recipe_uid: int,
    expected_color: str,
    timeout: float,
) -> dict[str, Any]:
    return {
        "label": label,
        "relationships": wait_for_all_relationships("testrun", timeout),
        "inventory_and_gold": inventory_bootstrap(),
        "equipment": equipment_bootstrap(
            recipe_uid=recipe_uid,
            expected_color=expected_color,
        ),
        "vitals_and_status": vitals_and_status_bootstrap(),
        "progression": progression_bootstrap(timeout),
    }


def stop_third_process(pid: int, timeout: float) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"Stop-Process -Id {pid} -Force -ErrorAction Stop",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    _kill_lua_daemon(THIRD_PIPE)
    if completed.returncode != 0:
        raise VerifyFailure(f"failed to stop third process {pid}: {completed.stdout}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = detect_instance_pids()
        if pids.get("third") != pid:
            return {"pid": pid, "stopped": True, "remaining": pids}
        time.sleep(0.1)
    raise VerifyFailure(f"third process {pid} did not exit")


def launch_third(timeout: float) -> dict[str, Any]:
    launch = launch_additional_client(
        preset="create_manual",
        god_mode=True,
        test_survival_boneyard_override=FLAT_BONEYARD,
        test_blank_boneyard=True,
    )
    create = complete_native_create(
        THIRD_PIPE,
        element="fire",
        discipline="mind",
        timeout=timeout,
    )
    wait_for_scene(THIRD_PIPE, "testrun", timeout)
    return {"launch": launch, "create": create}


def place_and_require_third_visible(
    position: tuple[float, float],
    timeout: float,
) -> dict[str, Any]:
    placement = place_player(THIRD_PIPE, position[0], position[1], 90.0)
    return {
        "placement": placement,
        "host": wait_for_remote_position_convergence(
            HOST_PIPE, THIRD_ID, position[0], position[1], timeout
        ),
        "client": wait_for_remote_position_convergence(
            CLIENT_PIPE, THIRD_ID, position[0], position[1], timeout
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    output: dict[str, Any] = {"ok": False}
    try:
        startup = launch_pair_ready(min(args.timeout, 45.0))
        output["pair_startup"] = {
            "attempt": startup["attempt"],
            "hub_ready": startup["hub_ready"],
            "run_ready": startup["run_ready"],
        }

        item = verify_native_item(
            SimpleNamespace(
                no_launch=True,
                attempts=1,
                timeout=min(args.timeout, 30.0),
                item_type=HAT_HELPER_TYPE_ID,
            )
        )
        output["pre_join_item"] = item
        recipe_uid = int(item["recipe"]["uid"])
        expected_color = item["accepted_result"].get("item_color_state", "")

        client_before = find_participant(capture_inventory(HOST_PIPE), CLIENT_ID)
        if client_before is None:
            raise VerifyFailure("host lost client ledger before owned-state mutation")
        output["gold_write"] = set_gold(CLIENT_PIPE, CLIENT_GOLD)
        output["gold_replication"] = wait_for_participant_gold(
            HOST_PIPE,
            CLIENT_ID,
            CLIENT_GOLD,
            min_revision=int(client_before["gold_revision"]),
            timeout=args.timeout,
        )
        output["pre_join_chaining"] = apply_pair_chaining(CLIENT, args.timeout)
        output["vitals_write"] = set_local_player_vitals(
            CLIENT_PIPE,
            CLIENT_HP,
            CLIENT_MAX_HP,
            mp=CLIENT_MP,
            max_mp=CLIENT_MAX_MP,
        )
        output["client_placement"] = place_player(
            CLIENT_PIPE,
            CLIENT_POSITION[0],
            CLIENT_POSITION[1],
            90.0,
        )
        output["host_observes_client_position"] = wait_for_remote_position_convergence(
            HOST_PIPE,
            CLIENT_ID,
            CLIENT_POSITION[0],
            CLIENT_POSITION[1],
            args.timeout,
        )
        output["poison_injection"] = inject_native_poison_status(
            CLIENT_PIPE,
            duration_ticks=100_000,
            damage_per_tick=0.0,
            source_slot=0,
            label="client_owner_pre_join",
        )
        output["host_observes_poison"] = wait_for_poison_state(
            HOST_PIPE,
            participant_id=CLIENT_ID,
            poisoned=True,
            timeout=args.timeout,
        )
        pair_pids = detect_instance_pids()
        output["late_join"] = launch_third(args.timeout)
        first_pids = detect_instance_pids()
        if first_pids.get("host") != pair_pids.get("host") or first_pids.get("client") != pair_pids.get("client"):
            raise VerifyFailure(
                f"late join disturbed existing pair: before={pair_pids} after={first_pids}"
            )
        output["first_third_visibility"] = place_and_require_third_visible(
            FIRST_THIRD_POSITION,
            args.timeout,
        )
        output["late_join_bootstrap"] = verify_bootstrap(
            "late_join",
            recipe_uid=recipe_uid,
            expected_color=expected_color,
            timeout=args.timeout,
        )

        first_third_pid = first_pids.get("third")
        if first_third_pid is None:
            raise VerifyFailure(f"late third process was not detected: {first_pids}")
        output["disconnect"] = stop_third_process(first_third_pid, args.timeout)
        output["reconnect"] = launch_third(args.timeout)
        reconnected_pids = detect_instance_pids()
        if reconnected_pids.get("third") in (None, first_third_pid):
            raise VerifyFailure(
                f"reconnected third did not receive a new process: "
                f"first={first_pids} reconnected={reconnected_pids}"
            )
        if reconnected_pids.get("host") != pair_pids.get("host") or reconnected_pids.get("client") != pair_pids.get("client"):
            raise VerifyFailure(
                f"reconnect disturbed existing pair: before={pair_pids} after={reconnected_pids}"
            )
        output["reconnected_third_visibility"] = place_and_require_third_visible(
            RECONNECTED_THIRD_POSITION,
            args.timeout,
        )
        output["reconnect_bootstrap"] = verify_bootstrap(
            "same_identity_reconnect",
            recipe_uid=recipe_uid,
            expected_color=expected_color,
            timeout=args.timeout,
        )
        output["summary"] = {
            "participant_count": len(PARTICIPANTS),
            "late_join_bootstrap_passed": True,
            "same_identity_reconnect_bootstrap_passed": True,
            "presentation_and_position_checks": 2,
            "exact_equipment_identity_and_color_checks": 2,
            "inventory_and_gold_checks": 2,
            "vitals_and_transient_status_checks": 2,
            "skillbook_statbook_loadout_checks": 2,
        }
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        output["error"] = str(exc)
        return_code = 1
    finally:
        if not args.keep_open:
            stop_games()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error", ""),
                "summary": output.get("summary", {}),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
