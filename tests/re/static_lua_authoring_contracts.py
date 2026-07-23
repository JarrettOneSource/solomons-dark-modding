"""Contracts for generated Lua editor metadata, hot reload, and exec console."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_authoring_is_generated_reloadable_and_safe_thread_executed() -> str:
    runtime_model = _read(
        "SolomonDarkModLauncher/src/Mods/RuntimeModDefinition.cs"
    )
    validator = _read("SolomonDarkModLauncher/src/Mods/ModManifestValidator.cs")
    stage_entry = _read(
        "SolomonDarkModLauncher/src/Staging/RuntimeStageManifestEntry.cs"
    )
    materializer = _read(
        "SolomonDarkModLauncher/src/Staging/RuntimeMetadataStageMaterializer.cs"
    )
    bootstrap_header = _read("SolomonDarkModLoader/include/runtime_bootstrap.h")
    bootstrap_parser = _read("SolomonDarkModLoader/src/runtime_bootstrap.cpp")
    hot_reload = _read("SolomonDarkModLoader/src/lua_hot_reload.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    engine_header = _read("SolomonDarkModLoader/include/lua_engine.h")
    engine_internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    loader = _read("SolomonDarkModLoader/src/mod_loader.cpp")
    pump = _read("SolomonDarkModLoader/src/lua_engine_main_thread_pump.inl")
    console = _read("SolomonDarkModLoader/src/lua_developer_console.cpp")
    window_hook = _read("SolomonDarkModLoader/src/background_focus_bypass.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    filters = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters")
    generator = _read("tools/generate_lua_api_stubs.py")
    generated_stub = _read("api/lua/sd.lua")
    generator_tests = _read("tests/test_lua_api_stub_generator.py")
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")
    luarc = _read(".luarc.json")
    launcher_tests = _read("tests/launcher-contracts/Program.cs")
    documentation = _read("docs/lua-authoring.md")
    roadmap = _read("docs/lua-seam-roadmap.md")

    assert "public bool HotReload { get; init; }" in runtime_model
    assert "manifest.Runtime.HotReload && !manifest.RequiresLuaRuntime" in validator
    for token in (
        "bool HotReload",
        "string SourceModRootPath",
        "string? SourceEntryScriptPath",
    ):
        assert token in stage_entry, f"hot-reload stage descriptor lacks: {token}"
    _require_in_order(
        materializer,
        "FileTreeMirror.Synchronize(mod.RootPath, stagedModRootPath)",
        "mod.Manifest.Runtime.HotReload",
        "mod.RootPath",
        "Path.Combine(stagedModRootPath",
    )
    for token in (
        'builder.Append("hot_reload=")',
        'builder.Append("source_root_path=")',
        'builder.Append("source_entry_script_path=")',
        'builder.Append("entry_script_path=")',
    ):
        assert token in materializer, f"runtime bootstrap writer lacks: {token}"
    for token in (
        "bool hot_reload = false",
        "source_root_path",
        "source_entry_script_path",
    ):
        assert token in bootstrap_header, f"native runtime descriptor lacks: {token}"
    for token in (
        "TryParseBoolean",
        '"hot_reload"',
        '"source_root_path"',
        '"source_entry_script_path"',
        "mod.source_entry_script_path =",
    ):
        assert token in bootstrap_parser, f"native bootstrap parser lacks: {token}"

    for token in (
        "kLuaHotReloadPollIntervalMs = 250",
        "kLuaHotReloadStableIntervalMs = 300",
        "kLuaHotReloadMaximumSourceBytes = 1024 * 1024",
        "kFnvOffsetBasis",
        "TryReadFingerprint",
        "PreflightLuaSource",
        "luaL_loadfile(preflight_state",
        "InitializeLuaHotReloadState",
        "PollLuaHotReloadsOnLockedThread",
        "hot reload rejected; existing state preserved",
        "hot reload execution failed; edit the source to retry",
    ):
        assert token in hot_reload, f"hot-reload runtime lacks: {token}"
    reload_apply = hot_reload.split(
        "const auto candidate = mod->hot_reload.pending_fingerprint;", 1
    )[1]
    _require_in_order(
        reload_apply,
        "PreflightLuaSource(*mod, candidate",
        "CloseLuaStateForMod(mod)",
        "CreateLuaStateForMod(",
        "hot reloaded source entry script",
    )
    _require_in_order(
        engine,
        "ClearLuaEventFilterRegistrationsForMod(mod)",
        "ClearLuaTimersForMod(mod)",
        "ClearLuaBusSubscriptionsForMod(mod)",
        "ClearLuaNetSubscriptionsForMod(mod)",
        "ClearLuaDrawFrameForMod(mod->descriptor.id)",
        "ClearLuaSpriteAtlasesForMod(mod->descriptor.id)",
        "lua_close(mod->state)",
    )
    for token in (
        "IsMultiplayerTransportConfigured",
        "IsLocalTransportEnabled",
        "PollLuaHotReloadsOnLockedThread",
    ):
        assert token in pump, f"safe-thread hot-reload gate lacks: {token}"
    assert "participant.transport_connected" not in pump
    assert "LuaHotReloadState hot_reload" in engine_internal

    for token in (
        "using LuaExecCompletion = std::function<void(LuaExecResult)>;",
        "QueueLuaExecRequestAsync",
        "GetLuaExecTargetModId",
    ):
        assert token in engine_header, f"async exec contract lacks: {token}"
    for token in (
        "LuaExecCompletion completion",
        "request->completion(result)",
        "SetPromiseValueSafely",
    ):
        assert token in engine, f"shared exec queue lacks: {token}"
    _require_in_order(
        pump,
        "ExecuteLuaCodeOnLockedState(shared_state, request->code)",
        "lock.unlock()",
        "FinishLuaExecRequest(request",
    )

    for token in (
        "kLuaDeveloperConsoleMaximumInputBytes = 4096",
        "kLuaDeveloperConsoleMaximumOutputLines = 128",
        "kLuaDeveloperConsoleMaximumHistoryEntries = 64",
        "wparam == VK_OEM_3",
        "IsControlDown()",
        "QueueLuaExecRequestAsync(code, &CompleteConsoleRequest)",
        "BeginLuaDrawFrame(kLuaDeveloperConsoleOwner)",
        "CommitLuaDrawFrame(kLuaDeveloperConsoleOwner)",
        "ReadClipboardUtf8",
        "NavigateConsoleHistory",
    ):
        assert token in console, f"in-game exec console lacks: {token}"
    assert '#include "lua.h"' not in console
    _require_in_order(
        window_hook,
        "HandleLuaDeveloperConsoleWindowMessage",
        "HandleLuaAuthoredUiWindowMessage",
    )
    _require_in_order(
        loader,
        "StartLuaDrawRenderer(",
        "StartLuaUiRenderer(",
        "InitializeLuaDeveloperConsole()",
    )
    _require_in_order(
        loader,
        'RunShutdownStep("lua exec pipe"',
        'RunShutdownStep("lua developer console"',
        'RunShutdownStep("lua engine"',
    )

    for item in (
        "include\\lua_developer_console.h",
        "src\\lua_developer_console.cpp",
        "src\\lua_hot_reload.cpp",
        "src\\lua_exec_wait.inl",
    ):
        assert item in project, f"native project omits: {item}"
        assert item in filters, f"native project filters omit: {item}"

    for token in (
        "_strip_cpp_comments",
        "discover_bindings",
        "ROOT_CALL",
        "RegisterLuaBindings contains no namespace registrations",
        "duplicate sd namespace",
        "canonical_by_table",
        "--check",
        "difflib.unified_diff",
    ):
        assert token in generator, f"Lua API generator lacks: {token}"
    for token in (
        "-- Inventory: 29 namespaces, 267 unique functions.",
        "---@class SdApi",
        "---@field runtime SdRuntimeApi",
        "---@field hud SdDrawApi",
        "function sd_sprites.register(...) end",
        "function sd_debug.capture_backbuffer(...) end",
        "hud = sd_draw",
        "draw = sd_draw",
    ):
        assert token in generated_stub, f"generated Lua API stub lacks: {token}"
    for token in (
        "test_cpp_comments_cannot_add_generated_bindings",
        "test_inventory_follows_root_registration_order_and_nested_helpers",
        "test_draw_and_hud_preserve_the_native_table_alias",
        "test_checked_in_stub_is_current",
    ):
        assert token in generator_tests, f"Lua API generator tests lack: {token}"
    assert '"workspace.library"' in luarc and '"api/lua"' in luarc
    assert "python tools/generate_lua_api_stubs.py --check" in workflow
    assert "python -m unittest tests.test_lua_api_stub_generator" in workflow

    for token in (
        '"Lua hot reload bootstrap"',
        '"hotReload": true',
        "staged.HotReload",
        "staged.SourceEntryScriptPath",
        "manifest accepted hot reload without a Lua entry point",
    ):
        assert token in launcher_tests, f"launcher hot-reload test lacks: {token}"
    for token in (
        "## Editor API",
        "## Entry-script hot reload",
        "## In-game exec console",
        "prior state remains live",
        "automatically deferred",
        "same capture result as the named pipe",
    ):
        assert token in documentation, f"Lua authoring documentation lacks: {token}"
    assert "**Implemented 2026-07-23.** The checked-in `api/lua/sd.lua`" in roadmap

    return (
        "Lua authoring derives editor metadata from native registrations, reloads "
        "opt-in source states only on safe offline pumps, and executes the bounded "
        "in-game console through the shared async queue"
    )
