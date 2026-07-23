"""Contracts for semantic authority-routed Lua scene control."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_scene_is_address_free_authority_owned_and_peer_followed() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    scene = _read("SolomonDarkModLoader/src/lua_engine_bindings_scene.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    queue = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_gameplay_action_queues.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )
    participant_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_participant_state_sync.inl"
    )
    bot_intents = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/scene_intents_api.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-scene.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_scene.py")
    multiplayer_verifier = _read("tools/verify_lua_scene_multiplayer.py")
    multiplayer_verifier_tests = _read(
        "tests/test_lua_scene_multiplayer_verifier.py"
    )
    manifest = _read("mods/lua_scene_lab/manifest.json")
    sample = _read("mods/lua_scene_lab/scripts/main.lua")
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    assert "RegisterLuaSceneBindings(mod->state)" in bindings
    assert "lua_engine_bindings_scene.cpp" in project
    for capability in ('"scene.read"', '"scene.switch.authority"'):
        assert capability in engine

    for token in (
        'RequireSceneAuthority(state)',
        'RegisterFunction(state, &LuaSceneGetState, "get_state")',
        'RegisterFunction(state, &LuaSceneSwitchRegion, "switch_region")',
        'lua_setfield(state, -2, "scene")',
        "QueueHubStartTestrun(&error_message)",
        "QueueGameplaySwitchRegion(",
        'scene.kind != "hub"',
        'scene.kind == "transition"',
    ):
        assert token in scene, f"Lua scene binding lacks: {token}"
    for raw_field in (
        "scene.gameplay_scene_address",
        "scene.world_address",
        "scene.arena_address",
        "scene.region_state_address",
    ):
        assert raw_field not in scene, f"semantic scene API leaks {raw_field}"

    for token in (
        "MaybeQueueClientHostRegionFollow",
        "IsAuthoritativeHostParticipantPacket(packet, from)",
        "DoesLocalSceneMatchParticipantIntent(scene_intent)",
        "IsLocalSceneAlreadyRun(scene_state)",
        "QueueGameplaySwitchRegion(target_region",
        "kClientHostMaximumPrivateRegionIndex",
    ):
        assert token in transport, f"client region follow lacks: {token}"
    assert participant_sync.count("MaybeQueueClientHostRegionFollow(") == 1
    assert "SetAllBotSceneIntentsToPrivateRegion(region_index)" in queue
    assert "SetAllBotSceneIntentsToSharedHub()" in queue
    assert "ParticipantSceneIntentKind::PrivateRegion" in bot_intents
    _require_in_order(
        queue,
        "pending_gameplay_region_switch_requests.push_back(request)",
        "SetAllBotSceneIntentsToPrivateRegion(region_index)",
    )

    for token in (
        "No gameplay-scene, world, arena, region-state, or other process address",
        "simulation authority",
        "authenticated authority endpoint",
        "stock Leave Game UI action",
        "scene.switch.authority",
        "verify_lua_scene_multiplayer.py --launch-pair --confirm-mutation",
        "private region 2 and back",
        "authenticated host participant intent",
        "Only the two process IDs",
    ):
        assert token in documentation, f"Lua scene documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.scene`" in roadmap
    for token in (
        "sd.scene.get_state",
        "sd.scene.switch_region",
        "raw_addresses_absent",
        "fraction_rejected",
    ):
        assert token in verifier, f"Lua scene verifier lacks: {token}"
    for token in (
        '"id": "sample.lua.scene_lab"',
        '"enabled": false',
        '"scene.read"',
        '"scene.switch.authority"',
    ):
        assert token in manifest, f"Lua scene sample manifest lacks: {token}"
    for token in (
        'sd.runtime.has_capability("scene.read")',
        'sd.runtime.has_capability("scene.switch.authority")',
        "sd.scene.get_state()",
    ):
        assert token in sample, f"Lua scene sample lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.scene_lab"',
        "PRIVATE_REGION_INDEX = 2",
        "CLIENT_REJECTION_PROBE",
        "PRIVATE_SWITCH_PROBE",
        "RUN_SWITCH_PROBE",
        "ARENA_EXIT_REJECTION_PROBE",
        "host_scene_region_index",
        "--confirm-mutation",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua scene multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_private_state_requires_exact_host_intent_and_local_region",
        "test_arena_exit_rejection_distinguishes_host_and_client",
        "test_mutation_confirmation_is_required_before_contact",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_run_stages_exact_mod_and_stops_only_launched_pair",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua scene multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_scene_multiplayer_verifier"
        in workflow
    )

    return (
        "sd.scene exposes semantic state, routes switches through the simulation "
        "authority, with exact two-peer follow and arena-exit acceptance"
    )
