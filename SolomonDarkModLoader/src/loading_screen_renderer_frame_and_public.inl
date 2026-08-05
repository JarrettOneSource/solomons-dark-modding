void RenderLoadingScreen(IDirect3DDevice9* device) {
    const auto snapshot = GetLoadingScreenSnapshot();
    if (!snapshot.active || device == nullptr) {
        return;
    }
    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms < snapshot.started_ms ||
        now_ms - snapshot.started_ms <
            kLoadingScreenPresentationDelayMs) {
        return;
    }

    std::scoped_lock lock(g_renderer.mutex);
    if (!g_renderer.started) {
        return;
    }
    std::string resource_error;
    if (!EnsureResourcesUnlocked(device, &resource_error)) {
        if (!g_renderer.render_failure_logged) {
            g_renderer.render_failure_logged = true;
            Log(
                "Loading screen render resources unavailable. " +
                resource_error);
        }
        return;
    }

    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 ||
        viewport.Height == 0) {
        return;
    }
    float crop_u0 = 0.0f;
    float crop_v0 = 0.0f;
    float crop_u1 = 1.0f;
    float crop_v1 = 1.0f;
    LoadingScreenRenderLayout captured_layout;
    if (!DrawLoadingScreen(
            device,
            snapshot,
            viewport,
            &crop_u0,
            &crop_v0,
            &crop_u1,
            &crop_v1,
            &captured_layout)) {
        if (!g_renderer.render_failure_logged) {
            g_renderer.render_failure_logged = true;
            Log("Loading screen D3D9 draw failed.");
        }
        return;
    }
    g_renderer.last_layout = captured_layout;
    g_renderer.has_last_layout = true;
    g_renderer.render_failure_logged = false;
    CaptureLoadingScreenEvidenceFrame(
        snapshot,
        &captured_layout);

    if (g_renderer.rendered_sequence != snapshot.sequence ||
        g_renderer.rendered_stage != snapshot.stage) {
        g_renderer.rendered_sequence = snapshot.sequence;
        g_renderer.rendered_stage = snapshot.stage;
        Log(
            "Loading screen rendered. sequence=" +
            std::to_string(snapshot.sequence) +
            " stage=" + snapshot.stage_id +
            " progress=" + std::to_string(snapshot.progress) +
            " viewport=" + std::to_string(viewport.Width) + "x" +
            std::to_string(viewport.Height) +
            " crop=" + std::to_string(crop_u0) + "," +
            std::to_string(crop_v0) + "," +
            std::to_string(crop_u1) + "," +
            std::to_string(crop_v1));
    }
}

}  // namespace

bool StartLoadingScreenRenderer(
    std::uintptr_t device_pointer_global,
    const std::filesystem::path& background_path,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (background_path.empty() ||
        !std::filesystem::is_regular_file(background_path)) {
        if (error_message != nullptr) {
            *error_message =
                "Loading screen background was not found: " +
                background_path.string();
        }
        return false;
    }
    {
        std::scoped_lock lock(g_renderer.mutex);
        if (g_renderer.started) {
            return true;
        }
        g_renderer.background_path = background_path;
    }
    if (!InstallD3d9FrameHook(
            device_pointer_global,
            &RenderLoadingScreen,
            error_message)) {
        std::scoped_lock lock(g_renderer.mutex);
        g_renderer.background_path.clear();
        return false;
    }
    std::scoped_lock lock(g_renderer.mutex);
    g_renderer.started = true;
    return true;
}

void StopLoadingScreenRenderer() {
    RemoveD3d9FrameCallback(&RenderLoadingScreen);
    std::scoped_lock lock(g_renderer.mutex);
    ReleaseResourcesUnlocked();
    g_renderer.started = false;
    g_renderer.render_failure_logged = false;
    g_renderer.background_path.clear();
    g_renderer.rendered_sequence = 0;
    g_renderer.rendered_stage =
        LoadingScreenStage::PreparingBoneyard;
    g_renderer.has_last_layout = false;
    g_renderer.last_layout = {};
}

bool TryGetLastLoadingScreenRenderLayout(
    LoadingScreenRenderLayout* layout) {
    if (layout == nullptr) {
        return false;
    }
    std::scoped_lock lock(g_renderer.mutex);
    if (!g_renderer.has_last_layout) {
        return false;
    }
    *layout = g_renderer.last_layout;
    return true;
}

}  // namespace sdmod::detail
