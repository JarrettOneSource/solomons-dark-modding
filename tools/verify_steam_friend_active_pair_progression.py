#!/usr/bin/env python3
"""Verify native skillbook replication on an already-running Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import multiplayer_progression_probe as progression
import verify_multiplayer_all_stat_sync as stats
import verify_multiplayer_all_upgrade_sync as upgrades
import verify_multiplayer_progression_catalog as catalog_probe
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure


DEFAULT_OUTPUT = ROOT / "runtime" / "steam_friend_active_pair_progression.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "steam-host-gameplay10")
CLIENT_INSTANCE = os.environ.get(
    "SDMOD_STEAM_CLIENT_INSTANCE", "wsl-steam-gameplay10"
)


def configure_verifiers(pair: SteamFriendActivePair) -> None:
    host_id = pair.host_participant_id
    client_id = pair.client_participant_id
    progression.lua = pair.lua
    upgrades.lua = pair.lua
    stats.lua = pair.lua
    for module in (catalog_probe, upgrades, stats):
        module.HOST_ID = host_id
        module.CLIENT_ID = client_id
        module.HOST_PIPE = HOST_ENDPOINT
        module.CLIENT_PIPE = CLIENT_ENDPOINT


def parse_entries(text: str | None, real_count: int) -> list[int]:
    if text is None:
        return list(range(real_count))
    return upgrades.parse_entry_filter(text, real_count)


def compact_catalog(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_count": result["config_count"],
        "native_entry_count": result["native_entry_count"],
        "real_skill_row_count": result["real_skill_row_count"],
        "structural_tail_count": result["structural_tail_count"],
        "parity": result["parity"],
        "skills": [
            {
                "entry_index": row["entry_index"],
                "skill_file": row["skill_file"],
                "skill_name": row["skill_name"],
                "category": row["category"],
                "native_max_level": row["native_max_level"],
            }
            for row in result["catalog"]
        ],
    }


def find_new_crash_artifacts(started_at: float) -> list[str]:
    locations = (
        ROOT / "runtime/instances" / HOST_INSTANCE / "stage/.sdmod/logs",
        ROOT / "runtime/instances" / CLIENT_INSTANCE / "stage/.sdmod/logs",
        Path("/mnt/c/Users/user/AppData/Local/CrashDumps"),
    )
    artifacts: list[str] = []
    for location in locations:
        if not location.is_dir():
            continue
        for path in location.glob("*crash*"):
            if path.is_file() and path.stat().st_mtime >= started_at - 0.5:
                artifacts.append(str(path))
        for path in location.glob("SolomonDark.exe*.dmp"):
            if path.is_file() and path.stat().st_mtime >= started_at - 0.5:
                artifacts.append(str(path))
    return sorted(set(artifacts))


def run_stats_phase(
    catalog: list[dict[str, Any]],
    pair: SteamFriendActivePair,
    timeout: float,
    output: dict[str, Any],
) -> None:
    output["quiet_progression_test_mode"] = (
        upgrades.enable_quiet_progression_test_mode()
    )
    output["pre_matrix_offer_drain"] = stats.drain_pending_natural_offers(timeout)
    output["post_run_progression_ready"] = (
        upgrades.wait_for_post_run_progression_ready(timeout)
    )

    initial_by_target = {
        pair.host_participant_id: progression.query_progression_snapshot(
            HOST_ENDPOINT
        ),
        pair.client_participant_id: progression.query_progression_snapshot(
            CLIENT_ENDPOINT
        ),
    }
    output["initial"] = {
        "host": stats.compact_snapshot(
            initial_by_target[pair.host_participant_id]
        ),
        "client": stats.compact_snapshot(
            initial_by_target[pair.client_participant_id]
        ),
    }
    for target_id in (pair.host_participant_id, pair.client_participant_id):
        owner, observer = stats.wait_for_derived_parity(target_id, timeout)
        mismatches = stats.derived_mismatches(owner, observer)
        if mismatches:
            raise VerifyFailure(
                f"initial derived stat parity failed target={target_id}: {mismatches}"
            )

    config_root = (
        ROOT
        / "runtime/instances"
        / HOST_INSTANCE
        / "stage/data/wizardskills"
    )
    contract_values = stats.load_stat_contract_values(
        catalog,
        config_root=config_root,
    )
    output["stat_contract_values"] = contract_values
    output["baseline_secondary_costs"] = stats.capture_secondary_cost_matrix()
    output["baseline_secondary_cost_parity"] = stats.verify_secondary_cost_parity(
        output["baseline_secondary_costs"]
    )
    output["baseline_mana_recovery"] = {
        "host": stats.sample_mana_recovery(pair.host_participant_id),
        "client": stats.sample_mana_recovery(pair.client_participant_id),
    }

    client_creativity = int(
        initial_by_target[pair.client_participant_id]["native"]["entries"][63][
            "active"
        ]
    )
    output["creativity_baseline_client"] = stats.exercise_natural_offer(
        pair.client_participant_id,
        4 if client_creativity > 0 else 3,
        timeout,
    )

    matrix: dict[str, Any] = {
        "stat_rows": list(stats.STAT_ROWS),
        "completed_step_count": 0,
        "steps": [],
    }
    output["matrix"] = matrix
    stats.run_stat_matrix(
        catalog,
        initial_by_target,
        contract_values,
        timeout,
        matrix,
    )

    output["creativity_upgraded"] = {
        "client": stats.exercise_natural_offer(
            pair.client_participant_id,
            4,
            timeout,
        ),
        "host": stats.exercise_natural_offer(
            pair.host_participant_id,
            4,
            timeout,
        ),
    }
    output["post_creativity_offer_drain"] = (
        stats.drain_pending_natural_offers(timeout)
    )
    output["final"] = stats.verify_final_maxima(
        catalog,
        initial_by_target,
        contract_values,
        timeout,
    )
    output["final_ranked_property_matrix"] = (
        stats.verify_ranked_property_matrix(catalog, contract_values)
    )
    output["final_secondary_costs"] = stats.capture_secondary_cost_matrix()
    output["final_secondary_cost_parity"] = stats.verify_secondary_cost_parity(
        output["final_secondary_costs"]
    )
    output["final_mana_recovery"] = {
        "host": stats.sample_mana_recovery(pair.host_participant_id),
        "client": stats.sample_mana_recovery(pair.client_participant_id),
    }
    for label in ("host", "client"):
        baseline_gain = float(output["baseline_mana_recovery"][label]["gain"])
        final_gain = float(output["final_mana_recovery"][label]["gain"])
        if final_gain <= baseline_gain + 0.5:
            raise VerifyFailure(
                f"{label} max Channel/Meditation did not improve live mana "
                f"recovery: baseline={baseline_gain:.3f} final={final_gain:.3f}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", choices=("catalog", "upgrades", "stats"), default="catalog"
    )
    parser.add_argument("--entries", help="comma-separated rows/ranges")
    parser.add_argument(
        "--directions", choices=("both", "client", "host"), default="both"
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False, "phase": args.phase}
    return_code = 1
    try:
        output["pair"] = pair.discover()
        configure_verifiers(pair)
        views = catalog_probe.wait_for_catalog_views(args.timeout)
        catalog = catalog_probe.build_and_verify_catalog(
            views, catalog_probe.load_skill_configs()
        )
        output["catalog"] = compact_catalog(catalog)
        if args.phase == "upgrades":
            output["quiet_progression_test_mode"] = (
                upgrades.enable_quiet_progression_test_mode()
            )
            output["pre_matrix_offer_drain"] = stats.drain_pending_natural_offers(
                args.timeout
            )
            output["post_run_progression_ready"] = (
                upgrades.wait_for_post_run_progression_ready(args.timeout)
            )
            matrix: dict[str, Any] = {}
            output["matrix"] = matrix
            upgrades.run_matrix(
                catalog["catalog"],
                parse_entries(args.entries, catalog["real_skill_row_count"]),
                args.directions,
                args.timeout,
                matrix,
            )
        elif args.phase == "stats":
            run_stats_phase(
                catalog["catalog"],
                pair,
                args.timeout,
                output,
            )
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                f"new crash artifacts appeared: {output['new_crash_artifacts']}"
            )
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        pair.close()
        output = pair.redact(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    matrix = output.get("matrix", {})
    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "phase": args.phase,
                "completed_step_count": matrix.get("completed_step_count", 0),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
