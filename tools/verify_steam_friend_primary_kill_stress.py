#!/usr/bin/env python3
"""Run the primary-cast kill stress suite on a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
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
from verify_steam_friend_active_pair_spell_behavior import (
    configure_behavior_modules,
)


DEFAULT_OUTPUT = (
    ROOT / "runtime" / "steam_friend_primary_kill_stress.json"
)
HOST_INSTANCE = os.environ.get(
    "SDMOD_STEAM_HOST_INSTANCE",
    "steam-host-regression-v60-manual",
)
CLIENT_INSTANCE = os.environ.get(
    "SDMOD_STEAM_CLIENT_INSTANCE",
    "wsl-steam-regression-v60-manual",
)


def configure(pair: SteamFriendActivePair) -> dict[str, str]:
    configure_behavior_modules(pair)

    host_log = Path(
        os.environ.get(
            "SDMOD_STEAM_HOST_LOG_PATH",
            ROOT
            / "runtime/instances"
            / HOST_INSTANCE
            / "stage/.sdmod/logs/solomondarkmodloader.log",
        )
    )
    client_log = Path(
        os.environ.get(
            "SDMOD_STEAM_CLIENT_LOG_PATH",
            ROOT
            / "runtime/instances"
            / CLIENT_INSTANCE
            / "stage/.sdmod/logs/solomondarkmodloader.log",
        )
    )
    primary.HOST_LOG = host_log
    primary.CLIENT_LOG = client_log
    primary.HOST_CRASH_LOG = host_log.with_name(
        "solomondarkmodloader.crash.log"
    )
    primary.CLIENT_CRASH_LOG = client_log.with_name(
        "solomondarkmodloader.crash.log"
    )

    host_view = local_sync.query(HOST_ENDPOINT)
    client_view = local_sync.query(CLIENT_ENDPOINT)
    host_name = client_view.get(
        f"peer.{pair.host_participant_id}.name",
        "",
    )
    client_name = host_view.get(
        f"peer.{pair.client_participant_id}.name",
        "",
    )
    if not host_name or not client_name:
        raise VerifyFailure(
            "Steam participant display names are unavailable"
        )

    for module in (local_sync, primary):
        module.HOST_ID = pair.host_participant_id
        module.CLIENT_ID = pair.client_participant_id
        module.HOST_NAME = host_name
        module.CLIENT_NAME = client_name
        module.HOST_PIPE = HOST_ENDPOINT
        module.CLIENT_PIPE = CLIENT_ENDPOINT
    primary.detect_instance_pids = lambda: {
        "host": 0,
        "client": 0,
    }
    return {"host": host_name, "client": client_name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kills-per-participant",
        type=int,
        default=30,
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--require-natural-drop", action="store_true")
    parser.add_argument(
        "--resume-output",
        type=Path,
        help="Resume the contiguous passed prefix from prior primary-kill evidence.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.kills_per_participant <= 0:
        raise SystemExit("--kills-per-participant must be positive")

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {
        "ok": False,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "started_at": time.time(),
    }
    return_code = 1
    stress_output = args.output.with_name(
        f"{args.output.stem}.primary{args.output.suffix}"
    )
    result["stress_output"] = str(stress_output)
    try:
        result["pair"] = pair.discover()
        if any(
            side.get("scene") != "testrun"
            for side in result["pair"].values()
            if isinstance(side, dict) and "scene" in side
        ):
            raise VerifyFailure(
                f"Steam friend pair is not in a shared test run: "
                f"{result['pair']}"
            )
        result["participant_names"] = configure(pair)
        primary.DIAGNOSTICS_ENABLED = bool(args.diagnostics)
        run_args = argparse.Namespace(
            kills_per_participant=args.kills_per_participant,
            timeout=args.timeout,
            attach=True,
            diagnostics=args.diagnostics,
            require_natural_drop=args.require_natural_drop,
            resume_output=args.resume_output,
            output=stress_output,
        )
        result["stress"] = primary.run_verifier(run_args)
        result["ok"] = bool(result["stress"].get("ok"))
        return_code = 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        try:
            result["stress"] = json.loads(
                stress_output.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            pass
    finally:
        pair.close()
        result["ended_at"] = time.time()
        result["duration_seconds"] = round(
            result["ended_at"] - result["started_at"],
            3,
        )
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
                    "kills": len(
                        result.get("stress", {}).get("kills", [])
                    ),
                    "natural_loot": result.get("stress", {}).get(
                        "natural_loot_summary"
                    ),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
