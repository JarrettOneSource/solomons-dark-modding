"""Contracts for authority-replicated semantic Lua wave intelligence."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_waves_parse_track_and_replicate_semantic_summaries() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    wave_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_waves.cpp"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    intelligence = _read("SolomonDarkModLoader/src/wave_intelligence.cpp")
    lifecycle = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "wave_spawn_filter.inl"
    )
    spawn_hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "wave_and_enemy_spawn_hooks.inl"
    )
    death_hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "enemy_death_reward_level_up_hooks.inl"
    )
    run_hooks = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "run_transition_hooks.inl"
    )
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    wave_events = _read("SolomonDarkModLoader/src/lua_engine_wave_events.cpp")
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_participant_state_sync.inl"
    )
    wave_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "wave_summary_sync.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-waves.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_waves.py")

    assert "RegisterLuaWaveBindings(mod->state)" in bindings
    assert "lua_engine_bindings_waves.cpp" in project
    assert "wave_intelligence.cpp" in project
    for capability in ('"waves.read"', '"waves.schedule.read"'):
        assert capability in engine
    for token in (
        'RegisterFunction(state, &LuaWavesGetState, "get_state")',
        'RegisterFunction(state, &LuaWavesGetSchedule, "get_schedule")',
        'lua_setfield(state, -2, "waves")',
        'lua_setfield(state, -2, "remaining_to_spawn")',
        'lua_setfield(state, -2, "composition")',
    ):
        assert token in wave_bindings, f"Lua wave binding lacks: {token}"
    for raw_field in (
        "spawner_address",
        "action_record_address",
        "arena_address",
    ):
        assert raw_field not in wave_bindings

    for token in (
        'stage_root / "data" / "wave.txt"',
        'StartsWithDirective(line, "SPAWN")',
        'line == "GROUP" || line == "FORMATION"',
        'line == "ZOMBIEWAVE"',
        "ProjectComposition(",
        "numerator % configured_total",
        "left.enemy_type < right.enemy_type",
        "wave_by_spawner_identity",
        "ObserveAuthorityWaveSpawner",
        "ObserveAuthorityWaveEnemySpawn",
        "ObserveAuthorityWaveEnemyDeath",
        "ApplyReplicatedWaveSummary",
    ):
        assert token in intelligence, f"wave intelligence lacks: {token}"

    _require_in_order(
        lifecycle,
        "PrepareLuaWaveSpawnFilter(",
        "ObserveAuthorityWaveSpawner(",
        "original(self, unused_edx)",
        "ObserveAuthorityWaveSpawner(",
    )
    assert "g_current_wave_number" in lifecycle
    assert "ObserveAuthorityWaveEnemySpawn(" in spawn_hook
    assert "ObserveAuthorityWaveEnemyDeath(" in death_hook
    assert "DispatchLuaWaveCompleted(" in death_hook
    assert run_hooks.count("ResetWaveIntelligenceRun();") == 2
    for token in (
        "PushWaveStartedPayload",
        'lua_setfield(state, -2, "planned")',
        'lua_setfield(state, -2, "composition")',
    ):
        assert token in wave_events, f"wave.started payload lacks: {token}"
    assert "DispatchWaveStartedToMod" in events

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 77;",
        "WaveCompositionRowPacketState",
        "wave_summary_remaining_to_spawn",
        "wave_summary_rows[kWaveSummaryMaxCompositionRows]",
        "static_assert(sizeof(ParticipantFramePacket) == 562",
    ):
        assert token in protocol, f"wave packet contract lacks: {token}"
    assert "PopulateAuthorityWaveSummary(&packet)" in outgoing
    assert "!g_local_transport.is_host" in wave_sync
    for token in (
        "packet_from_configured_authority",
        "packet.wave_summary_row_count > kWaveSummaryMaxCompositionRows",
        "source.enemy_type <= previous_enemy_type",
        "rows_spawned != summary.spawned",
        "ApplyReplicatedWaveSummary(summary)",
    ):
        assert token in wave_sync, f"replicated wave validation lacks: {token}"
    _require_in_order(
        wave_sync,
        "packet_from_configured_authority",
        "ApplyReplicatedWaveSummary(summary)",
    )

    for token in (
        "deterministic largest-remainder",
        "authenticated participant frame",
        "same authority summary on host and clients",
        "waves.schedule.read",
        "protocol version is 77",
    ):
        assert token in documentation, f"Lua wave documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.waves.get_state()`" in roadmap
    for token in (
        "sd.waves.get_state",
        "sd.waves.get_schedule",
        "schedule_valid",
        "raw_addresses_absent",
    ):
        assert token in verifier, f"Lua wave verifier lacks: {token}"

    return (
        "sd.waves parses the effective schedule, attributes authority births and "
        "deaths, and accepts bounded summaries only from the authenticated host"
    )
