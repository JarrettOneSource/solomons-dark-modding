#!/usr/bin/env python3
"""Verify live host run enemy spawns materialize on the client without sustained gaps."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    parse_key_values,
    lua,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)
from verify_run_world_snapshot import (
    CLIENT_SNAPSHOT_LUA,
    HOST_ENEMY_LUA,
    number,
    run_lifecycle_status,
    start_host_waves,
    wait_for_run_snapshot,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "run_enemy_materialization_catchup.json"


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def sample_once(elapsed: float) -> dict[str, Any]:
    host = values(HOST_PIPE, HOST_ENEMY_LUA)
    client = values(CLIENT_PIPE, CLIENT_SNAPSHOT_LUA)
    lifecycle = run_lifecycle_status(host, client)
    return {
        "elapsed": round(elapsed, 3),
        "host_live": int(number(host, "live_enemies")),
        "host_tracked": int(number(host, "tracked_enemies")),
        "client_snapshot_live": int(number(client, "live_snapshot_actors")),
        "client_local_live": int(number(client, "local_live_tracked_enemies")),
        "client_local_unparked": lifecycle["local_live_unparked_tracked_enemies"],
        "client_matched_live": lifecycle["matched_live_snapshot_actors"],
        "host_only_snapshot": lifecycle["host_only_snapshot_actors"],
        "extra_unparked_client": lifecycle["extra_unparked_client_tracked_enemies"],
        "client_apply_valid": client.get("apply_valid") == "true",
        "client_binding_count": int(number(client, "binding_count")),
    }


def longest_gap(samples: list[dict[str, Any]], key: str, interval: float) -> float:
    longest = 0.0
    current = 0.0
    for sample in samples:
        if int(sample.get(key, 0)) > 0:
            current += interval
            longest = max(longest, current)
        else:
            current = 0.0
    return round(longest, 3)


def run_verifier(
    *,
    sample_seconds: float,
    interval: float,
    max_sustained_gap_seconds: float,
    require_growth: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    stop_games()
    try:
        result["launch"] = launch_pair()
        disable_bots()
        result["host_run_entry"] = start_host_testrun_and_wait_for_clients()
        result["start_waves"] = start_host_waves()
        result["initial_snapshot"] = wait_for_run_snapshot(
            require_complete_lifecycle=True,
            stable_seconds=1.0,
        )
        initial_host_live = int(number(result["initial_snapshot"]["host"], "live_enemies"))

        samples: list[dict[str, Any]] = []
        deadline = time.monotonic() + sample_seconds
        started = time.monotonic()
        while time.monotonic() < deadline:
            samples.append(sample_once(time.monotonic() - started))
            time.sleep(interval)

        host_counts = [int(sample["host_live"]) for sample in samples]
        max_host_live = max(host_counts, default=0)
        max_host_only_gap = longest_gap(samples, "host_only_snapshot", interval)
        max_extra_gap = longest_gap(samples, "extra_unparked_client", interval)
        final = samples[-1] if samples else {}

        result["samples"] = samples
        result["summary"] = {
            "initial_host_live": initial_host_live,
            "max_host_live": max_host_live,
            "final": final,
            "max_host_only_gap_seconds": max_host_only_gap,
            "max_extra_unparked_gap_seconds": max_extra_gap,
            "sample_count": len(samples),
        }

        if not samples:
            raise VerifyFailure("no materialization samples collected")
        if require_growth and max_host_live <= initial_host_live:
            raise VerifyFailure(
                f"host did not spawn any additional enemies during sample window: "
                f"initial={initial_host_live} max={max_host_live}"
            )
        if max_host_only_gap > max_sustained_gap_seconds:
            raise VerifyFailure(
                f"client had host-only enemy snapshots for {max_host_only_gap:.2f}s "
                f"(limit {max_sustained_gap_seconds:.2f}s)"
            )
        if max_extra_gap > max_sustained_gap_seconds:
            raise VerifyFailure(
                f"client had extra unparked enemies for {max_extra_gap:.2f}s "
                f"(limit {max_sustained_gap_seconds:.2f}s)"
            )
        if int(final.get("host_only_snapshot", 0)) != 0:
            raise VerifyFailure(f"final sample still has host-only enemies: {final}")
        if int(final.get("extra_unparked_client", 0)) != 0:
            raise VerifyFailure(f"final sample still has extra client enemies: {final}")

        result["ok"] = True
        return result
    finally:
        stop_games()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-seconds", type=float, default=12.0)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--max-sustained-gap-seconds", type=float, default=1.0)
    parser.add_argument("--no-require-growth", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run_verifier(
            sample_seconds=args.sample_seconds,
            interval=args.interval,
            max_sustained_gap_seconds=args.max_sustained_gap_seconds,
            require_growth=not args.no_require_growth,
        )
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "summary": result.get("summary"),
        "error": result.get("error"),
        "output": str(RUNTIME_OUTPUT),
    }, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
