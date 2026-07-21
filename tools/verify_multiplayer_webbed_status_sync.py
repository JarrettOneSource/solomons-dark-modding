#!/usr/bin/env python3
"""Verify genuine Spider Webbed behavior for both multiplayer owners."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_natural_defense_harness import (
    arm_enemy_arena,
    configure_target_layout,
    query_enemy_target_state,
    set_enemy_mode,
)
from multiplayer_webbed_status_harness import (
    TRANSIENT_WEBBED,
    query_webbed_status,
    start_stock_web_escape,
    stop_stock_web_escape,
    wait_for_host_webbed_before_client_owner,
    wait_for_observer_webbed,
    wait_for_owner_webbed,
    wait_for_webbed_clear,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    parse_int_text,
    stop_games,
)
from verify_multiplayer_all_upgrade_sync import new_crash_artifacts
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_multiplayer_primary_kill_stress import (
    SPAWN_MANUAL_ENEMY_LUA,
    query_run_enemy_by_network_id,
    values,
    wait_for_spawn_result,
)
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime/multiplayer_webbed_status_sync.json"
SPIDER_TYPE_ID = 0x809
# Native and protocol observations below prove ParticipantTransientStatusFlagWebbed.
TEST_LIFE = 1_000.0
SPIDER_ATTACK_DISTANCE = 96.0


@dataclass(frozen=True)
class Direction:
    name: str
    participant_id: int
    owner_pipe: str
    observer_pipe: str
    observer_requires_native_modifier: bool


DIRECTIONS = (
    Direction("host_owned", HOST_ID, HOST_PIPE, CLIENT_PIPE, False),
    Direction("client_owned", CLIENT_ID, CLIENT_PIPE, HOST_PIPE, True),
)


def wait_for_replicated_spider(
    pipe_name: str,
    network_actor_id: int,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_run_enemy_by_network_id(pipe_name, network_actor_id)
        if (
            last.get("found") == "true"
            and parse_int_text(last.get("object_type_id"), 0) == SPIDER_TYPE_ID
            and last.get("tracked") == "true"
            and last.get("dead") != "true"
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"exact Spider did not materialize on {pipe_name}: "
        f"network_actor_id={network_actor_id} last={last}"
    )


def spawn_exact_spider(timeout: float) -> dict[str, Any]:
    request = values(
        HOST_PIPE,
        SPAWN_MANUAL_ENEMY_LUA
        .replace("__TYPE_ID__", str(SPIDER_TYPE_ID))
        .replace("__X__", "7000.0")
        .replace("__Y__", "7000.0")
        .replace("__FREEZE_ON_SPAWN__", "false"),
    )
    if request.get("ok") != "true":
        raise VerifyFailure(f"exact Spider spawn request failed: {request}")
    request_id = parse_int_text(request.get("request_id"), 0)
    result = wait_for_spawn_result(request_id, timeout=timeout)
    if parse_int_text(result.get("type_id"), 0) != SPIDER_TYPE_ID:
        raise VerifyFailure(
            f"exact Spider request materialized another class: {result}"
        )
    network_actor_id = parse_int_text(result.get("network_actor_id"), 0)
    if network_actor_id == 0:
        raise VerifyFailure(f"exact Spider has no network actor id: {result}")
    return {
        "request": request,
        "result": result,
        "network_actor_id": network_actor_id,
        "host": wait_for_replicated_spider(
            HOST_PIPE, network_actor_id, timeout
        ),
        "client": wait_for_replicated_spider(
            CLIENT_PIPE, network_actor_id, timeout
        ),
    }


def require_clear_baseline(direction: Direction, timeout: float) -> dict[str, Any]:
    return {
        "owner": wait_for_webbed_clear(
            direction.owner_pipe,
            participant_id=None,
            timeout=timeout,
        ),
        "observer": wait_for_webbed_clear(
            direction.observer_pipe,
            participant_id=direction.participant_id,
            timeout=timeout,
        ),
    }


def run_direction(
    direction: Direction,
    timeout: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    spider = spawn_exact_spider(timeout)
    result["spider"] = spider
    arena = arm_enemy_arena()
    result["arena"] = arena
    result["escape_stopped_before_attack"] = stop_stock_web_escape(
        direction.owner_pipe
    )
    layout = configure_target_layout(direction.owner_pipe)
    result["layout"] = layout
    resources = {
        "host": set_local_player_vitals(HOST_PIPE, TEST_LIFE, TEST_LIFE),
        "client": set_local_player_vitals(CLIENT_PIPE, TEST_LIFE, TEST_LIFE),
    }
    result["resources"] = resources
    baseline = require_clear_baseline(direction, timeout)
    result["baseline"] = baseline
    attack = set_enemy_mode(
        "attack",
        direction.participant_id if direction.owner_pipe == CLIENT_PIPE else None,
        SPIDER_ATTACK_DISTANCE,
        timeout=timeout,
        enemy_actor_address=parse_int_text(
            spider["result"].get("actor_address"),
            0,
        ),
    )
    result["attack"] = attack
    host_native_witness = None
    if direction.observer_requires_native_modifier:
        try:
            host_native_witness = wait_for_host_webbed_before_client_owner(
                direction.observer_pipe,
                direction.owner_pipe,
                direction.participant_id,
                timeout,
            )
        except VerifyFailure:
            result["attack_diagnostics"] = query_enemy_target_state(
                parse_int_text(spider["result"].get("actor_address"), 0),
                parse_int_text(attack.get("target_actor"), 0),
            )
            raise
        result["host_native_witness"] = host_native_witness
    observer_active = wait_for_observer_webbed(
        direction.observer_pipe,
        direction.participant_id,
        require_native_modifier=direction.observer_requires_native_modifier,
        timeout=timeout,
    )
    result["observer_active"] = observer_active
    owner_active = wait_for_owner_webbed(direction.owner_pipe, timeout)
    result["owner_active"] = owner_active
    result["parked_after_attack"] = set_enemy_mode("park", timeout=timeout)

    if owner_active["control_refs"] < 1:
        raise VerifyFailure(
            f"{direction.name} owner Webbed smart pointer is imbalanced: "
            f"{owner_active}"
        )
    if direction.observer_requires_native_modifier:
        if observer_active["control_refs"] < 1:
            raise VerifyFailure(
                f"{direction.name} host-mirror Webbed smart pointer is "
                f"imbalanced: {observer_active}"
            )
    elif observer_active["webbed_count"] != 0:
        raise VerifyFailure(
            f"{direction.name} observer created a behavioral Webbed clone: "
            f"{observer_active}"
        )
    if not (owner_active["runtime_flags"] & TRANSIENT_WEBBED):
        raise VerifyFailure(
            f"{direction.name} owner protocol lost Webbed: {owner_active}"
        )

    escape = start_stock_web_escape(direction.owner_pipe)
    result["escape"] = escape
    owner_cleared = wait_for_webbed_clear(
        direction.owner_pipe,
        participant_id=None,
        timeout=timeout,
    )
    result["owner_cleared"] = owner_cleared
    observer_cleared = wait_for_webbed_clear(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        timeout=timeout,
    )
    result["observer_cleared"] = observer_cleared
    escape_stopped = stop_stock_web_escape(direction.owner_pipe)
    result["escape_stopped"] = escape_stopped
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
            prearm_manual_spawner=True,
        )
        output["directions"] = {}
        for direction in DIRECTIONS:
            direction_result: dict[str, Any] = {}
            output["directions"][direction.name] = direction_result
            run_direction(
                direction,
                args.timeout,
                direction_result,
            )
        output["spiders_after"] = {
            name: {
                "host": query_run_enemy_by_network_id(
                    HOST_PIPE,
                    result["spider"]["network_actor_id"],
                ),
                "client": query_run_enemy_by_network_id(
                    CLIENT_PIPE,
                    result["spider"]["network_actor_id"],
                ),
            }
            for name, result in output["directions"].items()
        }
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                "new crash artifacts during Webbed regression: "
                f"{output['new_crash_artifacts']}"
            )
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
        try:
            output["failure_status"] = {
                direction.name: {
                    "owner": query_webbed_status(direction.owner_pipe),
                    "observer": query_webbed_status(
                        direction.observer_pipe,
                        participant_id=direction.participant_id,
                    ),
                }
                for direction in DIRECTIONS
            }
        except Exception as capture_error:
            output["failure_capture_error"] = str(capture_error)
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
            name: {
                "owner_ticks": result.get("owner_active", {}).get(
                    "modifier_ticks"
                ),
                "owner_strength": result.get("owner_active", {}).get(
                    "modifier_strength"
                ),
                "observer_native_count": result.get(
                    "observer_active", {}
                ).get("webbed_count"),
                "observer_render_flags": result.get(
                    "observer_active", {}
                ).get("actor_render_drive_flags"),
            }
            for name, result in output.get("directions", {}).items()
        },
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(args.output),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
