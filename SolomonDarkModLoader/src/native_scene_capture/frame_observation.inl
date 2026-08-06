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
