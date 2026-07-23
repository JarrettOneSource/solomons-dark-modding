"""Contracts for mod-owned runtime Lua sprite atlases."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_sprites_are_owned_bounded_sandboxed_and_revisioned() -> str:
    header = _read("SolomonDarkModLoader/include/lua_sprite_runtime.h")
    runtime = _read("SolomonDarkModLoader/src/lua_sprite_runtime.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_sprites.cpp")
    binding_root = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    draw_header = _read("SolomonDarkModLoader/include/lua_draw_runtime.h")
    draw_assets = _read("SolomonDarkModLoader/src/lua_draw_assets.cpp")
    draw_runtime = _read("SolomonDarkModLoader/src/lua_draw_runtime.cpp")
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
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    filters = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters")
    hasher = _read("SolomonDarkModLauncher/src/Mods/ModContentHasher.cs")
    compatibility = _read(
        "SolomonDarkModLauncher/src/Staging/MultiplayerCompatibilityMaterializer.cs"
    )
    documentation = _read("docs/lua-sprites.md")
    draw_documentation = _read("docs/lua-draw.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_sprites_lab/manifest.json")
    sample = _read("mods/lua_sprites_lab/scripts/main.lua")
    descriptor = _read("mods/lua_sprites_lab/sprites/atlas.example.json")
    sample_readme = _read("mods/lua_sprites_lab/sprites/README.md")
    builder = _read("tools/build_lua_sprite_bundle.py")
    verifier = _read("tools/verify_lua_sprites.py")
    tool_tests = _read("tests/test_lua_sprite_tools.py")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")

    for token in (
        "kLuaSpriteMaximumAtlasesPerMod = 32",
        "kLuaSpriteMaximumGlobalAtlases = 128",
        "kLuaSpriteMaximumFramesPerAtlas = 4096",
        "kLuaSpriteMaximumGlobalFrames = 32768",
        "kLuaSpriteMaximumRelativePathBytes = 512",
        "kLuaSpriteMaximumAtlasIdBytes",
        "kLuaContentMaximumIdentifierLength * 2 + 1",
        "kLuaSpriteMaximumImageBytes",
        "kLuaSpriteMaximumBundleBytes",
        "kLuaSpriteMaximumImageDimension = 4096",
        "kLuaSpriteMaximumFrameGeometry = 16384.0f",
        "struct LuaSpriteAtlasSnapshot",
        "TryGetLuaRegisteredSpriteSource",
    ):
        assert token in header, f"public Lua sprite contract lacks: {token}"

    for token in (
        "MultiByteToWideChar(",
        "CP_UTF8",
        "MB_ERR_INVALID_CHARS",
        "relative.is_absolute() || relative.has_root_path()",
        'component == "." || component == ".."',
        "std::filesystem::canonical(mod_root",
        "std::filesystem::is_regular_file",
        "IsWithinRoot(canonical_root, canonical_asset)",
        "kPngSignature",
        "ReadBigEndianU32(header, 8) != 13",
        "header[12] != 'I'",
        "kLuaSpriteMaximumImageDimension",
        "detail::TryParseLuaDrawSpriteBundle(",
        "frame.rotated",
        "extends beyond the PNG dimensions",
        "exceeds the 16384-pixel geometry bound",
        "CountGlobalFrames(registry, candidate.snapshot.id)",
        "CountModAtlases(registry, mod_id)",
        "candidate.snapshot.revision = registry.next_revision++",
        "registry.atlases[id] = std::move(candidate)",
        "atlas.snapshot.mod_id == mod_id",
    ):
        assert token in runtime, f"bounded sprite registry lacks: {token}"

    registration = runtime.split("bool RegisterLuaSpriteAtlas(", 1)[1].split(
        "bool UnregisterLuaSpriteAtlas(", 1
    )[0]
    _require_in_order(
        registration,
        "ResolveSpriteAssetPath(",
        "TryReadPngDimensions(",
        "detail::TryParseLuaDrawSpriteBundle(",
        "std::scoped_lock lock(registry.mutex)",
        "registry.atlases[id] = std::move(candidate)",
    )
    source_lookup = runtime.split("bool TryGetLuaRegisteredSpriteSource(", 1)[1]
    _require_in_order(
        source_lookup,
        "std::scoped_lock lock(registry.mutex)",
        "*image_path = found->second.canonical_image_path",
        "*revision = found->second.snapshot.revision",
    )

    for token in (
        'RegisterFunction(state, &LuaSpritesRegister, "register")',
        'RegisterFunction(state, &LuaSpritesUnregister, "unregister")',
        'RegisterFunction(state, &LuaSpritesGet, "get")',
        'RegisterFunction(state, &LuaSpritesList, "list")',
        'RegisterFunction(state, &LuaSpritesGetLimits, "get_limits")',
        'lua_setfield(state, -2, "sprites")',
        "RequireArgumentCount(state, 3, kApiName)",
        "mod->descriptor.root_path",
        'lua_setfield(state, -2, "revision")',
        'lua_setfield(state, -2, "local_only")',
        'lua_setfield(state, -2, "atlas_id_bytes")',
        'lua_setfield(state, -2, "bundle_bytes")',
        'lua_setfield(state, -2, "frame_geometry")',
    ):
        assert token in bindings, f"Lua sprite binding lacks: {token}"
    assert "RegisterLuaSpriteBindings(mod->state);" in binding_root
    assert "lua_createtable(mod->state, 0, 29);" in binding_root

    for token in (
        "TryGetLuaRegisteredSpriteInfo(",
        "TryGetLuaRegisteredSpriteSource(",
        "TryParseLuaDrawSpriteBundle(",
    ):
        assert token in draw_assets, f"draw/custom-atlas bridge lacks: {token}"
    assert "TryGetLuaDrawAtlasSource" in draw_header
    for token in (
        "cached.source_path != image_path || cached.revision != revision",
        "cached.texture->Release()",
        "PruneUnavailableAtlasTextures()",
        "TryGetLuaDrawAtlasSource(",
        "g_lua_draw_renderer.atlas_textures.erase(iterator)",
        "D3DPOOL_MANAGED",
    ):
        assert token in renderer, f"revisioned sprite renderer lacks: {token}"

    assert "ClearLuaDrawFrameForMod" in draw_runtime
    assert draw_runtime.count("ResetLuaSpriteRegistry();") == 2
    for capability in (
        '"sprites.local.register"',
        '"sprites.local.read"',
    ):
        assert capability in engine, f"Lua sprite capability lacks: {capability}"
    _require_in_order(
        engine,
        "ClearLuaDrawFrameForMod(mod->descriptor.id)",
        "ClearLuaSpriteAtlasesForMod(mod->descriptor.id)",
        "lua_close(mod->state)",
    )

    for item in (
        "include\\lua_sprite_runtime.h",
        "src\\lua_sprite_runtime.cpp",
        "src\\lua_engine_bindings_sprites.cpp",
    ):
        assert item in project, f"native project omits: {item}"
        assert item in filters, f"native project filters omit: {item}"

    for token in (
        'Directory.EnumerateFiles(rootPath, "*", SearchOption.AllDirectories)',
        "OrderBy(file => file.RelativePath, StringComparer.Ordinal)",
        'var record = $"{file.RelativePath}\\0{HashFile(file.FullPath)}\\n"',
    ):
        assert token in hasher, f"mod directory identity lacks: {token}"
    assert "ModContentHasher.HashDirectory(mod.RootPath)" in compatibility

    for token in (
        "## API",
        "## Asset sandbox",
        "## Bundle format and builder",
        "## Multiplayer and verification",
        "45-byte little-endian prefix",
        "failed replacement leaves the prior atlas intact",
        "first loaded",
    ):
        assert token in documentation, f"Lua sprite documentation lacks: {token}"
    assert "registered through [`sd.sprites`](lua-sprites.md)" in draw_documentation
    assert "**Implemented 2026-07-22.** `sd.sprites`" in roadmap

    for token in (
        '"id": "sample.lua.sprites_lab"',
        '"enabled": false',
        '"sprites.local.register"',
        '"draw.local.immediate"',
    ):
        assert token in manifest, f"sprite sample manifest lacks: {token}"
    for token in (
        "sd.sprites.register(",
        "sd.sprites.unregister(",
        "sd.sprites.get(\"lab\")",
        "sd.sprites.list()",
        "sd.sprites.get_limits()",
        "sd.draw.sprite(active_atlas.id",
    ):
        assert token in sample, f"sprite sample lacks: {token}"
    assert '"frames"' in descriptor
    assert "build_lua_sprite_bundle.py" in sample_readme

    for token in (
        'struct.pack(\n            "<ffffiIffffBI"',
        "MAX_FRAMES = 4096",
        "MAX_POINTS_PER_FRAME = 4096",
        "MAX_FRAME_GEOMETRY = 16_384",
        "MAX_BUNDLE_BYTES = 16 * 1024 * 1024",
        'set(document) != {"frames"}',
        "encoded_size > MAX_BUNDLE_BYTES",
        "return b\"\".join(encoded_frames)",
    ):
        assert token in builder, f"sprite bundle builder lacks: {token}"
    for token in (
        "capture_game_backbuffer(",
        "inspect_sprite_pixels(",
        "magenta_backdrop_pixels",
        "sprite_non_backdrop_pixels",
        'pcall(sd.sprites.unregister, "acceptance")',
        "replacement_revision",
        "traversal_rejected",
        "bundle_extension_rejected",
    ):
        assert token in verifier, f"live sprite verifier lacks: {token}"
    assert '"sprites": ("register", "unregister", "get", "list", "get_limits")' in runtime_verifier
    assert "check_call('sprites.list'" in runtime_verifier
    assert "check_call('sprites.get_limits'" in runtime_verifier
    for token in (
        "parse_bundle(path)",
        "inspect_sprite_pixels(path, 0, 0)",
        'mock.patch.object(bundle_builder, "MAX_BUNDLE_BYTES", 44)',
    ):
        assert token in tool_tests, f"sprite tool regression tests lack: {token}"

    return (
        "Lua mods own bounded, sandboxed, revisioned PNG/bundle atlases; draw-cache "
        "replacement, lifecycle cleanup, exact mod hashing, author tooling, docs, "
        "and live backbuffer acceptance are wired"
    )
