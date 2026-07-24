"""Contracts for bounded authority-owned Lua enemy AI."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_enemy_ai_is_bounded_authority_owned_and_collision_preserving() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_ai.cpp")
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    runtime = _read("SolomonDarkModLoader/src/lua_engine_enemy_ai.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    pump = _read("SolomonDarkModLoader/src/lua_engine_main_thread_pump.inl")
    native_runtime = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/lua_enemy_ai_runtime.inl"
    )
    hostile_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "monster_pathfinding_hook.inl"
    )
    actor_ids = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "cast_target_resolution.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-ai.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_ai_boss_lab/manifest.json")
    sample = _read("mods/lua_ai_boss_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_ai.py")
    multiplayer_verifier = _read("tools/verify_lua_ai_multiplayer.py")
    multiplayer_verifier_tests = _read(
        "tests/test_lua_ai_multiplayer_verifier.py"
    )
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    assert "RegisterLuaAiBindings(mod->state)" in root_bindings
    for source in (
        "lua_engine_bindings_ai.cpp",
        "lua_engine_enemy_ai.cpp",
        "lua_enemy_ai_runtime.inl",
        "public_api_lua_enemy_ai.inl",
    ):
        assert source in project, f"Lua AI project item lacks: {source}"
    for capability in (
        '"ai.register"',
        '"ai.read"',
        '"ai.control.authority"',
    ):
        assert capability in engine, f"Lua AI capability lacks: {capability}"

    for token in (
        "struct LuaEnemyAiRegistration",
        "struct LuaEnemyAiInstance",
        "int on_think_reference",
        "LuaModValue initial_blackboard",
        "LuaModValue blackboard",
        "std::vector<LuaEnemyAiRegistration> enemy_ai_registrations",
        "std::vector<LuaEnemyAiInstance> enemy_ai_instances",
    ):
        assert token in internal, f"Lua AI lifecycle lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaAiRegister, "register")',
        'RegisterFunction(state, &LuaAiGetState, "get_state")',
        'RegisterFunction(state, &LuaAiList, "list")',
        'RegisterFunction(state, &LuaAiSetTarget, "set_target")',
        'RegisterFunction(state, &LuaAiSetMoveGoal, "set_move_goal")',
        'RegisterFunction(state, &LuaAiStop, "stop")',
        'RegisterFunction(state, &LuaAiClear, "clear")',
        "kLuaMaximumEnemyAiRegistrationsPerMod = 256",
        "kLuaEnemyAiMinimumThinkIntervalMs = 16",
        "kLuaEnemyAiMaximumThinkIntervalMs = 5000",
        "kLuaEnemyAiMaximumBlackboardBytes = 4096",
        "mod->content_registration_open",
        "luaL_ref(state, LUA_REGISTRYINDEX)",
        "enemy must name an enemy registered by this mod",
    ):
        assert token in bindings, f"Lua AI binding lacks: {token}"
    for forbidden in (
        'lua_setfield(state, -2, "actor_address")',
        'lua_setfield(state, -2, "callback_reference")',
        'lua_setfield(state, -2, "registry_index")',
        'lua_setfield(state, -2, "native_function")',
    ):
        assert forbidden not in bindings, f"Lua AI API leaks internals: {forbidden}"

    for token in (
        "kLuaEnemyAiMaximumInstancesPerMod = 512",
        "kLuaEnemyAiMaximumCallbacksPerPump = 64",
        "!multiplayer::IsLuaModSimulationAuthority()",
        "!IsRunLifecycleActive()",
        "GetRunLifecycleTrackedEnemies(&tracked)",
        "TryGetRunLifecycleLuaEnemySpawnConfig",
        "GetLocalRunEnemyNetworkActorId",
        "registration->initial_blackboard",
        "instance->think_count += 1",
        "lua_pcall(mod->state, 1, 1, 0)",
        "ReadEnemyAiDecision",
        "SetLuaEnemyAiTargetOverride",
        "SetLuaEnemyAiMoveGoal",
        "ResetLuaEnemyAiRuntime",
    ):
        assert token in runtime, f"Lua AI callback runtime lacks: {token}"
    assert "DispatchLuaEnemyAiThink(context)" in pump

    for token in (
        "kMaximumLuaEnemyAiCommands = 512",
        "ValidateLuaEnemyAiActorIdentity",
        "TryGetRunLifecycleEnemySpawnSerial",
        "spawn_config.content_id != content_id",
        "Lua enemy AI target is already controlled by another registration",
        "ClearLuaEnemyAiOverridesForModInternal",
        "ResetLuaEnemyAiOverridesInternal",
    ):
        assert token in native_runtime, f"native Lua AI state lacks: {token}"
    for token in (
        "ApplyLuaEnemyAiTargetOverride",
        "WriteLuaEnemyAiNativeTarget",
        "kActorCurrentTargetActorOffset",
        "kHostileTargetBucketDeltaOffset",
        "target_actor_slot * kActorWorldBucketStride + target_world_slot",
        "native_move_magnitude",
        "goal_dx / goal_distance * native_move_magnitude",
        "IsBoundReplicatedRunEnemyActorForLocalClient",
        "ApplyAuthoritativeTurnUndeadCasterTargetLock",
    ):
        assert token in hostile_hooks, f"hostile Lua AI hook lacks: {token}"
    assert "kGameNpcSetMoveGoal" not in hostile_hooks
    _require_in_order(
        hostile_hooks,
        "ApplyAuthoritativeTurnUndeadCasterTargetLock",
        "multiplayer::IsLocalTransportClient()",
        "original(self, nullptr)",
        "ApplyLuaEnemyAiTargetOverride(hostile_actor_address)",
        "selector promoted wizard participant",
    )

    assert actor_ids.count("if (IsLuaModSimulationAuthority())") >= 2
    assert "if (network_actor_id == 0 || !IsLuaModSimulationAuthority())" in actor_ids
    for token in (
        "GameNpc_SetMoveGoal (0x005E9D50)",
        "different actor class",
        "rotates the native movement vector",
        "PlayerActor_MoveStep",
        "Clients create no controller instances",
        "protocol-82 world snapshots",
        "4096 bytes",
        "64 due callbacks",
        "verify_lua_ai_multiplayer.py --launch-pair --confirm-mutation",
        "nav-validated clear lane",
        "zero AI instances",
        "retirement on both peers",
        "stops only the exact processes",
    ):
        assert token in documentation, f"Lua AI documentation lacks: {token}"
    assert "**Implemented 2026-07-23.** `sd.ai.register`" in roadmap

    for token in (
        '"id": "sample.lua.ai_boss_lab"',
        '"ai.register"',
        '"ai.control.authority"',
    ):
        assert token in manifest, f"Lua AI sample manifest lacks: {token}"
    for token in (
        'key = "grave_oracle"',
        "6758053804871806748",
        "sd.ai.register",
        "on_think = function",
        "context.participants",
        "target = closest.ref",
        "move_goal = {",
        "blackboard = {step = step}",
    ):
        assert token in sample, f"Lua AI sample lacks: {token}"
    for token in (
        'sd.runtime.has_capability("ai.register")',
        "sd.ai.list()",
        "raw_internals_absent",
        "late_registration_rejected",
        "6758053804871806748",
    ):
        assert token in verifier, f"Lua AI verifier lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.ai_boss_lab"',
        "NAV_CANDIDATE",
        "CLIENT_ID",
        "blackboard_step",
        "goal_axis_aligned",
        "target_authoritative",
        "MINIMUM_MOVEMENT_DISTANCE",
        "_movement_segment_probe",
        "_client_mutation_rejection_probe",
        "--confirm-mutation",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "two exact process IDs",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua AI multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_spawn_result_requires_registered_native_actor",
        "test_host_ai_requires_exact_blackboard_target_and_movement",
        "test_client_snapshot_has_no_controller_and_tracks_authority",
        "test_mutation_confirmation_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_run_stages_exact_mod_and_stops_only_launched_pair",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua AI multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_ai_multiplayer_verifier"
        in workflow
    )

    return (
        "sd.ai runs bounded per-enemy blackboards only on authority and "
        "steers the proven hostile collision path without exposing addresses"
    )
