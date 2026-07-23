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
    multiplayer_verifier = _read("tools/verify_lua_waves_multiplayer.py")
    multiplayer_verifier_tests = _read(
        "tests/test_lua_waves_multiplayer_verifier.py"
    )
    manifest = _read("mods/lua_waves_lab/manifest.json")
    sample = _read("mods/lua_waves_lab/scripts/main.lua")
    fixture = _read("tests/fixtures/waves/lua_wave_filter_test.txt")
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

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
        "constexpr std::uint16_t kProtocolVersion = 81;",
        "WaveCompositionRowPacketState",
        "wave_summary_remaining_to_spawn",
        "wave_summary_rows[kWaveSummaryMaxCompositionRows]",
        "static_assert(sizeof(ParticipantFramePacket) == 586",
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
        "current protocol version is 81",
        "verify_lua_waves_multiplayer.py --launch-pair --confirm-mutation",
        "same sorted aggregate and per-type live summary",
        "stops only the two process IDs",
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
    for token in (
        '"id": "sample.lua.waves_lab"',
        '"enabled": false',
        '"waves.read"',
        '"waves.schedule.read"',
    ):
        assert token in manifest, f"Lua waves sample manifest lacks: {token}"
    for token in (
        'sd.events.on("wave.started"',
        'sd.runtime.has_capability("waves.read")',
        'sd.runtime.has_capability("waves.schedule.read")',
    ):
        assert token in sample, f"Lua waves sample lacks: {token}"
    for token in ("SPAWN:2", "SPAWN:3"):
        assert token in fixture, f"Lua waves acceptance fixture lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.waves_lab"',
        "WAVE_OVERRIDE",
        "schedule_signature",
        "event_composition_signature",
        "active_wave_matches",
        "--confirm-mutation",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua waves multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_schedule_requires_exact_controlled_projection",
        "test_active_wave_requires_event_and_exact_composition",
        "test_mutation_confirmation_is_required_before_contact",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_run_stages_exact_mod_and_stops_only_launched_pair",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua waves multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_waves_multiplayer_verifier"
        in workflow
    )

    return (
        "sd.waves parses the effective schedule, attributes authority births and "
        "deaths, and has exact two-peer authenticated summary acceptance"
    )
