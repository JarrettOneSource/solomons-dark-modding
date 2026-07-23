"""Contracts for presentation-local native Lua camera control."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_camera_is_native_bounded_owned_and_presentation_local() -> str:
    binding_root = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_camera.cpp")
    runtime = _read("SolomonDarkModLoader/src/lua_camera_runtime.cpp")
    runtime_header = _read("SolomonDarkModLoader/include/lua_camera_runtime.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    loader = _read("SolomonDarkModLoader/src/mod_loader.cpp")
    seams = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    layout = _read("config/binary-layout.ini")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-camera.md")
    native_re = _read("docs/reverse-engineering/native-camera-control.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_camera_lab/manifest.json")
    sample = _read("mods/lua_camera_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_camera.py")
    multiplayer_verifier = _read("tools/verify_lua_camera_multiplayer.py")
    multiplayer_verifier_tests = _read(
        "tests/test_lua_camera_multiplayer_verifier.py"
    )
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    assert "RegisterLuaCameraBindings(mod->state);" in binding_root
    assert "lua_createtable(mod->state, 0, 30);" in binding_root
    for item in (
        "include\\lua_camera_runtime.h",
        "src\\lua_engine_bindings_camera.cpp",
        "src\\lua_camera_runtime.cpp",
    ):
        assert item in project, f"Lua camera project item lacks: {item}"

    for token in (
        'RegisterFunction(state, &LuaCameraGetState, "get_state")',
        'RegisterFunction(state, &LuaCameraSetFocus, "set_focus")',
        'RegisterFunction(state, &LuaCameraClearFocus, "clear_focus")',
        'RegisterFunction(state, &LuaCameraShake, "shake")',
        'lua_setfield(state, -2, "camera")',
        "RequireArgumentCount(state, 2, kApiName)",
        "kLuaCameraMaximumCoordinateMagnitude = 1000000.0f",
        'lua_setfield(state, -2, "owns_focus")',
        'SetNumberField(state, "shake_accumulator"',
    ):
        assert token in bindings, f"Lua camera binding lacks: {token}"
    for forbidden in (
        'lua_setfield(state, -2, "region_address")',
        'lua_setfield(state, -2, "pointer")',
        'lua_setfield(state, -2, "function_address")',
    ):
        assert forbidden not in bindings, f"Lua camera leaks internals: {forbidden}"

    for token in (
        "kMaximumFocusOwners = 64",
        "kMaximumCoordinateMagnitude = 1000000.0f",
        "std::unordered_map<std::string, CameraFocusRequest>",
        "request.region_address != scene.world_address",
        "request.sequence <= selected_sequence",
        "state.focus_requests.erase(std::string(mod_id))",
        "kActorWorldExpandedViewOriginXOffset",
        "kActorWorldCullViewOriginXOffset",
        "TryTranslateCameraRectangles",
        "original(self);",
        "ApplyActiveCameraFocus(self);",
        "InvokeNativeCameraShake",
        "intensity <= 0.0f",
        "intensity > 1.0f",
        "RemoveHookSet",
    ):
        assert token in runtime, f"Lua camera runtime lacks: {token}"
    _require_in_order(runtime, "original(self);", "ApplyActiveCameraFocus(self);")
    assert runtime.count("InstallSafeX86Hook(") == 1
    assert "kRegionTickHookCount = 6" in runtime
    for hook in (
        "HookArenaRegionTick",
        "HookCourtyardRegionTick",
        "HookMortuaryRegionTick",
        "HookStoreRoomRegionTick",
        "HookLibraryRegionTick",
        "HookOfficeRegionTick",
    ):
        assert hook in runtime, f"Lua camera Region coverage lacks: {hook}"

    for token in (
        "bool runtime_available = false",
        "bool caller_owns_focus = false",
        "float shake_magnitude = 0.0f",
        "AppendLuaCameraCapabilities",
        "ClearLuaCameraFocus",
    ):
        assert token in runtime_header, f"Lua camera public runtime lacks: {token}"
    for capability in (
        '"camera.local.read"',
        '"camera.local.focus"',
        '"camera.local.shake"',
    ):
        assert capability in runtime, f"Lua camera capability lacks: {capability}"
    assert "AppendLuaCameraCapabilities(&capabilities);" in engine
    assert "ClearLuaCameraFocus(mod->descriptor.id);" in engine
    _require_in_order(
        loader,
        "InitializeLuaCameraRuntime(&camera_error)",
        "InitializeLuaEngine(runtime_bootstrap",
    )
    assert loader.count("ShutdownLuaCameraRuntime") == 2

    for token in (
        "kArenaRegionTick",
        "kCourtyardRegionTick",
        "kMortuaryRegionTick",
        "kStoreRoomRegionTick",
        "kLibraryRegionTick",
        "kOfficeRegionTick",
        "kRegionApplyCameraShake",
        "kActorWorldViewWidthOffset",
        "kActorWorldExpandedViewOriginXOffset",
        "kActorWorldCullViewOriginXOffset",
        "kActorWorldCameraShakeAccumulatorOffset",
    ):
        assert token in seams, f"Lua camera seam declaration lacks: {token}"
    for token in (
        "arena_region_tick=0x0046E570",
        "courtyard_region_tick=0x0050C970",
        "mortuary_region_tick=0x00509330",
        "storeroom_region_tick=0x00504220",
        "library_region_tick=0x00504BB0",
        "office_region_tick=0x00509F10",
        "region_apply_camera_shake=0x0063EEB0",
        "actor_world_view_origin_x=0x8BCC",
        "actor_world_view_width=0x8BD4",
        "actor_world_expanded_view_origin_x=0x8BDC",
        "actor_world_cull_view_origin_x=0x8BEC",
        "actor_world_camera_shake_accumulator=0x8E08",
    ):
        assert token in layout, f"Lua camera binary layout lacks: {token}"

    for token in (
        "## API",
        "## State",
        "## Native boundary",
        "presentation-local",
        "most recently set request wins",
        "does not expose zoom",
        "camera.local.focus",
    ):
        assert token in documentation, f"Lua camera docs lack: {token}"
    for token in (
        "0x0063ED80",
        "0x00462110",
        "0x0063EEB0",
        "after each original tick",
        "+0x8E04/+0x8E08",
        "replica-pool wrapper",
    ):
        assert token in native_re, f"Lua camera RE evidence lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.camera`" in roadmap

    for token in (
        '"id": "sample.lua.camera_lab"',
        '"enabled": false',
        '"camera.local.read"',
        '"camera.local.focus"',
        '"camera.local.shake"',
    ):
        assert token in manifest, f"Lua camera sample manifest lacks: {token}"
    for token in (
        "sd.camera.get_state",
        "sd.camera.set_focus",
        "sd.camera.clear_focus",
        "sd.camera.shake",
    ):
        assert token in sample, f"Lua camera sample lacks: {token}"
        assert token in verifier, f"Lua camera verifier lacks: {token}"
    for token in (
        'sd.runtime.has_capability("camera.local.read")',
        "nan_focus_rejected",
        "huge_focus_rejected",
        "zero_shake_rejected",
        "extra_clear_rejected",
    ):
        assert token in verifier, f"Lua camera verifier lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.camera_lab"',
        "HOST_FOCUS",
        "CLIENT_FOCUS",
        "STATE_PROBE",
        "HOST_FOCUS_PROBE",
        "CLIENT_FOCUS_PROBE",
        "SHAKE_PROBE",
        "native_focus_applied",
        "native_feedback_changed",
        "require_quiet=True",
        "--confirm-mutation",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua camera multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_focus_state_requires_native_center_and_exact_local_target",
        "test_shake_request_requires_synchronous_native_feedback_delta",
        "test_mutation_confirmation_is_required_before_contact",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_incomplete_process_ledger_stops_only_owned_process",
        "test_run_proves_independent_focus_and_host_shake_isolation",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua camera multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_camera_multiplayer_verifier"
        in workflow
    )
    assert '"camera": ("get_state", "set_focus", "clear_focus", "shake")' in runtime_verifier

    return "Lua camera native/local ownership has exact two-peer acceptance"
