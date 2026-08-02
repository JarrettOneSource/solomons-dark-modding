"""Contracts for the native world-render seam and overlay ownership boundary."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def _require(label: str, text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    assert not missing, f"{label} lacks: {', '.join(missing)}"


def test_world_sprites_use_native_order_while_screen_ui_stays_overlay() -> str:
    re_note = _read("docs/re/world-sprite-render-pipeline.md")
    design = _read("docs/design/world-render-seam.md")
    draw_docs = _read("docs/lua-draw.md")
    item_docs = _read("docs/lua-items.md")
    world_header = _read(
        "SolomonDarkModLoader/include/lua_world_render_runtime.h"
    )
    world_runtime = _read(
        "SolomonDarkModLoader/src/lua_world_render_runtime.cpp"
    )
    world_renderer = _read(
        "SolomonDarkModLoader/src/lua_world_renderer.cpp"
    )
    world_renderer += _read(
        "SolomonDarkModLoader/src/lua_world_renderer/"
        "native_texture_bridge.inl"
    )
    world_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_world_render.cpp"
    )
    binding_registry = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings.cpp"
    ) + _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_internal.h"
    ) + _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    native_hooks = _read(
        "SolomonDarkModLoader/src/lua_item_native_hooks.cpp"
    )
    item_header = _read(
        "SolomonDarkModLoader/include/lua_item_runtime.h"
    )
    item_runtime = _read(
        "SolomonDarkModLoader/src/lua_item_runtime.cpp"
    )
    vfx_helpers = _read(
        "SolomonDarkModLoader/src/lua_item_runtime/"
        "consumable_vfx_helpers.inl"
    )
    draw_header = _read(
        "SolomonDarkModLoader/include/lua_draw_runtime.h"
    )
    draw_renderer = _read(
        "SolomonDarkModLoader/src/lua_draw_renderer.cpp"
    )
    draw_helpers = _read(
        "SolomonDarkModLoader/src/lua_draw_renderer/rendering_helpers.inl"
    )
    texture_loader = _read(
        "SolomonDarkModLoader/src/lua_draw_texture_loader.cpp"
    )
    draw_internal = _read(
        "SolomonDarkModLoader/src/lua_draw_internal.h"
    )
    loader = _read("SolomonDarkModLoader/src/mod_loader.cpp")
    loader += _read("SolomonDarkModLoader/src/mod_loader/initialize.inl")
    layout = _read("config/binary-layout.ini")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    filters = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters")

    _require(
        "evidence-first native ordering recovery",
        re_note + design,
        (
            "0x0068C3B0",
            "floor(object.world_y) + floor(object.sort_bias)",
            "0x0068C480",
            "0x00624B40",
            "0x006105F0",
            "0x004143D0",
            "larger world Y / sort bias renders later",
            "HUD indicators",
            "Boneyard picker",
            "`BOT PLAYING` label",
            "Loading screens",
        ),
    )
    _require(
        "layout-backed native world seams",
        layout,
        (
            "[lua_world_render]",
            "arena_render_queue_offset=0x17C",
            "render_queue_flush=0x0068C480",
            "render_queue_insert=0x0068C3B0",
            "puppet_ctor=0x006287D0",
            "glyph_draw_at_position=0x004143D0",
            "native_texture_upload_bgra=0x00440F70",
            "native_texture_release=0x00420760",
            "native_render_page_register=0x0041FFE0",
            "native_renderer_global=0x00B401A8",
            "native_texture_critical_section=0x00B3F9DC",
            "native_texture_critical_section_initialized=0x00B40205",
        ),
    )
    _require(
        "bounded semantic world display lists",
        world_header + world_runtime + events + engine,
        (
            "kLuaWorldRenderMaxSpritesPerMod = 256",
            "kLuaWorldRenderMaxGlobalSprites = 2048",
            "struct LuaWorldSpriteCommand",
            "struct LuaWorldRenderFrameSnapshot",
            "BeginLuaWorldRenderFrame(mod->descriptor.id)",
            "CommitLuaWorldRenderFrame(mod->descriptor.id)",
            "ClearLuaWorldRenderFrameForMod(mod->descriptor.id)",
            "SubmitLuaWorldSpriteCommand",
            "RefreshLuaWorldRenderFrameSnapshots",
            '"world.render.native"',
        ),
    )
    _require_in_order(
        events,
        "BeginLuaDrawFrame(mod->descriptor.id);",
        "BeginLuaWorldRenderFrame(mod->descriptor.id);",
        "DispatchLuaTimersToMod(mod, context);",
        "CommitLuaWorldRenderFrame(mod->descriptor.id);",
        "CommitLuaDrawFrame(mod->descriptor.id);",
    )
    _require(
        "additive sd.world sprite binding",
        world_bindings + binding_registry,
        (
            "RegisterLuaWorldRenderBindings",
            "RegisterLuaWorldRenderBindings(state);",
            'RegisterFunction(state, &LuaWorldSprite, "sprite")',
            '"sd.world.sprite"',
            "TryGetLuaDrawSpriteInfo",
            "SubmitLuaWorldSpriteCommand",
        ),
    )
    _require(
        "native queue carrier and common lighting dispatch",
        world_renderer,
        (
            "HookNativeRenderQueueFlush",
            "GetX86HookTrampoline<NativeRenderQueueFlushFn>",
            "TryGetPlayerState(&player)",
            "player.world_address + g_world_renderer.arena_render_queue_offset",
            "g_world_renderer.render_queue_insert(",
            "g_world_renderer.puppet_ctor(",
            "kPuppetWorldPositionXOffset = 0x18",
            "kPuppetWorldPositionYOffset = 0x1C",
            "kPuppetOwnerWorldOffset = 0x58",
            "kPuppetSortBiasOffset = 0xA0",
            "kPuppetBoundsPointerOffset = 0xC8",
            "kPuppetRenderDispatchVtableIndex = 3",
            "kPuppetPrimaryDrawVtableIndex = 7",
            "kPuppetSecondaryDrawVtableIndex = 8",
            "DrawWorldCarrierGlyph",
            "original(self, pass);",
        ),
    )
    _require_in_order(
        world_renderer,
        "InsertWorldSpriteCarriers(self, pass)",
        "original(self, pass);",
    )
    _require(
        "native registered-atlas texture bridge",
        world_renderer + texture_loader + draw_internal,
        (
            "DecodeLuaDrawTextureBgra",
            "GUID_WICPixelFormat32bppBGRA",
            "TryGetLuaDrawAtlasSource",
            "native_texture_upload_bgra",
            "native_render_page_register",
            "native_texture_release",
            "EnterCriticalSection",
            "LeaveCriticalSection",
            "BuildNativeWorldGlyph",
            "DrawLuaSpriteWithStockGeometry",
        ),
    )
    _require(
        "custom potion uses the intercepted native glyph lane",
        native_hooks + world_renderer,
        (
            "HookSpriteDrawAtPosition",
            "TryMatchCustomPotionSprite",
            "DrawLuaSpriteWithStockGeometry",
            "stock_health_sprite",
            "original(self, x, y)",
        ),
    )
    for removed in (
        "LuaConsumableRenderQuad",
        "QueueLuaConsumableRenderQuad",
        "TakeLuaConsumableRenderQuads",
        "BuildCustomPotionWorldQuad",
        "AppendConsumableActivationBurstQuads",
        "QueueConsumableQuad",
    ):
        assert removed not in (
            item_header
            + item_runtime
            + vfx_helpers
            + native_hooks
            + draw_renderer
            + draw_helpers
        ), f"world-space overlay residue remains: {removed}"

    _require(
        "native-only replicated potion VFX",
        item_runtime + vfx_helpers,
        (
            "LuaConsumableNativeVfxRequest",
            "active_native_vfx_pulses",
            "SpawnSpellGlowForParticipant",
            "kSpellGlowAnimationLayer = 75.0f",
            "kSpellGlowPulseIntervalMs = 16",
            "kSpellGlowPulseDurationMs = 4000",
        ),
    )

    assert "LuaWorldSpriteCommand" not in draw_header + draw_renderer
    assert "LuaWorldRenderFrameSnapshot" not in draw_header + draw_renderer
    assert "lua_camera_runtime.h" not in native_hooks
    assert "TryGetLuaCameraSnapshot" not in native_hooks + vfx_helpers

    _require(
        "screen overlay contract remains screen-owned",
        draw_docs + draw_renderer + draw_helpers,
        (
            "screen-space",
            "D3DRS_ZENABLE, FALSE",
            "D3DRS_ZWRITEENABLE, FALSE",
            "D3DRS_LIGHTING, FALSE",
            "RenderLuaDrawFrame",
            "RefreshLuaDrawFrameSnapshots",
        ),
    )
    for screen_owner in (
        "SolomonDarkModLoader/src/boneyard_picker/frontend_render.inl",
        "SolomonDarkModLoader/src/lua_developer_console.cpp",
    ):
        source = _read(screen_owner)
        _require(
            f"screen owner {screen_owner}",
            source,
            ("BeginLuaDrawFrame(", "CommitLuaDrawFrame("),
        )

    _require(
        "fail-closed renderer lifecycle",
        loader + world_renderer,
        (
            "InitializeLuaWorldRenderer",
            'write_failed_status("lua-world-renderer-failed"',
            "ShutdownLuaWorldRenderer",
            "RemoveX86Hook(&g_world_renderer.render_queue_flush_hook)",
        ),
    )
    _require_in_order(
        loader,
        "InitializeLuaEngine(runtime_bootstrap, &lua_engine_error)",
        "InitializeLuaWorldRenderer(&lua_world_renderer_error)",
        "InitializeLuaItemNativeHooks(&lua_item_hook_error)",
    )

    for item in (
        r"include\lua_world_render_runtime.h",
        r"src\lua_world_render_runtime.cpp",
        r"src\lua_world_renderer.cpp",
        r"src\lua_engine_bindings_world_render.cpp",
    ):
        assert item in project, f"native project omits: {item}"
        assert item in filters, f"native project filters omit: {item}"

    _require(
        "compatibility and publication boundary",
        design + item_docs,
        (
            "does not require an Invincibility Potion mod republish",
            "No listing or release action",
            "native `SpellGlow`",
        ),
    )

    return (
        "world sprites enter the native Y-sorted, light-tinted queue while "
        "HUD and other intentional screen UI remain exclusively in EndScene"
    )
