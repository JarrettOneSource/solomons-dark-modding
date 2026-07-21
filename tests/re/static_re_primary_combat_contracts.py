"""Native primary spell, mana, and cast admission contracts."""

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
    BINARY_LAYOUT,
    BOT_MANA_TRACE_HELPERS,
    BOT_MANA_WRITER_LIVE_PROBE,
    BOT_NATIVE_MANA_SPEND_LIVE_PROBE,
    BOT_OUT_OF_MANA_REJECTION_LIVE_PROBE,
    BOT_RUNTIME_DEFAULTS_AND_LOOKUP,
    BOT_RUNTIME_HEADER,
    BOT_RUNTIME_LIFECYCLE_API,
    BOT_RUNTIME_SNAPSHOTS_API,
    BOT_SNAPSHOT_BUILDERS,
    BOULDER_PROJECTION,
    BOULDER_RETARGET_LIVE_PROBE,
    CASTING_API,
    CAST_PROBE_STATE,
    CAST_RELEASE_HELPERS,
    LUA_ENGINE_PARSER_SNAPSHOTS,
    MOD_LOADER_PROJECT,
    MOD_LOADER_PROJECT_FILTERS,
    NATIVE_SEAM_PLAN,
    NATIVE_SPELL_STATS_HEADER,
    NATIVE_STATBOOKS_CPP,
    NATIVE_STATBOOKS_HEADER,
    PENDING_CAST_PREPARATION,
    PENDING_CAST_PROCESSING,
    PUBLIC_API_DEBUG_AND_SPAWN,
    PURE_PRIMARY_STARTUP_LIVE_PROBE,
    RESOURCE_STATE,
    ROOT,
    SCENE_ANIMATION_GAMEPLAY_STATE,
    SCENE_SELECTION,
    StaticReTestFailure,
    read_native_spell_stats_source,
    read_text,
)

def test_primary_mana_resolver_uses_native_live_spell_stats() -> str:
    casting_text = read_text(CASTING_API)
    helper_header_text = read_text(NATIVE_SPELL_STATS_HEADER)
    helper_cpp_text = read_native_spell_stats_source()
    project_text = read_text(MOD_LOADER_PROJECT)
    filters_text = read_text(MOD_LOADER_PROJECT_FILTERS)
    layout_text = read_text(BINARY_LAYOUT)
    combined_text = "\n".join((casting_text, helper_header_text, helper_cpp_text, project_text, filters_text))

    forbidden_tokens = (
        "kFireMana",
        "kWaterMana",
        "kEarthMana",
        "kAirMana",
        "kEtherMana",
        "kPrimaryManaTables",
        "TryGetWizardSkillFloatValue",
        "native_statbooks",
        "fireball.cfg",
        "frost_jet.cfg",
        "boulder.cfg",
        "lightning.cfg",
        "magic_missile.cfg",
    )
    present_forbidden = [token for token in forbidden_tokens if token in combined_text]
    if present_forbidden:
        raise StaticReTestFailure(
            "primary mana resolution still references staged or hardcoded stat data: " +
            ", ".join(present_forbidden))

    lingering_files = [
        str(path.relative_to(ROOT)) for path in (NATIVE_STATBOOKS_HEADER, NATIVE_STATBOOKS_CPP)
        if path.exists()
    ]
    if lingering_files:
        raise StaticReTestFailure(
            "staged statbook resolver file(s) still exist: " + ", ".join(lingering_files))

    required_helper_tokens = (
        "SkillsWizardBuildPrimarySpellFn",
        "CallSkillsWizardBuildPrimarySpellSafe",
        "TryReadNativePrimaryStatOutputs",
        "TryResolveNativePrimarySpellStats",
        "NativePrimarySpellStats",
        "kProgressionPrimaryStatValuesOffset",
        "kProgressionPrimaryStatCountOffset",
        "kProgressionLevelOffset",
        "kProgressionCurrentSpellIdOffset",
    )
    missing_helper = [token for token in required_helper_tokens if token not in helper_cpp_text + helper_header_text]
    if missing_helper:
        raise StaticReTestFailure(
            "native primary spell stat helper is missing token(s): " +
            ", ".join(missing_helper))

    required_casting_tokens = (
        "uintptr_t progression_runtime_address",
        "TryResolveNativePrimarySelectionForProfile",
        "TryResolveNativePrimarySelectionFromSkillId",
        "TryResolveNativePrimarySpellStats",
        "progression_level",
        "mana_cost",
    )
    missing_casting = [token for token in required_casting_tokens if token not in casting_text]
    if missing_casting:
        raise StaticReTestFailure(
            "bot mana resolver is not wired to live progression/native spell stats: " +
            ", ".join(missing_casting))

    required_layout_tokens = (
        "progression_primary_stat_values=0x774",
        "progression_primary_stat_count=0x778",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "binary layout is missing native primary stat output offset(s): " +
            ", ".join(missing_layout))

    return "primary mana resolver uses live Skills_Wizard primary stat outputs"


def test_earth_boulder_damage_uses_native_live_spell_stats() -> str:
    resource_text = read_text(RESOURCE_STATE)
    projection_text = read_text(BOULDER_PROJECTION)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl")
    active_object_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/native_active_spell_object_state.inl")
    release_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/release_and_latch_helpers.inl")
    entity_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_entity_state.inl")
    layout_text = read_text(BINARY_LAYOUT)
    combined_text = "\n".join(
        (resource_text, projection_text, processing_text, active_object_text,
         release_text, entity_state_text, layout_text))

    forbidden_tokens = (
        "kEarthBoulderBaseDamageByLevel",
        "TryGetWizardSkillFloatValue",
        "boulder.cfg",
        "ReadEarthBoulderRequestedStatbookLevel",
        "statbook_damage",
        "statbook_level",
        "mana_statbook_level",
        "bounded_release_statbook_damage",
        "native_damage_context_ready",
        "native_damage_scale_query_positive",
        "earth_damage_threshold_reached",
        "bounded_release_at_damage_threshold",
        "damage_threshold_released",
        "kBoundedHeldDamageThresholdPostReleaseWorldUpdateTicks",
        "native_cleanup_release",
        "release_damage_native",
    )
    present_forbidden = [token for token in forbidden_tokens if token in combined_text]
    if present_forbidden:
        raise StaticReTestFailure(
            "Earth boulder damage still carries staged-statbook naming or data flow: " +
            ", ".join(present_forbidden))
    required_tokens = (
        "ResolveEarthBoulderBaseDamage",
        "NativePrimarySpellSelection",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "ResolveNativePrimaryEntryForElement",
        "TryResolveNativePrimarySpellStats",
        "ReadBotNativeActiveSpellObjectState",
        "kSpellObjectReleaseDamageOffset",
        "kSpellObjectReleaseBaseDamageOffset",
        "spell_object_release_damage=0x1F4",
        "spell_object_release_base_damage=0x1F8",
        "active_spell_state.release_base_damage",
        "obj_release_base_damage",
        "earth_max_size_reached",
        "earth_target_lethal_release_ready",
        "ResolveEarthBoulderDamageOutputScale",
        "ResolveEarthBoulderReleaseDamageScale",
        "ResolveEarthBoulderReleaseDamageFloor",
        "ResolveEarthBoulderReleaseDamageCapScale",
        "kEarthBoulderDamageOutputScaleGlobal",
        "kEarthBoulderReleaseDamageScaleGlobal",
        "kEarthBoulderReleaseDamageFloorGlobal",
        "kEarthBoulderReleaseDamageCapScaleGlobal",
        "earth_boulder_release_damage_scale",
        "earth_boulder_release_damage_floor",
        "earth_boulder_release_damage_cap_scale",
        "ongoing.bounded_release_requested",
        "ongoing.bounded_release_target_lethal",
        "kBoundedHeldPostReleaseWorldUpdateTicks",
        "kActorPrimaryActionLatchE4Offset",
        "kActorPostGateActiveByteOffset",
        "kSpellObjectGrowthRateOffset",
        "release_growth_stop",
        "progression_level",
        "base_damage",
        "projected_damage",
        "damage_output_scale",
        "projected_release_damage",
        "projected_hp_damage",
        "projection_target_in_impact",
        "release_charge_write",
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "Earth boulder damage is not backed by native live spell stats: " +
            ", ".join(missing))
    if "ResolveEarthBoulderBaseDamage(" in projection_text:
        raise StaticReTestFailure(
            "held Boulder projection still rebuilds native spell stats instead of reading the live Boulder release base")
    return "Earth boulder damage resolver uses live Boulder release fields and named native stat seams"


def test_boulder_projection_is_read_only_native_formula() -> str:
    projection_text = read_text(BOULDER_PROJECTION)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    forbidden_tokens = (
        "impact_context_write",
        "impact_context_x",
        "impact_context_y",
        "impact_context_radius",
        "0x8BCC",
        "0x8BD0",
        "0x8BD4",
        "0x8BD8",
        "TryWriteField<",
    )
    present = [token for token in forbidden_tokens if token in projection_text]
    if present:
        raise StaticReTestFailure(
            "boulder projection still writes guessed native query context: " +
            ", ".join(present))
    required_projection_tokens = (
        "native_secondary_reach_radius",
        "object_radius * release_charge * 2.0f",
        "candidate.target_radius * candidate.target_radius",
        "World_QueryRadius uses distance^2",
        "target_distance_squared < native_secondary_reach_radius_squared",
        "native_radius_damage_eligible",
        "base_damage * snapshot.charge * snapshot.charge",
        "ProjectEarthBoulderReleaseDamage",
        "FindBestNativeBoulderImpactVictim",
        "TryListSceneActors",
        "native_boulder_impact_victim_scan",
        "!candidate.native_radius_damage_eligible",
        "native_base_damage * release_damage_scale",
        "snapshot.projected_release_damage",
        "snapshot.projected_hp_damage",
        "snapshot.projected_hp_damage = snapshot.projected_release_damage",
    )
    required_processing_tokens = (
        "earth_target_lethal_release_ready",
        "earth_native_min_release_charge_reached",
        "ResolveEarthBoulderReleaseGrowthStopMinCharge",
        "min_release_ready",
        "earth_damage_projection.target_actor != 0",
        "earth_damage_projection.projected_hp_damage + 0.001f >= earth_damage_projection.target_hp",
        "target_lethal_released",
        "projection_target_in_impact",
        "kBoundedHeldPostReleaseWorldUpdateTicks =\n            kBoundedHeldNativeReleaseEdgeTicks + 8",
    )
    missing = [token for token in required_projection_tokens if token not in projection_text]
    missing += [token for token in required_processing_tokens if token not in processing_text]
    if missing:
        raise StaticReTestFailure(
            "boulder projection is missing native formula/release guard token(s): " +
            ", ".join(missing))
    target_lethal_guard = re.search(
        r"const bool earth_target_lethal_release_ready =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if target_lethal_guard is None:
        raise StaticReTestFailure("boulder target-lethal release guard was not found")
    if "native_radius_damage_eligible" in target_lethal_guard.group("body"):
        raise StaticReTestFailure(
            "target-lethal Boulder release should use live target HP and native projected damage without requiring current center-overlap")
    if "earth_native_min_release_charge_reached" not in target_lethal_guard.group("body"):
        raise StaticReTestFailure(
            "target-lethal Boulder release must wait for the native minimum release charge")
    remote_release_guard = re.search(
        r"const bool remote_bounded_release_ready =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if remote_release_guard is None:
        raise StaticReTestFailure("remote Boulder release guard was not found")
    if "earth_native_min_release_charge_reached" not in remote_release_guard.group("body"):
        raise StaticReTestFailure(
            "remote Boulder release must wait for the native minimum release charge")
    return "Earth boulder projection stays read-only and drives target-lethal release"


def test_boulder_held_charge_tracks_live_target_until_release() -> str:
    skill_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/skill_selection_rules.inl"
    )
    projection_text = read_text(BOULDER_PROJECTION)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    targeting_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/targeting_and_facing.inl"
    )
    release_text = read_text(CAST_RELEASE_HELPERS)
    snapshot_text = read_text(BOT_SNAPSHOT_BUILDERS)
    casting_api_text = read_text(CASTING_API)
    required_skill_tokens = (
        "OngoingCastTracksLiveTargetDuringNativeTick(ongoing)",
        "OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing) &&",
        "!ongoing.bounded_release_requested",
        "OngoingCastShouldUseLiveFacingTarget(ongoing)",
        "binding->facing_target_actor_address",
        "return ongoing.target_actor_address",
    )
    required_projection_tokens = (
        "current_target_actor = ResolveOngoingCastNativeTargetActor",
        "TryPopulateBoulderProjectionTarget",
        "FindBestNativeBoulderImpactVictim",
        "binding->ongoing_cast",
    )
    required_processing_tokens = (
        "Bounded held Earth follows the bot's live target while the boulder is",
        "once release is requested, target refresh stops",
        "ongoing.bounded_release_requested = true",
        "ongoing.bounded_release_target_actor = earth_damage_projection.target_actor",
        "HasBotNativeCastActivity(activity_before_dispatch)",
        "native_activity_before_dispatch",
        "gameplay_input_buffer_readable",
        "bounded_held_release_requested_safety_cap",
        "target_lethal_released",
        "max_size_released",
    )
    required_release_tokens = (
        "kBotNativeActionRearmTicks",
        "native_action_rearm",
    )
    required_readiness_tokens = (
        "native_action_cooldown_ticks",
        "cast rejected for native action cooldown",
    )
    movement_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/participant_scene_binding_ticks.inl"
    )
    required_movement_tokens = (
        "intent.face_target_actor_address != 0",
        "OngoingCastShouldUseLiveFacingTarget(binding->ongoing_cast)",
        "binding->ongoing_cast.target_actor_address = intent.face_target_actor_address",
    )
    required_targeting_tokens = (
        "OngoingCastShouldPreserveProjectionTargetAfterAimMiss",
        "OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing)",
        "!ongoing.bounded_release_requested",
    )
    missing = [token for token in required_skill_tokens if token not in skill_text]
    missing += [token for token in required_projection_tokens if token not in projection_text]
    missing += [token for token in required_processing_tokens if token not in processing_text]
    missing += [token for token in required_release_tokens if token not in release_text]
    missing += [
        token for token in required_readiness_tokens
        if token not in snapshot_text and token not in casting_api_text
    ]
    missing += [token for token in required_movement_tokens if token not in movement_tick_text]
    missing += [token for token in required_targeting_tokens if token not in targeting_text]
    if missing:
        raise StaticReTestFailure(
            "Earth boulder held retarget/release contract is missing token(s): " +
            ", ".join(missing))
    forbidden_processing_tokens = (
        "gameplay_input_buffer_unreadable",
        "gameplay_mouse_left_unreadable",
    )
    present_forbidden = [
        token for token in forbidden_processing_tokens
        if token in processing_text
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "Earth boulder startup still treats optional gameplay input buffer reads as fatal: " +
            ", ".join(present_forbidden))
    return "Earth boulder held charge tracks live target until release"


def test_boulder_live_retarget_probe_is_documented() -> str:
    probe_text = read_text(BOULDER_RETARGET_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")
    plan_text = read_text(NATIVE_SEAM_PLAN)
    required_probe_tokens = (
        "boulder_release_logged",
        "[bots] native boulder release requested.",
        "default=25000.0",
        "release_target_actor",
        "target_in_impact",
        "retarget_removed",
        "retarget_death_logged",
        "retarget_impact_observed",
        "enemy.death hook invoked",
        "initial target was damaged after the bot swapped targets",
        "initial target died after the bot swapped targets",
    )
    required_doc_tokens = (
        "tests/re/run_live_boulder_retarget_probe.py",
        "charges Boulder on one real wave enemy",
        "freezes that retargeted actor at release",
        "high-HP target remains alive",
    )
    missing = [token for token in required_probe_tokens if token not in probe_text]
    missing += [
        token
        for token in required_doc_tokens
        if token not in readme_text and token not in plan_text
    ]
    if missing:
        raise StaticReTestFailure(
            "Earth boulder live retarget probe coverage is missing token(s): " +
            ", ".join(missing))
    return "Earth boulder live retarget probe is documented"


def test_lua_earth_retargeting_uses_live_boulder_impact_anchor() -> str:
    combat_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/combat.lua")
    snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    bot_snapshot_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_parser_snapshots.cpp")
    bot_runtime_text = read_text(ROOT / "SolomonDarkModLoader/include/bot_runtime.h")
    mod_loader_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")

    required_snapshot_tokens = (
        "active_spell_object_address",
        "active_spell_object_x",
        "active_spell_object_y",
        "active_spell_object_radius",
        "active_spell_object_charge",
        "CallActorWorldLookupObjectByHandleSafe",
        "kObjectCollisionRadiusOffset",
        "kSpellObjectChargeOffset",
    )
    missing_snapshot_tokens = []
    for token in required_snapshot_tokens:
        if (
            token not in snapshot_text
            and token not in bot_snapshot_text
            and token not in bot_runtime_text
            and token not in mod_loader_text
        ):
            missing_snapshot_tokens.append(token)
    if missing_snapshot_tokens:
        raise StaticReTestFailure(
            "bot snapshots do not expose live active Boulder object fields: " +
            ", ".join(missing_snapshot_tokens))

    required_lua_tokens = (
        "earth_boulder_impact_center",
        "target_in_native_boulder_impact",
        "find_earth_boulder_enemy",
        "active_spell_object_x",
        "active_spell_object_y",
        "active_spell_object_radius",
        "active_spell_object_charge",
        "object_radius * charge * 2.0",
        "native_overlap_radius",
        "enemy.radius",
        "earth_boulder_no_impact_target",
    )
    missing_lua_tokens = [token for token in required_lua_tokens if token not in combat_text]
    if missing_lua_tokens:
        raise StaticReTestFailure(
            "Lua Earth targeting is not anchored to the live native Boulder impact window: " +
            ", ".join(missing_lua_tokens))

    return "Lua Earth retargeting uses the live native Boulder object impact window"


def test_active_cast_movement_clears_stale_vector_before_stock_tick() -> str:
    player_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    movement_step_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/wizard_bot_movement_step.inl"
    )

    required_tokens = (
        "Clear stale loader movement input before every stock bot tick",
        "const bool stock_tick_may_consume_stale_loader_vector =",
        "binding->movement_active || binding->last_movement_displacement > 0.0001f",
        "ClearWizardBotMovementVectorInputs(actor_address);",
        "active casts receive target/control input through selection state",
        "CallPlayerActorMoveStepSafe",
    )
    missing = [
        token
        for token in required_tokens
        if token not in player_tick_text and token not in movement_step_text
    ]
    if missing:
        raise StaticReTestFailure(
            "active-cast movement can still double-consume stale loader vectors: " +
            ", ".join(missing))

    forbidden_patterns = (
        r"if\s*\(\s*!binding->ongoing_cast\.active\s*\)\s*\{\s*// Loader-owned movement runs after stock tick\.",
        r"if\s*\(\s*!binding->ongoing_cast\.active\s*\)\s*\{\s*ClearWizardBotMovementVectorInputs\(actor_address\);",
    )
    present = [
        pattern for pattern in forbidden_patterns if re.search(pattern, player_tick_text, re.S)
    ]
    if present:
        raise StaticReTestFailure(
            "RunStockTick still clears stale movement only when no cast is active")

    return "active casts clear stale loader movement before stock tick and move once through the native step"


def test_bot_mana_spend_is_stock_owned_through_native_gate_patch() -> str:
    layout_text = read_text(BINARY_LAYOUT)
    plan_text = read_text(NATIVE_SEAM_PLAN)
    resource_text = read_text(RESOURCE_STATE)
    processing_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl"
    )
    processing_context_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/processing_context.inl"
    )
    preparation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl"
    )
    dispatch_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_cast_hooks.inl"
    )
    player_control_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    player_mana_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_mana_hooks.inl"
    )
    player_tick_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    standalone_slot_context_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/standalone_progression_slot_context.inl"
    )
    request_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    patch_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/native_cast_gate_patches.inl"
    )
    helper_text = read_text(BOT_MANA_TRACE_HELPERS)
    writer_probe_text = read_text(BOT_MANA_WRITER_LIVE_PROBE)
    native_spend_probe_text = read_text(BOT_NATIVE_MANA_SPEND_LIVE_PROBE)
    pure_primary_probe_text = read_text(PURE_PRIMARY_STARTUP_LIVE_PROBE)
    required_tokens = {
        "binary layout": "player_actor_apply_mana_delta=0x0052B150",
        "gate branch layout": "player_actor_apply_mana_delta_local_actor_gate_branch=0x0052B171",
        "ether gate branch layout": "spell_cast_008_slot_gate_branch=0x0053D1B3",
        "ether projectile gate branch layout": "spell_cast_008_projectile_slot_gate_branch=0x0053D9D2",
        "fire gate branch layout": "spell_cast_010_slot_gate_branch=0x0053E4E8",
        "fireball secondary effect gate branch layout": "fireball_hit_secondary_effect_projectile_group_gate_branch=0x005E5387",
        "magic missile hit damage gate branch layout": "magic_missile_hit_damage_projectile_group_gate_branch=0x005F1F39",
        "gate patch name": "player_actor_apply_mana_delta_local_actor_gate",
        "ether gate patch name": "spell_cast_008_ether_slot_gate",
        "ether projectile gate patch name": "spell_cast_008_ether_projectile_slot_gate",
        "fire gate patch name": "spell_cast_010_fire_slot_gate",
        "fireball secondary effect gate patch name": "fireball_hit_secondary_effect_projectile_group_gate",
        "magic missile hit damage gate patch name": "magic_missile_hit_damage_projectile_group_gate",
        "gate patch binding": "kPlayerActorApplyManaDeltaLocalActorGateBranch",
        "ether gate patch binding": "kSpellCast008SlotGateBranch",
        "ether projectile gate patch binding": "kSpellCast008ProjectileSlotGateBranch",
        "fire gate patch binding": "kSpellCast010SlotGateBranch",
        "fireball secondary effect gate patch binding": "kFireballHitSecondaryEffectProjectileGroupGateBranch",
        "magic missile hit damage gate patch binding": "kMagicMissileHitDamageProjectileGroupGateBranch",
        "gate opcode validator": "LooksLikeNativeJnzGate",
        "short jnz gate validator": "bytes[0] == 0x75",
        "gate patch byte count": "patch->byte_count",
        "gate runtime restore": "patch->original = current",
        "processing live depletion": "native mana depleted",
        "processing live read": "TryReadProgressionMana",
        "native rate validator": "ValidateNativeManaRateConfigForOngoingCast",
        "native rate invalidation": "ClearNativeManaRateConfigForOngoingCast",
        "native rate pending log": "native mana rate config pending",
        "trace helper": "wait_for_bot_native_mana_delta",
        "trace rate plausibility": "assert_native_mana_delta_matches_prepared_rate",
        "writer stale guard": "coordinate_only_stale_config_guard",
        "writer target actor": "target_actor_address=target_actor_address",
        "writer probe": "stock_native_mana_delta",
        "writer trace summary": "negative_bot_actor_hits",
        "writer player trace guard": "negative_player_actor_hits",
        "writer player mana guard": "assert_gameplay_player_mana_not_decreased",
        "writer player mp delta": "player_mp_delta",
        "pure primary trace": "stock_native_mana_delta",
        "standalone owner context type": "ScopedStandaloneBotProgressionSlotContext",
        "standalone owner context invoke": "InvokeWithStandaloneBotProgressionSlotContext",
        "standalone owner context log": "standalone_slot_owner_context",
        "bot owner context invoke": "InvokeWithBotProgressionSlotOwnerContext",
        "bot owner context mode": "require_standalone_slot",
        "mana delta hook": "HookPlayerActorApplyManaDelta",
        "mana delta hook state": "player_actor_apply_mana_delta_hook",
        "mana delta hook size": "kPlayerActorApplyManaDeltaHookPatchSize",
        "native mana delta owner context": "native mana delta owner context",
        "pure primary bot owner context": "pure_primary_bot_owner_context",
        "actor progression runtime cache": "EnsureActorProgressionRuntimeFieldFromHandle",
        "pre stock tick progression runtime cache": "pre_bot_stock_tick_progression_runtime",
        "post native mana delta repair": "post_native_bot_mana_delta",
        "player slot owner repair": "RepairGameplayPlayerProgressionSlotOwner",
        "post bot stock tick repair": "post_bot_stock_tick",
    }
    missing: list[str] = []
    if required_tokens["binary layout"] not in layout_text:
        missing.append(required_tokens["binary layout"])
    if required_tokens["gate branch layout"] not in layout_text:
        missing.append(required_tokens["gate branch layout"])
    if required_tokens["ether gate branch layout"] not in layout_text:
        missing.append(required_tokens["ether gate branch layout"])
    if required_tokens["ether projectile gate branch layout"] not in layout_text:
        missing.append(required_tokens["ether projectile gate branch layout"])
    if required_tokens["fire gate branch layout"] not in layout_text:
        missing.append(required_tokens["fire gate branch layout"])
    if required_tokens["magic missile hit damage gate branch layout"] not in layout_text:
        missing.append(required_tokens["magic missile hit damage gate branch layout"])
    for label, token in (
        ("gate patch name", required_tokens["gate patch name"]),
        ("ether gate patch name", required_tokens["ether gate patch name"]),
        ("ether projectile gate patch name", required_tokens["ether projectile gate patch name"]),
        ("fire gate patch name", required_tokens["fire gate patch name"]),
        ("magic missile hit damage gate patch name", required_tokens["magic missile hit damage gate patch name"]),
        ("gate patch binding", required_tokens["gate patch binding"]),
        ("ether gate patch binding", required_tokens["ether gate patch binding"]),
        ("ether projectile gate patch binding", required_tokens["ether projectile gate patch binding"]),
        ("fire gate patch binding", required_tokens["fire gate patch binding"]),
        ("magic missile hit damage gate patch binding", required_tokens["magic missile hit damage gate patch binding"]),
        ("gate opcode validator", required_tokens["gate opcode validator"]),
        ("short jnz gate validator", required_tokens["short jnz gate validator"]),
        ("gate patch byte count", required_tokens["gate patch byte count"]),
        ("gate runtime restore", required_tokens["gate runtime restore"]),
    ):
        if token not in patch_text:
            missing.append(f"{label}:{token}")
    for label, token in (
        ("processing live depletion", required_tokens["processing live depletion"]),
        ("processing live read", required_tokens["processing live read"]),
        ("native rate pending log", required_tokens["native rate pending log"]),
    ):
        if token not in processing_text:
            missing.append(f"{label}:{token}")
    for label, token in (
        ("native rate validator", required_tokens["native rate validator"]),
        ("native rate invalidation", required_tokens["native rate invalidation"]),
    ):
        if token not in resource_text:
            missing.append(f"{label}:{token}")
    for label, text, token in (
        ("trace helper", helper_text, required_tokens["trace helper"]),
        ("trace rate plausibility", helper_text, required_tokens["trace rate plausibility"]),
        ("writer stale guard", writer_probe_text, required_tokens["writer stale guard"]),
        ("writer target actor", writer_probe_text, required_tokens["writer target actor"]),
        ("writer probe", writer_probe_text, required_tokens["writer probe"]),
        ("writer trace summary", writer_probe_text + helper_text, required_tokens["writer trace summary"]),
        ("writer player trace guard", writer_probe_text + native_spend_probe_text + pure_primary_probe_text + helper_text, required_tokens["writer player trace guard"]),
        ("writer player mana guard", writer_probe_text + native_spend_probe_text + pure_primary_probe_text + helper_text, required_tokens["writer player mana guard"]),
        ("writer player mp delta", writer_probe_text + native_spend_probe_text + helper_text, required_tokens["writer player mp delta"]),
        ("native spend probe", native_spend_probe_text, required_tokens["writer probe"]),
        ("pure primary trace", pure_primary_probe_text, required_tokens["pure primary trace"]),
        ("standalone owner context type", standalone_slot_context_text, required_tokens["standalone owner context type"]),
        ("standalone owner context invoke", standalone_slot_context_text + processing_context_text + preparation_text + dispatch_hook_text + player_control_hook_text + player_tick_hook_text, required_tokens["standalone owner context invoke"]),
        ("standalone owner context log", processing_context_text + preparation_text + dispatch_hook_text + player_control_hook_text + player_tick_hook_text, required_tokens["standalone owner context log"]),
        ("bot owner context invoke", standalone_slot_context_text + player_mana_hook_text, required_tokens["bot owner context invoke"]),
        ("bot owner context mode", standalone_slot_context_text, required_tokens["bot owner context mode"]),
        ("mana delta hook", player_mana_hook_text, required_tokens["mana delta hook"]),
        ("mana delta hook state", player_mana_hook_text + request_state_text + public_api_text, required_tokens["mana delta hook state"]),
        ("mana delta hook size", constants_text + public_api_text, required_tokens["mana delta hook size"]),
        ("native mana delta owner context", player_mana_hook_text, required_tokens["native mana delta owner context"]),
        ("pure primary bot owner context", preparation_text + dispatch_hook_text + player_control_hook_text, required_tokens["pure primary bot owner context"]),
        ("actor progression runtime cache", standalone_slot_context_text + player_tick_hook_text + player_mana_hook_text, required_tokens["actor progression runtime cache"]),
        ("pre stock tick progression runtime cache", player_tick_hook_text, required_tokens["pre stock tick progression runtime cache"]),
        ("post native mana delta repair", player_mana_hook_text, required_tokens["post native mana delta repair"]),
        ("player slot owner repair", standalone_slot_context_text, required_tokens["player slot owner repair"]),
        ("post bot stock tick repair", player_tick_hook_text, required_tokens["post bot stock tick repair"]),
    ):
        if token not in text:
            missing.append(f"{label}:{token}")
    if "standalone stock tick owner context" in player_tick_hook_text:
        missing.append("standalone stock tick still swaps the player progression slot")
    if "bot_stock_tick_needs_progression_owner" in player_tick_hook_text:
        missing.append("bot stock tick still carries broad progression owner state")
    if "bot stock tick mana owner context" in player_tick_hook_text:
        missing.append("bot stock tick still logs broad progression owner context")
    if "InvokeWithBotProgressionSlotOwnerContext(" in player_tick_hook_text:
        missing.append("bot stock tick still wraps the whole native tick in slot owner context")
    if re.search(r"TryWriteField\s*<\s*float\s*>\s*\([^;]*kProgressionMpOffset", resource_text, re.S):
        missing.append("direct progression MP write still present")
    if re.search(
        r"TryWriteField\s*<\s*float\s*>\s*\([^;]*kActorSpellConfig2d0Offset[^;]*ongoing\.mana_cost",
        "\n".join((resource_text, processing_text)),
        re.S,
    ):
        missing.append("actor+0x2D0 is being populated from loader-owned mana cost")
    forbidden_active_tokens = (
        "TryApplyNativeBotManaDelta",
        "TrySpendBotMana",
        "NativeBotManaDeltaShim",
        "CallPlayerActorApplyManaDeltaSafe",
        "[bots] mana spent.",
    )
    active_text = "\n".join((resource_text, processing_text, patch_text))
    stale_active = [token for token in forbidden_active_tokens if token in active_text]
    if stale_active:
        missing.append("active code still contains manual mana tokens:" + ",".join(stale_active))
    stale_probe_text = "\n".join((writer_probe_text, native_spend_probe_text, pure_primary_probe_text))
    stale_probe_tokens = [
        token for token in ("assert_shim_fields_restored", "capture_shim_fields", "wait_for_native_mana_spend")
        if token in stale_probe_text
    ]
    if stale_probe_tokens:
        missing.append("live probes still assert shim/log path:" + ",".join(stale_probe_tokens))
    stale_plan_tokens = (
        "PerCast spend branch is still not live-proven",
        "current Fire/Ether pure-primary bot casts can complete with `startup_timeout`",
        "scoped actor/progression shim",
    )
    for token in stale_plan_tokens:
        if token in plan_text:
            missing.append(f"stale native seam plan token:{token}")
    if missing:
        raise StaticReTestFailure(
            "bot mana spend is not stock-owned through native gate patch: " + ", ".join(missing)
        )
    return "bot mana spend is stock-owned through the native mana-delta gate patch"


def test_bot_cast_admission_refreshes_live_mana_before_queue() -> str:
    casting_text = read_text(CASTING_API)
    mod_loader_header_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    snapshot_text = read_text(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl"
    )

    required_tokens = (
        "TryRefreshParticipantGameplayState",
        "PublishParticipantGameplaySnapshot(*binding)",
        "ApplyGameplayStateToSnapshot(request.bot_id, &live_snapshot)",
        "ApplyManaReserveStateToSnapshot(&live_snapshot)",
        "live_progression_available",
        "live_snapshot.max_mp > 0.0f",
        "live_snapshot.progression_runtime_state_address != 0",
        "live_snapshot.mana_reserve_active",
        "cast rejected for mana reserve",
        "mode=reserve before=",
        "live_snapshot.mp <= kBotManaReadinessEpsilon",
        "cast rejected for mana",
        "mode=unavailable before=",
        "snapshot->mp > kBotManaReadinessEpsilon && !snapshot->mana_reserve_active",
    )
    combined_text = "\n".join(
        (casting_text, mod_loader_header_text, state_getters_text, snapshot_text)
    )
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "bot cast admission does not refresh and reject live empty mana before queue: " +
            ", ".join(missing))

    refresh_pos = casting_text.find("TryRefreshParticipantGameplayState(request.bot_id")
    reject_pos = casting_text.find("cast rejected for mana")
    queue_pos = casting_text.find("g_pending_casts.push_back")
    if not (0 <= refresh_pos < reject_pos < queue_pos):
        raise StaticReTestFailure(
            "bot cast live mana rejection must run before pending-cast insertion")

    return "bot cast admission refreshes live mana and rejects empty MP before queueing"


def test_bot_mana_reserve_uses_hysteresis_for_casting() -> str:
    header_text = read_text(BOT_RUNTIME_HEADER)
    runtime_text = read_text(ROOT / "SolomonDarkModLoader/src/bot_runtime.cpp")
    lookup_text = read_text(BOT_RUNTIME_DEFAULTS_AND_LOOKUP)
    casting_text = read_text(CASTING_API)
    snapshot_text = read_text(BOT_SNAPSHOT_BUILDERS)
    snapshots_api_text = read_text(BOT_RUNTIME_SNAPSHOTS_API)
    lifecycle_text = read_text(BOT_RUNTIME_LIFECYCLE_API)
    state_mutation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/helpers/state_mutation.inl"
    )
    preparation_text = read_text(PENDING_CAST_PREPARATION)
    release_text = read_text(CAST_RELEASE_HELPERS)
    processing_text = read_text(PENDING_CAST_PROCESSING)
    release_helpers_text = read_text(CAST_RELEASE_HELPERS)
    player_mana_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_mana_hooks.inl"
    )
    player_tick_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    constants_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    lua_snapshot_text = read_text(LUA_ENGINE_PARSER_SNAPSHOTS)

    required_tokens = (
        "constexpr float kBotManaReserveEnterRatio = 0.10f",
        "constexpr float kBotManaReserveExitRatio = 0.80f",
        "bool mana_reserve_active = false",
        "struct BotManaReserveState",
        "std::vector<BotManaReserveState> g_bot_mana_reserves",
        "ratio < kBotManaReserveEnterRatio",
        "ratio > kBotManaReserveExitRatio",
        "UpdateBotManaReserveStateLocked",
        "RefreshBotManaReserveState",
        "ApplyManaReserveStateToSnapshot(&live_snapshot)",
        "ApplyManaReserveStateToSnapshot(snapshot)",
        "live_snapshot.mana_reserve_active",
        "cast rejected for mana reserve",
        "mode=reserve before=",
        "mana_reserve_active ||",
        "native mana reserve",
        "mana_stop_label = \"mana_reserve\"",
        "StopOngoingBotCastForManaReserve",
        "pre_bot_stock_tick_mana_reserve",
        "ApplyBotNativeManaReserveRecovery",
        "ClearIdleBotManaReserveNativeCastState",
        "native mana reserve idle cast cleanup",
        "InvokeNativeManaDeltaTrampolineForBotSafe",
        "native mana reserve recovery",
        "post_native_bot_mana_recovery",
        "kBotManaReserveRecoveryIntervalMs",
        "kBotManaReserveRecoveryRatioPerSecond",
        "std::strcmp(exit_label, \"mana_reserve\") == 0",
        "std::strcmp(exit_label, \"mana_depleted\") == 0",
        "g_bot_mana_reserves.clear()",
        "RemoveBotManaReserveState(bot_id)",
        "lua_setfield(state, -2, \"mana_reserve_active\")",
    )
    combined_text = "\n".join((
        header_text,
        runtime_text,
        lookup_text,
        casting_text,
        snapshot_text,
        snapshots_api_text,
        lifecycle_text,
        state_mutation_text,
        preparation_text,
        processing_text,
        release_helpers_text,
        player_mana_hook_text,
        player_tick_hook_text,
        constants_text,
        lua_snapshot_text,
    ))
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "bot mana reserve hysteresis is missing native cast token(s): " +
            ", ".join(missing))

    enter_pos = lookup_text.find("ratio < kBotManaReserveEnterRatio")
    exit_pos = lookup_text.find("ratio > kBotManaReserveExitRatio")
    if not (0 <= enter_pos < exit_pos):
        raise StaticReTestFailure(
            "bot mana reserve must enter below the low threshold and exit above the high threshold")

    refresh_pos = casting_text.find("ApplyManaReserveStateToSnapshot(&live_snapshot)")
    reserve_reject_pos = casting_text.find("cast rejected for mana reserve")
    queue_pos = casting_text.find("g_pending_casts.push_back")
    if not (0 <= refresh_pos < reserve_reject_pos < queue_pos):
        raise StaticReTestFailure(
            "bot mana reserve rejection must run before pending-cast insertion")

    active_reserve_pos = processing_text.find("native mana reserve")
    active_finish_pos = processing_text.find(
        "FinishBotCastNativeLifecycle(cast_context, ongoing, mana_stop_label, true)")
    if not (0 <= active_reserve_pos < active_finish_pos):
        raise StaticReTestFailure(
            "active bot casts must finish through the native lifecycle when reserve is active")

    run_stock_tick_pos = player_tick_hook_text.find("auto RunStockTick")
    pre_stop_pos = player_tick_hook_text.find(
        "StopOngoingBotCastForManaReserve", run_stock_tick_pos)
    recovery_pos = player_tick_hook_text.find(
        "ApplyBotNativeManaReserveRecovery", run_stock_tick_pos)
    drive_input_pos = player_tick_hook_text.find(
        "const bool drive_stock_cast_input", run_stock_tick_pos)
    original_tick_pos = player_tick_hook_text.find("original(self);", drive_input_pos)
    if not (
        0 <= run_stock_tick_pos < pre_stop_pos < recovery_pos < drive_input_pos < original_tick_pos
    ):
        raise StaticReTestFailure(
            "bot mana reserve stop/recovery must run before stock cast input and native tick")

    return "bot mana reserve uses 10/80 hysteresis across native cast paths"


def test_bot_out_of_mana_probe_checks_pre_execution_rejection() -> str:
    probe_text = read_text(BOT_OUT_OF_MANA_REJECTION_LIVE_PROBE)
    readme_text = read_text(ROOT / "tests/re/README.md")

    required_tokens = (
        "force_bot_mana",
        "sd.debug.write_float(mp_address, {current_mp})",
        "sd.debug.write_float(max_mp_address, {max_mp})",
        "queue_default_primary(bot_id",
        "allow_queued_rejection",
        "cast_rejected_without_effects",
        "sd_bots_cast_returned_false",
        "mana_rejection_logged",
        "no_pending_cast_after_rejection",
        "no_active_cast_after_rejection",
        "no_startup_after_rejection",
        "no_cast_activity_after_rejection",
        "no_pending_cast_insert_log",
        "mp_not_spent",
        "no_native_mana_spend",
        "no_cast_lifecycle_or_effect_logs",
        "cast rejected for mana",
    )
    missing = [token for token in required_tokens if token not in probe_text]
    if missing:
        raise StaticReTestFailure(
            "bot out-of-mana live probe is missing pre-execution rejection token(s): " +
            ", ".join(missing))

    required_doc_tokens = (
        "run_live_bot_out_of_mana_rejection_probe.py",
        "--bot-key earth --bot-element-id 2 --current-mp 1 --max-mp 100 --allow-queued-rejection",
        "forces the bot's live progression MP to zero",
        "before pending-cast insertion",
        "held-cast preparation gate",
        "no cast lifecycle or effect logs",
    )
    missing_doc = [token for token in required_doc_tokens if token not in readme_text]
    if missing_doc:
        raise StaticReTestFailure(
            "RE test README is missing out-of-mana rejection coverage token(s): " +
            ", ".join(missing_doc))

    return "bot out-of-mana probe checks pre-execution rejection and no effects"


def test_held_primary_mana_uses_native_spend_scale_and_start_rate() -> str:
    casting_text = read_text(CASTING_API)
    native_stats_header_text = read_text(NATIVE_SPELL_STATS_HEADER)
    native_stats_text = read_native_spell_stats_source()
    preparation_text = read_text(PENDING_CAST_PREPARATION)

    required_tokens = (
        "mana_spend_cost",
        "mana_spend_cost_available",
        "NativePrimaryManaOutputUsesDisplayScale",
        "kActorWalkCyclePrimaryDivisorGlobal",
        "TryReadValue(scale_address",
        "cost.cost = stats.mana_spend_cost",
        "cost.native_stat_cost = stats.mana_cost",
        "cost.native_output_scale = stats.mana_output_scale",
        "CanBotManaStartCast",
        "case BotManaChargeKind::PerSecond:",
        "return cost.cost;",
        "ResolveBotManaRequiredToStart(cost)",
        "ResolveBotManaRequiredToStart(cast_mana)",
        "CanBotManaStartCast(cast_mana, current_mp, max_mp)",
        "mana_reserve_active ? std::string(\"reserve\") : std::string(\"per_second\")",
        "\" rate=\" + std::to_string(cast_mana.cost)",
        "native_stat_cost=",
        "native_output_scale=",
    )
    combined_text = "\n".join((
        casting_text,
        native_stats_header_text,
        native_stats_text,
        preparation_text,
    ))
    missing = [token for token in required_tokens if token not in combined_text]
    if missing:
        raise StaticReTestFailure(
            "held primary mana policy is missing native scale/start-rate token(s): " +
            ", ".join(missing))

    forbidden_patterns = (
        (
            casting_text,
            r"case\s+BotManaChargeKind::PerSecond:\s*return\s+current_mp\s*>\s*kBotManaReadinessEpsilon\s*;",
            "per-second start still accepts any positive mana",
        ),
        (
            preparation_text,
            r"current_mp\s*\+\s*0\.001f\s*<\s*required_mana",
            "preparation still gates held casts by required_mana instead of start policy",
        ),
    )
    present = [
        label for text, pattern, label in forbidden_patterns if re.search(pattern, text, re.S)
    ]
    if present:
        raise StaticReTestFailure("; ".join(present))

    return "held primaries spend the unscaled native mana cost and require the native start rate"


def test_primary_build_skill_mapping_has_single_runtime_owner() -> str:
    casting_text = read_text(CASTING_API)
    scene_text = read_text(SCENE_SELECTION)
    native_spell_stats_text = read_native_spell_stats_source()
    preparation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl"
    )
    if "resolve_primary_build_skill_id" in casting_text:
        raise StaticReTestFailure("bot runtime still duplicates primary combo build-skill mapping")
    if "skill_id <= 0 || loadout_cost.resolved" in casting_text:
        raise StaticReTestFailure("bot mana resolver accepts arbitrary positive primary skill ids")
    if "TryResolvePrimaryCastDescriptorFromSkillId" not in scene_text:
        raise StaticReTestFailure("scene selection does not resolve explicit primary build ids")
    if "TryResolvePrimaryCastDescriptorFromSkillId" not in preparation_text:
        raise StaticReTestFailure("cast preparation does not use explicit primary descriptors")
    if "TryResolveNativePrimaryBuildSkillId" in scene_text or "TryResolveNativePrimaryBuildSkillId" in native_spell_stats_text:
        raise StaticReTestFailure(
            "primary combo build-skill mapping still uses a static helper instead of Skills_Wizard output")
    if re.search(r"case\s+(?:1000|0x3E[0-9A-F]|0x3F[0-9A-F])", native_spell_stats_text):
        raise StaticReTestFailure("native spell stats still reverse-map primary build ids with a switch")
    if re.search(r"case\s+(?:1000|0x3E[0-9A-F]|0x3F[0-9A-F])", scene_text):
        raise StaticReTestFailure("scene selection still classifies primary build ids with a switch")

    required_tokens = (
        "CallSkillsWizardBuildPrimarySpellSafe",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "TryResolveNativePrimarySelectionFromSkillId",
        "kSkillsWizardBuildPrimarySpell",
        "RestoreProgressionCurrentSpellIdIfNeeded",
    )
    missing_tokens = [
        token for token in required_tokens
        if token not in native_spell_stats_text and token not in scene_text
    ]
    if missing_tokens:
        raise StaticReTestFailure(
            "primary combo build-skill mapping is missing native builder token(s): " +
            ", ".join(missing_tokens))
    return "primary combo build-skill mapping is resolved from live Skills_Wizard output"


def test_gameplay_selection_writes_do_not_corrupt_stock_run_placement_vector() -> str:
    gameplay_state_text = read_text(SCENE_ANIMATION_GAMEPLAY_STATE)
    debug_state_text = read_text(PUBLIC_API_DEBUG_AND_SPAWN)
    cast_probe_text = read_text(CAST_PROBE_STATE)
    selection_doc_text = read_text(ROOT / "docs/spell-cast-cleanup-chain.md")

    required_tokens = (
        (
            gameplay_state_text,
            "gameplay selection writer",
            "TryWriteGameplayIndexStateValue(",
        ),
        (
            debug_state_text,
            "selection debug state",
            "state->player_selection_state_0 = state->slot_selection_entries[0];",
        ),
        (
            debug_state_text,
            "selection debug state",
            "state->player_selection_state_1 = state->slot_selection_entries[1];",
        ),
        (
            selection_doc_text,
            "selection lifecycle doc",
            "The globals at `0x00819EC4/0x00819EC8` are not a recovered bot selection API.",
        ),
    )
    missing = [f"{label}: {token}" for text, label, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "selection-state vector-corruption guard is missing token(s): " +
            ", ".join(missing))

    forbidden_tokens = (
        (gameplay_state_text, "gameplay selection writer", "TryWriteResolvedGlobalInt(selection_global"),
        (gameplay_state_text, "gameplay selection writer", "kPlayerSelectionState0Global"),
        (gameplay_state_text, "gameplay selection writer", "kPlayerSelectionState1Global"),
        (debug_state_text, "selection debug state", "TryReadResolvedGlobalInt(kPlayerSelectionState0Global"),
        (debug_state_text, "selection debug state", "TryReadResolvedGlobalInt(kPlayerSelectionState1Global"),
        (cast_probe_text, "cast probe", "TryReadResolvedGlobalInt(kPlayerSelectionState0Global"),
    )
    present = [f"{label}: {token}" for text, label, token in forbidden_tokens if token in text]
    if present:
        raise StaticReTestFailure(
            "selection-state code still touches stock run-placement vector global(s): " +
            ", ".join(present))

    return "gameplay selection writes stay on the slot table and do not touch stock vector globals"
