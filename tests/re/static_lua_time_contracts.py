"""Contracts for authority-owned shared Lua simulation time."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_time_is_authority_owned_replicated_and_coherently_gated() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_time.cpp")
    runtime_header = _read("SolomonDarkModLoader/include/lua_time_runtime.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    binding_registry = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    time_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_time_control_sync.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_participant_state_sync.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_dispatch.inl"
    )
    transport_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    actor_world = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "actor_world_pause_hook.inl"
    )
    player_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    wave_tick = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "wave_spawn_filter.inl"
    )
    run_reset = _read(
        "SolomonDarkModLoader/src/run_lifecycle/enemy_tracking_and_reset.inl"
    )
    documentation = _read("docs/lua-time.md")
    timing_re = _read("docs/reverse-engineering/game-timing-scale.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_time_lab/manifest.json")
    sample = _read("mods/lua_time_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_time.py")
    multiplayer_verifier = _read("tools/verify_lua_time_multiplayer.py")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")

    for item in (
        "include\\lua_time_runtime.h",
        "src\\lua_engine_bindings_time.cpp",
        "src\\multiplayer_local_transport\\lua_time_control_sync.inl",
    ):
        assert item in project, f"Lua time project item lacks: {item}"

    for token in (
        'RegisterFunction(state, &LuaTimeGetScale, "get_scale")',
        'RegisterFunction(state, &LuaTimeGetState, "get_state")',
        'RegisterFunction(state, &LuaTimeSetScale, "set_scale")',
        'RegisterFunction(state, &LuaTimeStep, "step")',
        "IsLuaModSimulationAuthority()",
        "scale < 0.0 || scale > 1.0",
        "HasActiveLuaTimeRun()",
        "SetLuaTimeScaleRequest(",
        "QueueLuaTimeStepFrames(",
        "ClearLuaTimeScaleRequest",
        "effective = (std::min)(effective, requested)",
    ):
        assert token in bindings, f"Lua time bindings/runtime lack: {token}"
    assert "RegisterLuaTimeBindings(mod->state);" in binding_registry
    for capability in ('"time.shared.scale"', '"time.shared.frame_step"'):
        assert capability in engine
    assert "ClearLuaTimeScaleRequest(mod->descriptor.id);" in engine

    for token in (
        "kLuaTimeScaleUnitsPerOne = 1'000'000",
        "kLuaTimeMaximumStepFrames = 120",
        "kLuaTimeMaximumControllingMods = 64",
        "unsent_step_frames",
        "BeginLuaTimeSimulationFrame",
        "ShouldHoldLuaTimeSimulationFrame",
    ):
        assert token in runtime_header, f"Lua time bounds lack: {token}"
    for token in (
        "PendingStepFramesLocked() + frame_count",
        "g_lua_time.frame_accumulator += g_lua_time.scale_units",
        "++g_lua_time.consumed_step_sequence",
        "g_lua_time_frame_scope_depth",
        "step_sequence <= g_lua_time.step_sequence",
    ):
        assert token in bindings, f"Lua time scheduler lacks: {token}"

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 81;",
        "LuaTimeControl = 27",
        "struct LuaTimeControlPacket",
        "authority_session_nonce",
        "lua_time_scale_units",
        "lua_time_revision",
        "LuaTimeControlPacketFlagStepFrames",
        "sizeof(LuaTimeControlPacket) == 56",
        "sizeof(StatePacket) == 5040",
        "sizeof(ParticipantFramePacket) == 570",
    ):
        assert token in protocol, f"Lua time protocol lacks: {token}"
    assert 'lua_time_control_sync.inl"' in transport

    for token in (
        "PopulateLuaTimeControlPacketFieldsImpl",
        "ApplyAuthoritativeLuaTimeControlSnapshot",
        "IsAuthorizedLuaTimeControlPacket",
        "IsConfiguredRemoteAuthorityEndpoint(from)",
        "nonce->second == packet.authority_session_nonce",
        "ApplyLuaTimeControlPacket",
        "SendLuaTimeControlUpdate",
        "SteamNetworkSendMode::ReliableNoNagle",
        "MarkLuaTimeControlUpdateSent",
    ):
        assert token in time_sync, f"Lua time transport lacks: {token}"
    assert incoming.count("ApplyAuthoritativeLuaTimeControlSnapshot(") == 2
    for token in (
        "kind == PacketKind::LuaTimeControl",
        "IsValidLuaTimeControlPacket(packet)",
        "ApplyLuaTimeControlPacket(packet, from)",
    ):
        assert token in dispatch, f"Lua time dispatch lacks: {token}"
    _require_in_order(
        transport_api,
        "SendLuaTimeControlUpdate();",
        "SendLocalState(now_ms);",
        "SendLocalParticipantFrame(now_ms);",
    )

    for token in (
        "ScopedGameplaySimulationFrame",
        "BeginGameplaySimulationFrame()",
        "EndGameplaySimulationFrame()",
        "if (frame.should_advance)",
    ):
        assert token in actor_world, f"coherent actor-world gate lacks: {token}"
    _require_in_order(
        actor_world,
        "BeginGameplaySimulationFrame()",
        "if (frame.should_advance)",
        "original(self, unused_edx);",
        "actor_tick(actor);",
    )
    for source in (player_tick, wave_tick):
        assert "ShouldPauseMultiplayerGameplay()" in source
    for token in (
        "ShouldPauseMultiplayerGameplayWithoutLuaTime()",
        "BeginLuaTimeSimulationFrame(",
        "ShouldHoldLuaTimeSimulationFrame()",
    ):
        assert token in transport_api, f"composed pause predicate lacks: {token}"
    assert "ResetLuaTimeControlForRun();" in run_reset

    for token in (
        "## Multiplayer contract",
        "fixed-point",
        "minimum active",
        "take precedence",
        "Protocol 80",
        "reliable no-Nagle",
        "kGameTimingScaleGlobal",
        "cannot synthesize extra",
    ):
        assert token in documentation, f"Lua time docs lack: {token}"
    assert "gates coherent world frames" in timing_re
    assert "**Implemented 2026-07-23.** `sd.time`" in roadmap
    for token in (
        '"id": "sample.lua.time_lab"',
        '"enabled": false',
        '"time.shared.scale"',
        '"time.shared.frame_step"',
    ):
        assert token in manifest, f"Lua time sample manifest lacks: {token}"
    for token in (
        "sd.time.set_scale",
        "sd.time.step",
        "sd.time.get_state",
    ):
        assert token in sample, f"Lua time sample lacks: {token}"
    for token in (
        'sd.runtime.has_capability("time.shared.scale")',
        "slow_motion_valid",
        "pause_valid",
        "step_valid",
        "pcall(sd.time.set_scale, 1)",
    ):
        assert token in verifier, f"Lua time verifier lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.time_lab"',
        "CLIENT_MUTATION_REJECTION",
        "_set_scale_probe(0.5)",
        "_set_scale_probe(0.0)",
        "step_sequence != pause_step_sequence + 3",
        "_set_scale_probe(1.0)",
        "start_host_testrun_and_wait_for_clients(",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "two exact process IDs",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua time multiplayer verifier lacks: {token}"
        )
    normalized_documentation = " ".join(documentation.split())
    for token in (
        "verify_lua_time_multiplayer.py --launch-pair",
        "client mutation is rejected",
        "exact authority",
        "cumulative step sequence",
        "stops only the exact processes",
    ):
        assert token in normalized_documentation, (
            f"Lua time multiplayer acceptance docs lack: {token}"
        )
    assert '"time": (' in runtime_verifier

    return (
        "sd.time gates coherent fixed-point simulation frames, composes with "
        "shared pauses, and has exact two-peer authority/replication acceptance"
    )
