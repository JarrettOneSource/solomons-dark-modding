"""Shared source readers and assertions for multiplayer static contracts."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_many(*relative_paths: str) -> str:
    return "\n".join(_read(path) for path in relative_paths)


_SPLIT_SOURCE_FRAGMENTS = frozenset(
    {
        "skill_choice_application.inl",
        "public_memory_forwarders.inl",
        "lua_engine_main_thread_pump.inl",
        "lua_engine_registered_spell_effect_parsing.inl",
        "lua_engine_event_queue.inl",
        "lua_engine_event_public_api.inl",
        "lua_exec_wait.inl",
        "participant_equipment_state.inl",
        "transient_status_participant_reconciliation.inl",
        "native_remote_vitals_and_playback.inl",
        "incoming_participant_state_sync.inl",
        "level_up_native_picker_presentation.inl",
        "level_up_packet_handlers.inl",
        "loot_pickup_packet_handlers.inl",
        "loot_pickup_host_finalization.inl",
        "completed_host_loot_pickups.inl",
        "participant_vitals_correction.inl",
        "native_progression_derived_stats.inl",
        "world_snapshot_hub_presentation_and_loot_helpers.inl",
        "lobby_event_handlers.inl",
        "state_timeline_and_formation.inl",
        "actor_binding_and_hub_presentation.inl",
        "run_enemy_health_and_status.inl",
        "run_enemy_targeting_and_retirement.inl",
        "run_lifecycle_and_materialization.inl",
        "apply_snapshot.inl",
        "run_transition_hooks.inl",
        "manual_enemy_spawning.inl",
        "actor_world_pause_hook.inl",
        "enemy_spawn_filter.inl",
        "wave_spawn_filter.inl",
        "wave_and_enemy_spawn_hooks.inl",
        "drop_roll_filter.inl",
        "enemy_death_reward_level_up_hooks.inl",
        "mod_loader_hub_state.inl",
        "mod_loader_public_api.inl",
        "public_api_combat_control_queues.inl",
        "public_api_native_behavior_probes.inl",
        "dispatch_and_hooks_native_probe_pump.inl",
        "lua_engine_bindings_spells_runtime.inl",
        "registered_spell_input.inl",
        "player_secondary_spell_cast_hook.inl",
    }
)


def read_source_unit(path: str | Path) -> str:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = ROOT / source_path

    def expand(current_path: Path, active_paths: frozenset[Path]) -> str:
        resolved_path = current_path.resolve()
        assert resolved_path not in active_paths, (
            f"recursive split-source include: {resolved_path}"
        )
        text = current_path.read_text(encoding="utf-8")
        next_active_paths = active_paths | {resolved_path}

        def replace_include(match: re.Match[str]) -> str:
            include_name = match.group(1)
            if Path(include_name).name not in _SPLIT_SOURCE_FRAGMENTS:
                return match.group(0)
            include_path = current_path.parent / include_name
            assert include_path.is_file(), f"missing split-source fragment: {include_path}"
            return expand(include_path, next_active_paths)

        return re.sub(
            r'^\s*#include\s+"([^"]+)"\s*$',
            replace_include,
            text,
            flags=re.MULTILINE,
        )

    return expand(source_path, frozenset())


def read_source_units(*paths: str | Path) -> str:
    return "\n".join(read_source_unit(path) for path in paths)


def _require_in_order(text: str, *tokens: str) -> None:
    cursor = 0
    for token in tokens:
        position = text.find(token, cursor)
        assert position >= 0, f"missing ordered token: {token}"
        cursor = position + len(token)
