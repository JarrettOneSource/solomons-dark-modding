const char* CapturePhaseLabel(CapturePhase phase) {
    switch (phase) {
        case CapturePhase::PreQueue:
            return "pre-queue";
        case CapturePhase::SortedQueue:
            return "sorted-queue";
        case CapturePhase::PostQueue:
            return "post-queue";
    }
    return "unknown";
}

const char* CaptureSurfaceLabel(CaptureSurface surface) {
    switch (surface) {
        case CaptureSurface::Scene:
            return "scene";
        case CaptureSurface::Hud:
            return "hud";
    }
    return "unknown";
}

std::string NativeSceneSequenceLabel(
    std::string_view base_label,
    std::uint32_t frame_index,
    std::uint32_t frame_count) {
    if (frame_count == 1) {
        return std::string(base_label);
    }
    std::ostringstream stream;
    stream << base_label << "-frame-" << std::setw(4)
           << std::setfill('0') << frame_index;
    return stream.str();
}

uintptr_t EffectiveCallerAddress(uintptr_t immediate_caller) {
    return g_scene_capture_callers.empty()
        ? immediate_caller
        : g_scene_capture_callers.back();
}

bool TryReadFloatRect(
    uintptr_t base,
    std::size_t offset,
    std::array<float, 4>* rect) {
    return rect != nullptr &&
        ProcessMemory::Instance().TryRead(
            base + offset,
            rect->data(),
            sizeof(*rect)) &&
        std::all_of(
            rect->begin(),
            rect->end(),
            [](float value) { return std::isfinite(value); });
}

CameraCapture ReadCameraCapture(uintptr_t region) {
    CameraCapture camera;
    (void)TryReadFloatRect(
        region, kRegionWorldBoundsOffset, &camera.world_bounds);
    (void)TryReadFloatRect(
        region, kRegionPrimaryViewOffset, &camera.primary_view);
    (void)TryReadFloatRect(
        region, kRegionExpandedViewOffset, &camera.expanded_view);
    (void)TryReadFloatRect(
        region, kRegionCullingViewOffset, &camera.culling_view);
    (void)TryReadRuntimeField(region, kRegionScaleOffset, &camera.scale);
    (void)TryReadRuntimeField(
        region,
        kRegionShakeMagnitudeOffset,
        &camera.shake_magnitude);
    (void)TryReadRuntimeField(
        region,
        kRegionShakeAccumulatorOffset,
        &camera.shake_accumulator);
    return camera;
}

bool IsRunnableCameraCapture(const CameraCapture& camera) {
    return std::isfinite(camera.scale) && camera.scale > 0.0f &&
        std::all_of(
            camera.primary_view.begin(),
            camera.primary_view.end(),
            [](float value) { return std::isfinite(value); }) &&
        camera.primary_view[2] > 0.0f &&
        camera.primary_view[3] > 0.0f;
}

void ObserveHudCameraBoundary(void* region) {
    if (g_scene_capture.surface != CaptureSurface::Hud || region == nullptr) {
        return;
    }
    const auto region_address = reinterpret_cast<uintptr_t>(region);
    const auto camera = ReadCameraCapture(region_address);
    g_scene_capture.last_region = region_address;
    g_scene_capture.last_camera = camera;
    g_scene_capture.last_camera_available = IsRunnableCameraCapture(camera);
    if (g_scene_capture.status != "armed") {
        return;
    }
    uintptr_t gameplay = 0;
    if (!g_scene_capture.last_camera_available ||
        g_scene_capture.hud_gameplay_global == 0 ||
        !ProcessMemory::Instance().TryReadValue(
            g_scene_capture.hud_gameplay_global, &gameplay) ||
        gameplay == 0) {
        FailActiveSceneCapture(
            "native HUD capture reached the scene-overlay boundary without a runnable gameplay object");
        return;
    }
    BeginHudFrameCapture(reinterpret_cast<void*>(gameplay));
}

std::string ReadCaptureInstanceName() {
    char value[512] = {};
    const auto length = GetEnvironmentVariableA(
        kInstanceEnvironment,
        value,
        static_cast<DWORD>(sizeof(value)));
    return length > 0 && length < sizeof(value)
        ? std::string(value, length)
        : std::string{};
}

std::array<float, 4> RectFromQuad(const std::array<float, 8>& quad) {
    std::array<float, 4> rect = {
        (std::numeric_limits<float>::max)(),
        (std::numeric_limits<float>::max)(),
        (std::numeric_limits<float>::lowest)(),
        (std::numeric_limits<float>::lowest)(),
    };
    for (std::size_t index = 0; index < 4; ++index) {
        rect[0] = (std::min)(rect[0], quad[index * 2]);
        rect[1] = (std::min)(rect[1], quad[index * 2 + 1]);
        rect[2] = (std::max)(rect[2], quad[index * 2]);
        rect[3] = (std::max)(rect[3], quad[index * 2 + 1]);
    }
    return rect;
}

std::array<float, 4> ClipScreenRect(
    const std::array<float, 4>& rect) {
    const float viewport_right =
        g_scene_capture.frame.camera.primary_view[2] *
        g_scene_capture.frame.camera.scale;
    const float viewport_bottom =
        g_scene_capture.frame.camera.primary_view[3] *
        g_scene_capture.frame.camera.scale;
    std::array<float, 4> clipped = {
        (std::max)(rect[0], 0.0f),
        (std::max)(rect[1], 0.0f),
        (std::min)(rect[2], viewport_right),
        (std::min)(rect[3], viewport_bottom),
    };
    std::array<float, 4> renderer_clip = {};
    if (g_scene_capture.frame.surface == CaptureSurface::Hud &&
        TryReadRendererClipRect(&renderer_clip)) {
        clipped[0] = (std::max)(clipped[0], renderer_clip[0]);
        clipped[1] = (std::max)(clipped[1], renderer_clip[1]);
        clipped[2] = (std::min)(clipped[2], renderer_clip[2]);
        clipped[3] = (std::min)(clipped[3], renderer_clip[3]);
    }
    return clipped;
}

bool AddressInRange(
    uintptr_t address,
    uintptr_t first,
    uintptr_t one_past_last) {
    return address >= first && address < one_past_last;
}

bool IsTopLevelPreQueueCaller(uintptr_t preferred_address) {
    const auto& scene = g_scene_capture.frame.scene_kind;
    if (scene == "arena") {
        return AddressInRange(preferred_address, 0x0046EC80, 0x00470B00);
    }
    if (scene == "courtyard") {
        return AddressInRange(preferred_address, 0x0051EB60, 0x00520D00);
    }
    if (scene == "mortuary") {
        return AddressInRange(preferred_address, 0x0050EAC0, 0x00511000);
    }
    if (scene == "storeroom") {
        return AddressInRange(preferred_address, 0x00519070, 0x00519E40);
    }
    if (scene == "library") {
        return AddressInRange(preferred_address, 0x00511320, 0x00514000);
    }
    if (scene == "office") {
        return AddressInRange(preferred_address, 0x00519E40, 0x0051D000);
    }
    return false;
}

bool IsWorldSpaceUiArt(const ResolvedNativeArt& art) {
    return art.atlas == "UI" || art.atlas == "Fonts" ||
        art.atlas == "ControlPanel" || art.atlas == "Skills";
}

bool CoversMostOfViewport(const DrawCapture& draw) {
    const auto viewport_width =
        g_scene_capture.frame.camera.primary_view[2];
    const auto viewport_height =
        g_scene_capture.frame.camera.primary_view[3];
    const auto width = draw.screen_rect[2] - draw.screen_rect[0];
    const auto height = draw.screen_rect[3] - draw.screen_rect[1];
    return viewport_width > 0.0f && viewport_height > 0.0f &&
        width >= viewport_width * 0.9f && height >= viewport_height * 0.9f;
}

std::string ClassifySceneRole(const DrawCapture& draw) {
    if (g_scene_capture.frame.surface == CaptureSurface::Hud) {
        return "screen-overlay";
    }
    if (draw.draw_kind == "clear") {
        return "framebuffer-clear";
    }
    if (g_scene_capture.phase == CapturePhase::SortedQueue) {
        return "shared-world-object";
    }
    if (g_scene_capture.phase == CapturePhase::PreQueue) {
        if (IsTopLevelPreQueueCaller(draw.caller_preferred_address)) {
            return g_scene_capture.frame.scene_kind == "arena"
                ? "terrain-base"
                : "background-backdrop";
        }
        return "scene-underlay-art";
    }
    if (draw.draw_kind == "untextured-quad" ||
        CoversMostOfViewport(draw)) {
        return "screen-overlay";
    }
    if (IsWorldSpaceUiArt(draw.art) ||
        AddressInRange(
            draw.caller_preferred_address,
            0x005D08C0,
            0x005D1100)) {
        return "world-space-ui";
    }
    return "overhead-art";
}

std::string ClassifySceneLayer(const DrawCapture& draw) {
    if (g_scene_capture.frame.surface == CaptureSurface::Hud) {
        return "screen-overlay";
    }
    if (draw.draw_kind == "clear") {
        return "framebuffer-clear";
    }
    if (g_scene_capture.phase == CapturePhase::PreQueue) {
        return "scene-underlay";
    }
    if (g_scene_capture.phase == CapturePhase::SortedQueue) {
        return "world-sorted";
    }
    if (draw.draw_kind == "untextured-quad" ||
        CoversMostOfViewport(draw)) {
        return "screen-overlay";
    }
    return "scene-overdraw";
}

SortCapture BuildSortCapture(
    void* queue,
    int reference_y,
    void* object,
    int pass,
    std::uint32_t gather_index) {
    SortCapture sort;
    if (queue == nullptr || object == nullptr || pass < 0) {
        return sort;
    }
    const auto queue_address = reinterpret_cast<uintptr_t>(queue);
    const auto object_address = reinterpret_cast<uintptr_t>(object);
    if (!TryReadRuntimeField(
            object_address,
            kObjectWorldYOffset,
            &sort.world_y) ||
        !TryReadRuntimeField(
            object_address,
            kObjectSortBiasOffset,
            &sort.sort_bias) ||
        !std::isfinite(sort.world_y) || !std::isfinite(sort.sort_bias)) {
        return sort;
    }
    std::int32_t origin = 0;
    std::int32_t bucket_count = 0;
    if (!ProcessMemory::Instance().TryReadValue(queue_address, &origin) ||
        !ProcessMemory::Instance().TryReadValue(
            queue_address + static_cast<uintptr_t>(pass) * 0x48 + 0x18,
            &bucket_count)) {
        return sort;
    }

    sort.present = true;
    sort.gather_index = gather_index;
    sort.pass = pass;
    sort.queue_origin = origin;
    sort.queue_bucket_count = bucket_count;
    sort.reference_y = reference_y;
    sort.floor_world_y = static_cast<std::int32_t>(std::floor(sort.world_y));
    sort.floor_sort_bias =
        static_cast<std::int32_t>(std::floor(sort.sort_bias));
    sort.relative =
        sort.floor_world_y + sort.floor_sort_bias - reference_y;
    sort.bucket_offset = sort.relative / 2;
    sort.bucket_index = origin + sort.bucket_offset;
    sort.lane = sort.bucket_index < 0
        ? "leading-overflow"
        : (sort.bucket_index >= bucket_count
               ? "trailing-overflow"
               : "normal");
    return sort;
}

const SortCapture* FindCurrentSortCapture(uintptr_t object_address) {
    if (object_address == 0) {
        return nullptr;
    }
    for (std::size_t index = g_scene_capture.frame.insertion_objects.size();
         index > 0;
         --index) {
        if (g_scene_capture.frame.insertion_objects[index - 1] ==
            object_address) {
            return &g_scene_capture.frame.insertions[index - 1];
        }
    }
    return nullptr;
}

void PopulateObjectAndSort(DrawCapture* draw) {
    if (draw == nullptr || g_scene_capture_objects.empty()) {
        return;
    }
    const auto object = g_scene_capture_objects.back();
    draw->object_address = object;
    (void)TryReadRuntimeField(
        object, kObjectTypeOffset, &draw->object_type);
    (void)TryReadRuntimeField(
        object, kObjectWorldXOffset, &draw->object_world_x);
    (void)TryReadRuntimeField(
        object, kObjectWorldYOffset, &draw->object_world_y);
    if (TryReadRuntimeField(
            object,
            kObjectLightingScalarOffset,
            &draw->lighting_scalar) &&
        std::isfinite(draw->lighting_scalar)) {
        draw->has_lighting_scalar = true;
    }
    if (const auto* sort = FindCurrentSortCapture(object); sort != nullptr) {
        draw->sort = *sort;
    }
}

void PopulateProjectedWorldQuad(DrawCapture* draw) {
    if (draw == nullptr || draw->layer == "framebuffer-clear" ||
        draw->layer == "screen-overlay") {
        return;
    }
    const auto& camera = g_scene_capture.frame.camera;
    if (!std::isfinite(camera.scale) || camera.scale <= 0.0f) {
        return;
    }
    for (std::size_t index = 0; index < 4; ++index) {
        draw->inverse_projected_world_quad[index * 2] =
            camera.primary_view[0] +
            draw->screen_quad[index * 2] / camera.scale;
        draw->inverse_projected_world_quad[index * 2 + 1] =
            camera.primary_view[1] +
            draw->screen_quad[index * 2 + 1] / camera.scale;
    }
}

void ScaleLogicalQuadToScreenPixels(DrawCapture* draw) {
    if (draw == nullptr || draw->layer == "framebuffer-clear") {
        return;
    }
    if (g_scene_capture.frame.surface == CaptureSurface::Hud) {
        return;
    }
    const auto scale = g_scene_capture.frame.camera.scale;
    if (!std::isfinite(scale) || scale <= 0.0f) {
        return;
    }
    for (auto& coordinate : draw->screen_quad) {
        coordinate *= scale;
    }
}

void CompleteDrawCapture(DrawCapture* draw) {
    if (draw == nullptr) {
        return;
    }
    draw->phase = CapturePhaseLabel(g_scene_capture.phase);
    draw->tint = ReadRendererTint();
    draw->blend = ReadBlendState();
    // Glyph/TextQuad and mesh hooks see the renderer's logical camera-space
    // coordinates. Classify in those units, then resolve physical pixels.
    draw->screen_rect = RectFromQuad(draw->screen_quad);
    PopulateObjectAndSort(draw);
    draw->layer = ClassifySceneLayer(*draw);
    draw->semantic_role = ClassifySceneRole(*draw);
    ScaleLogicalQuadToScreenPixels(draw);
    draw->screen_rect = RectFromQuad(draw->screen_quad);
    draw->clipped_screen_rect = ClipScreenRect(draw->screen_rect);
    draw->visible =
        draw->clipped_screen_rect[2] > draw->clipped_screen_rect[0] &&
        draw->clipped_screen_rect[3] > draw->clipped_screen_rect[1];
    PopulateProjectedWorldQuad(draw);
}

void FailActiveSceneCapture(std::string message) {
    g_scene_capture.status = "failed";
    g_scene_capture.error_message = std::move(message);
    g_scene_capture.frame_active = false;
}

void AppendDrawCapture(DrawCapture draw) {
    if (!g_scene_capture.frame_active) {
        return;
    }
    if (g_scene_capture.frame.draws.size() >= kMaximumDrawsPerFrame) {
        FailActiveSceneCapture(
            "native scene capture exceeded the 32768-draw frame limit");
        return;
    }
    draw.order =
        static_cast<std::uint32_t>(g_scene_capture.frame.draws.size());
    CompleteDrawCapture(&draw);
    g_scene_capture.frame.draws.push_back(std::move(draw));
}

bool CaptureHudFrameState(
    uintptr_t gameplay_address,
    std::string* error_message) {
    auto& frame = g_scene_capture.frame;
    auto& hud = frame.hud;
    hud = HudCapture{};
    hud.gameplay_address = gameplay_address;

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || !player.valid ||
        player.actor_address == 0 || player.progression_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture reached the retail renderer without a runnable local player state";
        }
        return false;
    }
    frame.player = player;
    frame.player_available = true;
    hud.available = true;
    hud.actor_address = player.actor_address;
    hud.progression_address = player.progression_address;
    hud.simulation_tick = player.local_player_tick_count;
    hud.hp = player.hp;
    hud.max_hp = player.max_hp;
    hud.mp = player.mp;
    hud.max_mp = player.max_mp;
    hud.xp = player.xp;
    hud.level = player.level;
    hud.gold = player.gold;
    hud.persistent_status_flags = player.persistent_status_flags;
    hud.transient_status_flags = player.transient_status_flags;
    hud.poison_remaining_ticks = player.poison_remaining_ticks;
    hud.webbed_remaining_ticks = player.webbed_remaining_ticks;
    hud.damage_x4_remaining_ticks = player.damage_x4_remaining_ticks;

    std::uint8_t dead = 0;
    std::uint8_t score_visible = 0;
    std::uint8_t vitals_visible = 0;
    std::int32_t pending_choice_a = 0;
    std::int32_t pending_choice_b = 0;
    uintptr_t featured_enemy = 0;
    std::int32_t ally_count = 0;
    std::int32_t ally_capacity = 0;
    uintptr_t ally_rows = 0;
    if (!TryReadRuntimeField(player.actor_address, 0x160, &dead) ||
        !TryReadRuntimeField(
            player.actor_address, 0x1C4, &hud.magic_shield_current) ||
        !TryReadRuntimeField(
            player.actor_address, 0x1C8, &hud.magic_shield_maximum) ||
        !TryReadRuntimeField(
            player.progression_address, 0x740, &hud.mana_reserve) ||
        !TryReadRuntimeField(gameplay_address, 0x1AC3, &score_visible) ||
        !TryReadRuntimeField(gameplay_address, 0x1AC4, &vitals_visible) ||
        !TryReadRuntimeField(
            player.progression_address, 0x44, &pending_choice_a) ||
        !TryReadRuntimeField(
            player.progression_address, 0x48, &pending_choice_b) ||
        !TryReadRuntimeField(
            gameplay_address, 0x1C2C, &featured_enemy) ||
        !TryReadRuntimeField(gameplay_address, 0x1C14, &ally_rows) ||
        !TryReadRuntimeField(gameplay_address, 0x1C18, &ally_capacity) ||
        !TryReadRuntimeField(gameplay_address, 0x1C20, &ally_count)) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture could not read the retail HUD state at its render boundary";
        }
        return false;
    }
    const std::array<float, 4> finite_hud_values = {
        hud.magic_shield_current,
        hud.magic_shield_maximum,
        hud.mana_reserve,
        hud.mp,
    };
    if (!std::all_of(
            finite_hud_values.begin(),
            finite_hud_values.end(),
            [](float value) { return std::isfinite(value); })) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture observed non-finite retail vitals or charge state";
        }
        return false;
    }
    hud.local_dead = dead != 0;
    hud.score_indicator_visible = score_visible != 0;
    hud.vitals_and_slots_visible = vitals_visible != 0;
    hud.level_up_choice_active = pending_choice_a + pending_choice_b != 0;
    hud.featured_enemy_available = featured_enemy != 0;

    SDModWorldState world;
    if (TryGetWorldState(&world) && world.valid) {
        hud.world_available = true;
        hud.wave = world.wave;
    }

    if (ally_count < 0 || ally_count > 32 || ally_capacity < ally_count ||
        (ally_count > 0 && ally_rows == 0)) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture observed an invalid ally-bar vector instead of guessing its rows";
        }
        return false;
    }
    hud.ally_bars.reserve(static_cast<std::size_t>(ally_count));
    for (std::int32_t index = 0; index < ally_count; ++index) {
        uintptr_t glyph = 0;
        float health_ratio = 0.0f;
        const auto row = ally_rows + static_cast<uintptr_t>(index) * 8;
        if (!ProcessMemory::Instance().TryReadValue(row, &glyph) ||
            !ProcessMemory::Instance().TryReadValue(
                row + sizeof(std::uint32_t), &health_ratio) ||
            glyph == 0 || !std::isfinite(health_ratio)) {
            if (error_message != nullptr) {
                *error_message =
                    "native HUD capture could not resolve every stock ally-bar row";
            }
            return false;
        }
        HudAllyBarCapture ally;
        ally.glyph = ResolveNativeSceneArt(glyph);
        ally.health_ratio = health_ratio;
        hud.ally_bars.push_back(std::move(ally));
    }
    return true;
}

bool CaptureHudSlotState(
    void* slot,
    HudSlotCapture* capture,
    std::string* error_message) {
    if (slot == nullptr || capture == nullptr) {
        return false;
    }
    const auto address = reinterpret_cast<uintptr_t>(slot);
    float x = 0.0f;
    float y = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
    if (!TryReadRuntimeField(address, 0xB4, &capture->kind_id) ||
        !TryReadRuntimeField(address, 0x14, &x) ||
        !TryReadRuntimeField(address, 0x18, &y) ||
        !TryReadRuntimeField(address, 0x1C, &width) ||
        !TryReadRuntimeField(address, 0x20, &height) ||
        !TryReadRuntimeField(address, 0x78, &capture->selection_flag) ||
        !TryReadRuntimeField(address, 0xB8, &capture->skill_id) ||
        !TryReadRuntimeField(address, 0xBC, &capture->item_value) ||
        !TryReadRuntimeField(address, 0xC0, &capture->presentation_value) ||
        !TryReadRuntimeField(address, 0xE4, &capture->count) ||
        !TryReadRuntimeField(address, 0xE8, &capture->input_slot) ||
        !std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(width) || !std::isfinite(height) ||
        !std::isfinite(capture->presentation_value)) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture could not read a rendered belt-slot state";
        }
        return false;
    }
    capture->object_address = address;
    capture->rect = {x, y, x + width, y + height};
    if (capture->kind_id != 0x1B67 || capture->skill_id < 0) {
        return true;
    }

    const auto progression = g_scene_capture.frame.hud.progression_address;
    uintptr_t entries = 0;
    std::int32_t entry_count = 0;
    if (progression == 0 ||
        !TryReadRuntimeField(progression, 0x20, &entries) ||
        !TryReadRuntimeField(progression, 0x24, &entry_count) ||
        capture->skill_id >= entry_count || entries == 0) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture could not resolve the rendered skill slot in the progression table";
        }
        return false;
    }
    const auto entry = entries +
        static_cast<uintptr_t>(capture->skill_id) * 0x70;
    if (!TryReadRuntimeField(
            entry, 0x64, &capture->cooldown_current) ||
        !TryReadRuntimeField(
            entry, 0x68, &capture->cooldown_capacity) ||
        !std::isfinite(capture->cooldown_current) ||
        !std::isfinite(capture->cooldown_capacity)) {
        if (error_message != nullptr) {
            *error_message =
                "native HUD capture could not read the rendered skill cooldown pair";
        }
        return false;
    }
    capture->cooldown_available = true;
    return true;
}

void BeginHudFrameCapture(void* gameplay) {
    if (!g_scene_capture.initialized ||
        g_scene_capture.surface != CaptureSurface::Hud ||
        g_scene_capture.status != "armed" || gameplay == nullptr) {
        return;
    }
    if (!g_scene_capture.last_camera_available ||
        g_scene_capture.last_region == 0) {
        FailActiveSceneCapture(
            "native HUD capture reached the HUD renderer before a runnable scene camera boundary");
        return;
    }

    g_scene_capture.frame = SceneFrameCapture{};
    auto& frame = g_scene_capture.frame;
    frame.label = g_scene_capture.pending_label;
    frame.surface = CaptureSurface::Hud;
    frame.scene_kind = "gameplay_hud";
    frame.instance = ReadCaptureInstanceName();
    frame.region = g_scene_capture.last_region;
    frame.sequence_index = g_scene_capture.captured_frame_count;
    frame.render_observed_ms = GetTickCount64();
    frame.player_fixed_tick_animation.swap(
        g_scene_capture.pending_player_fixed_tick_animation);
    frame.camera = g_scene_capture.last_camera;
    std::string state_error;
    if (!CaptureHudFrameState(
            reinterpret_cast<uintptr_t>(gameplay), &state_error)) {
        FailActiveSceneCapture(std::move(state_error));
        return;
    }

    g_scene_capture.active_label = g_scene_capture.pending_label;
    g_scene_capture.pending_label.clear();
    g_scene_capture.status = "capturing";
    g_scene_capture.error_message.clear();
    g_scene_capture.frame_active = true;
    g_scene_capture.phase = CapturePhase::PostQueue;
    g_pending_sprite_draws.clear();
    g_scene_capture_callers.clear();
    g_scene_capture_objects.clear();
    g_scene_capture_mesh_objects.clear();
    g_pending_exact_text_captures.clear();
}

void FinalizeActiveNativeSceneCapture() {
    if (!g_scene_capture.frame_active) {
        g_pending_sprite_draws.clear();
        g_scene_capture_callers.clear();
        g_scene_capture_objects.clear();
        g_scene_capture_mesh_objects.clear();
        g_pending_exact_text_captures.clear();
        return;
    }
    if (!g_pending_exact_text_captures.empty()) {
        FailActiveSceneCapture(
            "native scene capture observed an imbalanced exact-text render stack");
    } else if (g_scene_capture.frame.draws.empty()) {
        g_scene_capture.pending_label = g_scene_capture.frame.label;
        g_scene_capture.active_label.clear();
        g_scene_capture.frame_active = false;
        g_scene_capture.status = "armed";
        g_scene_capture.error_message.clear();
    } else {
        std::string write_error;
        if (WriteNativeSceneCaptureFile(&write_error)) {
            ++g_scene_capture.captured_frame_count;
            g_scene_capture.error_message.clear();
            g_scene_capture.frame_active = false;
            if (g_scene_capture.captured_frame_count <
                g_scene_capture.requested_frame_count) {
                g_scene_capture.pending_label = NativeSceneSequenceLabel(
                    g_scene_capture.sequence_base_label,
                    g_scene_capture.captured_frame_count,
                    g_scene_capture.requested_frame_count);
                g_scene_capture.status = "armed";
            } else {
                g_scene_capture.status = "complete";
            }
        } else {
            FailActiveSceneCapture(std::move(write_error));
        }
    }
    g_pending_sprite_draws.clear();
    g_scene_capture_callers.clear();
    g_scene_capture_objects.clear();
    g_scene_capture_mesh_objects.clear();
    g_pending_exact_text_captures.clear();
}

ResolvedNativeArt MakeSyntheticArt(
    std::string id,
    std::string atlas,
    std::string resolution) {
    ResolvedNativeArt art;
    art.id = std::move(id);
    art.atlas = std::move(atlas);
    art.resolution = std::move(resolution);
    return art;
}

void ObserveNativeClear(
    float red,
    float green,
    float blue,
    float alpha,
    uintptr_t caller_address) {
    if (!g_scene_capture.frame_active) {
        return;
    }
    DrawCapture draw;
    draw.draw_kind = "clear";
    draw.caller_preferred_address =
        PreferredAddress(EffectiveCallerAddress(caller_address));
    draw.art = MakeSyntheticArt(
        "native.framebuffer-clear",
        "native-renderer",
        "native-clear-call");
    draw.tint = {red, green, blue, alpha};
    const auto width =
        g_scene_capture.frame.camera.primary_view[2] *
        g_scene_capture.frame.camera.scale;
    const auto height =
        g_scene_capture.frame.camera.primary_view[3] *
        g_scene_capture.frame.camera.scale;
    draw.screen_quad = {0.0f, 0.0f, width, 0.0f, width, height, 0.0f, height};
    const auto draw_count_before = g_scene_capture.frame.draws.size();
    AppendDrawCapture(std::move(draw));
    if (g_scene_capture.frame.draws.size() == draw_count_before + 1) {
        g_scene_capture.frame.draws.back().tint = {red, green, blue, alpha};
    }
}

void ObserveNativeUntexturedQuad(
    float x,
    float y,
    float width,
    float height,
    uintptr_t caller_address) {
    if (!g_scene_capture.frame_active) {
        return;
    }
    float base_x = 0.0f;
    float base_y = 0.0f;
    (void)TryReadRendererBase(&base_x, &base_y);
    const auto left = x + base_x;
    const auto top = y + base_y;
    const auto right = left + width;
    const auto bottom = top + height;
    DrawCapture draw;
    draw.draw_kind = "untextured-quad";
    draw.caller_preferred_address =
        PreferredAddress(EffectiveCallerAddress(caller_address));
    draw.art = MakeSyntheticArt(
        "native.untextured-quad",
        "native-renderer",
        "native-untextured-quad-call");
    draw.transform_kind = "position-size";
    draw.submitted_position = {x, y};
    draw.screen_quad = {
        left, top, right, top, right, bottom, left, bottom};
    AppendDrawCapture(std::move(draw));
}

ResolvedNativeArt ResolveMeshArt(uintptr_t caller_preferred_address) {
    if (!g_scene_capture_mesh_objects.empty()) {
        const auto context = g_scene_capture_mesh_objects.back();
        if (std::string_view(context.kind) == "road") {
            std::uint8_t selector = 0;
            (void)TryReadRuntimeField(context.object, 0x8C, &selector);
            constexpr const char* kRoadTextures[] = {
                "road.png",
                "road2.png",
                "road3.png",
                "road4.png",
                "road5.png",
            };
            const auto id = selector <
                    sizeof(kRoadTextures) / sizeof(kRoadTextures[0])
                ? std::string(kRoadTextures[selector])
                : "road.invalid-selector-" + std::to_string(selector);
            auto art = MakeSyntheticArt(
                id, "loose-road-texture", "road-object-selector");
            art.sprite_index = selector;
            return art;
        }
        if (std::string_view(context.kind) == "terrain") {
            std::uint32_t selector = 0;
            (void)TryReadRuntimeField(context.object, 0xC0, &selector);
            auto art = MakeSyntheticArt(
                "terrain-texture." + std::to_string(selector),
                "generated-terrain",
                "terrain-object-selector");
            art.sprite_index = static_cast<std::int32_t>(selector);
            return art;
        }
    }
    std::ostringstream id;
    id << "native.mesh@0x" << std::hex << std::uppercase
       << caller_preferred_address;
    return MakeSyntheticArt(
        id.str(), "native-generated-mesh", "native-mesh-callsite");
}

void ObserveNativeMesh(
    int vertex_count,
    const float* vertices,
    uintptr_t caller_address) {
    if (!g_scene_capture.frame_active || vertex_count <= 0 ||
        vertex_count > 65536 || vertices == nullptr) {
        return;
    }
    std::vector<float> copied(static_cast<std::size_t>(vertex_count) * 6);
    if (!ProcessMemory::Instance().TryRead(
            reinterpret_cast<uintptr_t>(vertices),
            copied.data(),
            copied.size() * sizeof(float))) {
        FailActiveSceneCapture(
            "native scene mesh vertices became unreadable during capture");
        return;
    }
    float base_x = 0.0f;
    float base_y = 0.0f;
    (void)TryReadRendererBase(&base_x, &base_y);
    std::array<float, 4> rect = {
        (std::numeric_limits<float>::max)(),
        (std::numeric_limits<float>::max)(),
        (std::numeric_limits<float>::lowest)(),
        (std::numeric_limits<float>::lowest)(),
    };
    for (int index = 0; index < vertex_count; ++index) {
        const auto x = copied[static_cast<std::size_t>(index) * 6] + base_x;
        const auto y = copied[static_cast<std::size_t>(index) * 6 + 1] + base_y;
        rect[0] = (std::min)(rect[0], x);
        rect[1] = (std::min)(rect[1], y);
        rect[2] = (std::max)(rect[2], x);
        rect[3] = (std::max)(rect[3], y);
    }
    DrawCapture draw;
    draw.draw_kind = "indexed-mesh";
    draw.caller_preferred_address =
        PreferredAddress(EffectiveCallerAddress(caller_address));
    draw.art = ResolveMeshArt(draw.caller_preferred_address);
    draw.screen_quad = {
        rect[0], rect[1], rect[2], rect[1], rect[2], rect[3], rect[0], rect[3]};
    AppendDrawCapture(std::move(draw));
}

void BeginSceneFrameCapture(void* region, const char* scene_kind) {
    if (!g_scene_capture.initialized ||
        g_scene_capture.status != "armed" || region == nullptr ||
        scene_kind == nullptr) {
        return;
    }
    g_scene_capture.frame = SceneFrameCapture{};
    g_scene_capture.frame.surface = CaptureSurface::Scene;
    g_scene_capture.frame.label = g_scene_capture.pending_label;
    g_scene_capture.frame.scene_kind = scene_kind;
    g_scene_capture.frame.instance = ReadCaptureInstanceName();
    g_scene_capture.frame.region = reinterpret_cast<uintptr_t>(region);
    g_scene_capture.frame.sequence_index =
        g_scene_capture.captured_frame_count;
    g_scene_capture.frame.render_observed_ms = GetTickCount64();
    g_scene_capture.frame.player_fixed_tick_animation.swap(
        g_scene_capture.pending_player_fixed_tick_animation);
    CaptureAnimationActors(&g_scene_capture.frame);
    if (g_scene_capture.status == "failed") {
        return;
    }
    g_scene_capture.frame.camera = ReadCameraCapture(
        g_scene_capture.frame.region);
    g_scene_capture.active_label = g_scene_capture.pending_label;
    g_scene_capture.pending_label.clear();
    g_scene_capture.status = "capturing";
    g_scene_capture.error_message.clear();
    g_scene_capture.frame_active = true;
    g_scene_capture.phase = CapturePhase::PreQueue;
    g_pending_sprite_draws.clear();
    g_scene_capture_callers.clear();
    g_scene_capture_objects.clear();
    g_scene_capture_mesh_objects.clear();
}

void ObserveRenderQueueInsertion(
    void* queue,
    int reference_y,
    void* object,
    int pass) {
    if (!g_scene_capture.frame_active || queue == nullptr || object == nullptr) {
        return;
    }
    std::uint8_t pending_remove = 1;
    if (!TryReadRuntimeField(
            reinterpret_cast<uintptr_t>(object),
            kObjectPendingRemoveOffset,
            &pending_remove) ||
        pending_remove != 0) {
        return;
    }
    const auto gather_index = static_cast<std::uint32_t>(
        g_scene_capture.frame.insertions.size());
    g_scene_capture.frame.insertions.push_back(BuildSortCapture(
        queue, reference_y, object, pass, gather_index));
    g_scene_capture.frame.insertion_objects.push_back(
        reinterpret_cast<uintptr_t>(object));
}

void BeginSceneSpriteDraw(
    void* sprite,
    const char* draw_kind,
    float x,
    float y,
    const float* transform,
    uintptr_t caller_address) {
    if (!g_scene_capture.frame_active || sprite == nullptr ||
        draw_kind == nullptr) {
        return;
    }
    PendingSpriteDraw pending;
    pending.sprite_address = reinterpret_cast<uintptr_t>(sprite);
    pending.caller_address =
        EffectiveCallerAddress(caller_address);
    pending.draw_kind = draw_kind;
    pending.x = x;
    pending.y = y;
    if (transform != nullptr &&
        ProcessMemory::Instance().TryRead(
            reinterpret_cast<uintptr_t>(transform),
            pending.transform.data(),
            sizeof(pending.transform))) {
        pending.has_transform = true;
    }
    g_pending_sprite_draws.push_back(std::move(pending));
}

void ObserveSceneTexturedQuad(
    const float* destination_vertices,
    uintptr_t caller_address) {
    if (!g_scene_capture.frame_active || destination_vertices == nullptr) {
        return;
    }
    std::array<float, 8> vertices = {};
    if (!ProcessMemory::Instance().TryRead(
            reinterpret_cast<uintptr_t>(destination_vertices),
            vertices.data(),
            sizeof(vertices))) {
        FailActiveSceneCapture(
            "native scene textured-quad vertices became unreadable during capture");
        return;
    }
    float base_x = 0.0f;
    float base_y = 0.0f;
    (void)TryReadRendererBase(&base_x, &base_y);
    for (std::size_t index = 0; index < 4; ++index) {
        vertices[index * 2] += base_x;
        vertices[index * 2 + 1] += base_y;
    }

    DrawCapture draw;
    draw.draw_kind = "textured-quad";
    draw.screen_quad = vertices;
    if (!g_pending_sprite_draws.empty()) {
        const auto& pending = g_pending_sprite_draws.back();
        draw.draw_kind = pending.draw_kind;
        draw.caller_preferred_address =
            PreferredAddress(pending.caller_address);
        draw.art = ResolveNativeSceneArt(pending.sprite_address);
        draw.submitted_position = {pending.x, pending.y};
        if (pending.has_transform) {
            draw.transform_kind = "matrix4x4";
            draw.submitted_matrix = pending.transform;
        } else {
            draw.transform_kind = "position";
        }
    } else {
        draw.caller_preferred_address = PreferredAddress(
            EffectiveCallerAddress(caller_address));
        std::ostringstream id;
        id << "native.textured-quad@0x" << std::hex << std::uppercase
           << draw.caller_preferred_address;
        draw.art = MakeSyntheticArt(
            id.str(),
            "native-texture-batch",
            "text-quad-without-sprite-owner");
        draw.transform_kind = "submitted-quad";
    }
    AppendDrawCapture(std::move(draw));
}
