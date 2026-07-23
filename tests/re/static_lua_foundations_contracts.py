"""Contracts for the authority-owned RNG and blessed native navigation seams."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_run_seed_is_authority_owned_and_native_applied() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    foundations = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_foundations.cpp"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    seed_api = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_gameplay_action_queues.inl"
    )
    seed_helpers = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "run_generation_seed_helpers.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-rng.md")
    timing_evidence = _read(
        "docs/reverse-engineering/game-timing-scale.md"
    )
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_rng.py")
    multiplayer_verifier = _read("tools/verify_lua_rng_multiplayer.py")
    multiplayer_verifier_tests = _read(
        "tests/test_lua_rng_multiplayer_verifier.py"
    )
    manifest = _read("mods/lua_rng_lab/manifest.json")
    sample = _read("mods/lua_rng_lab/scripts/main.lua")
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    assert "RegisterLuaRngBindings(mod->state)" in bindings
    assert '"rng.run.seed"' in engine
    assert "lua_engine_bindings_foundations.cpp" in project
    for token in (
        "kMaximumRunGenerationSeed = 0x3FFFFFFF",
        'RequireSimulationAuthority(state, "sd.rng.set_seed")',
        "local->runtime.in_run",
        "SetPendingRunGenerationSeed(",
        'RegisterFunction(state, &LuaRngGetSeed, "get_seed")',
        'RegisterFunction(state, &LuaRngSetSeed, "set_seed")',
        'lua_setfield(state, -2, "rng")',
    ):
        assert token in foundations, f"Lua RNG binding lacks: {token}"
    _require_in_order(
        foundations,
        "RequireSimulationAuthority",
        "local->runtime.in_run",
        "SetPendingRunGenerationSeed(",
    )

    assert "SetPendingRunGenerationSeedInternal" in seed_api
    for token in (
        "kNativeRngSeedMask = 0x3FFFFFFF",
        "PublishLocalRunNonce(seed)",
        "kNativeRngInitialize",
        "ApplyPendingRunGenerationSeedForSceneSwitch",
    ):
        assert token in seed_helpers, f"native seed path lacks: {token}"

    for token in (
        "## API",
        "simulation authority",
        "before entering a run",
        "run nonce",
        "rng.run.seed",
        "verify_lua_rng_multiplayer.py --launch-pair --confirm-mutation",
        "`testrun` entry is contingent",
        "correct authority-versus-already-in-run rejection",
        "stops only the two process IDs",
    ):
        assert token in documentation, f"Lua RNG documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.rng`" in roadmap
    for token in (
        "136 references",
        "78 containing functions",
        "divide-by-zero",
        "implementation shortcut",
    ):
        assert token in timing_evidence, f"timing investigation lacks: {token}"
    for token in (
        "sd.rng.set_seed",
        "sd.rng.get_seed",
        "zero_rejected",
        "fraction_rejected",
        "run seed did not round trip exactly",
    ):
        assert token in verifier, f"Lua RNG verifier lacks: {token}"
    for token in (
        '"id": "sample.lua.rng_lab"',
        '"enabled": false',
        '"rng.run.seed"',
    ):
        assert token in manifest, f"Lua RNG sample manifest lacks: {token}"
    for token in (
        'sd.runtime.has_capability("rng.run.seed")',
        "sd.rng.get_seed()",
    ):
        assert token in sample, f"Lua RNG sample lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.rng_lab"',
        "ACCEPTANCE_SEED = 0x1234567",
        "CLIENT_REJECTION_PROBE",
        "SEED_CONVERGENCE_PROBE",
        "RUN_STATE_PROBE",
        "participant_scene_kind",
        "run_nonce",
        "--confirm-mutation",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua RNG multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_initial_state_requires_exact_empty_rng_namespace",
        "test_applied_state_requires_exact_nonce_and_rejection_reason",
        "test_mutation_confirmation_is_required_before_contact",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_run_stages_exact_mod_and_stops_only_launched_pair",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua RNG multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_rng_multiplayer_verifier"
        in workflow
    )

    return (
        "sd.rng accepts exact pre-run seeds only from the simulation authority, "
        "publishes the run nonce, and has native-gated two-peer acceptance"
    )


def test_lua_nav_is_bounded_read_only_and_native_backed() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    foundations = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_foundations.cpp"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    nav_service = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/nav_grid_snapshot_service.inl"
    )
    nav_api = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
    )
    documentation = _read("docs/lua-nav.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_nav.py")
    bot_manifest = _read("mods/lua_bots/manifest.json")
    bot_follow = _read("mods/lua_bots/scripts/lib/lua_bots/follow.lua")

    assert "RegisterLuaNavBindings(mod->state)" in bindings
    assert '"nav.read"' in engine
    for token in (
        "kMaximumNavGridSubdivisions = 4",
        "RequestNavGridSnapshotRebuild",
        "GetLastNavGridSnapshotShared",
        "TryTestGameplayNavSegment",
        "CheckFiniteFloat",
        "player.world_address != snapshot->world_address",
        'RegisterFunction(state, &LuaNavGetGrid, "get_grid")',
        'RegisterFunction(state, &LuaNavTestSegment, "test_segment")',
        'lua_setfield(state, -2, "nav")',
    ):
        assert token in foundations, f"Lua nav binding lacks: {token}"
    for raw_field in (
        "grid.world_address",
        "grid.controller_address",
        "grid.cells_address",
        "grid.probe_actor_address",
    ):
        assert raw_field not in foundations

    assert "kNavGridMinRebuildIntervalMs = 500" in nav_service
    for token in (
        "IsGameplayPathPlacementTraversable",
        "IsGameplayPathCellTraversable",
        "IsGameplayPathSegmentTraversable",
    ):
        assert token in nav_api, f"native nav path lacks: {token}"

    for token in (
        "## API",
        "1` through `4",
        "500 milliseconds",
        "No process, world, controller, actor, or cell-list addresses",
        "read-only",
        "nav.read",
    ):
        assert token in documentation, f"Lua nav documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.nav`" in roadmap
    assert '"nav.read"' in bot_manifest
    assert "sd.nav.get_grid" in bot_follow
    assert "sd.debug.get_nav_grid" not in bot_follow
    for token in (
        "sd.nav.get_grid(2)",
        "sd.nav.test_segment",
        "raw_addresses_absent",
        "sample_count != cell_count * 4",
        "navigation snapshot did not reach subdivision 2",
    ):
        assert token in verifier, f"Lua nav verifier lacks: {token}"

    return (
        "sd.nav exposes bounded address-free snapshots and finite segment tests "
        "through the native player-sized path and collision rules"
    )
