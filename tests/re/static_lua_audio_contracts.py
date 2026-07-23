"""Contracts for scoped presentation-local Lua audio."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_audio_is_scoped_bounded_local_and_game_owned() -> str:
    binding_root = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_audio.cpp")
    runtime = _read("SolomonDarkModLoader/src/lua_engine_audio.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    pump = _read("SolomonDarkModLoader/src/lua_engine_main_thread_pump.inl")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-audio.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_audio_lab/manifest.json")
    sample = _read("mods/lua_audio_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_audio.py")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")

    assert "RegisterLuaAudioBindings(mod->state);" in binding_root
    assert "lua_createtable(mod->state, 0, 29);" in binding_root
    for source in (
        "lua_engine_bindings_audio.cpp",
        "lua_engine_audio.cpp",
    ):
        assert source in project, f"Lua audio project item lacks: {source}"

    for token in (
        "enum class LuaAudioPlaybackKind",
        "struct LuaAudioPlayback",
        "struct LuaAudioPlaybackSnapshot",
        "std::uint32_t sample_handle",
        "std::uint32_t channel_handle",
        "std::vector<LuaAudioPlayback> audio_playbacks",
        "std::uint64_t next_audio_playback_id = 1",
    ):
        assert token in internal, f"Lua audio lifecycle lacks: {token}"

    for token in (
        'RegisterFunction(state, &LuaAudioPlaySample, "play_sample")',
        'RegisterFunction(state, &LuaAudioPlayStream, "play_stream")',
        'RegisterFunction(state, &LuaAudioStop, "stop")',
        'RegisterFunction(state, &LuaAudioSetVolume, "set_volume")',
        'RegisterFunction(state, &LuaAudioGetState, "get_state")',
        'RegisterFunction(state, &LuaAudioClear, "clear")',
        'RegisterFunction(state, &LuaAudioIsAvailable, "is_available")',
        'lua_setfield(state, -2, "audio")',
        'field == "volume" || field == "loop"',
        "options.loop must be a boolean",
        "must be finite and between 0 and 1",
        "handle must be a positive integer",
    ):
        assert token in bindings, f"Lua audio binding lacks: {token}"
    for forbidden in (
        'lua_setfield(state, -2, "channel_handle")',
        'lua_setfield(state, -2, "sample_handle")',
        'lua_setfield(state, -2, "bass_handle")',
        'lua_setfield(state, -2, "native_handle")',
    ):
        assert forbidden not in bindings, f"Lua audio leaks internals: {forbidden}"

    for token in (
        "kLuaAudioMaximumPlaybacksPerMod = 64",
        "kLuaAudioMaximumGlobalPlaybacks = 256",
        "kLuaAudioMaximumRelativePathBytes = 512",
        "kLuaAudioMaximumAssetBytes = 512ULL * 1024ULL * 1024ULL",
        'GetModuleHandleW(L"bass.dll")',
        '"BASS_SampleLoad"',
        '"BASS_SampleFree"',
        '"BASS_SampleGetChannel"',
        '"BASS_StreamCreateFile"',
        '"BASS_StreamFree"',
        '"BASS_ChannelPlay"',
        '"BASS_ChannelStop"',
        '"BASS_ChannelSetAttribute"',
        '"BASS_ChannelIsActive"',
        '"BASS_ErrorGetCode"',
        '"BASS_GetVersion"',
        "std::filesystem::canonical",
        "IsWithinRoot(canonical_root, canonical_asset)",
        "relative_path.find('\\0')",
        "MB_ERR_INVALID_CHARS",
        'component == "." || component == ".."',
        'L".wav", L".ogg", L".mp3", L".caf"',
        "asset_size > kLuaAudioMaximumAssetBytes",
        "kBassUnicode",
        "kBassSampleLoop",
        "kBassAttributeVolume",
        "ReleasePlayback(&playback)",
        "g_bass.channel_is_active",
        "mod->audio_playbacks.erase(found)",
        "void ResetLuaAudioRuntimeForMod",
        "mod->next_audio_playback_id = 1",
    ):
        assert token in runtime, f"Lua BASS runtime lacks: {token}"
    assert "LoadLibrary" not in runtime
    assert "BASS_Init" not in runtime

    for capability in (
        '"audio.local.playback"',
        '"audio.sample"',
        '"audio.stream"',
    ):
        assert capability in runtime, f"Lua audio capability lacks: {capability}"
    assert "AppendLuaAudioCapabilities(&capabilities);" in engine
    _require_in_order(
        engine,
        "InitializeLuaDrawRuntime(bootstrap.stage_root",
        "detail::InitializeLuaAudioRuntime();",
        "const auto capabilities = detail::BuildLuaCapabilitySet();",
        "detail::LoadLuaModsForBootstrap",
    )
    _require_in_order(
        engine,
        "ResetLuaAudioRuntimeForMod(mod);",
        "lua_close(mod->state)",
    )
    assert engine.count("detail::ShutdownLuaAudioRuntime();") == 2
    assert "HasLuaAudioPlaybacks(mod.get())" in events
    assert pump.count("detail::TickLuaAudioRuntime();") == 2

    for token in (
        "## API",
        "## Paths and limits",
        "## Capabilities and multiplayer",
        "presentation-local",
        "`bass.dll` already loaded by Solomon Dark",
        "never loads a second BASS DLL",
        "64 simultaneous playbacks per mod",
        "256 simultaneous Lua playbacks",
        "512 MiB",
        "`sd.events.broadcast`",
    ):
        assert token in documentation, f"Lua audio documentation lacks: {token}"
    assert "**Implemented 2026-07-23.** `sd.audio`" in roadmap

    for token in (
        '"id": "sample.lua.audio_lab"',
        '"enabled": false',
        '"audio.local.playback"',
        '"audio.sample"',
        '"audio.stream"',
    ):
        assert token in manifest, f"Lua audio sample manifest lacks: {token}"
    for token in (
        'sd.events.on("sample.audio.stinger"',
        'sd.events.on("sample.audio.music"',
        "sd.audio.play_sample",
        "sd.audio.play_stream",
        "sd.audio.set_volume",
        "sd.audio.clear()",
    ):
        assert token in sample, f"Lua audio sample lacks: {token}"

    for token in (
        'sd.runtime.has_capability("audio.local.playback")',
        'sd.audio.play_sample(asset, {{volume = 0.25, loop = true}})',
        'sd.audio.play_stream(asset, {{volume = 0.3, loop = true}})',
        "raw_internals_absent",
        "traversal_rejected",
        "absolute_rejected",
        "invalid_utf8_rejected",
        "unknown_option_rejected",
        "playback_paths_passed",
    ):
        assert token in verifier, f"Lua audio verifier lacks: {token}"
    assert '"audio": (' in runtime_verifier

    return (
        "sd.audio reuses the game-owned BASS device for bounded mod-root "
        "samples and streams with opaque local-only ownership and cleanup"
    )
