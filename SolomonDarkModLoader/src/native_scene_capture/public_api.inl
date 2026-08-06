bool IsNativeSceneCaptureRequested() {
    char value[32768] = {};
    const auto length = GetEnvironmentVariableA(
        kCaptureDirectoryEnvironment,
        value,
        static_cast<DWORD>(sizeof(value)));
    return length > 0 && length < sizeof(value);
}

bool InitializeNativeSceneCapture(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_scene_capture.initialized) {
        return true;
    }
    g_scene_capture.requested = IsNativeSceneCaptureRequested();
    if (!g_scene_capture.requested) {
        g_scene_capture.status = "unavailable";
        return true;
    }
    if (error_message == nullptr) {
        return false;
    }

    char surface_value[16] = {};
    const auto surface_length = GetEnvironmentVariableA(
        kCaptureSurfaceEnvironment,
        surface_value,
        static_cast<DWORD>(sizeof(surface_value)));
    if (surface_length == 0) {
        g_scene_capture.surface = CaptureSurface::Scene;
    } else if (surface_length >= sizeof(surface_value)) {
        *error_message =
            "native scene capture surface exceeds its 15-character bound";
        g_scene_capture.status = "failed";
        g_scene_capture.error_message = *error_message;
        return false;
    } else {
        const std::string_view surface(surface_value, surface_length);
        if (surface == "scene") {
            g_scene_capture.surface = CaptureSurface::Scene;
        } else if (surface == "hud") {
            g_scene_capture.surface = CaptureSurface::Hud;
        } else {
            *error_message =
                "native scene capture surface must be exactly scene or hud";
            g_scene_capture.status = "failed";
            g_scene_capture.error_message = *error_message;
            return false;
        }
    }

    char directory_value[32768] = {};
    const auto directory_length = GetEnvironmentVariableA(
        kCaptureDirectoryEnvironment,
        directory_value,
        static_cast<DWORD>(sizeof(directory_value)));
    if (directory_length == 0 ||
        directory_length >= sizeof(directory_value)) {
        *error_message =
            "native scene capture directory is missing or exceeds the Windows environment limit";
        g_scene_capture.status = "failed";
        g_scene_capture.error_message = *error_message;
        return false;
    }

    try {
        g_scene_capture.directory = std::filesystem::u8path(
            std::string(directory_value, directory_length));
        std::filesystem::create_directories(g_scene_capture.directory);
        const auto write_probe =
            g_scene_capture.directory / ".native-scene-capture-write-probe";
        {
            std::ofstream stream(
                write_probe, std::ios::binary | std::ios::trunc);
            stream << "native-scene-capture-write-probe\n";
            stream.flush();
            if (!stream) {
                *error_message =
                    "native scene capture directory exists but cannot write a probe file";
                g_scene_capture.status = "failed";
                g_scene_capture.error_message = *error_message;
                return false;
            }
        }
        std::error_code remove_error;
        if (!std::filesystem::remove(write_probe, remove_error) ||
            remove_error) {
            *error_message =
                "native scene capture directory wrote but could not remove its probe file";
            g_scene_capture.status = "failed";
            g_scene_capture.error_message = *error_message;
            return false;
        }
    } catch (const std::exception& ex) {
        *error_message = std::string(
            "native scene capture directory is not runnable: ") + ex.what();
        g_scene_capture.status = "failed";
        g_scene_capture.error_message = *error_message;
        return false;
    }

    g_scene_capture.runtime_image_base =
        ProcessMemory::Instance().ModuleBase();
    if (g_scene_capture.runtime_image_base == 0 ||
        !InstallNativeSceneCaptureHooks(error_message)) {
        if (error_message->empty()) {
            *error_message =
                "native scene capture could not resolve the running game image";
        }
        RemoveNativeSceneCaptureHooks();
        g_scene_capture.status = "failed";
        g_scene_capture.error_message = *error_message;
        return false;
    }
    if (g_scene_capture.surface == CaptureSurface::Hud) {
        constexpr uintptr_t kD3d9DevicePointerGlobalAddress = 0x00B401E8;
        const auto device_pointer_global = ProcessMemory::Instance()
            .ResolveGameAddressOrZero(kD3d9DevicePointerGlobalAddress);
        if (device_pointer_global == 0 ||
            !InstallD3d9FrameHook(
                device_pointer_global,
                &OnNativeHudEndScene,
                error_message)) {
            if (error_message->empty()) {
                *error_message =
                    "native HUD capture could not register its EndScene boundary";
            }
            RemoveNativeSceneCaptureHooks();
            g_scene_capture.status = "failed";
            g_scene_capture.error_message = *error_message;
            return false;
        }
        g_scene_capture.hud_end_scene_callback_registered = true;
    }

    g_scene_capture.initialized = true;
    g_scene_capture.status = "idle";
    g_scene_capture.error_message.clear();
    Log(
        "Native scene capture initialized. surface=" +
        std::string(CaptureSurfaceLabel(g_scene_capture.surface)) +
        " directory=" + g_scene_capture.directory.string());
    return true;
}

void ShutdownNativeSceneCapture() {
    RemoveNativeSceneCaptureHooks();
    g_pending_sprite_draws.clear();
    g_scene_capture_callers.clear();
    g_scene_capture_objects.clear();
    g_scene_capture_mesh_objects.clear();
    g_pending_exact_text_captures.clear();
    g_scene_capture = NativeSceneCaptureState{};
}

bool QueueNativeSceneCapture(
    std::string_view label,
    std::string* error_message) {
    return QueueNativeSceneCaptureSequence(label, 1, error_message);
}

bool QueueNativeSceneCaptureSequence(
    std::string_view label,
    std::uint32_t frame_count,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (error_message == nullptr) {
        return false;
    }
    if (!g_scene_capture.requested || !g_scene_capture.initialized) {
        *error_message =
            "native scene capture is unavailable; launch with SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY";
        return false;
    }
    if (frame_count == 0 || frame_count > 512) {
        *error_message =
            "native scene capture sequence must request 1-512 render frames";
        return false;
    }
    if (g_scene_capture.status == "armed" ||
        g_scene_capture.status == "capturing") {
        *error_message =
            "native scene capture is busy with label " +
            (g_scene_capture.pending_label.empty()
                 ? g_scene_capture.active_label
                 : g_scene_capture.pending_label);
        return false;
    }
    if (label.empty() || label.size() > 96 ||
        !std::all_of(
            label.begin(),
            label.end(),
            [](unsigned char character) {
                return std::isalnum(character) != 0 || character == '-' ||
                    character == '_';
            })) {
        *error_message =
            "native scene capture label must be 1-96 ASCII letters, digits, hyphens, or underscores";
        return false;
    }

    for (std::uint32_t index = 0; index < frame_count; ++index) {
        const auto frame_label = NativeSceneSequenceLabel(
            label, index, frame_count);
        const auto output =
            g_scene_capture.directory / (frame_label + ".json");
        const auto temporary =
            g_scene_capture.directory / (frame_label + ".json.tmp");
        std::error_code exists_error;
        const bool output_exists =
            std::filesystem::exists(output, exists_error);
        if (exists_error) {
            *error_message =
                "native scene capture could not inspect a sequence output path";
            return false;
        }
        const bool temporary_exists =
            std::filesystem::exists(temporary, exists_error);
        if (exists_error) {
            *error_message =
                "native scene capture could not inspect a sequence temporary path";
            return false;
        }
        if (output_exists || temporary_exists) {
            *error_message =
                "native scene capture refuses to overwrite any sequence output or temporary file";
            return false;
        }
    }

    RebuildNativeSceneArtResolver();
    if (g_scene_capture.art_by_address.empty()) {
        *error_message =
            "native scene capture atlas resolver is runnable but no native atlas records are loaded";
        g_scene_capture.status = "failed";
        g_scene_capture.error_message = *error_message;
        return false;
    }
    g_scene_capture.sequence_base_label.assign(label.begin(), label.end());
    g_scene_capture.requested_frame_count = frame_count;
    g_scene_capture.captured_frame_count = 0;
    g_scene_capture.pending_player_fixed_tick_animation.clear();
    g_scene_capture.pending_label = NativeSceneSequenceLabel(
        label, 0, frame_count);
    g_scene_capture.active_label.clear();
    g_scene_capture.output_path.clear();
    g_scene_capture.error_message.clear();
    g_scene_capture.frame = SceneFrameCapture{};
    g_scene_capture.status = "armed";
    return true;
}

bool TryGetNativeSceneCaptureStatus(NativeSceneCaptureStatus* status) {
    if (status == nullptr) {
        return false;
    }
    status->requested = g_scene_capture.requested;
    status->initialized = g_scene_capture.initialized;
    status->state = g_scene_capture.status;
    status->surface = CaptureSurfaceLabel(g_scene_capture.surface);
    status->label = g_scene_capture.pending_label.empty()
        ? g_scene_capture.active_label
        : g_scene_capture.pending_label;
    status->output_path = g_scene_capture.output_path;
    status->error_message = g_scene_capture.error_message;
    status->draw_count = static_cast<std::uint32_t>(
        g_scene_capture.frame.draws.size());
    status->requested_frame_count =
        g_scene_capture.requested_frame_count;
    status->captured_frame_count =
        g_scene_capture.captured_frame_count;
    return true;
}

void NativeSceneCaptureObservePlayerFixedTick(
    std::uintptr_t actor_address,
    std::uint64_t simulation_tick) {
    if (!g_scene_capture.initialized || actor_address == 0 ||
        simulation_tick == 0 ||
        (g_scene_capture.status != "armed" &&
         g_scene_capture.status != "capturing")) {
        return;
    }
    if (g_scene_capture.pending_player_fixed_tick_animation.size() >=
        kMaximumFixedTickAnimationSamples) {
        FailActiveSceneCapture(
            "native scene capture fixed-tick animation history exceeded its 4096-sample bound");
        return;
    }

    PlayerFixedTickAnimationCapture capture;
    capture.tick = simulation_tick;
    capture.observed_ms = GetTickCount64();
    if (!TryGetPlayerState(&capture.player) ||
        capture.player.actor_address != actor_address ||
        !TryReadRuntimeField(
            actor_address,
            0x1BC,
            &capture.animation_duration_ticks) ||
        !TryReadRuntimeField(
            actor_address,
            0x22C,
            &capture.render_frame_state) ||
        !TryReadRuntimeField(
            actor_address,
            0xE4,
            &capture.action_count)) {
        FailActiveSceneCapture(
            "native scene capture could not read the local player fixed-tick animation state");
        return;
    }
    if (capture.action_count == 1) {
        uintptr_t action_list = 0;
        uintptr_t control = 0;
        uintptr_t action = 0;
        if (!TryReadRuntimeField(
                actor_address, 0xF0, &action_list) ||
            action_list == 0 ||
            !ProcessMemory::Instance().TryReadValue(
                action_list, &control) ||
            control == 0 ||
            !ProcessMemory::Instance().TryReadValue(control, &action) ||
            action == 0 ||
            !TryReadRuntimeField(action, 0x14, &capture.action_id) ||
            !TryReadRuntimeField(
                action, 0x30, &capture.action_progress)) {
            FailActiveSceneCapture(
                "native scene capture could not resolve the local player fixed-tick action");
            return;
        }
    }
    capture.player.local_player_tick_count = simulation_tick;
    capture.player.local_player_tick_observed_ms = capture.observed_ms;
    g_scene_capture.pending_player_fixed_tick_animation.push_back(
        std::move(capture));
}

void NativeSceneCaptureBeginFrame(void* region, const char* scene_kind) {
    if (g_scene_capture.surface == CaptureSurface::Hud) {
        return;
    }
    BeginSceneFrameCapture(region, scene_kind);
}

void NativeSceneCaptureEndFrame(void* region) {
    if (g_scene_capture.surface == CaptureSurface::Hud) {
        ObserveHudCameraBoundary(region);
        return;
    }
    if (!g_scene_capture.initialized || region == nullptr ||
        g_scene_capture.frame.region != reinterpret_cast<uintptr_t>(region)) {
        return;
    }
    g_scene_capture.frame.camera = ReadCameraCapture(
        g_scene_capture.frame.region);
    FinalizeActiveNativeSceneCapture();
}

void NativeSceneCaptureBeginSortedQueue(void* queue, int pass) {
    if (!g_scene_capture.frame_active || queue == nullptr || pass < 0) {
        return;
    }
    g_scene_capture.phase = CapturePhase::SortedQueue;
}

void NativeSceneCaptureEndSortedQueue(void* queue, int pass) {
    if (!g_scene_capture.frame_active || queue == nullptr || pass < 0) {
        return;
    }
    g_scene_capture.phase = CapturePhase::PostQueue;
}

void NativeSceneCaptureBeginWorldObject(void* object) {
    if (g_scene_capture.frame_active && object != nullptr) {
        g_scene_capture_objects.push_back(
            reinterpret_cast<uintptr_t>(object));
    }
}

void NativeSceneCaptureEndWorldObject(void* object) {
    if (!g_scene_capture.frame_active || object == nullptr ||
        g_scene_capture_objects.empty()) {
        return;
    }
    if (g_scene_capture_objects.back() !=
        reinterpret_cast<uintptr_t>(object)) {
        FailActiveSceneCapture(
            "native scene capture observed an imbalanced world-object render stack");
        g_scene_capture_objects.clear();
        return;
    }
    g_scene_capture_objects.pop_back();
}

void NativeSceneCapturePushCaller(std::uintptr_t caller_address) {
    if (g_scene_capture.frame_active && caller_address != 0) {
        g_scene_capture_callers.push_back(caller_address);
    }
}

void NativeSceneCapturePopCaller() {
    if (g_scene_capture.frame_active &&
        !g_scene_capture_callers.empty()) {
        g_scene_capture_callers.pop_back();
    }
}

void NativeSceneCaptureBeginSpriteDraw(
    void* sprite,
    const char* draw_kind,
    float x,
    float y,
    const float* transform,
    std::uintptr_t caller_address) {
    BeginSceneSpriteDraw(
        sprite, draw_kind, x, y, transform, caller_address);
}

void NativeSceneCaptureObserveTexturedQuad(
    const float* destination_vertices,
    const float* /*texture_vertices*/,
    std::uintptr_t caller_address) {
    ObserveSceneTexturedQuad(destination_vertices, caller_address);
}

void NativeSceneCaptureEndSpriteDraw() {
    if (g_scene_capture.frame_active && !g_pending_sprite_draws.empty()) {
        g_pending_sprite_draws.pop_back();
    }
}

void NativeSceneCaptureBeginExactText(
    std::string_view text,
    std::uintptr_t caller_address) {
    if (!g_scene_capture.frame_active) {
        return;
    }
    if (text.size() > 4096) {
        FailActiveSceneCapture(
            "native scene capture exact-text run exceeded its 4096-byte bound");
        return;
    }
    PendingExactTextCapture capture;
    capture.text.assign(text.begin(), text.end());
    capture.caller_address = caller_address;
    capture.first_draw_index = g_scene_capture.frame.draws.size();
    g_pending_exact_text_captures.push_back(std::move(capture));
}

void NativeSceneCaptureEndExactText() {
    if (!g_scene_capture.frame_active ||
        g_pending_exact_text_captures.empty()) {
        return;
    }
    auto pending = std::move(g_pending_exact_text_captures.back());
    g_pending_exact_text_captures.pop_back();
    ExactTextCapture capture;
    capture.text = std::move(pending.text);
    capture.caller_preferred_address =
        PreferredAddress(pending.caller_address);
    capture.first_draw_order = static_cast<std::uint32_t>(
        pending.first_draw_index);
    const auto end = g_scene_capture.frame.draws.size();
    capture.draw_count = static_cast<std::uint32_t>(
        end - pending.first_draw_index);
    if (capture.draw_count != 0) {
        capture.screen_rect = {
            (std::numeric_limits<float>::max)(),
            (std::numeric_limits<float>::max)(),
            (std::numeric_limits<float>::lowest)(),
            (std::numeric_limits<float>::lowest)(),
        };
        for (std::size_t index = pending.first_draw_index;
             index < end;
             ++index) {
            const auto& rect =
                g_scene_capture.frame.draws[index].screen_rect;
            capture.screen_rect[0] =
                (std::min)(capture.screen_rect[0], rect[0]);
            capture.screen_rect[1] =
                (std::min)(capture.screen_rect[1], rect[1]);
            capture.screen_rect[2] =
                (std::max)(capture.screen_rect[2], rect[2]);
            capture.screen_rect[3] =
                (std::max)(capture.screen_rect[3], rect[3]);
        }
    }
    g_scene_capture.frame.exact_text.push_back(std::move(capture));
}
