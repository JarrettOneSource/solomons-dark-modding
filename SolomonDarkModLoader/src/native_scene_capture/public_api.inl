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

    g_scene_capture.initialized = true;
    g_scene_capture.status = "idle";
    g_scene_capture.error_message.clear();
    Log(
        "Native scene capture initialized. directory=" +
        g_scene_capture.directory.string());
    return true;
}

void ShutdownNativeSceneCapture() {
    RemoveNativeSceneCaptureHooks();
    g_pending_sprite_draws.clear();
    g_scene_capture_callers.clear();
    g_scene_capture_objects.clear();
    g_scene_capture_mesh_objects.clear();
    g_scene_capture = NativeSceneCaptureState{};
}

bool QueueNativeSceneCapture(
    std::string_view label,
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

    const auto output =
        g_scene_capture.directory / (std::string(label) + ".json");
    const auto temporary =
        g_scene_capture.directory / (std::string(label) + ".json.tmp");
    std::error_code exists_error;
    const bool output_exists = std::filesystem::exists(output, exists_error);
    if (exists_error) {
        *error_message =
            "native scene capture could not inspect its output path";
        return false;
    }
    const bool temporary_exists =
        std::filesystem::exists(temporary, exists_error);
    if (exists_error) {
        *error_message =
            "native scene capture could not inspect its temporary path";
        return false;
    }
    if (output_exists || temporary_exists) {
        *error_message =
            "native scene capture refuses to overwrite an existing output or temporary file";
        return false;
    }

    RebuildNativeSceneArtResolver();
    if (g_scene_capture.art_by_address.empty()) {
        *error_message =
            "native scene capture atlas resolver is runnable but no native atlas records are loaded";
        g_scene_capture.status = "failed";
        g_scene_capture.error_message = *error_message;
        return false;
    }
    g_scene_capture.pending_label.assign(label.begin(), label.end());
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
    status->label = g_scene_capture.pending_label.empty()
        ? g_scene_capture.active_label
        : g_scene_capture.pending_label;
    status->output_path = g_scene_capture.output_path;
    status->error_message = g_scene_capture.error_message;
    status->draw_count = static_cast<std::uint32_t>(
        g_scene_capture.frame.draws.size());
    return true;
}

void NativeSceneCaptureBeginFrame(void* region, const char* scene_kind) {
    BeginSceneFrameCapture(region, scene_kind);
}

void NativeSceneCaptureEndFrame(void* region) {
    if (!g_scene_capture.initialized || region == nullptr ||
        g_scene_capture.frame.region != reinterpret_cast<uintptr_t>(region)) {
        return;
    }
    if (!g_scene_capture.frame_active) {
        g_pending_sprite_draws.clear();
        g_scene_capture_callers.clear();
        g_scene_capture_objects.clear();
        g_scene_capture_mesh_objects.clear();
        return;
    }

    g_scene_capture.frame.camera = ReadCameraCapture(
        g_scene_capture.frame.region);
    if (g_scene_capture.frame.draws.empty()) {
        FailActiveSceneCapture(
            "native scene capture reached the scene end without observing a draw");
    } else {
        std::string write_error;
        if (WriteNativeSceneCaptureFile(&write_error)) {
            g_scene_capture.status = "complete";
            g_scene_capture.error_message.clear();
            g_scene_capture.frame_active = false;
        } else {
            FailActiveSceneCapture(std::move(write_error));
        }
    }
    g_pending_sprite_draws.clear();
    g_scene_capture_callers.clear();
    g_scene_capture_objects.clear();
    g_scene_capture_mesh_objects.clear();
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
