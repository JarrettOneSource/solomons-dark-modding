"""Spell behavior and convergence verifier contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_multiplayer_contract_support import (
    _read,
    _require_in_order,
    read_source_unit,
)


def test_secondary_replay_preserves_owner_authored_aim_when_target_resolves() -> str:
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_cast_packet_sync.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_cast_packet_sync.inl"
    )
    hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    replay = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "native_secondary_cast_replay.inl"
    )
    preparation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "pending_cast_preparation.inl"
    )
    origin_context = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "scoped_actor_cast_origin_context.inl"
    )

    assert "request.aim_target_x = packet.aim_target_x" in incoming
    assert "request.aim_target_y = packet.aim_target_y" in incoming
    assert "request.target_actor_address = resolved_target_actor_address" in incoming
    assert "request.aim_target_x = cast_target.x" not in incoming
    assert "request.aim_target_y = cast_target.y" not in incoming

    assert "TryRefreshLocalSecondaryCastAim" in hooks
    assert "TryCaptureLocalSecondaryCastOrigin" in hooks
    _require_in_order(
        hooks,
        "TryCaptureLocalSecondaryCastOrigin(actor_address, capture)",
        "native_result = original(self, skill_entry_index)",
        "TryRefreshLocalSecondaryCastAim(actor_address, &capture)",
        "QueueLocalSecondarySpellCastEvent(",
    )
    refresh_start = hooks.index("bool TryRefreshLocalSecondaryCastAim(")
    refresh_end = hooks.index("bool TryCaptureLocalSecondaryCast(", refresh_start)
    refresh_body = hooks[refresh_start:refresh_end]
    assert "kActorPositionXOffset" not in refresh_body
    assert "kActorPositionYOffset" not in refresh_body
    assert "capture->direction_x = aim_dx / aim_length" not in hooks
    assert "capture->direction_y = aim_dy / aim_length" not in hooks

    assert "cast_direction_length_squared" in outgoing
    assert "built.heading = cast_heading" in outgoing

    assert "request.has_aim_angle" in replay
    assert "request.has_origin_transform" in replay
    assert "NormalizeWizardActorHeadingForWrite(request.aim_angle)" in replay
    assert "TryComputeActorAimTowardTarget(" not in replay
    assert "InvokeWithActorCastOriginContext(" in replay
    _require_in_order(
        replay,
        "InvokeWithActorCastOriginContext(",
        "InvokeOriginalPlayerActorSecondarySpellCast(",
    )
    assert (
        "kActorCurrentTargetActorOffset,\n        request.target_actor_address" in replay
    )
    _require_in_order(
        preparation,
        "multiplayer::ConsumePendingBotCast(binding->bot_id, &request)",
        "return ReplayPendingNativeSecondaryCast(",
        "if (request.has_origin_transform)",
    )
    for token in (
        "struct ScopedActorCastOriginContext",
        "kActorPositionXOffset",
        "kActorPositionYOffset",
        "original_x",
        "original_y",
        "authored_x",
        "authored_y",
        "cast_origin_context.Restore()",
    ):
        assert token in origin_context
    _require_in_order(
        origin_context,
        "ScopedActorCastOriginContext cast_origin_context(",
        "invoke()",
        "cast_origin_context.Restore()",
    )
    return (
        "secondary replay keeps the accepted cast's pre-dispatch origin and owner-authored "
        "heading for native placement, then restores the observer's interpolated actor position"
    )


def test_cursor_placed_secondaries_replay_owner_world_position() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    bot_runtime = _read("SolomonDarkModLoader/include/bot_runtime.h")
    hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    hook_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    hook_installer = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    native_types = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "native_function_types.inl"
    )
    pending_cast_storage = _read("SolomonDarkModLoader/src/bot_runtime.cpp")
    casting_api = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/casting_api.inl"
    )
    cast_validation = _read(
        "SolomonDarkModLoader/src/bot_runtime/helpers/request_validation.inl"
    )
    cursor_context = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "scoped_secondary_cursor_world_placement_context.inl"
    )
    replay = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "native_secondary_cast_replay.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_cast_packet_sync.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_cast_packet_sync.inl"
    )
    layout = _read("config/binary-layout.ini")

    assert "constexpr std::uint16_t kProtocolVersion = 75;" in protocol
    assert "CastInputFlagCursorWorldPlacement" in protocol
    assert "float cursor_world_x;" in protocol
    assert "float cursor_world_y;" in protocol
    assert 'static_assert(sizeof(CastPacket) == 128' in protocol
    for token in (
        "has_cursor_world_placement",
        "cursor_world_x",
        "cursor_world_y",
    ):
        assert token in bot_runtime
        assert token in outgoing
        assert token in incoming
        assert token in pending_cast_storage
        assert f"pending_cast->{token} = request.{token};" in casting_api
        assert f"request->{token} = pending_cast->{token};" in casting_api
    assert "request.has_cursor_world_placement" in cast_validation

    for row in (0x0B, 0x1B, 0x2D, 0x31, 0x32, 0x48, 0x49, 0x4A, 0x4C):
        assert f"case 0x{row:02X}:" in cursor_context, (
            f"cursor-placement capture omits secondary row 0x{row:02X}"
        )
    assert "SecondaryCursorWorldProjectionFn" in native_types
    assert "secondary_cursor_world_projection_hook" in hook_state
    assert "HookSecondaryCursorWorldProjection" in hooks
    assert "ScopedLocalSecondaryCursorProjectionCapture" in hooks
    _require_in_order(
        hooks,
        "ScopedLocalSecondaryCursorProjectionCapture cursor_projection_capture(",
        "native_result = original(self, skill_entry_index)",
        "QueueLocalSecondarySpellCastEvent(",
    )
    assert "TryReadCurrentSecondaryCursorWorldPlacement(" not in cursor_context
    _require_in_order(
        hook_installer,
        "secondary_cursor_world_projection =",
        "HookSecondaryCursorWorldProjection",
        "secondary_cursor_world_projection_hook",
    )

    for token in (
        "secondary_cursor_world_projection=0x00462110",
        "cursor_secondary_at_mouse=0x00B3BCF4",
        "cursor_screen_position=0x0082025C",
        "gameplay_cursor_placement_active=0x7D",
        "actor_world_view_scale=0x80",
        "actor_world_view_origin_x=0x8BCC",
        "actor_world_view_origin_y=0x8BD0",
    ):
        assert token in layout, f"cursor world-placement seam lacks {token}"

    for token in (
        "struct ScopedSecondaryCursorWorldPlacementContext",
        "kCursorSecondaryAtMouseGlobal",
        "kCursorScreenPositionGlobal",
        "kGameplayCursorPlacementActiveOffset",
        "kActorWorldViewScaleOffset",
        "kActorWorldViewOriginXOffset",
        "kActorWorldViewOriginYOffset",
        "original_cursor_screen_x",
        "original_cursor_screen_y",
        "original_cursor_secondary_at_mouse",
        "original_cursor_placement_active",
        "cursor_secondary_at_mouse_address",
        "cursor_screen_position_address",
        "ResolveGameAddressOrZero(kCursorSecondaryAtMouseGlobal)",
        "ResolveGameAddressOrZero(kCursorScreenPositionGlobal)",
        "ResolveGameAddressOrZero(kGameObjectGlobal)",
        "cursor_context.Restore()",
    ):
        assert token in cursor_context, (
            f"scoped cursor-placement replay lacks {token}"
        )
    assert "screen_x" not in protocol
    assert "screen_y" not in protocol
    _require_in_order(
        replay,
        "InvokeWithActorCastOriginContext(",
        "InvokeWithSecondaryCursorWorldPlacementContext(",
        "InvokeOriginalPlayerActorSecondarySpellCast(",
    )
    return (
        "cursor-placed secondaries carry the owner's accepted world position and "
        "scope it through stock replay independently of either peer's resolution"
    )


def test_webbed_status_replicates_stock_state_to_remote_presentation() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    constants = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "gameplay_constants.inl"
    )
    status_reader = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_actor_calls/"
        "lifecycle_and_stat_calls.inl"
    )
    status_reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "transient_status_participant_reconciliation.inl"
    )
    packet_writer = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    packet_reader = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )
    vitals_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_authority.inl"
    )
    native_remote_vitals = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_vitals_and_playback.inl"
    )
    status_actions = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_participant_vitals_actions.inl"
    )
    live_verifier = _read("tools/verify_multiplayer_webbed_status_sync.py")
    steam_verifier = _read(
        "tools/verify_steam_friend_active_pair_webbed.py"
    )
    steam_context = _read("tools/steam_friend_behavior_context.py")

    assert "ParticipantTransientStatusFlagWebbed = 1 << 4" in protocol
    assert "ParticipantTransientStatusFlagWebbed;" in protocol
    assert "kParticipantWebbedMaxStrength = 3.0f" in protocol
    assert "kNativeWebbedModifierTypeId = 0x1B79" in constants
    _require_in_order(
        status_reader,
        "type_id == kNativeWebbedModifierTypeId",
        "ParticipantTransientStatusFlagWebbed",
    )
    assert (
        "packet->transient_status_flags = "
        "local.runtime.transient_status_flags" in packet_writer
    )
    assert "kParticipantTransientStatusValueMask" in packet_reader
    _require_in_order(
        status_reconciliation,
        "constexpr std::uint32_t kWebbedRenderDriveFlag = 0x20u",
        "ParticipantTransientStatusFlagWebbed",
        "kActorRenderDriveFlagsOffset",
    )
    _require_in_order(
        status_reconciliation,
        "ReconcileReplicatedWebbedPresentation(",
        "if (binding->ongoing_cast.active)",
    )
    for token in (
        "webbed_remaining_ticks",
        "webbed_strength",
    ):
        assert token in protocol, f"webbed correction packet lacks {token}"
        assert token in vitals_authority, f"webbed correction authority lacks {token}"
    for token in (
        "native_webbed_observed",
        "native_webbed_remaining_ticks",
        "native_webbed_strength",
    ):
        assert token in native_remote_vitals, (
            f"host mirror cannot capture genuine Spider web state: {token}"
        )
    for token in (
        "InstallReplicatedWebbedModifier(",
        "QueueLocalPlayerVitalsCorrection(",
        "ConfirmLocalParticipantVitalsCorrection(",
    ):
        assert token in status_actions, (
            f"client owner cannot apply corrected native Webbed state: {token}"
        )
    for token in (
        "SPIDER_TYPE_ID = 0x809",
        "spawn_exact_spider",
        "ParticipantTransientStatusFlagWebbed",
        "actor_render_drive_flags",
        "host_owned",
        "client_owned",
        "wait_for_host_webbed_before_client_owner",
        'result["spider"] = spider',
        "enemy_actor_address=parse_int_text(",
    ):
        assert token in live_verifier, (
            f"genuine two-owner Spider regression lacks {token}"
        )
    for token in (
        "context = configure_behavior_context(pair)",
        "require_shared_test_run(output[\"pair\"])",
        "context.webbed_directions",
        "reset_quiet_arena()",
        "webbed.run_direction(",
        "find_new_crash_artifacts(started_at)",
        "primary.cleanup_live_enemies()",
    ):
        assert token in steam_verifier, (
            f"real-Steam Spider/Webbed regression lacks {token}"
        )
    assert "launch_pair_ready" not in steam_verifier
    assert "stop_games" not in steam_verifier
    for token in (
        "multiplayer_natural_defense_harness as natural_defense_harness",
        "multiplayer_webbed_status_harness as webbed_harness",
        "verify_multiplayer_webbed_status_sync as webbed",
        "webbed_directions: tuple[webbed.Direction, webbed.Direction]",
        "webbed.DIRECTIONS = webbed_directions",
    ):
        assert token in steam_context, (
            f"Steam behavior context cannot route Webbed through the active pair: {token}"
        )
    return (
        "stock Mod_Webbed state transfers from host-simulated Spider hits into "
        "the client owner and drives matching remote presentation on real Steam"
    )


def test_webbed_fixture_pins_selected_spider_target_until_contact() -> str:
    natural_harness = _read("tools/multiplayer_natural_defense_harness.py")
    live_verifier = _read("tools/verify_multiplayer_webbed_status_sync.py")

    for token in (
        "LOCAL_OWNER_SPIDER_ATTACK_DISTANCE = 96.0",
        "REMOTE_OWNER_SPIDER_ATTACK_DISTANCE = 16.0",
        "attack_distance=LOCAL_OWNER_SPIDER_ATTACK_DISTANCE",
        "attack_distance=REMOTE_OWNER_SPIDER_ATTACK_DISTANCE",
        "direction.attack_distance",
    ):
        assert token in live_verifier, (
            "the Spider fixture must use a stock approach for the local owner "
            "and immediate contact for the remote owner: " + token
        )

    for token in (
        "arena.selected_actor_address = __ENEMY_ACTOR_ADDRESS__",
        "arena.target_actor = target_actor",
        "arena.attack_distance = __ATTACK_DISTANCE__",
        "if type(_G.__sdmod_defense_drive) == 'function' then",
        "_G.__sdmod_defense_drive(arena, true)",
        "local selected = arena.selected_actor_address == 0 or",
        "address == arena.selected_actor_address",
        "arena.mode == 'attack' and selected",
        "address + ot, arena.mode == 'attack' and selected and",
        "arena.target_actor or 0",
        "actor_current_target_bucket_delta",
        "actor_world_bucket_stride",
        "target_slot * bucket_stride + target_handle -",
        "hostile_slot * bucket_stride",
        "sd.debug.write_i32(address + ob, bucket_delta)",
        "drive(arena, false)",
    ):
        assert token in natural_harness, (
            "exact Spider fixture does not preserve its target through stock "
            f"AI retargeting: {token}"
        )
    _require_in_order(
        natural_harness,
        "arena.selected_actor_address = __ENEMY_ACTOR_ADDRESS__",
        "_G.__sdmod_defense_drive(arena, true)",
    )
    cadence_reset = """if rebind then
            if ort ~= nil then sd.debug.write_u32(brain + ort, 0) end
            if otc ~= nil then sd.debug.write_u32(brain + otc, 0) end
            if oac ~= nil then sd.debug.write_u32(brain + oac, 0) end
          end"""
    assert cadence_reset in natural_harness, (
        "continuous target pinning must not restart the Spider action cadence"
    )
    movement_release = """if not attacking or rebind then
        if ox ~= nil then sd.debug.write_float(address + ox, x) end
        if oy ~= nil then sd.debug.write_float(address + oy, y) end
      end"""
    assert movement_release in natural_harness, (
        "the selected Spider must be free to close from its initial attack "
        "position into the stock overlap radius"
    )
    for token in (
        "def query_enemy_target_state(",
        "current_target_actor",
        "target_bucket_delta",
        "brain_target_slot",
        "brain_target_handle",
        "target_distance",
        "target_contact_radius",
        "local_contact_radius",
    ):
        assert token in natural_harness, (
            f"failed exact Spider attacks lack native targeting evidence: {token}"
        )
    for token in (
        "query_enemy_target_state(",
        'result["attack_diagnostics"]',
    ):
        assert token in live_verifier, (
            f"Webbed verifier drops failed attack targeting evidence: {token}"
        )
    return (
        "the selected stock Spider remains pinned to the intended participant "
        "until contact while every nonselected enemy stays parked"
    )


def test_webbed_fixture_requires_canonical_safe_pair_placement() -> str:
    natural_harness = _read("tools/multiplayer_natural_defense_harness.py")
    webbed_harness = _read("tools/multiplayer_webbed_status_harness.py")

    for token in (
        "place_player(HOST_PIPE, *host_xy, 0.0)",
        "place_player(CLIENT_PIPE, *client_xy, 0.0)",
        '"owner_local_distance"',
        '"owner_remote_distance"',
        '"parked_peer_delta"',
        '"participant_separation"',
        "TARGET_LAYOUT_TOLERANCE",
        "MIN_TARGET_SEPARATION",
        "target layout did not hold",
    ):
        assert token in natural_harness, (
            "Webbed setup can accept converged but incorrect geometry: "
            f"{token}"
        )
    assert "PIN_PLAYER_LUA" not in natural_harness, (
        "Webbed setup must reuse canonical native placement instead of a "
        "second movement-reset implementation"
    )
    assert "parse_float," not in natural_harness
    assert '_float(view, "x")' in natural_harness
    assert '_float(view, "y")' in natural_harness
    assert "__sdmod_defense_pin" not in webbed_harness, (
        "stock Webbed escape must not depend on a removed fixture pin"
    )
    return (
        "the Webbed fixture retries canonical native placement until both views "
        "agree on the exact victim and a safely separated bystander"
    )


def test_remote_webbed_escape_consumes_owner_movement_intent() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    public_state = _read("SolomonDarkModLoader/include/mod_loader.h")
    control_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_control_hooks.inl"
    )
    state_getter = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_state_getters.inl"
    )
    packet_writer = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    packet_reader = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )
    entity_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "participant_entity_state.inl"
    )
    remote_playback = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_playback.inl"
    )
    webbed_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "webbed_authority_hook.inl"
    )
    tick_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    layout = _read("config/binary-layout.ini")
    seam_header = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = _read(
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    seam_bindings = _read(
        "SolomonDarkModLoader/src/gameplay_seams/"
        "state_and_address_bindings.inl"
    )
    hook_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    installation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    lua_player = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    live_harness = _read("tools/multiplayer_webbed_status_harness.py")
    live_verifier = _read("tools/verify_multiplayer_webbed_status_sync.py")

    assert "constexpr std::uint16_t kProtocolVersion = 75;" in protocol
    for source_name, source in (
        ("protocol", protocol),
        ("runtime state", runtime_state),
        ("public player state", public_state),
    ):
        for field in ("movement_intent_x", "movement_intent_y"):
            assert field in source, f"{source_name} lacks owner {field}"
    for token in (
        "publication_actor_slot == 0",
        "local_movement_intent_x.store(",
        "local_movement_intent_y.store(",
        "local_movement_intent_observed_ms.store(",
    ):
        assert token in control_hook, f"native owner input capture lacks: {token}"
    for token in (
        "local_movement_intent_x.load(",
        "local_movement_intent_y.load(",
        "local_movement_intent_observed_ms.load(",
    ):
        assert token in state_getter, f"player state movement intent lacks: {token}"
    for token in (
        "local->runtime.movement_intent_x = player_state.movement_intent_x",
        "local->runtime.movement_intent_y = player_state.movement_intent_y",
        "packet->movement_intent_x = local.runtime.movement_intent_x",
        "packet->movement_intent_y = local.runtime.movement_intent_y",
    ):
        assert token in packet_writer, f"movement intent transmit path lacks: {token}"
    for token in (
        "normalized.movement_intent_x",
        "normalized.movement_intent_y",
        "participant->runtime.movement_intent_x",
        "participant->runtime.movement_intent_y",
    ):
        assert token in packet_reader, f"movement intent receive path lacks: {token}"
    for token in (
        "replicated_movement_intent_x",
        "replicated_movement_intent_y",
    ):
        assert token in entity_state, f"host mirror state lacks: {token}"
        assert token in remote_playback, f"host mirror refresh lacks: {token}"
    for source_name, source in (
        ("Lua player state", lua_player),
        ("Lua participant runtime", lua_runtime),
        ("live Webbed harness", live_harness),
    ):
        for token in ("movement_intent_x", "movement_intent_y"):
            assert token in source, f"{source_name} lacks {token} evidence"
    for token in (
        "WEBBED_CLEAR_STABLE_SECONDS",
        "stable_since: float | None = None",
        "time.monotonic() - stable_since >= stable_seconds",
        "stable_since = None",
    ):
        assert token in live_harness, (
            f"Webbed cleanup can accept a transient clear sample: {token}"
        )
    for token in (
        'output["directions"][direction.name] = direction_result',
        'result["spider"] = spider',
        'result["attack"] = attack',
        'result["host_native_witness"] = host_native_witness',
    ):
        assert token in live_verifier, (
            f"Webbed verifier does not preserve pre-failure evidence: {token}"
        )

    for source, token in (
        (layout, "webbed_modifier_tick=0x00623BA0"),
        (seam_header, "kWebbedModifierTick"),
        (seam_storage, "kWebbedModifierTick = 0"),
        (seam_bindings, '"webbed_modifier_tick", kWebbedModifierTick'),
        (hook_state, "webbed_modifier_tick_hook"),
        (installation, "HookWebbedModifierTick"),
        (installation, "kWebbedModifierTickHookMinimumPatchSize"),
        (installation, "RemoveX86Hook(&g_gameplay_keyboard_injection.webbed_modifier_tick_hook)"),
    ):
        assert token in source, f"required Webbed authority seam lacks: {token}"
    for token in (
        "HookWebbedModifierTick",
        "kDamageContextTargetGlobal",
        "IsNativeRemoteParticipantBinding(binding)",
        "binding->replicated_movement_intent_x",
        "binding->replicated_movement_intent_y",
        "kActorAnimationConfigBlockOffset",
        "kActorAnimationDriveParameterOffset",
        "saved_movement_x",
        "saved_movement_y",
    ):
        assert token in webbed_hook, f"scoped stock Webbed escape lacks: {token}"
    _require_in_order(
        webbed_hook,
        "kActorAnimationConfigBlockOffset, movement_x",
        "original(self);",
        "kActorAnimationConfigBlockOffset, saved_movement_x",
    )
    assert "replicated_movement_intent" not in tick_hook, (
        "remote owner input must be scoped to Mod_Webbed, not the whole stock "
        "PlayerActor tick"
    )
    return (
        "remote Mod_Webbed consumes replicated owner movement only inside its "
        "native tick, then restores the mirror actor input"
    )


def test_network_clients_reject_stock_incoming_damage_authority() -> str:
    layout = _read("config/binary-layout.ini")
    seam_header = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = _read(
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    seam_bindings = _read(
        "SolomonDarkModLoader/src/gameplay_seams/"
        "state_and_address_bindings.inl"
    )
    native_types = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "native_function_types.inl"
    )
    hook_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_damage_authority_hook.inl"
    )
    poison_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "poison_authority_hook.inl"
    )
    installation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )

    for source, token in (
        (layout, "poisoned_modifier_tick=0x00627160"),
        (layout, "damage_context_reset=0x006246F0"),
        (seam_header, "extern uintptr_t kPoisonedModifierTick;"),
        (seam_header, "extern uintptr_t kDamageContextReset;"),
        (seam_storage, "uintptr_t kPoisonedModifierTick = 0;"),
        (seam_storage, "uintptr_t kDamageContextReset = 0;"),
        (
            seam_bindings,
            'SDMOD_ADDR("gameplay.hooks", "poisoned_modifier_tick", '
            "kPoisonedModifierTick)",
        ),
        (
            seam_bindings,
            'SDMOD_ADDR("gameplay.hooks", "damage_context_reset", '
            "kDamageContextReset)",
        ),
        (native_types, "using PoisonedModifierTickFn = void(__thiscall*)"),
        (native_types, "using DamageContextResetFn = void(__thiscall*)"),
        (hook_state, "X86Hook poisoned_modifier_tick_hook;"),
        (hook_state, "X86Hook player_actor_magic_damage_hook;"),
        (hook_state, "g_client_owner_poison_tick_target"),
        (hook_state, "uintptr_t damage_context_reset_address = 0;"),
        (hook_state, "uintptr_t damage_context_source_address = 0;"),
        (installation, "reinterpret_cast<void*>(&HookPoisonedModifierTick)"),
        (installation, "kPoisonedModifierTickHookMinimumPatchSize"),
        (
            installation,
            "RemoveX86Hook(&g_gameplay_keyboard_injection.poisoned_modifier_tick_hook)",
        ),
        (installation, "reinterpret_cast<void*>(&HookPlayerActorMagicDamage)"),
        (installation, "kPlayerActorMagicDamageHookMinimumPatchSize"),
    ):
        assert token in source, f"incoming-damage authority lacks: {token}"

    for token in (
        "HookPoisonedModifierTick",
        "kDamageContextTargetGlobal",
        "kNativePoisonSourceSlotOffset",
        "kNativePoisonDamagePerTickOffset",
        "local_player_tick_actor_address",
        "g_client_owner_poison_tick_target",
        "original(self)",
    ):
        assert token in poison_hook, (
            f"owner poison authority scope lacks: {token}"
        )
    _require_in_order(
        poison_hook,
        "g_client_owner_poison_tick_target = actor_address",
        "original(self);",
        "g_client_owner_poison_tick_target = previous_target",
    )
    _require_in_order(
        hook,
        "if (multiplayer::IsLocalTransportClient() &&",
        "g_client_owner_poison_tick_target != actor_address",
        "ResetActiveDamageContext();",
        "return 0;",
        "if (HasLuaDamageFilterHandlers())",
    )
    assert "if (!shield_authority.applicable)" in hook
    assert "return original(self);" in hook
    assert "IsBoundReplicatedRunEnemyActorForLocalClient" not in hook, (
        "client damage rejection must cover every stock incoming-damage "
        "source, including projectiles and hazards"
    )
    return (
        "network clients accept only a scoped local-owner poison tick while "
        "rejecting other stock incoming damage and queued modifiers"
    )


def test_secondary_behavior_matrix_uses_native_two_owner_witnesses() -> str:
    harness = _read("tools/multiplayer_secondary_behavior_harness.py")
    runner = _read("tools/verify_steam_friend_active_pair_secondary_behavior.py")
    active_pair = _read("tools/steam_friend_active_pair.py")
    focus = _read("tools/verify_multiplayer_focus_behavior_sync.py")
    ring = _read("tools/verify_multiplayer_ring_of_fire_multikill_stability.py")
    layout = _read("config/binary-layout.ini")
    seams = _read("SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl")
    mouse_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    input_queue = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_input_queueing.inl"
    )
    lua_input = _read("SolomonDarkModLoader/src/lua_engine_bindings_input.cpp")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    spell_effect_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "spell_effect_sync.inl"
    )
    spell_effect_reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "spell_effect_reconciliation.inl"
    )
    world_capture = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_capture.inl"
    )
    world_packet_builder = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_snapshot_packet_builders.inl"
    )
    world_packet_reader = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_snapshot_packet_sync.inl"
    )
    world_fragmentation = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_fragmentation.inl"
    )
    world_reconciliation = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )
    status_reader = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_actor_calls/lifecycle_and_stat_calls.inl"
    )
    status_reconcile = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_casting/transient_status_reconciliation.inl"
    )
    entity_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "core/participant_entity_state.inl"
    )
    vitals_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_authority.inl"
    )
    secondary_replay = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_casting/native_secondary_cast_replay.inl"
    )
    actor_slot_context = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "core/scoped_actor_slot_context.inl"
    )
    gameplay_api = _read("SolomonDarkModLoader/include/mod_loader_gameplay_api.inl")
    state_getters = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_state_getters.inl"
    )
    debug_observations = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_debug/"
        "functions_combat_observations.inl"
    )
    debug_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp")
    dampen_context = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "stock_dampen_effect_context.inl"
    )
    dampen_rendering = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "gameplay_dampen_rendering.inl"
    )
    dampen_effect = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/"
        "multiplayer_dampen_effect.inl"
    )
    player_cast_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    turn_undead_target_lock = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "turn_undead_caster_target_lock.inl"
    )
    monster_pathfinding = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "monster_pathfinding_hook.inl"
    )
    actor_lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )

    assert len(re.findall(r"^\s*SecondarySkillSpec\(\d+,", harness, re.MULTILINE)) == 23
    for token in (
        '"[bots] remote native secondary cast replayed."',
        'and "success=1" in line',
        '"Injected gameplay mouse-right click."',
        '"native_mouse_right_injection_count"',
        '"native_keyboard_edge_count"',
        "concurrent.futures.ThreadPoolExecutor(max_workers=2)",
        "SECONDARY_SKILL_BELT_SLOTS = (0, 1, 2, 5, 6, 7)",
        "if belt[slot] == -1",
        "ARM_EFFECT_MONITOR_LUA",
        "COLLECT_EFFECT_MONITOR_LUA",
        "primary.spawn_one_enemy(",
        "primary.find_target(",
        "target_x = float(owner_transform[0]) + TARGET_OFFSET_X",
        "target_y = float(owner_transform[1]) + TARGET_OFFSET_Y",
        "wait_for_target_convergence(",
        "maximum_hp_satisfied",
        "damage_baseline_hp",
        'float(target["baseline"]["host"]["hp"])',
        'float(target_after["client"]["hp"])',
        'skill.behavior in ("area_damage", "target_damage")',
        '"host_damage": host_damage',
        '"client_damage": client_damage',
        'native_mana_spent = float(mana_observation["spent_total"])',
        'float(mana_observation["spent_total"])',
        "sd.debug.reset_local_cast_observation(1)",
        "sd.debug.get_local_cast_observation(1)",
        'int(mana_observation["spend_call_count"]) < 1',
        "after_delivery_owner = query_vitals(",
        "wait_for_vitals_convergence(",
        "mana_error <= mana_tolerance",
        "observer_mana_error",
        "shared_effect_types",
        'SecondarySkillSpec(27, "Magic Storm", "field", True, True, 0x07F0)',
        'SecondarySkillSpec(72, "Acid Rain", "field", True, True, 0x07FE)',
        "synchronized_effect_type: int | None = None",
        "verify_synchronized_effect_positions(",
        "wait_for_effect_type_absent(",
        "def cast_secondary_until_delivered(",
        '"attempt_count": len(attempts)',
        'owner["last_x"] - best["last_x"]',
        'if maximum_position_error > tolerance:',
        '"effect_position_sync": effect_position_sync',
        "NATIVE_TRANSIENT_STATUS_FLAGS",
        "run_native_transient_status(",
        'observer["native_transient_status_flags"] & status_flag',
        "MINIMUM_TRANSIENT_STATUS_OBSERVATION_SECONDS = 2.5",
        "MINIMUM_TRANSIENT_STATUS_COMPARISON_SAMPLES = 2",
        "TRANSIENT_STATUS_CLEAR_PROPAGATION_BUDGET_SECONDS = 2.0",
        "active_observation_seconds = owner_cleared_at - owner_active_since",
        "minimum_matching_samples = math.ceil(compared_active_samples * 0.9)",
        "clear_delay > clear_delay_budget",
        "baseline = rush.run_movement_trial(",
        "extra_displacement < 60.0",
        "position_error > 2.0",
        'SecondarySkillSpec(54, "Magic Shield", "magic_shield")',
        "run_magic_shield(",
        "defense.invoke_native_magic_hit_trial(",
        "require_life_loss=False",
        'expected_capacity=MAGIC_SHIELD_RANK_ONE_ABSORB',
        'flashes["observer_replicated"] <= 0.001',
        'expected_capacity=0.0',
        "NATIVE_TARGET_MODIFIER_TYPES = {",
        "30: 0x1B76",
        "35: 0x1B6F",
        "QUERY_ACTOR_MODIFIERS_LUA",
        "sd.debug.get_actor_modifiers(actor)",
        'target.get("actor_address", "0")',
        "require_target_modifier_absent(",
        "wait_for_target_modifier_sync(",
        'durations["host"] > 0',
        'durations["client"] > 0',
        "duration_error <= duration_tolerance",
        'SecondarySkillSpec(51, "Dampen", "dampen")',
        "DAMPEN_DISPATCH_TOKEN",
        "DAMPEN_PRESENTATION_PATTERN",
        "prepare_dampen_shared_view_geometry(",
        "DAMPEN_SHARED_VIEW_OFFSET_X = 160.0",
        "owner_on_observer = rush.wait_for_remote_convergence(",
        "observer_on_owner = rush.wait_for_remote_convergence(",
        "wait_for_dampen_application(",
        'source["cast_sequence"] != observer["cast_sequence"]',
        'source["authority_instance"]',
        '"projectiles_repelled"',
        '"mages_disrupted"',
        '"shields_dispelled"',
        'SecondarySkillSpec(77, "Turn Undead", "turn_undead", True)',
        "TURN_UNDEAD_ELIGIBLE_ACTOR_TYPES",
        "QUERY_TURN_UNDEAD_STATE_LUA",
        "ARM_TURN_UNDEAD_MONITOR_LUA",
        "COLLECT_TURN_UNDEAD_MONITOR_LUA",
        "actor_turn_undead_flee_heading",
        "actor_turn_undead_activation_scalar",
        "actor_turn_undead_duration_ticks",
        "arm_turn_undead_monitors(",
        "collect_turn_undead_monitors(",
        '"positive_sample_count"',
        '"peak_duration_ticks"',
        '"first_active_ms"',
        '"last_active_ms"',
        "arm_timeout_ms",
        "monitor.first_active_ms > 0",
        "now - monitor.first_active_ms >= monitor.duration_ms",
        "now - monitor.started_ms >= monitor.arm_timeout_ms",
        "require_turn_undead_baseline(",
        "wait_for_turn_undead_activation(",
        "clear_turn_undead_target_freeze(",
        "wait_for_turn_undead_flee(",
        "TURN_UNDEAD_MINIMUM_DISPLACEMENT",
        "TURN_UNDEAD_MINIMUM_RADIAL_GAIN",
        "TURN_UNDEAD_MAXIMUM_VISUAL_POSITION_ERROR",
        'sample["duration_ticks"] > 0',
        "best_active_radial_gain",
        '"timeline": turn_undead_timeline',
    ):
        assert token in harness, f"secondary behavior harness lacks: {token}"
    assert harness.count(
        "input_cast, delivery = cast_secondary_until_delivered("
    ) == 4
    assert "if after_activation and (terminal_edge or sample_due) then" in harness
    assert (
        "if after_activation and (positive or terminal_edge or sample_due) then"
        not in harness
    )
    assert '"turn_undead_timeline": turn_undead_timeline' in harness
    assert '"turn_undead_flee": turn_undead_flee' not in harness
    for source, token in (
        (transport, "kMagicStormNativeTypeId = 0x07F0"),
        (spell_effect_sync, "case kMagicStormNativeTypeId:"),
        (spell_effect_sync, "IsReplicatedSpellEffectMotionNativeType("),
        (
            spell_effect_sync,
            "if (IsReplicatedSpellEffectMotionNativeType(actor.object_type_id)",
        ),
        (spell_effect_reconciliation, "if (effect.transform_valid && !native_replay_driven_primary)"),
    ):
        assert token in source, (
            f"Magic Storm authoritative effect-transform path lacks: {token}"
        )
    for token in (
        "actor_turn_undead_flee_heading=0x19C",
        "actor_turn_undead_activation_scalar=0x1B4",
        "actor_turn_undead_duration_ticks=0x20C",
    ):
        assert token in layout, f"Turn Undead native state layout lacks: {token}"
        assert f'"{token.split("=")[0]}"' in seams, (
            f"Turn Undead native state seam lacks: {token}"
        )
    for token in (
        "WorldActorStatusFlagTurnUndeadStateValid",
        "WorldActorStatusFlagTurnUndeadActive",
        "IsTurnUndeadEligibleRunEnemyType(",
        "std::uint8_t status_flags;",
        "std::int32_t turn_undead_duration_ticks;",
        "float turn_undead_flee_heading;",
        "float turn_undead_activation_scalar;",
    ):
        assert token in protocol, f"Turn Undead wire status lacks: {token}"
        assert token.split(";")[0] in runtime_state + protocol, (
            f"Turn Undead runtime status lacks: {token}"
        )
    for source, token in (
        (world_capture, "PopulateRunEnemyTransientStatusSnapshot("),
        (world_capture, "kActorTurnUndeadDurationTicksOffset"),
        (world_packet_builder, "PopulateRunEnemyTransientStatusSnapshot("),
        (world_packet_reader, "actor.status_flags = packet_actor.status_flags"),
        (world_fragmentation, "kWorldActorStatusKnownFlags"),
        (world_fragmentation, "turn_undead_active && !turn_undead_state_valid"),
        (world_reconciliation, "CopyWorldActorTransientStatusState("),
        (world_reconciliation, "ApplyReplicatedRunEnemyTransientStatus("),
        (world_reconciliation, "local_duration_ticks > 0"),
        (
            world_reconciliation,
            "const bool hard_correct_transient_run_enemy =",
        ),
        (
            world_reconciliation,
            "WorldActorStatusFlagTurnUndeadActive",
        ),
        (
            world_reconciliation,
            "!hard_correct_transient_run_enemy",
        ),
    ):
        assert token in source, (
            f"authoritative Turn Undead status path lacks: {token}"
        )
    for source, token in (
        (turn_undead_target_lock, "CaptureAuthoritativeTurnUndeadPrecastState("),
        (turn_undead_target_lock, "duration_ticks < -100000"),
        (turn_undead_target_lock, "RegisterAuthoritativeTurnUndeadCasterTargets("),
        (turn_undead_target_lock, "current_duration_ticks <= previous.duration_ticks"),
        (turn_undead_target_lock, "WriteAuthoritativeTurnUndeadCasterTarget("),
        (turn_undead_target_lock, "caster_actor_address"),
        (player_cast_hooks, "CaptureAuthoritativeTurnUndeadPrecastState("),
        (player_cast_hooks, "RegisterAuthoritativeTurnUndeadCasterTargets("),
        (secondary_replay, "CaptureAuthoritativeTurnUndeadPrecastState("),
        (secondary_replay, "RegisterAuthoritativeTurnUndeadCasterTargets("),
        (monster_pathfinding, "ApplyAuthoritativeTurnUndeadCasterTargetLock("),
        (actor_lifecycle, "ForgetAuthoritativeTurnUndeadTargetLocksForActor("),
        (actor_lifecycle, "ClearAuthoritativeTurnUndeadTargetLocks();"),
    ):
        assert token in source, (
            f"authoritative Turn Undead caster-target lock lacks: {token}"
        )
    _require_in_order(
        monster_pathfinding,
        "ApplyAuthoritativeTurnUndeadCasterTargetLock(hostile_actor_address)",
        "if (multiplayer::IsLocalTransportClient())",
        "original(self, nullptr);",
    )
    assert "TARGET_X =" not in harness
    assert "TARGET_Y =" not in harness
    assert 'SecondarySkillSpec(21, "Ring of Fire", "area_damage", True, True)' not in harness
    assert 'SecondarySkillSpec(35, "Ring of Ice", "target_status", True, True)' not in harness
    discovery = active_pair[
        active_pair.index("def discover(self)") :
        active_pair.index("def redact(self", active_pair.index("def discover(self)"))
    ]
    assert "except VerifyFailure as exc:" in discovery
    assert "last_read_error = str(exc)" in discovery
    assert "self.lua(" not in discovery

    requires_slot_zero = secondary_replay[
        secondary_replay.index("bool RequiresStockSecondaryActorSlotZero(") :
        secondary_replay.index(
            "template <typename InvokeFn>",
            secondary_replay.index("bool RequiresStockSecondaryActorSlotZero(")
        )
    ]
    assert "return skill_entry_index == 0x1E;" in requires_slot_zero
    slot_zero_return = re.search(r"return\s+[^;]+;", requires_slot_zero)
    assert slot_zero_return is not None
    assert slot_zero_return.group(0) == "return skill_entry_index == 0x1E;"
    for token in (
        "kActorSlotOffset",
        "original_slot",
        "applied_slot != 0",
        "restored_slot == original_slot",
        "return slot_context.ready && slot_context.restored;",
        "InvokeWithActorSlotZeroContext(",
    ):
        assert token in actor_slot_context, (
            f"shared stock actor-slot transaction lacks: {token}"
        )
    for token in (
        "InvokeWithStockSecondaryActorSlotZeroContext(",
        "InvokeWithActorSlotZeroContext(",
        "stock_slot_context_ok &&",
        "stock_effect_verified &&",
        "kNativePrismaticModifierTypeId",
        "modifier.duration_ticks > 0",
        '" stock_slot_context_ok="',
    ):
        assert token in secondary_replay, (
            f"Prismatic stock slot transaction lacks: {token}"
        )
    assert secondary_replay.count("InvokeWithStockSecondaryActorSlotZeroContext(") == 2

    for token in (
        "dampen_stock_effect_block=0x0054F0D6",
        "kDampenStockEffectBlock",
    ):
        assert token in layout + seams + _read(
            "SolomonDarkModLoader/src/gameplay_seams.h"
        ), f"stock Dampen presentation seam lacks: {token}"
    for token in (
        "kStockDampenEffectBlockBytes",
        "0x53, 0x83, 0xEC, 0x08, 0x8D",
        "0x46, 0x18, 0x8B, 0xCC, 0x89",
        "kStockDampenEffectBlockSkipBytes",
        "0xC6, 0x44, 0x24, 0x1F, 0x01",
        "0xE9, 0x3B, 0x00, 0x00, 0x00",
        "ScopedStockDampenEffectSuppression",
        "current != kStockDampenEffectBlockBytes",
        "applied != kStockDampenEffectBlockSkipBytes",
        "restored_bytes == kStockDampenEffectBlockBytes",
        "return succeeded;",
    ):
        assert token in dampen_context, (
            f"stock Dampen effect-call transaction lacks: {token}"
        )
    assert player_cast_hooks.count(
        "InvokeWithStockDampenEffectSuppressed("
    ) == 2
    assert "TryConsumeLocalMultiplayerDampenMana" not in player_cast_hooks
    assert "Multiplayer remote Dampen used the safe replicated dispatcher" not in (
        player_cast_hooks
    )
    for token in (
        "kMultiplayerDampenDisruptableFlag = 0x2u",
        "actor.object_header_word &",
        "kMultiplayerDampenDisruptableFlag",
    ):
        assert token in dampen_effect, (
            f"deterministic Dampen native-family gate lacks: {token}"
        )
    assert "if (!actor.tracked_enemy)" not in dampen_effect
    assert "QueueDebugUiMultiplayerDampenPresentation(" in dampen_effect
    for token in (
        "BuildGameplayDampenPresentationRenderItems(",
        "multiplayer::GetLocalTransportParticipantId()",
        'element.surface_id == "gameplay_nameplate"',
        "D3DPT_LINESTRIP",
        "DrawGameplayDampenPresentation(",
        '"Multiplayer Dampen DX9 presentation drawn.',
    ):
        assert token in dampen_rendering, (
            f"multiplayer Dampen DX9 presentation lacks: {token}"
        )

    for source, token in (
        (gameplay_api, "bool TryListNativeActorModifiers("),
        (state_getters, "bool TryListNativeActorModifiers("),
        (state_getters, "kActorModifierListCountOffset"),
        (state_getters, "kNativeModifierTypeIdOffset"),
        (state_getters, "kNativeModifierDurationTicksOffset"),
        (debug_observations, "int LuaDebugGetActorModifiers("),
        (debug_bindings, '"get_actor_modifiers"'),
    ):
        assert token in source, f"exact native modifier witness lacks: {token}"

    for token in (
        "SteamFriendActivePair",
        "require_shared_test_run",
        "primary.enable_manual_stock_spawner_combat()",
        "secondary.ensure_batch_capacity(",
        "for direction in context.focus_directions:",
        "reset_quiet_arena(",
        "secondary.wait_for_effect_type_absent(",
        '"prior_effect_retirement"',
        "require_manual_spawner=skill.target_required",
        "secondary.acquire_skill(",
        "secondary.run_skill(",
        "find_new_crash_artifacts",
    ):
        assert token in runner, f"Steam secondary behavior runner lacks: {token}"
    _require_in_order(
        runner,
        'output["active_step"] = "combat_bootstrap"',
        'output["combat_bootstrap"] = primary.enable_manual_stock_spawner_combat()',
        'output["active_step"] = "initial_arena_reset"',
        'output["initial_arena_reset"] = reset_quiet_arena()',
        'output["active_step"] = "capacity"',
        'output["active_step"] = "acquire"',
    )

    for token in (
        "gameplay_mouse_right_button=0x27A",
        "FUN_00429820 writes raw mouse-mask bit 2",
    ):
        assert token in layout, f"right-mouse layout lacks: {token}"
    assert '"gameplay_mouse_right_button"' in seams
    for token in (
        "kGameplayMouseRightButtonOffset",
        "pending_mouse_right_frames",
        "ClearRawGameplayMouseRight",
        "Injected gameplay mouse-right click",
        "Released injected gameplay mouse-right",
    ):
        assert token in mouse_hook, f"right-mouse hook lacks: {token}"
    for token in (
        "bool QueueGameplayBindingPress(",
        "kMouseLeftBindingCode = 0x200",
        "kMouseRightBindingCode = 0x201",
        "return QueueGameplayMouseRightClick(error_message);",
    ):
        assert token in input_queue, f"exact binding dispatcher lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaInputPressBinding, "press_binding")',
        'RegisterFunction(state, &LuaInputHoldMouseRightFrames, "hold_mouse_right_frames")',
        'RegisterFunction(state, &LuaInputClearMouseRight, "clear_mouse_right")',
        'RegisterFunction(state, &LuaInputGetMouseRightState, "get_mouse_right_state")',
    ):
        assert token in lua_input, f"Lua right-mouse binding lacks: {token}"
    assert "falling back to windowed SendInput" not in lua_input
    assert "sd.input.press_binding" in focus
    assert "def wait_for_secondary_belt_parity(" in focus
    _require_in_order(
        focus,
        "pause_cleared = wait_for_pause(",
        "wait_for_secondary_belt_parity(",
    )
    assert "sd.input.hold_mouse_right_frames" not in focus
    assert "activation was not consumed" in focus
    assert "source_offset = log_position(direction.source_log)" in focus
    assert "log_after(direction.source_log, source_offset)" in focus
    assert "deadline - time.monotonic()" in focus
    assert "time.sleep(min(0.05, remaining))" in focus
    assert "consumption_count_before" not in focus
    assert "def queue_secondary_belt_slot(" in focus
    assert "def queue_until_accepted_casts(" in focus
    assert "parse_secondary_accept_times(last_log, belt_slot)" in focus
    assert '"native_accept_timestamps"' in focus
    assert "(current - previous).total_seconds()" in focus
    assert "wait_for_next_accept" not in focus
    assert '"input_kind": "mouse_right" if mouse_backed else "keyboard"' in focus
    for relative_path in (
        "tools/verify_multiplayer_focus_behavior_sync.py",
        "tools/verify_multiplayer_persistent_status_sync.py",
        "tools/verify_multiplayer_ring_of_fire_multikill_stability.py",
        "tools/multiplayer_secondary_behavior_harness.py",
    ):
        tree = ast.parse(_read(relative_path), filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name != "cast_secondary_belt_slot":
                continue
            has_timeout = len(node.args) >= 3 or any(
                keyword.arg == "timeout" for keyword in node.keywords
            )
            assert has_timeout, (
                f"{relative_path} calls cast_secondary_belt_slot without its "
                "bounded input-consumption timeout"
            )
    assert "input_witnessed = (" in harness
    assert "if belt_slot == 0" in harness
    assert "click_process(" not in ring
    assert 'input_modes.append("live_native_binding")' in ring

    for token in (
        "ParticipantTransientStatusFlagPlanewalker = 1 << 2",
        "ParticipantTransientStatusFlagStoneskin = 1 << 3",
        "constexpr std::uint16_t kProtocolVersion = 75;",
    ):
        assert token in protocol, f"native transient status protocol lacks: {token}"
    for token in (
        "kActorRenderDriveFlagsOffset",
        "ParticipantTransientStatusFlagPlanewalker",
        "kNativeStoneskinModifierTypeId",
        "ParticipantTransientStatusFlagStoneskin",
    ):
        assert token in status_reader, f"native transient status reader lacks: {token}"
    for token in (
        "kNativeTransientStatusMappings",
        "RemoveAllNativeActorModifiersByType(",
        "InvokeNativeRemoteParticipantSecondarySkill(",
        "transient_status_reconcile_not_before_ms",
        "now_ms + 500",
        "now_ms + (verified ? 100 : 1000)",
    ):
        assert token in status_reconcile, (
            f"native transient status reconciliation lacks: {token}"
        )
    assert "transient_status_reconcile_desired_flags" in entity_state
    assert (
        "transient_status_flags & ParticipantTransientStatusFlagPoisoned"
        in vitals_authority
    ), "host damage correction must not claim owner-authored secondary statuses"

    primary = _read("tools/verify_multiplayer_primary_kill_stress.py")
    faster = _read("tools/verify_multiplayer_faster_caster_behavior_sync.py")
    stale_hold = _read("tools/verify_steam_friend_world_snapshot_stale_hold.py")
    for source, token in (
        (primary, 'network_id = int(spawn["network_actor_id"])'),
        (harness, 'network_id = int(spawned["network_actor_id"])'),
        (faster, 'network_id = int(spawn["network_actor_id"])'),
        (stale_hold, 'network_id = int(spawn["network_actor_id"])'),
    ):
        assert token in source, (
            "spawn-driven combat verification must bind the exact returned "
            f"network actor id: {token}"
        )
    assert '"network_actor_id": network_actor_id' in primary

    _require_in_order(
        runner,
        'output["capacity"] = secondary.ensure_batch_capacity(',
        'output["acquisitions"] = {}',
        'output["behaviors"] = {}',
        "reset_quiet_arena(",
        "secondary.run_skill(",
    )
    return (
        "all 23 native secondary skills have a capacity-safe real-Steam matrix "
        "with both-owner dispatch, replay, effect, resource, target, and motion witnesses"
    )


def test_secondary_matrix_drives_targeted_stock_cursor_geometry() -> str:
    harness = _read("tools/multiplayer_secondary_behavior_harness.py")
    focus = _read("tools/verify_multiplayer_focus_behavior_sync.py")

    for token in (
        "cursor_world: tuple[float, float] | None = None",
        "actor_world_view_scale",
        "actor_world_view_origin_x",
        "actor_world_view_origin_y",
        "cursor_screen_position",
        "cursor_secondary_at_mouse",
        "gameplay_cursor_placement_active",
        "sd.debug.resolve_game_address",
        "sd.debug.write_i32(cursor_screen_address, cursor_screen_x)",
        "sd.debug.write_i32(cursor_screen_address + 4, cursor_screen_y)",
        "sd.input.press_binding",
    ):
        assert token in focus, f"targeted stock-cursor input lacks {token}"
    _require_in_order(
        focus,
        "sd.debug.write_i32(cursor_screen_address, cursor_screen_x)",
        "sd.input.press_binding",
    )

    for token in (
        "CURSOR_PLACED_SECONDARY_ROWS",
        "CURSOR_WORLD_TARGET_TOLERANCE",
        "expected_cursor_world=cursor_world",
        "cursor_world_error <= CURSOR_WORLD_TARGET_TOLERANCE",
        'float(target["x"])',
        'float(target["y"])',
        'SecondarySkillSpec(76, "Call Comet", "target_damage", True, True)',
    ):
        assert token in harness, f"targeted secondary witness lacks {token}"

    return (
        "targeted cursor secondaries drive the owner stock cursor from live "
        "camera geometry and verify the accepted world point"
    )


def test_secondary_matrix_isolates_prior_native_effect_lifetimes() -> str:
    runner = _read("tools/verify_steam_friend_active_pair_secondary_behavior.py")
    harness = _read("tools/multiplayer_secondary_behavior_harness.py")
    gameplay_api = _read("SolomonDarkModLoader/include/mod_loader_gameplay_api.inl")
    gameplay_public = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_debug_and_spawn.inl"
    )
    lua_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")

    for token in (
        'output["post_behavior_retirements"] = {}',
        'shared_effect_types = behavior.get("shared_effect_types", [])',
        "secondary.retire_test_player_created_effects(",
        "secondary.wait_for_effect_type_absent(",
        'output["post_behavior_retirements"][direction.name][str(row)]',
    ):
        assert token in runner, f"secondary case isolation lacks {token}"
    _require_in_order(
        runner,
        "secondary.run_skill(",
        'shared_effect_types = behavior.get("shared_effect_types", [])',
        "secondary.retire_test_player_created_effects(",
        "secondary.wait_for_effect_type_absent(",
        'output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)',
    )

    for token in (
        "TEST_PLAYER_CREATED_EFFECT_TYPES",
        "RETIRE_TEST_PLAYER_CREATED_ACTORS_LUA",
        "def retire_test_player_created_effects(",
        "sd.gameplay.retire_test_run_player_created_actors",
        'values.get("ok") != "true"',
        'parse_int_text(values.get("requested_count"), 0) < 1',
    ):
        assert token in harness, f"player-created effect cleanup lacks {token}"
    retire_start = harness.index("def retire_test_player_created_effects(")
    retire_end = harness.index("\ndef ", retire_start + 4)
    retire_body = harness[retire_start:retire_end]
    for token in (
        '"host": HOST_ENDPOINT',
        '"client": CLIENT_ENDPOINT',
        "concurrent.futures.ThreadPoolExecutor(max_workers=2)",
    ):
        assert token in retire_body, (
            f"player-created effect cleanup must retire both stock-owned copies: {token}"
        )

    assert "RetireTestRunPlayerCreatedActors(" in gameplay_api
    for token in (
        "bool RetireTestRunPlayerCreatedActors(",
        "IsRunLifecycleManualEnemySpawnerTestModeEnabled()",
        "multiplayer::IsReplicatedRunPlayerCreatedActorType(native_type_id)",
        'scene.kind != "arena"',
        "CallActorRequestRetirementSafe(",
        "kActorPendingRemoveOffset",
    ):
        assert token in gameplay_public, f"test actor retirement lacks {token}"
    for token in (
        "LuaGameplayRetireTestRunPlayerCreatedActors",
        '"retire_test_run_player_created_actors"',
        "RetireTestRunPlayerCreatedActors(",
    ):
        assert token in lua_bindings, f"Lua test actor retirement lacks {token}"

    return (
        "each secondary behavior retires explicit long-lived test actors and "
        "waits for every observed native effect to leave both peers"
    )


def test_magic_trap_lifetime_follows_cast_owner() -> str:
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    effect_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "spell_effect_sync.inl"
    )
    secondary_harness = _read(
        "tools/multiplayer_secondary_behavior_harness.py"
    )
    effect_reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "spell_effect_reconciliation.inl"
    )
    world_protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    world_reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation/apply_snapshot.inl"
    )

    assert "kMagicTrapNativeTypeId = 0x07F5" in transport
    for token in (
        "case kMagicTrapNativeTypeId:",
        "SpellEffectStateFlagTerminal",
        "!active && effect.native_type_id == kMagicTrapNativeTypeId",
    ):
        assert token in effect_sync, (
            f"Magic Trap participant-owned effect tracking lacks {token}"
        )
    _require_in_order(
        effect_sync,
        "!active && effect.native_type_id == kMagicTrapNativeTypeId",
        "active && effect.native_type_id != kFirewalkerTrailNativeTypeId",
    )

    for token in (
        "MAGIC_TRAP_NATIVE_TYPE_ID = 0x07F5",
        '"Magic Trap",',
        "MAGIC_TRAP_NATIVE_TYPE_ID)",
        "actor_slot = tonumber(actor.actor_slot) or -1",
        "emit(prefix .. 'actor_slot', row.actor.actor_slot)",
        '"actor_slot": parse_int_text(',
        "def verify_participant_owned_effect_slots(",
        'owner_slots != [0]',
        'any(slot <= 0 for slot in observer_slots)',
        '"participant_owned_effect_slots": participant_owned_effect_slots',
    ):
        assert token in secondary_harness, (
            f"Magic Trap live ownership witness lacks {token}"
        )
    _require_in_order(
        secondary_harness,
        "effects = collect_effect_monitors(pair, direction, timeout)",
        "participant_owned_effect_slots = verify_participant_owned_effect_slots(",
        '"participant_owned_effect_slots": participant_owned_effect_slots',
    )

    for token in (
        "kReplicatedMagicTrapNativeTypeId = 0x07F5",
        "TryRequestReplicatedSpellEffectRetirement(",
        "CallActorRequestRetirementSafe(",
        "kActorPendingRemoveOffset",
    ):
        assert token in effect_reconciliation, (
            f"Magic Trap observer retirement lacks {token}"
        )

    assert "kMagicTrapNativeTypeId" not in world_protocol
    assert (
        "IsReplicatedRunPlayerCreatedRetirementAuthoritative"
        not in world_reconciliation
    )

    return (
        "Magic Trap transform and terminal state follow the casting "
        "participant in both ownership directions"
    )


def test_mana_recovery_tolerance_respects_float32_precision() -> str:
    import verify_multiplayer_all_stat_sync as stats

    # Native progression mana is stored as a 32-bit float. A comparison exactly
    # on the semantic 0.5 boundary can therefore arrive one float ULP above it.
    assert not stats.exceeds_float32_tolerance(
        0.5000001192092896,
        0.5,
        (1.0, 1.5),
    )
    assert stats.exceeds_float32_tolerance(
        0.501,
        0.5,
        (1.0, 1.5),
    )
    return "mana comparison admits one native-float rounding edge, not real skew"


def test_health_up_contract_composes_with_life_charm() -> str:
    import verify_multiplayer_all_stat_sync as stats

    ranked_values = (0.0, 50.0, 100.0, 150.0, 200.0)
    assert stats.expected_ranked_max_hp(62.5, 0, 2, ranked_values) == 187.5
    assert stats.expected_ranked_max_hp(187.5, 2, 4, ranked_values) == 312.5
    return "HEALTH UP retains the native Life Charm multiplier from any initial rank"


def test_mana_up_contract_replaces_the_initial_rank_bonus() -> str:
    import verify_multiplayer_all_stat_sync as stats

    ranked_values = (0.0, 100.0, 200.0, 300.0, 400.0)
    assert stats.expected_ranked_max_mp(100.0, 0, 3, ranked_values) == 400.0
    assert stats.expected_ranked_max_mp(200.0, 1, 3, ranked_values) == 400.0
    return "MANA UP replaces an inherited rank bonus instead of counting it twice"


def test_world_stale_hold_controls_the_exact_remote_host_process() -> str:
    verifier = _read("tools/verify_steam_friend_world_snapshot_stale_hold.py")
    for token in (
        'if PAIR_BACKEND == "remote-windows-host":',
        "remote_windows_process_id()",
        "def suspend_remote_windows_game(",
        "[string]::Equals([string]$cim.ExecutablePath,$path,",
        "return suspend_remote_windows_game(pid, duration_ms)",
        "def query_client_transport_liveness(",
        "def verify_spawned_enemy_stale_hold(\n    pair: SteamFriendActivePair,",
        "return verify_spawned_enemy_stale_hold(\n            pair,",
        'sample["session_status"] == "Ready"',
        'values.get("transport_ready") == "true"',
        'values.get("remote_transport_connected") == "true"',
        '"transport_liveness_samples": transport_liveness_samples',
        '"--suspend-ms must be between 1800 and 25000"',
    ):
        assert token in verifier, token
    _require_in_order(
        verifier,
        "configure(pair)",
        "primary.cleanup_live_enemies()",
        "manual_prelude = primary.enable_manual_stock_spawner_combat()",
    )
    assert "finally:\n        primary.cleanup_live_enemies()" in verifier
    return "stale-authority testing suspends only the exact remote Windows host game"


def test_hub_presentation_uses_stored_authority_across_lifecycle_rotation() -> str:
    import probe_hub_npc_presentation_sync as presentation

    client = {
        "repactor.1.network_id": "456",
        "repactor.1.type": str(presentation.STUDENT_TYPE_ID),
        "applyactor.1.network_id": "123",
        "applyactor.1.type": str(presentation.STUDENT_TYPE_ID),
        "presactor.1.network_id": "123",
        "presactor.1.type": str(presentation.STUDENT_TYPE_ID),
        "presactor.1.student_book_palette_count": "0",
        "binding.1.network_id": "123",
        "binding.1.address": "0x1000",
        "binding.1.type": str(presentation.STUDENT_TYPE_ID),
        "binding.1.matched": "true",
        "binding.1.parked": "false",
        "binding.1.removed": "false",
        "actor.1.address": "0x1000",
        "actor.1.type": str(presentation.STUDENT_TYPE_ID),
        "replicated.apply_valid": "true",
        "replicated.apply_actors_available": "true",
        "replicated.apply_presentation_available": "true",
        "replicated.apply_presentation_received_ms": "90",
        "replicated.applied_ms": "100",
        "replicated.sampled_ms": "110",
    }
    comparison = presentation.compare_host_to_client({}, client)
    assert comparison["summary"]["compared_total"] == 1
    assert comparison["summary"]["student_compared"] == 1
    assert comparison["comparisons"][0]["student_color_match"]
    assert comparison["comparisons"][0]["student_book_palette_match"]
    return "hub presentation survives host lifecycle rotation by using stored applied authority"


def test_hub_services_use_typed_native_lua_dispatch() -> str:
    layout = _read("config/binary-layout.ini")
    runtime = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/hub_service_runtime.inl"
    )
    public_api = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_hub.inl"
    )
    lua = _read("SolomonDarkModLoader/src/lua_engine_bindings_input.cpp")
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )

    for token in (
        "hub_service_dispatch=0x00514A20",
        "hub_courtyard=0x00819A70",
        "hub_chat_active=0x008199F0",
        "hub_courtyard_vtable=0x00792644",
        "inventory_screen_vtable=0x00794F54",
        "inventory_shop_vtable=0x0079044C",
        "gameplay_hub_surface=0x15A0",
        "hub_luthacus_storage_action=0x10D0",
        "hub_fomentius_action=0x1184",
        "hub_hagatha_action=0x101C",
        "inventory_screen_shop=0x160",
    ):
        assert token in layout, f"typed hub service layout lacks: {token}"

    for token in (
        "enum class HubServiceKind",
        'name == "luthacus_storage"',
        'name == "fomentius"',
        'name == "hagatha"',
        "IsSharedHubSceneContext(scene_context)",
        "surface.chat_active",
        "surface.surface_active",
        "courtyard_vtable != expected_courtyard_vtable",
        "vtable_dispatch_address != dispatch_address",
        "CallHubServiceDispatchSafe",
        "surface.inventory_screen_active",
        "surface.inventory_shop_active",
    ):
        assert token in runtime, f"typed hub service runtime lacks: {token}"
    assert "SendInput" not in runtime
    assert "mouse_event" not in runtime

    for token in (
        "QueueHubOpenService(",
        "pending_hub_service_request",
        "Another hub service request is already pending.",
        "TryGetHubSurfaceState(",
    ):
        assert token in public_api, f"typed hub service API lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaHubOpenService, "open_service")',
        'RegisterFunction(state, &LuaHubGetSurfaceState, "get_surface_state")',
        'lua_setfield(state, -2, "inventory_screen_active")',
        'lua_setfield(state, -2, "inventory_shop_active")',
    ):
        assert token in lua, f"typed hub Lua API lacks: {token}"
    assert "TryDispatchPendingHubServiceOnGameThread();" in pump
    return "Lua opens named hub services through the verified stock Courtyard dispatcher"


def test_natural_offer_expectation_clamps_to_native_maximum() -> str:
    import verify_multiplayer_all_stat_sync as stats

    assert stats.expected_natural_offer_active(
        {"active": 1, "statbook_max_level": 1}, 1
    ) == 1
    assert stats.expected_natural_offer_active(
        {"active": 3, "statbook_max_level": 12}, 2
    ) == 5
    return "natural choices accept stock max-rank clamping without hiding rank growth"


def test_stat_matrix_waits_for_expected_derived_contract() -> str:
    stats = _read("tools/verify_multiplayer_all_stat_sync.py")
    assert "def wait_for_stat_contract(" in stats
    assert "contract_convergence = wait_for_stat_contract(" in stats
    assert '"contract_convergence": contract_convergence' in stats
    return "stat steps require expected owner/observer values, not stale matching views"


def test_mana_recovery_precondition_holds_zero_until_replication() -> str:
    stats = _read("tools/verify_multiplayer_all_stat_sync.py")
    loop = stats.split("while time.monotonic() < settle_deadline:", 1)[1].split(
        "else:", 1
    )[0]
    assert "settle_reset = set_local_mana(target_pipe, 0.0)" in loop
    assert '"owner_mp": owner["native"]' in loop
    assert 'float(settle_sample["owner_mp"]) < settle_ceiling' in loop
    return "high recovery cannot outrun the replicated zero-mana precondition"


def test_reconnect_verifier_has_a_dedicated_cold_launch_timeout() -> str:
    reconnect = _read("tools/verify_steam_friend_active_run_reconnect.py")
    assert '"--launch-timeout", type=float, default=180.0' in reconnect
    assert "wait_for_game(args.new_client_instance, args.launch_timeout)" in reconnect
    return "cold Proton staging is not bounded by the gameplay convergence timeout"


def test_loot_materialization_waits_for_native_field_convergence() -> str:
    loot = _read("tools/verify_multiplayer_loot_drop_materialization.py")
    assert "def wait_for_probe_field_convergence(" in loot
    assert "field_state = wait_for_probe_field_convergence(" in loot
    assert 'result["field_convergence"] = field_state["convergence"]' in loot
    assert 'result["final_host_capture"] = field_state["host_capture"]' in loot
    assert 'result["final_client_capture"] = field_state["client_capture"]' in loot
    return "loot evidence uses settled native actors rather than first materialization frames"


def test_primary_kill_stress_resumes_only_a_contiguous_passed_prefix() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    prior = {
        "kills": [
            {"kill_index": 1, "direction": "host_to_client", "status": "passed"},
            {"kill_index": 2, "direction": "host_to_client", "status": "setup"},
        ]
    }
    resumed = primary.validated_resume_kills(
        prior,
        ("host_to_client", "client_to_host"),
        2,
    )
    assert len(resumed) == 1
    invalid = {
        "kills": prior["kills"]
        + [{"kill_index": 3, "direction": "client_to_host", "status": "passed"}]
    }
    try:
        primary.validated_resume_kills(
            invalid,
            ("host_to_client", "client_to_host"),
            2,
        )
    except primary.VerifyFailure:
        pass
    else:
        raise AssertionError("non-contiguous passed kills were accepted")
    source = _read("tools/verify_multiplayer_primary_kill_stress.py")
    assert "FAST_LUA_TIMEOUT_SECONDS = 8.0" in source
    assert "timeout=FAST_LUA_TIMEOUT_SECONDS" in source
    return "kill stress preserves proved prefixes and rejects gaps after automation faults"


def test_primary_kill_stress_accepts_a_late_death_from_the_prior_cast() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    original = primary.require_death_logs
    calls = []
    try:
        primary.require_death_logs = lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ) or {"source_ok": True, "receiver_ok": True}
        attempt = {
            "status": "native_primary_no_kill",
            "source_log_offset": 11,
            "receiver_log_offset": 22,
        }
        target = {
            "network_id": 33,
            "host_actor_address": 44,
            "x": 1.0,
            "y": 2.0,
        }
        observed = primary.finalize_late_primary_death(
            object(),
            target,
            attempt,
            {
                "host": {"found": "true", "snapshot.dead": "true"},
                "client": {"found": "true", "snapshot.dead": "false"},
            },
        )
        removed_attempt = {
            "status": "native_primary_no_kill",
            "source_log_offset": 33,
            "receiver_log_offset": 44,
        }
        removed = primary.finalize_late_primary_death(
            object(),
            target,
            removed_attempt,
            {
                "host": {"found": "false", "live_local_count": "0"},
                "client": {"found": "false", "live_local_count": "0"},
            },
        )
    finally:
        primary.require_death_logs = original
    assert observed
    assert attempt["status"] == "death_logs_observed"
    assert attempt["late_death_observed"] is True
    assert attempt["death_logs"] == {"source_ok": True, "receiver_ok": True}
    assert removed
    assert removed_attempt["target_removed_after_late_death"] is True
    assert removed_attempt["status"] == "death_logs_observed"
    assert len(calls) == 2
    assert calls[0][0][2:] == (11, 22)
    return "a delayed lethal effect is attributed to its real prior native cast"


def test_primary_kill_stress_requires_native_death_evidence_at_epsilon_hp() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    rounded_epsilon_hp = {
        "found": "true",
        "snapshot.dead": "false",
        "snapshot.hp": "0.050",
        "local.dead": "false",
        "local.death_handled": "0",
        "local.hp": "0.050",
    }
    assert not primary.target_state_dead(rounded_epsilon_hp)
    assert primary.target_state_alive(rounded_epsilon_hp)
    assert primary.target_state_dead(
        rounded_epsilon_hp | {"local.death_handled": "1"}
    )
    return "rounded low HP cannot consume the final retry without a native death signal"


def test_run_reentry_audits_only_logs_written_during_the_test() -> str:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    import verify_steam_friend_run_exit_reentry as reentry

    token = (
        "Multiplayer session/transport tick rejected outside its owning "
        "AppMainTick thread."
    )
    with TemporaryDirectory() as directory:
        log = Path(directory) / "loader.log"
        log.write_text(token + "\n", encoding="utf-8")
        positions = reentry.capture_log_positions((log,))
        with log.open("a", encoding="utf-8") as stream:
            stream.write("new lifecycle activity\n")
        reentry.assert_no_wrong_thread_rejections(positions)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(token + "\n")
        try:
            reentry.assert_no_wrong_thread_rejections(positions)
        except reentry.VerifyFailure:
            pass
        else:
            raise AssertionError("new wrong-thread rejection was not detected")
    return "run reentry scans only bounded log content appended during its own run"


def test_beta_artifact_verifier_streams_large_zip_members() -> str:
    import hashlib
    import struct
    import zipfile
    from pathlib import Path
    from tempfile import TemporaryDirectory

    import verify_beta_release_artifact as artifact

    payload = bytearray(2 * 1024 * 1024)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x84, artifact.PE_I386)
    expected_digest = hashlib.sha256(payload).hexdigest()
    with TemporaryDirectory() as directory:
        archive_path = Path(directory) / "large-member.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as output:
            output.writestr("large.exe", payload)
        with zipfile.ZipFile(archive_path) as archive:
            member = archive.getinfo("large.exe")
            archive.read = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("whole-member buffering is forbidden")
            )
            assert artifact.sha256_zip_member(archive, member) == expected_digest
            assert (
                artifact.pe_machine_zip_member(archive, member, "large.exe")
                == artifact.PE_I386
            )
    return "beta artifact verification streams hashes and bounded PE headers"


def test_beta_package_smoke_forwards_a_valid_website_lobby_uri() -> str:
    smoke = _read("scripts/Test-BetaReleasePackage.ps1")
    assert (
        '$testDirectory = [Uri]::EscapeDataString("http://127.0.0.1:5080")'
        in smoke
    )
    assert (
        '"solomondarkrevived://join/${testLobbyId}?directory=${testDirectory}"'
        in smoke
    )
    return "package smoke exercises the same directory-bearing URI emitted by the website"


def test_animated_loot_comparison_bounds_snapshot_phase_skew() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    host = {
        "network_drop_id": 1,
        "type_id": primary.LOOT_ORB_TYPE_ID,
        "kind": "Orb",
        "active": True,
        "presentation_state": 0,
        "materialized": False,
        "local_actor_address": 0,
        "actor_type_id": 0,
        "x": 100.0,
        "y": 200.0,
        "actor_x": 100.0,
        "actor_y": 200.0,
        "radius": 15.0,
        "actor_radius": 15.0,
        "amount": 23,
        "amount_tier": 1,
        "value": 0.584,
        "actor_amount": 0,
        "actor_amount_tier": 0,
        "actor_value": 0.0,
        "item_type_id": 0,
        "item_slot": -1,
        "stack_count": 0,
        "actor_item_type_id": 0,
        "actor_item_slot": -1,
        "actor_stack_count": 0,
    }
    client = {
        **host,
        "materialized": True,
        "local_actor_address": 2,
        "actor_type_id": primary.LOOT_ORB_TYPE_ID,
        "x": 104.5,
        "actor_x": 104.5,
        "actor_amount_tier": 1,
        "actor_value": 0.584,
    }
    bounded = primary.compare_replicated_loot_drop(host, client)
    assert bounded["ok"], bounded
    assert bounded["actor_position_delta"] == 0.0
    assert primary.client_loot_presentation_converged(client)

    client["actor_x"] = 100.0
    assert not primary.client_loot_presentation_converged(client)

    client["x"] = 109.0
    client["actor_x"] = 109.0
    excessive = primary.compare_replicated_loot_drop(host, client)
    assert not excessive["ok"]
    assert "client snapshot drop position differs from host" in excessive["failures"]
    return "animated loot allows one transport phase of skew while bounding real drift"


def test_shared_menu_pause_is_host_authoritative_and_time_bounded() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    runtime_effect_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    pause_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "shared_gameplay_pause_sync.inl"
    )
    local_packets = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_participant_state_sync.inl"
    )
    pause_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    peer_lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "remote_peer_lifecycle.inl"
    )
    actor_world = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "actor_world_pause_hook.inl"
    )
    actor_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/"
        "player_actor_tick_hook.inl"
    )
    wave_tick = read_source_unit(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    verifier = _read("tools/verify_multiplayer_shared_menu_pause.py")

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 75",
        "local_menu_pause_request_epoch",
        "local_menu_pause_requested",
        "shared_gameplay_pause_active",
        "shared_gameplay_pause_timed_out",
        "shared_gameplay_pause_deadline_remaining_ms",
        "shared_gameplay_pause_origin_participant_id",
    ):
        assert token in protocol, f"shared-pause wire contract lacks: {token}"
    assert "struct SharedGameplayPauseRuntimeInfo" in runtime_state
    assert (
        "SharedGameplayPauseRuntimeInfo shared_gameplay_pause"
        in runtime_effect_state
    )
    for token in (
        '#include "multiplayer_local_transport/shared_gameplay_pause_sync.inl"',
        "HostMenuPauseRequestState",
        "host_menu_pause_requests_by_participant",
    ):
        assert token in transport, f"shared-pause transport state lacks: {token}"

    for token in (
        "kSharedGameplayPauseTimeoutMs = 60'000",
        "TryGetLatestDebugUiSurfaceSnapshot",
        'observed_surface_id == "pause_menu"',
        'observed_surface_id == "simple_menu"',
        'observed_surface_id == "quick_panel"',
        'observed_surface_id == "settings"',
        "RefreshLocalMenuPauseRequest",
        "ApplyHostMenuPauseRequest",
        "RefreshHostSharedGameplayPause",
        "ApplyAuthoritativeSharedGameplayPause",
    ):
        assert token in pause_sync, f"shared-pause implementation lacks: {token}"
    assert "IsAuthoritativeHostParticipantPacket" in incoming
    assert "ShouldPauseMultiplayerGameplay" in pause_api
    assert "deadline_ms = now_ms + kSharedGameplayPauseTimeoutMs" in pause_sync
    assert "request.timed_out_until_release = true" in pause_sync
    assert "if (!requested)" in pause_sync
    assert "request.timed_out_until_release = false" in pause_sync
    assert "kSharedGameplayPauseAuthorityFreshnessMs" in pause_sync
    identity_resolver_start = pause_sync.index(
        "const ParticipantInfo* FindHostPauseRequestParticipant("
    )
    identity_resolver_end = pause_sync.index(
        "bool IsHostPauseRequestParticipantCurrent(",
        identity_resolver_start,
    )
    identity_resolver = pause_sync[
        identity_resolver_start:identity_resolver_end
    ]
    _require_in_order(
        identity_resolver,
        "participant_id == g_local_transport.local_peer_id",
        "FindLocalParticipant(runtime_state)",
        "FindParticipant(runtime_state, participant_id)",
    )
    assert (
        "host_menu_pause_requests_by_participant.erase(participant_id)"
        in peer_lifecycle
    )
    assert "SharedGameplayPauseRuntimeInfo{}" in peer_lifecycle
    assert "SharedGameplayPauseRuntimeInfo{}" in pause_api

    assert "PopulateSharedGameplayPausePacketFields" in local_packets
    for token in (
        "local_menu_pause_request_epoch",
        "local_menu_pause_requested",
        "shared_gameplay_pause_active",
        "shared_gameplay_pause_deadline_remaining_ms",
        "shared_gameplay_pause_origin_participant_id",
    ):
        assert token in incoming, f"incoming shared-pause sync lacks: {token}"
        assert token in pause_sync, f"outgoing shared-pause sync lacks: {token}"

    for hook_source in (actor_world, actor_tick, wave_tick):
        assert "ShouldPauseMultiplayerGameplay()" in hook_source
        assert "ShouldPauseGameplayForLevelUpSelection()" not in hook_source
    assert "shared_gameplay_pause_status" in lua_runtime

    for token in (
        "open_local_pause_surface",
        "wait_for_shared_pause",
        "assert_world_frozen",
        "close_local_pause_surface",
        "assert_world_resumed",
        "wait_for_timeout_release",
        "60.0",
        '"host_owned"',
        '"client_owned"',
    ):
        assert token in verifier, f"shared-pause live verifier lacks: {token}"

    _require_in_order(
        verifier,
        "configure_behavior_context(pair)",
        'result["manual_prelude"] = primary.enable_manual_stock_spawner_combat()',
        "for direction in DIRECTIONS:",
    )
    assert "wait_for_pair_transform_convergence" not in verifier
    enemy_position_start = verifier.index("def enemy_position(")
    enemy_position_end = verifier.index(
        "def position_distance(",
        enemy_position_start,
    )
    enemy_position = verifier[enemy_position_start:enemy_position_end]
    assert 'floating(state, "x")' in enemy_position
    assert 'floating(state, "y")' in enemy_position
    assert '"local.found"' not in enemy_position

    return (
        "run menus publish a fast local request, the host owns one 60-second "
        "pause barrier, and both peers freeze and resume the same world"
    )
