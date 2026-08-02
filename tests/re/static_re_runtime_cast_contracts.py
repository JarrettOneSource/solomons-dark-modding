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
    SKILL_SELECTION_RULES,
    STEAM_FRIEND_ACTIVE_PAIR_VISUALS_VERIFIER,
    STEAM_FRIEND_HUB_VISUALS_VERIFIER,
    StaticReTestFailure,
    read_mod_loader_header_source,
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
        "IsRemoteInputControlledParticipantBinding(binding) &&",
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


def test_queued_mouse_holds_use_player_tick_duration() -> str:
    runtime_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    mouse_refresh_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    input_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl"
    )
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )

    required_tokens = (
        (runtime_state_text, "runtime_state", "last_mouse_left_hold_player_tick_generation"),
        (runtime_state_text, "runtime_state", "last_mouse_right_hold_player_tick_generation"),
        (mouse_refresh_text, "mouse_refresh", "ConsumeGameplayMouseHoldFrameForCurrentPlayerTick("),
        (mouse_refresh_text, "mouse_refresh", "local_player_tick_generation.load("),
        (mouse_refresh_text, "mouse_refresh", "last_mouse_left_hold_player_tick_generation"),
        (mouse_refresh_text, "mouse_refresh", "last_mouse_right_hold_player_tick_generation"),
        (input_queue_text, "input_queue", "last_mouse_left_hold_player_tick_generation.store("),
        (input_queue_text, "input_queue", "last_mouse_right_hold_player_tick_generation.store("),
        (input_queue_text, "input_queue", "const auto queued_frames ="),
        (input_queue_text, "input_queue", "static_cast<std::uint64_t>(queued_frames) * 50"),
        (player_control_text, "player_control", "const auto edge_serial = GetGameplayMouseLeftEdgeSerial();"),
        (player_control_text, "player_control", "!TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)"),
    )
    missing = [
        f"{label}:{token}"
        for text, label, token in required_tokens
        if token not in text
    ]
    if missing:
        raise StaticReTestFailure(
            "queued gameplay mouse holds are not player-tick bounded: " +
            ", ".join(missing))

    helper_start = mouse_refresh_text.find(
        "bool ConsumeGameplayMouseHoldFrameForCurrentPlayerTick(")
    hook_start = mouse_refresh_text.find("void __fastcall HookGameplayMouseRefresh(")
    if helper_start == -1 or hook_start == -1 or helper_start >= hook_start:
        raise StaticReTestFailure("player-tick mouse-hold consumer is not isolated before the hook")
    helper_body = mouse_refresh_text[helper_start:hook_start]
    generation_read = helper_body.find("local_player_tick_generation.load(")
    generation_claim = helper_body.find("last_consumed_generation.compare_exchange_weak(")
    pending_decrement = helper_body.find("pending_frames.compare_exchange_weak(")
    if not (0 <= generation_read < generation_claim < pending_decrement):
        raise StaticReTestFailure(
            "mouse-hold frames must claim a new player-tick generation before decrementing")
    if mouse_refresh_text.count(
            "ConsumeGameplayMouseHoldFrameForCurrentPlayerTick(") != 3:
        raise StaticReTestFailure(
            "player-tick mouse-hold consumer must serve exactly left and right injection")

    capture_start = player_control_text.find(
        "bool QueueLocalPlayerPrimaryCastForMultiplayer(")
    capture_end = player_control_text.find(
        "void __fastcall HookPurePrimarySpellStart(", capture_start)
    if capture_start == -1 or capture_end == -1:
        raise StaticReTestFailure("local primary multiplayer capture body was not found")
    capture_body = player_control_text[capture_start:capture_end]
    if capture_body.count(
            "!TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)") != 1:
        raise StaticReTestFailure(
            "native primary capture must claim exactly one synthetic input edge")
    if (
        "s_last_pure_primary_tick_ms" in capture_body
        or "s_last_pure_primary_actor" in capture_body
        or "std::uint64_t edge_serial = 0" in capture_body
        or (
            "capture_kind == LocalPrimaryCastCaptureKind::NativeDispatcherPrimary &&\n"
            "        !TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)"
        ) in capture_body
    ):
        raise StaticReTestFailure(
            "pure-primary capture can still amplify one held input edge into tick-rate casts")

    pure_primary_hook_start = player_control_text.find(
        "void __fastcall HookPurePrimarySpellStart(")
    if pure_primary_hook_start == -1:
        raise StaticReTestFailure("pure-primary start hook was not found")
    pure_primary_hook = player_control_text[pure_primary_hook_start:]
    required_emission_tokens = (
        "ApplyLocalPlayerControlTakeoverPrimarySelection(actor_address);",
        "TryListPurePrimaryProjectileActorAddressesInScene(",
        "TryFindNewPurePrimaryProjectileActorInScene(",
        "if (local_projectile_emitted)",
        "stock emitted no matching projectile",
    )
    missing_emission_tokens = [
        token for token in required_emission_tokens
        if token not in pure_primary_hook
    ]
    if missing_emission_tokens:
        raise StaticReTestFailure(
            "local pure-primary capture lacks native emission proof: "
            + ", ".join(missing_emission_tokens))
    original_call = pure_primary_hook.find("original(self);")
    emission_check = pure_primary_hook.find(
        "TryFindNewPurePrimaryProjectileActorInScene(")
    packet_queue = pure_primary_hook.find(
        "QueueLocalPlayerPrimaryCastForMultiplayer(actor_address);")
    if not (0 <= original_call < emission_check < packet_queue):
        raise StaticReTestFailure(
            "local primary packet capture must follow stock projectile emission")
    local_player_log_guard = (
        "local_actor_address == actor_address &&\n"
        "            g_pure_primary_control_log_budget > 0"
    )
    if (
        local_player_log_guard not in pure_primary_hook
        or pure_primary_hook.count(
            "--g_pure_primary_control_log_budget;") != 2
    ):
        raise StaticReTestFailure(
            "local-player pure-primary diagnostics can still log every stock tick")

    return "queued mouse holds preserve repeated presses without tick-rate primary amplification"


def test_remote_held_input_casts_defer_lifecycle_to_sender_input() -> str:
    processing_text = read_text(PENDING_CAST_PROCESSING)
    selection_rules_text = read_text(SKILL_SELECTION_RULES)
    player_tick_text = read_text(PLAYER_ACTOR_TICK_HOOK)
    local_transport_header = read_text(
        ROOT
        / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    service_header = read_text(
        ROOT
        / "SolomonDarkModLoader/include/multiplayer_service_loop.h"
    )
    service_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
    )
    cast_transport_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )

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
        "constexpr std::uint64_t kRemoteCastInputStallTimeoutMs = 3000;",
        "now_ms - remote_input_state.last_update_ms >=",
        "kRemoteCastInputStallTimeoutMs;",
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

    drive_rule = re.search(
        r"bool OngoingCastShouldDriveSyntheticCastInput\("
        r"(?P<body>.*?)"
        r"\n\}",
        selection_rules_text,
        re.DOTALL,
    )
    if drive_rule is None:
        raise StaticReTestFailure("synthetic cast-input drive rule was not found")
    drive_body = drive_rule.group("body")
    required_release_edge_tokens = (
        "ongoing.remote_input_controlled",
        "ongoing.saw_activity",
        "ongoing.remote_input_release_requested",
        "ongoing.remote_input_timed_out",
        "OngoingCastRequiresHeldCastInputDuringNativeTick(ongoing)",
        "return false;",
    )
    missing_release_edge_tokens = [
        token for token in required_release_edge_tokens
        if token not in drive_body
    ]
    if missing_release_edge_tokens:
        raise StaticReTestFailure(
            "remote held-primary release cannot reach the stock transition edge: " +
            ", ".join(missing_release_edge_tokens))

    startup_pos = drive_body.find("ongoing.startup_in_progress")
    remote_release_pos = drive_body.find("ongoing.remote_input_controlled")
    held_default_pos = drive_body.rfind(
        "OngoingCastRequiresHeldCastInputDuringNativeTick(ongoing)")
    bounded_pos = drive_body.find(
        "OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing)")
    if not (
        0 <= startup_pos < remote_release_pos < held_default_pos < bounded_pos
    ):
        raise StaticReTestFailure(
            "remote held-primary release must drop synthetic input after startup "
            "and before the generic held-input rule")

    direct_release_sample_pos = player_tick_text.find(
        "multiplayer::ReadBotCastInputState(")
    drive_input_pos = player_tick_text.find(
        "const bool drive_stock_cast_input")
    stock_tick_pos = player_tick_text.find(
        "original(self);",
        drive_input_pos,
    )
    if not (
        0 <= direct_release_sample_pos < drive_input_pos < stock_tick_pos
    ):
        raise StaticReTestFailure(
            "remote held-primary release is not sampled and presented before "
            "the stock actor tick")
    required_direct_sample_tokens = (
        "remote_held_release_observed_before_stock_tick",
        "remote_input_state.cast_sequence ==",
        "binding->ongoing_cast.remote_input_cast_sequence",
        "RefreshRemoteCastInputReleaseState(",
        "&binding->ongoing_cast",
    )
    missing_direct_sample_tokens = [
        token for token in required_direct_sample_tokens
        if token not in player_tick_text[
            direct_release_sample_pos:drive_input_pos
        ]
    ]
    if missing_direct_sample_tokens:
        raise StaticReTestFailure(
            "remote held-primary release still waits for the post-stock "
            "pending-cast pass: " +
            ", ".join(missing_direct_sample_tokens))

    remote_release_edge_pos = player_tick_text.find(
        "const bool apply_remote_held_release_edge")
    combined_release_edge_pos = player_tick_text.find(
        "if (apply_bounded_release_edge || apply_remote_held_release_edge)")
    remote_native_guard = re.search(
        r"if \(apply_remote_held_release_edge\) \{(?P<body>.*?)\n        \}",
        player_tick_text[
            remote_release_edge_pos:combined_release_edge_pos
        ],
        re.DOTALL,
    )
    if remote_native_guard is None:
        raise StaticReTestFailure(
            "remote held-primary release does not clear its native transition guard")
    missing_native_guard_tokens = [
        token for token in (
            "ClearLiveWizardActorAnimationDriveState(actor_address);",
            "kActorNoInterruptFlagOffset",
            "std::uint8_t",
            "0",
        )
        if token not in remote_native_guard.group("body")
    ]
    if missing_native_guard_tokens:
        raise StaticReTestFailure(
            "remote held-primary release is missing native transition guard clear token(s): " +
            ", ".join(missing_native_guard_tokens))
    clear_target_pos = player_tick_text.find(
        "ClearSelectionBrainTarget(",
        combined_release_edge_pos,
    )
    clear_state_pos = player_tick_text.find(
        "kActorControlBrainStateIdOffset",
        combined_release_edge_pos,
    )
    release_stock_tick_pos = player_tick_text.find(
        "original(self);",
        combined_release_edge_pos,
    )
    release_edge_body = player_tick_text[
        remote_release_edge_pos:combined_release_edge_pos
    ]
    required_release_edge_body_tokens = (
        "ongoing_cast.remote_input_controlled",
        "ongoing_cast.saw_activity",
        "ongoing_cast.remote_input_release_requested",
        "ongoing_cast.remote_input_timed_out",
        "OngoingCastRequiresHeldCastInputDuringNativeTick(",
    )
    missing_release_edge_body_tokens = [
        token for token in required_release_edge_body_tokens
        if token not in release_edge_body
    ]
    if (
        missing_release_edge_body_tokens
        or not (
            0 <= remote_release_edge_pos
            < combined_release_edge_pos
            < clear_target_pos
            < clear_state_pos
            < release_stock_tick_pos
        )
    ):
        raise StaticReTestFailure(
            "remote held-primary release must idle the authored control brain "
            "before the stock transition tick: " +
            ", ".join(missing_release_edge_body_tokens))

    required_release_flush_pairs = (
        (
            local_transport_header,
            "void FlushActiveLocalCastRelease(std::uint64_t now_ms);",
        ),
        (
            service_header,
            "void FlushGameplayCastReleaseOnAppThread(std::uint64_t now_ms);",
        ),
        (
            cast_transport_text,
            "void FlushActiveLocalCastRelease(std::uint64_t now_ms)",
        ),
        (cast_transport_text, "!active.active"),
        (cast_transport_text, "IsGameplayMouseLeftDown()"),
        (cast_transport_text, "now_ms < active.minimum_hold_until_ms"),
        (cast_transport_text, "SendActiveLocalCastInput(now_ms);"),
        (
            service_text,
            "void FlushGameplayCastReleaseOnAppThread(std::uint64_t now_ms)",
        ),
        (service_text, "g_session_transport_lifecycle_mutex"),
        (service_text, "FlushActiveLocalCastRelease(now_ms);"),
        (
            player_tick_text,
            "multiplayer::FlushGameplayCastReleaseOnAppThread(",
        ),
    )
    missing_release_flush_tokens = [
        token
        for text, token in required_release_flush_pairs
        if token not in text
    ]
    if missing_release_flush_tokens:
        raise StaticReTestFailure(
            "local held-primary release can still wait for the next AppMain "
            "transport pass: " +
            ", ".join(missing_release_flush_tokens))

    return (
        "remote held input casts defer cleanup to sender input and present "
        "release through an immediate local flush, a direct remote input "
        "sample, cleared native guards, and an idle control brain to the "
        "stock transition edge"
    )


def test_local_primary_network_capture_is_single_owner_and_preserves_lua_events() -> str:
    spell_hook_text = read_text(RUN_LIFECYCLE_SPELL_CAST_HOOKS)
    mod_loader_header_text = read_mod_loader_header_source()
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
    if "multiplayer::QueueLocalSpellCastEvent(" in spell_hook_text:
        raise StaticReTestFailure(
            "run-lifecycle spell hooks must delegate multiplayer Air capture "
            "instead of building transport events")

    native_dispatcher_tokens = (
        "QueueLocalPlayerNativeDispatcherPrimaryCast(self_address, spell_id)",
        "bool QueueLocalPlayerNativeDispatcherPrimaryCast(",
        "LocalPrimaryCastCaptureKind::NativeDispatcherPrimary",
        "dispatched_skill_id != kAirPrimaryEntryIndex",
        "TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)",
        "TryConsumeManualSpawnerPrimaryCastAllowance()",
        "multiplayer::QueueLocalSpellCastEvent(",
    )
    native_dispatcher_text = (
        spell_hook_text + mod_loader_header_text + player_control_text + input_queue_text
    )
    missing_native_dispatcher = [
        token for token in native_dispatcher_tokens if token not in native_dispatcher_text
    ]
    if missing_native_dispatcher:
        raise StaticReTestFailure(
            "native Air dispatch does not own the exact multiplayer input edge: "
            + ", ".join(missing_native_dispatcher)
        )
    if (
        "compare_exchange_weak" not in input_queue_text
        or "claimed_primary_cast_edge_serial" not in input_queue_text
    ):
        raise StaticReTestFailure(
            "native primary capture does not atomically claim one network cast per input edge"
        )

    air_hook_pos = spell_hook_text.find("void __fastcall HookSpellCast_018")
    air_original_pos = spell_hook_text.find("original(self, unused_edx);", air_hook_pos)
    air_capture_pos = spell_hook_text.find(
        "QueueLocalPlayerNativeDispatcherPrimaryCast(self_address, spell_id)",
        air_hook_pos,
    )
    if air_hook_pos < 0 or air_original_pos < air_hook_pos or air_capture_pos <= air_original_pos:
        raise StaticReTestFailure(
            "Air multiplayer capture must follow the successful native Lightning dispatch"
        )
    forbidden_heuristics = (
        "IsActiveTargetlessAirPrimaryCast(",
        "LocalPrimaryCastCaptureKind::TargetlessAir",
        "CaptureLocalPlayerPostStockPrimaryInput(actor_address);",
    )
    heuristic_text = player_control_text + stock_input_text + player_tick_text
    present_heuristics = [
        token for token in forbidden_heuristics if token in heuristic_text
    ]
    if present_heuristics:
        raise StaticReTestFailure(
            "Air multiplayer capture still depends on post-stock targetless heuristics: "
            + ", ".join(present_heuristics)
        )

    return (
        "Lua spell notification and multiplayer primary capture have distinct "
        "dedupe ownership, with Air captured from its native dispatcher"
    )


def test_water_continuous_primary_is_captured_from_its_native_dispatcher() -> str:
    spell_hook_text = read_text(RUN_LIFECYCLE_SPELL_CAST_HOOKS)
    mod_loader_header_text = read_mod_loader_header_source()
    player_control_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    input_queue_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl"
    )

    required_tokens = (
        (spell_hook_text, "HookSpellCast_020"),
        (
            spell_hook_text,
            "QueueLocalPlayerNativeDispatcherPrimaryCast(self_address, spell_id)",
        ),
        (mod_loader_header_text, "bool QueueLocalPlayerNativeDispatcherPrimaryCast("),
        (player_control_text, "NativeDispatcherPrimary"),
        (player_control_text, "constexpr std::int32_t kWaterPrimaryEntryIndex = 0x20;"),
        (player_control_text, "dispatched_skill_id != kWaterPrimaryEntryIndex"),
        (player_control_text, "TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)"),
        (input_queue_text, "LocalPrimaryCastCaptureKind::NativeDispatcherPrimary"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Water continuous primary does not own a multiplayer cast from its "
            "native dispatcher: " + ", ".join(missing)
        )

    if "SDMOD_DEFINE_SPELL_CAST_HOOK(020, kHookSpellCast020)" in spell_hook_text:
        raise StaticReTestFailure(
            "Water still uses the generic Lua-only spell hook and cannot queue a "
            "multiplayer cast"
        )

    water_hook_pos = spell_hook_text.find("void __fastcall HookSpellCast_020")
    water_original_pos = spell_hook_text.find(
        "original(self, unused_edx);", water_hook_pos
    )
    water_capture_pos = spell_hook_text.find(
        "QueueLocalPlayerNativeDispatcherPrimaryCast(self_address, spell_id)",
        water_hook_pos,
    )
    water_dispatch_pos = spell_hook_text.find(
        "DispatchSpellCastForSelf(self_address, spell_id);", water_hook_pos
    )
    if not (
        water_hook_pos >= 0
        and water_original_pos > water_hook_pos
        and water_capture_pos > water_original_pos
        and water_dispatch_pos > water_capture_pos
    ):
        raise StaticReTestFailure(
            "Water multiplayer capture must run once after stock dispatch and before "
            "the Lua notification"
        )

    return "Water continuous primary is captured once from native dispatcher entry 0x20"


def test_earth_primary_is_captured_from_its_native_dispatcher() -> str:
    spell_hook_text = read_text(RUN_LIFECYCLE_SPELL_CAST_HOOKS)
    mod_loader_header_text = read_mod_loader_header_source()
    player_control_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )
    input_queue_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_input_queueing.inl"
    )

    required_tokens = (
        (spell_hook_text, "HookSpellCast_028"),
        (
            spell_hook_text,
            "QueueLocalPlayerNativeDispatcherPrimaryCast(self_address, spell_id)",
        ),
        (mod_loader_header_text, "bool QueueLocalPlayerNativeDispatcherPrimaryCast("),
        (player_control_text, "NativeDispatcherPrimary"),
        (player_control_text, "constexpr std::int32_t kEarthPrimaryEntryIndex = 0x28;"),
        (player_control_text, "dispatched_skill_id != kEarthPrimaryEntryIndex"),
        (player_control_text, "TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)"),
        (input_queue_text, "LocalPrimaryCastCaptureKind::NativeDispatcherPrimary"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Earth primary does not own a multiplayer cast from its native "
            "dispatcher: " + ", ".join(missing)
        )

    if "SDMOD_DEFINE_SPELL_CAST_HOOK(028, kHookSpellCast028)" in spell_hook_text:
        raise StaticReTestFailure(
            "Earth still uses the generic Lua-only spell hook and cannot queue a "
            "multiplayer cast"
        )

    earth_hook_pos = spell_hook_text.find("void __fastcall HookSpellCast_028")
    earth_original_pos = spell_hook_text.find(
        "original(self, unused_edx);", earth_hook_pos
    )
    earth_capture_pos = spell_hook_text.find(
        "QueueLocalPlayerNativeDispatcherPrimaryCast(self_address, spell_id)",
        earth_hook_pos,
    )
    earth_dispatch_pos = spell_hook_text.find(
        "DispatchSpellCastForSelf(self_address, spell_id);", earth_hook_pos
    )
    if not (
        earth_hook_pos >= 0
        and earth_original_pos > earth_hook_pos
        and earth_capture_pos > earth_original_pos
        and earth_dispatch_pos > earth_capture_pos
    ):
        raise StaticReTestFailure(
            "Earth multiplayer capture must run once after stock dispatch and before "
            "the Lua notification"
        )

    return "Earth primary is captured once from native dispatcher entry 0x28"


def test_water_live_verifier_requires_native_visual_emission() -> str:
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_animation_mana_elements.py"
    )
    binary_layout_text = read_text(BINARY_LAYOUT)
    required_tokens = (
        (binary_layout_text, "water_frost_jet_visual_ctor=0x00453550"),
        (verifier_text, 'read_runtime_layout_offset("water_frost_jet_visual_ctor")'),
        (verifier_text, "sd.debug.trace_function({FROST_JET_VISUAL_CTOR}"),
        (verifier_text, "pcall(sd.debug.untrace_function, {FROST_JET_VISUAL_CTOR})"),
        (verifier_text, "WATER_CONTINUOUS_VISUAL_MATCH_SAMPLE_COUNT"),
        (verifier_text, "source_visual_calls"),
        (verifier_text, "observer_visual_calls"),
        (verifier_text, "owner emitted no native Frost Jet visuals"),
        (verifier_text, "observer emitted no native Frost Jet visuals"),
        (verifier_text, "def cast_aim_heading("),
        (verifier_text, "owner_heading = cast_aim_heading(owner)"),
        (verifier_text, "cast_facing_sample(proxy, owner_heading)"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Water live regression does not prove owner and observer native visual "
            "emission with live facing: " + ", ".join(missing)
        )

    return "Water live verifier requires native Frost Jet visuals on owner and observer"


def test_earth_live_verifier_requires_native_boulder_visual_emission() -> str:
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_animation_mana_elements.py"
    )
    binary_layout_text = read_text(BINARY_LAYOUT)
    required_tokens = (
        (binary_layout_text, "earth_boulder_ctor=0x005FA270"),
        (verifier_text, 'read_runtime_layout_offset("earth_boulder_ctor")'),
        (verifier_text, 'ElementSpec("earth", "earth_boulder", "projectile", 0x7D5'),
        (verifier_text, "sd.debug.trace_function({EARTH_BOULDER_CTOR}"),
        (verifier_text, "pcall(sd.debug.untrace_function, {EARTH_BOULDER_CTOR})"),
        (verifier_text, "source_visual_calls"),
        (verifier_text, "observer_visual_calls"),
        (verifier_text, "owner emitted no native Earth Boulder visual"),
        (verifier_text, "observer emitted no native Earth Boulder visual"),
        (verifier_text, "wait_for_remote_projectile_spawn_sequences("),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Earth live regression does not prove owner and observer native Boulder "
            "visual emission: " + ", ".join(missing)
        )

    return "Earth live verifier requires native Boulder visuals on owner and observer"


def test_multiplayer_nameplates_render_from_native_scene_passes() -> str:
    hud_text = read_text(GAMEPLAY_HUD_HOOKS)
    public_state_text = read_text(GAMEPLAY_PUBLIC_STATE_GETTERS)
    animation_text = read_text(ACTOR_ANIMATION_ADVANCE_HOOK)
    world_renderer_text = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_world_renderer.cpp"
    )
    world_renderer_text += read_text(
        ROOT
        / "SolomonDarkModLoader/src/lua_world_renderer/"
        "native_indicator_lane.inl"
    )
    world_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/native_world_render.h"
    )
    overlay_text = "\n".join(
        (
            read_text(ROOT / "SolomonDarkModLoader/src/debug_ui_overlay.cpp"),
            read_text(DEBUG_UI_OVERLAY_FRAME_RENDER),
            read_text(DEBUG_UI_OVERLAY_PUBLIC_SURFACE),
            read_text(DEBUG_UI_OVERLAY_HEADER),
            read_text(
                ROOT
                / "SolomonDarkModLoader/src/debug_ui_overlay/"
                "exact_text_capture/glyph_observation.inl"
            ),
            read_text(
                ROOT
                / "SolomonDarkModLoader/src/debug_ui_overlay/"
                "exact_text_capture/render_hooks.inl"
            ),
        )
    )
    layout_text = read_text(BINARY_LAYOUT)
    native_types_text = read_text(GAMEPLAY_NATIVE_FUNCTION_TYPES)
    keyboard_text = read_text(GAMEPLAY_KEYBOARD_INJECTION)
    player_tick_text = read_text(PLAYER_ACTOR_TICK_HOOK)
    verifier_text = read_text(MULTIPLAYER_HUD_NAMES_VERIFIER)
    materializer_text = read_text(HUD_LABEL_ASSET_MATERIALIZER)
    mod_loader_text = read_mod_loader_header_source()
    acceptance_text = read_text(ROOT / "tools/verify_world_render_z_order.py")

    required_native_indicator_tokens = (
        "void RenderGameplayWorldIndicatorsInNativePassImpl()",
        "DrawGameplayWorldIndicatorParticipant(",
        "TryProjectNativeWorldIndicatorPoint(",
        "DrawGameplayHudExactTextAt(",
        "DrawNativeWorldIndicatorHealthBar(",
        "TryGetGameplayHudParticipantDisplayNameForActor(",
        "source=native_world_indicator",
        "health_bar=native",
    )
    missing_indicator = [
        token for token in required_native_indicator_tokens if token not in hud_text
    ]
    if missing_indicator:
        raise StaticReTestFailure(
            "native post-scene participant indicator contract is incomplete: "
            + ", ".join(missing_indicator)
        )

    required_world_hook_tokens = (
        "void __fastcall HookNativeArenaRender(",
        "original(self);",
        "RenderGameplayWorldIndicatorsInNativePass();",
        "RenderLuaWorldMarkersInNativePass();",
        "DrawNativeWorldIndicatorHealthBar(",
        "native_renderer_set_color",
        "native_untextured_quad",
    )
    missing_world_hook = [
        token
        for token in required_world_hook_tokens
        if token not in world_renderer_text + world_header_text
    ]
    if missing_world_hook:
        raise StaticReTestFailure(
            "native post-scene renderer hook is incomplete: "
            + ", ".join(missing_world_hook)
        )

    forbidden_animation_tokens = (
        "DrawGameplayHudParticipantName(",
        "BeginDebugUiGameplayParticipantNameplateCapture(",
        "health_bar=dx9",
        "source=playerwizard_render",
    )
    present_animation = [
        token for token in forbidden_animation_tokens if token in animation_text
    ]
    if present_animation:
        raise StaticReTestFailure(
            "PlayerWizard animation pass still emits world-attached overlays: "
            + ", ".join(present_animation)
        )

    forbidden_overlay_tokens = (
        "RenderGameplayParticipantNameplates(",
        "TryListGameplayParticipantNameplates(&items)",
        "BuildGameplayParticipantHealthBarRenderItems(",
        "DrawGameplayParticipantHealthBar(",
        "source=dx9_nameplate_healthbar",
        "BeginDebugUiGameplayParticipantNameplateCapture(",
        "EndDebugUiGameplayParticipantNameplateCapture(",
        'surface_id = "gameplay_nameplate"',
        "gameplay_nameplate_overlay_items",
        "TryProjectGameplayNameplateWithD3dTransform(",
    )
    combined_runtime = "\n".join(
        (overlay_text, animation_text, hud_text, mod_loader_text)
    )
    present_overlay = [
        token for token in forbidden_overlay_tokens if token in combined_runtime
    ]
    if present_overlay:
        raise StaticReTestFailure(
            "world-attached participant UI leaked back into EndScene: "
            + ", ".join(present_overlay)
        )

    required_ally_hud_tokens = (
        "void __fastcall HookGameplayUiAllyLabelGlyphDraw(",
        "BuildGameplayAllyHudRows()",
        "BuildGameplayAllyHudExactText(",
        "DrawGameplayHudAllyBarParticipantName(",
        "source=ally_healthbar",
        '" layout_ok="',
    )
    missing_ally_hud = [
        token for token in required_ally_hud_tokens if token not in hud_text
    ]
    if missing_ally_hud:
        raise StaticReTestFailure(
            "screen-space top-left ally rows changed during world cutover: "
            + ", ".join(missing_ally_hud)
        )

    ally_rows = hud_text[
        hud_text.index("std::vector<GameplayAllyHudRow> BuildGameplayAllyHudRows()") :
        hud_text.index("\nbool IsGameplayAllyHudLabelGlyphCall(")
    ]
    if "TryGetRemoteParticipantDisplayState(" not in ally_rows:
        raise StaticReTestFailure(
            "ally HUD rows no longer resolve display state from transport"
        )

    required_authoritative_vitals_tokens = (
        "bool TryGetGameplayHudParticipantDisplayNameForActor(",
        "multiplayer::TryGetRemoteParticipantDisplayState(",
        "resolved_runtime.life_current / resolved_runtime.life_max",
        "health_ratio",
    )
    missing_vitals = [
        token
        for token in required_authoritative_vitals_tokens
        if token not in public_state_text
    ]
    if missing_vitals:
        raise StaticReTestFailure(
            "participant indicators no longer use authoritative replicated vitals: "
            + ", ".join(missing_vitals)
        )
    if "TryReadActorProgressionHealth(" in hud_text:
        raise StaticReTestFailure(
            "participant indicators read tick-delayed actor health"
        )

    required_layout_tokens = (
        "gameplay_ui_glyph_draw=0x004143D0",
        "gameplay_ui_centered_glyph_draw=0x004142E0",
        "gameplay_hud_render_dispatch=0x00512060",
        "gameplay_exact_text_object_render=0x0043BCD0",
        "gameplay_exact_text_object=0x008199A0",
        "gameplay_exact_text_object=0xE7D98",
        "arena_render=0x0046EC80",
        "native_renderer_set_color=0x0041FE50",
        "native_untextured_quad=0x0041DD70",
    )
    missing_layout = [
        token for token in required_layout_tokens if token not in layout_text
    ]
    if missing_layout:
        raise StaticReTestFailure(
            "native indicator layout keys are missing: "
            + ", ".join(missing_layout)
        )

    for token in (
        "using GameplayUiGlyphDrawFn = void(__thiscall*)(void* self, float x, float y)",
        "using GameplayHudRenderDispatchFn = void(__thiscall*)(void* self, int render_case, uintptr_t arg1, uintptr_t arg2)",
        "struct NativeGameString",
    ):
        if token not in native_types_text:
            raise StaticReTestFailure(
                "native ExactText call types are incomplete: " + token
            )

    for token in (
        "gameplay_hud_render_dispatch_hook",
        "gameplay_ui_glyph_draw_hook",
        "gameplay_ui_ally_label_glyph_draw_hook",
    ):
        if token not in keyboard_text:
            raise StaticReTestFailure(
                "native HUD hook lifecycle is incomplete: " + token
            )

    for token in (
        "TickParticipantSceneBindingsIfActive",
        "ApplyNativeRemoteParticipantPlayback",
    ):
        if token not in player_tick_text:
            raise StaticReTestFailure(
                "player tick no longer owns remote participant playback: " + token
            )

    for token in (
        "launch_pair(",
        "wait_for_all_relationships",
        "source=ally_healthbar",
        "layout_ok=1",
    ):
        if token not in verifier_text:
            raise StaticReTestFailure(
                "existing participant HUD verifier lost screen-HUD coverage: " + token
            )

    for token in ("UI.bundle", "UI.png", "AllyLabelEnvironmentVariable"):
        if token not in materializer_text:
            raise StaticReTestFailure(
                "HUD label asset materializer is incomplete: " + token
            )

    for token in (
        'INSTANCE_NAME = "zrd"',
        "PORTS = (51755, 51756)",
        "native_world_indicator",
        "health_bar=native",
        "side_by_side",
        "both_peers",
    ):
        if token not in acceptance_text:
            raise StaticReTestFailure(
                "world-render acceptance verifier is incomplete: " + token
            )

    return (
        "remote names and health bars use the native post-scene indicator pass "
        "while top-left ally rows remain screen-space HUD"
    )


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


def test_write_watch_rearm_is_owned_by_faulting_thread() -> str:
    internal = read_text(ROOT / "SolomonDarkModLoader/src/runtime_debug_internal.h")
    handler = RUNTIME_DEBUG_WATCH_HELPERS.read_text(encoding="utf-8")

    required_tokens = (
        (internal, "DWORD pending_rearm_thread_id = 0;"),
        (handler, "page_it->second.pending_rearm_thread_id = thread_id;"),
        (handler, "state.pending_rearm_thread_id != thread_id"),
        (handler, "state.pending_rearm_thread_id = 0;"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "PAGE_GUARD rearm must remain owned by the thread whose guarded access "
            "set the trap flag: " + ", ".join(missing)
        )
    if "bool pending_rearm" in internal:
        raise StaticReTestFailure(
            "global per-page pending_rearm lets one thread consume another thread's "
            "single-step rearm"
        )

    return "PAGE_GUARD single-step rearm is owned by the faulting thread"


def test_primary_cast_lane_requires_native_collision_segment() -> str:
    """A cast lane is clear only when stock movement geometry also permits it."""

    gameplay_api = read_text(
        ROOT / "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    gameplay_public_api = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
    )
    lua_nav = read_text(
        ROOT
        / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_nav_grid_and_copy.inl"
    )
    lua_registration = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp"
    )
    cast_harness = read_text(
        ROOT / "tools/verify_multiplayer_primary_kill_stress.py"
    )

    required = (
        (gameplay_api, "TryTestGameplayNavSegment("),
        (gameplay_public_api, "bool TryTestGameplayNavSegment("),
        (gameplay_public_api, "IsGameplayPathSegmentTraversable("),
        (lua_nav, "int LuaDebugTestNavSegment(lua_State* state)"),
        (lua_nav, "TryTestGameplayNavSegment("),
        (lua_registration, '&LuaDebugTestNavSegment, "test_nav_segment"'),
        (cast_harness, "sd.debug.test_nav_segment("),
        (cast_harness, 'emit("native_query_ok", native_query.ok)'),
        (cast_harness, 'emit("native_traversable", native_query.traversable)'),
        (cast_harness, "native_clear and blocker_count == 0"),
    )
    missing = [token for text, token in required if token not in text]
    if missing:
        raise StaticReTestFailure(
            "primary-cast lane selection can ignore stock scenery collision: "
            + ", ".join(missing)
        )
    if 'emit("ok", blocker_count == 0)' in cast_harness:
        raise StaticReTestFailure(
            "actor-only clearance still decides whether a primary-cast lane is usable"
        )

    return "primary-cast lanes require the stock native collision-segment query"


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


def test_local_player_control_brain_retires_only_its_invalid_ally_hud_registration() -> str:
    config = read_text(ROOT / "config/binary-layout.ini")
    player_control_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl"
    )

    assert "gameplay_ally_healthbar_count=0x1C20" in config
    hook_start = player_control_text.index(
        "void __fastcall HookPlayerControlBrainUpdate("
    )
    hook_end = player_control_text.index(
        "bool IsActorCurrentLocalPlayerSlotZero(", hook_start
    )
    hook = player_control_text[hook_start:hook_end]
    required_tokens = (
        "publication_actor_slot == 0",
        "kGameplayAllyHealthbarCountOffset",
        "ally_healthbar_count_before",
        "original(self, param2, param3);",
        "ally_healthbar_count_after == ally_healthbar_count_before + 1",
        "ally_healthbar_count_before))",
        "retired stock local-player ally HUD registration",
    )
    missing = [token for token in required_tokens if token not in hook]
    if missing:
        raise StaticReTestFailure(
            "local control-brain ally-HUD ownership repair is missing token(s): "
            + ", ".join(missing)
        )
    if hook.index("ally_healthbar_count_before") > hook.index(
        "original(self, param2, param3);"
    ):
        raise StaticReTestFailure(
            "the local ally-HUD count must be captured before the stock append"
        )
    if hook.index("ally_healthbar_count_after ==") < hook.index(
        "original(self, param2, param3);"
    ):
        raise StaticReTestFailure(
            "the stock append must be observed before its invalid local registration is retired"
        )

    return "slot zero keeps stock self-HUD ownership while remote control brains keep native ally rows"
