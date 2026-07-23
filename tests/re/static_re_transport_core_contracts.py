"""Core transport and snapshot ownership contracts."""

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
    ACTOR_ANIMATION_ADVANCE_HOOK,
    BINARY_LAYOUT,
    BOT_RUNTIME_HEADER,
    BOT_RUNTIME_SNAPSHOTS_API,
    DISPATCH_PUMP_LOOP,
    ENEMY_DAMAGE_CLAIM_SYNC_VERIFIER,
    LOCAL_MULTIPLAYER_PAIR_SCRIPT,
    LOCAL_MULTIPLAYER_SYNC_VERIFIER,
    LUA_ENGINE_BOTS_BINDING,
    LUA_EXEC_PIPE,
    MOD_LOADER_PROJECT,
    MOD_LOADER_PROJECT_FILTERS,
    MULTIPLAYER_LOCAL_TRANSPORT_HEADER,
    MULTIPLAYER_PARTICIPANT_MODEL_DOC,
    MULTIPLAYER_PROTOCOL,
    MULTIPLAYER_SERVICE_LOOP,
    NATIVE_ENEMY_LIFECYCLE,
    NATIVE_ENEMY_LIFECYCLE_HEADER,
    NETWORKING_DOC,
    PARTICIPANT_ENTITY_SYNC,
    PARTICIPANT_SCENE_BINDING_TICKS,
    PLAYER_ACTOR_TICK_HOOK,
    PLAYER_HEALTH_DEATH_SYNC_VERIFIER,
    ROOT,
    RUN_ENEMY_PRESENTATION_PROBE,
    RUN_ENEMY_SEED_VERIFIER,
    RUN_REWARD_SYNC_PROBE,
    RUN_STATIC_LAYOUT_SYNC_VERIFIER,
    RUN_WORLD_SNAPSHOT_VERIFIER,
    STAGED_GAME_LAUNCHER,
    StaticReTestFailure,
    WORLD_SNAPSHOT_RECONCILIATION,
    WORLD_SYNC_AUTHORITY_PLAN_DOC,
    read_gameplay_seams_header_source,
    read_lua_runtime_source,
    read_mod_loader_header_source,
    read_multiplayer_runtime_state_source,
    read_multiplayer_transport_source,
    read_source_unit,
    read_text,
)


def test_client_gold_pickup_replays_stock_feedback_once_after_authority_accepts() -> str:
    gold_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/gold_pickup_hook.inl"
    )
    reconciliation_text = "\n".join((
        read_text(
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
        ),
        read_text(
            ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_gold_pickup_feedback.inl"
        ),
    ))
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_replicated_loot.inl"
    )
    gameplay_api_text = read_text(
        ROOT / "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_packet_handlers.inl"
    )
    lua_gameplay_text = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_gold_pickup_authority.py"
    )
    binary_layout_text = read_text(BINARY_LAYOUT)

    required_pairs = (
        (transport_text, "QueueAcceptedReplicatedGoldPickupFeedback("),
        (transport_text, "CancelReplicatedGoldPickupFeedback("),
        (gameplay_api_text, "QueueAcceptedReplicatedGoldPickupFeedback("),
        (gameplay_api_text, "TryGetLastReplicatedGoldPickupFeedbackState("),
        (public_api_text, "QueueAcceptedReplicatedGoldPickupFeedbackInternal("),
        (public_api_text, "TryGetLastReplicatedGoldPickupFeedbackStateInternal("),
        (reconciliation_text, "MarkReplicatedGoldPickupAwaitingAuthorityInternal("),
        (reconciliation_text, "ShouldHoldReplicatedGoldPickupForFeedbackLocked("),
        (reconciliation_text, "TryBeginAcceptedReplicatedGoldPickupFeedbackForActorInternal("),
        (reconciliation_text, "CompleteReplicatedGoldPickupFeedbackInternal("),
        (gold_hook_text, "TryBeginAcceptedReplicatedGoldPickupFeedbackForActorInternal("),
        (gold_hook_text, "kReplicatedGoldLifetimeOffset"),
        (gold_hook_text, "kActorPendingRemoveOffset"),
        (gold_hook_text, "pending_remove != 0"),
        (gold_hook_text, "AbortReplicatedGoldPickupFeedbackInternal("),
        (gold_hook_text, "feedback.resulting_gold - feedback.amount"),
        (gold_hook_text, "TryWriteResolvedGlobalInt(kGoldGlobal, feedback.resulting_gold)"),
        (gold_hook_text, "CompleteReplicatedGoldPickupFeedbackInternal("),
        (lua_gameplay_text, '"last_gold_feedback"'),
        (lua_gameplay_text, '"apply_count"'),
        (binary_layout_text, "gold_pickup_text_feedback=0x005CA7C0"),
        (binary_layout_text, "gold_pickup_sound_start=0x00407B70"),
        (verifier_text, 'read_runtime_layout_offset("gold_pickup_text_feedback")'),
        (verifier_text, 'read_runtime_layout_offset("gold_pickup_sound_start")'),
        (verifier_text, 'feedback.get("applied") == "true"'),
        (verifier_text, 'parse_int_text(feedback.get("apply_count"), 0) == 1'),
        (verifier_text, '"stock_popup_calls"'),
        (verifier_text, '"stock_sound_calls"'),
        (verifier_text, '"feedback_applied_once"'),
        (verifier_text, '"duplicate_preserved_single_feedback"'),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "client gold pickup stock-feedback replay missing token(s): "
            + ", ".join(missing)
        )

    accepted_replay = re.search(
        r"if\s*\(TryBeginAcceptedReplicatedGoldPickupFeedbackForActorInternal\s*\("
        r"(?P<body>.*?)CompleteReplicatedGoldPickupFeedbackInternal\s*\(",
        gold_hook_text,
        re.DOTALL,
    )
    if accepted_replay is None or "original(self);" not in accepted_replay.group("body"):
        raise StaticReTestFailure(
            "client gold pickup must invoke the stock tick only inside an accepted feedback replay"
        )
    if gold_hook_text.count("CompleteReplicatedGoldPickupFeedbackInternal(") != 1:
        raise StaticReTestFailure(
            "client gold pickup must have exactly one stock-feedback completion site"
        )

    return "accepted client gold pickups replay stock popup, sound, particles, and credit exactly once"


def test_client_non_gold_pickups_replay_stock_feedback_once_after_authority_accepts() -> str:
    feedback_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_pickup_feedback.inl"
    )
    orb_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/orb_pickup_hook.inl"
    )
    item_credit_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    powerup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/powerup_pickup_hook.inl"
    )
    transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_packet_handlers.inl"
    )
    gameplay_api_text = read_text(
        ROOT / "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    lua_gameplay_text = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )

    required_pairs = (
        (feedback_text, "MarkReplicatedLootPickupAwaitingAuthorityInternal("),
        (feedback_text, "ShouldHoldReplicatedLootPickupForFeedbackLocked("),
        (feedback_text, "TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal("),
        (feedback_text, "CompleteReplicatedLootPickupFeedbackInternal("),
        (feedback_text, "CallNativePickupNotificationSafe("),
        (gameplay_api_text, "QueueAcceptedReplicatedOrbPickupFeedback("),
        (gameplay_api_text, "QueueAcceptedReplicatedPowerupPickupFeedback("),
        (transport_text, "QueueAcceptedReplicatedOrbPickupFeedback("),
        (transport_text, "QueueAcceptedReplicatedPowerupPickupFeedback("),
        (orb_hook_text, "TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal("),
        (orb_hook_text, "original(self);"),
        (orb_hook_text, "TryWriteLocalPlayerOrbResource("),
        (orb_hook_text, "pending_remove != 0"),
        (orb_hook_text, "CompleteReplicatedLootPickupFeedbackInternal("),
        (item_credit_text, "CallAcceptedItemDropPickupTickSafe("),
        (item_credit_text, "GetX86HookTrampoline<ItemDropPickupTickFn>"),
        (item_credit_text, "stock_feedback_applied"),
        (item_credit_text, "kActorPendingRemoveOffset"),
        (powerup_hook_text, "kSuppressedPowerupApplyKind"),
        (powerup_hook_text, "TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal("),
        (powerup_hook_text, "original(self);"),
        (powerup_hook_text, "CallNativePickupNotificationSafe("),
        (powerup_hook_text, "CompleteReplicatedLootPickupFeedbackInternal("),
        (lua_gameplay_text, '"last_pickup_feedback"'),
        (lua_gameplay_text, '"apply_count"'),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "accepted client non-gold pickup feedback missing token(s): "
            + ", ".join(missing)
        )

    for hook_text, label in ((orb_hook_text, "orb"), (powerup_hook_text, "powerup")):
        replay = re.search(
            r"TryBeginAcceptedReplicatedLootPickupFeedbackForActorInternal\s*\("
            r"(?P<body>.*?)CompleteReplicatedLootPickupFeedbackInternal\s*\(",
            hook_text,
            re.DOTALL,
        )
        if replay is None or "original(self);" not in replay.group("body"):
            raise StaticReTestFailure(
                f"accepted client {label} pickup must replay its retail tick exactly once"
            )

    return (
        "accepted client orbs, items, potions, and powerups replay native feedback "
        "exactly once while retaining authoritative state"
    )


def test_all_stock_potion_subtypes_replicate_as_native_pickups() -> str:
    transport_text = read_multiplayer_transport_source()
    reconciliation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    inventory_credit_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_pickup_feedback.py"
    )

    required_pairs = (
        (transport_text, "kStockPotionSubtypeMin = 0"),
        (transport_text, "kStockPotionSubtypeMax = 5"),
        (reconciliation_text, "kStockPotionSubtypeMin = 0"),
        (reconciliation_text, "kStockPotionSubtypeMax = 5"),
        (reconciliation_text, "drop.item_slot <= kStockPotionSubtypeMax"),
        (inventory_credit_text, "request.item_slot > kStockPotionSubtypeMax"),
        (verifier_text, "STOCK_POTION_SUBTYPES = (0, 1, 2, 3, 4, 5)"),
        (verifier_text, '"Health Potion"'),
        (verifier_text, '"Mana Potion"'),
        (verifier_text, '"Wizard Chug"'),
        (verifier_text, '"Antidote"'),
        (verifier_text, '"Mind Chug"'),
        (verifier_text, '"Rejuvenation Potion"'),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "stock potion subtype replication missing token(s): " + ", ".join(missing)
        )

    restricted_sources = (reconciliation_text, inventory_credit_text)
    stale_limits = [
        token
        for token in ("item_slot > 1", "drop.item_slot <= 1", "(std::min)(1, drop.item_slot)")
        if any(token in text for text in restricted_sources)
    ]
    if stale_limits:
        raise StaticReTestFailure(
            "stock potion replication is still restricted to health/mana: "
            + ", ".join(stale_limits)
        )

    return "all six retail potion subtypes materialize, stack, and replay native pickup feedback"


def test_misc_ground_items_replicate_without_recipe_identity() -> str:
    transport_text = read_multiplayer_transport_source()
    reconciliation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    materialization_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl"
    )
    inventory_credit_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_pickup_feedback.py"
    )

    required_pairs = (
        (transport_text, "kMiscItemTypeId = 0x1B64"),
        (transport_text, "IsSupportedNonRecipeLootItem("),
        (reconciliation_text, "kReplicatedLootMiscItemTypeId = 0x1B64"),
        (reconciliation_text, "IsSupportedReplicatedNonRecipeItem("),
        (materialization_text, "BuildNativeItemFromLootSnapshot("),
        (materialization_text, "CallGameObjectFactorySafe("),
        (materialization_text, "kInventoryMiscItemTypeId"),
        (inventory_credit_text, "IsSupportedReplicatedNonRecipeItem("),
        (verifier_text, "MISC_ITEM_SUBTYPES"),
        (verifier_text, '"Fabric Dye Kit"'),
        (verifier_text, '"Wizard Key"'),
        (verifier_text, '"Book of Skill"'),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "nonrecipe miscellaneous pickup replication missing token(s): "
            + ", ".join(missing)
        )

    return (
        "stock dye, key, and skill-book ground items use exact native factory identity "
        "without inventing recipe UIDs"
    )

def test_local_multiplayer_udp_transport_is_wired() -> str:
    protocol_text = read_text(MULTIPLAYER_PROTOCOL)
    runtime_state_text = read_multiplayer_runtime_state_source()
    transport_header_text = read_text(MULTIPLAYER_LOCAL_TRANSPORT_HEADER)
    transport_text = read_multiplayer_transport_source()
    native_enemy_lifecycle_header_text = read_text(NATIVE_ENEMY_LIFECYCLE_HEADER)
    native_enemy_lifecycle_text = read_text(NATIVE_ENEMY_LIFECYCLE)
    world_snapshot_reconciliation_text = read_source_unit(WORLD_SNAPSHOT_RECONCILIATION)
    service_loop_text = read_text(MULTIPLAYER_SERVICE_LOOP)
    lua_exec_pipe_text = read_text(LUA_EXEC_PIPE)
    staged_game_launcher_text = read_text(STAGED_GAME_LAUNCHER)
    launcher_command_parser_text = read_text(ROOT / "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs")
    isolated_profile_bootstrapper_text = read_text(ROOT / "SolomonDarkModLauncher/src/Launch/IsolatedProfileBootstrapper.cs")
    stage_sandbox_links_text = read_text(ROOT / "SolomonDarkModLauncher/src/Staging/StageSandboxCompatibilityLinks.cs")
    project_text = read_text(MOD_LOADER_PROJECT)
    project_filters_text = read_text(MOD_LOADER_PROJECT_FILTERS)
    bot_runtime_header_text = read_text(BOT_RUNTIME_HEADER)
    bot_snapshots_text = read_text(BOT_RUNTIME_SNAPSHOTS_API)
    entity_sync_text = read_text(PARTICIPANT_ENTITY_SYNC)
    scene_binding_text = read_text(PARTICIPANT_SCENE_BINDING_TICKS)
    participant_snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    native_remote_playback_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl"
    )
    orb_pickup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/orb_pickup_hook.inl"
    )
    gold_pickup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/gold_pickup_hook.inl"
    )
    item_drop_pickup_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/item_drop_pickup_hook.inl"
    )
    replicated_loot_reconciliation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    host_loot_drop_deactivation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    spell_effect_transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/spell_effect_sync.inl"
    )
    spell_effect_reconciliation_text = "\n".join(
        (
            read_text(
                ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/spell_effect_reconciliation.inl"
            ),
            read_text(
                ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/spell_effect_materialization.inl"
            ),
        )
    )
    participant_collision_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/participant_collision_response.inl"
    )
    networking_doc_text = read_text(NETWORKING_DOC)
    world_sync_plan_text = read_text(WORLD_SYNC_AUTHORITY_PLAN_DOC)
    participant_doc_text = read_text(MULTIPLAYER_PARTICIPANT_MODEL_DOC)
    script_text = read_text(LOCAL_MULTIPLAYER_PAIR_SCRIPT)
    verifier_text = read_text(LOCAL_MULTIPLAYER_SYNC_VERIFIER)
    run_snapshot_verifier_text = read_text(RUN_WORLD_SNAPSHOT_VERIFIER)
    enemy_damage_claim_verifier_text = read_text(ENEMY_DAMAGE_CLAIM_SYNC_VERIFIER)
    run_static_layout_verifier_text = read_text(RUN_STATIC_LAYOUT_SYNC_VERIFIER)
    player_health_death_verifier_text = read_text(PLAYER_HEALTH_DEATH_SYNC_VERIFIER)
    run_seed_verifier_text = read_text(RUN_ENEMY_SEED_VERIFIER)
    run_enemy_presentation_probe_text = read_text(RUN_ENEMY_PRESENTATION_PROBE)
    run_reward_sync_probe_text = read_text(RUN_REWARD_SYNC_PROBE)
    progression_ledger_sync_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_progression_ledger_sync.py"
    )
    level_up_offer_sync_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_level_up_offer_sync.py"
    )
    host_owned_level_up_sync_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_host_owned_level_up_sync.py"
    )
    progression_probe_text = read_text(
        ROOT / "tools/multiplayer_progression_probe.py"
    )
    fireball_explode_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )
    skill_choices_api_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl"
    )
    state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    participant_snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    gold_pickup_authority_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_gold_pickup_authority.py"
    )
    orb_pickup_authority_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_orb_pickup_authority.py"
    )
    inventory_audit_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_inventory_audit.py"
    )
    item_potion_contract_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_item_potion_pickup_contract.py"
    )
    enemy_soft_reconciliation_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_enemy_soft_reconciliation.py"
    )
    level_up_choice_and_picker_text = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_choice_and_picker.inl"
    )
    skill_picker_visual_identity_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_skill_picker_visual_identity.py"
    )
    lua_input_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_input.cpp")
    lua_gameplay_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    lua_runtime_text = read_lua_runtime_source()
    named_hub_npc_probe_text = read_text(ROOT / "tools/probe_named_hub_npc_fields.py")
    inventory_item_doc_text = read_text(ROOT / "docs/inventory-item-investigation.md")
    binary_layout_text = read_text(BINARY_LAYOUT)
    background_focus_text = read_text(ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp")
    gameplay_seams_header_text = read_gameplay_seams_header_source()
    gameplay_seams_bindings_text = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    gameplay_seams_size_bindings_text = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    dispatch_thread_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"
    )
    dispatch_pump_loop_text = read_text(DISPATCH_PUMP_LOOP)
    run_generation_seed_helpers_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/run_generation_seed_helpers.inl"
    )
    run_lifecycle_level_hooks_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    participant_entity_lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_lifecycle.inl"
    )

    required_pairs = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 76;"),
        (protocol_text, "kParticipantDisplayNameBytes"),
        (protocol_text, "kParticipantInventorySnapshotMaxItems"),
        (protocol_text, "kParticipantProgressionBookSnapshotMaxEntries"),
        (protocol_text, "kWorldSnapshotActorsPerFragment"),
        (protocol_text, "kWorldSnapshotMaxLogicalActors"),
        (protocol_text, "kLootSnapshotMaxDrops"),
        (protocol_text, "kWorldActorStudentVisualStateBytes"),
        (protocol_text, "kWorldActorStudentBookPaletteMaxEntries"),
        (protocol_text, "std::uint32_t snapshot_id;"),
        (protocol_text, "LootSnapshotFlagTruncated"),
        (protocol_text, "LootSnapshot = 6"),
        (protocol_text, "EnemyDamageClaim = 7"),
        (protocol_text, "EnemyDamageResult = 8"),
        (protocol_text, "std::uint8_t claim_flags;"),
        (protocol_text, "kEnemyDamageClaimFlagTargetPositionOptional"),
        (protocol_text, "kEnemyDamageClaimKnownFlags"),
        (protocol_text, "LootPickupRequest = 9"),
        (protocol_text, "LootPickupResult = 10"),
        (protocol_text, "LevelUpOffer = 11"),
        (protocol_text, "LevelUpChoice = 12"),
        (protocol_text, "LevelUpChoiceResult = 13"),
        (protocol_text, "SpellEffectSnapshot = 14"),
        (protocol_text, "kSpellEffectSnapshotMaxEffects"),
        (protocol_text, "SpellEffectStateFlagEmberRuntime"),
        (protocol_text, "SpellEffectStateFlagFirewalkerRuntime"),
        (protocol_text, "struct SpellEffectPacketState"),
        (protocol_text, "struct SpellEffectSnapshotPacket"),
        (protocol_text, "static_assert(sizeof(SpellEffectPacketState) == 124"),
        (protocol_text, "static_assert(sizeof(SpellEffectSnapshotPacket) == 4000"),
        (protocol_text, "kLevelUpWaitStatusMaxParticipants"),
        (protocol_text, "std::uint8_t level_up_pause_active"),
        (protocol_text, "std::uint8_t level_up_waiting_count"),
        (protocol_text, "std::uint64_t level_up_waiting_participant_ids"),
        (native_enemy_lifecycle_header_text, "TryTriggerRunEnemyDeath"),
        (native_enemy_lifecycle_text, "ResolveGameAddressOrZero(kEnemyDeath)"),
        (native_enemy_lifecycle_text, "kEnemyDeathHandledOffset"),
        (native_enemy_lifecycle_text, "kEnemyDeathPresenterVtableSlotOffset"),
        (native_enemy_lifecycle_text, "CallEnemyDeathPresenterVirtualSafe"),
        (native_enemy_lifecycle_text, "CallEnemyDeathSafe"),
        (binary_layout_text, "enemy_death_presenter_vtable_slot=0x50"),
        (gameplay_seams_header_text, "kEnemyDeathPresenterVtableSlotOffset"),
        (gameplay_seams_size_bindings_text, "enemy_death_presenter_vtable_slot"),
        (world_snapshot_reconciliation_text, "HoldReplicatedRunEnemyDeath"),
        (enemy_damage_claim_verifier_text, "wait_for_host_enemy_native_death_log"),
        (project_text, "include\\native_enemy_lifecycle.h"),
        (project_text, "src\\native_enemy_lifecycle.cpp"),
        (project_filters_text, "include\\native_enemy_lifecycle.h"),
        (project_filters_text, "src\\native_enemy_lifecycle.cpp"),
        (protocol_text, "Gold = 1"),
        (protocol_text, "enum class LootPickupResultCode"),
        (protocol_text, "enum class LevelUpChoiceResultCode"),
        (protocol_text, "struct LootPickupRequestPacket"),
        (protocol_text, "struct LootPickupResultPacket"),
        (protocol_text, "struct LevelUpOfferPacket"),
        (protocol_text, "struct LevelUpChoicePacket"),
        (protocol_text, "struct LevelUpChoiceResultPacket"),
        (protocol_text, "std::uint16_t resulting_active;"),
        (protocol_text, "struct ParticipantInventoryItemPacketState"),
        (protocol_text, "struct ParticipantProgressionBookEntryPacketState"),
        (protocol_text, "struct LevelUpOfferOptionPacketState"),
        (protocol_text, "Orb = 4"),
        (protocol_text, "WorldActorSnapshotFlagLifecycleOwned"),
        (protocol_text, "WorldActorPresentationFlagAnimationDriveWord"),
        (protocol_text, "WorldActorPresentationFlagStudentVisualState"),
        (protocol_text, "WorldActorPresentationFlagStudentVariantBytes"),
        (protocol_text, "WorldActorPresentationFlagLocomotionFloats"),
        (protocol_text, "WorldActorPresentationFlagStudentBookPalette"),
        (protocol_text, "WorldActorSnapshotFlagRunStatic"),
        (protocol_text, "WorldActorSnapshotFlagTargetAuthoritative"),
        (protocol_text, "std::uint64_t target_participant_id;"),
        (protocol_text, "std::uint32_t target_native_type_id;"),
        (protocol_text, "std::int32_t target_actor_slot;"),
        (protocol_text, "std::int32_t target_world_slot;"),
        (protocol_text, "std::int32_t target_bucket_delta;"),
        (protocol_text, "std::uint64_t participant_id;"),
        (protocol_text, "std::uint64_t target_network_actor_id;"),
        (protocol_text, "float life_current;"),
        (protocol_text, "float life_max;"),
        (protocol_text, "float mana_current;"),
        (protocol_text, "float mana_max;"),
        (protocol_text, "std::int32_t owned_gold;"),
        (protocol_text, "std::uint32_t gold_revision;"),
        (protocol_text, "std::uint32_t concentration_revision;"),
        (protocol_text, "std::int32_t concentration_entry_a;"),
        (protocol_text, "std::int32_t concentration_entry_b;"),
        (protocol_text, "struct ParticipantDerivedStatPacketState"),
        (protocol_text, "std::uint32_t derived_stat_revision;"),
        (protocol_text, "std::uint16_t inventory_item_count;"),
        (protocol_text, "ParticipantInventorySnapshotFlagTruncated"),
        (protocol_text, "ParticipantProgressionBookSnapshotFlagTruncated"),
        (protocol_text, "std::uint16_t progression_book_entry_count;"),
        (protocol_text, "ParticipantPresentationFlagAnimationDriveWord"),
        (protocol_text, "ParticipantPresentationFlagRenderDriveFloats"),
        (protocol_text, "ParticipantPresentationFlagStaffVisualState"),
        (protocol_text, "ParticipantPresentationFlagRenderSelectorBytes"),
        (protocol_text, "ParticipantPresentationFlagVisualLinkColorBlocks"),
        (protocol_text, "std::uint32_t attachment_staff_visual_state;"),
        (protocol_text, "std::uint8_t primary_visual_link_color_block"),
        (protocol_text, "std::uint32_t anim_drive_state_word;"),
        (protocol_text, "float magic_shield_absorb_remaining;"),
        (protocol_text, "float magic_shield_absorb_capacity;"),
        (protocol_text, "float magic_shield_explosion_fraction;"),
        (protocol_text, "float magic_shield_hit_flash;"),
        (protocol_text, "float render_drive_overlay_alpha;"),
        (protocol_text, "float render_drive_move_blend;"),
        (protocol_text, "display_name"),
        (protocol_text, "static_assert(sizeof(ParticipantInventoryItemPacketState) == 20"),
        (protocol_text, "static_assert(sizeof(ParticipantProgressionBookEntryPacketState) == 20"),
        (protocol_text, "std::uint64_t authority_participant_id;"),
        (protocol_text, "static_assert(sizeof(StatePacket) == 4520"),
        (protocol_text, "static_assert(sizeof(StudentBookPaletteEntryPacketState) == 24"),
        (protocol_text, "static_assert(sizeof(NamedHubNpcPresentationPacketState) == 40"),
        (protocol_text, "static_assert(sizeof(WorldActorSnapshotPacketState) == 328"),
        (protocol_text, "static_assert(sizeof(WorldSnapshotPacket) == 1032"),
        (protocol_text, "static_assert(sizeof(LootDropSnapshotPacketState) == 112"),
        (protocol_text, "static_assert(sizeof(LootSnapshotPacket) == 7200"),
        (protocol_text, "static_assert(sizeof(LootPickupRequestPacket) == 56"),
        (protocol_text, "static_assert(sizeof(LootPickupResultPacket) == 164"),
        (protocol_text, "static_assert(sizeof(LevelUpOfferPacket) == 116"),
        (protocol_text, "static_assert(sizeof(LevelUpChoicePacket) == 40"),
        (protocol_text, "static_assert(sizeof(LevelUpChoiceResultPacket) == 64"),
        (runtime_state_text, "LocalUdp"),
        (runtime_state_text, "ParticipantOwnedProgressionState"),
        (runtime_state_text, "ParticipantInventoryItemState"),
        (runtime_state_text, "ParticipantProgressionBookEntryState"),
        (runtime_state_text, "inventory_item_total_count"),
        (runtime_state_text, "std::vector<ParticipantInventoryItemState> inventory_items"),
        (runtime_state_text, "progression_book_entry_total_count"),
        (runtime_state_text, "concentration_selection_valid"),
        (runtime_state_text, "ParticipantDerivedStatState"),
        (runtime_state_text, "std::vector<ParticipantProgressionBookEntryState> progression_book_entries"),
        (runtime_state_text, "ability_loadout_valid"),
        (runtime_state_text, "WorldSnapshotRuntimeInfo"),
        (runtime_state_text, "LootSnapshotRuntimeInfo"),
        (runtime_state_text, "LootPickupResultRuntimeInfo"),
        (runtime_state_text, "SpellEffectSnapshotRuntimeInfo"),
        (runtime_state_text, "SpellEffectApplyRuntimeInfo"),
        (runtime_state_text, "std::vector<SpellEffectSnapshotRuntimeInfo> spell_effect_snapshots"),
        (runtime_state_text, "WorldSnapshotApplyRuntimeInfo"),
        (runtime_state_text, "WorldSnapshotActorBindingRuntimeInfo"),
        (runtime_state_text, "ParticipantTransformSample"),
        (runtime_state_text, "transform_history"),
        (runtime_state_text, "world_snapshot_history"),
        (runtime_state_text, "loot_snapshot"),
        (runtime_state_text, "last_loot_pickup_result"),
        (runtime_state_text, "LevelUpOfferRuntimeInfo"),
        (runtime_state_text, "LevelUpChoiceResultRuntimeInfo"),
        (runtime_state_text, "std::uint16_t resulting_active = 0;"),
        (runtime_state_text, "LevelUpWaitStatusRuntimeInfo"),
        (runtime_state_text, "active_level_up_offer"),
        (runtime_state_text, "last_level_up_choice_result"),
        (runtime_state_text, "level_up_wait_status"),
        (runtime_state_text, "kParticipantTransformHistoryCapacity"),
        (runtime_state_text, "kWorldSnapshotHistoryCapacity"),
        (runtime_state_text, "TrySampleParticipantTransform"),
        (runtime_state_text, "TrySampleWorldSnapshot"),
        (runtime_state_text, "InterpolateHeadingDegrees"),
        (runtime_state_text, "float life_current"),
        (runtime_state_text, "float mana_current"),
        (runtime_state_text, "std::uint32_t gold_revision"),
        (runtime_state_text, "inventory_host_authoritative"),
        (runtime_state_text, "float resource_delta"),
        (runtime_state_text, "std::int32_t resource_kind"),
        (runtime_state_text, "float resulting_life_current"),
        (lua_runtime_text, "participant.runtime.position_x"),
        (lua_runtime_text, "participant.runtime.position_y"),
        (lua_gameplay_text, "get_replicated_spell_effects"),
        (transport_text, '#include "multiplayer_local_transport/spell_effect_sync.inl"'),
        (transport_text, "ApplySpellEffectSnapshotPacket(packet, from, now_ms)"),
        (transport_text, "SendSpellEffectSnapshot(now_ms)"),
        (spell_effect_transport_text, "TryCaptureLocalSpellEffectState"),
        (spell_effect_transport_text, "actor.actor_slot != 0"),
        (spell_effect_transport_text, "SpellEffectStateFlagTerminal"),
        (transport_text, "kLocalSpellEffectTombstoneHoldMs = 4000"),
        (spell_effect_transport_text, "RelayPacketBufferToPeers("),
        (spell_effect_reconciliation_text, "MatchReplicatedSpellEffectActor"),
        (spell_effect_reconciliation_text, "owner_gameplay.gameplay_slot"),
        (spell_effect_reconciliation_text, "actor.actor_slot != owner_gameplay_slot"),
        (participant_snapshot_text, "std::int8_t native_actor_slot = -1;"),
        (participant_snapshot_text, "snapshot.actor_slot = static_cast<int>(native_actor_slot);"),
        (spell_effect_reconciliation_text, "TryApplyReplicatedSpellEffectState"),
        (spell_effect_reconciliation_text, "effect.ember_runtime_valid"),
        (spell_effect_reconciliation_text, "effect.terminal"),
        (fireball_explode_verifier_text, "include_client=False"),
        (binary_layout_text, "spell_effect_motion_x=0x13C"),
        (binary_layout_text, "ember_lifetime=0x150"),
        (gameplay_seams_header_text, "kEmberLifetimeOffset"),
        (gameplay_seams_size_bindings_text, "ember_lifetime"),
        (runtime_state_text, "std::uint16_t presentation_flags"),
        (runtime_state_text, "float magic_shield_absorb_remaining"),
        (runtime_state_text, "float magic_shield_absorb_capacity"),
        (runtime_state_text, "float magic_shield_explosion_fraction"),
        (runtime_state_text, "float magic_shield_hit_flash"),
        (runtime_state_text, "float render_drive_overlay_alpha"),
        (runtime_state_text, "float render_drive_move_blend"),
        (runtime_state_text, "actor_total_count"),
        (runtime_state_text, "truncated"),
        (runtime_state_text, "target_authoritative"),
        (runtime_state_text, "created_actor_count"),
        (runtime_state_text, "created_actor_total_count"),
        (runtime_state_text, "presentation_write_count"),
        (runtime_state_text, "health_write_count"),
        (runtime_state_text, "dead_actor_count"),
        (runtime_state_text, "removed_actor_count"),
        (runtime_state_text, "removed_actor_total_count"),
        (runtime_state_text, "failed_remove_actor_count"),
        (runtime_state_text, "failed_remove_actor_total_count"),
        (runtime_state_text, "actor_bindings"),
        (runtime_state_text, "LootDropKindLabel"),
        (transport_header_text, "TickLocalTransport"),
        (transport_header_text, "IsLocalTransportHost"),
        (transport_header_text, "IsLocalTransportClient"),
        (transport_header_text, "GetLocalTransportParticipantId"),
        (transport_header_text, "QueueLocalLootPickupRequest"),
        (transport_header_text, "ObserveReplicatedRunEnemyDamage"),
        (transport_header_text, "PublishHostLevelUpOffers"),
        (transport_header_text, "QueueLocalLevelUpChoice"),
        (transport_header_text, "ShouldPauseMultiplayerGameplay"),
        (transport_header_text, "TryBuildLevelUpWaitStatusText"),
        (transport_text, "SDMOD_MULTIPLAYER_TRANSPORT"),
        (transport_text, "SDMOD_MULTIPLAYER_LOCAL_PORT"),
        (transport_text, "SDMOD_MULTIPLAYER_REMOTE_PORT"),
        (transport_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (transport_text, "RelayParticipantPacketToPeers"),
        (transport_text, "NormalizeMagicShieldState"),
        (transport_text, "kMagicShieldAbsorbEpsilon"),
        (transport_text, "packet->anim_drive_state_word = local.runtime.anim_drive_state_word"),
        (transport_text, "packet->magic_shield_absorb_remaining ="),
        (transport_text, "packet->magic_shield_absorb_capacity ="),
        (transport_text, "packet->magic_shield_explosion_fraction ="),
        (transport_text, "participant->runtime.magic_shield_absorb_remaining ="),
        (transport_text, "participant->runtime.magic_shield_absorb_capacity ="),
        (transport_text, "participant->runtime.magic_shield_explosion_fraction ="),
        (transport_text, "sample.magic_shield_absorb_remaining = normalized.magic_shield_absorb_remaining"),
        (transport_text, "sample.render_drive_overlay_alpha = packet.render_drive_overlay_alpha"),
        (transport_text, "staff attachment tail field at +0x84 is native-owned"),
        (transport_text, "packet.presentation_flags &"),
        (transport_text, "participant->runtime.attachment_staff_visual_state = 0"),
        (transport_text, "BuildLocalWorldSnapshot"),
        (transport_text, "ResolveRunEnemyTargetParticipantId"),
        (transport_text, "target_native_type_id == 1"),
        (transport_text, "target_actor_slot == 0"),
        (transport_text, "PopulateRunEnemyNativeTargetSnapshot"),
        (transport_text, "kActorCurrentTargetBucketDeltaOffset"),
        (transport_text, "WorldActorSnapshotFlagTargetAuthoritative"),
        (transport_text, "snapshot.target_participant_id = ResolveRunEnemyTargetParticipantId(actor.actor_address)"),
        (transport_text, "TryTriggerRunEnemyDeath(target_actor.actor_address"),
        (transport_text, "TryTriggerRunEnemyDeath(actor_address"),
        (transport_text, "kRecentRunEnemyDeathSnapshotHoldMs"),
        (transport_text, "RecentRunEnemyDeathSnapshot"),
        (transport_text, "recent_run_enemy_deaths_by_network_id"),
        (transport_text, "RecordRecentRunEnemyDeathSnapshot"),
        (transport_text, "WorldActorSnapshotFlagDead |"),
        (transport_text, "WorldActorSnapshotFlagTrackedEnemy |"),
        (transport_text, "local_death_called"),
        (transport_text, "(actor.dead || actor.hp > kEnemyDamageClaimHpEpsilon)"),
        (transport_text, "BuildLocalLootSnapshotPacket"),
        (transport_text, "PopulateWorldActorPresentationSnapshot"),
        (transport_text, "student_visual_state"),
        (transport_text, "TryGetRunLifecycleEnemySpawnSerial"),
        (transport_text, "kRunHostLocalWorldActorNetworkIdBase"),
        (transport_text, "kRunLootDropNetworkIdBase"),
        (transport_text, "kOrbRewardNativeTypeId"),
        (transport_text, "kItemDropNativeTypeId"),
        (transport_text, "kSolomonDigNativeTypeId"),
        (transport_text, "IsRunStaticLayoutActor"),
        (transport_text, "run_host_local_world_actor_ids_by_address"),
        (transport_text, "run_loot_drop_ids_by_address"),
        (transport_text, "AllocateRunHostLocalWorldActorNetworkId"),
        (transport_text, "AllocateRunLootDropNetworkId"),
        (transport_text, "PruneRunHostLocalWorldActorNetworkIds"),
        (transport_text, "PruneRunLootDropNetworkIds"),
        (transport_text, "kGoldRewardAmountOffset"),
        (transport_text, "built.flags = built.amount > 0 && lifetime != 0 ? LootDropSnapshotFlagActive : 0"),
        (host_loot_drop_deactivation_text, "kReplicatedGoldAmountOffset"),
        (host_loot_drop_deactivation_text, "kReplicatedGoldLifetimeOffset"),
        (transport_text, "kOrbRewardValueOffset"),
        (transport_text, "kOrbRewardResourceKindOffset"),
        (transport_text, "kOrbHealthRewardScale"),
        (transport_text, "kOrbManaRewardScale"),
        (binary_layout_text, "actor_world_transient_actor_list=0x8B70"),
        (gameplay_seams_header_text, "kActorWorldTransientActorListOffset"),
        (gameplay_seams_size_bindings_text, "actor_world_transient_actor_list"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "AppendTransientRewardActors"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "0x07DB"),
        (transport_text, "assigned host-local run actor network id"),
        (transport_text, "BuildRunWorldActorNetworkId"),
        (transport_text, "ParticipantSceneIntentKind::SharedHub"),
        (transport_text, "ParticipantSceneIntentKind::Run"),
        (transport_text, "actor.tracked_enemy"),
        (transport_text, "TryAcceptWorldSnapshotFragment"),
        (transport_text, "LootSnapshotFlagTruncated"),
        (transport_text, "ApplyWorldSnapshotPacket"),
        (world_snapshot_reconciliation_text, "ResolveReplicatedRunEnemyTargetActor"),
        (world_snapshot_reconciliation_text, "TryReadActorWorldTargetSlotState"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyTarget"),
        (world_snapshot_reconciliation_text, "kActorCurrentTargetActorOffset"),
        (world_snapshot_reconciliation_text, "kHostileTargetBucketDeltaOffset"),
        (world_snapshot_reconciliation_text, "authoritative_actor.target_participant_id"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyTarget("),
        (lua_gameplay_text, "target_participant_id"),
        (lua_gameplay_text, "target_authoritative"),
        (read_text(ROOT / "tools/verify_run_enemy_target_authority.py"), "replicated_target_participant_id"),
        (read_text(ROOT / "tools/verify_run_enemy_target_authority.py"), "start_host_testrun_and_wait_for_clients(timeout=60.0)"),
        (transport_text, "ApplyLootSnapshotPacket"),
        (transport_text, "ApplyLootPickupRequestPacket"),
        (transport_text, "ApplyLootPickupResultPacket"),
        (transport_text, "ApplyLevelUpOfferPacket"),
        (transport_text, "ApplyLevelUpChoicePacket"),
        (transport_text, "ApplyLevelUpChoiceResultPacket"),
        (transport_text, "BuildLevelUpChoiceResultPacket"),
        (transport_text, "packet.resulting_active > 0"),
        (transport_text, "native_applied_level_up_result_offer_ids"),
        (transport_text, "Multiplayer host-self level-up choice resolved and broadcast"),
        (transport_text, "const auto endpoints = BuildKnownSendEndpoints();"),
        (transport_text, "CollectUnresolvedLevelUpOfferParticipantIds"),
        (transport_text, "BuildLevelUpWaitStatusTextFromIds"),
        (transport_text, "PendingHostLevelUpOfferTarget"),
        (transport_text, "pending_level_up_offer_targets_by_participant"),
        (transport_text, "QueuePendingHostLevelUpOfferTarget"),
        (transport_text, "ProcessPendingHostLevelUpOffers"),
        (transport_text, "IsLevelUpOfferMaterializationPendingError"),
        (transport_text, "Multiplayer level-up offer deferred; participant progression not materialized"),
        (transport_text, "ClearLocalLevelUpPickerAfterProgrammaticChoice"),
        (transport_text, "Multiplayer level-up native picker closed and cleared after programmatic accepted choice"),
        (transport_text, "kProgressionLevelUpPickerUiFlagOffset"),
        (transport_text, "kProgressionLevelUpTemporaryPickerObjectOffset"),
        (transport_text, "kProgressionLevelUpTemporaryPickerValueOffset"),
        (transport_text, "TryApplyLocalProgrammaticLevelUpChoiceThroughNativePicker"),
        (transport_text, "CallLevelUpScreenCloseSafe"),
        (transport_text, "Multiplayer level-up native picker applied locally through programmatic choice"),
        (level_up_choice_and_picker_text, "HookLocalLevelUpOptionRoll"),
        (level_up_choice_and_picker_text, "TryOverwriteNativeLevelUpOptions"),
        (level_up_choice_and_picker_text, "ArmLocalLevelUpOptionRoll"),
        (level_up_choice_and_picker_text, "native option roll replaced before visual build"),
        (transport_text, "ShutdownLocalLevelUpOptionRollHook"),
        (skill_picker_visual_identity_verifier_text, "SKILL_VISUAL_IDENTITY_RETURN = 0x0066FE0E"),
        (skill_picker_visual_identity_verifier_text, "visual_option_ids"),
        (skill_picker_visual_identity_verifier_text, "picker_option_ids"),
        (skill_picker_visual_identity_verifier_text, "wait_for_choice_result"),
        (transport_text, "RelayPacketToPeers(result, endpoint)"),
        (transport_text, "HydrateAuthoritativeRemoteProgressionEntryState(\n                    packet.target_participant_id"),
        (transport_text, "SendQueuedLevelUpChoices"),
        (transport_text, "SyncParticipantProgressionToSharedLevelUpAndRollChoices"),
        (transport_text, "ReconcileRemoteParticipantNativeProgression"),
        (transport_text, "kNativeProgressionReconcileAuditMs"),
        (transport_text, "SyncParticipantProgressionToSharedLevelUp("),
        (transport_text, "ReconcileRemoteParticipantNativeProgression(now_ms);"),
        (transport_text, "ApplyAuthoritativeRemoteSkillRankDelta"),
        (transport_text, "ApplyLocalPlayerSkillChoiceOption"),
        (transport_text, "LevelUpChoiceResultCode::InvalidOption"),
        (transport_text, "HasLocalLevelUpOfferAwaitingNativePresentation"),
        (transport_text, "if (HasPendingLocalLevelUpChoice(runtime_state)) {\n        return true;\n    }"),
        (dispatch_pump_loop_text, "allow_level_up_picker_create"),
        (dispatch_pump_loop_text, "HasLocalLevelUpOfferAwaitingNativePresentation"),
        (dispatch_pump_loop_text, "ReconcileLocalLevelUpOfferPresentation(\n            now_ms,\n            allow_level_up_picker_create)"),
        (skill_choices_api_text, "CaptureLocalSharedLevelUpVitals"),
        (skill_choices_api_text, "RestoreLocalSharedLevelUpVitals"),
        (skill_choices_api_text, "local shared level-up sync preserving live vitals"),
        (skill_choices_api_text, "SyncParticipantProgressionToSharedLevelUp("),
        (transport_text, "ValidateLootPickupRequest"),
        (transport_text, "TryPopulateOrbLootDropSnapshot"),
        (transport_text, "TryPopulateItemLootDropSnapshot"),
        (transport_text, "TryReadItemDropHeldItemMetadata"),
        (transport_text, "QueueHostLootDropDeactivation("),
        (transport_text, "ProcessCompletedHostLootPickups();"),
        (host_loot_drop_deactivation_text, "PumpHostLootDropDeactivation()"),
        (host_loot_drop_deactivation_text, "CallActorRequestRetirementSafe("),
        (transport_text, "TryBuildAcceptedOrbLootPickupPayload"),
        (transport_text, "TryBuildAcceptedItemLootPickupPayload"),
        (transport_text, "ApplyOwnedInventoryLootItem"),
        (transport_text, "TryWriteLocalPlayerOrbResource"),
        (transport_text, "last_synced_enemy_hp_by_network_id"),
        (transport_text, "HasReplicatedRunEnemyDamageBaseline"),
        (transport_text, "MarkReplicatedRunEnemyDamageBaseline"),
        (transport_text, "ClearReplicatedRunEnemyDamageBaseline"),
        (transport_text, "ObservedLocalEnemyDamage"),
        (transport_text, "observed_enemy_damage_by_network_id"),
        (transport_text, "recent_local_cast_skill_id"),
        (transport_text, "recent_local_air_chain_target_until_ms"),
        (transport_text, "active.target_network_actor_id == network_actor_id"),
        (transport_text, "kEnemyDamageObservationEpsilon"),
        (transport_text, "kEnemyDamageClaimResultRetryMs"),
        (transport_text, "Multiplayer observed enemy damage reached claim threshold"),
        (transport_text, "Multiplayer observed enemy damage claim sent"),
        (transport_text, "Multiplayer observed enemy damage claim retried"),
        (transport_text, "Multiplayer enemy damage claim suppressed until first authoritative HP baseline"),
        (world_snapshot_reconciliation_text, "const bool has_damage_baseline"),
        (world_snapshot_reconciliation_text, "const bool observed_local_damage"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyDamageObservationEpsilon"),
        (world_snapshot_reconciliation_text, "multiplayer::ObserveReplicatedRunEnemyDamage("),
        (transport_text, "unknown_claim_flags"),
        (transport_text, "const bool target_position_optional"),
        (transport_text, "!target_position_optional &&"),
        (transport_text, "kEnemyDamageClaimFlagTargetPositionOptional"),
        (world_snapshot_reconciliation_text, "float claimed_target_x = authoritative_actor.position_x;"),
        (world_snapshot_reconciliation_text, "TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &local_target_x)"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyHealth(binding.actor.actor_address, authoritative_actor, now_ms)"),
        (transport_text, "TryApplyAcceptedEnemyDamageTargetPosition"),
        (transport_text, "accepted_new_damage"),
        (transport_text, "position_applied="),
        (transport_text, "sdmod::RebindSceneActorCell(target_actor.actor_address"),
        (enemy_damage_claim_verifier_text, 'damage_client_enemy("damage_position")'),
        (enemy_damage_claim_verifier_text, "wait_for_host_position_accept_log"),
        (
            world_snapshot_reconciliation_text,
            "has_damage_baseline &&\n        max_hp_synced &&\n        local_health.hp + kReplicatedRunEnemyDamageObservationEpsilon < authoritative_hp",
        ),
        (world_snapshot_reconciliation_text, "void ClearReplicatedRunActorBindings()"),
        (world_snapshot_reconciliation_text, "void BindReplicatedRunActor"),
        (world_snapshot_reconciliation_text, "void UnbindReplicatedRunActor"),
        (
            world_snapshot_reconciliation_text,
            "for (const auto& binding : g_replicated_run_bindings_by_network_id) {\n        multiplayer::ClearReplicatedRunEnemyDamageBaseline(binding.first);",
        ),
        (world_snapshot_reconciliation_text, "multiplayer::ClearReplicatedRunEnemyDamageBaseline(previous_by_actor->second);"),
        (replicated_loot_reconciliation_text, "kReplicatedLootPotionItemTypeId = 0x1B59"),
        (replicated_loot_reconciliation_text, "kArenaSpawnPotionDropVfuncOffset = 0x148"),
        (replicated_loot_reconciliation_text, "SpawnPotionDropFn"),
        (replicated_loot_reconciliation_text, "ExecuteSpawnReplicatedPotionDropNow"),
        (replicated_loot_reconciliation_text, "drop.drop_kind == multiplayer::LootDropKind::Potion"),
        (replicated_loot_reconciliation_text, "held_item_type_id != drop.item_type_id"),
        (replicated_loot_reconciliation_text, "memory.TryWriteField(held_item_address, kItemSlotOffset, potion_slot)"),
        (replicated_loot_reconciliation_text, "kPotionStackCountOffset,"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"), "using SpawnPotionDropFn"),
        (protocol_text, "std::uint32_t item_type_id;"),
        (protocol_text, "std::int32_t item_slot;"),
        (protocol_text, "std::int32_t stack_count;"),
        (protocol_text, "std::uint32_t inventory_revision;"),
        (binary_layout_text, "orb_pickup=0x005E62E0"),
        (gameplay_seams_header_text, "kOrbPickup"),
        (gameplay_seams_bindings_text, '"orb_pickup", kOrbPickup'),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"), "using OrbPickupTickFn"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"), "using ItemDropPickupTickFn"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"), "kOrbPickupHookMinimumPatchSize"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"), "kItemDropPickupHookMinimumPatchSize"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"), "orb_pickup_hook"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"), "item_drop_pickup_hook"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "HookOrbPickupTick"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "RemoveX86Hook(&g_gameplay_keyboard_injection.orb_pickup_hook)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "HookItemDropPickupTick"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"), "RemoveX86Hook(&g_gameplay_keyboard_injection.item_drop_pickup_hook)"),
        (orb_pickup_hook_text, "ShouldSuppressRemoteParticipantOrbPickup"),
        (orb_pickup_hook_text, "TryQueueReplicatedLootPickupRequest"),
        (
            orb_pickup_hook_text,
            "last_result.result_code == multiplayer::LootPickupResultCode::Accepted",
        ),
        (
            orb_pickup_hook_text,
            "last_result.participant_id == local_transport_participant_id",
        ),
        (
            orb_pickup_hook_text,
            "last_result.result_code == multiplayer::LootPickupResultCode::AlreadyGone",
        ),
        (
            orb_pickup_hook_text,
            "g_replicated_loot_pickup_request_not_before_ms.erase(presentation.network_drop_id)",
        ),
        (orb_pickup_hook_text, "LootDropKind::Orb"),
        (orb_pickup_hook_text, "IsLocalTransportHost()"),
        (orb_pickup_hook_text, "IsNativeRemoteParticipantBinding(&binding)"),
        (orb_pickup_hook_text, "return false;"),
        (orb_pickup_hook_text, "original(self);"),
        (gold_pickup_hook_text, "TryQueueReplicatedLootPickupRequest"),
        (gold_pickup_hook_text, "LootDropKind::Gold"),
        (gold_pickup_hook_text, "client_gold_pickup_tick"),
        (item_drop_pickup_hook_text, "ShouldSuppressRemoteParticipantItemDropPickup"),
        (item_drop_pickup_hook_text, "kItemDropHeldItemOffset"),
        (item_drop_pickup_hook_text, "IsNativeRemoteParticipantBinding(&binding)"),
        (item_drop_pickup_hook_text, "original(self);"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "health_orb"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "mana_orb"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "ExecuteSpawnGoldRewardNow"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "CallSpawnRewardGoldSafe"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "ResolveGameAddressOrZero(kSpawnRewardGold)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "kSpawnRewardDefaultLifetime"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl"), "CallRewardWorldAttachSafe"),
        (transport_text, "QueueHostLootDropDeactivation("),
        (transport_text, "TryWriteLocalGlobalGold"),
        (transport_text, "accepted_loot_pickup_drop_ids"),
        (transport_text, "RefreshOwnedInventoryFromSnapshot"),
        (transport_text, "packet.inventory_item_count"),
        (transport_text, "participant->owned_progression.inventory_items"),
        (transport_text, "ParticipantInventorySnapshotFlagTruncated"),
        (read_mod_loader_header_source(), "SDModInventoryState"),
        (read_mod_loader_header_source(), "kSDModInventorySnapshotMaxItems"),
        (read_mod_loader_header_source(), "TryGetPlayerInventoryState"),
        (binary_layout_text, "gameplay_item_list_root=0x13B8"),
        (binary_layout_text, "gameplay_item_list_count=0x14"),
        (binary_layout_text, "gameplay_item_list_items=0x20"),
        (binary_layout_text, "item_slot=0x1C"),
        (binary_layout_text, "potion_stack_count=0x88"),
        (binary_layout_text, "item_drop_held_item=0x148"),
        (gameplay_seams_header_text, "kGameplayItemListRootOffset"),
        (gameplay_seams_header_text, "kPotionStackCountOffset"),
        (gameplay_seams_header_text, "kItemDropHeldItemOffset"),
        (gameplay_seams_size_bindings_text, "gameplay_item_list_root"),
        (gameplay_seams_size_bindings_text, "item_drop_held_item"),
        (
            read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"),
            "const bool owns_wizard_progression = state.object_type_id == 1;",
        ),
        (
            read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"),
            "} else if (owns_wizard_progression &&",
        ),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "TryGetPlayerInventoryState"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "kGameplayItemListRootOffset"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"), "kSDModInventorySnapshotMaxItems"),
        (lua_gameplay_text, "LuaPlayerGetInventoryState"),
        (lua_gameplay_text, "\"get_inventory_state\""),
        (inventory_audit_verifier_text, "Verify typed local inventory/equip audit"),
        (inventory_audit_verifier_text, "POTION_TYPE_ID = 0x1B59"),
        (inventory_audit_verifier_text, "STAFF_HELPER_TYPE_ID = 0x1B5C"),
        (inventory_audit_verifier_text, "has_inventory_items"),
        (inventory_audit_verifier_text, "has_skillbook_entries"),
        (inventory_audit_verifier_text, "has_spellbook_entries"),
        (inventory_audit_verifier_text, "assert_owned_inventory_rows"),
        (inventory_audit_verifier_text, "inventory_item_count"),
        (inventory_audit_verifier_text, "inventory_host_authoritative"),
        (inventory_audit_verifier_text, "owned inventory missing potion slots"),
        (item_potion_contract_verifier_text, "Verify the multiplayer item/potion pickup contract"),
        (item_potion_contract_verifier_text, "item_drop_held_item=0x148"),
        (item_potion_contract_verifier_text, "TryPopulateItemLootDropSnapshot"),
        (item_potion_contract_verifier_text, "HookItemDropPickupTick"),
        (inventory_audit_verifier_text, "assert_multiplayer_boundary"),
        (lua_runtime_text, "\"inventory_items\""),
        (lua_runtime_text, "\"inventory_item_total_count\""),
        (lua_runtime_text, "\"inventory_host_authoritative\""),
        (lua_gameplay_text, "\"item_type_id\""),
        (lua_gameplay_text, "\"item_slot\""),
        (lua_gameplay_text, "\"stack_count\""),
        (lua_gameplay_text, "\"inventory_revision\""),
        (lua_gameplay_text, "\"resource_kind\""),
        (lua_gameplay_text, "\"resource_delta\""),
        (lua_gameplay_text, "\"resulting_life_current\""),
        (lua_gameplay_text, "\"resulting_mana_current\""),
        (transport_text, "SendLootSnapshot"),
        (transport_text, "SendQueuedLootPickupRequests"),
        (transport_text, "bool automatic_proximity_request = false;"),
        (
            transport_text,
            "request.automatic_proximity_request = capture != nullptr && capture->valid;",
        ),
        (transport_text, "automatic_request_already_terminal"),
        (
            transport_text,
            "last_result.participant_id == g_local_transport.local_peer_id",
        ),
        (
            transport_text,
            "Multiplayer automatic loot pickup retry suppressed after terminal result.",
        ),
        (transport_text, "complete_snapshot.actors.empty() &&"),
        (transport_text, "MaybeQueueClientHostRunStart"),
        (transport_text, "IsAuthoritativeHostParticipantPacket"),
        (transport_text, "packet.participant_id == packet.authority_participant_id"),
        (transport_text, "kClientHostRunFollowRetryMs"),
        (transport_text, "host-authoritative run entry"),
        (transport_text, "SetPendingRunGenerationSeed(packet.run_nonce"),
        (transport_text, "run_generation_seed"),
        (run_generation_seed_helpers_text, "BuildHostRunGenerationSeed"),
        (run_generation_seed_helpers_text, "ApplyPendingRunGenerationSeedForSceneSwitch"),
        (run_generation_seed_helpers_text, "kNativeGlobalRngStateGlobal"),
        (run_generation_seed_helpers_text, "kNativeRngInitialize"),
        (run_generation_seed_helpers_text, "CallNativeRngInitializeSafe"),
        (run_generation_seed_helpers_text, "Initialized host-authoritative run generation RNG"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"), "EnsureHostRunGenerationSeed(\"hub_start_testrun_queue\")"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedWorldSnapshotIfActive"),
        (world_snapshot_reconciliation_text, "authoritative_actor.run_static"),
        (world_snapshot_reconciliation_text, "ApplyHostAuthoritativeRunEntryFormationIfNeeded"),
        (world_snapshot_reconciliation_text, "GetLocalTransportParticipantId"),
        (world_snapshot_reconciliation_text, "kRunEntryFormationNavSnapMaxAuthorityDistance"),
        (world_snapshot_reconciliation_text, "kRunEntryFormationBootstrapMs"),
        (world_snapshot_reconciliation_text, "kRunEntryFormationReapplyIntervalMs"),
        (world_snapshot_reconciliation_text, "g_run_entry_formation_settled"),
        (world_snapshot_reconciliation_text, "BuildLocalReplicatedWorldActorBindings"),
        (world_snapshot_reconciliation_text, "TryCreateReplicatedSharedHubActor"),
        (world_snapshot_reconciliation_text, "IsReplicatedSharedHubFactoryActorType"),
        (world_snapshot_reconciliation_text, "CallGameObjectFactorySafe"),
        (world_snapshot_reconciliation_text, "CallActorWorldRegisterSafe"),
        (world_snapshot_reconciliation_text, "RemoveReplicatedSharedHubActor"),
        (world_snapshot_reconciliation_text, "CallActorWorldUnregisterSafe"),
        (world_snapshot_reconciliation_text, "OverlayLatestWorldSnapshotPresentation"),
        (world_snapshot_reconciliation_text, "kHubAnimationDrivePhaseUnitsPerSecond"),
        (world_snapshot_reconciliation_text, "AdvanceHubAnimationDrivePhase"),
        (world_snapshot_reconciliation_text, "case 0x138F:"),
        (lua_gameplay_text, '"sampled_ms"'),
        (world_snapshot_reconciliation_text, "ApplyReplicatedWorldActorPresentation"),
        (world_snapshot_reconciliation_text, "kStudentVisualStateBlockOffset"),
        (world_snapshot_reconciliation_text, "presentation_write_count"),
        (world_snapshot_reconciliation_text, "removed_actor_count"),
        (world_snapshot_reconciliation_text, "failed_remove_actor_count"),
        (world_snapshot_reconciliation_text, "HasPendingParticipantWorldMutation"),
        (world_snapshot_reconciliation_text, "wizard_bot_sync_not_before_ms"),
        (world_snapshot_reconciliation_text, "pending_participant_sync_requests"),
        (world_snapshot_reconciliation_text, "CanMutateReplicatedSharedHubActors"),
        (world_snapshot_reconciliation_text, "RemoveReplicatedCreatedSharedHubActorsForSceneSwitch"),
        (world_snapshot_reconciliation_text, "abandoned replicated hub actor bindings for scene switch"),
        (world_snapshot_reconciliation_text, "RemoveReplicatedSharedHubActor(binding, &exception_code)"),
        (world_snapshot_reconciliation_text, "abandoned_count"),
        (dispatch_thread_text, "PrepareGameplaySceneSwitchOnGameThread"),
        (dispatch_thread_text, "RemoveReplicatedCreatedSharedHubActorsForSceneSwitch(source)"),
        (dispatch_thread_text, "wizard_bot_sync_not_before_ms.store"),
        (dispatch_thread_text, "pending_participant_sync_requests.clear()"),
        (dispatch_thread_text, "DematerializeAllMaterializedWizardBotsForSceneSwitch(source)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "PrepareGameplaySceneSwitchOnGameThread(\n        gameplay_address,\n        region_index,\n        \"gameplay_switch_region_pre_dispatch\")"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "puppet_manager_delete_puppet skipped object delete during scene churn"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "CallActorWorldUnregisterSafe"),
        (participant_entity_lifecycle_text, "ResetParticipantEntityMaterializationState(&binding)"),
        (participant_entity_lifecycle_text, "PublishParticipantGameplaySnapshot(binding)"),
        (participant_entity_lifecycle_text, "abandoned materialized bot entity for scene switch"),
        (world_snapshot_reconciliation_text, "created_actor_total_count += counts.created_actor_count"),
        (world_snapshot_reconciliation_text, "removed_actor_total_count +="),
        (world_snapshot_reconciliation_text, "failed_remove_actor_total_count +="),
        (world_snapshot_reconciliation_text, "TryRebindActorToOwnerWorld"),
        (world_snapshot_reconciliation_text, "kWorldSnapshotApplyStaleMs"),
        (world_snapshot_reconciliation_text, "kWorldSnapshotInterpolationDelayMs"),
        (world_snapshot_reconciliation_text, "TrySampleWorldSnapshot"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemySoftCorrectionFactor"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyHardSnapDistance"),
        (world_snapshot_reconciliation_text, "soft_correct_live_run_enemy"),
        (enemy_soft_reconciliation_verifier_text, "INJECTED_DRIFT = 96.0"),
        (enemy_soft_reconciliation_verifier_text, "MAX_CORRECTION_STEP = 48.0"),
        (enemy_soft_reconciliation_verifier_text, "correction_step_count"),
        (world_snapshot_reconciliation_text, "ParticipantSceneIntentKind::SharedHub"),
        (world_snapshot_reconciliation_text, "ParticipantSceneIntentKind::Run"),
        (world_snapshot_reconciliation_text, "QueueGameplayStartWaves"),
        (world_snapshot_reconciliation_text, "IsLocalRunCombatAlreadyActive"),
        (world_snapshot_reconciliation_text, "remote_state_wave"),
        (world_snapshot_reconciliation_text, "MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot"),
        (world_snapshot_reconciliation_text, "TryAccelerateRunLifecycleEnemyPoolForSnapshot"),
        (world_snapshot_reconciliation_text, "CountAuthoritativeTrackedRunEnemiesForScene"),
        (world_snapshot_reconciliation_text, "authoritative_counts_by_enemy_type"),
        (world_snapshot_reconciliation_text, "authoritative_actor.tracked_enemy &&"),
        (world_snapshot_reconciliation_text, "local_counts_by_enemy_type"),
        (world_snapshot_reconciliation_text, "authoritative_count - local_count"),
        (world_snapshot_reconciliation_text, "TryBindAuthoritativeRunActorToLocalPool"),
        (world_snapshot_reconciliation_text, "IsSameReplicatedRunEnemyKind"),
        (
            world_snapshot_reconciliation_text,
            "local_actor.object_type_id == authoritative_actor.native_type_id",
        ),
        (
            world_snapshot_reconciliation_text,
            "queued replicated manual run enemy materialization",
        ),
        (world_snapshot_reconciliation_text, "authoritative_actor.player_created"),
        (world_snapshot_reconciliation_text, "BindReplicatedRunActor"),
        (world_snapshot_reconciliation_text, "RecordWorldSnapshotBinding"),
        (world_snapshot_reconciliation_text, "ApplyReplicatedRunEnemyHealth"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyDeathHpEpsilon"),
        (world_snapshot_reconciliation_text, "kReplicatedRunEnemyRemoteDeathHoldMs"),
        (world_snapshot_reconciliation_text, "g_replicated_run_pending_enemy_death_until_ms"),
        (world_snapshot_reconciliation_text, "IsAuthoritativeRunTrackedEnemyDeadSnapshot"),
        (world_snapshot_reconciliation_text, "TryBindAuthoritativeDeadRunEnemyToLocalPool"),
        (world_snapshot_reconciliation_text, "bound authoritative dead run enemy snapshot to local actor"),
        (world_snapshot_reconciliation_text, "IsReplicatedRunEnemyDeathPending"),
        (world_snapshot_reconciliation_text, "!IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor)"),
        (world_snapshot_reconciliation_text, "TryTriggerRunEnemyDeath(actor_address"),
        (world_snapshot_reconciliation_text, "triggered replicated run enemy death"),
        (world_snapshot_reconciliation_text, "kEnemyCurrentHpOffset"),
        (world_snapshot_reconciliation_text, "kEnemyMaxHpOffset"),
        (world_snapshot_reconciliation_text, "snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub"),
        (transport_text, "CopyPacketDisplayName"),
        (transport_text, "QueueParticipantEntitySync"),
        (transport_text, "participant_materialized"),
        (transport_text, "!participant_materialized"),
        (transport_text, "ParticipantControllerKind::Native"),
        (transport_text, "AppendParticipantTransformSample"),
        (transport_text, "AppendWorldSnapshot"),
        (transport_text, "state.loot_snapshot"),
        (transport_text, "TryGetPlayerState"),
        (transport_text, "local->runtime.life_current = player_state.hp"),
        (transport_text, "packet.owned_gold = local->owned_progression.gold"),
        (transport_text, "participant->owned_progression.gold = packet.owned_gold"),
        (transport_text, "packet.gold_revision >= participant->owned_progression.gold_revision"),
        (transport_text, "local->owned_progression.gold_revision += 1"),
        (transport_text, "RefreshOwnedProgressionBookFromSnapshot"),
        (transport_text, "RefreshOwnedAbilityLoadoutFromProfile"),
        (transport_text, "packet.progression_book_entry_count"),
        (transport_text, "participant->owned_progression.progression_book_entries"),
        (state_getters_text, "const bool structural_tail_record ="),
        (state_getters_text, "entry.statbook_max_level > 256"),
        (progression_probe_text, "compare_book_rows"),
        (progression_probe_text, "compare_float_fields"),
        (host_owned_level_up_sync_verifier_text, "snapshot_recovery"),
        (host_owned_level_up_sync_verifier_text, "wait_for_bidirectional_progression_parity"),
        (host_owned_level_up_sync_verifier_text, "target_self"),
        (progression_ledger_sync_verifier_text, "verify_bidirectional_gold_ledger"),
        (progression_ledger_sync_verifier_text, "wait_for_participant_gold"),
        (progression_ledger_sync_verifier_text, "sd.debug.write_i32(address"),
        (progression_ledger_sync_verifier_text, "gold_revision"),
        (gold_pickup_authority_verifier_text, "request_loot_pickup"),
        (gold_pickup_authority_verifier_text, "AlreadyGone"),
        (gold_pickup_authority_verifier_text, "duplicate_rejected_without_second_credit"),
        (orb_pickup_authority_verifier_text, "health_orb"),
        (orb_pickup_authority_verifier_text, "mana_orb"),
        (orb_pickup_authority_verifier_text, "resource_delta"),
        (orb_pickup_authority_verifier_text, "resource_kind"),
        (orb_pickup_authority_verifier_text, "duplicate_rejected_without_second_credit"),
        (lua_gameplay_text, "request_loot_pickup"),
        (lua_gameplay_text, "last_pickup_result"),
        (transport_text, "TryGetWorldState"),
        (transport_text, "packet->wave = local.runtime.wave"),
        (lua_input_text, "host-only while connected to a multiplayer session"),
        (lua_input_text, "QueueGameplayMouseLeftClick(&gameplay_click_error)"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"), "Blocked client run switch_region while connected to multiplayer"),
        (read_text(ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"), "g_multiplayer_client_authorized_hub_run_switch_depth"),
        (service_loop_text, "InitializeLocalTransport()"),
        (service_loop_text, "TickGameplayTransportOnAppThread"),
        (service_loop_text, "ShutdownLocalTransport()"),
        (lua_exec_pipe_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_TRANSPORT"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_PARTICIPANT_ID"),
        (staged_game_launcher_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (staged_game_launcher_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (staged_game_launcher_text, "temporaryProfile"),
        (staged_game_launcher_text, "StageSandboxCompatibilityLinks.Materialize(stage.StageRootPath, options.SavegamesRootPath)"),
        (launcher_command_parser_text, "--temporary-profile"),
        (isolated_profile_bootstrapper_text, "temporary-client-profile"),
        (stage_sandbox_links_text, "savegamesTargetPath"),
        (project_text, "include\\multiplayer_local_transport.h"),
        (project_text, "src\\multiplayer_local_transport.cpp"),
        (project_filters_text, "include\\multiplayer_local_transport.h"),
        (project_filters_text, "src\\multiplayer_local_transport.cpp"),
        (bot_runtime_header_text, "bool ReadParticipantSnapshot"),
        (bot_snapshots_text, "ReadParticipantSnapshot"),
        (read_text(LUA_ENGINE_BOTS_BINDING), "LuaBotsGetParticipantState"),
        (read_text(LUA_ENGINE_BOTS_BINDING), "LuaBotsGetParticipants"),
        (read_text(LUA_ENGINE_BOTS_BINDING), "LuaBotsGetNameplate"),
        (entity_sync_text, "ReadParticipantSnapshot(request.bot_id"),
        (scene_binding_text, "ReadParticipantSnapshot(binding.bot_id"),
        (scene_binding_text, "RefreshNativeRemoteParticipantTransformTarget"),
        (scene_binding_text, "ApplyNativeRemoteParticipantPlayback"),
        (native_remote_playback_text, "ApplyNativeRemoteParticipantPlayback"),
        (native_remote_playback_text, "ApplyNativeRemoteParticipantVitalState"),
        (native_remote_playback_text, "ApplyNativeRemoteParticipantPresentationState"),
        (native_remote_playback_text, "replicated_presentation_valid"),
        (read_text(PLAYER_ACTOR_TICK_HOOK), "binding->ongoing_cast.active && !native_remote_binding"),
        (read_text(PLAYER_ACTOR_TICK_HOOK), "if (!playback.presentation_valid)"),
        (read_text(ACTOR_ANIMATION_ADVANCE_HOOK), "struct AnimationAdvanceContextScope"),
        (read_text(ACTOR_ANIMATION_ADVANCE_HOOK), "~AnimationAdvanceContextScope()"),
        (read_text(PLAYER_ACTOR_TICK_HOOK), "ApplyNativeRemoteParticipantPresentationState(binding, actor_address)"),
        (native_remote_playback_text, "participant->runtime.life_current"),
        (native_remote_playback_text, "kProgressionHpOffset"),
        (native_remote_playback_text, "kProgressionMpOffset"),
        (participant_snapshot_text, "if (multiplayer::IsNativeControlledParticipant(*participant))"),
        (participant_snapshot_text, "participant->runtime.life_current = snapshot.hp"),
        (native_remote_playback_text, "replicated_transform_playback_ms"),
        (native_remote_playback_text, "kRemoteTransformInterpolationDelayMs"),
        (native_remote_playback_text, "TrySampleParticipantTransform"),
        (native_remote_playback_text, "kRemoteSnapDistance"),
        (participant_collision_text, "left.local_player && right.native_remote"),
        (participant_collision_text, "right.local_player && left.native_remote"),
        (participant_collision_text, "cross-instance feedback loop"),
        (participant_collision_text, "if (native_player_pair)"),
        (networking_doc_text, "client-predicted / authority-verified"),
        (networking_doc_text, "SDMOD_MULTIPLAYER_TRANSPORT=local_udp"),
        (networking_doc_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (networking_doc_text, "verify_local_multiplayer_sync.py"),
        (networking_doc_text, "verify_player_health_death_sync.py"),
        (networking_doc_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (networking_doc_text, "player/player"),
        (networking_doc_text, "WorldSnapshot"),
        (networking_doc_text, "LootSnapshot"),
        (networking_doc_text, "sd.world.get_replicated_loot()"),
        (networking_doc_text, "Protocol v30"),
        (networking_doc_text, "Gold, health/mana orbs, item/potion carriers, and powerups have host-authorized request/result ownership"),
        (networking_doc_text, "run-world"),
        (networking_doc_text, "tracked enemies"),
        (networking_doc_text, "bootstrap client wave activation"),
        (networking_doc_text, "accelerates its native wave-spawner timers"),
        (networking_doc_text, "host lifecycle spawn serial"),
        (networking_doc_text, "live HP/max-HP"),
        (networking_doc_text, "run enemy presentation probe"),
        (networking_doc_text, "host-authoritative run entry"),
        (networking_doc_text, "host-authored run generation seed"),
        (networking_doc_text, "run-static prop families"),
        (networking_doc_text, "verify_run_static_layout_sync.py"),
        (networking_doc_text, "connected-client"),
        (networking_doc_text, "empty Run"),
        (networking_doc_text, "one-shot run-entry formation placement"),
        (networking_doc_text, "death-handled byte"),
        (networking_doc_text, "per-family allocation sizes"),
        (networking_doc_text, "Synced host-owned run drops"),
        (networking_doc_text, "sd.player.get_inventory_state()"),
        (networking_doc_text, "tools/verify_multiplayer_inventory_audit.py"),
        (networking_doc_text, "Accepted potions and exact recipe-backed items enter the owning client's stock native inventory"),
        (networking_doc_text, "Observer processes intentionally retain replicated inventory rows"),
        (networking_doc_text, "pickup-request / pickup-result"),
        (networking_doc_text, "bounded full participant-owned inventory item rows"),
        (networking_doc_text, "progression-book/statbook/skillbook/spellbook rows"),
        (networking_doc_text, "Gold, health/mana orbs, item/potion carriers, and powerups have host-authorized request/result ownership"),
        (world_sync_plan_text, "tools/probe_named_hub_npc_fields.py"),
        (world_sync_plan_text, "FUN_00502120"),
        (world_sync_plan_text, "larger player/Student render window"),
        (world_sync_plan_text, "tools/probe_run_enemy_presentation_sync.py"),
        (world_sync_plan_text, "drive word stays zero"),
        (world_sync_plan_text, "WorldActorPresentationFlagLocomotionFloats"),
        (world_sync_plan_text, "death-handled byte"),
        (world_sync_plan_text, "tools/verify_run_enemy_seed_viability.py"),
        (world_sync_plan_text, "stock run-enemy lockstep was rejected"),
        (world_sync_plan_text, "client's native wave spawner as a local"),
        (world_sync_plan_text, "host lifecycle spawn serial"),
        (world_sync_plan_text, "extra_unparked_client_tracked_enemies"),
        (world_sync_plan_text, "tools/probe_run_reward_sync.py"),
        (world_sync_plan_text, "host gold reward actors are visible as native type `0x7DC`"),
        (world_sync_plan_text, "sd.world.get_replicated_loot()"),
        (world_sync_plan_text, "host-confirmed pickup and participant-owned"),
        (named_hub_npc_probe_text, "NAMED_TYPES"),
        (named_hub_npc_probe_text, "FUN_00502450"),
        (named_hub_npc_probe_text, "moving_drive_types"),
        (named_hub_npc_probe_text, "max_drive_phase_distance"),
        (run_enemy_presentation_probe_text, "KILL_HOST_ENEMY_LUA"),
        (run_enemy_presentation_probe_text, "setup_live_run_pair"),
        (run_enemy_presentation_probe_text, "max_drive_byte_mismatches"),
        (run_enemy_presentation_probe_text, "max_snapshot_locomotion_present"),
        (run_enemy_presentation_probe_text, "max_locomotion_mismatches"),
        (run_enemy_presentation_probe_text, "max_snapshot_dead"),
        (run_reward_sync_probe_text, "GOLD_REWARD_TYPE_ID = 0x07DC"),
        (run_reward_sync_probe_text, "park_players_away_from_reward"),
        (run_reward_sync_probe_text, "STATIONARY_REWARD_MIN_PLAYER_DISTANCE"),
        (run_reward_sync_probe_text, "current_world_snapshot_excludes_gold_drops"),
        (run_reward_sync_probe_text, "client_receives_host_loot_metadata"),
        (run_reward_sync_probe_text, "client_materializes_host_loot_actor"),
        (run_reward_sync_probe_text, "loot_gold.count"),
        (run_reward_sync_probe_text, "wait_for_client_replicated_loot"),
        (run_reward_sync_probe_text, "pickup_authority_is_participant_owned"),
        (lua_gameplay_text, "LuaWorldGetReplicatedLoot"),
        (lua_gameplay_text, '"get_replicated_loot"'),
        (lua_runtime_text, "LuaRuntimeGetMultiplayerState"),
        (lua_runtime_text, '"get_multiplayer_state"'),
        (lua_runtime_text, "PushLevelUpOfferRuntimeInfo"),
        (lua_runtime_text, "PushLevelUpChoiceResultRuntimeInfo"),
        (lua_runtime_text, "PushLevelUpWaitStatusRuntimeInfo"),
        (lua_runtime_text, '"active_level_up_offer"'),
        (lua_runtime_text, '"last_level_up_choice_result"'),
        (lua_runtime_text, '"level_up_wait_status"'),
        (lua_runtime_text, "LuaRuntimeChooseLevelUpOption"),
        (lua_runtime_text, '"choose_level_up_option"'),
        (lua_runtime_text, "LuaRuntimeDebugPublishLevelUpOffer"),
        (lua_runtime_text, '"debug_publish_level_up_offer"'),
        (level_up_offer_sync_verifier_text, "debug_publish_level_up_offer"),
        (level_up_offer_sync_verifier_text, "choose_level_up_option"),
        (level_up_offer_sync_verifier_text, "client_progression_mode"),
        (level_up_offer_sync_verifier_text, "client_picker_screen"),
        (level_up_offer_sync_verifier_text, "verify_level_up_offer_sync"),
        (run_lifecycle_level_hooks_text, "suppress_client_local_level_up"),
        (run_lifecycle_level_hooks_text, "kProgressionNonLocalModeValue"),
        (run_lifecycle_level_hooks_text, "PublishHostLevelUpBarrierOffers"),
        (run_seed_verifier_text, "stock_run_enemy_lockstep_viable"),
        (run_seed_verifier_text, "global_seed_as_primary_sync_recommended"),
        (run_seed_verifier_text, "tracked_count_sequence_diverged"),
        (run_seed_verifier_text, "launch_isolated_pair"),
        (run_snapshot_verifier_text, "run_lifecycle_status"),
        (run_snapshot_verifier_text, "authoritative_actors_matched"),
        (run_snapshot_verifier_text, "host_only_snapshot_actors"),
        (run_snapshot_verifier_text, "extra_client_tracked_enemies"),
        (run_snapshot_verifier_text, "extra_unparked_client_tracked_enemies"),
        (run_snapshot_verifier_text, "parked_client_tracked_enemies"),
        (run_snapshot_verifier_text, "matched_binding_count"),
        (run_snapshot_verifier_text, "lifecycle_owned_snapshot_actors"),
        (run_snapshot_verifier_text, "--require-complete-lifecycle"),
        (participant_doc_text, "RemoteParticipant + Native"),
        (participant_doc_text, "native-remote playback"),
        (participant_doc_text, "push both actors"),
        (participant_doc_text, "sd.bots.get_participants()"),
        (participant_doc_text, "sd.bots.get_nameplate(actor_address)"),
        (participant_doc_text, "Participant-Owned Inventory And Books"),
        (participant_doc_text, "ParticipantOwnedProgressionState"),
        (participant_doc_text, "gold revision"),
        (participant_doc_text, "host-authorized gold, health/mana orbs, and"),
        (participant_doc_text, "configured host reports `in_run`"),
        (participant_doc_text, "sd.runtime.get_multiplayer_state()"),
        (participant_doc_text, "inventory root and equipment sinks"),
        (participant_doc_text, "spellbook unlock/upgrade state"),
        (participant_doc_text, "statbook allocation/upgrade state"),
        (participant_doc_text, "sd.player.get_inventory_state()"),
        (participant_doc_text, "sd.player.get_progression_book_state()"),
        (participant_doc_text, "read-only native inventory audit surface"),
        (participant_doc_text, "Observers retain the authoritative participant rows"),
        (participant_doc_text, "Local UDP protocol v30 mirrors bounded full participant-owned"),
        (inventory_item_doc_text, "tools/probe_run_reward_sync.py --attempts 3"),
        (inventory_item_doc_text, "sd.world.get_replicated_loot()"),
        (inventory_item_doc_text, "sd.player.get_inventory_state()"),
        (inventory_item_doc_text, "tools/verify_multiplayer_inventory_audit.py"),
        (inventory_item_doc_text, "item row count, item pointer array address"),
        (inventory_item_doc_text, "local UDP `StatePacket` protocol v30 introduced a bounded full participant-owned"),
        (inventory_item_doc_text, "participant-owned progression-book/statbook/skillbook/"),
        (inventory_item_doc_text, "participant-owned starter potion rows"),
        (inventory_item_doc_text, "by exact item type and recipe identity"),
        (inventory_item_doc_text, "not a valid\n\"available for pickup\" predicate"),
        (inventory_item_doc_text, "verify_multiplayer_orb_pickup_authority.py --attempts 3"),
        (inventory_item_doc_text, "`0x005E6B50` -> `ItemDropActor_TickPickup`"),
        (inventory_item_doc_text, "`sd.player.equip_inventory_item(recipe_uid)`"),
        (inventory_item_doc_text, "tools/verify_multiplayer_native_item_inventory_sync.py"),
        (inventory_item_doc_text, "host snapshots `drop + 0x148` held-item metadata"),
        (binary_layout_text, "item_drop_pickup=0x005E6B50"),
        (binary_layout_text, "native_global_rng_state=0x00818B08"),
        (binary_layout_text, "native_rng_initialize=0x00401120"),
        (binary_layout_text, "window_input_scale_x=0x00818678"),
        (binary_layout_text, "window_input_scale_y=0x0081867C"),
        (background_focus_text, "UpdateWindowInputScale"),
        (background_focus_text, "IsMouseInputMessage"),
        (background_focus_text, "FindCurrentProcessMainWindow"),
        (background_focus_text, "WM_WINDOWPOSCHANGED"),
        (background_focus_text, "Updated SolomonDark window input scale"),
        (background_focus_text, "kWindowInputScaleXGlobal"),
        (background_focus_text, "kWindowInputScaleYGlobal"),
        (gameplay_seams_header_text, "kWindowInputScaleXGlobal"),
        (gameplay_seams_header_text, "kWindowInputScaleYGlobal"),
        (gameplay_seams_header_text, "kNativeGlobalRngStateGlobal"),
        (gameplay_seams_header_text, "kNativeRngInitialize"),
        (gameplay_seams_bindings_text, '"window_input_scale_x", kWindowInputScaleXGlobal'),
        (gameplay_seams_bindings_text, '"window_input_scale_y", kWindowInputScaleYGlobal'),
        (gameplay_seams_bindings_text, '"native_global_rng_state", kNativeGlobalRngStateGlobal'),
        (gameplay_seams_bindings_text, '"native_rng_initialize", kNativeRngInitialize'),
        (gameplay_seams_header_text, "kItemDropPickupCaller"),
        (gameplay_seams_bindings_text, '"item_drop_pickup", kItemDropPickupCaller'),
        (script_text, "local-mp-host"),
        (script_text, "local-mp-client"),
        (script_text, "[string]$HostPreset"),
        (script_text, "[string]$ClientPreset"),
        (script_text, "$effectiveHostPreset"),
        (script_text, "$effectiveClientPreset"),
        (script_text, '$hostLaunchPreset = "create_manual"'),
        (script_text, '$clientLaunchPreset = "create_manual"'),
        (read_text(ROOT / "mods/lua_ui_sandbox_lab/scripts/lib/setup.lua"), 'active_preset == "create_manual"'),
        (script_text, "SDMOD_MULTIPLAYER_PLAYER_NAME"),
        (script_text, "SDMOD_LUA_EXEC_PIPE_NAME"),
        (script_text, "multiplayer.steam_bootstrap=false"),
        (script_text, "--temporary-profile"),
        (script_text, "[switch]$AllowFocusSteal"),
        (script_text, "$showNoActivate = 4"),
        (script_text, "if ($AllowFocusSteal) {"),
        (script_text, "Window click fallback requires -AllowFocusSteal"),
        (script_text, "allowFocusSteal = [bool]$AllowFocusSteal"),
        (verifier_text, "wait_for_remote"),
        (verifier_text, "nudge_player"),
        (verifier_text, "wait_for_remote_convergence"),
        (verifier_text, "wait_for_local_transform_settled"),
        (verifier_text, "heading_tolerance: float = 0.25"),
        (verifier_text, "observed-motion heading"),
        (verifier_text, 'emit(prefix .. "actor_heading", actor_heading(peer.actor_address))'),
        (verifier_text, "heading_distance(actor_heading, expected_heading)"),
        (verifier_text, "verify_native_remote_overlap_policy"),
        (verifier_text, "skip_local_native_remote_push_to_avoid_replication_feedback"),
        (verifier_text, "sd.bots.get_nameplate"),
        (verifier_text, "sd.hub.start_testrun"),
        (verifier_text, "assert_client_start_testrun_blocked"),
        (verifier_text, "start_host_testrun_and_wait_for_clients"),
        (verifier_text, "verify_run_entry_bootstrap"),
        (verifier_text, "client_replicated_scene_kind"),
        (verifier_text, "client_followed_host"),
        (run_snapshot_verifier_text, "start_host_testrun_and_wait_for_clients"),
        (run_static_layout_verifier_text, "start_host_testrun_and_wait_for_clients"),
        (run_static_layout_verifier_text, "circle_digest"),
        (run_static_layout_verifier_text, "circle_mask4_digest"),
        (run_static_layout_verifier_text, "circle_mask4_count"),
        (run_static_layout_verifier_text, "shape_digest"),
        (run_static_layout_verifier_text, "static_actor_digest"),
        (run_static_layout_verifier_text, "local_run_nonce"),
        (player_health_death_verifier_text, "DEAD_CORPSE_DRIVE_STATE"),
        (player_health_death_verifier_text, "set_local_player_vitals"),
        (player_health_death_verifier_text, "assert_dead_remote_ignores_transform"),
        (player_health_death_verifier_text, "assert_restored_remote_follows_transform"),
        (player_health_death_verifier_text, "launch_trio"),
        (player_health_death_verifier_text, "VITAL_SYNC_TOLERANCE = 0.25"),
        (player_health_death_verifier_text, "host_to_client"),
        (player_health_death_verifier_text, "host_to_third"),
        (player_health_death_verifier_text, "client_to_host"),
        (player_health_death_verifier_text, "client_to_third"),
        (player_health_death_verifier_text, "third_to_host"),
        (player_health_death_verifier_text, "third_to_client"),
        (player_health_death_verifier_text, '"observer_relationship_count": 6'),
        (run_enemy_presentation_probe_text, "start_host_testrun_and_wait_for_clients"),
        (run_reward_sync_probe_text, "start_host_testrun_and_wait_for_clients"),
        (transport_text, "std::fabs(local_actor.max_hp - authoritative_max_hp)"),
        (world_snapshot_reconciliation_text, "max_hp_synced"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if re.search(
        r"claimed_target_y,\s*true\)",
        world_snapshot_reconciliation_text,
    ) is None:
        missing.append("enemy damage claims preserve a validated target position")
    native_remote_vital_guard = participant_snapshot_text.find(
        "if (multiplayer::IsNativeControlledParticipant(*participant))"
    )
    gameplay_snapshot_vital_feedback = participant_snapshot_text.find(
        "participant->runtime.life_current = snapshot.hp"
    )
    if not (0 <= native_remote_vital_guard < gameplay_snapshot_vital_feedback):
        missing.append(
            "native remote participant snapshot guard before gameplay vitals write"
        )
    if "built.flags = active != 0 ? LootDropSnapshotFlagActive : 0" in transport_text:
        missing.append("gold loot availability must not use the +0x148 state byte")
    if "ExecuteHostLootDropDeactivationNow(" not in host_loot_drop_deactivation_text:
        missing.append("gameplay-thread loot deactivation helper")
    if "CallActorRequestRetirementSafe(" not in host_loot_drop_deactivation_text:
        missing.append("accepted loot must enter the stock deferred-retirement lifecycle")
    if "CallActorRequestRetirementSafe(" not in replicated_loot_reconciliation_text:
        missing.append("client loot must enter the stock deferred-retirement lifecycle")
    if "CallActorWorldUnregisterSafe(" in host_loot_drop_deactivation_text:
        missing.append("accepted loot must not unregister actors while stock readers retain them")
    if "CallActorWorldUnregisterSafe(" in replicated_loot_reconciliation_text:
        missing.append("client loot cleanup must not unregister actors while stock readers retain them")
    if "ParkReplicatedLootPresentationActor" in host_loot_drop_deactivation_text:
        missing.append("host loot deactivation must not park native drop actors")
    if "ParkReplicatedLootPresentationActor" in replicated_loot_reconciliation_text:
        missing.append("client loot cleanup must not park native drop actors")
    if "g_client_non_authoritative_loot_suppressed_actors" in replicated_loot_reconciliation_text:
        missing.append("client loot cleanup must not retain suppressed actor tombstones")
    if "RemoveReplicatedLootPresentationActor(binding, &exception_code)" not in replicated_loot_reconciliation_text:
        missing.append("unbound client loot cleanup must unregister native drop actors")
    if "kItemDropHeldItemOffset" in host_loot_drop_deactivation_text:
        missing.append("item/potion loot deactivation must not null the native held-item pointer")
    if "CallActorWorldUnregisterSafe(" in transport_text:
        missing.append("network service thread must not mutate native world containers")
    if missing:
        raise StaticReTestFailure(
            "local multiplayer transport wiring missing token(s): " + ", ".join(missing))

    # TryListSceneActors includes the 0xFA1 hub scene/runtime record alongside
    # actual factory actors. Treating every finite shared-hub record as an
    # actor lets reconciliation write actor offsets into that scene record and
    # leaves stock code executing through its map-config pointer. Keep capture,
    # local binding, packet consumption, and pool binding independently guarded
    # so a future broadening at any one boundary cannot reintroduce that crash.
    shared_hub_actor_guards = (
        (
            transport_text,
            "ShouldReplicateWorldActor",
            r"IsSharedHubFactoryActorType\s*\(\s*actor\.object_type_id\s*\)",
        ),
        (
            world_snapshot_reconciliation_text,
            "ShouldReconcileLocalWorldActor",
            r"IsReplicatedSharedHubFactoryActorType\s*\(\s*actor\.object_type_id\s*\)",
        ),
        (
            world_snapshot_reconciliation_text,
            "ShouldUseAuthoritativeWorldActorForScene",
            r"IsReplicatedSharedHubFactoryActorType\s*\(\s*actor\.native_type_id\s*\)",
        ),
        (
            world_snapshot_reconciliation_text,
            "TryBindAuthoritativeSharedHubActorToLocalPool",
            r"IsReplicatedSharedHubFactoryActorType\s*"
            r"\(\s*authoritative_actor\.native_type_id\s*\)",
        ),
    )
    for source_text, function_name, required_guard in shared_hub_actor_guards:
        function_match = re.search(
            rf"(?:bool|std::vector<[^>]+>)\s+{function_name}\s*"
            rf"\([^)]*\)\s*\{{(?P<body>.*?)\n\}}",
            source_text,
            re.DOTALL,
        )
        if function_match is None:
            raise StaticReTestFailure(
                f"shared-hub actor safety function missing: {function_name}"
            )
        if re.search(required_guard, function_match.group("body")) is None:
            raise StaticReTestFailure(
                f"{function_name} must restrict shared-hub records to native factory actor types"
            )
    scene_switch_cleanup = re.search(
        r"void\s+RemoveReplicatedCreatedSharedHubActorsForSceneSwitch\s*"
        r"\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        world_snapshot_reconciliation_text,
        re.DOTALL,
    )
    if scene_switch_cleanup is None:
        raise StaticReTestFailure("scene-switch replicated hub actor cleanup function missing")
    scene_switch_cleanup_body = scene_switch_cleanup.group("body")
    forbidden_scene_switch_cleanup = [
        token for token in (
            "RemoveReplicatedSharedHubActor(",
            "CallActorWorldUnregisterSafe",
            "CallObjectDeleteSafe",
        )
        if token in scene_switch_cleanup_body
    ]
    if forbidden_scene_switch_cleanup:
        raise StaticReTestFailure(
            "scene-switch replicated hub cleanup must abandon bindings and let native teardown own actors: " +
            ", ".join(forbidden_scene_switch_cleanup))
    actor_lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    switch_region_hook = re.search(
        r"void\s+__fastcall\s+HookGameplaySwitchRegion\s*"
        r"\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        actor_lifecycle_text,
        re.DOTALL,
    )
    if switch_region_hook is None:
        raise StaticReTestFailure("gameplay switch-region hook missing")
    switch_region_body = switch_region_hook.group("body")
    if "tracked_standalone_scene_churn_actor" not in actor_lifecycle_text:
        raise StaticReTestFailure(
            "world_unregister hook must reset tracked standalone wizard bindings after any scene-churn unregister")
    if "PrepareGameplaySceneSwitchOnGameThread(" not in switch_region_body:
        raise StaticReTestFailure(
            "scene switch must run the shared scene-switch preparation helper")
    if "KeepMaterializedWizardBotsForNativeSceneTeardown" in actor_lifecycle_text:
        raise StaticReTestFailure(
            "scene switch must not preserve materialized remote wizard bindings for native teardown")
    if "DematerializeAllMaterializedWizardBotsForSceneSwitch(source)" not in dispatch_thread_text:
        raise StaticReTestFailure(
            "shared scene-switch preparation must dematerialize materialized remote wizard bindings")
    if "puppet_manager_delete_puppet skipped object delete during scene churn" not in actor_lifecycle_text:
        raise StaticReTestFailure(
            "tracked standalone remote wizard scene teardown must skip the native object delete/free path")
    allow_focus_gate = script_text.find("if ($AllowFocusSteal) {")
    foreground_call = script_text.find(
        "[void][SolomonDarkWindowActivator]::SetForegroundWindow")
    if allow_focus_gate < 0 or foreground_call < allow_focus_gate:
        raise StaticReTestFailure(
            "local multiplayer pair launcher must keep SetForegroundWindow behind -AllowFocusSteal")
    fallback_guard = script_text.find("Window click fallback requires -AllowFocusSteal")
    activate_flag = script_text.find("--activate")
    if fallback_guard < 0 or activate_flag < fallback_guard:
        raise StaticReTestFailure(
            "local multiplayer pair launcher must guard activate-click fallback behind -AllowFocusSteal")
    gameplay_click_queue = lua_input_text.find("QueueGameplayMouseLeftClick(&gameplay_click_error)")
    window_foreground_fallback = lua_input_text.find("SetForegroundWindow(window)")
    if not (0 <= gameplay_click_queue < window_foreground_fallback):
        raise StaticReTestFailure(
            "Lua input clicks must try the no-focus gameplay queue before foreground window fallback")
    if "latest runtime snapshot" in networking_doc_text:
        raise StaticReTestFailure("networking docs still describe latest-packet playback instead of interpolation history")
    forbidden_networking_tokens = (
        "Non-gold inventory stays SP",
        "Gold-only drops",
        "Inventory replication beyond gold",
    )
    present_networking_regressions = [
        token for token in forbidden_networking_tokens if token in networking_doc_text
    ]
    if present_networking_regressions:
        raise StaticReTestFailure(
            "networking docs still describe loot as single-player/gold-only: " +
            ", ".join(present_networking_regressions))

    return "local UDP dev transport is wired through protocol, service loop, interpolated participant/world sync, docs, and launch script"
