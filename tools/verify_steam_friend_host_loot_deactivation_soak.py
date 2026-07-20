#!/usr/bin/env python3
"""Soak host loot retirement on an authenticated two-account Steam pair."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_primary_kill_stress import configure


DEFAULT_ITERATIONS = 64
DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_host_loot_deactivation_soak.json"


def write_checkpoint(
    output_path: Path,
    pair: SteamFriendActivePair,
    result: dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(pair.redact(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def require_deferred_retirement_log(
    network_drop_id: int,
    log_offset: int,
) -> str:
    marker = (
        "native_loot: stock deferred-retirement request completed at the "
        "post-stock AppMainTick boundary."
    )
    for line in primary.log_after(primary.HOST_LOG, log_offset).splitlines():
        if (
            marker in line
            and f"network_drop_id={network_drop_id}" in line
            and "kind=Gold" in line
            and "deactivated=1" in line
            and "seh=0x0" in line
        ):
            return line
    raise VerifyFailure(
        "accepted gold pickup lacked successful post-stock retirement evidence: "
        f"network_drop_id={network_drop_id}"
    )


def compact_iteration(
    index: int,
    pickup_owner: str,
    drop: dict[str, Any],
    retirement_log: str,
) -> dict[str, Any]:
    host_drop = drop["host_drop"]
    client_drop = drop["client_drop"]
    pickup_result = drop["pickup_result"]
    return {
        "index": index,
        "pickup_owner": pickup_owner,
        "network_drop_id": primary.parse_int(client_drop.get("network_drop_id")),
        "host_actor_address": host_drop.get("actor_address"),
        "client_actor_address": client_drop.get("local_actor_address"),
        "pickup_result": pickup_result.get("pickup.result"),
        "pickup_participant_id": pickup_result.get("pickup.participant_id"),
        "host_actor_absent": drop["host_native_actor_absent_after_pickup"],
        "client_actor_absent": drop["client_native_actor_absent_after_pickup"],
        "retirement_log": retirement_log,
        "passed": True,
    }


def run_soak(
    pair: SteamFriendActivePair,
    *,
    iterations: int,
    output_path: Path,
    result: dict[str, Any],
) -> None:
    if any(
        side.get("scene") != "testrun"
        for side in result["pair"].values()
        if isinstance(side, dict) and "scene" in side
    ):
        raise VerifyFailure(
            f"Steam friend pair is not in a shared test run: {result['pair']}"
        )

    result["disable_bots"] = primary.disable_bots()
    result["manual_combat"] = primary.enable_manual_stock_spawner_combat()
    result["initial_cleanup"] = primary.cleanup_live_enemies()

    target_x, target_y = primary.snap_to_nav(
        CLIENT_ENDPOINT,
        primary.CLIENT_TARGET[0],
        primary.CLIENT_TARGET[1],
    )
    result["drop_position"] = {"x": target_x, "y": target_y}

    for index in range(1, iterations + 1):
        pickup_owner = "client"
        result["last_parking"] = primary.park_pair_away_from_target(
            target_x,
            target_y,
        )
        log_offset = primary.log_position(primary.HOST_LOG)
        drop = primary.verify_forced_gold_drop(
            amount=primary.FORCED_GOLD_AMOUNT,
            x=target_x,
            y=target_y,
            pickup_pipe=CLIENT_ENDPOINT,
        )
        network_drop_id = primary.parse_int(
            drop["client_drop"].get("network_drop_id")
        )
        retirement_log = require_deferred_retirement_log(
            network_drop_id,
            log_offset,
        )
        result["iterations"].append(
            compact_iteration(
                index,
                pickup_owner,
                drop,
                retirement_log,
            )
        )
        result["completed_iterations"] = index
        write_checkpoint(output_path, pair, result)

    result["final_views"] = {
        "host": local_sync.query(HOST_ENDPOINT),
        "client": local_sync.query(CLIENT_ENDPOINT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.iterations <= 37:
        raise SystemExit("--iterations must exceed the prior 37-pickup crash boundary")

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {
        "ok": False,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "requested_iterations": args.iterations,
        "completed_iterations": 0,
        "iterations": [],
        "started_at": time.time(),
    }
    return_code = 1
    host_crash_start = 0
    client_crash_start = 0
    try:
        result["pair"] = pair.discover()
        result["participant_names"] = configure(pair)
        host_crash_start = primary.crash_log_size(primary.HOST_CRASH_LOG)
        client_crash_start = primary.crash_log_size(primary.CLIENT_CRASH_LOG)
        run_soak(
            pair,
            iterations=args.iterations,
            output_path=args.output,
            result=result,
        )
        result["host_crash_delta"] = primary.crash_log_tail(
            primary.HOST_CRASH_LOG,
            host_crash_start,
        )
        result["client_crash_delta"] = primary.crash_log_tail(
            primary.CLIENT_CRASH_LOG,
            client_crash_start,
        )
        if result["host_crash_delta"] or result["client_crash_delta"]:
            raise VerifyFailure("loot retirement soak produced a new crash report")
        result["ok"] = True
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        if host_crash_start:
            result["host_crash_delta"] = primary.crash_log_tail(
                primary.HOST_CRASH_LOG,
                host_crash_start,
            )
        if client_crash_start:
            result["client_crash_delta"] = primary.crash_log_tail(
                primary.CLIENT_CRASH_LOG,
                client_crash_start,
            )
    finally:
        result["ended_at"] = time.time()
        result["duration_seconds"] = round(
            result["ended_at"] - result["started_at"],
            3,
        )
        write_checkpoint(args.output, pair, result)
        pair.close()

    print(
        json.dumps(
            {
                "ok": result["ok"],
                "completed_iterations": result["completed_iterations"],
                "error": result.get("error"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
