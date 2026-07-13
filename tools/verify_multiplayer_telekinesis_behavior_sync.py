#!/usr/bin/env python3
"""Verify stock Telekinesis pickup behavior and ownership in both directions."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import query_progression_snapshot
from probe_run_reward_sync import (
    capture as reward_capture,
    reward_rows,
    spawn_gold,
    wait_for_client_replicated_loot,
    wait_for_spawned_host_reward,
)
from verify_flat_multiplayer_boneyard import nav_summary
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    distance,
    parse_int_text,
    place_player,
    snap_to_nav,
    stop_games,
    wait_for_local_transform_settled,
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
from verify_multiplayer_gold_pickup_authority import (
    capture_pair as pickup_capture_pair,
    find_participant,
    try_wait_for_client_pickup_result,
    wait_for_client_replicated_drop_absent,
)


OUTPUT = ROOT / "runtime/multiplayer_telekinesis_behavior_sync.json"
TELEKINESIS_ROW = 66
STOCK_GOLD_RANGE_SCALE = 30.0
TRIAL_DISTANCE = 120.0
TRIAL_DISTANCE_TOLERANCE = 24.0
OTHER_PLAYER_MIN_DISTANCE = 520.0
BASELINE_HOLD_SECONDS = 1.5
GOLD_AMOUNTS = {HOST_ID: 11, CLIENT_ID: 13}


@dataclass(frozen=True)
class Direction:
    name: str
    participant_id: int
    owner_pipe: str
    observer_pipe: str
    other_pipe: str


DIRECTIONS = (
    Direction("host_owned", HOST_ID, HOST_PIPE, CLIENT_PIPE, CLIENT_PIPE),
    Direction("client_owned", CLIENT_ID, CLIENT_PIPE, HOST_PIPE, HOST_PIPE),
)


def player_gold(values: dict[str, str]) -> int:
    return parse_int_text(values.get("player.gold"), 0)


def compact_gold_capture(values: dict[str, str]) -> dict[str, Any]:
    return {
        "player_gold": player_gold(values),
        "player_x": float(values.get("player.x", "nan")),
        "player_y": float(values.get("player.y", "nan")),
        "participants": [
            {
                "id": row["id"],
                "name": row["name"],
                "gold": row["gold"],
                "gold_revision": row["gold_revision"],
                "x": row["x"],
                "y": row["y"],
            }
            for row in (
                find_participant(values, HOST_ID),
                find_participant(values, CLIENT_ID),
            )
            if row is not None
        ],
    }


def select_geometry() -> dict[str, Any]:
    nav = nav_summary(HOST_PIPE)
    center_x = (float(nav["min_x"]) + float(nav["max_x"])) * 0.5
    center_y = (float(nav["min_y"]) + float(nav["max_y"])) * 0.5
    requested_drops = (
        (center_x, center_y),
        (center_x - float(nav["span_x"]) * 0.2, center_y),
        (center_x, center_y - float(nav["span_y"]) * 0.2),
    )
    approach_offsets = (
        (TRIAL_DISTANCE, 0.0),
        (-TRIAL_DISTANCE, 0.0),
        (0.0, TRIAL_DISTANCE),
        (0.0, -TRIAL_DISTANCE),
    )
    far_offsets = (
        (900.0, 0.0),
        (-900.0, 0.0),
        (0.0, 900.0),
        (0.0, -900.0),
        (700.0, 700.0),
        (-700.0, -700.0),
    )
    attempts: list[dict[str, Any]] = []
    for requested_drop_x, requested_drop_y in requested_drops:
        drop_x, drop_y = snap_to_nav(HOST_PIPE, requested_drop_x, requested_drop_y)
        for offset_x, offset_y in approach_offsets:
            approach_x, approach_y = snap_to_nav(
                HOST_PIPE,
                drop_x + offset_x,
                drop_y + offset_y,
            )
            approach_distance = distance(approach_x, approach_y, drop_x, drop_y)
            if abs(approach_distance - TRIAL_DISTANCE) > TRIAL_DISTANCE_TOLERANCE:
                attempts.append({
                    "drop": [drop_x, drop_y],
                    "approach": [approach_x, approach_y],
                    "approach_distance": approach_distance,
                })
                continue
            for far_dx, far_dy in far_offsets:
                far_x, far_y = snap_to_nav(HOST_PIPE, drop_x + far_dx, drop_y + far_dy)
                far_distance = distance(far_x, far_y, drop_x, drop_y)
                if far_distance >= OTHER_PLAYER_MIN_DISTANCE:
                    return {
                        "nav": nav,
                        "drop": {"x": drop_x, "y": drop_y},
                        "approach": {
                            "x": approach_x,
                            "y": approach_y,
                            "distance": approach_distance,
                        },
                        "far": {"x": far_x, "y": far_y, "distance": far_distance},
                    }
    raise VerifyFailure(f"flat arena could not provide Telekinesis geometry: {attempts}")


def place_trial_players(direction: Direction, geometry: dict[str, Any]) -> dict[str, Any]:
    approach = geometry["approach"]
    far = geometry["far"]
    owner_place = place_player(
        direction.owner_pipe,
        float(approach["x"]),
        float(approach["y"]),
        180.0,
    )
    other_place = place_player(
        direction.other_pipe,
        float(far["x"]),
        float(far["y"]),
        180.0,
    )
    owner_settled = wait_for_local_transform_settled(
        direction.owner_pipe,
        stable_seconds=0.3,
    )
    other_settled = wait_for_local_transform_settled(
        direction.other_pipe,
        stable_seconds=0.3,
    )
    drop = geometry["drop"]
    owner_distance = distance(
        owner_settled[0], owner_settled[1], float(drop["x"]), float(drop["y"])
    )
    other_distance = distance(
        other_settled[0], other_settled[1], float(drop["x"]), float(drop["y"])
    )
    if abs(owner_distance - TRIAL_DISTANCE) > TRIAL_DISTANCE_TOLERANCE:
        raise VerifyFailure(
            f"{direction.name} owner did not settle at the discriminating distance: "
            f"actual={owner_distance:.3f} expected={TRIAL_DISTANCE:.3f}"
        )
    if other_distance < OTHER_PLAYER_MIN_DISTANCE:
        raise VerifyFailure(
            f"{direction.name} untargeted player settled too close to the drop: "
            f"actual={other_distance:.3f}"
        )
    return {
        "owner_place": owner_place,
        "other_place": other_place,
        "owner_settled": {
            "x": owner_settled[0],
            "y": owner_settled[1],
            "distance": owner_distance,
        },
        "other_settled": {
            "x": other_settled[0],
            "y": other_settled[1],
            "distance": other_distance,
        },
    }


def wait_for_gold_view_parity(timeout: float) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last = pickup_capture_pair()
    while time.monotonic() < deadline:
        last = pickup_capture_pair()
        host_on_client = find_participant(last["client"], HOST_ID)
        client_on_host = find_participant(last["host"], CLIENT_ID)
        if (
            host_on_client is not None
            and client_on_host is not None
            and host_on_client["gold"] == player_gold(last["host"])
            and client_on_host["gold"] == player_gold(last["client"])
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"participant gold views did not converge: {last}")


def assert_drop_survives_baseline(
    direction: Direction,
    *,
    reward_address: int,
    network_drop_id: int,
    amount: int,
    before_pair: dict[str, dict[str, str]],
) -> dict[str, Any]:
    deadline = time.monotonic() + BASELINE_HOLD_SECONDS
    samples = 0
    last_reward: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        samples += 1
        host_reward = next(
            (row for row in reward_rows(reward_capture(HOST_PIPE)) if row["address"] == reward_address),
            None,
        )
        if host_reward is None or int(host_reward["amount"]) != amount:
            raise VerifyFailure(
                f"{direction.name} baseline picked up the discriminating drop: {host_reward}"
            )
        last_reward = host_reward
        current_pair = pickup_capture_pair()
        if player_gold(current_pair["host"]) != player_gold(before_pair["host"]):
            raise VerifyFailure(f"{direction.name} baseline changed host gold")
        if player_gold(current_pair["client"]) != player_gold(before_pair["client"]):
            raise VerifyFailure(f"{direction.name} baseline changed client gold")
        client_result = current_pair["client"]
        if (
            client_result.get("pickup.valid") == "true"
            and parse_int_text(client_result.get("pickup.network_drop_id"), 0) == network_drop_id
            and client_result.get("pickup.result") == "Accepted"
        ):
            raise VerifyFailure(f"{direction.name} baseline client request was accepted")
        time.sleep(0.1)
    return {
        "duration_seconds": BASELINE_HOLD_SECONDS,
        "samples": samples,
        "last_reward": last_reward,
        "host_gold": player_gold(before_pair["host"]),
        "client_gold": player_gold(before_pair["client"]),
    }


def wait_for_host_reward_consumed(address: int, timeout: float) -> dict[str, Any]:
    """Accept either stock removal or the authority path's zeroed carrier."""
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = reward_capture(HOST_PIPE)
        row = next(
            (candidate for candidate in reward_rows(last) if candidate["address"] == address),
            None,
        )
        if row is None:
            return {"consumed": True, "mode": "removed"}
        if int(row["amount"]) == 0:
            return {"consumed": True, "mode": "zeroed", "reward": row}
        time.sleep(0.1)
    raise VerifyFailure(
        f"host gold reward was neither removed nor zeroed: address=0x{address:X} last={last}"
    )


def wait_for_gold_credit(
    direction: Direction,
    *,
    amount: int,
    before_pair: dict[str, dict[str, str]],
    timeout: float,
) -> dict[str, Any]:
    expected_owner_gold = player_gold(before_pair[
        "host" if direction.participant_id == HOST_ID else "client"
    ]) + amount
    expected_other_gold = player_gold(before_pair[
        "client" if direction.participant_id == HOST_ID else "host"
    ])
    deadline = time.monotonic() + timeout
    last = pickup_capture_pair()
    while time.monotonic() < deadline:
        last = pickup_capture_pair()
        owner_label = "host" if direction.participant_id == HOST_ID else "client"
        other_label = "client" if owner_label == "host" else "host"
        observer_row = find_participant(last[other_label], direction.participant_id)
        if (
            player_gold(last[owner_label]) == expected_owner_gold
            and player_gold(last[other_label]) == expected_other_gold
            and observer_row is not None
            and observer_row["gold"] == expected_owner_gold
        ):
            return {
                "expected_owner_gold": expected_owner_gold,
                "expected_other_gold": expected_other_gold,
                "owner": compact_gold_capture(last[owner_label]),
                "observer": compact_gold_capture(last[other_label]),
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"{direction.name} Telekinesis pickup did not credit exactly one owner: {last}"
    )


def run_direction(
    direction: Direction,
    geometry: dict[str, Any],
    catalog: list[dict[str, Any]],
    initial_by_target: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {"placement": place_trial_players(direction, geometry)}
    before_pair = wait_for_gold_view_parity(timeout)
    result["before"] = {
        label: compact_gold_capture(values) for label, values in before_pair.items()
    }

    drop = geometry["drop"]
    amount = GOLD_AMOUNTS[direction.participant_id]
    before_addresses = {row["address"] for row in reward_rows(reward_capture(HOST_PIPE))}
    result["spawn"] = spawn_gold(
        HOST_PIPE,
        amount=amount,
        x=float(drop["x"]),
        y=float(drop["y"]),
    )
    spawned = wait_for_spawned_host_reward(
        before_addresses=before_addresses,
        amount=amount,
        x=float(drop["x"]),
        y=float(drop["y"]),
        timeout=timeout,
    )
    replicated = wait_for_client_replicated_loot(
        amount=amount,
        x=float(drop["x"]),
        y=float(drop["y"]),
        timeout=timeout,
    )
    reward_address = int(spawned["reward"]["address"])
    network_drop_id = int(replicated["drop"]["network_id"])
    result["drop"] = {
        "host": spawned["reward"],
        "client": replicated["drop"],
        "network_drop_id": network_drop_id,
    }
    result["baseline_survival"] = assert_drop_survives_baseline(
        direction,
        reward_address=reward_address,
        network_drop_id=network_drop_id,
        amount=amount,
        before_pair=before_pair,
    )

    result["upgrade_steps"] = max_stat_for_target(
        catalog,
        TELEKINESIS_ROW,
        direction.participant_id,
        initial_by_target,
        contract_values,
        timeout,
    )
    owner, observer = wait_for_derived_parity(direction.participant_id, timeout)
    pickup_range = float(owner["native"]["derived"]["pickup_range"])
    maximum = int(catalog[TELEKINESIS_ROW]["native_max_level"])
    active = int(owner["native"]["entries"][TELEKINESIS_ROW]["active"])
    stock_world_distance = pickup_range * STOCK_GOLD_RANGE_SCALE
    actual_distance = float(result["placement"]["owner_settled"]["distance"])
    if active != maximum or stock_world_distance <= actual_distance:
        raise VerifyFailure(
            f"{direction.name} max Telekinesis did not cover the live drop: "
            f"active={active}/{maximum} pickup_range={pickup_range:.3f} "
            f"world_distance={stock_world_distance:.3f} actual={actual_distance:.3f}"
        )
    result["upgraded_views"] = {
        "owner": compact_snapshot(owner, TELEKINESIS_ROW),
        "observer": compact_snapshot(observer, TELEKINESIS_ROW),
        "stock_gold_world_distance": stock_world_distance,
    }

    result["host_drop_consumed"] = wait_for_host_reward_consumed(
        reward_address,
        timeout,
    )
    result["client_drop_removed"] = wait_for_client_replicated_drop_absent(
        network_drop_id,
        timeout,
    )
    result["credit"] = wait_for_gold_credit(
        direction,
        amount=amount,
        before_pair=before_pair,
        timeout=timeout,
    )
    if direction.participant_id == CLIENT_ID:
        accepted = try_wait_for_client_pickup_result(
            network_drop_id=network_drop_id,
            request_sequence=None,
            expected_result="Accepted",
            timeout=timeout,
        )
        if accepted is None:
            raise VerifyFailure(
                "client-owned Telekinesis pickup had no host Accepted result"
            )
        result["accepted_result"] = {
            key: accepted.get(key)
            for key in (
                "pickup.request_sequence",
                "pickup.network_drop_id",
                "pickup.result",
                "pickup.amount",
                "pickup.resulting_gold",
            )
        }
    return result


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
        output["startup"] = launch_pair_ready(
            args.timeout,
            god_mode=False,
            manual_combat=False,
        )
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        catalog_result = build_and_verify_catalog(
            wait_for_catalog_views(args.timeout),
            load_skill_configs(),
        )
        catalog = catalog_result["catalog"]
        contract_values = load_stat_contract_values(catalog)
        initial = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }
        output["geometry"] = select_geometry()
        output["directions"] = {}
        for direction in DIRECTIONS:
            output["directions"][direction.name] = run_direction(
                direction,
                output["geometry"],
                catalog,
                initial,
                contract_values,
                args.timeout,
            )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts during Telekinesis test: {crashes}")
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

    print(json.dumps({
        "ok": output.get("ok", False),
        "error": output.get("error"),
        "directions": {
            label: {
                "baseline_survival": trial.get("baseline_survival"),
                "stock_gold_world_distance": trial.get("upgraded_views", {}).get(
                    "stock_gold_world_distance"
                ),
                "credit": trial.get("credit"),
            }
            for label, trial in output.get("directions", {}).items()
        },
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(args.output),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
