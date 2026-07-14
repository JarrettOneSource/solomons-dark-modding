#!/usr/bin/env python3
"""Verify upgraded spell behavior on an already-running Steam friend pair."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import multiplayer_progression_probe as progression
import verify_multiplayer_all_stat_sync as stats
import verify_multiplayer_all_upgrade_sync as upgrades
import verify_multiplayer_fireball_embers_effect_sync as embers
import verify_multiplayer_fireball_explode_effect_sync as explode
import verify_multiplayer_host_owned_level_up_sync as host_level
import verify_multiplayer_level_up_offer_sync as level
import verify_multiplayer_lightning_chaining_effect_sync as chaining
import verify_multiplayer_primary_kill_stress as primary
import verify_multiplayer_progression_catalog as catalog_probe
import verify_multiplayer_targeted_spell_matrix as targeted_spells
import verify_player_health_death_sync as health
import verify_real_input_spell_cast_sync as real_input
import verify_local_multiplayer_sync as local_verify
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_progression import (
    configure_verifiers,
    find_new_crash_artifacts,
)


DEFAULT_OUTPUT = ROOT / "runtime" / "steam_friend_active_pair_spell_behavior.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "steam-host-gameplay10")
CLIENT_INSTANCE = os.environ.get(
    "SDMOD_STEAM_CLIENT_INSTANCE", "wsl-steam-gameplay10"
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


def configure_behavior_modules(pair: SteamFriendActivePair) -> None:
    configure_verifiers(pair)
    modules = (
        progression,
        local_verify,
        upgrades,
        stats,
        catalog_probe,
        primary,
        real_input,
        health,
        level,
        host_level,
        targeted_spells,
        explode,
        embers,
        chaining,
    )
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "HOST_NAME": "Steam Host",
        "CLIENT_NAME": "Steam Friend",
        "HOST_LOG": HOST_LOG,
        "CLIENT_LOG": CLIENT_LOG,
    }
    for module in modules:
        if hasattr(module, "lua"):
            module.lua = pair.lua
        for name, value in replacements.items():
            if hasattr(module, name):
                setattr(module, name, value)


def direction(
    pair: SteamFriendActivePair,
    *,
    owner: str,
    behavior: str,
) -> real_input.Direction:
    if owner == "host":
        return real_input.Direction(
            f"steam_host_to_friend_{behavior}",
            pair.host_participant_id,
            "Steam Host",
            HOST_ENDPOINT,
            HOST_LOG,
            0,
            CLIENT_ENDPOINT,
            CLIENT_LOG,
        )
    return real_input.Direction(
        f"steam_friend_to_host_{behavior}",
        pair.client_participant_id,
        "Steam Friend",
        CLIENT_ENDPOINT,
        CLIENT_LOG,
        0,
        HOST_ENDPOINT,
        HOST_LOG,
    )


def ensure_upgrade_rank(
    pair: SteamFriendActivePair,
    *,
    participant_id: int,
    owner_endpoint: str,
    option_id: int,
    desired_rank: int,
    timeout: float = 30.0,
) -> dict[str, Any]:
    before = progression.query_progression_snapshot(owner_endpoint, timeout=8.0)
    row = before["native"]["entries"].get(option_id)
    if row is None:
        raise VerifyFailure(f"native progression row {option_id} is unavailable")
    active = int(row["active"])
    maximum = int(row["statbook_max_level"])
    if desired_rank > maximum:
        raise VerifyFailure(
            f"requested rank {desired_rank} exceeds native maximum {maximum} "
            f"for progression row {option_id}"
        )
    if active >= desired_rank:
        return {
            "action": "already_at_rank",
            "before_rank": active,
            "after_rank": active,
            "native_max_rank": maximum,
        }

    promotion_steps: list[dict[str, Any]] = []
    current_rank = active
    current = before
    while current_rank < desired_rank:
        target_level = int(current["native"]["level"]) + 1
        if target_level > upgrades.MAX_NATIVE_PROGRESSION_LEVEL:
            raise VerifyFailure(
                "cannot promote the behavior-test rank after exhausting the stock "
                f"level curve: option={option_id} current_level="
                f"{current['native']['level']}"
            )
        target_experience = int(
            math.ceil(current["native"]["next_xp_threshold"])
        )
        # The native deterministic-offer seam accepts at most two applications
        # in one skill-pick, matching the largest stock option payload.
        apply_count = min(2, desired_rank - current_rank)
        expected_rank = current_rank + apply_count
        published = upgrades.publish_deterministic_offer(
            participant_id,
            target_level,
            target_experience,
            option_id,
            apply_count=apply_count,
        )
        offer = upgrades.wait_for_offer(
            owner_endpoint,
            participant_id,
            target_level,
            option_id,
            timeout,
            apply_count=apply_count,
        )
        pause_active = upgrades.wait_for_pause(participant_id, True, timeout)
        choice = upgrades.choose_offer(
            owner_endpoint, offer["offer_id"], option_id
        )
        result = upgrades.wait_for_result(
            offer["offer_id"],
            participant_id,
            target_level,
            option_id,
            expected_rank,
            timeout,
            apply_count=apply_count,
        )
        parity = upgrades.wait_for_target_parity(
            participant_id,
            option_id,
            expected_rank,
            target_level,
            timeout,
        )
        pause_cleared = upgrades.wait_for_pause(
            participant_id, False, timeout
        )
        promotion_steps.append(
            {
                "before_rank": current_rank,
                "after_rank": expected_rank,
                "apply_count": apply_count,
                "target_level": target_level,
                "target_experience": target_experience,
                "publish": published,
                "offer": offer,
                "pause_active": pause_active,
                "choice": choice,
                "result": result,
                "parity": parity,
                "pause_cleared": pause_cleared,
            }
        )
        current_rank = expected_rank
        current = progression.query_progression_snapshot(
            owner_endpoint, timeout=8.0
        )
    return {
        "action": "authoritative_rank_promotion",
        "before_rank": active,
        "after_rank": desired_rank,
        "native_max_rank": maximum,
        "steps": promotion_steps,
    }


def verify_explode(pair: SteamFriendActivePair) -> dict[str, Any]:
    cast_direction = direction(pair, owner="host", behavior="fireball_explode")
    option_id = explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE]
    rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=pair.host_participant_id,
        owner_endpoint=HOST_ENDPOINT,
        option_id=option_id,
        desired_rank=1,
    )
    progression_views = {
        "owner": level.query_progression_entry(
            HOST_ENDPOINT, option_id=option_id
        ),
        "observer": level.query_progression_entry(
            CLIENT_ENDPOINT,
            option_id=option_id,
            participant_id=pair.host_participant_id,
        ),
    }
    for label, entry in progression_views.items():
        if int(entry["active"]) < 1 or int(entry["visible"]) < 1:
            raise VerifyFailure(
                f"{label} has no active native Explode rank: {entry}"
            )

    primary.cleanup_live_enemies()
    offset_search = explode.find_upgraded_explode_offset(
        cast_direction,
        candidate_offsets=list(explode.UPGRADED_OFFSET_CANDIDATES),
    )
    selected = offset_search["selected"]
    cast = selected["cast"]
    damage = cast["damage"]
    delivery = cast["replicated_cast_delivery"]
    impact_counts = {
        label: local_verify.parse_int_text(sample.get("call_count"), 0)
        for label, sample in cast["impact_trace"]["sample"].items()
    }
    if not damage["primary_damaged"] or not damage["secondary_damaged"]:
        raise VerifyFailure(
            f"Steam Explode did not damage both authority targets: {damage}"
        )
    if not delivery.get("ok") or any(count < 1 for count in impact_counts.values()):
        raise VerifyFailure(
            "Steam Explode did not execute the native impact path on both owner "
            f"and observer: delivery={delivery} impact_counts={impact_counts}"
        )
    return {
        "rank_setup": rank_setup,
        "progression": progression_views,
        "offset_search": offset_search,
        "summary": {
            "offset": [selected["offset_x"], selected["offset_y"]],
            "primary_damage": damage["primary_damage"],
            "secondary_damage": damage["secondary_damage"],
            "owner_observer_impact_counts": impact_counts,
            "replicated_cast_delivery": True,
        },
    }


def verify_embers(pair: SteamFriendActivePair) -> dict[str, Any]:
    cast_direction = direction(pair, owner="host", behavior="fireball_embers")
    explode_rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=pair.host_participant_id,
        owner_endpoint=HOST_ENDPOINT,
        option_id=explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE],
        desired_rank=1,
    )
    embers_rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=pair.host_participant_id,
        owner_endpoint=HOST_ENDPOINT,
        option_id=embers.EMBERS_OPTION_ID,
        desired_rank=1,
    )
    progression_views = embers.progression_views(cast_direction)
    for label, entry in progression_views.items():
        if int(entry["active"]) < 1 or int(entry["visible"]) < 1:
            raise VerifyFailure(f"{label} has no active native Embers rank: {entry}")

    prerequisite_views = {
        "owner": level.query_progression_entry(
            HOST_ENDPOINT,
            option_id=explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE],
        ),
        "observer": level.query_progression_entry(
            CLIENT_ENDPOINT,
            option_id=explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE],
            participant_id=pair.host_participant_id,
        ),
    }
    for label, entry in prerequisite_views.items():
        if int(entry["active"]) < 1 or int(entry["visible"]) < 1:
            raise VerifyFailure(
                f"{label} has no active native Explode prerequisite for Embers: "
                f"{entry}"
            )

    upgraded = embers.run_fragment_phase_with_impact_retry(
        cast_direction, "steam_upgraded"
    )
    expected = {
        "owner": embers.EXPECTED_LEVEL_ONE_FRAGMENTS,
        "observer": embers.EXPECTED_LEVEL_ONE_FRAGMENTS,
    }
    counts = upgraded["trace"]["fragment_counts"]
    if counts != expected:
        raise VerifyFailure(
            f"Steam Embers fragment count mismatch: expected={expected} actual={counts}"
        )
    effect_sync = upgraded["network_effect_sync"]
    if not effect_sync["capture"].get("ok") or not effect_sync["terminal"].get("ok"):
        raise VerifyFailure(f"Steam Embers lifecycle did not converge: {effect_sync}")

    forced = embers.run_fragment_phase_with_impact_retry(
        cast_direction,
        "steam_forced_materialization",
        force_observer_materialization=True,
    )
    forced_counts = forced["trace"]["fragment_counts"]
    materialized_count = int(
        forced["network_effect_sync"].get("materialized_count", 0)
    )
    if forced_counts != expected or materialized_count < embers.EXPECTED_LEVEL_ONE_FRAGMENTS:
        raise VerifyFailure(
            "Steam Embers fallback materialization was incomplete: "
            f"counts={forced_counts} materialized={materialized_count}"
        )
    return {
        "rank_setup": {
            "explode": explode_rank_setup,
            "embers": embers_rank_setup,
        },
        "progression": progression_views,
        "prerequisites": prerequisite_views,
        "upgraded": upgraded,
        "forced_materialization": forced,
        "summary": {
            "fragment_counts": counts,
            "forced_fragment_counts": forced_counts,
            "forced_materialization_count": materialized_count,
            "owner_observer_lifecycle_converged": True,
        },
    }


def positive_chaining_evidence(
    attempt: dict[str, Any], minimum_chain_targets: int
) -> dict[str, Any] | None:
    delivery = attempt["cast"].get("replicated_cast_delivery", {})
    air_sync = chaining.build_air_chain_sync_evidence(attempt)
    owner_count = chaining.dispatcher_chain_count(attempt, "owner")
    observer_count = chaining.dispatcher_chain_count(attempt, "observer")
    accepted_target_count = int(attempt["cast"]["accepted_target_count"])
    minimum_victim_count = minimum_chain_targets + 1
    valid = (
        delivery.get("ok")
        and accepted_target_count >= minimum_victim_count
        and owner_count >= minimum_chain_targets
        and observer_count >= minimum_chain_targets
        and air_sync["max_owner_target_count"] >= minimum_chain_targets
        and air_sync["max_observer_target_count"] >= minimum_chain_targets
        and air_sync["matching_frame_count"] > 0
        and air_sync["applied_target_parity"]
        and air_sync["source_override_success_delta"] > 0
        and air_sync["source_override_failure_delta"] == 0
        and air_sync["target_override_success_delta"] > 0
        and air_sync["target_override_failure_delta"] == 0
        and air_sync["applied_source_endpoint_parity"]
        and air_sync["applied_target_endpoint_parity"]
        and air_sync["endpoint_error_ok"]
        and air_sync["owner_terminal_seen"]
        and air_sync["observer_terminal_seen"]
    )
    if not valid:
        return None
    return {
        "offsets": attempt["offsets"],
        "accepted_target_count": accepted_target_count,
        "minimum_victim_count": minimum_victim_count,
        "owner_dispatcher_chain_count": owner_count,
        "observer_dispatcher_chain_count": observer_count,
        "air_chain_sync": air_sync,
    }


def verify_chaining(
    pair: SteamFriendActivePair,
    pattern_limit: int | None,
    minimum_chain_targets: int,
) -> dict[str, Any]:
    cast_direction = direction(pair, owner="client", behavior="lightning_chaining")
    rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=pair.client_participant_id,
        owner_endpoint=CLIENT_ENDPOINT,
        option_id=chaining.CHAINING_OPTION_ID,
        desired_rank=minimum_chain_targets,
    )
    progression_views = {
        "owner": level.query_progression_entry(
            CLIENT_ENDPOINT, option_id=chaining.CHAINING_OPTION_ID
        ),
        "observer": level.query_progression_entry(
            HOST_ENDPOINT,
            option_id=chaining.CHAINING_OPTION_ID,
            participant_id=pair.client_participant_id,
        ),
    }
    for label, entry in progression_views.items():
        if int(entry["active"]) < 1 or int(entry["visible"]) < 1:
            raise VerifyFailure(f"{label} has no active native Chaining rank: {entry}")

    native_outputs = {
        "owner": chaining.query_native_primary_outputs(CLIENT_ENDPOINT),
        "observer": chaining.query_native_primary_outputs(
            HOST_ENDPOINT, participant_id=pair.client_participant_id
        ),
    }
    pattern_search = chaining.run_pattern_search(
        cast_direction,
        phase="steam_upgraded",
        pattern_limit=pattern_limit,
        natural_cluster=False,
        scripted_manual_control=True,
    )
    evidence = next(
        (
            row
            for attempt in pattern_search["attempts"]
            if (
                row := positive_chaining_evidence(
                    attempt, minimum_chain_targets
                )
            )
            is not None
        ),
        None,
    )
    if evidence is None:
        diagnostics = [
            {
                "offsets": attempt["offsets"],
                "owner_dispatcher_chain_count": chaining.dispatcher_chain_count(
                    attempt, "owner"
                ),
                "observer_dispatcher_chain_count": chaining.dispatcher_chain_count(
                    attempt, "observer"
                ),
                "accepted_target_count": attempt["cast"]["accepted_target_count"],
                "air_chain_sync": chaining.build_air_chain_sync_evidence(attempt),
            }
            for attempt in pattern_search["attempts"]
        ]
        raise VerifyFailure(
            "Steam Chaining did not damage the primary plus every required chain "
            "target while executing the replicated multi-target loop on owner and "
            f"observer (minimum_chain_targets={minimum_chain_targets}): {diagnostics}"
        )
    return {
        "rank_setup": rank_setup,
        "progression": progression_views,
        "native_primary_outputs": native_outputs,
        "pattern_search": pattern_search,
        "summary": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--behavior",
        choices=("explode", "embers", "chaining", "all"),
        default="all",
    )
    parser.add_argument("--pattern-limit", type=int, default=1)
    parser.add_argument(
        "--minimum-chain-targets",
        type=int,
        default=4,
        help="minimum extra targets/arcs required on both owner and observer",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False, "behavior": args.behavior}
    return_code = 1
    try:
        output["pair"] = pair.discover()
        configure_behavior_modules(pair)
        if any(side["scene"] != "testrun" for side in output["pair"].values() if isinstance(side, dict) and "scene" in side):
            raise VerifyFailure(f"Steam friend pair is not in the shared test run: {output['pair']}")
        output["offer_drain"] = stats.drain_pending_natural_offers(30.0)
        manual_spawner_state = {
            "host": primary.manual_spawner_state(HOST_ENDPOINT),
            "client": primary.manual_spawner_state(CLIENT_ENDPOINT),
        }
        manual_spawner_ready = all(
            state.get("manual_mode") == "true"
            and state.get("has_spawner") == "true"
            for state in manual_spawner_state.values()
        )
        manual_combat_setup = (
            {
                "mode": "existing_manual_spawner",
                "state": manual_spawner_state,
            }
            if manual_spawner_ready
            else chaining.enable_flat_manual_cluster_combat()
        )
        output["manual_combat"] = {
            "mode": "active_pair_existing_run",
            "setup": manual_combat_setup,
            "cleanup": primary.cleanup_live_enemies(),
        }
        if args.behavior in ("explode", "all"):
            output["explode"] = verify_explode(pair)
        if args.behavior in ("embers", "all"):
            output["embers"] = verify_embers(pair)
        if args.behavior in ("chaining", "all"):
            output["chaining"] = verify_chaining(
                pair,
                args.pattern_limit,
                args.minimum_chain_targets,
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
        try:
            primary.clear_gameplay_mouse_left(HOST_ENDPOINT)
            primary.clear_gameplay_mouse_left(CLIENT_ENDPOINT)
        except Exception:
            pass
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
                "behavior": args.behavior,
                "explode": output.get("explode", {}).get("summary"),
                "embers": output.get("embers", {}).get("summary"),
                "chaining": output.get("chaining", {}).get("summary"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
