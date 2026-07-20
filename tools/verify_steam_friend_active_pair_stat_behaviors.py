#!/usr/bin/env python3
"""Verify remaining native stat behaviors on a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from drive_steam_friend_active_pair import disable_test_manual_enemy_mode
import multiplayer_progression_probe as progression
import verify_multiplayer_defense_behavior_sync as defense
import verify_multiplayer_staff_stat_behavior_sync as staff
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    BehaviorContext,
    configure_behavior_context,
    disable_runtime_test_godmode,
    load_progression_inputs,
    require_shared_test_run,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_real_input_spell_cast_sync import Direction
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_stat_behaviors.json"
PROFILE_ROWS = {
    "defense": (
        defense.RESIST_MAGIC_ROW,
        defense.DEFLECT_ROW,
        defense.RESIST_POISON_ROW,
    ),
    "staff": (
        staff.ENCHANT_STAFF_ROW,
        staff.FORTUNATE_FLAILING_ROW,
    ),
}


def assert_pristine_rows(
    pair: SteamFriendActivePair,
    rows: tuple[int, ...],
) -> dict[str, dict[str, int]]:
    snapshots = {
        "host": progression.query_progression_snapshot(HOST_ENDPOINT),
        "client": progression.query_progression_snapshot(CLIENT_ENDPOINT),
    }
    ranks = {
        label: {
            str(row): int(snapshot["native"]["entries"][row]["active"])
            for row in rows
        }
        for label, snapshot in snapshots.items()
    }
    contaminated = {
        label: values
        for label, values in ranks.items()
        if any(rank != 0 for rank in values.values())
    }
    if contaminated:
        raise VerifyFailure(
            f"{tuple(rows)} behavior profile requires pristine ranks: "
            f"{contaminated}"
        )
    return ranks


def require_fixture_environment(
    pair: SteamFriendActivePair,
    *,
    require_wave: bool,
) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for label, endpoint in (("host", HOST_ENDPOINT), ("client", CLIENT_ENDPOINT)):
        values = parse_key_values(
            pair.lua(
                endpoint,
                """
local function emit(k,v) print(k .. '=' .. tostring(v or '')) end
emit('blank', sd.runtime.get_environment_variable('SDMOD_TEST_BLANK_BONEYARD'))
emit('boneyard', sd.runtime.get_environment_variable('SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE'))
emit('wave', sd.runtime.get_environment_variable('SDMOD_TEST_WAVE_OVERRIDE'))
""",
                timeout=8.0,
            )
        )
        checks = {
            "blank_boneyard": values.get("blank") == "1",
            "boneyard_override": bool(values.get("boneyard")),
            "wave_override": bool(values.get("wave")),
        }
        if not checks["blank_boneyard"] or not checks["boneyard_override"]:
            raise VerifyFailure(
                f"{label} is not using the explicit blank flat Boneyard fixture"
            )
        if require_wave and not checks["wave_override"]:
            raise VerifyFailure(
                f"{label} is not using the deterministic physical-wave fixture"
            )
        result[label] = checks
    return result


def staff_directions(
    pair: SteamFriendActivePair,
    context: BehaviorContext,
) -> tuple[Direction, Direction]:
    return (
        Direction(
            "host_owned",
            pair.host_participant_id,
            "Steam Host",
            HOST_ENDPOINT,
            context.host_log,
            0,
            CLIENT_ENDPOINT,
            context.client_log,
        ),
        Direction(
            "client_owned",
            pair.client_participant_id,
            "Steam Friend",
            CLIENT_ENDPOINT,
            context.client_log,
            0,
            HOST_ENDPOINT,
            context.host_log,
        ),
    )


def run_defense(timeout: float) -> dict[str, Any]:
    quiet = defense.enable_quiet_progression_test_mode()
    session = load_progression_inputs(timeout)
    session["quiet"] = quiet
    return {
        "resist_magic": defense.run_prepared_magic_stat_session(
            session,
            timeout,
        ),
        "deflect": defense.run_prepared_deflect_stat_session(
            session,
            timeout,
        ),
        "resist_poison": defense.run_prepared_poison_stat_session(
            session,
            timeout,
        ),
    }


def compact_summary(
    output: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    profile = output.get("profile")
    result: dict[str, Any] = {
        "ok": output.get("ok", False),
        "profile": profile,
        "active_step": output.get("active_step"),
        "error": output.get("error"),
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(output_path),
    }
    if profile == "defense":
        result["contracts"] = {
            name: output.get("matrix", {}).get(name, {}).get("contracts", {})
            for name in ("resist_magic", "deflect", "resist_poison")
        }
    elif profile == "staff":
        result["contracts"] = {
            "enchant": output.get("matrix", {}).get("enchant_contracts", {}),
            "fortunate": output.get("matrix", {}).get("fortunate_contracts", {}),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILE_ROWS), required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False, "profile": args.profile}
    return_code = 1
    try:
        output["active_step"] = "discover_pair"
        output["pair"] = pair.discover()
        require_shared_test_run(output["pair"])
        context = configure_behavior_context(pair)
        output["fixture"] = require_fixture_environment(
            pair,
            require_wave=args.profile == "staff",
        )
        output["initial_ranks"] = assert_pristine_rows(
            pair,
            PROFILE_ROWS[args.profile],
        )

        output["active_step"] = args.profile
        if args.profile == "defense":
            output["test_godmode"] = disable_runtime_test_godmode(pair)
            output["matrix"] = run_defense(args.timeout)
        else:
            output["manual_enemy_mode_release"] = {
                "host": disable_test_manual_enemy_mode(pair, HOST_ENDPOINT),
                "client": disable_test_manual_enemy_mode(pair, CLIENT_ENDPOINT),
            }
            quiet = staff.enable_quiet_progression_test_mode()
            session = load_progression_inputs(args.timeout)
            session["quiet"] = quiet
            output["matrix"] = staff.run_prepared_staff_matrix(
                staff_directions(pair, context),
                args.timeout,
                session,
            )

        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                f"new crash artifacts appeared during {args.profile} test"
            )
        output.pop("active_step", None)
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["error_type"] = type(exc).__name__
        output["traceback"] = traceback.format_exc()
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        pair.close()
        output = pair.redact(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(compact_summary(output, args.output), indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
