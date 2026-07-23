"""Contracts for the multiplayer-native Lua state and custom-event seam."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, read_source_unit


def test_lua_mod_state_and_events_are_authority_replicated() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport = "\n".join(
        _read(path)
        for path in (
            "SolomonDarkModLoader/src/multiplayer_local_transport.cpp",
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "lua_mod_stream_codec.inl",
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "lua_mod_stream_sync.inl",
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "lua_mod_stream_public.inl",
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "incoming_packet_dispatch.inl",
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "public_cast_loot_api.inl",
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "remote_peer_lifecycle.inl",
        )
    )
    value_contract = _read("SolomonDarkModLoader/include/lua_mod_runtime.h")
    value_codec = _read("SolomonDarkModLoader/src/lua_mod_runtime.cpp")
    state_store = _read("SolomonDarkModLoader/src/lua_mod_state_store.cpp")
    lua_values = _read("SolomonDarkModLoader/src/lua_engine_values.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_state.cpp")
    binding_root = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    runtime_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime/"
        "level_up_and_runtime_api.inl"
    )
    events = "\n".join(
        (
            read_source_unit("SolomonDarkModLoader/src/lua_engine_events.cpp"),
            _read("SolomonDarkModLoader/src/lua_engine_custom_events.cpp"),
        )
    )
    live_verifier = _read("tools/verify_lua_mod_replication.py")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")
    multiplayer_verifier = _read("tools/verify_local_multiplayer_sync.py")
    pair_launcher = _read("scripts/Launch-LocalMultiplayerPair.ps1")
    additional_client_launcher = _read(
        "scripts/Launch-LocalMultiplayerAdditionalClient.ps1"
    )
    launcher_process_helpers = _read(
        "scripts/LocalMultiplayerLauncher.Process.ps1"
    )
    compatibility = _read(
        "SolomonDarkModLauncher/src/Staging/"
        "MultiplayerCompatibilityMaterializer.cs"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    documentation = _read("docs/lua-state-and-events.md")

    for token in (
        "kLuaModMaxStringBytes = 16 * 1024",
        "kLuaModMaxValueBytes = 32 * 1024",
        "kLuaModMaxStateSnapshotBytes = 64 * 1024",
        "kLuaModMaxValueDepth = 16",
        "kLuaModMaxValueNodes = 2048",
        "EncodeLuaModValue(",
        "DecodeLuaModValue(",
        "EncodeLuaModStateSnapshot(",
        "DecodeLuaModStateSnapshot(",
    ):
        assert token in value_contract + value_codec, (
            f"bounded deterministic Lua value contract lacks: {token}"
        )
    for token in (
        "Lua values cannot contain table cycles",
        "Lua values cannot contain mixed array/object tables",
        "Lua arrays must be dense and one-indexed",
        "Lua value exceeds the maximum node count",
    ):
        assert token in lua_values, f"Lua value conversion lacks: {token}"

    for token in (
        "SetLuaModStateValue(",
        "DeleteLuaModStateValue(",
        "ClearLuaModStateValues(",
        "ApplyReplicatedLuaModStateSnapshot(",
        "revision <= g_lua_mod_state.revision",
        "std::mutex g_lua_mod_state_mutex",
        "ContainsNilValue(",
    ):
        assert token in state_store, f"Lua state store lacks: {token}"

    for token in (
        'RegisterFunction(state, &LuaStateGet, "get")',
        'RegisterFunction(state, &LuaStateSet, "set")',
        'RegisterFunction(state, &LuaStateDelete, "delete")',
        'RegisterFunction(state, &LuaStateClear, "clear")',
        'RegisterFunction(state, &LuaStateSnapshot, "snapshot")',
        'RegisterFunction(state, &LuaStateGetRevision, "get_revision")',
        'RegisterFunction(state, &LuaStateIsAuthority, "is_authority")',
        'RegisterFunction(state, &LuaEventsBroadcast, "broadcast")',
        "RequireSimulationAuthority",
    ):
        assert token in bindings, f"Lua state/event binding lacks: {token}"
    assert "RegisterLuaStateBindings(mod->state);" in binding_root
    assert "RegisterLuaEventBroadcastBinding(state);" in runtime_bindings
    for token in (
        "CustomEvent",
        "DispatchLuaCustomEvent(",
        "DispatchCustomEventToLuaMods(",
        "stream_sequence",
    ):
        assert token in events, f"custom Lua event dispatch lacks: {token}"

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 81;",
        "LuaModStream = 21",
        "enum class LuaModStreamMessageKind",
        "struct LuaModStreamPacket",
        "kLuaModStreamFragmentPayloadBytes = 1024",
        "kLuaModStreamMaxFragments = 64",
        "IsValidLuaModStreamPacketWireSize(",
    ):
        assert token in protocol, f"Lua mod wire protocol lacks: {token}"
    assert "CurrentProtocolVersion = 81;" in compatibility
    for capability in (
        '"state.replicated.read"',
        '"state.replicated.write"',
        '"events.replicated.broadcast"',
    ):
        assert capability in engine, f"Lua capability set lacks: {capability}"

    for token in (
        "bool IsLuaModSimulationAuthority();",
        "PublishAuthoritativeLuaModStateSet(",
        "PublishAuthoritativeLuaModStateDelete(",
        "PublishAuthoritativeLuaModStateClear(",
        "PublishAuthoritativeLuaModEvent(",
    ):
        assert token in transport_header, f"Lua transport API lacks: {token}"
    for token in (
        "SteamNetworkSendMode::ReliableNoNagle",
        "SendLuaModStreamMessageToEndpoint(",
        "ApplyLuaModStreamPacket(",
        "pending_lua_mod_stream_assemblies",
        "completed_lua_mod_stream_messages",
        "last_lua_mod_stream_applied_sequence + 1",
        "IsConfiguredRemoteAuthorityEndpoint(from)",
        "SendLuaModStateCheckpointToEndpoint(",
        "lua_mod_checkpointed_participants",
        "latest_stream_sequence",
        "checkpoint_covers_message",
        "ApplyReplicatedLuaModStateSnapshot(",
        "DispatchLuaCustomEvent(",
    ):
        assert token in transport, f"Lua stream transport lacks: {token}"

    for token in (
        "REGISTER_HANDLER",
        "PUBLISH",
        "READ_CONVERGENCE",
        "event_state_tokens",
        "launch_additional_client(",
        "READ_LATE_JOIN",
        "late_join_checkpoint",
    ):
        assert token in live_verifier, f"live Lua replication verifier lacks: {token}"
    for verifier_name, verifier in (
        ("replication", live_verifier),
        ("runtime", runtime_verifier),
    ):
        assert "tile_windows=False" in verifier, (
            f"{verifier_name} verifier may rearrange active desktop windows"
        )
        assert "kill_existing=False" in verifier, (
            f"{verifier_name} verifier does not preserve existing game processes"
        )
        assert "stop_game_processes(" in verifier, (
            f"{verifier_name} verifier does not clean up its exact process IDs"
        )
        assert 'ACCEPTANCE_MOD_ID = "sample.lua.authoring_lab"' in verifier, (
            f"{verifier_name} verifier does not declare its exact Lua mod"
        )
        assert "exact_mod_id=ACCEPTANCE_MOD_ID" in verifier, (
            f"{verifier_name} verifier does not stage its exact Lua mod"
        )
        assert "two exact process IDs" in verifier, (
            f"{verifier_name} verifier accepts an incomplete process ledger"
        )
        assert "stop_games(" not in verifier, (
            f"{verifier_name} verifier still uses machine-wide game cleanup"
        )
    for token in (
        "game_process_ids(",
        "stop_game_processes(",
        '"-NoKill"',
        '"-ProcessIdOutputPath"',
        "_read_process_id_ledger(",
    ):
        assert token in multiplayer_verifier, (
            f"local multiplayer verifier lacks isolated cleanup support: {token}"
        )
    for launcher_name, launcher in (
        ("pair", pair_launcher),
        ("additional-client", additional_client_launcher),
    ):
        assert "$ProcessIdOutputPath" in launcher, (
            f"{launcher_name} launcher does not publish exact game process IDs"
        )
        assert "[System.IO.File]::WriteAllText(" in launcher, (
            f"{launcher_name} launcher does not persist process IDs immediately"
        )
        assert "$ExactModIds" in launcher, (
            f"{launcher_name} launcher does not accept exact verifier mods"
        )
        assert "Set-ExactMultiplayerModState" in launcher, (
            f"{launcher_name} launcher does not isolate its enabled mod set"
        )
    for token in (
        "function Set-ExactMultiplayerModState",
        '"runtime\\instances"',
        '"mod-manager-state.json"',
        "foreach ($ModId in $ModIds)",
        "$mods[$ModId]",
        "ConvertTo-Json -Depth 4",
    ):
        assert token in launcher_process_helpers, (
            f"exact multiplayer mod-state helper lacks: {token}"
        )

    for token in (
        "## Authority model",
        "## `sd.state`",
        "## `sd.events.broadcast`",
        "## Value model and limits",
        "## Network behavior",
        "Events are transient",
        "Authority migration remains intentionally out of scope",
    ):
        assert token in documentation, f"Lua state/event documentation lacks: {token}"

    return (
        "Lua mod values are bounded and deterministic; authority mutations and "
        "custom events use a reliable ordered fragmented stream with late-join "
        "state checkpoints and live acceptance coverage"
    )
