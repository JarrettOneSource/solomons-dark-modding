#!/usr/bin/env python3
"""Verify gameplay state on an already-running two-account Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import multiplayer_transient_status_harness as transient_harness
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_all_stat_sync as stats
import verify_multiplayer_all_upgrade_sync as upgrades
import verify_multiplayer_animation_mana_elements as animation
import verify_multiplayer_inventory_audit as inventory
import verify_multiplayer_transient_status_sync as transient
import verify_player_health_death_sync as health
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_real_input_spell_cast_sync import Direction
from verify_steam_friend_active_pair_progression import (
    configure_verifiers,
    find_new_crash_artifacts,
)


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_state.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "steam-host-gameplay12")
CLIENT_INSTANCE = os.environ.get(
    "SDMOD_STEAM_CLIENT_INSTANCE", "wsl-steam-gameplay12"
)
HOST_LOG = (
    ROOT
    / "runtime/instances"
    / HOST_INSTANCE
    / "stage/.sdmod/logs/solomondarkmodloader.log"
)
CLIENT_LOG = (
    ROOT
    / "runtime/instances"
    / CLIENT_INSTANCE
    / "stage/.sdmod/logs/solomondarkmodloader.log"
)


def set_module_endpoint(module: Any, name: str, value: Any) -> None:
    if hasattr(module, name):
        setattr(module, name, value)


def configure_modules(pair: SteamFriendActivePair) -> dict[str, str]:
    configure_verifiers(pair)
    modules = (
        local_sync,
        health,
        stats,
        upgrades,
        animation,
        inventory,
        transient,
        transient_harness,
    )
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "lua": pair.lua,
    }
    for module in modules:
        for name, value in replacements.items():
            set_module_endpoint(module, name, value)

    host_view = local_sync.query(HOST_ENDPOINT)
    client_view = local_sync.query(CLIENT_ENDPOINT)
    client_name = host_view.get(
        f"peer.{pair.client_participant_id}.name", "Steam Friend"
    )
    host_name = client_view.get(
        f"peer.{pair.host_participant_id}.name", "Steam Host"
    )
    local_sync.HOST_NAME = host_name
    local_sync.CLIENT_NAME = client_name
    health.HOST_NAME = host_name
    health.CLIENT_NAME = client_name
    animation.HOST_NAME = host_name
    animation.CLIENT_NAME = client_name

    transient.DIRECTIONS = (
        transient.Direction(
            "host_owned",
            pair.host_participant_id,
            pair.client_participant_id,
            HOST_ENDPOINT,
            CLIENT_ENDPOINT,
        ),
        transient.Direction(
            "client_owned",
            pair.client_participant_id,
            pair.host_participant_id,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
        ),
    )
    return {"host": host_name, "client": client_name}


def direction(
    pair: SteamFriendActivePair,
    names: dict[str, str],
    *,
    owner: str,
) -> Direction:
    if owner == "host":
        return Direction(
            "steam_host_to_friend",
            pair.host_participant_id,
            names["host"],
            HOST_ENDPOINT,
            HOST_LOG,
            0,
            CLIENT_ENDPOINT,
            CLIENT_LOG,
        )
    return Direction(
        "steam_friend_to_host",
        pair.client_participant_id,
        names["client"],
        CLIENT_ENDPOINT,
        CLIENT_LOG,
        0,
        HOST_ENDPOINT,
        HOST_LOG,
    )


def verify_inventory_boundary(pair: SteamFriendActivePair) -> dict[str, Any]:
    captured = inventory.capture_pair()
    boundary = inventory.assert_multiplayer_boundary(
        captured["host"], captured["client"]
    )
    books = {
        "host": inventory.assert_progression_book_shape(
            "host", captured["host"]
        ),
        "client": inventory.assert_progression_book_shape(
            "client", captured["client"]
        ),
    }
    return {
        "host_observes_client": boundary["host_view_client"],
        "client_observes_host": boundary["client_view_host"],
        "local_book_entry_counts": {
            side: book["entry_count"] for side, book in books.items()
        },
        "expected_participants": [
            pair.host_participant_id,
            pair.client_participant_id,
        ],
    }


def compact_scene(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene": result["scene"],
        "host_remote_render_selector": result["host_remote_render_selector"],
        "client_remote_render_selector": result["client_remote_render_selector"],
        "host_remote_visual_lane_types": result["host_remote_visual_lane_types"],
        "client_remote_visual_lane_types": result["client_remote_visual_lane_types"],
        "host_motion": {
            "owner": result["host_moved_to"],
            "observer": result["client_observed_host_settled"],
        },
        "client_motion": {
            "owner": result["client_moved_to"],
            "observer": result["host_observed_client_settled"],
        },
        "participant_overlap": result["participant_overlap"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["pair"] = pair.discover()
        if any(
            side.get("scene") != "testrun"
            for side in output["pair"].values()
            if isinstance(side, dict) and "scene" in side
        ):
            raise VerifyFailure(
                f"Steam friend pair is not in the shared test run: {output['pair']}"
            )
        names = configure_modules(pair)
        output["offer_drain"] = stats.drain_pending_natural_offers(args.timeout)
        output["progression_ready"] = upgrades.wait_for_post_run_progression_ready(
            args.timeout
        )

        scene = local_sync.verify_scene("testrun")
        output["presentation_transform"] = compact_scene(scene)
        output["animation"] = {
            owner: animation.verify_animation_field_replication(
                direction(pair, names, owner=owner)
            )
            for owner in ("host", "client")
        }
        output["status_resources"] = {
            "host": health.set_local_player_vitals(
                HOST_ENDPOINT, 1000.0, 1000.0
            ),
            "client": health.set_local_player_vitals(
                CLIENT_ENDPOINT, 1000.0, 1000.0
            ),
        }
        output["transient_status"] = {
            item.name: transient.run_direction(item, args.timeout)
            for item in transient.DIRECTIONS
        }
        output["host_mirror_owner_correction"] = (
            transient.run_host_mirror_owner_correction(args.timeout)
        )
        output["derived_stats"] = {
            label: {
                "owner": stats.compact_snapshot(owner),
                "observer": stats.compact_snapshot(observer),
                "mismatches": stats.derived_mismatches(owner, observer),
            }
            for label, target in (
                ("host_owned", pair.host_participant_id),
                ("client_owned", pair.client_participant_id),
            )
            for owner, observer in [stats.wait_for_derived_parity(target, args.timeout)]
        }
        secondary_costs = stats.capture_secondary_cost_matrix()
        output["secondary_cost_parity"] = stats.verify_secondary_cost_parity(
            secondary_costs
        )
        output["inventory_boundary"] = verify_inventory_boundary(pair)

        # Forced owner HP-zero drives the stock local actor into its corpse
        # state. Positive HP proves that the remote representation recovers,
        # but it does not invoke a native local-player revive. Keep this
        # destructive check last so it cannot silently invalidate the cast,
        # status, or stat checks above it.
        vitals_recovery = {
            "host_owned": health.verify_one_direction(
                owner_pipe=HOST_ENDPOINT,
                owner_name="host",
                observer_pipe=CLIENT_ENDPOINT,
                participant_id=pair.host_participant_id,
            ),
            "client_owned": health.verify_one_direction(
                owner_pipe=CLIENT_ENDPOINT,
                owner_name="client",
                observer_pipe=HOST_ENDPOINT,
                participant_id=pair.client_participant_id,
            ),
        }
        output["vitals_remote_death_recovery"] = vitals_recovery
        output["post_suite_scene_reset_required"] = any(
            bool(result["owner_gameplay_actor_requires_scene_reset"])
            for result in vitals_recovery.values()
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

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "checks": {
                    "presentation_transform": "presentation_transform" in output,
                    "animation": "animation" in output,
                    "vitals_remote_death_recovery": (
                        "vitals_remote_death_recovery" in output
                    ),
                    "transient_status": "transient_status" in output,
                    "derived_stats": "derived_stats" in output,
                    "secondary_cost_parity": "secondary_cost_parity" in output,
                    "inventory_boundary": "inventory_boundary" in output,
                },
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
