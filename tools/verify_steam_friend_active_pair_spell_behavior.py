#!/usr/bin/env python3
"""Verify upgraded spell behavior on an already-running Steam friend pair."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import multiplayer_progression_probe as progression
import verify_multiplayer_all_stat_sync as stats
import verify_multiplayer_all_upgrade_sync as upgrades
import verify_multiplayer_animation_mana_elements as animation
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
FIRE_PRIMARY_SPELL_ID = 1011
AIR_PRIMARY_SPELL_ID = 1013
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()
CLIENT_INSTANCE = os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()
HOST_LOG = Path(
    os.environ.get(
        "SDMOD_STEAM_HOST_LOG_PATH",
        ROOT
        / "runtime/instances"
        / HOST_INSTANCE
        / "stage/.sdmod/logs/solomondarkmodloader.log",
    )
)
CLIENT_LOG = Path(
    os.environ.get(
        "SDMOD_STEAM_CLIENT_LOG_PATH",
        ROOT
        / "runtime/instances"
        / CLIENT_INSTANCE
        / "stage/.sdmod/logs/solomondarkmodloader.log",
    )
)
NATIVE_DEATH_PRESENTER_PREFIX = "native enemy death presenter invoked."
NATIVE_DEATH_PRESENTER_RESULT = re.compile(
    r"\bcalled=(?P<called>[01])\s+seh=0x(?P<seh>[0-9A-Fa-f]+)\b"
)


def capture_log_offsets() -> dict[str, int]:
    return {
        "host": HOST_LOG.stat().st_size,
        "client": CLIENT_LOG.stat().st_size,
    }


def read_log_suffix(path: Path, offset: int) -> str:
    with path.open("rb") as stream:
        if stream.seek(0, os.SEEK_END) < offset:
            offset = 0
        stream.seek(offset)
        return stream.read().decode("utf-8", errors="replace")


def verify_native_death_presenter_results(
    offsets: dict[str, int],
    timeout: float = 8.0,
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while True:
        results: dict[str, dict[str, Any]] = {}
        failed: dict[str, list[dict[str, Any]]] = {}
        for label, path in (("host", HOST_LOG), ("client", CLIENT_LOG)):
            lines = [
                line
                for line in read_log_suffix(path, offsets[label]).splitlines()
                if NATIVE_DEATH_PRESENTER_PREFIX in line
            ]
            outcomes: list[dict[str, Any]] = []
            for line in lines:
                match = NATIVE_DEATH_PRESENTER_RESULT.search(line)
                if match is None:
                    outcomes.append({"called": None, "seh": None})
                    continue
                outcomes.append(
                    {
                        "called": int(match.group("called")),
                        "seh": f"0x{int(match.group('seh'), 16):X}",
                    }
                )
            failures = [
                outcome
                for outcome in outcomes
                if outcome["called"] != 1 or outcome["seh"] != "0x0"
            ]
            results[label] = {
                "event_count": len(outcomes),
                "failed_count": len(failures),
                "outcomes": outcomes,
            }
            if failures:
                failed[label] = failures

        if failed:
            raise VerifyFailure(
                "native enemy-death presentation failed during Lua cleanup: "
                f"{failed}"
            )
        missing = [
            label
            for label, result in results.items()
            if result["event_count"] == 0
        ]
        if not missing:
            return results
        if time.monotonic() >= deadline:
            raise VerifyFailure(
                "post-behavior Lua cleanup produced no native enemy-death "
                f"presenter witness on: {missing}"
            )
        time.sleep(0.05)


def configure_behavior_modules(pair: SteamFriendActivePair) -> None:
    if not HOST_INSTANCE or not CLIENT_INSTANCE:
        raise VerifyFailure("both Steam instance environment variables are required")
    for log_path in (HOST_LOG, CLIENT_LOG):
        if not log_path.is_file():
            raise VerifyFailure(f"Steam behavior log does not exist: {log_path}")

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
        animation,
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


def owner_context(
    pair: SteamFriendActivePair,
    owner: str,
) -> tuple[int, str, str]:
    if owner == "host":
        return pair.host_participant_id, HOST_ENDPOINT, CLIENT_ENDPOINT
    if owner == "client":
        return pair.client_participant_id, CLIENT_ENDPOINT, HOST_ENDPOINT
    raise ValueError(f"unknown spell-behavior owner: {owner}")


def require_primary_spell(
    owner_endpoint: str,
    *,
    expected_spell_id: int,
    behavior: str,
) -> dict[str, int]:
    snapshot = progression.query_progression_snapshot(owner_endpoint, timeout=8.0)
    current_spell_id = int(snapshot["spell"]["current_spell_id"])
    if current_spell_id != expected_spell_id:
        raise VerifyFailure(
            f"{behavior} requires primary spell {expected_spell_id}, "
            f"but the owner has {current_spell_id}"
        )
    return {
        "current_spell_id": current_spell_id,
        "primary_entry": int(snapshot["loadout"]["primary_entry"]),
        "combo_entry": int(snapshot["loadout"]["combo_entry"]),
    }


def select_matching_owners(
    owner_labels: tuple[tuple[str, str], ...],
    primary_spell_ids: dict[str, int],
    *,
    expected_spell_id: int,
    behavior: str,
) -> tuple[tuple[str, str], ...]:
    matching = tuple(
        row
        for row in owner_labels
        if primary_spell_ids.get(row[1]) == expected_spell_id
    )
    if not matching:
        raise VerifyFailure(
            f"{behavior} has no requested owner with primary spell "
            f"{expected_spell_id}: {primary_spell_ids}"
        )
    return matching


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


def verify_explode(
    pair: SteamFriendActivePair,
    *,
    owner: str,
) -> dict[str, Any]:
    participant_id, owner_endpoint, observer_endpoint = owner_context(pair, owner)
    cast_direction = direction(pair, owner=owner, behavior="fireball_explode")
    primary_precondition = require_primary_spell(
        owner_endpoint,
        expected_spell_id=FIRE_PRIMARY_SPELL_ID,
        behavior="Fireball Explode",
    )
    option_id = explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE]
    rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=participant_id,
        owner_endpoint=owner_endpoint,
        option_id=option_id,
        desired_rank=1,
    )
    progression_views = {
        "owner": level.query_progression_entry(
            owner_endpoint, option_id=option_id
        ),
        "observer": level.query_progression_entry(
            observer_endpoint,
            option_id=option_id,
            participant_id=participant_id,
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
        "primary_precondition": primary_precondition,
        "rank_setup": rank_setup,
        "progression": progression_views,
        "offset_search": offset_search,
        "summary": {
            "owner": owner,
            "offset": [selected["offset_x"], selected["offset_y"]],
            "primary_damage": damage["primary_damage"],
            "secondary_damage": damage["secondary_damage"],
            "owner_observer_impact_counts": impact_counts,
            "replicated_cast_delivery": True,
        },
    }


def verify_embers(
    pair: SteamFriendActivePair,
    *,
    owner: str,
) -> dict[str, Any]:
    participant_id, owner_endpoint, observer_endpoint = owner_context(pair, owner)
    cast_direction = direction(pair, owner=owner, behavior="fireball_embers")
    primary_precondition = require_primary_spell(
        owner_endpoint,
        expected_spell_id=FIRE_PRIMARY_SPELL_ID,
        behavior="Fireball Embers",
    )
    explode_rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=participant_id,
        owner_endpoint=owner_endpoint,
        option_id=explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE],
        desired_rank=1,
    )
    embers_rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=participant_id,
        owner_endpoint=owner_endpoint,
        option_id=embers.EMBERS_OPTION_ID,
        desired_rank=1,
    )
    progression_views = embers.progression_views(cast_direction)
    for label, entry in progression_views.items():
        if int(entry["active"]) < 1 or int(entry["visible"]) < 1:
            raise VerifyFailure(f"{label} has no active native Embers rank: {entry}")

    prerequisite_views = {
        "owner": level.query_progression_entry(
            owner_endpoint,
            option_id=explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE],
        ),
        "observer": level.query_progression_entry(
            observer_endpoint,
            option_id=explode.TARGET_OPTION_IDS[explode.TARGET_SKILL_FILE],
            participant_id=participant_id,
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

    authoritative_materialization = embers.run_fragment_phase_with_impact_retry(
        cast_direction,
        "steam_authoritative_materialization",
        force_observer_materialization=True,
    )
    materialized_counts = authoritative_materialization["trace"]["fragment_counts"]
    materialized_count = int(
        authoritative_materialization["network_effect_sync"].get(
            "materialized_count", 0
        )
    )
    if (
        materialized_counts != expected
        or materialized_count < embers.EXPECTED_LEVEL_ONE_FRAGMENTS
    ):
        raise VerifyFailure(
            "Steam Embers authoritative snapshot materialization was incomplete: "
            f"counts={materialized_counts} materialized={materialized_count}"
        )
    return {
        "primary_precondition": primary_precondition,
        "rank_setup": {
            "explode": explode_rank_setup,
            "embers": embers_rank_setup,
        },
        "progression": progression_views,
        "prerequisites": prerequisite_views,
        "upgraded": upgraded,
        "authoritative_materialization": authoritative_materialization,
        "summary": {
            "owner": owner,
            "fragment_counts": counts,
            "materialized_fragment_counts": materialized_counts,
            "authoritative_materialization_count": materialized_count,
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
    *,
    owner: str,
    pattern_limit: int | None,
    minimum_chain_targets: int,
) -> dict[str, Any]:
    participant_id, owner_endpoint, observer_endpoint = owner_context(pair, owner)
    cast_direction = direction(pair, owner=owner, behavior="lightning_chaining")
    primary_precondition = require_primary_spell(
        owner_endpoint,
        expected_spell_id=AIR_PRIMARY_SPELL_ID,
        behavior="Air Chaining",
    )
    rank_setup = ensure_upgrade_rank(
        pair,
        participant_id=participant_id,
        owner_endpoint=owner_endpoint,
        option_id=chaining.CHAINING_OPTION_ID,
        desired_rank=minimum_chain_targets,
    )
    progression_views = {
        "owner": level.query_progression_entry(
            owner_endpoint, option_id=chaining.CHAINING_OPTION_ID
        ),
        "observer": level.query_progression_entry(
            observer_endpoint,
            option_id=chaining.CHAINING_OPTION_ID,
            participant_id=participant_id,
        ),
    }
    for label, entry in progression_views.items():
        if int(entry["active"]) < 1 or int(entry["visible"]) < 1:
            raise VerifyFailure(f"{label} has no active native Chaining rank: {entry}")

    native_outputs = {
        "owner": chaining.query_native_primary_outputs(owner_endpoint),
        "observer": chaining.query_native_primary_outputs(
            observer_endpoint, participant_id=participant_id
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
        "primary_precondition": primary_precondition,
        "rank_setup": rank_setup,
        "progression": progression_views,
        "native_primary_outputs": native_outputs,
        "pattern_search": pattern_search,
        "summary": {"owner": owner, **evidence},
    }


def verify_targetless_air(
    pair: SteamFriendActivePair,
    *,
    owner: str,
) -> dict[str, Any]:
    _, owner_endpoint, _ = owner_context(pair, owner)
    cast_direction = direction(pair, owner=owner, behavior="targetless_air")
    primary_precondition = require_primary_spell(
        owner_endpoint,
        expected_spell_id=AIR_PRIMARY_SPELL_ID,
        behavior="Targetless Air",
    )
    cleanup = primary.cleanup_live_enemies()
    if local_verify.parse_int_text(cleanup.get("after.live_enemy_count"), -1) != 0:
        raise VerifyFailure(
            f"Targetless Air arena still contains a live enemy: {cleanup}"
        )

    cast = animation.verify_continuous_cast(
        cast_direction,
        animation.ELEMENT_BY_NAME["air"],
    )
    flow = cast["flow"]
    native_sequences = set(flow["native_sequences"])
    witnesses = {
        "local_targetless": set(flow["local_targetless_sequences"]),
        "remote_targetless_queue": set(
            flow["remote_targetless_queue_sequences"]
        ),
        "remote_prepared": set(flow["remote_prep_sequences"]),
        "remote_released": set(flow["remote_release_sequences"]),
    }
    missing = {
        label: sorted(native_sequences - sequences)
        for label, sequences in witnesses.items()
        if not native_sequences.issubset(sequences)
    }
    if missing:
        raise VerifyFailure(
            "Targetless Air did not complete the native remote cast lifecycle: "
            f"missing={missing} flow={flow}"
        )
    if not cast["active_seen"] or not cast["anim_seen"]:
        raise VerifyFailure(
            "Targetless Air did not become a visible active cast on the remote "
            f"participant: active={cast['active_seen']} anim={cast['anim_seen']}"
        )
    return {
        "primary_precondition": primary_precondition,
        "cleanup": cleanup,
        "cast": cast,
        "summary": {
            "owner": owner,
            "native_sequences": sorted(native_sequences),
            "remote_native_cast_active": True,
            "remote_animation_active": True,
            "target_network_actor_id": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--behavior",
        choices=("explode", "embers", "chaining", "targetless-air", "all"),
        default="all",
    )
    parser.add_argument(
        "--owners",
        choices=("both", "host", "client"),
        default="both",
        help="limit behavior casts to owners whose native primary matches the test",
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
        presenter_log_offsets = capture_log_offsets()
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
        owner_labels = (("host_owned", "host"), ("client_owned", "client"))
        if args.owners != "both":
            owner_labels = tuple(
                row for row in owner_labels if row[1] == args.owners
            )
        primary_spell_ids = {
            owner: int(
                progression.query_progression_snapshot(
                    owner_context(pair, owner)[1],
                    timeout=8.0,
                )["spell"]["current_spell_id"]
            )
            for _, owner in owner_labels
        }
        output["owner_primary_spells"] = primary_spell_ids
        fire_owner_labels = (
            select_matching_owners(
                owner_labels,
                primary_spell_ids,
                expected_spell_id=FIRE_PRIMARY_SPELL_ID,
                behavior="Fire behavior",
            )
            if args.behavior in ("explode", "embers", "all")
            else ()
        )
        air_owner_labels = (
            select_matching_owners(
                owner_labels,
                primary_spell_ids,
                expected_spell_id=AIR_PRIMARY_SPELL_ID,
                behavior="Air behavior",
            )
            if args.behavior in ("chaining", "targetless-air", "all")
            else ()
        )
        if args.behavior in ("targetless-air", "all"):
            output["targetless_air"] = {}
            for label, owner in air_owner_labels:
                output["active_step"] = f"targetless_air.{label}"
                output["targetless_air"][label] = verify_targetless_air(
                    pair,
                    owner=owner,
                )
        if args.behavior in ("explode", "all"):
            output["explode"] = {}
            for label, owner in fire_owner_labels:
                output["active_step"] = f"explode.{label}"
                output["explode"][label] = verify_explode(pair, owner=owner)
        if args.behavior in ("embers", "all"):
            output["embers"] = {}
            for label, owner in fire_owner_labels:
                output["active_step"] = f"embers.{label}"
                output["embers"][label] = verify_embers(pair, owner=owner)
        if args.behavior in ("chaining", "all"):
            output["chaining"] = {}
            for label, owner in air_owner_labels:
                output["active_step"] = f"chaining.{label}"
                output["chaining"][label] = verify_chaining(
                    pair,
                    owner=owner,
                    pattern_limit=args.pattern_limit,
                    minimum_chain_targets=args.minimum_chain_targets,
                )
        if args.behavior != "targetless-air":
            output["post_behavior_cleanup"] = primary.cleanup_live_enemies()
            if local_verify.parse_int_text(
                output["post_behavior_cleanup"].get("cleaned"), 0
            ) < 1:
                raise VerifyFailure(
                    "spell behavior left no durable enemy for the Lua "
                    "death-presenter regression witness"
                )
            output["native_enemy_death_presenter"] = (
                verify_native_death_presenter_results(presenter_log_offsets)
            )
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                f"new crash artifacts appeared: {output['new_crash_artifacts']}"
            )
        output["ok"] = True
        output.pop("active_step", None)
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["error_type"] = type(exc).__name__
        output["traceback"] = traceback.format_exc()
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
                "explode": {
                    label: result.get("summary")
                    for label, result in output.get("explode", {}).items()
                },
                "embers": {
                    label: result.get("summary")
                    for label, result in output.get("embers", {}).items()
                },
                "chaining": {
                    label: result.get("summary")
                    for label, result in output.get("chaining", {}).items()
                },
                "targetless_air": {
                    label: result.get("summary")
                    for label, result in output.get("targetless_air", {}).items()
                },
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
