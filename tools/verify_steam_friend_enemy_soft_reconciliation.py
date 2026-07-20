#!/usr/bin/env python3
"""Verify soft enemy transform correction on an active Steam friend pair."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_verify
import verify_multiplayer_enemy_soft_reconciliation as reconciliation
import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import CLIENT_ENDPOINT, HOST_ENDPOINT, ROOT, SteamFriendActivePair
from steam_friend_behavior_context import configure_behavior_context, reset_quiet_arena
from verify_local_multiplayer_sync import VerifyFailure


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_enemy_soft_reconciliation.json"


def run(pair: SteamFriendActivePair, timeout: float) -> dict[str, Any]:
    discovered = pair.discover()
    if discovered["host"]["scene"] != "testrun" or discovered["client"]["scene"] != "testrun":
        raise VerifyFailure(f"Steam friend pair is not in a shared test run: {discovered}")
    configure_behavior_context(pair)
    reconciliation.HOST_PIPE = HOST_ENDPOINT
    reconciliation.CLIENT_PIPE = CLIENT_ENDPOINT

    result: dict[str, Any] = {
        "ok": False,
        "pair": discovered,
        "injected_drift": reconciliation.INJECTED_DRIFT,
        "maximum_correction_step": reconciliation.MAX_CORRECTION_STEP,
        "converged_error": reconciliation.CONVERGED_ERROR,
    }
    result["arena_reset"] = reset_quiet_arena()
    result["placement"] = {
        "host": local_verify.place_player(
            HOST_ENDPOINT, *reconciliation.HOST_POSITION, 90.0
        ),
        "client": local_verify.place_player(
            CLIENT_ENDPOINT, *reconciliation.CLIENT_POSITION, 90.0
        ),
    }
    result["placement"]["convergence"] = primary.wait_for_pair_transform_convergence(
        timeout=timeout
    )

    spawn = primary.spawn_one_enemy(
        *reconciliation.ENEMY_POSITION,
        setup_hp=50000.0,
        freeze_on_spawn=True,
    )
    network_id = primary.parse_int(spawn["result"].get("network_actor_id"))
    primary.find_target(
        HOST_ENDPOINT,
        *reconciliation.ENEMY_POSITION,
        network_id,
        timeout,
        require_local_binding=False,
    )
    primary.find_target(
        CLIENT_ENDPOINT,
        *reconciliation.ENEMY_POSITION,
        network_id,
        timeout,
    )
    result["spawn"] = {
        "type_id": primary.SKELETON_TYPE_ID,
        "x": reconciliation.ENEMY_POSITION[0],
        "y": reconciliation.ENEMY_POSITION[1],
        "hp": 50000.0,
        "host_frozen": True,
    }

    result["arm"] = reconciliation.values(
        CLIENT_ENDPOINT,
        reconciliation.ARM_PROBE_LUA
        .replace("__NETWORK_ID__", str(network_id))
        .replace("__AUTHORITY_X__", f"{reconciliation.ENEMY_POSITION[0]:.3f}")
        .replace("__AUTHORITY_Y__", f"{reconciliation.ENEMY_POSITION[1]:.3f}")
        .replace("__INJECTED_DRIFT__", f"{reconciliation.INJECTED_DRIFT:.3f}")
        .replace("__SAMPLE_COUNT__", str(reconciliation.SAMPLE_COUNT)),
    )
    if result["arm"].get("registered") != "true":
        raise VerifyFailure(f"failed to arm enemy reconciliation probe: {result['arm']}")

    _, samples = reconciliation.wait_for_samples(timeout)
    analysis = reconciliation.analyze_samples(samples)
    result["samples"] = samples
    result["analysis"] = analysis
    if analysis["initial_error"] < reconciliation.INJECTED_DRIFT - 2.0:
        raise VerifyFailure(f"probe did not observe injected drift: {analysis}")
    if analysis["max_correction_step"] > reconciliation.MAX_CORRECTION_STEP:
        raise VerifyFailure(f"replicated enemy used a visible hard correction: {analysis}")
    if analysis["correction_step_count"] < 3:
        raise VerifyFailure(f"replicated enemy did not use multiple correction steps: {analysis}")
    if not analysis["mostly_monotonic"]:
        raise VerifyFailure(f"replicated enemy correction oscillated: {analysis}")
    if analysis["final_error"] > reconciliation.CONVERGED_ERROR:
        raise VerifyFailure(f"replicated enemy did not converge: {analysis}")
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(pair, args.timeout)
        return_code = 0
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
                    "analysis": result.get("analysis"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
