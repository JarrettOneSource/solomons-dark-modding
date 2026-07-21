"""Runtime cast, nameplate, memory, and actor ownership contracts."""

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
    CAST_RELEASE_HELPERS,
    DEBUG_UI_OVERLAY_FRAME_RENDER,
    DEBUG_UI_OVERLAY_HEADER,
    DEBUG_UI_OVERLAY_PUBLIC_SURFACE,
    GAMEPLAY_HUD_HOOKS,
    GAMEPLAY_KEYBOARD_INJECTION,
    GAMEPLAY_NATIVE_FUNCTION_TYPES,
    GAMEPLAY_PUBLIC_STATE_GETTERS,
    HUD_LABEL_ASSET_MATERIALIZER,
    MEMORY_ACCESS_HEADER,
    MEMORY_ACCESS_REGIONS,
    MOD_LOADER_GAMEPLAY,
    MOD_LOADER_HEADER,
    MULTIPLAYER_HUD_NAMES_VERIFIER,
    PENDING_CAST_PREPARATION,
    PENDING_CAST_PROCESSING,
    PLAYER_ACTOR_TICK_HOOK,
    REAL_INPUT_SPELL_CAST_SYNC_VERIFIER,
    ROOT,
    RUNTIME_DEBUG_CORE,
    RUNTIME_DEBUG_WATCH,
    RUNTIME_DEBUG_WATCH_HELPERS,
    RUNTIME_DEBUG_WATCH_MANAGEMENT,
    RUNTIME_DEBUG_WATCH_REGISTRATION,
    RUN_LIFECYCLE_SPELL_CAST_HOOKS,
    STEAM_FRIEND_ACTIVE_PAIR_VISUALS_VERIFIER,
    STEAM_FRIEND_HUB_VISUALS_VERIFIER,
    StaticReTestFailure,
    read_multiplayer_transport_source,
    read_player_cast_hooks_source,
    read_text,
)

def test_remote_per_cast_primary_settles_without_waiting_for_release() -> str:
    processing_text = read_text(PENDING_CAST_PROCESSING)
    preparation_text = read_text(PENDING_CAST_PREPARATION)
    release_text = read_text(CAST_RELEASE_HELPERS)
    projectile_observation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/projectile_observation.inl"
    )
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    player_cast_text = read_player_cast_hooks_source()
    keyboard_injection_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    participant_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_entity_state.inl"
    )
    transport_text = read_multiplayer_transport_source()
    runtime_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    mouse_refresh_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    input_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl"
    )
    verifier_text = read_text(REAL_INPUT_SPELL_CAST_SYNC_VERIFIER)
    animation_element_verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_animation_mana_elements.py"
    )

    required_processing_tokens = (
        "remote_per_cast_pure_primary_no_handle_settled",
        "ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerCast",
        "remote_per_cast_pure_primary_without_live_handle",
        "remote_per_cast_projectile_observed",
        "kRemotePerCastPurePrimaryProjectileSettleTicks",
        "kRemotePerCastPurePrimaryProjectileMissingSettleTicks",
        "remote_per_cast_projectile_impact_lifecycle_settled",
        "remote_per_cast_projectile_targetless_settled",
        "preserve_remote_per_cast_projectile_target",
        "kRemotePerCastPurePrimaryNoProjectileSafetyTicks",
        "remote_release_driven_pure_primary_no_handle_settled",
        "ongoing.mana_charge_kind != multiplayer::BotManaChargeKind::PerCast",
        "remote_input_release_or_timeout",
        "!remote_per_cast_pure_primary_without_live_handle",
    )
    missing_processing_tokens = [
        token for token in required_processing_tokens if token not in processing_text
    ]
    if missing_processing_tokens:
        raise StaticReTestFailure(
            "remote per-cast primary settlement is missing token(s): " +
            ", ".join(missing_processing_tokens))

    required_observation_tokens = (
        (preparation_text, "preparation", "remote_per_cast_projectile_baseline_valid"),
        (preparation_text, "preparation", "remote_per_cast_projectile_expected_type"),
        (preparation_text, "preparation", "remote_per_cast_projectile_addresses_before"),
        (preparation_text, "preparation", "ExpectedPurePrimaryProjectileTypeForSelectionState"),
        (preparation_text, "preparation", "TryListPurePrimaryProjectileActorAddressesInScene("),
        (preparation_text, "preparation", "ongoing.remote_per_cast_projectile_expected_type"),
        (preparation_text, "preparation", "remote_cast_sequence="),
        (projectile_observation_text, "projectile_observation", "IsPurePrimaryProjectileActorType"),
        (projectile_observation_text, "projectile_observation", "ExpectedPurePrimaryProjectileTypeForSelectionState"),
        (projectile_observation_text, "projectile_observation", "return 0x7D3"),
        (projectile_observation_text, "projectile_observation", "0x7D4"),
        (projectile_observation_text, "projectile_observation", "return 0x7D5"),
        (projectile_observation_text, "projectile_observation", "TryListSceneActors"),
        (projectile_observation_text, "projectile_observation", "TryFindNewPurePrimaryProjectileActorInScene("),
        (processing_text, "processing", "TryFindNewPurePrimaryProjectileActorInScene("),
        (processing_text, "processing", "TryFindPurePrimaryProjectileActorStateInScene("),
        (processing_text, "processing", "ongoing.remote_per_cast_projectile_expected_type"),
        (processing_text, "processing", "remote_per_cast_projectile_observed_actor"),
        (processing_text, "processing", "remote_per_cast_projectile_reached_target"),
        (processing_text, "processing", "remote_per_cast_projectile_missing_ticks_waiting"),
        (projectile_observation_text, "projectile_observation", "TryFindPurePrimaryProjectileActorStateInScene("),
        (release_text, "release", "remote_cast_sequence="),
        (release_text, "release", "remote_projectile_expected_type="),
        (release_text, "release", "remote_projectile_observed_actor="),
        (release_text, "release", "remote_projectile_reached_target="),
        (release_text, "release", "remote_projectile_missing_ticks="),
        (player_control_text, "player_control", "native_tick_ms="),
        (player_control_text, "player_control", "native_queue_id="),
    )
    missing_observation_tokens = [
        f"{label}:{token}" for text, label, token in required_observation_tokens if token not in text
    ]
    if missing_observation_tokens:
        raise StaticReTestFailure(
            "remote per-cast projectile observation is missing token(s): " +
            ", ".join(missing_observation_tokens))

    required_emission_guard_tokens = (
        "HasNativeRemotePerCastProjectileEmission",
        "binding->ongoing_cast.remote_per_cast_projectile_observed",
        "binding->ongoing_cast.remote_per_cast_projectile_emission_latched",
        "binding->ongoing_cast.mana_charge_kind !=\n            multiplayer::BotManaChargeKind::PerCast",
        "HookPurePrimaryAttackDispatch",
        "remote_per_cast_duplicate_dispatches_suppressed",
        "TryFindNewPurePrimaryProjectileActorInScene(",
        "ongoing.remote_per_cast_projectile_emission_latched = true",
    )
    missing_emission_guard_tokens = [
        token for token in required_emission_guard_tokens
        if token not in player_cast_text
    ]
    if missing_emission_guard_tokens:
        raise StaticReTestFailure(
            "observed remote per-cast projectiles must suppress repeat native emission: " +
            ", ".join(missing_emission_guard_tokens))
    required_dispatch_latch_tokens = (
        (participant_state_text, "participant_state", "remote_per_cast_projectile_emission_latched"),
        (participant_state_text, "participant_state", "remote_per_cast_duplicate_dispatches_suppressed"),
        (keyboard_injection_text, "keyboard_injection", "kPurePrimaryAttackDispatch"),
        (keyboard_injection_text, "keyboard_injection", "HookPurePrimaryAttackDispatch"),
        (keyboard_injection_text, "keyboard_injection", "pure_primary_attack_dispatch_hook"),
        (keyboard_injection_text, "keyboard_injection", "Failed to install pure-primary attack dispatch hook"),
    )
    missing_dispatch_latch_tokens = [
        f"{label}:{token}"
        for text, label, token in required_dispatch_latch_tokens
        if token not in text
    ]
    if missing_dispatch_latch_tokens:
        raise StaticReTestFailure(
            "remote per-cast native dispatch dedupe is not wired end-to-end: " +
            ", ".join(missing_dispatch_latch_tokens))
    dispatch_hook_start = player_cast_text.find(
        "void __fastcall HookPurePrimaryAttackDispatch")
    dispatch_hook_end = player_cast_text.find(
        "void __fastcall", dispatch_hook_start + 1)
    dispatch_hook_body = player_cast_text[
        dispatch_hook_start:
        dispatch_hook_end if dispatch_hook_end != -1 else len(player_cast_text)
    ]
    dispatch_latch_guard_pos = dispatch_hook_body.find(
        "if (ongoing.remote_per_cast_projectile_emission_latched)")
    dispatch_original_pos = dispatch_hook_body.find("original(self)")
    dispatch_observation_pos = dispatch_hook_body.find(
        "TryFindNewPurePrimaryProjectileActorInScene(")
    dispatch_latch_set_pos = dispatch_hook_body.find(
        "ongoing.remote_per_cast_projectile_emission_latched = true")
    if not (
        dispatch_latch_guard_pos != -1 and
        dispatch_original_pos != -1 and
        dispatch_observation_pos != -1 and
        dispatch_latch_set_pos != -1 and
        dispatch_latch_guard_pos < dispatch_original_pos <
        dispatch_observation_pos < dispatch_latch_set_pos
    ):
        raise StaticReTestFailure(
            "remote per-cast dispatch must guard, emit once, observe the real projectile, then latch")
    for hook_name in ("HookPlayerActorPurePrimaryGate", "HookSpellCastDispatcher"):
        hook_start = player_cast_text.find(f"void __fastcall {hook_name}")
        next_hook = player_cast_text.find("void __fastcall", hook_start + 1)
        hook_body = player_cast_text[
            hook_start:next_hook if next_hook != -1 else len(player_cast_text)
        ]
        guard_pos = hook_body.find("HasNativeRemotePerCastProjectileEmission(actor_address, nullptr)")
        original_pos = hook_body.find("original(self)")
        if guard_pos == -1 or original_pos == -1 or guard_pos > original_pos:
            raise StaticReTestFailure(
                f"{hook_name} must suppress repeat per-cast emission before stock execution")

    required_startup_sanitizer_tokens = (
        "TryReadRollbackAimTargetFloat",
        "std::isfinite(raw) ? raw : fallback_value",
        "memory.TryWriteField(actor_address, offset, *value)",
        "aim_x_fallback",
        "aim_y_fallback",
    )
    missing_startup_sanitizer_tokens = [
        token for token in required_startup_sanitizer_tokens
        if token not in preparation_text
    ]
    if missing_startup_sanitizer_tokens:
        raise StaticReTestFailure(
            "remote cast startup does not sanitize stale non-finite aim-target rollback fields: " +
            ", ".join(missing_startup_sanitizer_tokens))
    if re.search(
        r"TryReadFiniteFloatField\(\s*actor_address,\s*kActorAimTargetXOffset",
        preparation_text,
        re.S,
    ) or re.search(
        r"TryReadFiniteFloatField\(\s*actor_address,\s*kActorAimTargetYOffset",
        preparation_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "remote cast startup must not reject stale non-finite actor aim-target cache fields")
    if re.search(
        r"remote_per_cast_pure_primary_no_handle_settled\s*=\s*"
        r".*remote_per_cast_projectile_observed_ticks_waiting\s*>=\s*"
        r"kRemotePerCastPurePrimaryProjectileSettleTicks",
        processing_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "targeted remote pure-primary projectiles must not settle solely from observed tick count")
    if re.search(
        r"remote_per_cast_projectile_impact_lifecycle_settled\s*=\s*"
        r".*remote_per_cast_projectile_reached_target\s*&&",
        processing_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "targeted remote pure-primary projectiles must wait for native projectile disappearance, not target proximity")
    impact_lifecycle_initializer = re.search(
        r"remote_per_cast_projectile_impact_lifecycle_settled\s*=\s*(?P<body>.*?);",
        processing_text,
        re.S,
    )
    if (
        impact_lifecycle_initializer is not None and
        "remote_per_cast_projectile_observed_ticks_waiting" in
        impact_lifecycle_initializer.group("body")
    ):
        raise StaticReTestFailure(
            "targeted remote pure-primary projectiles must not settle from an observed-tick safety cap")
    if not re.search(
        r"preserve_remote_per_cast_projectile_target\s*=\s*"
        r".*ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary"
        r".*multiplayer::BotManaChargeKind::PerCast"
        r".*ongoing\.target_actor_address\s*!=\s*0",
        processing_text,
        re.S,
    ):
        raise StaticReTestFailure(
            "remote per-cast pure-primary casts must preserve the initial target through release updates")

    required_replacement_tokens = (
        "ReleaseActiveLocalCastInputForReplacement",
        "Multiplayer local active cast replaced by native cast",
        "replacement_native_queue_id",
        "CastInputPhase::Released",
    )
    missing_replacement_tokens = [
        token for token in required_replacement_tokens if token not in transport_text
    ]
    if missing_replacement_tokens:
        raise StaticReTestFailure(
            "held primary native restarts are still dropped instead of replacing the active replicated cast: " +
            ", ".join(missing_replacement_tokens))
    if "Multiplayer local cast event dropped while gesture active" in transport_text:
        raise StaticReTestFailure(
            "held primary native restarts still use the old drop path while a gesture is active")
    required_idle_remote_suppression_tokens = (
        "sanitize_native_remote_idle_control_brain",
        "ClearIdleNativeRemoteCastReplayState(actor_address, selection_pointer);",
        "ClearIdleNativeRemoteCastReplayState(actor_address);",
        "IsIdleNativeRemoteParticipantActor(actor_address, nullptr)",
        "IsNativeRemoteParticipantBinding(binding) &&",
        "!binding->ongoing_cast.active",
        "kActorPrimaryActionLatchE4Offset",
        "kActorPrimaryActionLatchE8Offset",
        "kActorPostGateActiveByteOffset",
        "(void)write_vector2(param2, 0.0f, 0.0f);",
    )
    missing_idle_remote_suppression_tokens = [
        token for token in required_idle_remote_suppression_tokens
        if token not in player_control_text and token not in player_cast_text
    ]
    if missing_idle_remote_suppression_tokens:
        raise StaticReTestFailure(
            "idle native-remote participants must not let stock control brain replay casts: " +
            ", ".join(missing_idle_remote_suppression_tokens))
    idle_remote_suppression = re.search(
        r"if\s*\(\s*sanitize_native_remote_idle_control_brain\s*\)\s*\{(?P<body>.*?)\n\s*\}",
        player_control_text,
        re.S,
    )
    if idle_remote_suppression is None:
        raise StaticReTestFailure("idle native-remote control-brain sanitation block is missing")
    idle_remote_suppression_body = idle_remote_suppression.group("body")
    if "return;" in idle_remote_suppression_body:
        raise StaticReTestFailure(
            "idle native-remote control-brain sanitation must not skip stock original()")
    original_call = player_control_text.find("original(self, param2, param3);")
    sanitation_before = player_control_text.find("if (sanitize_native_remote_idle_control_brain)")
    sanitation_after = player_control_text.find(
        "if (sanitize_native_remote_idle_control_brain)",
        original_call + len("original(self, param2, param3);") if original_call != -1 else 0,
    )
    if (
        original_call == -1 or
        sanitation_before == -1 or
        sanitation_after == -1 or
        sanitation_before > original_call or
        sanitation_after < original_call
    ):
        raise StaticReTestFailure(
            "idle native-remote control-brain sanitation must scrub before and after stock original()")
    for hook_name in ("HookPlayerActorPurePrimaryGate", "HookSpellCastDispatcher"):
        hook_start = player_cast_text.find(f"void __fastcall {hook_name}")
        if hook_start == -1:
            raise StaticReTestFailure(f"{hook_name} is missing")
        next_hook = player_cast_text.find("void __fastcall", hook_start + 1)
        hook_body = player_cast_text[hook_start:next_hook if next_hook != -1 else len(player_cast_text)]
        guard_pos = hook_body.find("IsIdleNativeRemoteParticipantActor(actor_address, nullptr)")
        original_pos = hook_body.find("original(self)")
        if guard_pos == -1 or original_pos == -1 or guard_pos > original_pos:
            raise StaticReTestFailure(
                f"{hook_name} must reject idle native-remote replay before stock cast execution")
    required_mouse_release_tokens = (
        (runtime_state_text, "runtime_state", "injected_mouse_left_active"),
        (mouse_refresh_text, "mouse_refresh", "Released injected gameplay mouse-left"),
        (mouse_refresh_text, "mouse_refresh", "kGameplayCastIntentOffset"),
        (input_queue_text, "input_queue", "ClearQueuedGameplayMouseLeft"),
        (input_queue_text, "input_queue", "pending_mouse_left_frames.store(0"),
        (verifier_text, "real_input_verifier", "sd.input.clear_mouse_left"),
    )
    missing_mouse_release_tokens = [
        f"{label}:{token}" for text, label, token in required_mouse_release_tokens if token not in text
    ]
    if missing_mouse_release_tokens:
        raise StaticReTestFailure(
            "queued gameplay mouse-left input must release its injected press/cast-intent state: " +
            ", ".join(missing_mouse_release_tokens))

    if "remote_projectile_observed_count != native_hook_count" not in verifier_text:
        if "assert_sequence_counts" not in verifier_text:
            raise StaticReTestFailure(
                "real-input spell verifier must reject remote projectile lifecycle overproduction")
    if "parse_remote_settle_sequences" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must compare completed remote cast sequences")
    if "parse_local_pressed_sequences" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must compare against source cast sequences")
    if "Multiplayer local native cast sent" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must map native queue ids to transport cast sequences")
    if '"sampled_fire_addresses": sorted(observed_fire)' not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must report sampled projectile actors")
    if "remote_projectile_observed_sequences" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must report completed remote projectile lifecycle sequences")
    if "native_hook_count = count_local_native_queues" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must compare remote presentation against source native hook count")
    if "remote_settle_count" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must require one remote per-cast lifecycle settlement")
    if "held_fire |= parse_unique_fire(state)" not in verifier_text:
        raise StaticReTestFailure(
            "real-input spell verifier must sample short-lived projectiles during the hold window")
    required_animation_element_verifier_tokens = (
        "parse_remote_projectile_spawn_sequences",
        "remote_projectile_expected_type=",
        "remote_projectile_observed=1",
        "obj_type=",
        "runtime_observed_sequences",
        "sample_observed_projectile",
    )
    missing_animation_element_verifier_tokens = [
        token for token in required_animation_element_verifier_tokens
        if token not in animation_element_verifier_text
    ]
    if missing_animation_element_verifier_tokens:
        raise StaticReTestFailure(
            "all-element verifier does not assert exact runtime projectile type evidence: " +
            ", ".join(missing_animation_element_verifier_tokens))

    return "remote per-cast primaries settle from projectile observation and verifier rejects overfire"


def test_remote_held_input_casts_defer_lifecycle_to_sender_input() -> str:
    processing_text = read_text(PENDING_CAST_PROCESSING)

    target_lost_guard = re.search(
        r"const bool target_lost =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if target_lost_guard is None:
        raise StaticReTestFailure("target-lost guard was not found")
    target_lost_body = target_lost_guard.group("body")
    required_target_lost_tokens = (
        "!remote_input_driven_cast",
        "held_target_missing",
        "kTargetlessRetargetGraceTicks",
    )
    missing_target_lost_tokens = [
        token for token in required_target_lost_tokens
        if token not in target_lost_body
    ]
    if missing_target_lost_tokens:
        raise StaticReTestFailure(
            "remote held input can still be cleaned up as target-lost: " +
            ", ".join(missing_target_lost_tokens))

    required_processing_tokens = (
        "Remote-player casts are driven by the sender's input stream.",
        "remote_input_active_without_release",
        "remote_input_release_settled",
        "!remote_input_active_without_release",
    )
    missing_processing_tokens = [
        token for token in required_processing_tokens
        if token not in processing_text
    ]
    if missing_processing_tokens:
        raise StaticReTestFailure(
            "remote held input lifecycle is missing sender-input guard token(s): " +
            ", ".join(missing_processing_tokens))

    safety_cap_guard = re.search(
        r"const bool safety_cap_hit =(?P<body>.*?);",
        processing_text,
        re.DOTALL,
    )
    if safety_cap_guard is None:
        raise StaticReTestFailure("safety-cap guard was not found")
    if "!remote_input_active_without_release" not in safety_cap_guard.group("body"):
        raise StaticReTestFailure(
            "remote held input can still hit the generic safety cap while sender input is active")

    return "remote held input casts defer lifecycle cleanup to sender release or timeout"


def test_local_primary_network_capture_is_single_owner_and_preserves_lua_events() -> str:
    spell_hook_text = read_text(RUN_LIFECYCLE_SPELL_CAST_HOOKS)
    player_control_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    stock_input_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/local_player_stock_input_runtime.inl"
    )
    player_tick_text = read_text(PLAYER_ACTOR_TICK_HOOK)
    input_queue_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl"
    )
    required_lua_tokens = (
        "bool IsLocalPlayerActorForRunLifecycle(uintptr_t actor_address)",
        "ResolveLocalPlayerActorForRunLifecycle()",
        "if (!IsLocalPlayerActorForRunLifecycle(self_address))",
        "last_dispatched_lua_spell_click_serial",
        "DispatchLuaSpellCast(spell_id, x, y, direction_x, direction_y);",
    )
    missing_lua = [
        token for token in required_lua_tokens if token not in spell_hook_text
    ]
    if missing_lua:
        raise StaticReTestFailure(
            "run-lifecycle spell hooks do not preserve local-only Lua events: " +
            ", ".join(missing_lua))

    guard_pos = spell_hook_text.find("if (!IsLocalPlayerActorForRunLifecycle(self_address))")
    lua_dedupe_pos = spell_hook_text.find("last_dispatched_lua_spell_click_serial")
    lua_dispatch_pos = spell_hook_text.find("DispatchLuaSpellCast(")
    if not (
        guard_pos >= 0
        and lua_dedupe_pos > guard_pos
        and lua_dispatch_pos > lua_dedupe_pos
    ):
        raise StaticReTestFailure(
            "run-lifecycle spell hooks must prove local ownership and deduplicate "
            "the input before dispatching Lua")
    if (
        "TryClaimGameplayMouseLeftPrimaryCastEdge(" in spell_hook_text
        or "multiplayer::QueueLocalSpellCastEvent(" in spell_hook_text
    ):
        raise StaticReTestFailure(
            "run-lifecycle Lua hooks must not claim or queue the multiplayer "
            "primary cast input")

    targetless_tokens = (
        "IsActiveTargetlessAirPrimaryCast(",
        "descriptor.primary_entry_index != kAirPrimaryEntryIndex",
        "target_actor_address == 0",
        "TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)",
        "LocalPrimaryCastCaptureKind::TargetlessAir",
        "TryConsumeManualSpawnerPrimaryCastAllowance()",
        "multiplayer::QueueLocalSpellCastEvent(",
    )
    targetless_text = player_control_text + stock_input_text
    missing_targetless = [
        token for token in targetless_tokens if token not in targetless_text
    ]
    if missing_targetless:
        raise StaticReTestFailure(
            "targetless Air capture does not own the exact native input edge: "
            + ", ".join(missing_targetless)
        )
    if (
        "compare_exchange_weak" not in input_queue_text
        or "claimed_primary_cast_edge_serial" not in input_queue_text
    ):
        raise StaticReTestFailure(
            "native primary capture does not atomically claim one network cast per input edge"
        )

    stock_tick_pos = player_tick_text.find("original(self);")
    post_stock_capture_pos = player_tick_text.find(
        "CaptureLocalPlayerPostStockPrimaryInput(actor_address);"
    )
    if stock_tick_pos < 0 or post_stock_capture_pos <= stock_tick_pos:
        raise StaticReTestFailure(
            "targetless Air capture must observe stock actor state after the local player tick"
        )

    return (
        "Lua spell notification and multiplayer primary capture have distinct "
        "dedupe ownership, with post-stock targetless Air capture"
    )


def test_multiplayer_nameplates_render_from_native_scene_passes() -> str:
    hud_text = read_text(GAMEPLAY_HUD_HOOKS)
    public_state_text = read_text(GAMEPLAY_PUBLIC_STATE_GETTERS)
    overlay_text = read_text(DEBUG_UI_OVERLAY_FRAME_RENDER)
    overlay_health_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/gameplay_health_bar_rendering.inl"
    )
    overlay_primitives_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/font_atlas_rendering.inl"
    )
    overlay_capture_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/capture_session.inl"
    )
    overlay_glyph_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/glyph_observation.inl"
    )
    overlay_projection_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/"
        "gameplay_nameplate_projection.inl"
    )
    overlay_render_hooks_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/render_hooks.inl"
    )
    overlay_header_text = read_text(DEBUG_UI_OVERLAY_HEADER)
    overlay_public_text = read_text(DEBUG_UI_OVERLAY_PUBLIC_SURFACE)
    mod_loader_header_text = read_text(MOD_LOADER_HEADER)
    mod_loader_text = read_text(MOD_LOADER_GAMEPLAY)
    layout_text = read_text(BINARY_LAYOUT)
    animation_text = read_text(ACTOR_ANIMATION_ADVANCE_HOOK)
    player_tick_text = read_text(PLAYER_ACTOR_TICK_HOOK)
    keyboard_injection_text = read_text(GAMEPLAY_KEYBOARD_INJECTION)
    native_types_text = read_text(GAMEPLAY_NATIVE_FUNCTION_TYPES)
    verifier_text = read_text(MULTIPLAYER_HUD_NAMES_VERIFIER)
    steam_verifier_text = read_text(STEAM_FRIEND_HUB_VISUALS_VERIFIER)
    physical_steam_verifier_text = read_text(
        STEAM_FRIEND_ACTIVE_PAIR_VISUALS_VERIFIER
    )
    hud_label_materializer_text = read_text(HUD_LABEL_ASSET_MATERIALIZER)

    required_animation_tokens = (
        "struct AnimationAdvanceContextScope",
        "~AnimationAdvanceContextScope()",
        "original(self);",
        "IsTrackedWizardParticipantActorForHud(actor_address)",
        "TryGetGameplayHudParticipantDisplayNameForActor(",
        "&health_ratio);",
        "DrawGameplayHudParticipantName(",
        "participant_id,",
        "health_ratio,",
        "source=playerwizard_render",
        "health_ratio=",
        "health_bar=dx9",
    )
    missing_animation = [
        token for token in required_animation_tokens
        if token not in animation_text
    ]
    if missing_animation:
        raise StaticReTestFailure(
            "PlayerWizard render callback no longer draws remote names and health bars: " +
            ", ".join(missing_animation))

    forbidden_animation_tokens = (
        "TryListGameplayParticipantNameplates(",
        "PublishGameplayParticipantNameplateOverlaySnapshot",
        "source=actor_callback",
        "DrawGameplayParticipantHealthBar(",
        "health_segments",
        # The rendered ratio must come from the authoritative participant
        # runtime snapshot, never from tick-synced actor progression memory
        # that freezes while player-actor ticks are paused.
        "TryGetGameplayParticipantHealthRatio(",
        "TryReadActorProgressionHealth(",
    )
    present_animation = [
        token for token in forbidden_animation_tokens if token in animation_text
    ]
    if present_animation:
        raise StaticReTestFailure(
            "PlayerWizard native render path contains stale overlay/callback plumbing: " +
            ", ".join(present_animation))

    forbidden_hud_tokens = (
        "TryListGameplayParticipantNameplates(",
        "multiplayer-nameplate",
        "ShouldDrawGameplayHudParticipantNameFromActorCallback",
        "PublishGameplayParticipantNameplateOverlaySnapshot",
        "ClearDebugUiGameplayNameplateOverlaySnapshot",
        "DebugUiGameplayNameplateOverlayItem",
        "PublishDebugUiGameplayNameplateOverlaySnapshot",
        "TryProjectGameplayHudNameplatePosition",
        "TryGetPlayerState(",
        "scene_state.kind != \"arena\"",
        "kGameplayHudVirtualWidth",
        "actor_x - player_state.x",
        "DrawGameplayHudUiExactTextAt(",
        "kGameplayUiExactTextObjectRender",
    )
    present_hud = [token for token in forbidden_hud_tokens if token in hud_text]
    if present_hud:
        raise StaticReTestFailure(
            "native nameplate helper still contains stale arena projection or overlay plumbing: " +
            ", ".join(present_hud))

    required_hud_tokens = (
        "void __fastcall HookGameplayUiAllyLabelGlyphDraw(",
        "IsGameplayAllyHudLabelGlyphCall(glyph_address, caller_address)",
        "BuildGameplayAllyHudRows()",
        "ResolveGameplayAllyHudRowIndex(y, rows.size())",
        "DrawGameplayHudAllyBarParticipantName(",
        "&name_layout,",
        "&exception_code);",
        "source=ally_healthbar",
        "stock_label=0",
        "BuildGameplayAllyHudExactText(",
        "EstimateGameplayAllyHudTextWidth(",
        "constexpr float kGameplayAllyHudReservedLabelWidth = 128.0f;",
        "constexpr float kGameplayAllyHudNameHorizontalPadding = 2.0f;",
        "multiplayer::kParticipantDisplayNameBytes - 1",
        '"The ally HUD reservation must fit the longest protocol display name."',
        "resolved.name_left_x = x + kGameplayAllyHudNameHorizontalPadding;",
        "layout_ok=",
        "bar_right_x=",
        "label_right_x=",
        "name_left_x=",
        "name_right_x=",
        "bool CallGameplayExactTextObjectRenderSafe(",
        "NativeStringAssignFn",
        "NativeExactTextObjectRenderFn",
        "NativeGameString native_text",
        "string_assign(&native_text, nullptr)",
        "std::string BuildGameplayNameplateExactText(const std::string& display_name)",
        "constexpr const char* kHalfScaleCommand = \"s(0.5)\"",
        "bool DrawGameplayHudParticipantName(",
        "native gameplay HUD participant name draw",
        "ResolveGameAddressOrZero(kGameplayStringAssign)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectRender)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectGlobal)",
        "kGameplayExactTextObjectOffset",
        "const auto text_object_address = text_object_base + kGameplayExactTextObjectOffset",
        "TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x)",
        "TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y)",
        "y -= 45.0f;",
        "float EstimateGameplayNameplateTextWidth(std::string_view display_name)",
        "constexpr float kNativeGlyphAdvance = 16.0f;",
        "constexpr float kNativeSpaceAdvance = 8.0f;",
        "float CalculateGameplayNameplateDrawX(float actor_x, std::string_view display_name)",
        "x = CalculateGameplayNameplateDrawX(x, display_name);",
        "const auto nameplate_text = BuildGameplayNameplateExactText(display_name);",
        "BeginDebugUiGameplayParticipantNameplateCapture(",
        "EndDebugUiGameplayParticipantNameplateCapture();",
        "CallGameplayExactTextObjectRenderSafe(",
        "nameplate_text.c_str()",
    )
    missing_hud = [token for token in required_hud_tokens if token not in hud_text]
    if missing_hud:
        raise StaticReTestFailure(
            "native remote-name or thin-health-bar rendering contract is incomplete: " +
            ", ".join(missing_hud))

    if "TryReadActorProgressionHealth(" in hud_text:
        raise StaticReTestFailure(
            "native nameplate helpers read tick-synced actor progression health "
            "instead of the authoritative participant runtime vitals")

    ally_rows = hud_text[
        hud_text.index("std::vector<GameplayAllyHudRow> BuildGameplayAllyHudRows()") :
        hud_text.index("\nbool IsGameplayAllyHudLabelGlyphCall(")
    ]
    if "SnapshotRuntimeState()" in ally_rows:
        raise StaticReTestFailure(
            "the per-row ally HUD path deep-copies the full multiplayer runtime")

    required_authoritative_vitals_tokens = (
        "bool TryGetGameplayHudParticipantDisplayNameForActor(",
        "TryGetRemoteParticipantDisplayState(",
        "!resolved_runtime.valid",
        "resolved_runtime.life_current / resolved_runtime.life_max",
        "resolved_runtime.life_max <= 0.0f",
    )
    missing_authoritative_vitals = [
        token for token in required_authoritative_vitals_tokens
        if token not in public_state_text
    ]
    if missing_authoritative_vitals:
        raise StaticReTestFailure(
            "nameplate health no longer resolves from the authoritative "
            "participant runtime snapshot: " +
            ", ".join(missing_authoritative_vitals))

    if "TryGetGameplayHudParticipantNameplateForActor" in public_state_text + animation_text:
        raise StaticReTestFailure(
            "nameplate health retained a redundant display-name API alias")

    nameplate_getter = public_state_text[
        public_state_text.index("bool TryGetGameplayHudParticipantDisplayNameForActor(") :
        public_state_text.index("\nbool TryGetPlayerState(")
    ]
    if "SnapshotRuntimeState()" in nameplate_getter:
        raise StaticReTestFailure(
            "the per-actor nameplate path deep-copies the full multiplayer runtime")

    forbidden_ascii_health_tokens = (
        "constexpr int kBarSegments",
        "std::string bar_text",
        "\"_s(0.25)[\"",
        "filled_segment_count",
        "bar_text.append",
    )
    present_ascii_health = [
        token for token in forbidden_ascii_health_tokens if token in hud_text
    ]
    if present_ascii_health:
        raise StaticReTestFailure(
            "ASCII participant health fallback remains active: "
            + ", ".join(present_ascii_health)
        )

    required_materializer_tokens = (
        'private const string DefaultAllyLabel = "ALLY";',
        "private const int GeneratedAllyLabelWidth = 128;",
        "return string.IsNullOrEmpty(configuredLabel) ? DefaultAllyLabel : configuredLabel;",
    )
    missing_materializer = [
        token for token in required_materializer_tokens
        if token not in hud_label_materializer_text
    ]
    if missing_materializer:
        raise StaticReTestFailure(
            "staged ally HUD label reservation no longer matches the native name layout: " +
            ", ".join(missing_materializer))

    forbidden_public_tokens = (
        "struct SDModGameplayNameplateDrawItem",
        "TryListGameplayParticipantNameplates(",
        "DebugUiGameplayNameplateOverlayItem",
        "PublishDebugUiGameplayNameplateOverlaySnapshot",
        "ClearDebugUiGameplayNameplateOverlaySnapshot",
    )
    present_public = [
        token for token in forbidden_public_tokens
        if token in public_state_text or token in mod_loader_header_text or token in overlay_header_text or token in overlay_public_text
    ]
    if present_public:
        raise StaticReTestFailure(
            "public nameplate snapshot or overlay API was reintroduced: " +
            ", ".join(present_public))

    forbidden_overlay_tokens = (
        "RenderGameplayParticipantNameplates(",
        "TryListGameplayParticipantNameplates(&items)",
        "TryGetPlayerState(",
        "TryGetSceneState(",
        "struct GameplayNameplateOverlayRenderItem",
        "CopyRecentGameplayNameplateOverlayItems()",
        "BuildGameplayNameplateOverlayRenderItems(",
        "kGameplayNameplateOverlayMaximumIdleMs",
        "kGameplayNameplateVirtualWidth",
        "kGameplayNameplateVirtualHeight",
        "TryProjectGameplayNameplateWithD3dTransform(",
        "DrawGameplayNameplateOverlayItem(",
        "Debug UI overlay rendered cached gameplay nameplates",
        "struct DebugUiGameplayNameplateOverlayItem",
        "PublishDebugUiGameplayNameplateOverlaySnapshot",
        "ClearDebugUiGameplayNameplateOverlaySnapshot",
        "gameplay_nameplate_overlay_items",
        "gameplay_nameplate_overlay_captured_at",
    )
    combined_overlay_text = "\n".join((
        overlay_text,
        overlay_health_text,
        overlay_primitives_text,
        overlay_capture_text,
        overlay_glyph_text,
        overlay_projection_text,
        overlay_render_hooks_text,
        overlay_header_text,
        overlay_public_text,
        mod_loader_text,
    ))
    present_overlay = [token for token in forbidden_overlay_tokens if token in combined_overlay_text]
    if present_overlay:
        raise StaticReTestFailure(
            "D3D gameplay nameplate overlay workaround was reintroduced instead of native commit 35378b3 path: " +
            ", ".join(present_overlay))

    required_dx9_health_tokens = (
        "BeginDebugUiGameplayParticipantNameplateCapture(",
        "EndDebugUiGameplayParticipantNameplateCapture()",
        'capture.surface_id = "gameplay_nameplate";',
        "BuildGameplayParticipantHealthBarRenderItems(",
        # The bar sits flush under the captured name bounds and spans the
        # nameplate width with a readable floor.
        "constexpr float kBarMinimumWidth = 64.0f;",
        "constexpr float kBarVerticalGap = 1.0f;",
        "element.max_x - element.min_x);",
        "item.top = element.max_y + kBarVerticalGap;",
        "GameplayParticipantHealthBarDrawResult DrawGameplayParticipantHealthBar(",
        "GameplayParticipantHealthBarDrawResult::Culled",
        "GameplayParticipantHealthBarDrawResult::Drawn",
        "GameplayParticipantHealthBarDrawResult::Failed",
        "LogGameplayParticipantHealthBarDraw(health_bar, draw_result)",
        'source=dx9_nameplate_healthbar',
        '" ok=" + std::string(drew_bar ? "1" : "0")',
        '" health_percent=" + std::to_string(health_percent)',
        "render_elements.empty() && gameplay_health_bars.empty()",
        "for (const auto& health_bar : gameplay_health_bars)",
        "DrawFilledRect(",
        "DrawRectOutline(",
        "SUCCEEDED(device->DrawPrimitiveUP(",
        "element.gameplay_health_ratio",
        "std::clamp(",
        "bool TryReadUiRenderBase(float* base_x, float* base_y)",
        "capture.expected_origin_x = render_base_x + origin_x;",
        "capture.expected_origin_y = render_base_y + origin_y;",
        "capture.capture_enabled = capture.has_expected_origin;",
        "capture.gameplay_world_width =",
        "TryBuildDestinationQuadBounds(",
        "TryProjectGameplayNameplateQuadBounds(",
        "TryApplyGameplayNameplateViewportClamp(",
        "constexpr float kViewportMargin = 2.0f;",
        "constexpr float kMinimumHealthBarWidth = 64.0f;",
        "const bool intersects_viewport =",
        "capture.gameplay_viewport_offset_resolved = true;",
        "GetLastSeenD3d9Device()",
        "kTextQuadDrawStateDepthOffset",
        "GetTransform(D3DTS_WORLD, &world)",
        "GetTransform(D3DTS_VIEW, &view)",
        "GetTransform(D3DTS_PROJECTION, &projection)",
        "point = TransformD3dRowVector(point, world);",
        "point = TransformD3dRowVector(point, view);",
        "clip.w <= kMinimumPositiveClipW",
        "name_bounds=(",
        "ObserveActiveExactTextQuad(self, draw_vertices, arg3);",
        "original(self, draw_vertices, arg3);",
        "const float* destination_vertices,",
        "const float* /*texture_coordinates*/",
    )
    missing_dx9_health = [
        token
        for token in required_dx9_health_tokens
        if token not in combined_overlay_text
    ]
    if missing_dx9_health:
        raise StaticReTestFailure(
            "DX9 participant health-bar rendering contract is incomplete: "
            + ", ".join(missing_dx9_health)
        )

    forbidden_quad_heuristics = (
        "alternate_valid",
        "alternate_area",
        "primary_area",
        "TryBuildGlyphQuadBounds(arg3",
        "capture.has_expected_origin = false;",
    )
    present_quad_heuristics = [
        token
        for token in forbidden_quad_heuristics
        if token in combined_overlay_text
    ]
    if present_quad_heuristics:
        raise StaticReTestFailure(
            "gameplay nameplate capture reintroduced unverified geometry "
            "fallbacks: " + ", ".join(present_quad_heuristics)
        )

    quad_function_start = overlay_glyph_text.index(
        "void ObserveActiveExactTextQuad("
    )
    gameplay_projection_start = overlay_glyph_text.index(
        'if (capture.surface_id == "gameplay_nameplate")',
        quad_function_start,
    )
    gameplay_projection_end = overlay_glyph_text.index(
        "capture.min_x =",
        gameplay_projection_start,
    )
    gameplay_projection_branch = overlay_glyph_text[
        gameplay_projection_start:gameplay_projection_end
    ]
    for token in (
        "TryProjectGameplayNameplateQuadBounds(",
        "draw_state,",
        "destination_vertices,",
        "base_x,",
        "base_y,",
    ):
        if token not in gameplay_projection_branch:
            raise StaticReTestFailure(
                "gameplay nameplate quad capture does not project through the "
                "stock fixed-function transform: " + token
            )

    required_layout_tokens = (
        "gameplay_ui_glyph_draw=0x004143D0",
        "gameplay_ui_centered_glyph_draw=0x004142E0",
        "gameplay_ally_label_glyph_return=0x005D3521",
        "gameplay_string_assign=0x00402AE0",
        "gameplay_exact_text_object_render=0x0043BCD0",
        "gameplay_ui_bundle=0x008199E4",
        "gameplay_exact_text_object=0x008199A0",
        "gameplay_ui_ally_label_glyph=0x38",
        "gameplay_exact_text_object=0xE7D98",
    )
    missing_layout = [token for token in required_layout_tokens if token not in layout_text]
    if missing_layout:
        raise StaticReTestFailure(
            "native exact-text layout keys are missing: " +
            ", ".join(missing_layout))

    forbidden_layout_tokens = ("gameplay_nameplate_text_object",)
    present_layout = [token for token in forbidden_layout_tokens if token in layout_text]
    if present_layout:
        raise StaticReTestFailure(
            "stale nameplate-only native text layout keys were reintroduced: " +
            ", ".join(present_layout))

    required_native_type_tokens = (
        "using GameplayUiGlyphDrawFn = void(__thiscall*)(void* self, float x, float y)",
        "using GameplayHudRenderDispatchFn = void(__thiscall*)(void* self, int render_case, uintptr_t arg1, uintptr_t arg2)",
        "struct NativeGameString",
        "static_assert(sizeof(NativeGameString) == 0x1C",
        "using NativeStringAssignFn = void(__thiscall*)(void* self, char* text)",
        "using NativeExactTextObjectRenderFn = void(__thiscall*)(void* self, NativeGameString text, float x, float y)",
    )
    missing_native_types = [
        token for token in required_native_type_tokens
        if token not in native_types_text
    ]
    if missing_native_types:
        raise StaticReTestFailure(
            "native text function types are missing: " +
            ", ".join(missing_native_types))

    required_injection_tokens = (
        "ResolveGameAddressOrZero(kGameplayUiGlyphDraw)",
        "ResolveGameAddressOrZero(kGameplayUiCenteredGlyphDraw)",
        "ResolveGameAddressOrZero(kGameplayAllyLabelGlyphReturn)",
        "ResolveGameAddressOrZero(kGameplayUiBundleGlobal)",
        "kGameplayUiAllyLabelGlyphOffset == 0",
        "reinterpret_cast<void*>(&HookGameplayUiGlyphDraw)",
        "reinterpret_cast<void*>(&HookGameplayUiAllyLabelGlyphDraw)",
        "kGameplayUiGlyphDrawHookPatchSize",
        "kGameplayUiCenteredGlyphDrawHookPatchSize",
        "gameplay_ui_glyph_draw_hook",
        "gameplay_ui_ally_label_glyph_draw_hook",
        "ResolveGameAddressOrZero(kGameplayStringAssign)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectRender)",
        "ResolveGameAddressOrZero(kGameplayExactTextObjectGlobal)",
        "kGameplayExactTextObjectOffset == 0",
        "native HUD text helpers",
        "gameplay_exact_text_object_offset=",
    )
    missing_injection = [
        token for token in required_injection_tokens
        if token not in keyboard_injection_text
    ]
    if missing_injection:
        raise StaticReTestFailure(
            "gameplay injection startup no longer validates native HUD text helpers: " +
            ", ".join(missing_injection))

    required_player_tick_tokens = (
        "native_remote_pre_tick_progression_runtime",
        "ApplyNativeRemoteParticipantPlayback(binding, actor_address, native_tick_now_ms)",
        "ApplyNativeRemoteParticipantPresentationState(binding, actor_address)",
        "ApplyReplicatedWorldSnapshotIfActive(gameplay_address_for_pump, static_cast<std::uint64_t>(::GetTickCount64()))",
    )
    missing_player_tick = [
        token for token in required_player_tick_tokens
        if token not in player_tick_text
    ]
    if missing_player_tick:
        raise StaticReTestFailure(
            "player tick no longer owns remote participant playback/presentation: " +
            ", ".join(missing_player_tick))

    if "PublishGameplayParticipantNameplateOverlaySnapshot();" in player_tick_text:
        raise StaticReTestFailure(
            "player tick still publishes stale D3D nameplate overlay snapshots")

    required_verifier_tokens = (
        "launch_trio(god_mode=False, tile_windows=True)",
        "wait_for_all_relationships(\"hub\", timeout)",
        "wait_for_all_relationships(\"testrun\", timeout)",
        "place_trio_for_capture(timeout)",
        "set_local_player_vitals(",
        "wait_for_remote_matches_owner_health(",
        "verify_dx9_nameplate_health_bar_geometry(",
        "name_bounds=",
        "DX9 health bar is not centered under its name",
        "DX9 health bar is not flush under its name",
        "health_percent={EXPECTED_HALF_HEALTH_PERCENT}",
        "source=playerwizard_render",
        "source=dx9_nameplate_healthbar",
        '"health_bar=dx9"',
        '"dx9_health_bar": dx9_health_line',
        "source=ally_healthbar",
        "stock_label=0",
        "layout_ok=1",
        "wait_for_render_logs(timeout)",
        "verify_ally_hud_name_layout(ally_hud_line)",
        "ally HUD name overlaps its health bar",
        "ally HUD name extends outside its reserved label slot",
        "reversed(log_text.splitlines())",
        "capture_game_backbuffer(",
    )
    missing_verifier = [
        token for token in required_verifier_tokens if token not in verifier_text
    ]
    if missing_verifier:
        raise StaticReTestFailure(
            "three-player name/health-bar regression verifier is incomplete: " +
            ", ".join(missing_verifier))

    required_steam_verifier_tokens = (
        "suspend_runtime_test_godmode(",
        "restore_runtime_test_godmode(",
        "_G.__sdmod_steam_test_godmode_enabled = false",
        "verify_dx9_nameplate_health_bar_geometry(",
        "attachment_visual_type",
        "attachment_visual_address",
    )
    missing_steam_verifier = [
        token
        for token in required_steam_verifier_tokens
        if token not in steam_verifier_text
    ]
    if missing_steam_verifier:
        raise StaticReTestFailure(
            "Steam friend name/health-bar regression verifier is incomplete: "
            + ", ".join(missing_steam_verifier)
        )

    required_physical_resolution_tokens = (
        "def verify_capture_resolution_contract(",
        'parser.add_argument("--require-distinct-resolutions", action="store_true")',
        'resolutions["host"] != resolutions["client"]',
        "participant name/health geometry escaped its",
        "VIEWPORT_EDGE_EXERCISE_DISTANCE = 24.0",
        "edge_contained_health_bars",
        "did not exercise a participant",
        'output["resolution_contract"] = verify_capture_resolution_contract(',
        "wait_for_local_transform_settled(",
        '"host_settled": list(host_target)',
        '"client_settled": list(client_target)',
        "suspend_runtime_test_godmode(",
        "restore_runtime_test_godmode(",
        "client_godmode_before = suspend_runtime_test_godmode(",
    )
    missing_physical_resolution = [
        token
        for token in required_physical_resolution_tokens
        if token not in physical_steam_verifier_text
    ]
    if missing_physical_resolution:
        raise StaticReTestFailure(
            "physical Steam cross-resolution verifier is incomplete: "
            + ", ".join(missing_physical_resolution)
        )

    return "remote names, DX9 health bars, and ally names render through the native PlayerWizard and ally-HUD passes"


def test_memory_region_cache_refreshes_newly_committed_native_objects() -> str:
    text = MEMORY_ACCESS_REGIONS.read_text(encoding="utf-8")
    required_tokens = (
        "if (!has_required_access(region))",
        "RefreshRegion(current, &region)",
        "if (!is_executable(region))",
        "formerly reserved range",
    )
    missing = [token for token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "memory-region cache can reject newly committed native objects: "
            + ", ".join(missing)
        )

    stale_short_circuits = (
        "if (!region.committed || region.guarded || region.no_access) {\n"
        "            return false;",
        "if (!region.committed || region.guarded || region.no_access || !region.executable) {\n"
        "            return false;",
    )
    present = [token for token in stale_short_circuits if token in text]
    if present:
        raise StaticReTestFailure(
            "memory-region access still trusts an inaccessible cached reservation"
        )

    return "inaccessible cached reservations are refreshed after native heap/page commits"


def test_write_watches_are_transparent_to_loader_memory_access() -> str:
    memory_header = MEMORY_ACCESS_HEADER.read_text(encoding="utf-8")
    memory_regions = MEMORY_ACCESS_REGIONS.read_text(encoding="utf-8")
    debug_core = RUNTIME_DEBUG_CORE.read_text(encoding="utf-8")
    registration = RUNTIME_DEBUG_WATCH_REGISTRATION.read_text(encoding="utf-8")
    management = RUNTIME_DEBUG_WATCH_MANAGEMENT.read_text(encoding="utf-8")
    shutdown = RUNTIME_DEBUG_WATCH.read_text(encoding="utf-8")
    handler = RUNTIME_DEBUG_WATCH_HELPERS.read_text(encoding="utf-8")

    required_by_source = {
        "memory_access.h": (
            "RegisterManagedGuardRange",
            "UnregisterManagedGuardRange",
            "IsManagedGuardRange",
            "managed_guard_ranges_",
        ),
        "memory_access_regions.cpp": (
            "candidate.guarded && !IsManagedGuardRange(current, candidate_size)",
            "(!candidate.guarded || IsManagedGuardRange(current, candidate_size))",
        ),
        "runtime_debug_core.cpp": (
            "ProcessMemory::Instance().InvalidateRange(page_base, page_size)",
        ),
        "runtime_debug_watch_registration.cpp": (
            "RegisterManagedGuardRange(",
            "UnregisterManagedGuardRange(",
        ),
        "runtime_debug_watch_management.cpp": ("UnregisterManagedGuardRange(",),
        "runtime_debug_watch.cpp": ("UnregisterManagedGuardRange(",),
    }
    source_text = {
        "memory_access.h": memory_header,
        "memory_access_regions.cpp": memory_regions,
        "runtime_debug_core.cpp": debug_core,
        "runtime_debug_watch_registration.cpp": registration,
        "runtime_debug_watch_management.cpp": management,
        "runtime_debug_watch.cpp": shutdown,
    }
    missing = [
        f"{source}:{token}"
        for source, tokens in required_by_source.items()
        for token in tokens
        if token not in source_text[source]
    ]
    if missing:
        raise StaticReTestFailure(
            "write-watch guard transparency is incomplete: " + ", ".join(missing)
        )

    capture_position = handler.find("after_bytes_by_hit.reserve(hits_to_log.size())")
    rearm_position = handler.find("page.base_protect | PAGE_GUARD", capture_position)
    log_position = handler.find(
        "LogWriteWatchHit(hits_to_log[index], after_bytes_by_hit[index])",
        capture_position,
    )
    if capture_position == -1 or rearm_position == -1 or log_position == -1:
        raise StaticReTestFailure("write-watch post-write capture sequence was not found")
    capture_read_position = handler.find("ProcessMemory::Instance().TryRead(", capture_position)
    if capture_read_position == -1 or not (
        capture_position < capture_read_position < rearm_position < log_position
    ):
        raise StaticReTestFailure(
            "write-watch post-write bytes must be captured before PAGE_GUARD is rearmed"
        )

    return "managed PAGE_GUARD watches remain transparent to loader and Lua memory access"


def test_player_control_brain_requires_published_gameplay_slot() -> str:
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    required_tokens = (
        "IsPlayerActorPublishedInCurrentGameplaySlot(",
        "kActorSlotOffset",
        "kGameplayPlayerSlotCount",
        "TryResolveCurrentGameplayScene(&live_gameplay_address)",
        "TryResolvePlayerActorForSlot(",
        "return live_published_actor_address == actor_address;",
        "control_brain skipped unpublished player actor during scene transition",
        "s_logged_unpublished_actor.exchange(true",
    )
    missing = [token for token in required_tokens if token not in player_control_text]
    if missing:
        raise StaticReTestFailure(
            "player control-brain scene-transition gate is missing token(s): " +
            ", ".join(missing))

    hook_start = player_control_text.find("void __fastcall HookPlayerControlBrainUpdate(")
    hook_end = player_control_text.find(
        "bool IsActorCurrentLocalPlayerSlotZero(", hook_start)
    if hook_start == -1 or hook_end == -1:
        raise StaticReTestFailure("player control-brain hook body was not found")
    hook_body = player_control_text[hook_start:hook_end]
    publication_guard = hook_body.find(
        "if (!IsPlayerActorPublishedInCurrentGameplaySlot(")
    stock_call = hook_body.find("original(self, param2, param3);")
    if publication_guard == -1 or stock_call == -1 or publication_guard > stock_call:
        raise StaticReTestFailure(
            "player slot publication must be validated before stock control-brain execution")

    if player_control_text.count(
            "static std::atomic<bool> s_logged_unpublished_actor") != 1:
        raise StaticReTestFailure(
            "unpublished player-actor logging must have one process-wide gate")

    guard_end = hook_body.find("\n    }", publication_guard)
    if guard_end == -1 or "return;" not in hook_body[publication_guard:guard_end]:
        raise StaticReTestFailure(
            "unpublished player actors must not reach the stock control-brain routine")

    return "player control-brain skips actors until the current gameplay slot table owns them"
