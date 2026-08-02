"""Contracts for the native world-render seam and overlay ownership boundary."""

from __future__ import annotations

from static_multiplayer_contract_support import ROOT, _read, _require_in_order


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
        "native_carrier_queue.inl"
    )
    world_renderer += _read(
        "SolomonDarkModLoader/src/lua_world_renderer/"
        "native_indicator_lane.inl"
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
    gameplay_hud = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "gameplay_hud_hooks.inl"
    )
    animation_advance = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/animation_advance_hook.inl"
    )
    dampen_effect = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/"
        "multiplayer_dampen_effect.inl"
    )
    debug_overlay = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay.cpp"
    ) + _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_surface_registry_and_frame_render.inl"
    ) + _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/public_api.inl"
    )
    showcase = _read("mods/lua_hud_showcase/scripts/main.lua")
    acceptance = _read("tools/verify_world_render_z_order.py")

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
            "post-scene world-indicator pass",
            "0x005C9BB0",
            "Actor-attached names and health bars",
            "Top-left ally rows and other screen HUD",
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
            "arena_render=0x0046EC80",
            "render_queue_flush=0x0068C480",
            "render_queue_insert=0x0068C3B0",
            "puppet_ctor=0x006287D0",
            "glyph_draw_at_position=0x004143D0",
            "native_texture_upload_bgra=0x00440F70",
            "native_texture_release=0x00420760",
            "native_render_page_register=0x0041FFE0",
            "native_renderer_global=0x00B401A8",
            "native_renderer_draw_state_offset=0x000001D0",
            "native_texture_critical_section=0x00B3F9DC",
            "native_texture_critical_section_initialized=0x00B40205",
            "native_renderer_set_color=0x0041FE50",
            "native_untextured_quad=0x0041DD70",
        ),
    )
    _require(
        "bounded semantic world display lists",
        world_header + world_runtime + events + engine,
        (
            "kLuaWorldRenderMaxSpritesPerMod = 256",
            "kLuaWorldRenderMaxGlobalSprites = 2048",
            "struct LuaWorldSpriteCommand",
            "struct LuaWorldMarkerCommand",
            "struct LuaWorldRenderFrameSnapshot",
            "BeginLuaWorldRenderFrame(mod->descriptor.id)",
            "CommitLuaWorldRenderFrame(mod->descriptor.id)",
            "ClearLuaWorldRenderFrameForMod(mod->descriptor.id)",
            "SubmitLuaWorldSpriteCommand",
            "SubmitLuaWorldMarkerCommand",
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
        "additive sd.world sprite and marker bindings",
        world_bindings + binding_registry,
        (
            "RegisterLuaWorldRenderBindings",
            "RegisterLuaWorldRenderBindings(state);",
            'RegisterFunction(state, &LuaWorldSprite, "sprite")',
            'RegisterFunction(state, &LuaWorldMarker, "marker")',
            '"sd.world.sprite"',
            '"sd.world.marker"',
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
        "native post-scene world indicator lane",
        world_renderer + gameplay_hud,
        (
            "HookNativeArenaRender",
            "GetX86HookTrampoline<NativeArenaRenderFn>",
            "original(self);",
            "reinterpret_cast<uintptr_t>(self) != player.world_address",
            "RenderGameplayWorldIndicatorsInNativePass();",
            "RenderLuaWorldMarkersInNativePass();",
            "native_renderer_set_color",
            "native_untextured_quad",
            "TryGetLuaCameraSnapshot({}, &camera)",
            "(world_x - camera.origin_x) * camera.scale",
            "(world_y - camera.origin_y) * camera.scale",
            "renderer + g_world_renderer.native_renderer_draw_state_offset",
            "DrawNativeWorldIndicatorHealthBar",
            "source=native_world_indicator",
            "health_bar=native",
        ),
    )
    _require_in_order(
        world_renderer,
        "original(self);",
        "RenderGameplayWorldIndicatorsInNativePass();",
        "RenderLuaWorldMarkersInNativePass();",
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
        "QueueDebugUiMultiplayerDampenPresentation",
        "BuildGameplayDampenPresentationRenderItems",
        "DrawGameplayDampenPresentation",
        "BuildGameplayParticipantHealthBarRenderItems",
        "source=dx9_nameplate_healthbar",
        "BeginDebugUiGameplayParticipantNameplateCapture",
        'surface_id = "gameplay_nameplate"',
    ):
        assert removed not in (
            item_header
            + item_runtime
            + vfx_helpers
            + native_hooks
            + draw_renderer
            + draw_helpers
            + debug_overlay
            + gameplay_hud
            + animation_advance
            + dampen_effect
        ), f"world-space overlay residue remains: {removed}"

    _require(
        "Dampen uses a native Y-sorted carrier",
        world_header + world_renderer + dampen_effect,
        (
            "QueueNativeWorldDampenPresentation",
            "NativeWorldDampenPresentation",
            "BuildNativeDampenRingGlyph",
            "Multiplayer Dampen native world presentation",
            "request.position_x",
            "request.position_y",
        ),
    )
    assert "DX9 presentation" not in debug_overlay + dampen_effect
    assert "D3DPT_LINESTRIP" not in debug_overlay

    _require(
        "in-repository world marker uses the native indicator API",
        showcase,
        ('sd.world.marker("YOU"',),
    )
    assert "sd.draw.world_to_screen" not in showcase
    assert "sd.draw.world_to_screen" not in acceptance
    for lua_path in sorted((ROOT / "mods").rglob("*.lua")):
        lua_source = lua_path.read_text(encoding="utf-8")
        assert "sd.draw.world_to_screen" not in lua_source, (
            "in-repository Lua content may not project a world-owned draw into "
            f"the overlay; use sd.world.sprite/marker: {lua_path}"
        )

    _require(
        "two-peer native world and indicator acceptance",
        acceptance,
        (
            'INSTANCE_NAME = "zrd"',
            "PORTS = (51755, 51756)",
            "wait_for_mpp_games_to_exit()",
            "netsh interface ipv4 show excludedportrange protocol=udp",
            'parser.add_argument("--expected-source-sha", required=True)',
            "verify_exact_source_and_artifacts",
            "verify_launched_processes_and_modules",
            "verify_campaign_port_owners",
            "wait_for_campaign_ports_unbound",
            '"native post-scene marker drawn"',
            '"generic_world_marker_both_peers": True',
            "probe_native_render_state",
            "ITEM_UID_OFFSET = 0x14",
            'label="indicator-host-actor-front"',
            'label="indicator-client-actor-front"',
            '"floating_bar_stock_indicator_semantics_both_peers": True',
            '"actor_front_occludes_both": True',
            '"actor_behind_is_occluded_by_both": True',
        ),
    )

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
            "native_world_renderer_required",
            "multiplayer::IsFoundationInitialized()",
            "InitializeLuaWorldRenderRuntime",
            "InitializeLuaWorldRenderer",
            "IsLuaCameraRuntimeAvailable()",
            "requires the Region camera runtime",
            'Log("Module path: " + GetModulePath(module_handle).string())',
            'write_failed_status("lua-world-renderer-failed"',
            "ShutdownLuaWorldRenderer",
            "RemoveX86Hook(&g_world_renderer.render_queue_flush_hook)",
            "RemoveX86Hook(&g_world_renderer.arena_render_hook)",
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
        r"src\lua_world_renderer\native_carrier_queue.inl",
        r"src\lua_world_renderer\native_indicator_lane.inl",
        r"src\lua_engine_bindings_world_render.cpp",
    ):
        assert item in project, f"native project omits: {item}"
        assert item in filters, f"native project filters omit: {item}"

    _require(
        "compatibility and publication boundary",
        design + item_docs,
        (
            "the Invincibility Potion does not",
            "No listing, republish, or release action",
            "showcase therefore needs republishing",
            "native `SpellGlow`",
        ),
    )

    return (
        "world sprites enter the native Y-sorted, light-tinted queue, world "
        "indicators use the native post-scene lane, and screen UI stays overlay-owned"
    )
