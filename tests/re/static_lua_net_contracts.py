"""Contracts for bounded authenticated raw Lua participant messaging."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_net_is_fragmented_authenticated_and_host_relayed() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_net.cpp")
    runtime_header = _read("SolomonDarkModLoader/include/lua_net_runtime.h")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    binding_registry = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    pump = _read("SolomonDarkModLoader/src/lua_engine_main_thread_pump.inl")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    codec = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_net_message_codec.inl"
    )
    sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_net_message_sync.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_dispatch.inl"
    )
    shutdown = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    configuration = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "skill_config_and_packet_helpers.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "remote_peer_lifecycle.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-net.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_net_lab/manifest.json")
    sample = _read("mods/lua_net_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_net.py")
    multiplayer_verifier = _read("tools/verify_lua_net_multiplayer.py")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")

    for item in (
        "include\\lua_net_runtime.h",
        "src\\lua_engine_bindings_net.cpp",
        "src\\multiplayer_local_transport\\lua_net_message_codec.inl",
        "src\\multiplayer_local_transport\\lua_net_message_sync.inl",
    ):
        assert item in project, f"Lua net project item lacks: {item}"

    for token in (
        'RegisterFunction(state, &LuaNetSend, "send")',
        'RegisterFunction(state, &LuaNetBroadcast, "broadcast")',
        'RegisterFunction(state, &LuaNetOn, "on")',
        'RegisterFunction(state, &LuaNetOff, "off")',
        'RegisterFunction(state, &LuaNetGetLimits, "get_limits")',
        "luaL_checklstring",
        "luaL_ref(state, LUA_REGISTRYINDEX)",
        "luaL_unref(state, LUA_REGISTRYINDEX",
        "QueueLuaNetMessage(",
        "QueueLuaNetMessageDelivery(",
        "lua_pcall(mod->state, 2, 0, 0)",
    ):
        assert token in bindings, f"Lua net bindings lack: {token}"
    assert "RegisterLuaNetBindings(mod->state);" in binding_registry

    for token in (
        "kLuaNetMaximumChannelBytes = 64",
        "kLuaNetMaximumPayloadBytes = 60 * 1024",
        "kLuaNetMaximumSubscriptionsPerMod = 64",
        "kLuaNetMaximumQueuedMessages = 16",
        "kLuaNetMaximumQueuedBytes = 256 * 1024",
        "kLuaNetMaximumPendingDeliveries = 64",
        "kLuaNetMaximumPendingDeliveryBytes = 512 * 1024",
        "struct LuaNetMessage",
    ):
        assert token in runtime_header, f"Lua net bounds lack: {token}"
    for token in (
        "struct LuaNetSubscription",
        "std::vector<LuaNetSubscription> net_subscriptions",
        "next_net_subscription_id",
        "ClearLuaNetSubscriptionsForMod",
    ):
        assert token in internal, f"Lua net callback ownership lacks: {token}"
    _require_in_order(
        engine,
        "ClearLuaNetSubscriptionsForMod(mod);",
        "lua_close(mod->state)",
    )
    for capability in (
        '"net.raw.fragmented"',
        '"net.participant.unicast"',
        '"net.participant.broadcast"',
    ):
        assert capability in engine
    assert pump.count("detail::DispatchPendingLuaNetMessages();") == 2

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 81;",
        "LuaNetMessage = 26",
        "struct LuaNetMessagePacket",
        "transport_participant_id",
        "source_participant_id",
        "source_session_nonce",
        "target_participant_id",
        "message_sequence",
        "kLuaNetMessagePacketPrefixBytes == 64",
        "sizeof(LuaNetMessagePacket) == 1088",
        "IsValidLuaNetMessagePacketWireSize(",
    ):
        assert token in protocol, f"Lua net protocol lacks: {token}"
    assert 'lua_net_message_sync.inl"' in transport

    for token in (
        "kLuaNetEnvelopeVersion = 1",
        "kLuaNetMaxPendingAssemblies = 32",
        "kLuaNetMaxPendingAssemblyBytes = 512 * 1024",
        "kLuaNetMaxRememberedSequencesPerParticipant = 256",
        "EncodeLuaNetEnvelope(",
        "DecodeLuaNetEnvelope(",
        "SendBufferToEndpoint(",
        "SteamNetworkSendMode::ReliableNoNagle",
        "packet.transport_participant_id = g_local_transport.local_peer_id",
        "packet.source_participant_id = message.source_participant_id",
        "SameEndpoint(candidate.endpoint, from)",
        "packet.transport_participant_id == packet.source_participant_id",
        "nonce->second == packet.source_session_nonce",
        "RememberLuaNetSequence(",
        "QueueOutboundLuaNetMessage(std::move(message)",
        "message.target_participant_id == g_local_transport.local_peer_id",
        "PruneLuaNetAssemblies(now_ms)",
    ):
        assert token in transport + codec + sync, f"Lua net transport lacks: {token}"
    assert sync.count("kLuaNetMaximumQueuedMessages") >= 3
    assert sync.count("kLuaNetMaximumQueuedBytes") >= 3

    for token in (
        "SteamLuaNetPacketHopMatches(",
        "packet.transport_participant_id == sender_steam_id",
        "case PacketKind::LuaNetMessage:",
        "ApplyLuaNetMessagePacket(packet, from, now_ms);",
    ):
        assert token in dispatch, f"Lua net authenticated dispatch lacks: {token}"
    assert "SendQueuedLuaNetMessages();" in shutdown
    for reset_source in (shutdown, configuration):
        for token in (
            "g_queued_lua_net_messages.clear()",
            "g_next_lua_net_message_sequence = 1",
            "g_queued_lua_net_message_bytes = 0",
        ):
            assert token in reset_source, f"Lua net reset lacks: {token}"
    assert "ClearLuaNetParticipantTransportState(" in lifecycle

    for token in (
        "## API",
        "## Topology and authentication",
        "## Bounds",
        "binary-safe",
        "does not make the",
        "payload trusted game authority",
        "Steam fragments use reliable",
        "local UDP backend",
        "Protocol 81",
    ):
        assert token in documentation, f"Lua net docs lack: {token}"
    assert "**Implemented 2026-07-23.** `sd.net.send" in roadmap
    for token in (
        '"id": "sample.lua.net_lab"',
        '"enabled": false',
        '"net.raw.fragmented"',
        '"net.participant.unicast"',
        '"net.participant.broadcast"',
    ):
        assert token in manifest, f"Lua net sample manifest lacks: {token}"
    for token in (
        "sd.net.on",
        "sd.net.broadcast",
        "sd.net.send",
        "sd.net.get_limits",
    ):
        assert token in sample, f"Lua net sample lacks: {token}"
    for token in (
        'sd.runtime.has_capability("net.raw.fragmented")',
        "bad_channel_rejected",
        "oversized_rejected",
        "offline_unicast_rejected",
        "callback_valid",
        "subscription_lifetime_valid",
    ):
        assert token in verifier, f"Lua net verifier lacks: {token}"
    for token in (
        "HOST_PUBLISH",
        "CLIENT_PUBLISH",
        "payload_bytes=2050",
        "payload_bytes=2562",
        "payload_bytes=3074",
        "payload_bytes=4098",
        "sender=HOST_ID",
        "sender=CLIENT_ID",
        "target=HOST_ID",
        "target=CLIENT_ID",
        "broadcast=True",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "two exact process IDs",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua net multiplayer verifier lacks: {token}"
        )
    for token in (
        "verify_lua_net_multiplayer.py --launch-pair",
        "fragmented binary unicast",
        "target, sequence, broadcast flag",
        "cleans up only the exact process IDs",
    ):
        assert token in documentation, (
            f"Lua net multiplayer acceptance docs lack: {token}"
        )
    assert '"net": (' in runtime_verifier

    return (
        "sd.net carries bounded binary participant messages through an "
        "authenticated host relay, with exact two-peer fragmented live acceptance, "
        "and dispatches them only on the Lua game thread"
    )
