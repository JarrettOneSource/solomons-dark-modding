template <std::size_t Index>
void __fastcall HookFixedRegionRender(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<RegionRenderFn>(
        g_scene_capture.fixed_region_hooks[Index]);
    if (original == nullptr) {
        return;
    }
    NativeSceneCaptureBeginFrame(self, kFixedRegionNames[Index]);
    original(self);
    NativeSceneCaptureEndFrame(self);
}

void __fastcall HookNativeHudRender(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<NativeHudRenderFn>(
        g_scene_capture.hud_render_hook);
    if (original == nullptr) {
        FailActiveSceneCapture(
            "native HUD capture lost the retail HUD render trampoline");
        return;
    }
    BeginHudFrameCapture(self);
    original(self);
    if (g_scene_capture.frame_active &&
        g_scene_capture.frame.surface == CaptureSurface::Hud &&
        g_scene_capture.frame.hud.gameplay_address !=
            reinterpret_cast<uintptr_t>(self)) {
        FailActiveSceneCapture(
            "native HUD capture crossed gameplay objects during one render boundary");
    }
}

void OnNativeHudEndScene(IDirect3DDevice9* /*device*/) {
    if (g_scene_capture.frame_active &&
        g_scene_capture.frame.surface == CaptureSurface::Hud) {
        FinalizeActiveNativeSceneCapture();
    }
}

void __fastcall HookNativeHudSlotRender(
    void* self,
    void* /*unused_edx*/) {
    if (g_scene_capture.frame_active &&
        g_scene_capture.frame.surface == CaptureSurface::Hud) {
        if (g_scene_capture.frame.hud.slots.size() >= 64) {
            FailActiveSceneCapture(
                "native HUD capture exceeded its 64 rendered-slot bound");
        } else {
            HudSlotCapture capture;
            capture.draw_order = static_cast<std::uint32_t>(
                g_scene_capture.frame.draws.size());
            std::string slot_error;
            if (CaptureHudSlotState(self, &capture, &slot_error)) {
                g_scene_capture.frame.hud.slots.push_back(
                    std::move(capture));
            } else {
                FailActiveSceneCapture(std::move(slot_error));
            }
        }
    }
    const auto original = GetX86HookTrampoline<NativeHudSlotRenderFn>(
        g_scene_capture.hud_slot_render_hook);
    if (original != nullptr) {
        original(self);
    }
}

void __fastcall HookNativeHudStripRender(
    void* sprite,
    void* /*unused_edx*/,
    float x,
    float y,
    float width) {
    const auto original = GetX86HookTrampoline<NativeHudStripRenderFn>(
        g_scene_capture.hud_strip_render_hook);
    if (original == nullptr) {
        FailActiveSceneCapture(
            "native HUD capture lost the retail strip-render trampoline");
        return;
    }

    const bool capturing =
        g_scene_capture.frame_active &&
        g_scene_capture.frame.surface == CaptureSurface::Hud;
    const auto first_draw = g_scene_capture.frame.draws.size();
    original(sprite, x, y, width);
    if (!capturing || !g_scene_capture.frame_active ||
        g_scene_capture.frame.surface != CaptureSurface::Hud) {
        return;
    }
    if (g_scene_capture.frame.hud.strips.size() >= 32) {
        FailActiveSceneCapture(
            "native HUD capture exceeded its 32 rendered-strip bound");
        return;
    }
    if (!std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(width) || width < 0.0f) {
        FailActiveSceneCapture(
            "native HUD capture observed invalid strip geometry");
        return;
    }
    HudStripCapture capture;
    capture.art = ResolveNativeSceneArt(
        reinterpret_cast<uintptr_t>(sprite));
    capture.first_draw_order = static_cast<std::uint32_t>(first_draw);
    capture.draw_count = static_cast<std::uint32_t>(
        g_scene_capture.frame.draws.size() - first_draw);
    capture.x = x;
    capture.y = y;
    capture.width = width;
    g_scene_capture.frame.hud.strips.push_back(std::move(capture));
}

void __fastcall HookSceneRenderQueueInsert(
    void* self,
    void* /*unused_edx*/,
    int reference_y,
    void* object,
    int pass) {
    ObserveRenderQueueInsertion(self, reference_y, object, pass);
    const auto original = GetX86HookTrampoline<RenderQueueInsertFn>(
        g_scene_capture.render_queue_insert_hook);
    if (original != nullptr) {
        original(self, reference_y, object, pass);
    }
}

void __fastcall HookNativeSceneMeshDraw(
    void* self,
    void* /*unused_edx*/,
    float primitive_count,
    int vertex_count,
    int index_count,
    const float* vertices,
    const std::int16_t* indices) {
    ObserveNativeMesh(
        vertex_count,
        vertices,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original = GetX86HookTrampoline<NativeMeshDrawFn>(
        g_scene_capture.mesh_draw_hook);
    if (original != nullptr) {
        original(
            self,
            primitive_count,
            vertex_count,
            index_count,
            vertices,
            indices);
    }
}

void __fastcall HookNativeSceneUntexturedQuad(
    void* self,
    void* /*unused_edx*/,
    float x,
    float y,
    float width,
    float height) {
    ObserveNativeUntexturedQuad(
        x,
        y,
        width,
        height,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original = GetX86HookTrampoline<NativeUntexturedQuadFn>(
        g_scene_capture.untextured_quad_hook);
    if (original != nullptr) {
        original(self, x, y, width, height);
    }
}

void __fastcall HookNativeSceneClear(
    void* self,
    void* /*unused_edx*/,
    float red,
    float green,
    float blue,
    float alpha) {
    ObserveNativeClear(
        red,
        green,
        blue,
        alpha,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original = GetX86HookTrampoline<NativeClearFn>(
        g_scene_capture.clear_hook);
    if (original != nullptr) {
        original(self, red, green, blue, alpha);
    }
}

void __fastcall HookNativeSceneRoadRender(
    void* self,
    void* /*unused_edx*/) {
    g_scene_capture_mesh_objects.push_back(
        MeshObjectContext{"road", reinterpret_cast<uintptr_t>(self)});
    const auto original = GetX86HookTrampoline<NativeObjectRenderFn>(
        g_scene_capture.road_render_hook);
    if (original != nullptr) {
        original(self);
    }
    g_scene_capture_mesh_objects.pop_back();
}

void __fastcall HookNativeSceneTerrainRender(
    void* self,
    void* /*unused_edx*/) {
    g_scene_capture_mesh_objects.push_back(
        MeshObjectContext{"terrain", reinterpret_cast<uintptr_t>(self)});
    const auto original = GetX86HookTrampoline<NativeObjectRenderFn>(
        g_scene_capture.terrain_render_hook);
    if (original != nullptr) {
        original(self);
    }
    g_scene_capture_mesh_objects.pop_back();
}

void RemoveNativeSceneCaptureHooks() {
    if (g_scene_capture.hud_end_scene_callback_registered) {
        RemoveD3d9FrameCallback(&OnNativeHudEndScene);
        g_scene_capture.hud_end_scene_callback_registered = false;
    }
    RemoveX86Hook(&g_scene_capture.hud_strip_render_hook);
    RemoveX86Hook(&g_scene_capture.hud_slot_render_hook);
    RemoveX86Hook(&g_scene_capture.hud_render_hook);
    RemoveX86Hook(&g_scene_capture.terrain_render_hook);
    RemoveX86Hook(&g_scene_capture.road_render_hook);
    RemoveX86Hook(&g_scene_capture.clear_hook);
    RemoveX86Hook(&g_scene_capture.untextured_quad_hook);
    RemoveX86Hook(&g_scene_capture.mesh_draw_hook);
    RemoveX86Hook(&g_scene_capture.render_queue_insert_hook);
    for (auto& hook : g_scene_capture.fixed_region_hooks) {
        RemoveX86Hook(&hook);
    }
}

bool TryGetNativeSceneLayoutValue(
    const char* key,
    uintptr_t* value) {
    return key != nullptr && value != nullptr &&
        TryGetBinaryLayoutNumericValue(kLayoutSection, key, value) &&
        *value != 0;
}

bool InstallNativeSceneCaptureHooks(std::string* error_message) {
    // These retail 0w0e addresses belong only to the opt-in G9 observation
    // surface. Keeping them local avoids adding HUD-only keys to the shared
    // binary-layout file whose exact bytes are provenance for older goldens.
    constexpr uintptr_t kHudRenderAddress = 0x005D2520;
    constexpr uintptr_t kHudSlotRenderAddress = 0x005D3E10;
    constexpr uintptr_t kHudStripRenderAddress = 0x00415230;
    constexpr uintptr_t kGameplayGlobalAddress = 0x0081C264;
    constexpr std::array<const char*, 5> kFixedRegionLayoutKeys = {
        "courtyard_render",
        "mortuary_render",
        "storeroom_render",
        "library_render",
        "office_render",
    };
    const std::array<void*, 5> kFixedRegionDetours = {
        reinterpret_cast<void*>(&HookFixedRegionRender<0>),
        reinterpret_cast<void*>(&HookFixedRegionRender<1>),
        reinterpret_cast<void*>(&HookFixedRegionRender<2>),
        reinterpret_cast<void*>(&HookFixedRegionRender<3>),
        reinterpret_cast<void*>(&HookFixedRegionRender<4>),
    };

    std::array<uintptr_t, 5> fixed_region_targets = {};
    uintptr_t render_queue_insert = 0;
    uintptr_t native_mesh_draw = 0;
    uintptr_t native_untextured_quad = 0;
    uintptr_t native_clear = 0;
    uintptr_t road_render = 0;
    uintptr_t terrain_render = 0;
    uintptr_t native_renderer_global = 0;
    uintptr_t native_renderer_draw_state_offset = 0;
    uintptr_t hud_render = kHudRenderAddress;
    uintptr_t hud_slot_render = kHudSlotRenderAddress;
    uintptr_t hud_strip_render = kHudStripRenderAddress;
    uintptr_t gameplay_global = kGameplayGlobalAddress;
    for (std::size_t index = 0; index < fixed_region_targets.size(); ++index) {
        if (!TryGetNativeSceneLayoutValue(
                kFixedRegionLayoutKeys[index],
                &fixed_region_targets[index])) {
            if (error_message != nullptr) {
                *error_message = std::string(
                    "native scene capture layout is missing ") +
                    kFixedRegionLayoutKeys[index];
            }
            return false;
        }
    }
    if (!TryGetNativeSceneLayoutValue(
            "render_queue_insert", &render_queue_insert) ||
        !TryGetNativeSceneLayoutValue(
            "native_mesh_draw", &native_mesh_draw) ||
        !TryGetNativeSceneLayoutValue(
            "native_untextured_quad", &native_untextured_quad) ||
        !TryGetNativeSceneLayoutValue("native_clear", &native_clear) ||
        !TryGetNativeSceneLayoutValue("road_render", &road_render) ||
        !TryGetNativeSceneLayoutValue("terrain_render", &terrain_render) ||
        !TryGetNativeSceneLayoutValue(
            "native_renderer_global", &native_renderer_global) ||
        !TryGetNativeSceneLayoutValue(
            "native_renderer_draw_state_offset",
            &native_renderer_draw_state_offset)) {
        if (error_message != nullptr) {
            *error_message =
                "native scene capture primitive layout is incomplete";
        }
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    for (auto& target : fixed_region_targets) {
        target = memory.ResolveGameAddressOrZero(target);
    }
    render_queue_insert =
        memory.ResolveGameAddressOrZero(render_queue_insert);
    native_mesh_draw = memory.ResolveGameAddressOrZero(native_mesh_draw);
    native_untextured_quad =
        memory.ResolveGameAddressOrZero(native_untextured_quad);
    native_clear = memory.ResolveGameAddressOrZero(native_clear);
    road_render = memory.ResolveGameAddressOrZero(road_render);
    terrain_render = memory.ResolveGameAddressOrZero(terrain_render);
    native_renderer_global =
        memory.ResolveGameAddressOrZero(native_renderer_global);
    if (g_scene_capture.surface == CaptureSurface::Hud) {
        hud_render = memory.ResolveGameAddressOrZero(hud_render);
        hud_slot_render =
            memory.ResolveGameAddressOrZero(hud_slot_render);
        hud_strip_render =
            memory.ResolveGameAddressOrZero(hud_strip_render);
        gameplay_global =
            memory.ResolveGameAddressOrZero(gameplay_global);
    }

    std::vector<uintptr_t> executable_targets = {
        fixed_region_targets[0],
        fixed_region_targets[1],
        fixed_region_targets[2],
        fixed_region_targets[3],
        fixed_region_targets[4],
        render_queue_insert,
        native_mesh_draw,
        native_untextured_quad,
        native_clear,
        road_render,
        terrain_render,
    };
    if (g_scene_capture.surface == CaptureSurface::Hud) {
        executable_targets.push_back(hud_render);
        executable_targets.push_back(hud_slot_render);
        executable_targets.push_back(hud_strip_render);
    }
    if (std::any_of(
            executable_targets.begin(),
            executable_targets.end(),
            [&](uintptr_t address) {
                return address == 0 || !memory.IsExecutableRange(address, 1);
            }) ||
        native_renderer_global == 0 ||
        !memory.IsReadableRange(
            native_renderer_global, sizeof(uintptr_t)) ||
        (g_scene_capture.surface == CaptureSurface::Hud &&
         (gameplay_global == 0 ||
          !memory.IsReadableRange(
              gameplay_global, sizeof(uintptr_t))))) {
        if (error_message != nullptr) {
            *error_message =
                "native scene capture targets failed executable/readable validation";
        }
        return false;
    }

    g_scene_capture.native_renderer_global = native_renderer_global;
    g_scene_capture.native_renderer_draw_state_offset =
        static_cast<std::size_t>(native_renderer_draw_state_offset);
    g_scene_capture.hud_gameplay_global = gameplay_global;

    struct SceneHookInstall {
        uintptr_t target = 0;
        void* detour = nullptr;
        X86Hook* hook = nullptr;
        const char* claim = nullptr;
    };
    std::vector<SceneHookInstall> hooks;
    hooks.reserve(14);
    for (std::size_t index = 0; index < fixed_region_targets.size(); ++index) {
        hooks.push_back(SceneHookInstall{
            fixed_region_targets[index],
            kFixedRegionDetours[index],
            &g_scene_capture.fixed_region_hooks[index],
            kFixedRegionLayoutKeys[index],
        });
    }
    hooks.push_back(SceneHookInstall{
        render_queue_insert,
        reinterpret_cast<void*>(&HookSceneRenderQueueInsert),
        &g_scene_capture.render_queue_insert_hook,
        "render_queue_insert",
    });
    hooks.push_back(SceneHookInstall{
        native_mesh_draw,
        reinterpret_cast<void*>(&HookNativeSceneMeshDraw),
        &g_scene_capture.mesh_draw_hook,
        "native_mesh_draw",
    });
    hooks.push_back(SceneHookInstall{
        native_untextured_quad,
        reinterpret_cast<void*>(&HookNativeSceneUntexturedQuad),
        &g_scene_capture.untextured_quad_hook,
        "native_untextured_quad",
    });
    hooks.push_back(SceneHookInstall{
        native_clear,
        reinterpret_cast<void*>(&HookNativeSceneClear),
        &g_scene_capture.clear_hook,
        "native_clear",
    });
    hooks.push_back(SceneHookInstall{
        road_render,
        reinterpret_cast<void*>(&HookNativeSceneRoadRender),
        &g_scene_capture.road_render_hook,
        "road_render",
    });
    hooks.push_back(SceneHookInstall{
        terrain_render,
        reinterpret_cast<void*>(&HookNativeSceneTerrainRender),
        &g_scene_capture.terrain_render_hook,
        "terrain_render",
    });
    if (g_scene_capture.surface == CaptureSurface::Hud) {
        hooks.push_back(SceneHookInstall{
            hud_render,
            reinterpret_cast<void*>(&HookNativeHudRender),
            &g_scene_capture.hud_render_hook,
            "hud_render",
        });
        hooks.push_back(SceneHookInstall{
            hud_slot_render,
            reinterpret_cast<void*>(&HookNativeHudSlotRender),
            &g_scene_capture.hud_slot_render_hook,
            "hud_slot_render",
        });
        hooks.push_back(SceneHookInstall{
            hud_strip_render,
            reinterpret_cast<void*>(&HookNativeHudStripRender),
            &g_scene_capture.hud_strip_render_hook,
            "hud_strip_render",
        });
    }

    for (const auto& hook : hooks) {
        std::string hook_error;
        if (InstallSafeX86Hook(
                reinterpret_cast<void*>(hook.target),
                hook.detour,
                5,
                hook.hook,
                &hook_error)) {
            continue;
        }
        RemoveNativeSceneCaptureHooks();
        if (error_message != nullptr) {
            *error_message = std::string(
                "native scene capture could not install ") +
                hook.claim + " hook: " + hook_error;
        }
        return false;
    }
    return true;
}
