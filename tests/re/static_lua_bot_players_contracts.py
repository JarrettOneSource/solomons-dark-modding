"""Contracts for host-owned synthetic multiplayer participants."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_bots_are_synthetic_remote_participants() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    runtime_lifecycle = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/lifecycle_api.inl"
    )
    entity_lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_registry_and_movement_participant_lifecycle.inl"
    )
    materialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "standalone_materialization_slot_bot_creation.inl"
    )
    materialization += _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/"
        "spawn_gameplay_slot_bot.inl"
    )
    participant_kinds = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "participant_kind_helpers.inl"
    )
    state_writer = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    state_reader = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_participant_state_sync.inl"
    )
    state_sender = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_packet_sync.inl"
    )
    cast_ingress = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_cast_packet_sync.inl"
    )
    synthetic_cast = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "synthetic_participant_cast_sync.inl"
    )
    lua_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp"
    )
    steam_members = "\n".join(
        (
            _read("SolomonDarkModLoader/src/multiplayer_steam_session.cpp"),
            _read(
                "SolomonDarkModLoader/src/multiplayer_steam_session/"
                "lobby_and_events.inl"
            ),
        )
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 86;",
        "enum ParticipantStateFlag",
        "ParticipantStateFlagRetired",
        "std::uint8_t participant_state_flags;",
        "static_assert(sizeof(StatePacket) == 653",
    ):
        assert token in protocol, f"synthetic participant wire contract lacks: {token}"

    for token in (
        "RegisterSyntheticParticipantTransport(",
        "RetireSyntheticParticipantTransport(",
        "QueueSyntheticParticipantCast(",
    ):
        assert token in transport_header, f"synthetic transport API lacks: {token}"
    _require_in_order(
        runtime_lifecycle,
        "UpsertRemoteParticipant(",
        "ParticipantControllerKind::LuaBrain",
        "RegisterSyntheticParticipantTransport(",
        "TryDispatchEntitySync(",
    )
    _require_in_order(
        runtime_lifecycle,
        "RetireSyntheticParticipantTransport(",
        "state.participants.erase(",
        "TryDispatchDestroy(",
    )
    assert "occupied_remote_slots >= 3" in runtime_lifecycle

    for token in (
        "TrySpawnGameplaySlotBotParticipantEntity(",
        "CreateGameplaySlotBotActor(",
        "FinalizeGameplaySlotBotRegistration(",
        "All gameplay bot slots (1..3) are occupied.",
    ):
        combined = entity_lifecycle + materialization
        assert token in combined, f"ordinary remote-player materialization lacks: {token}"
    for forbidden in (
        "kLocalPlayerActorGlobal",
        "HookMonsterPathfindingRefreshTarget",
    ):
        assert forbidden not in runtime_lifecycle + materialization

    for token in (
        "IsPacketDrivenRemoteParticipantBinding(",
        "ParticipantControllerKind::Native",
        "ParticipantControllerKind::LuaBrain",
        "multiplayer::IsLocalTransportClient()",
    ):
        assert token in participant_kinds, f"packet-driven controller split lacks: {token}"

    for token in (
        "BuildSyntheticParticipantStatePacket(",
        "BuildSyntheticParticipantFramePacket(",
        "ParticipantStateFlagRetired",
        "PopulateParticipantFrameFields(",
        "PopulateParticipantStateFields(",
    ):
        assert token in state_writer, f"synthetic state authoring lacks: {token}"
    for token in (
        "IsAuthenticatedHostSyntheticParticipantPacket(",
        "IsConfiguredRemoteAuthorityEndpoint(from)",
        "ParticipantControllerKind::LuaBrain",
        "retired_session_nonces_by_participant",
        "ParticipantStateFlagRetired",
    ):
        assert token in state_reader, f"synthetic state authentication lacks: {token}"
    for token in (
        "SendSyntheticParticipantState(",
        "SteamNetworkSendMode::ReliableNoNagle",
        "kLocalTransportParticipantFrameIntervalMs",
        "kSyntheticParticipantRetirementResendIntervalMs",
    ):
        assert token in state_sender, f"synthetic state publication lacks: {token}"

    _require_in_order(
        synthetic_cast,
        "BuildSyntheticParticipantCastPacket(",
        "InjectSyntheticParticipantCastPacket(",
        "ApplyParticipantCastPacket(",
    )
    for token in (
        "locally_owned_synthetic",
        "authenticated_host_synthetic",
        "QueueBotCast(request)",
        "RelayCastPacketToPeers(packet, from);",
    ):
        assert token in cast_ingress, f"shared replicated cast ingress lacks: {token}"

    for token in (
        "&LuaBotsSpawn",
        "&LuaBotsList",
        "&LuaBotHandleDespawn",
        "&LuaBotHandleMoveTo",
        "&LuaBotHandleStop",
        "&LuaBotHandleCast",
        "&LuaBotHandlePosition",
        "&LuaBotHandleHp",
        "&LuaBotHandleMaxHp",
        "&LuaBotHandleAlive",
        "&LuaBotHandleSlot",
        "&LuaBotHandleParticipantId",
        '"spawn"',
        '"list"',
        '"despawn"',
        '"move_to"',
        '"stop"',
        '"cast"',
        '"position"',
        '"hp"',
        '"max_hp"',
        '"alive"',
        '"slot"',
        '"participant_id"',
        "only the multiplayer host can control bots",
    ):
        assert token in lua_bindings, f"sd.bots handle API lacks: {token}"

    for token in (
        "participant_id",
        "gameplay_slot",
        "is_synthetic",
        "IsLuaControlledParticipant(participant)",
    ):
        assert token in steam_members, f"synthetic member status lacks: {token}"

    return (
        "Lua bots register as host-owned synthetic remote participants, use the "
        "ordinary slot actor and authenticated State/Frame/Cast rails, and "
        "retire through a reliable participant tombstone"
    )
