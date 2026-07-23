"""Contracts for deterministic authority-owned Lua enemy spawning."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_enemies_use_exact_stock_spawn_and_replicated_content_identity() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_enemies.cpp")
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    public_api = _read("SolomonDarkModLoader/include/mod_loader_gameplay_api.inl")
    state = _read("SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl")
    tracking = _read(
        "SolomonDarkModLoader/src/run_lifecycle/enemy_tracking_and_reset.inl"
    )
    queue = "\n".join(
        (
            _read("SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"),
            _read("SolomonDarkModLoader/src/run_lifecycle/lua_enemy_spawn_api.inl"),
        )
    )
    exact_spawn = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/manual_enemy_spawning.inl"
    )
    spawn_hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/wave_and_enemy_spawn_hooks.inl"
    )
    drop_hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/drop_roll_filter.inl"
    )
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_snapshot_packet_builders.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_snapshot_packet_sync.inl"
    )
    materialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/world_snapshot_reconciliation/"
        "run_lifecycle_and_materialization.inl"
    )
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    compatibility = _read(
        "SolomonDarkModLauncher/src/Staging/MultiplayerCompatibilityMaterializer.cs"
    )
    manifest = _read("mods/lua_enemies_registry_lab/manifest.json")
    sample = _read("mods/lua_enemies_registry_lab/scripts/main.lua")
    documentation = _read("docs/lua-enemies.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_enemies.py")
    spawn_verifier = _read("tools/verify_lua_enemy_spawn.py")

    assert "RegisterLuaEnemyBindings(mod->state)" in root_bindings
    assert "lua_engine_bindings_enemies.cpp" in project
    for capability in (
        '"enemies.register"',
        '"enemies.read"',
        '"enemies.spawn.authority"',
    ):
        assert capability in engine, f"enemy capability lacks: {capability}"
    for token in (
        "struct LuaEnemyDefinition",
        "LuaContentIdentity identity",
        "std::vector<LuaEnemyDefinition> enemy_definitions",
        "LuaEnemyLootPolicy loot_policy",
    ):
        assert token in internal, f"enemy registration lifecycle lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaEnemiesRegister, "register")',
        'RegisterFunction(state, &LuaEnemiesGet, "get")',
        'RegisterFunction(state, &LuaEnemiesList, "list")',
        'RegisterFunction(state, &LuaEnemiesSpawn, "spawn")',
        "RegisterLuaContentIdentityForMod(",
        "LuaContentKind::Enemy",
        "kLuaMaximumRegisteredEnemiesPerMod = 256",
        "sd.enemies.spawn may only be called by the simulation authority",
        "QueueRunLifecycleLuaEnemySpawn(",
        "definition->identity.network_id",
    ):
        assert token in bindings, f"Lua enemy binding lacks: {token}"
    for forbidden in (
        'lua_getfield(state, 1, "native_type_id")',
        'lua_getfield(state, 1, "address")',
        'lua_setfield(state, -2, "actor_address")',
        'lua_setfield(state, -2, "config_address")',
    ):
        assert forbidden not in bindings, f"enemy API exposes native identity: {forbidden}"

    for token in (
        "SDModLuaEnemySpawnConfig lua_config",
        "g_queued_run_enemy_spawns",
        "kQueuedRunEnemySpawnLimit = 16",
        "QueueRunLifecycleLuaEnemySpawn",
        "TryGetPreferredManualRunEnemySpawner",
        "IsLuaModSimulationAuthority",
    ):
        assert token in state + queue + public_api, f"enemy queue lacks: {token}"
    assert "g_state.lua_enemy_configs_by_address.erase(enemy_address)" in tracking
    for token in (
        "EmptyEnemyModifierArray no_modifiers",
        "no_modifiers.vtable = modifier_array_vtable",
        "spawn(",
        "&no_modifiers",
        "kSpawnExactEnemyGroup",
        "IsArenaCombatActorType",
    ):
        assert token in exact_spawn, f"exact stock spawn lacks: {token}"
    _require_in_order(
        exact_spawn,
        "no_modifiers.vtable = modifier_array_vtable",
        "spawn(",
        "&no_modifiers",
    )
    assert "Enemy_Create" not in exact_spawn + bindings
    for token in (
        "TryCaptureLuaEnemySpawnFilterContext",
        "ApplyLuaEnemySpawnConfigToFilterContext",
        "ApplyLuaEnemySpawnFilters",
        "WriteLuaEnemySpawnFilterConfig",
        "RestoreLuaEnemySpawnFilterConfig",
        "RememberLuaEnemySpawnConfig",
        "DispatchLuaEnemySpawned(enemy_type, x, y, spawned_content_id)",
    ):
        assert token in spawn_hook, f"registered spawn hook lacks: {token}"
    _require_in_order(
        spawn_hook,
        "ApplyLuaEnemySpawnConfigToFilterContext",
        "ApplyLuaEnemySpawnFilters",
        "WriteLuaEnemySpawnFilterConfig",
        "RestoreLuaEnemySpawnFilterConfig",
    )
    for token in (
        "LookupLuaEnemySpawnConfig",
        "SDModLuaEnemyLootPolicy::None",
        "ApplyLuaDropRollFilters",
        "LuaDropForcedKind::None",
    ):
        assert token in drop_hook, f"registered loot policy lacks: {token}"

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 77;",
        "std::uint64_t lua_content_id",
        "LuaEnemySpawnSnapshotFlagHp",
        "LuaEnemySpawnSnapshotFlagChaseSpeed",
        "LuaEnemySpawnSnapshotFlagAttackSpeed",
        "LuaEnemySpawnSnapshotFlagScale",
        "sizeof(WorldActorSnapshotPacketState) == 328",
        "sizeof(WorldSnapshotPacket) == 1032",
    ):
        assert token in protocol, f"enemy snapshot protocol lacks: {token}"
    assert "CurrentProtocolVersion = 77;" in compatibility
    for token in (
        "TryGetRunLifecycleLuaEnemySpawnConfig",
        "snapshot.lua_content_id = lua_enemy_config.content_id",
        "snapshot.lua_spawn_chase_speed",
        "snapshot.lua_spawn_attack_speed",
        "snapshot.lua_spawn_scale",
    ):
        assert token in capture, f"enemy snapshot capture lacks: {token}"
    for token in (
        "actor.lua_content_id = packet_actor.lua_content_id",
        "actor.lua_spawn_hp = packet_actor.lua_spawn_hp",
        "actor.lua_spawn_chase_speed = packet_actor.lua_spawn_chase_speed",
    ):
        assert token in incoming, f"enemy snapshot decode lacks: {token}"
    for token in (
        "lua_config.content_id = authoritative_actor.lua_content_id",
        "lua_config.chase_speed_valid",
        "lua_config.attack_speed_valid",
        "QueueRunLifecycleReplicatedEnemyCatchupSpawn",
    ):
        assert token in materialization, f"enemy materialization lacks: {token}"
    for token in (
        'lua_setfield(state, -2, "content_id")',
        "EnemySpawnedEvent",
        "EnemyDeathEvent",
    ):
        assert token in events, f"content-aware enemy event lacks: {token}"

    for token in (
        '"id": "sample.lua.enemies_registry_lab"',
        '"enemies.register"',
        '"enemies.read"',
        '"enemies.spawn.authority"',
    ):
        assert token in manifest, f"enemy sample manifest lacks: {token}"
    for token in (
        'key = "grave_tyrant"',
        'base = "skeleton"',
        "8726222830294414077",
    ):
        assert token in sample, f"enemy sample lacks: {token}"
    for token in (
        "semantic stock-class name",
        "offline or host simulation",
        "modifier array",
        "Protocol 77",
        "death tombstones",
        "Raw actor/config",
        "addresses never cross the wire",
    ):
        assert token in documentation, f"enemy documentation lacks: {token}"
    assert "**Enemy registration and spawning implemented 2026-07-22.**" in roadmap
    for token in (
        "sd.enemies.list",
        "sd.enemies.get(expected_id)",
        "raw_addresses_absent",
        "late_registration_rejected",
    ):
        assert token in verifier, f"enemy verifier lacks: {token}"
    for token in (
        "--confirm-mutation",
        "sd.enemies.spawn(enemy.id",
        "get_last_manual_run_enemy_spawn",
        "refusing enemy spawn",
    ):
        assert token in spawn_verifier, f"enemy spawn verifier lacks: {token}"

    return (
        "sd.enemies registers deterministic semantic stock archetypes and authority-routes "
        "safe exact spawns with replicated constructor state, identity, and loot policy"
    )
