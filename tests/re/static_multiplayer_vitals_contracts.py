"""Host-authoritative participant-vitals synchronization contracts."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_client_owned_magic_shield_consumption_is_host_authoritative() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    vitals_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_authority.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )
    native_remote_vitals = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_vitals_and_playback.inl"
    )
    native_remote_playback = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_playback.inl"
    )
    actor_slot_context = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "scoped_actor_slot_context.inl"
    )
    damage_authority_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_damage_authority_hook.inl"
    )
    request_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    action_queue = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_gameplay_action_queues.inl"
    )
    action_executor = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_participant_vitals_actions.inl"
    )
    native_probe = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "native_defense_behavior_probes.inl"
    )
    lua_probe = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_debug/"
        "functions_native_calls.inl"
    )
    defense_harness = _read(
        "tools/multiplayer_defense_behavior_harness.py"
    )
    secondary_harness = _read(
        "tools/multiplayer_secondary_behavior_harness.py"
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 78;",
        "ParticipantVitalsCorrectionFlagMagicShieldState",
        "std::uint8_t correction_flags;",
        "float magic_shield_absorb_remaining;",
        "float magic_shield_absorb_capacity;",
        "float magic_shield_explosion_fraction;",
        "float magic_shield_hit_flash;",
        "static_assert(sizeof(ParticipantVitalsCorrectionPacket) == 88",
    ):
        assert token in protocol, f"shield correction protocol lacks: {token}"

    for token in (
        "magic_shield_absorb_remaining",
        "magic_shield_absorb_capacity",
        "magic_shield_explosion_fraction",
        "magic_shield_hit_flash",
    ):
        assert token in transport_header
        assert token in transport_state
        assert token in vitals_authority
        assert token in incoming

    for token in (
        "struct ScopedActorSlotZeroContext",
        "kActorSlotOffset",
        "original_slot",
        "void Restore()",
        "restored_slot == original_slot",
    ):
        assert token in actor_slot_context, (
            f"remote damage cannot establish an exact stock slot context: {token}"
        )

    _require_in_order(
        damage_authority_hook,
        "HookPlayerActorMagicDamage(",
        "TryPrepareRemoteMagicShieldDamageAuthority(",
        "ScopedGameplayPlayerActorSlotContext",
        "ScopedActorSlotZeroContext",
        "original(self)",
        "PublishRemoteMagicShieldDamageAuthority(",
    )
    publish_authority = damage_authority_hook[
        damage_authority_hook.index(
            "bool PublishRemoteMagicShieldDamageAuthority("
        ):
        damage_authority_hook.index(
            "HookPlayerActorMagicDamage("
        )
    ]
    _require_in_order(
        publish_authority,
        "QueueHostParticipantVitalsCorrection(",
        "ParticipantVitalsCorrectionFlagMagicShieldState",
    )
    for token in (
        "multiplayer::IsLocalTransportHost()",
        "FindParticipantEntityForActor(actor_address)",
        "IsNativeRemoteParticipantBinding(binding)",
        "native_remote_magic_shield_authority_pending = true",
        "replicated_magic_shield_absorb_remaining",
        "replicated_magic_shield_absorb_capacity",
        "transient_status_flags",
        "poison_remaining_ticks",
        "webbed_remaining_ticks",
    ):
        assert token in damage_authority_hook, (
            f"remote shield damage is not captured at the native transaction: {token}"
        )
    assert "native_magic_shield_observed" not in native_remote_vitals, (
        "shield authority must not be inferred later from a playback field"
    )
    for token in (
        "native_remote_magic_shield_authority_pending",
        "authoritative_magic_shield_matches_runtime",
    ):
        assert token in native_remote_playback, (
            f"stale owner frames can overwrite the immediate shield result: {token}"
        )
    for token in (
        "correction_magic_shield",
        "normalized.magic_shield_absorb_remaining =",
        "normalized.magic_shield_absorb_capacity =",
        "normalized.magic_shield_explosion_fraction =",
        "normalized.magic_shield_hit_flash =",
    ):
        assert token in incoming, (
            f"stale owner frames can overwrite shield authority: {token}"
        )

    assert "struct PendingLocalPlayerVitalsCorrection" in request_state
    assert "QueueLocalPlayerVitalsCorrection(" in action_queue
    for token in (
        "ApplyLocalPlayerMagicShieldCorrection(",
        "kActorMagicShieldAbsorbRemainingOffset",
        "kActorMagicShieldAbsorbCapacityOffset",
        "kActorMagicShieldExplosionFractionOffset",
        "kActorMagicShieldHitFlashOffset",
        "ConfirmLocalParticipantVitalsCorrection(",
    ):
        assert token in action_executor, (
            f"owner cannot apply and acknowledge native shield state: {token}"
        )

    for token in (
        "target_participant_id",
        "FindParticipantEntity(request.target_participant_id)",
    ):
        assert token in native_probe, (
            f"native hit probe cannot exercise the host mirror: {token}"
        )
    assert "luaL_optinteger(state, 4, 0)" in lua_probe
    assert "target_participant_id: int = 0" in defense_harness
    assert "target_participant_id" in defense_harness

    client_branch = secondary_harness[
        secondary_harness.index("def invoke_authoritative_magic_shield_hit("):
        secondary_harness.index("\ndef run_magic_shield(")
    ]
    _require_in_order(
        client_branch,
        "direction.source_pipe == HOST_ENDPOINT",
        "observer_endpoint(direction)",
        "target_participant_id = direction.source_id",
        "target_participant_id=target_participant_id",
    )
    assert secondary_harness.count(
        "invoke_authoritative_magic_shield_hit("
    ) == 3

    return (
        "host-side native hits consume a client owner's Magic Shield, hold "
        "the corrected charge against stale owner frames, and acknowledge "
        "only after the client writes the native shield state"
    )
