"""Contracts for native-rendered, semantically activated Lua UI authoring."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_ui_authoring_is_native_bounded_and_authority_routed() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_ui_authoring.cpp")
    semantic_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_ui.cpp")
    runtime = _read("SolomonDarkModLoader/src/lua_ui_runtime.cpp")
    input_helpers = _read(
        "SolomonDarkModLoader/src/lua_ui_runtime/input_helpers.inl"
    )
    renderer = _read("SolomonDarkModLoader/src/lua_ui_renderer.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    pump = _read("SolomonDarkModLoader/src/lua_engine_main_thread_pump.inl")
    window = _read("SolomonDarkModLoader/src/background_focus_bypass.cpp")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    route = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/lua_ui_action_sync.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_dispatch.inl"
    )
    layout = _read("config/binary-layout.ini")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-ui-authoring.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_ui_authoring_lab/manifest.json")
    sample = _read("mods/lua_ui_authoring_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_ui_authoring.py")
    verifier_tests = _read("tests/test_lua_ui_authoring_verifier.py")
    multiplayer_verifier = _read("tools/verify_lua_ui_multiplayer.py")
    multiplayer_verifier_tests = _read(
        "tests/test_lua_ui_multiplayer_verifier.py"
    )
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")

    for source in (
        "lua_engine_bindings_ui_authoring.cpp",
        "lua_ui_runtime.cpp",
        "lua_ui_renderer.cpp",
        "lua_ui_action_sync.inl",
        "input_helpers.inl",
    ):
        assert source in project, f"authored UI project item lacks: {source}"

    for token in (
        'RegisterFunction(state, &LuaUiCreateSurface, "create_surface")',
        'RegisterFunction(state, &LuaUiCreatePanel, "create_panel")',
        'RegisterFunction(state, &LuaUiCreateLabel, "create_label")',
        'RegisterFunction(state, &LuaUiCreateButton, "create_button")',
        'RegisterFunction(state, &LuaUiShow, "show")',
        'RegisterFunction(state, &LuaUiHide, "hide")',
        'RegisterFunction(state, &LuaUiDestroy, "destroy")',
        'RegisterFunction(state, &LuaUiSetText, "set_text")',
        'RegisterFunction(state, &LuaUiSetEnabled, "set_enabled")',
        'RegisterFunction(state, &LuaUiFocus, "focus")',
        'RegisterFunction(state, &LuaUiGetAuthoredState, "get_authored_state")',
        "RejectUnknownFields(",
        "options.on_activate must be a function",
        "'presentation' or 'simulation'",
        "luaL_ref(state, LUA_REGISTRYINDEX)",
        "luaL_unref(mod->state, LUA_REGISTRYINDEX",
        "ClearLuaUiForMod(mod->descriptor.id)",
    ):
        assert token in bindings, f"authored UI binding lacks: {token}"
    assert "RegisterLuaUiAuthoringBindings(state);" in semantic_bindings
    assert semantic_bindings.count("TryQueueLuaUiAction(") == 2

    for token in (
        "kLuaUiMaximumSurfacesPerMod = 8",
        "kLuaUiMaximumSurfaces = 64",
        "kLuaUiMaximumPanelsPerSurface = 16",
        "kLuaUiMaximumLabelsPerSurface = 64",
        "kLuaUiMaximumButtonsPerSurface = 32",
        "kLuaUiMaximumTextBytesPerSurface = 8 * 1024",
        "kMaximumPendingActions = 128",
        "IsValidIdentifier(",
        "FindOwnedSurfaceLocked(",
        "FindOwnedElementLocked(",
        "TakePendingLuaUiActions()",
    ):
        assert token in runtime + _read(
            "SolomonDarkModLoader/include/lua_ui_runtime.h"
        ), f"authored UI runtime lacks: {token}"
    for token in (
        "WM_KEYDOWN",
        "VK_UP",
        "VK_DOWN",
        "VK_TAB",
        "VK_RETURN",
        "VK_ESCAPE",
        "WM_MOUSEMOVE",
        "WM_LBUTTONUP",
        "QueueButtonActionLocked",
    ):
        assert token in runtime + input_helpers, f"authored UI input lacks: {token}"
    _require_in_order(
        window,
        "HandleLuaAuthoredUiWindowMessage(hwnd, message, wparam, lparam)",
        "IsMouseInputMessage(message)",
        "original(hwnd, message, wparam, lparam)",
    )

    for token in (
        '"lua_ui_authoring"',
        '"panel_render"',
        '"exact_text_render"',
        '"string_assign"',
        '"font_bundle_global"',
        '"render_context_color"',
        "ResolveGameAddressOrZero",
        "InstallD3d9FrameHook(",
        "NativeUiString",
        "__try",
        "__except",
        "UiPanelRenderFn",
        "ExactTextRenderFn",
    ):
        assert token in renderer, f"native authored UI renderer lacks: {token}"
    assert "CreateStateBlock" not in renderer
    for token in (
        "[lua_ui_authoring]",
        "device_pointer_global=0x00B401E8",
        "panel_render=0x005C3F40",
        "exact_text_render=0x0043BCD0",
        "string_assign=0x00402AE0",
        "font_bundle_global=0x008199A0",
        "font_object_offset=0x0004D530",
        "render_context_global=0x00B401A8",
        "render_context_color=0x0041FE50",
        "render_context_draw_state_offset=0x000001D0",
    ):
        assert token in layout, f"native authored UI layout lacks: {token}"

    for token in (
        "struct LuaUiActionRegistration",
        "std::vector<LuaUiActionRegistration> ui_actions",
        "LuaUiActionClass action_class",
        "int callback_reference",
    ):
        assert token in internal, f"authored UI callback ownership lacks: {token}"
    _require_in_order(
        engine,
        "ClearLuaUiBindingsForMod(mod);",
        "lua_close(mod->state)",
    )
    for capability in (
        '"ui.authoring.native"',
        '"ui.action.presentation"',
        '"ui.action.simulation.route"',
    ):
        assert capability in engine
    assert "HasLuaUiRegistrationsForMod(mod->descriptor.id)" in events
    assert pump.count("detail::DispatchPendingLuaUiActions();") == 2

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 81;",
        "LuaUiActionRequest = 25",
        "struct LuaUiActionRequestPacket",
        "participant_session_nonce",
        "char mod_id[kLuaUiModIdPacketBytes]",
        "char surface_id[kLuaUiIdentifierPacketBytes]",
        "char action_id[kLuaUiIdentifierPacketBytes]",
        "sizeof(LuaUiActionRequestPacket) == 294",
    ):
        assert token in protocol, f"authored UI protocol lacks: {token}"
    assert 'lua_ui_action_sync.inl"' in transport
    for token in (
        "kMaximumQueuedLuaUiActionRequests = 64",
        "IsLocalTransportClient()",
        "g_local_transport.local_session_nonce",
        "BuildKnownSendEndpoints()",
        "SendPacketToEndpoint(packet, endpoint)",
        "IsLocalTransportHost()",
        "SameEndpoint(candidate.endpoint, from)",
        "session_nonce_by_participant.find(packet.participant_id)",
        "packet.request_id <= last_request",
        "QueueRemoteLuaUiSimulationAction(",
    ):
        assert token in route, f"authored UI authority route lacks: {token}"
    assert "case PacketKind::LuaUiActionRequest:" in dispatch
    assert "ApplyLuaUiActionRequestPacket(packet, from, now_ms);" in dispatch

    for token in (
        "## API",
        "## Action execution classes",
        "## Ownership and limits",
        "## Native rendering seam",
        "presentation",
        "simulation",
        "participant session nonce",
        "game-thread pump",
        "Live presentation verification",
    ):
        assert token in documentation, f"authored UI docs lack: {token}"
    assert "**Implemented 2026-07-23.** Authored `sd.ui`" in roadmap
    for token in (
        '"id": "sample.lua.ui_authoring_lab"',
        '"enabled": false',
        '"ui.authoring.native"',
        '"ui.action.simulation.route"',
    ):
        assert token in manifest, f"authored UI sample manifest lacks: {token}"
    for token in (
        "sd.ui.create_surface",
        "sd.ui.create_panel",
        "sd.ui.create_label",
        "sd.ui.create_button",
        'execution = "presentation"',
        'execution = "simulation"',
        "sd.state.set",
    ):
        assert token in sample, f"authored UI sample lacks: {token}"
    for token in (
        'sd.runtime.has_capability("ui.authoring.native")',
        "unknown_field_rejected",
        "bad_rect_rejected",
        "foreign_handle_rejected",
        "callback_dispatched",
        "destroyed_state_absent",
        "capture_game_backbuffer",
        "inspect_native_ui_pixels",
        "changed_inside",
        "changed_outside",
        "CLEANUP_PROBE",
    ):
        assert token in verifier, f"authored UI verifier lacks: {token}"
    for token in (
        "test_localized_surface_change_passes",
        "test_identical_frames_fail",
        "test_whole_frame_change_is_not_surface_evidence",
    ):
        assert token in verifier_tests, f"authored UI verifier tests lack: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.ui_authoring_lab"',
        'execution = "presentation"',
        'execution = "simulation"',
        "presentation_participant_id=CLIENT_ID",
        "simulation_participant_id=CLIENT_ID",
        "simulation_routed=True",
        "simulation_participant_id=HOST_ID",
        "simulation_routed=False",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "two exact process IDs",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"authored UI multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_snapshot_matches_local_and_routed_action_metadata",
        "test_snapshot_rejects_wrong_routed_participant",
        "test_run_stages_exact_mod_and_stops_only_launched_pair",
    ):
        assert token in multiplayer_verifier_tests, (
            f"authored UI multiplayer verifier tests lack: {token}"
        )
    normalized_documentation = " ".join(documentation.split())
    for token in (
        "verify_lua_ui_multiplayer.py --launch-pair",
        "presentation callbacks stay on the activating client",
        "runs exactly once on the authority",
        "routed client participant identity",
        "`sd.state` mutation converges back to the client",
        "stops only the exact processes",
    ):
        assert token in normalized_documentation, (
            f"authored UI multiplayer docs lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_ui_authoring_verifier"
        in workflow
    )
    assert (
        "python -m unittest tests.test_lua_ui_multiplayer_verifier"
        in workflow
    )
    assert '"get_authored_state",' in runtime_verifier

    return (
        "sd.ui authors bounded native panels/text with one semantic input queue "
        "and exact two-peer authority routing for simulation callbacks"
    )
