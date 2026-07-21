"""Multiplayer combat, progression, and upgrade contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_re_contract_support import (
    ALLY_HP_RECOMPUTE_GHIDRA,
    BINARY_LAYOUT,
    BOT_ELEMENT_DAMAGE_PROBE,
    BOT_SKILL_UPGRADE_COMBAT_FLOW_LIVE_PROBE,
    BOT_UPGRADE_DAMAGE_DELTA_LIVE_PROBE,
    CASTING_API,
    DISPATCH_PUMP_LOOP,
    LUA_BOT_CONFIG,
    LUA_BOT_CONSTANTS_RE_DOC,
    LUA_ENGINE_BOTS_BINDING,
    MULTIPLAYER_PROTOCOL,
    NATIVE_SEAM_PLAN,
    NATIVE_SPELL_STATS_HEADER,
    PENDING_CAST_PREPARATION,
    PRIMARY_KILL_STRESS_VERIFIER,
    PRIMARY_SPELL_BUILDER_GHIDRA,
    ROOT,
    SCENE_ANIMATION_DRIVE_PROFILES,
    SCENE_SELECTION,
    StaticReTestFailure,
    TARGETED_SPELL_MATRIX_VERIFIER,
    WORLD_SNAPSHOT_RECONCILIATION,
    read_bot_skill_choice_source,
    read_multiplayer_runtime_state_source,
    read_multiplayer_transport_source,
    read_native_spell_stats_source,
    read_source_unit,
    read_text,
)

def test_primary_kill_stress_verifier_uses_manual_spawns_without_waves() -> str:
    verifier_text = read_text(PRIMARY_KILL_STRESS_VERIFIER)
    runtime_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl")
    input_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl")
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl")
    player_cast_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl")
    pump_loop_text = read_text(DISPATCH_PUMP_LOOP)
    run_lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl")
    run_lifecycle_hooks_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl")
    run_lifecycle_cast_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl")
    run_lifecycle_public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl")
    required_tokens = (
        "sd.gameplay.enable_combat_prelude()",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(enabled)",
        "parse_int(state.get(\"wave_index\")) == 0",
        "parse_int(state.get(\"wave_counter\")) == 999999999",
        "spawn_manual_run_enemy",
        "sd.gameplay.set_run_enemy_health(actor_address, hp, hp)",
        "PRIMARY_CAST_HOOK_MARKER",
        "quiesce_gameplay_primary_input",
        "clear_gameplay_mouse_left",
        "PREPARE_AND_QUEUE_CASTER_LUA",
        "MAX_SCRIPTED_PRIMARY_TARGET_DISTANCE",
        "source_target_distance",
        "transport_active_count",
        "place_player_and_require_pair_views_at",
        "FORCED_PICKUP_POSITION_TOLERANCE",
        "select_forced_gold_location",
        "FORCED_GOLD_MIN_PLAYER_DISTANCE",
        "forced_gold_location",
        "before_spawn",
    )
    missing = [token for token in required_tokens if token not in verifier_text]
    if missing:
        raise StaticReTestFailure(
            "primary kill stress verifier is missing no-wave manual-spawn token(s): " +
            ", ".join(missing))
    bootstrap_start = verifier_text.find("def enable_manual_stock_spawner_combat()")
    bootstrap_end = verifier_text.find("\ndef cleanup_live_enemies()", bootstrap_start)
    bootstrap_text = verifier_text[bootstrap_start:bootstrap_end]
    manual_mode = bootstrap_text.find('result["client_manual_spawner_mode"]')
    pre_prime_cleanup = bootstrap_text.find(
        'result["pre_prime_cleanup"] = cleanup_live_enemies()'
    )
    combat_prelude = bootstrap_text.find('result["host_enable"]')
    if not 0 <= manual_mode < pre_prime_cleanup < combat_prelude:
        raise StaticReTestFailure(
            "manual stock-spawner bootstrap must suppress ambient waves and remove "
            "pre-existing enemies before it attributes any enemy to spawner priming"
        )
    native_required_tokens = (
        (verifier_text, "primary kill verifier", "START_WAVES_LUA"),
        (verifier_text, "primary kill verifier", "sd.gameplay.get_manual_enemy_spawner_state"),
        (verifier_text, "primary kill verifier", "host_manual_spawner_ready"),
        (verifier_text, "primary kill verifier", "client_manual_spawner_ready"),
        (verifier_text, "primary kill verifier", "host native manual-spawner priming leaked stock enemies"),
        (verifier_text, "primary kill verifier", "client native manual-spawner priming leaked stock enemies"),
        (pump_loop_text, "gameplay pump", "PumpRunLifecycleManualEnemySpawnRequest(&manual_spawn_error)"),
        (run_lifecycle_public_api_text, "run lifecycle API", "IsRunLifecycleManualEnemySpawnerReady()"),
        (run_lifecycle_public_api_text, "run lifecycle API", "g_state.last_wave_spawner.load"),
        (run_lifecycle_public_api_text, "run lifecycle API", "g_state.last_wave_spawner_vtable.load"),
        (run_lifecycle_public_api_text, "run lifecycle API", "g_state.last_wave_spawner_tick_ms.load"),
        (run_lifecycle_public_api_text, "run lifecycle API", "TryGetPreferredManualRunEnemySpawner"),
        (run_lifecycle_public_api_text, "run lifecycle API", "IsRememberedWaveSpawnerVtableValid"),
        (run_lifecycle_public_api_text, "run lifecycle API", "TryDispatchManualRunEnemySpawnFromSpawner("),
        (run_lifecycle_public_api_text, "run lifecycle API", "manual run enemy spawn: dispatched from remembered stock spawner"),
        (run_lifecycle_public_api_text, "run lifecycle API", "if (!IsRunLifecycleManualEnemySpawnerReady())"),
        (run_lifecycle_public_api_text, "run lifecycle API", "CompletePendingDirectManualRunEnemySpawnFailure"),
        (run_lifecycle_public_api_text, "run lifecycle API", "manual run enemy spawn: stock wave spawner became unavailable."),
        (run_lifecycle_state_text, "run lifecycle state", "last_arena_enemy_wave_spawner"),
        (run_lifecycle_state_text, "run lifecycle state", "g_current_wave_spawner_tick_address"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "RememberArenaEnemyWaveSpawner"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "TryReadActorObjectTypeForRunLifecycle(enemy_address, &actor_object_type)"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "DispatchExactRunEnemySpawn(request, spawner_address)"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "CallSpawnExactEnemyGroupSafe("),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "g_current_wave_spawner_tick_address = spawner_address"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "g_current_wave_spawner_tick_address = self_address"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "IsArenaCombatActorType(actor_object_type)"),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "actor_object_type="),
        (run_lifecycle_hooks_text, "run lifecycle hooks", "manual run enemy spawn: ignored non-arena stock spawn during controlled exact spawn"),
        (runtime_state_text, "runtime request state", "manual_spawner_primary_cast_control_grace_until_ms"),
        (input_queue_text, "input queue", "kManualSpawnerPrimaryCastControlGraceMinMs"),
        (player_control_text, "player control hooks", "IsManualSpawnerPrimaryCastControlGraceActive()"),
        (player_control_text, "player control hooks", "suppressed extra local pure-primary start during scripted cast grace"),
        (player_control_text, "player control hooks", "manual_spawner_scripted_local_primary_control"),
        (player_control_text, "player control hooks", "seeded local scripted primary control"),
        (player_control_text, "player control hooks", "const bool actor_target_written ="),
        (player_control_text, "player control hooks", "const auto target_heading = NormalizeWizardActorHeadingForWrite("),
        (player_control_text, "player control hooks", "ApplyWizardActorFacingState(actor_address, target_heading)"),
        (player_control_text, "player control hooks", "if (!actor_target_written || selection_pointer == 0)"),
        (player_control_text, "player control hooks", "if (selection_pointer != 0)"),
        (input_queue_text, "input queue", "if (selection_pointer != 0)"),
        (player_cast_text, "player cast hooks", "void __fastcall HookPurePrimaryAttackDispatch("),
        (player_cast_text, "player cast hooks", "IsManualSpawnerPrimaryCastControlGraceActive()"),
        (player_cast_text, "player cast hooks", "ApplyManualSpawnerPrimaryTargetState("),
        (run_lifecycle_cast_text, "run lifecycle cast hooks", "ApplyPinnedManualSpawnerPrimaryTarget(self_address)"),
    )
    native_missing = [
        f"{label}: {token}"
        for text, label, token in native_required_tokens
        if token not in text
    ]
    if native_missing:
        raise StaticReTestFailure(
            "manual enemy spawn requests must be serviced by the gameplay action pump: " +
            ", ".join(native_missing))
    if "fallback_spawner" in run_lifecycle_public_api_text:
        raise StaticReTestFailure(
            "manual enemy spawning retained a fallback spawner path instead of "
            "failing an unavailable native-spawner request")
    for forbidden in (
        "CallManualRunEnemySpawnerTickSafe(",
        "manual run enemy spawn: arming stock spawner",
        "request.network_actor_id == 0 ||",
    ):
        if forbidden in run_lifecycle_hooks_text:
            raise StaticReTestFailure(
                "manual enemy spawning can still ignore its requested native class: " +
                forbidden
            )
    if "if (!manual_spawner_scripted_local_primary_control || selection_pointer == 0)" in player_control_text:
        raise StaticReTestFailure(
            "scripted local primary aiming still requires a bot-owned selection pointer")
    if "x=target_x + FORCED_GOLD_OFFSET_X" in verifier_text:
        raise StaticReTestFailure(
            "primary kill stress verifier regressed to a blind forced-gold offset instead of nav-aware selection")
    active_gold_filter_tokens = (
        "FORCED_GOLD_MIN_PLAYER_DISTANCE = 900.0",
        "FORCED_GOLD_CANDIDATE_OFFSETS = (\n    (100.0, -1200.0)",
        "(-960.0, -720.0)",
        "(1280.0, FORCED_GOLD_OFFSET_Y)",
        "def list_host_active_native_gold_addresses()",
        "parse_int(row.get(\"amount\")) > 0",
        "parse_int(row.get(\"lifetime\")) != 0",
        "before_addresses = list_host_active_native_gold_addresses()",
    )
    missing_active_gold_filter_tokens = [
        token for token in active_gold_filter_tokens if token not in verifier_text
    ]
    if missing_active_gold_filter_tokens:
        raise StaticReTestFailure(
            "primary kill stress verifier must only exclude active pre-existing gold drops: " +
            ", ".join(missing_active_gold_filter_tokens))
    source_lane_tokens = (
        "def clear_lane_probe(target_x: float, target_y: float, pipe_name: str = HOST_PIPE)",
        "result[\"pipe\"] = pipe_name",
        "clear_lane_probe(planned_target_x, planned_target_y, pipe_name=direction.source_pipe)",
        "pipe_name=direction.source_pipe",
    )
    missing_source_lane_tokens = [
        token for token in source_lane_tokens if token not in verifier_text
    ]
    if missing_source_lane_tokens:
        raise StaticReTestFailure(
            "primary kill stress verifier must check clear cast lanes from the casting instance: " +
            ", ".join(missing_source_lane_tokens))
    return (
        "primary kill stress primes exact native spawners, rejects unavailable "
        "manual requests, and completes accepted readiness races"
    )


def test_bot_equip_materialization_stays_scoped_to_bot_creation() -> str:
    resources_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_wizard_resources.inl")
    slot_creation_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_slot_bot_creation.inl")
    shared_required_tokens = (
        (resources_text, "generic equip repair helper", "bool EnsureWizardActorEquipRuntimeHandles("),
        (resources_text, "generic equip repair helper", "CreateStandaloneWizardEquipWrapper("),
        (resources_text, "generic equip repair helper", "AssignActorSmartPointerWrapperSafe("),
        (resources_text, "generic equip repair helper", "[bots] wizard actor equip runtime handles created."),
        (slot_creation_text, "gameplay-slot equip repair wrapper", "\"gameplay_slot_bot\""),
    )
    shared_missing = [
        f"{label}: {token}"
        for text, label, token in shared_required_tokens
        if token not in text
    ]
    if shared_missing:
        raise StaticReTestFailure(
            "bot equip materialization is missing required token(s): " +
            ", ".join(shared_missing))
    if "local_player_run_cast_prime" in resources_text + slot_creation_text:
        raise StaticReTestFailure(
            "bot equip materialization still exposes the removed local-player path")
    return "wizard equip materialization remains available to bot creation without a local-player owner"


def test_hub_start_testrun_uses_gameplay_region_switch() -> str:
    seams_header_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    seam_address_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl")
    seam_binding_text = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    native_types_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl")
    action_queue_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl")
    dispatch_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl")
    actor_lifecycle_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl")
    config_text = read_text(ROOT / "config/binary-layout.ini")
    required_tokens = (
        (action_queue_text, "Queued hub testrun request."),
        (action_queue_text, "EnsureHostRunGenerationSeed(\"hub_start_testrun_queue\")"),
        (dispatch_text, "ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion)"),
        (dispatch_text, "CallGameplaySwitchRegionSafe("),
        (dispatch_text, "ScopedHubRunSwitchAuthorization authorize_switch"),
        (dispatch_text, "kArenaRegionIndex"),
        (dispatch_text, "Hub testrun region switch completed."),
        (actor_lifecycle_text, "PrepareGameplaySceneSwitchOnGameThread(\n        gameplay_address,\n        region_index,\n        \"gameplay_switch_region_pre_dispatch\")"),
        (actor_lifecycle_text, "Blocked client run switch_region while connected to multiplayer"),
        (config_text, "gameplay_switch_region=0x005CDDD0"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "hub start testrun is missing native region-switch token(s): " +
            ", ".join(missing))
    forbidden_tokens = (
        "kHubStartTestrunNative",
        "kHubStartTestrunRemoveChild",
        "kHubStartTestrunPreviousChildGlobal",
        "HubStartTestrunNativeFn",
        "HubOwnerRemoveChildFn",
        "CallHubOwnerRemoveChildSafe",
        "CallHubStartTestrunNativeSafe",
        "hub_start_testrun_native_builder",
        "Hub testrun native builder completed.",
        "start_testrun_native=0x005B6D50",
        "start_testrun_remove_child=0x00428160",
        "start_testrun_previous_child_global=0x0081993C",
        "CallHubOwnerControlActionSafe",
        "HubOwnerControlActionFn",
        "kHubStartTestrunControlByteOffset",
        "CallHubStartTestrunPrepareSafe",
        "HubStartTestrunPrepareFn",
        "kHubStartTestrunPrepare",
        "start_testrun_prepare",
    )
    active_text = "\n".join((
        seams_header_text,
        seam_address_text,
        seam_binding_text,
        native_types_text,
        dispatch_text,
        config_text,
    ))
    present = [token for token in forbidden_tokens if token in active_text]
    if present:
        raise StaticReTestFailure(
            "hub start testrun still references incomplete native UI/builder dispatch token(s): " +
            ", ".join(present))
    return "hub start testrun dispatches through native Gameplay_SwitchRegion"


def test_hub_start_testrun_waits_for_app_tick_pump() -> str:
    pump_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl")
    pending_index = pump_text.find("pending_hub_start_testrun_requests.load")
    app_tick_guard_index = pump_text.find("if (!g_allow_gameplay_action_pump_in_gameplay) {", pending_index)
    dispatch_index = pump_text.find("TryDispatchHubStartTestrunOnGameThread()", pending_index)
    gameplay_return_guard_index = pump_text.find(
        "if (!g_allow_gameplay_action_pump_in_gameplay && gameplay_active)",
        pending_index)
    if pending_index < 0 or app_tick_guard_index < 0 or dispatch_index < 0:
        raise StaticReTestFailure("hub start testrun pump no longer has app-tick guarded dispatch")
    if not (pending_index < app_tick_guard_index < dispatch_index < gameplay_return_guard_index):
        raise StaticReTestFailure(
            "hub start testrun dispatch must stay inside the app-tick guard and before the "
            "non-gameplay action return guard")
    return "hub start testrun remains app-tick owned and deferred out of the actor-tick gameplay pump"


def test_primary_kill_stress_verifier_uses_native_hub_start() -> str:
    verifier_text = read_text(PRIMARY_KILL_STRESS_VERIFIER)
    local_sync_text = read_text(ROOT / "tools/verify_local_multiplayer_sync.py")
    required_tokens = (
        (verifier_text, "start_host_testrun_and_wait_for_clients(timeout=60.0)"),
        (local_sync_text, "sd.hub.start_testrun()"),
        (local_sync_text, "assert_client_start_testrun_blocked"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "primary kill stress verifier is missing native hub-start token(s): " +
            ", ".join(missing))
    return "primary kill stress verifier enters runs through the native hub start request"


def test_unverified_play_boneyard_shortcut_is_not_exposed() -> str:
    active_texts = {
        "mod_loader_h": read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h"),
        "input_bindings": read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_input.cpp"),
        "local_sync": read_text(ROOT / "tools/verify_local_multiplayer_sync.py"),
        "primary_kill_stress": read_text(PRIMARY_KILL_STRESS_VERIFIER),
    }
    forbidden = (
        "QueueHubStartPlayBoneyard",
        "start_play_boneyard",
        "stage_play_boneyard",
        "--boneyard-source",
        "play-boneyard",
    )
    present = [
        f"{name}:{token}"
        for name, text in active_texts.items()
        for token in forbidden
        if token in text
    ]
    if present:
        raise StaticReTestFailure(
            "unverified play.boneyard shortcut is still exposed in active code: " +
            ", ".join(present))
    return "unverified play.boneyard shortcut remains out of active runtime and verifier code"


def test_replicated_manual_run_enemy_materialization_is_client_bounded() -> str:
    world_snapshot_text = read_source_unit(WORLD_SNAPSHOT_RECONCILIATION)
    run_lifecycle_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl")
    run_lifecycle_hooks_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl")
    debug_spawn_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl")
    local_transport_text = read_multiplayer_transport_source()
    local_transport_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h")
    required_tokens = (
        "g_replicated_run_pending_enemy_materialization_until_ms",
        "QueueReplicatedManualRunEnemyMaterialization",
        "!multiplayer::IsLocalTransportClient()",
        "QueueRunLifecycleReplicatedEnemyCatchupSpawn(",
        "request.allow_active_waves = allow_active_waves",
        "request.freeze_on_spawn = freeze_on_spawn",
        "if (request.freeze_on_spawn) {",
        "multiplayer::HasLocalPendingLethalEnemyDamageClaim(authoritative_actor.network_actor_id, now_ms)",
        "if (IsRunLifecycleManualEnemySpawnerTestModeEnabled())",
        "QueueRunLifecycleManualEnemySpawn(",
        "(void)QueueReplicatedManualRunEnemyMaterialization(authoritative_actor, now_ms)",
        "g_replicated_run_pending_enemy_materialization_until_ms.erase(network_actor_id)",
        "pending_lethal_enemy_damage_claim_until_ms",
        "kEnemyDamageLethalClaimPendingSuppressMs",
        "HasLocalPendingLethalEnemyDamageClaim",
        "manual run enemy spawn is host-authoritative while connected to multiplayer.",
    )
    haystacks = {
        "world snapshot reconciliation": world_snapshot_text,
        "run lifecycle API": run_lifecycle_api_text,
        "run lifecycle hooks": run_lifecycle_hooks_text,
        "debug spawn public API": debug_spawn_text,
        "local transport": local_transport_text,
        "local transport header": local_transport_header_text,
    }
    missing: list[str] = []
    for token in required_tokens:
        if not any(token in text for text in haystacks.values()):
            missing.append(token)
    if missing:
        raise StaticReTestFailure(
            "replicated manual enemy materialization is missing bounded-client token(s): " +
            ", ".join(missing))
    return "replicated manual run enemy materialization stays client/test-mode bounded and public API remains host-authoritative"


def test_primary_mana_resolver_accepts_native_dispatcher_entry_ids() -> str:
    casting_text = read_text(CASTING_API)
    scene_text = read_text(SCENE_SELECTION)
    native_spell_stats_text = read_native_spell_stats_source()

    resolver_match = re.search(
        r"BotManaCost\s+ResolveBotCastManaCost\([^{}]*\)\s*\{(?P<body>.*?)\n\}",
        casting_text,
        re.S,
    )
    if not resolver_match:
        raise StaticReTestFailure("could not find ResolveBotCastManaCost body")
    resolver_body = resolver_match.group("body")
    required_tokens = (
        "TryResolveNativePrimarySelectionFromSkillId",
        "if (!selection_resolved)",
        "TryResolveNativePrimarySelectionFromPair",
    )
    missing = [token for token in required_tokens if token not in resolver_body]
    if missing:
        raise StaticReTestFailure(
            "primary mana resolver does not accept native dispatcher entry ids: " +
            ", ".join(missing))
    if not re.search(
        r"TryResolveNativePrimarySelectionFromPair\(\s*skill_id,\s*skill_id,",
        resolver_body,
    ):
        raise StaticReTestFailure(
            "primary mana resolver does not validate a dispatcher entry as a primary pair")

    descriptor_tokens = (
        "case 0x18:",
        "case 0x20:",
        "case 0x28:",
        "TryResolvePrimaryCastDescriptorFromSelectionPair",
    )
    missing_descriptor_tokens = [
        token for token in descriptor_tokens if token not in scene_text
    ]
    if missing_descriptor_tokens:
        raise StaticReTestFailure(
            "primary descriptor resolver no longer accepts native dispatcher ids: " +
            ", ".join(missing_descriptor_tokens))

    dispatcher_mana_tokens = (
        "entry_pair_is_pure_projectile",
        "!EntryUsesContinuousMana(primary_entry_index)",
        "selection->pure_primary = entry_pair_is_pure_projectile",
    )
    missing_dispatcher_mana_tokens = [
        token for token in dispatcher_mana_tokens if token not in native_spell_stats_text
    ]
    if missing_dispatcher_mana_tokens:
        raise StaticReTestFailure(
            "native dispatcher entry ids still look like pure-projectile mana selections: " +
            ", ".join(missing_dispatcher_mana_tokens))

    return "primary mana resolver accepts native dispatcher ids through validated primary pairs"


def test_native_primary_output_layout_is_stat_ordered() -> str:
    native_spell_stats_text = read_native_spell_stats_source()

    required_tokens = (
        "kMinimumNativePrimaryStatOutputCount = 2",
        "ResolveNativePrimaryManaOutputIndex(selection)",
        "selection.primary_entry_index == selection.combo_entry_index ? 1u : 2u",
        "if (output_count <= mana_output_index)",
        "if (mana_output_index > 1)",
    )
    missing = [token for token in required_tokens if token not in native_spell_stats_text]
    if missing:
        raise StaticReTestFailure(
            "native primary output resolver no longer follows Skills_Wizard stat order: " +
            ", ".join(missing))

    forbidden_tokens = (
        "selection.pure_primary ? 1u : 2u",
        "selection.primary_entry_index != ether_entry",
        "mana_output_index = output_count - 1",
        "mana_output_index + 1",
        "!selection.pure_primary && output_count > 1",
    )
    present = [token for token in forbidden_tokens if token in native_spell_stats_text]
    if present:
        raise StaticReTestFailure(
            "native primary output resolver still derives stat layout from cast lifetime: " +
            ", ".join(present))

    return "native primary output resolver keeps base mana ahead of appended upgrade stats"


def test_lightning_chaining_verifier_uses_native_dispatcher_loop() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_lightning_chaining_effect_sync.py"
    )
    transport_text = read_multiplayer_transport_source()
    protocol_text = read_text(MULTIPLAYER_PROTOCOL)
    runtime_state_text = read_multiplayer_runtime_state_source()
    lua_gameplay_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    air_chain_sync_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/air_chain_sync.inl"
    )
    run_lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    spell_cast_hooks_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl"
    )
    pending_cast_text = read_text(PENDING_CAST_PREPARATION)
    scene_selection_text = read_text(SCENE_SELECTION)
    targeted_spell_matrix_text = read_text(TARGETED_SPELL_MATRIX_VERIFIER)
    animation_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_animation_mana_elements.py"
    )
    active_pair_spell_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_spell_behavior.py"
    )

    required_layout_tokens = (
        "actor_air_lightning_chain_count=0x284",
        "air_lightning_chain_target=0x00641340",
        "air_lightning_chain_target_return=0x005403AF",
        "air_lightning_chain_source_from_return_slot=0xB0",
        "spell_cast_018=0x0053F9C0",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "Lightning Chaining native path is missing layout token(s): " +
            ", ".join(missing_layout))

    required_verifier_tokens = (
        'read_runtime_layout_offset("spell_cast_018")',
        'read_runtime_layout_offset("air_lightning_chain_target")',
        'read_runtime_layout_offset("actor_air_lightning_chain_count")',
        'emit("chain_count", ok and chain_count or "")',
        '"native_chain_state"',
        '"air_chain_sync"',
        'sd.world.get_replicated_air_chains',
        'build_air_chain_sync_evidence',
        '#selected - 127',
        '"applied_target_parity"',
        '"endpoint_error_ok"',
        '"applied_source_endpoint_parity"',
        '"applied_target_endpoint_parity"',
        '"source_override_failure_delta"',
        '"target_override_success_delta"',
        '"target_override_failure_delta"',
        'include_client=False',
        '"replicated_cast_delivery"',
        '"observer_native_cast_prepped"',
        "dispatcher_chain_count",
        "baseline_native_chain_evidence_ok",
        "upgraded_native_chain_evidence_ok",
    )
    missing_verifier = [
        token for token in required_verifier_tokens if token not in verifier_text
    ]
    if missing_verifier:
        raise StaticReTestFailure(
            "Lightning Chaining verifier is missing native behavior token(s): " +
            ", ".join(missing_verifier))
    if "0x00628F10" in verifier_text:
        raise StaticReTestFailure(
            "Lightning Chaining verifier still traces the unrelated Air action routine")
    if "trace_function(" in verifier_text or "untrace_function(" in verifier_text:
        raise StaticReTestFailure(
            "Lightning Chaining verifier still competes with the permanent target hook")

    required_network_tokens = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 69;"),
        (protocol_text, "AirChainSnapshot = 15"),
        (protocol_text, "kAirChainSnapshotMaxTargets = 8"),
        (protocol_text, "struct AirChainTargetPacketState"),
        (protocol_text, "struct AirChainSnapshotPacket"),
        (protocol_text, "static_assert(sizeof(AirChainSnapshotPacket) == 260"),
        (runtime_state_text, "AirChainSnapshotRuntimeInfo"),
        (runtime_state_text, "AirChainApplyRuntimeInfo"),
        (lua_gameplay_text, '"get_replicated_air_chains"'),
        (run_lifecycle_state_text, "kHookAirLightningChainTarget"),
        (run_lifecycle_state_text, "targets[kHookAirLightningChainTarget] = {kAirLightningChainTarget, 7}"),
        (spell_cast_hooks_text, "HookAirLightningChainTarget"),
        (spell_cast_hooks_text, "PublishLocalAirChainFrame"),
        (spell_cast_hooks_text, "ResolveReplicatedAirChainTarget"),
        (spell_cast_hooks_text, "ApplyAuthoritativeAirChainSourceEndpointToNativeCaller"),
        (spell_cast_hooks_text, "ApplyAuthoritativeAirChainTargetEndpointForNativeCopy"),
        (spell_cast_hooks_text, "RecordReplicatedAirChainTargetOverride"),
        (spell_cast_hooks_text, "kAirLightningChainTargetReturn"),
        (spell_cast_hooks_text, "kAirLightningChainSourceFromReturnSlotOffset"),
        (spell_cast_hooks_text, "kCallerSourceContractEpsilon"),
        (air_chain_sync_text, "RelayPacketToPeers(packet, from)"),
        (air_chain_sync_text, "kAirChainRuntimeHistoryCapacity = 128"),
        (air_chain_sync_text, "cumulative_override_success_count"),
        (air_chain_sync_text, "cumulative_unmapped_target_count"),
        (air_chain_sync_text, "cumulative_source_override_success_count"),
        (air_chain_sync_text, "cumulative_source_override_failure_count"),
        (air_chain_sync_text, "cumulative_target_override_success_count"),
        (air_chain_sync_text, "cumulative_target_override_failure_count"),
        (air_chain_sync_text, "binding.source_error_before_override"),
        (air_chain_sync_text, "binding.target_error_before_override"),
        (air_chain_sync_text, "return local_target.actor_address;"),
        (air_chain_sync_text, "An authoritative target that is not materialized"),
    )
    missing_network = [
        token for text, token in required_network_tokens if token not in text
    ]
    if missing_network:
        raise StaticReTestFailure(
            "Lightning Chaining authoritative target lane is incomplete: " +
            ", ".join(missing_network))

    exact_enemy_identity_tokens = (
        "if tonumber(binding.network_actor_id) == target_id",
        "bound_address = tonumber(binding.local_actor_address) or 0",
        "if not resolved and bound_address == 0 then",
        "clustered tests must never substitute a neighbour",
    )
    missing_enemy_identity = [
        token for token in exact_enemy_identity_tokens
        if token not in targeted_spell_matrix_text
    ]
    if missing_enemy_identity:
        raise StaticReTestFailure(
            "clustered spell verification can still read a neighbouring enemy instead of its exact binding: " +
            ", ".join(missing_enemy_identity))

    required_remote_start_tokens = (
        "IsSaneExplicitCastTarget(cast_target, packet.position_x, packet.position_y)",
        "cast_input_state.target_actor_address = resolved_target_actor_address",
        "if (!input_tracker.start_queued)",
        "if (QueueBotCast(request))",
    )
    missing_remote_start = [
        token for token in required_remote_start_tokens if token not in transport_text
    ]
    if missing_remote_start:
        raise StaticReTestFailure(
            "remote cast playback no longer queues targetless native presentation: " +
            ", ".join(missing_remote_start))
    forbidden_remote_start_tokens = (
        "air_primary_packet",
        "deferred_start_packet_count",
        "Multiplayer remote Air cast start deferred until exact target resolves",
    )
    present_remote_start = [
        token for token in forbidden_remote_start_tokens if token in transport_text
    ]
    if present_remote_start:
        raise StaticReTestFailure(
            "remote Air playback still suppresses a valid targetless cast: " +
            ", ".join(present_remote_start))

    required_targetless_air_regression_tokens = (
        'choices=("explode", "embers", "chaining", "targetless-air", "all")',
        "def verify_targetless_air(",
        'if args.behavior in ("targetless-air", "all"):',
        'animation.ELEMENT_BY_NAME["air"]',
        'flow["local_targetless_sequences"]',
        'flow["remote_targetless_queue_sequences"]',
        'flow["remote_prep_sequences"]',
        'flow["remote_release_sequences"]',
        'if not cast["active_seen"] or not cast["anim_seen"]:',
    )
    missing_targetless_air_regression = [
        token
        for token in required_targetless_air_regression_tokens
        if token not in active_pair_spell_text
    ]
    if missing_targetless_air_regression:
        raise StaticReTestFailure(
            "real-Steam targetless Air regression lacks exact lifecycle witness(es): "
            + ", ".join(missing_targetless_air_regression)
        )
    for token in (
        '"local_targetless_sequences": local_targetless_sequences',
        '"remote_targetless_queue_sequences": remote_targetless_queue_sequences',
        '"target_network_actor_id=0" not in line',
        '"target_actor=0x0" not in line',
        '"target_source=none" not in line',
        "require_remote_release=True",
        "receiver_deadline = time.monotonic() + 8.0",
    ):
        if token not in animation_verifier_text:
            raise StaticReTestFailure(
                "targetless Air flow parser lacks: " + token
            )

    forbidden_predicted_damage_tokens = (
        "TryResolveLocalPrimaryCastClaimDamage",
        "TrySendLocalCastEnemyDamageClaim",
        "local_cast_damage_claimed_sequences",
        "Multiplayer local cast damage claim sent from cast packet",
    )
    present_predicted_damage_tokens = [
        token for token in forbidden_predicted_damage_tokens
        if token in transport_text
    ]
    if present_predicted_damage_tokens:
        raise StaticReTestFailure(
            "cast press can still apply predicted spell output before native impact: " +
            ", ".join(present_predicted_damage_tokens))

    resolved_build_id_tokens = (
        "kProgressionCurrentSpellIdOffset,\n                    ongoing.skill_id",
        "request.secondary_slot,\n            ongoing.skill_id);",
    )
    missing_build_id = [
        token for token in resolved_build_id_tokens if token not in pending_cast_text
    ]
    if missing_build_id:
        raise StaticReTestFailure(
            "remote primary preparation still feeds a dispatcher entry to native spell stats: " +
            ", ".join(missing_build_id))
    dispatcher_build_tokens = (
        "const bool have_live_build =",
        "TryResolveNativePrimarySelectionFromLiveProgression(",
        "have_live_build ? live_selection.build_skill_id : -1",
    )
    missing_dispatcher_build = [
        token for token in dispatcher_build_tokens if token not in scene_selection_text
    ]
    if missing_dispatcher_build:
        raise StaticReTestFailure(
            "dispatcher-entry cast descriptors no longer retain their live Skills_Wizard build id: " +
            ", ".join(missing_dispatcher_build))

    return "Lightning Chaining verifies native delivery plus authoritative target IDs, endpoints, substitutions, and terminal state on both peers"


def test_primary_selection_mapping_is_native_backed_not_static_table() -> str:
    native_spell_stats_text = read_native_spell_stats_source()
    native_spell_stats_header_text = read_text(NATIVE_SPELL_STATS_HEADER)
    scene_text = read_text(SCENE_SELECTION)
    config_text = read_text(LUA_BOT_CONFIG)
    targeting_test_text = read_text(ROOT / "tools/test_lua_bots_targeting.lua")
    combined_text = "\n".join((
        native_spell_stats_text,
        native_spell_stats_header_text,
        scene_text,
        config_text,
        targeting_test_text,
    ))

    forbidden_tokens = (
        "NativePrimarySkillPair",
        "kNativePrimarySkillPairs",
        "PRIMARY_BUILD_SKILL_IDS",
        "[0] = 0x10",
        "[1] = 0x20",
        "[2] = 0x28",
        "[3] = 0x18",
        "[4] = 0x08",
    )
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "primary selection mapping still uses static hardcoded table token(s): " +
            ", ".join(present))

    required_tokens = (
        "TryResolveNativePrimaryEntryForElement",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "TryResolveNativePrimarySelectionFromSkillId",
        "kSkillsWizardBuildPrimarySpell",
        "kProgressionCurrentSpellIdOffset",
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "primary selection mapping is missing native-backed resolver token(s): " +
            ", ".join(missing))

    return "primary selection mapping is backed by live Skills_Wizard output instead of a static table"


def test_primary_attack_window_uses_live_native_selection_range() -> str:
    lua_bots_binding_text = read_text(LUA_ENGINE_BOTS_BINDING)
    doc_text = read_text(LUA_BOT_CONSTANTS_RE_DOC)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    targeting_test_text = read_text(ROOT / "tools/test_lua_bots_targeting.lua")

    forbidden_tokens = (
        "kProjectilePrimaryEngagementRange",
        "kBoulderPrimaryReleaseMinimumRange",
        "kWaterConeBaseRange",
        "kWaterConeRangePerShapeUnit",
        "kPrimaryEngagementSafetyMargin",
        "water_primary_native_base_cone",
        "water_primary_live_actor_cone",
        "projectile_primary_engagement",
        "earth_boulder_release_window",
        "max_range = 360.0",
        "max_range = 205.0",
        "min_range = 96.0",
    )
    combined_text = "\n".join((lua_bots_binding_text, targeting_test_text))
    present = [token for token in forbidden_tokens if token in combined_text]
    if present:
        raise StaticReTestFailure(
            "primary attack window still carries fixed engagement scalar token(s): " +
            ", ".join(present))

    required_tokens = (
        "ReadNativePrimarySelectionPursuitRange",
        "kActorAnimationSelectionStateOffset",
        "kActorControlBrainPursuitRangeOffset",
        "native_selection_pursuit_range",
        "FUN_0052C910",
        "actor_control_brain_pursuit_range",
    )
    evidence_text = "\n".join((lua_bots_binding_text, doc_text, plan_text))
    missing = [token for token in required_tokens if token not in evidence_text]
    if missing:
        raise StaticReTestFailure(
            "primary attack window is missing live native selection-range token(s): " +
            ", ".join(missing))

    drive_text = read_text(SCENE_ANIMATION_DRIVE_PROFILES)
    reset_start = drive_text.find("void ResetStandaloneWizardControlBrain")
    reset_end = drive_text.find("void ApplyStandaloneWizardPuppetDriveState", reset_start)
    if reset_start < 0 or reset_end < 0:
        raise StaticReTestFailure("ResetStandaloneWizardControlBrain was not found")
    if "kActorControlBrainPursuitRangeOffset" in drive_text[reset_start:reset_end]:
        raise StaticReTestFailure(
            "control-brain reset still clears the native primary pursuit range used by Lua attack windows")

    return "primary attack window reads the live native selection pursuit range"


def test_bot_level_sync_uses_native_level_up() -> str:
    skill_choices_text = read_bot_skill_choice_source()
    layout_text = read_text(BINARY_LAYOUT)
    skill_picker_doc_text = read_text(ROOT / "docs/skill-picker-re.md")

    required_layout_tokens = (
        "level_up=0x0067C250",
        "progression_level=0x30",
        "progression_xp=0x34",
        "progression_previous_xp_threshold=0x38",
        "progression_next_xp_threshold=0x3C",
        "progression_nonlocal_mode_flag=0x40",
        "progression_local_skill_picker_screen=0x83C",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "native level-up layout evidence is missing token(s): " +
            ", ".join(missing_layout))

    required_code_tokens = (
        "using NativeLevelUpFn",
        "CallNativeLevelUpSafe",
        "kLevelUp",
        "SyncNativeBotProgressionLevel",
        "EnsureBotOwnedProgressionMode",
        "kProgressionNonLocalModeFlagOffset",
        "kProgressionNonLocalModeValue",
        "native level_up",
        "level_before",
        "level_after",
    )
    missing_code = [token for token in required_code_tokens if token not in skill_choices_text]
    if missing_code:
        raise StaticReTestFailure(
            "bot level sync is not wired through native level_up: " +
            ", ".join(missing_code))

    forbidden_direct_stat_writes = (
        (r"TryWriteField\s*<\s*std::int32_t\s*>\s*\(\s*progression_address\s*,\s*kProgressionLevelOffset", "level"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionHpOffset", "current HP"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionMaxHpOffset", "max HP"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionMpOffset", "current MP"),
        (r"TryWriteField\s*<\s*float\s*>\s*\(\s*progression_address\s*,\s*kProgressionMaxMpOffset", "max MP"),
    )
    present_direct_writes = [
        label for pattern, label in forbidden_direct_stat_writes
        if re.search(pattern, skill_choices_text)
    ]
    if present_direct_writes:
        raise StaticReTestFailure(
            "bot level sync still directly writes progression stat fields: " +
            ", ".join(present_direct_writes))

    required_doc_tokens = (
        "0x0067C250",
        "native level-up routine",
        "Bots call the same native `level_up` routine",
        "Bot-owned progressions are marked non-local through `progression + 0x40`",
        "does not write progression level, HP, max HP, MP, or max MP directly",
    )
    missing_doc = [token for token in required_doc_tokens if token not in skill_picker_doc_text]
    if missing_doc:
        raise StaticReTestFailure(
            "skill-picker RE doc does not describe the native bot level sync contract: " +
            ", ".join(missing_doc))

    return "bot level/stat sync uses native level_up instead of direct progression stat writes"


def test_native_stat_refresh_preserves_live_vitals() -> str:
    helper_cpp_text = read_native_spell_stats_source()
    preparation_text = read_text(PENDING_CAST_PREPARATION)
    builder_ghidra_text = read_text(PRIMARY_SPELL_BUILDER_GHIDRA)
    recompute_ghidra_text = read_text(ALLY_HP_RECOMPUTE_GHIDRA)

    required_native_tokens = (
        "CallSkillsWizardBuildPrimarySpellSafe",
        "TryReadNativePrimaryStatOutputs",
        "progression_runtime_address",
        "kProgressionPrimaryStatValuesOffset",
        "kProgressionPrimaryStatCountOffset",
    )
    missing_native = [token for token in required_native_tokens if token not in helper_cpp_text]
    if missing_native:
        raise StaticReTestFailure(
            "native primary stat query is missing native output-reader token(s): " +
            ", ".join(missing_native))

    forbidden_restore_tokens = (
        "ProgressionResourceSnapshot",
        "CaptureProgressionResourceSnapshot",
        "RestoreProgressionResourceSnapshot",
        "ProgressionVitalSnapshot",
        "CaptureProgressionVitals",
        "RestoreProgressionVitals",
    )
    present_restore_tokens = [
        token for token in forbidden_restore_tokens
        if token in helper_cpp_text or token in preparation_text
    ]
    if present_restore_tokens:
        raise StaticReTestFailure(
            "native stat/refresh path still uses loader-owned resource snapshot restore token(s): " +
            ", ".join(present_restore_tokens))

    forbidden_direct_restore_patterns = (
        (helper_cpp_text, "native_spell_stats.cpp"),
        (preparation_text, "pending_cast_preparation.inl"),
    )
    direct_restore_fields = (
        "kProgressionHpOffset",
        "kProgressionMaxHpOffset",
        "kProgressionMpOffset",
        "kProgressionMaxMpOffset",
    )
    direct_restore_hits: list[str] = []
    for text, label in forbidden_direct_restore_patterns:
        for field in direct_restore_fields:
            if re.search(
                rf"TryWriteField\s*<\s*float\s*>\s*\([^;]*{field}",
                text,
                re.S,
            ):
                direct_restore_hits.append(f"{label}:{field}")
    if direct_restore_hits:
        raise StaticReTestFailure(
            "native stat/refresh path still writes progression HP/MP directly: " +
            ", ".join(direct_restore_hits))

    refresh_call = preparation_text.find("CallActorProgressionRefreshSafe")
    if refresh_call == -1:
        raise StaticReTestFailure("cast preparation no longer calls native ActorProgressionRefresh")

    required_builder_evidence = (
        "FUNCTION FUN_00666020 @ 00666020",
        "*(undefined4 *)(param_1 + 0x750)",
        "param_1 + 0x774",
        "param_1 + 0x778",
    )
    missing_builder_evidence = [
        token for token in required_builder_evidence
        if token not in builder_ghidra_text
    ]
    if missing_builder_evidence:
        raise StaticReTestFailure(
            "primary spell builder Ghidra evidence is missing token(s): " +
            ", ".join(missing_builder_evidence))

    forbidden_builder_resource_writes = (
        "*(float *)(param_1 + 0x70)",
        "*(float *)(param_1 + 0x74)",
        "*(float *)(param_1 + 0x7c)",
        "*(float *)(param_1 + 0x80)",
        "param_1[0x1c] =",
        "param_1[0x1d] =",
        "param_1[0x1f] =",
        "param_1[0x20] =",
    )
    builder_resource_hits = [
        token for token in forbidden_builder_resource_writes
        if token in builder_ghidra_text.split("=== TARGET: 0x006741B0 ===", 1)[0]
    ]
    if builder_resource_hits:
        raise StaticReTestFailure(
            "primary spell builder evidence shows direct progression resource writes: " +
            ", ".join(builder_resource_hits))

    required_recompute_evidence = (
        "FUNCTION FUN_0065f9a0 @ 0065f9a0",
        "param_1[0x1c] = (int)((float)param_1[0x1d] * (fVar1 / fVar2));",
        "param_1[0x1f] = (int)((float)param_1[0x20] * (fVar3 / fVar4));",
    )
    missing_recompute_evidence = [
        token for token in required_recompute_evidence
        if token not in recompute_ghidra_text
    ]
    if missing_recompute_evidence:
        raise StaticReTestFailure(
            "ActorProgressionRefresh Ghidra evidence is missing native ratio-preserve token(s): " +
            ", ".join(missing_recompute_evidence))

    return "native stat query avoids resource writes and cast refresh uses native ratio-preserving recompute"


def test_bot_skill_upgrade_combat_probe_checks_native_damage_and_mana() -> str:
    probe_text = read_text(BOT_SKILL_UPGRADE_COMBAT_FLOW_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "query_primary_stat_output",
        "progression_primary_stat_values",
        "progression_primary_stat_count",
        "baseline_damage",
        "post_upgrade_damage",
        "post_damage <= baseline_damage",
        "baseline_stats_output.get(\"mana_cost\"",
        "post_stats_output.get(\"mana_cost\"",
        "entry_after.get(\"active\"",
        "profile_after.get(\"primary_entry_index\"",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot skill-upgrade combat probe no longer checks native output token(s): " +
            ", ".join(missing))

    required_doc_tokens = (
        "run_live_bot_skill_upgrade_combat_flow_probe.py",
        "reports increased",
        "damage and mana cost",
        "test_bot_skill_choice_regression.py --iterations 5 --active-bots all --min-bots 5",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing bot skill-upgrade coverage token(s): " +
            ", ".join(missing_doc))

    return "bot skill-upgrade combat probe checks native stat output damage, mana, entry, and loadout evidence"


def test_bot_element_damage_probe_supports_upgraded_primary_victim_validation() -> str:
    probe_text = read_text(BOT_ELEMENT_DAMAGE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "--apply-primary-upgrade",
        "apply_primary_upgrade_to_bot",
        "stress.debug_sync_level_up",
        "stress.choose_skill",
        "matched_primary_upgrade",
        "matching_native_mana_delta",
        "actual_victims",
        "any_hostile_damaged",
        "native_spell_stat_validation.get(\"ok\") is True",
        "native_target_lethal_waits_for_min_charge",
        "target_lethal_min_charge_ok",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot element damage probe no longer supports upgraded primary victim validation token(s): " +
            ", ".join(missing))

    run_element_match = re.search(
        r"def run_element_probe\(element: str, args: argparse\.Namespace\) -> dict\[str, object\]:(?P<body>.*?)\n\ndef ",
        probe_text,
        re.S,
    )
    if run_element_match is None:
        raise StaticReTestFailure("bot element damage probe run_element_probe block was not found")
    run_element_body = run_element_match.group("body")
    launch_index = run_element_body.find("result[\"navigation\"] = prepare_clean_run")
    config_index = run_element_body.find("config = element_config(element)")
    if launch_index == -1 or config_index == -1 or config_index < launch_index:
        raise StaticReTestFailure(
            "bot element damage probe resolves native primary entry before launching a clean Lua runtime")

    required_doc_tokens = (
        "run_live_bot_upgrade_damage_delta_probe.py",
        "probe_earth_baseline_35000_force_both_goal_confirm.json",
        "probe_earth_upgraded_35000_force_both_goal_confirm.json",
        "held Boulder release diagnostics",
        "skill picker",
        "native max-size release",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing upgraded primary victim validation token(s): " +
            ", ".join(missing_doc))

    return "bot element damage probe supports native-upgraded primary victim validation"


def test_bot_upgrade_damage_delta_probe_checks_native_mana_projection_and_release_policy() -> str:
    probe_text = read_text(BOT_UPGRADE_DAMAGE_DELTA_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "probe_earth_baseline_35000_force_both_goal_confirm.json",
        "probe_earth_upgraded_35000_force_both_goal_confirm.json",
        "DEFAULT_TARGET_HP = 35000.0",
        "DEFAULT_CAST_INTERVAL_SECONDS = 30.0",
        "MIN_POST_RELEASE_TICKS = 3",
        "DEFAULT_CHILD_ATTEMPTS = 2",
        "DEFAULT_CHILD_TIMEOUT_SECONDS = 240.0",
        "subprocess.TimeoutExpired",
        "child_artifact_has_native_boulder_release",
        "native_boulder_release_artifact",
        "output.unlink()",
        "--cast-interval-seconds",
        "--apply-primary-upgrade",
        "--positioning",
        "force_both",
        "matched_primary_upgrade",
        "live_progression_primary_stat_output",
        "upgraded native mana cost did not increase",
        "upgraded native boulder projected damage did not increase",
        "baseline did not use native max-size release",
        "upgraded native release was not max-size",
        "upgraded max-size release did not write release charge",
        "removed threshold-release fields",
        "native post-release launch window",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot upgrade damage delta probe no longer checks native upgrade projection token(s): " +
            ", ".join(missing))

    required_doc_tokens = (
        "run_live_bot_upgrade_damage_delta_probe.py",
        "same high-HP Earth setup twice",
        "force_both",
        "extended Earth cast window",
        "target HP is intentionally above",
        "upgraded max-size Boulder projection",
        "native Boulder upgrade",
        "native mana cost",
        "projected damage increase",
        "native max-size release",
        "incidental HP loss as proof",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing bot upgrade damage delta coverage token(s): " +
            ", ".join(missing_doc))

    return "bot upgrade damage delta probe checks native mana and projected damage without threshold-release shortcuts"
