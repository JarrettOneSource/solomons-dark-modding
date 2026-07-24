"""Contracts for semantic authority-routed Lua scene control."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_scene_is_address_free_authority_owned_and_rooms_are_participant_local() -> str:
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
    snapshot_builders = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_snapshot_packet_builders.inl"
    )
    snapshot_capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_capture.inl"
    )
    gameplay_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_main_thread_pump.inl"
    )
    steam_session = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/"
        "lobby_and_events.inl"
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

    assert "MaybeQueueClientHostRegionFollow" not in transport
    assert "MaybeQueueClientHostRegionFollow" not in participant_sync
    assert "kClientHostMaximumPrivateRegionIndex" not in transport
    assert "kClientHostSharedHubRegionIndex" not in transport
    assert "MaybeQueueClientHostRunStart(packet, scene_intent, from, now_ms)" in (
        participant_sync
    )
    for token in (
        "TryListSharedHubActors(&actors)",
        "authoritative_scene_intent.kind =",
        "ParticipantSceneIntentKind::SharedHub;",
        "RefreshWorldSceneTracking(",
        "scene_state, authoritative_scene_intent.kind)",
    ):
        assert token in snapshot_builders, (
            f"dormant shared-hub snapshot ownership lacks: {token}"
        )
    assert "BuildWorldSceneKey(scene_state, scene_kind)" in snapshot_capture
    assert "TickDormantSharedHubOnGameThread();" in gameplay_pump
    private_region_case = steam_session.index(
        "case ParticipantSceneIntentKind::PrivateRegion:"
    )
    assert (
        'game_phase = "hub";'
        in steam_session[private_region_case : private_region_case + 160]
    )
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
        "participant-local",
        "host keeps the shared courtyard simulation authoritative",
        "stock Leave Game UI action",
        "scene.switch.authority",
        "verify_lua_scene_multiplayer.py --launch-pair --confirm-mutation",
        "different private rooms",
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
        "CLIENT_PRIVATE_SWITCH_PROBE",
        "_poll_switch_request",
        "hub_observing_private_host_state_matches",
        "different_private_rooms_state_matches",
        "host_scene_region_index",
        'host_scene_kind == "SharedHub" and 0',
        "sd.state.is_authority() and participant.is_owner",
        "instance_prefix=instance_prefix",
        "game_directory=game_directory",
        "select_available_windows_udp_ports(2)",
        "--confirm-mutation",
        "--game-directory",
        "tile_windows=False",
        "kill_existing=False",
        "quick_start=True",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua scene multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_client_hub_can_observe_host_private_room",
        "test_host_and_client_can_occupy_different_private_rooms",
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
        "authority, keeps hub rooms participant-local, and preserves synchronized "
        "run entry"
    )
