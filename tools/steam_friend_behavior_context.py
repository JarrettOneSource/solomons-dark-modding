#!/usr/bin/env python3
"""Shared configuration for behavior tests on an active Steam friend pair."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import multiplayer_defense_behavior_harness as defense_harness
import multiplayer_natural_defense_harness as natural_defense_harness
import multiplayer_persistent_status_harness as persistent_harness
import multiplayer_progression_probe as progression
import multiplayer_staff_behavior_harness as staff_harness
import multiplayer_transient_status_harness as transient_harness
import multiplayer_webbed_status_harness as webbed_harness
import probe_run_reward_sync as rewards
import verify_flat_multiplayer_boneyard as flat_boneyard
import verify_local_multiplayer_sync as local_verify
import verify_multiplayer_all_stat_sync as stats
import verify_multiplayer_all_upgrade_sync as upgrades
import verify_multiplayer_battle_siege_behavior_sync as battle_siege
import verify_multiplayer_defense_behavior_sync as defense
import verify_multiplayer_faster_caster_behavior_sync as faster_caster
import verify_multiplayer_fireball_embers_effect_sync as embers
import verify_multiplayer_fireball_explode_effect_sync as explode
import verify_multiplayer_focus_behavior_sync as focus
import verify_multiplayer_gold_pickup_authority as pickup_authority
import verify_multiplayer_meditation_behavior_sync as meditation
import verify_multiplayer_mindstar_behavior_sync as mindstar
import verify_multiplayer_persistent_status_sync as persistent
import verify_multiplayer_primary_kill_stress as primary
import verify_multiplayer_progression_catalog as catalog_probe
import verify_multiplayer_rush_behavior_sync as rush
import verify_multiplayer_staff_stat_behavior_sync as staff
import verify_multiplayer_telekinesis_behavior_sync as telekinesis
import verify_multiplayer_transient_status_sync as transient
import verify_multiplayer_webbed_status_sync as webbed
import verify_player_health_death_sync as health
import verify_real_input_spell_cast_sync as real_input
import verify_spell_cast_sync as spell_cast
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_steam_friend_active_pair_progression import configure_verifiers
from verify_steam_friend_active_pair_progression import steam_skill_config_root


HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()
CLIENT_INSTANCE = os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()


@dataclass(frozen=True)
class BehaviorContext:
    pair: SteamFriendActivePair
    host_log: Path
    client_log: Path
    focus_directions: tuple[focus.Direction, focus.Direction]
    faster_directions: tuple[faster_caster.Direction, faster_caster.Direction]
    meditation_directions: tuple[meditation.Direction, meditation.Direction]
    transient_directions: tuple[transient.Direction, transient.Direction]
    telekinesis_directions: tuple[
        telekinesis.Direction,
        telekinesis.Direction,
    ]
    defense_directions: tuple[defense.Direction, defense.Direction]
    rush_directions: tuple[rush.Direction, rush.Direction]
    webbed_directions: tuple[webbed.Direction, webbed.Direction]


def instance_log(instance: str, override_environment_variable: str) -> Path:
    override = os.environ.get(override_environment_variable, "").strip()
    if override:
        return Path(override)
    if not instance:
        raise VerifyFailure("both Steam instance environment variables are required")
    return (
        ROOT
        / "runtime/instances"
        / instance
        / "stage/.sdmod/logs/solomondarkmodloader.log"
    )


def configure_behavior_context(pair: SteamFriendActivePair) -> BehaviorContext:
    configure_verifiers(pair)
    host_log = instance_log(HOST_INSTANCE, "SDMOD_STEAM_HOST_LOG_PATH")
    client_log = instance_log(CLIENT_INSTANCE, "SDMOD_STEAM_CLIENT_LOG_PATH")
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "HOST_NAME": "Steam Host",
        "CLIENT_NAME": "Steam Friend",
        "HOST_LOG": host_log,
        "CLIENT_LOG": client_log,
        "lua": pair.lua,
    }
    modules = (
        progression,
        local_verify,
        upgrades,
        stats,
        catalog_probe,
        primary,
        real_input,
        spell_cast,
        health,
        focus,
        faster_caster,
        meditation,
        mindstar,
        persistent,
        persistent_harness,
        battle_siege,
        explode,
        embers,
        telekinesis,
        rewards,
        flat_boneyard,
        pickup_authority,
        transient,
        transient_harness,
        defense,
        defense_harness,
        natural_defense_harness,
        staff,
        staff_harness,
        rush,
        webbed,
        webbed_harness,
    )
    for module in modules:
        for name, value in replacements.items():
            if hasattr(module, name):
                setattr(module, name, value)

    focus_directions = (
        focus.Direction(
            "host_owned",
            "host",
            pair.host_participant_id,
            HOST_ENDPOINT,
            host_log,
            client_log,
        ),
        focus.Direction(
            "client_owned",
            "client",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            client_log,
            host_log,
        ),
    )
    faster_directions = (
        faster_caster.Direction(
            "host_owned",
            pair.host_participant_id,
            HOST_ENDPOINT,
            host_log,
            client_log,
        ),
        faster_caster.Direction(
            "client_owned",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            client_log,
            host_log,
        ),
    )
    meditation_directions = (
        meditation.Direction(
            "host_owned",
            pair.host_participant_id,
            HOST_ENDPOINT,
            CLIENT_ENDPOINT,
            CLIENT_ENDPOINT,
            host_log,
            430.0,
            330.0,
        ),
        meditation.Direction(
            "client_owned",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
            HOST_ENDPOINT,
            client_log,
            430.0,
            520.0,
        ),
    )
    transient_directions = (
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
    telekinesis_directions = (
        telekinesis.Direction(
            "host_owned",
            pair.host_participant_id,
            HOST_ENDPOINT,
            CLIENT_ENDPOINT,
            CLIENT_ENDPOINT,
        ),
        telekinesis.Direction(
            "client_owned",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
            HOST_ENDPOINT,
        ),
    )
    defense_directions = (
        defense.Direction(
            "host_owned",
            pair.host_participant_id,
            HOST_ENDPOINT,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
            0,
        ),
        defense.Direction(
            "client_owned",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
            HOST_ENDPOINT,
            pair.client_participant_id,
        ),
    )
    rush_directions = (
        rush.Direction(
            "host_owned",
            pair.host_participant_id,
            HOST_ENDPOINT,
            CLIENT_ENDPOINT,
            CLIENT_ENDPOINT,
        ),
        rush.Direction(
            "client_owned",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
            HOST_ENDPOINT,
        ),
    )
    webbed_directions = (
        webbed.Direction(
            "host_owned",
            pair.host_participant_id,
            HOST_ENDPOINT,
            CLIENT_ENDPOINT,
            False,
            attack_distance=webbed.LOCAL_OWNER_SPIDER_ATTACK_DISTANCE,
        ),
        webbed.Direction(
            "client_owned",
            pair.client_participant_id,
            CLIENT_ENDPOINT,
            HOST_ENDPOINT,
            True,
            attack_distance=webbed.REMOTE_OWNER_SPIDER_ATTACK_DISTANCE,
        ),
    )

    focus.DIRECTIONS = focus_directions
    faster_caster.DIRECTIONS = faster_directions
    meditation.DIRECTIONS = meditation_directions
    mindstar.DIRECTIONS = focus_directions
    transient.DIRECTIONS = transient_directions
    telekinesis.DIRECTIONS = telekinesis_directions
    telekinesis.GOLD_AMOUNTS = {
        pair.host_participant_id: 11,
        pair.client_participant_id: 13,
    }
    defense.DIRECTIONS = defense_directions
    rush.DIRECTIONS = rush_directions
    webbed.DIRECTIONS = webbed_directions

    return BehaviorContext(
        pair=pair,
        host_log=host_log,
        client_log=client_log,
        focus_directions=focus_directions,
        faster_directions=faster_directions,
        meditation_directions=meditation_directions,
        transient_directions=transient_directions,
        telekinesis_directions=telekinesis_directions,
        defense_directions=defense_directions,
        rush_directions=rush_directions,
        webbed_directions=webbed_directions,
    )


def require_shared_test_run(discovery: dict[str, Any]) -> None:
    scenes = [
        side.get("scene")
        for side in discovery.values()
        if isinstance(side, dict) and "scene" in side
    ]
    if scenes != ["testrun", "testrun"]:
        raise VerifyFailure(f"Steam friend pair is not in one shared test run: {scenes}")


def disable_runtime_test_godmode(pair: SteamFriendActivePair) -> dict[str, Any]:
    code = """
local function emit(k,v) print(k .. '=' .. tostring(v)) end
_G.__sdmod_steam_test_godmode_enabled = false
emit('enabled', _G.__sdmod_steam_test_godmode_enabled)
"""
    result: dict[str, Any] = {}
    for label, endpoint in (("host", HOST_ENDPOINT), ("client", CLIENT_ENDPOINT)):
        values = parse_key_values(pair.lua(endpoint, code, timeout=8.0))
        if values.get("enabled") != "false":
            raise VerifyFailure(
                f"failed to disable runtime test godmode on {label}: {values}"
            )
        result[label] = values
    return result


def load_progression_inputs(timeout: float) -> dict[str, Any]:
    config_root = steam_skill_config_root()
    ready = upgrades.wait_for_post_run_progression_ready(timeout)
    catalog_result = upgrades.build_and_verify_catalog(
        upgrades.wait_for_catalog_views(timeout),
        upgrades.load_skill_configs(config_root),
    )
    catalog = catalog_result["catalog"]
    return {
        "ready": ready,
        "catalog_result": catalog_result,
        "catalog": catalog,
        "contract_values": stats.load_stat_contract_values(
            catalog,
            config_root=config_root,
        ),
        "initial": {
            upgrades.HOST_ID: progression.query_progression_snapshot(HOST_ENDPOINT),
            upgrades.CLIENT_ID: progression.query_progression_snapshot(CLIENT_ENDPOINT),
        },
    }


def reset_quiet_arena(
    *,
    require_manual_spawner: bool = True,
) -> dict[str, Any]:
    # Stop stock wave production before cleanup so an active run cannot spawn
    # replacements between the cleanup pass and the zero-enemy assertion.
    manual_enemy_mode = upgrades.enable_quiet_progression_test_mode()
    poison_clear: dict[str, Any] = {}
    for label, endpoint in (("host", HOST_ENDPOINT), ("client", CLIENT_ENDPOINT)):
        before = transient_harness.query_poison_status(endpoint)
        if int(before["poison_count"]) > 0:
            poison_clear[label] = {
                "before": before,
                "clear": transient_harness.clear_local_native_poison_status(
                    endpoint
                ),
            }
        else:
            poison_clear[label] = {"before": before, "clear": None}
    enemy_cleanup = primary.cleanup_live_enemies()
    if require_manual_spawner:
        manual_spawner_state = {
            "host": primary.wait_for_manual_spawner_ready(
                HOST_ENDPOINT,
                timeout=12.0,
            ),
            "client": primary.wait_for_manual_spawner_ready(
                CLIENT_ENDPOINT,
                timeout=12.0,
            ),
        }
    else:
        manual_spawner_state = {
            "host": primary.manual_spawner_state(HOST_ENDPOINT),
            "client": primary.manual_spawner_state(CLIENT_ENDPOINT),
        }
    return {
        "poison_clear": poison_clear,
        "enemy_cleanup": enemy_cleanup,
        "manual_enemy_mode": manual_enemy_mode,
        "manual_spawner_required": require_manual_spawner,
        "manual_spawner_state": manual_spawner_state,
    }
