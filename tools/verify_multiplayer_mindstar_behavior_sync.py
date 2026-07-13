#!/usr/bin/env python3
"""Verify Mindstar's +1 skill rank and mana hoard for either owner."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_persistent_status_harness import (
    PERSISTENT_MINDSTAR,
    query_persistent_status,
)
from multiplayer_progression_probe import (
    query_progression_snapshot,
    query_ranked_numeric_stat,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    stop_games,
)
from verify_multiplayer_all_upgrade_sync import (
    new_crash_artifacts,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_embers_effect_sync import (
    SECONDARY_OFFSET,
    direction_for_owner,
)
from verify_multiplayer_fireball_explode_effect_sync import (
    build_manual_pair,
    cast_fireball_pair,
    launch_pair_ready,
)
from verify_multiplayer_focus_behavior_sync import (
    DIRECTIONS,
    Direction,
    acquire_secondary_to_rank,
)
from verify_multiplayer_persistent_status_sync import toggle_once
from verify_multiplayer_primary_kill_stress import cleanup_live_enemies
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import detect_instance_pids, read_log
from verify_spell_cast_sync import (
    remote_cast_state_lua,
    values,
    wait_for_remote_completion,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_mindstar_behavior_sync.json"
MINDSTAR_ROW = 0x4E
CONTROLLED_RESOURCE = 100.0


def observer_pipe(direction: Direction) -> str:
    return HOST_PIPE if direction.source_pipe == CLIENT_PIPE else CLIENT_PIPE


def query_spell_views(direction: Direction) -> dict[str, Any]:
    owner = query_progression_snapshot(direction.source_pipe)
    observer = query_progression_snapshot(
        observer_pipe(direction),
        participant_id=direction.source_id,
    )
    combo_entry = int(owner["loadout"]["combo_entry"])
    return {
        "owner": owner,
        "observer": observer,
        "combo_entry": combo_entry,
        "base_mana_property": query_ranked_numeric_stat(
            direction.source_pipe,
            combo_entry,
            "mManaCost",
        ),
        "mindstar_hoard_property": query_ranked_numeric_stat(
            direction.source_pipe,
            MINDSTAR_ROW,
            "mHoard",
        ),
    }


def compact_spell(view: dict[str, Any]) -> dict[str, Any]:
    spell = view["spell"]
    return {
        "resolved": spell["resolved"],
        "current_spell_id": spell["current_spell_id"],
        "output_count": spell["output_count"],
        "outputs": spell["outputs"],
        "damage": spell["damage"],
        "mana_cost": spell["mana_cost"],
        "mana_spend_cost": spell["mana_spend_cost"],
    }


def wait_for_spell_views(
    direction: Direction,
    label: str,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Wait until stock cast work releases the shared native output buffer."""

    deadline = time.monotonic() + timeout
    attempts = 0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        last = query_spell_views(direction)
        owner = compact_spell(last["owner"])
        observer = compact_spell(last["observer"])
        if owner["resolved"] and observer["resolved"] and owner == observer:
            last["quiescent_attempt_count"] = attempts
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} {label} native primary output buffer did not "
        f"quiesce: owner={compact_spell(last['owner']) if last else {}} "
        f"observer={compact_spell(last['observer']) if last else {}}"
    )


def verify_owner_observer_spell_parity(
    direction: Direction,
    label: str,
    views: dict[str, Any],
) -> dict[str, Any]:
    owner = compact_spell(views["owner"])
    observer = compact_spell(views["observer"])
    if not owner["resolved"] or not observer["resolved"] or owner != observer:
        raise VerifyFailure(
            f"{direction.name} {label} native primary outputs diverged: "
            f"owner={owner} observer={observer}"
        )
    return {"owner": owner, "observer": observer, "exact_match": True}


def run_fireball_trial(
    direction: Direction,
    cast_direction: Any,
    label: str,
) -> dict[str, Any]:
    cleanup = cleanup_live_enemies()
    pair = build_manual_pair(cast_direction, *SECONDARY_OFFSET)
    receiver_log_offset = len(read_log(cast_direction.receiver_log))
    cast = cast_fireball_pair(
        cast_direction,
        pair,
        f"mindstar.{direction.name}.{label}",
    )
    damage = cast["damage"]
    if not damage["primary_damaged"] or damage["secondary_damaged"]:
        raise VerifyFailure(
            f"{direction.name} {label} Fireball geometry was not single-target: {damage}"
        )
    if not cast.get("replicated_cast_delivery", {}).get("ok"):
        raise VerifyFailure(
            f"{direction.name} {label} Fireball did not execute natively on both peers: "
            f"{cast.get('replicated_cast_delivery')}"
        )
    completion = wait_for_remote_completion(
        cast_direction,
        receiver_log_offset,
    )
    deadline = time.monotonic() + 3.0
    final_state: dict[str, str] = {}
    while time.monotonic() < deadline:
        final_state = values(
            cast_direction.receiver_pipe,
            remote_cast_state_lua(direction.source_id),
        )
        if final_state.get("cast_active") != "true" and final_state.get(
            "cast_pending"
        ) != "true":
            break
        time.sleep(0.05)
    if final_state.get("cast_active") == "true" or final_state.get(
        "cast_pending"
    ) == "true":
        raise VerifyFailure(
            f"{direction.name} {label} remote Fireball did not settle: {final_state}"
        )
    return {
        "cleanup": cleanup,
        "pair": pair,
        "cast": cast,
        "remote_completion": completion,
        "remote_final_state": final_state,
    }


def wait_for_hoarded_mana(
    direction: Direction,
    expected_mana: float,
    timeout: float,
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
        if (
            math.isclose(owner["mp"], expected_mana, abs_tol=0.15)
            and math.isclose(observer["mp"], expected_mana, abs_tol=0.75)
            and math.isclose(owner["max_mp"], CONTROLLED_RESOURCE, abs_tol=0.15)
            and math.isclose(observer["max_mp"], CONTROLLED_RESOURCE, abs_tol=0.75)
        ):
            return {
                "attempt_count": attempts,
                "expected_mana": expected_mana,
                "owner": owner,
                "observer": observer,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} Mindstar mana hoard did not converge to "
        f"{expected_mana}: owner={owner} observer={observer}"
    )


def verify_behavior_transition(
    direction: Direction,
    baseline_views: dict[str, Any],
    active_views: dict[str, Any],
    baseline_cast: dict[str, Any],
    active_cast: dict[str, Any],
) -> dict[str, Any]:
    baseline_spell = compact_spell(baseline_views["owner"])
    active_spell = compact_spell(active_views["owner"])
    if baseline_spell["current_spell_id"] != active_spell["current_spell_id"]:
        raise VerifyFailure(
            f"{direction.name} Mindstar changed the selected spell instead of its rank"
        )
    if baseline_spell["output_count"] != active_spell["output_count"]:
        raise VerifyFailure(
            f"{direction.name} Mindstar changed the primary output shape"
        )
    if (
        active_spell["damage"] <= baseline_spell["damage"]
        or active_spell["mana_cost"] <= baseline_spell["mana_cost"]
    ):
        raise VerifyFailure(
            f"{direction.name} Mindstar did not advance Fireball by one native rank: "
            f"baseline={baseline_spell} active={active_spell}"
        )

    baseline_damage = float(baseline_cast["cast"]["damage"]["primary_damage"])
    active_damage = float(active_cast["cast"]["damage"]["primary_damage"])
    native_ratio = active_spell["damage"] / baseline_spell["damage"]
    behavior_ratio = active_damage / baseline_damage
    if not math.isclose(behavior_ratio, native_ratio, rel_tol=0.0, abs_tol=0.08):
        raise VerifyFailure(
            f"{direction.name} real Fireball damage did not follow Mindstar's native "
            f"+1 output: native_ratio={native_ratio} behavior_ratio={behavior_ratio} "
            f"baseline={baseline_damage} active={active_damage}"
        )
    return {
        "baseline_native_damage": baseline_spell["damage"],
        "active_native_damage": active_spell["damage"],
        "baseline_native_mana": baseline_spell["mana_cost"],
        "active_native_mana": active_spell["mana_cost"],
        "baseline_real_damage": baseline_damage,
        "active_real_damage": active_damage,
        "native_damage_ratio": native_ratio,
        "real_damage_ratio": behavior_ratio,
        "ok": True,
    }


def run_direction(
    direction: Direction,
    acquisition: dict[str, Any],
    cast_direction: Any,
    timeout: float,
) -> dict[str, Any]:
    baseline_views = wait_for_spell_views(direction, "baseline")
    baseline_parity = verify_owner_observer_spell_parity(
        direction,
        "baseline",
        baseline_views,
    )
    resource_reset = set_local_player_vitals(
        direction.source_pipe,
        CONTROLLED_RESOURCE,
        CONTROLLED_RESOURCE,
    )
    activated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=PERSISTENT_MINDSTAR,
        timeout=timeout,
    )
    hoard_property = query_ranked_numeric_stat(
        direction.source_pipe,
        MINDSTAR_ROW,
        "mHoard",
    )
    if not hoard_property["property_found"]:
        raise VerifyFailure(
            f"{direction.name} Mindstar mHoard is unavailable: {hoard_property}"
        )
    expected_mana = CONTROLLED_RESOURCE * (
        1.0 - float(hoard_property["value"]) / 100.0
    )
    hoarded_mana = wait_for_hoarded_mana(direction, expected_mana, timeout)

    active_views = wait_for_spell_views(direction, "active")
    active_parity = verify_owner_observer_spell_parity(
        direction,
        "active",
        active_views,
    )
    deactivated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=0,
        timeout=timeout,
    )
    restored_views = wait_for_spell_views(direction, "restored")
    restored_parity = verify_owner_observer_spell_parity(
        direction,
        "restored",
        restored_views,
    )
    if compact_spell(restored_views["owner"]) != compact_spell(
        baseline_views["owner"]
    ):
        raise VerifyFailure(
            f"{direction.name} Mindstar outputs did not restore after toggle-off: "
            f"baseline={compact_spell(baseline_views['owner'])} "
            f"restored={compact_spell(restored_views['owner'])}"
        )

    # Exercise real damage only after the full stock builder vectors have been
    # compared. A completed remote Fireball intentionally leaves additional
    # stock construction outputs in its participant-owned native buffer; those
    # trailing values are runtime work state, not Mindstar rank outputs.
    baseline_cast = run_fireball_trial(
        direction,
        cast_direction,
        "baseline",
    )
    cast_resource_reset = set_local_player_vitals(
        direction.source_pipe,
        CONTROLLED_RESOURCE,
        CONTROLLED_RESOURCE,
    )
    reactivated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=PERSISTENT_MINDSTAR,
        timeout=timeout,
    )
    active_cast = run_fireball_trial(
        direction,
        cast_direction,
        "active",
    )
    transition = verify_behavior_transition(
        direction,
        baseline_views,
        active_views,
        baseline_cast,
        active_cast,
    )
    final_deactivated = toggle_once(
        direction,
        belt_slot=int(acquisition["belt_slot"]),
        expected_values=0,
        timeout=timeout,
    )
    return {
        "baseline": {
            "views": baseline_views,
            "parity": baseline_parity,
            "cast": baseline_cast,
        },
        "resource_reset": resource_reset,
        "activated": activated,
        "hoarded_mana": hoarded_mana,
        "active": {
            "views": active_views,
            "parity": active_parity,
            "cast": active_cast,
        },
        "transition": transition,
        "deactivated": deactivated,
        "restored": {
            "views": restored_views,
            "parity": restored_parity,
        },
        "cast_resource_reset": cast_resource_reset,
        "reactivated": reactivated,
        "final_deactivated": final_deactivated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(args.timeout, god_mode=False)
        output["launch"] = startup["launch"]
        output["manual_combat"] = startup["manual_combat"]
        output["post_run_progression_ready"] = (
            wait_for_post_run_progression_ready(args.timeout)
        )
        acquisitions = {
            direction.name: acquire_secondary_to_rank(
                direction,
                MINDSTAR_ROW,
                1,
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["acquisitions"] = acquisitions

        pids = detect_instance_pids()
        output["directions"] = {}
        for direction in DIRECTIONS:
            owner = "host" if direction.source_id == HOST_ID else "client"
            output["directions"][direction.name] = run_direction(
                direction,
                acquisitions[direction.name],
                direction_for_owner(owner, pids),
                args.timeout,
            )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts during Mindstar test: {crashes}"
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
