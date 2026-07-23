"""Contracts for the local immediate-mode Lua drawing seam."""

from __future__ import annotations

from static_multiplayer_contract_support import _read


def test_lua_draw_is_bounded_local_and_backbuffer_verified() -> str:
    public_api = _read("SolomonDarkModLoader/include/lua_draw_runtime.h")
    runtime = _read("SolomonDarkModLoader/src/lua_draw_runtime.cpp")
    assets = _read("SolomonDarkModLoader/src/lua_draw_assets.cpp")
    renderer = "\n".join(
        (
            _read("SolomonDarkModLoader/src/lua_draw_renderer.cpp"),
            _read(
                "SolomonDarkModLoader/src/lua_draw_renderer/"
                "rendering_helpers.inl"
            ),
            _read("SolomonDarkModLoader/src/lua_draw_texture_loader.cpp"),
        )
    )
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_draw.cpp")
    binding_root = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    loader = _read("SolomonDarkModLoader/src/mod_loader.cpp")
    d3d_hook = _read("SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp")
    projection_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/animation_advance_hook.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-draw.md")
    sample_manifest = _read("mods/lua_hud_showcase/manifest.json")
    sample = _read("mods/lua_hud_showcase/scripts/main.lua")
    live_verifier = _read("tools/verify_lua_draw.py")
    multiplayer_verifier = _read(
        "tools/verify_lua_draw_multiplayer.py"
    )
    multiplayer_verifier_tests = _read(
        "tests/test_lua_draw_multiplayer_verifier.py"
    )
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    for token in (
        "kLuaDrawMaxCommandsPerMod = 512",
        "kLuaDrawMaxTextBytesPerMod = 16 * 1024",
        "kLuaDrawMaxTextCommandBytes = 1024",
        "struct LuaDrawFrameSnapshot",
        "struct LuaDrawSpriteInfo",
        "struct LuaDrawProjectionResult",
    ):
        assert token in public_api, f"public Lua draw contract lacks: {token}"

    for token in (
        "std::mutex mutex",
        "BeginLuaDrawFrame(",
        "CommitLuaDrawFrame(",
        "active_commands.swap(frame->second.pending_commands)",
        "pending_commands.size() >= kLuaDrawMaxCommandsPerMod",
        "kLuaDrawMaxTextBytesPerMod - frame->second.pending_text_bytes",
        "for (const auto& mod_id : g_lua_draw_runtime.mod_order)",
    ):
        assert token in runtime, f"per-mod draw-frame runtime lacks: {token}"

    for token in (
        "constexpr std::array<std::string_view, 28> kStockAtlasNames",
        '"ControlPanel"',
        '"Fonts"',
        "TryParseCommonSprite(",
        "TryParseAuxiliaryFontGroups(",
        "kMaximumBundleBytes = 16 * 1024 * 1024",
        "kMaximumBundleRecords = 20 * 1024",
        "AsciiEqualsIgnoreCase(",
    ):
        assert token in assets, f"bounded stock-atlas parser lacks: {token}"

    for token in (
        "CreateStateBlock(D3DSBT_ALL",
        "state_block->Capture()",
        "state_block->Apply()",
        "ConfigureUntexturedStage(",
        "ConfigureTexturedStage(",
        "D3DPT_TRIANGLESTRIP",
        "D3DPT_TRIANGLELIST",
        "InitializeFontAtlas(",
        "LoadLuaDrawTexture(",
        "CLSID_WICImagingFactory",
        "D3DPOOL_MANAGED",
        "successful_command_count != 0",
    ):
        assert token in renderer, f"D3D9 Lua draw renderer lacks: {token}"

    for token in (
        'RegisterFunction(state, &LuaDrawText, "text")',
        'RegisterFunction(state, &LuaDrawRect, "rect")',
        'RegisterFunction(state, &LuaDrawLine, "line")',
        'RegisterFunction(state, &LuaDrawSprite, "sprite")',
        'RegisterFunction(state, &LuaDrawWorldToScreen, "world_to_screen")',
        'RegisterFunction(state, &LuaDrawGetViewport, "get_viewport")',
        'RegisterFunction(state, &LuaDrawGetSpriteInfo, "get_sprite_info")',
        'RegisterFunction(state, &LuaDrawGetLimits, "get_limits")',
        'lua_setfield(state, -3, "hud")',
        'lua_setfield(state, -2, "draw")',
        "options.color.%s must be an integer from 0 through 255",
    ):
        assert token in bindings, f"Lua draw binding lacks: {token}"
    assert "RegisterLuaDrawBindings(mod->state);" in binding_root

    for capability in (
        '"draw.local.immediate"',
        '"draw.text"',
        '"draw.primitives"',
        '"draw.stock_sprites"',
        '"draw.world_projection"',
    ):
        assert capability in engine, f"Lua capability set lacks: {capability}"
    assert "InitializeLuaDrawRuntime(bootstrap.stage_root" in engine
    assert "ShutdownLuaDrawRuntime();" in engine
    assert "BeginLuaDrawFrame(mod->descriptor.id);" in events
    assert "CommitLuaDrawFrame(mod->descriptor.id);" in events
    assert "StartLuaDrawRenderer(" in loader
    assert "write_failed_status(\"lua-draw-renderer-failed\"" in loader

    for token in (
        "kMaximumFrameCallbacks = 8",
        "std::array<D3d9FrameCallback, kMaximumFrameCallbacks>",
        "RemoveD3d9FrameCallback(",
        "GetLastSeenD3d9Device()",
    ):
        assert token in d3d_hook, f"shared D3D9 subscriber seam lacks: {token}"
    assert (
        "CaptureLuaDrawWorldProjection(GetLastSeenD3d9Device());"
        in projection_hook
    )

    for source in (
        "lua_engine_bindings_draw.cpp",
        "lua_draw_assets.cpp",
        "lua_draw_renderer.cpp",
        "lua_draw_runtime.cpp",
        "lua_draw_texture_loader.cpp",
    ):
        assert source in project, f"native project omits: {source}"

    for token in (
        "## Frame contract and limits",
        "## Coordinates, colors, and text",
        "### `sd.draw.sprite",
        "### `sd.draw.world_to_screen",
        "## Capabilities",
        "presentation-local",
        "10,498 records",
    ):
        assert token in documentation, f"Lua draw documentation lacks: {token}"
    for token in (
        '"enabled": false',
        '"draw.local.immediate"',
        '"draw.world_projection"',
    ):
        assert token in sample_manifest, f"HUD sample manifest lacks: {token}"
    for token in (
        'sd.events.on("runtime.tick"',
        "sd.hud ~= sd.draw",
        "sd.draw.text(",
        "sd.draw.rect(",
        "sd.draw.line(",
        'sd.draw.sprite("Title", 9',
        "sd.draw.world_to_screen(",
    ):
        assert token in sample, f"HUD showcase lacks: {token}"

    for token in (
        "capture_game_backbuffer(",
        "inspect_acceptance_pixels(",
        "green_fill_pixels",
        "cyan_line_pixels",
        "white_text_pixels",
        "white_outline_pixels",
        "sprite_non_backdrop_pixels",
        "projection_generation",
    ):
        assert token in live_verifier, f"live draw verifier lacks: {token}"
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.hud_showcase"',
        "CONTRACT_PROBE",
        "ACTIVATE_PROBE",
        "DEACTIVATE_PROBE",
        "STATUS_PROBE",
        "_setup_probe(",
        "contract_matches",
        "status_matches",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua draw multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_contract_requires_exact_local_draw_schema",
        "test_status_requires_exact_peer_label_and_projection",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_incomplete_process_ledger_stops_only_owned_process",
        "test_run_proves_independent_draw_activation_and_release",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua draw multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_draw_multiplayer_verifier"
        in workflow
    )
    for token in (
        "verify_lua_draw_multiplayer.py --launch-pair",
        "remain local to each process",
        "Actual D3D9 output remains a separate rendered-window gate",
        "does not claim pixel coverage",
    ):
        assert token in documentation, (
            f"Lua draw multiplayer documentation lacks: {token}"
        )
    assert '"draw": (' in runtime_verifier
    assert "if sd.hud ~= sd.draw then fail('hud_alias_mismatch') end" in runtime_verifier

    return (
        "Lua mods own bounded tick-scoped display lists; D3D9 state is restored; "
        "stock bundles, projection, docs, an opt-in sample, namespace checks, "
        "exact two-peer local lifecycle, and pixel-level live acceptance are wired"
    )
