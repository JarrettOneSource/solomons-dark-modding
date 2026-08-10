std::string JsonEscapeMenuCapture(std::string_view value) {
    std::ostringstream output;
    for (const auto character : value) {
        switch (character) {
            case '\\': output << "\\\\"; break;
            case '"': output << "\\\""; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default: output << character; break;
        }
    }
    return output.str();
}

std::string SerializeNativeBootStructure(
    const NativeBootCaptureSample& sample) {
    std::ostringstream output;
    output << std::fixed << std::setprecision(6)
           << "{\"numerator\":" << sample.numerator
           << ",\"denominator\":" << sample.denominator
           << ",\"complete\":" << (sample.complete ? "true" : "false")
           << ",\"progress\":" << sample.progress
           << ",\"elements\":[";
    for (std::size_t index = 0; index < sample.elements.size(); ++index) {
        const auto& element = sample.elements[index];
        if (index != 0) {
            output << ',';
        }
        output << "{\"art_id\":\""
               << JsonEscapeMenuCapture(element.art_id)
               << "\",\"draw_kind\":\""
               << JsonEscapeMenuCapture(element.draw_kind)
               << "\"}";
    }
    output << "]}";
    return output.str();
}

void WriteNativeBootCaptureJson() {
    if (g_native_boot_capture_directory.empty()) {
        return;
    }
    std::error_code error;
    std::filesystem::create_directories(
        g_native_boot_capture_directory,
        error);
    if (error) {
        return;
    }

    const auto output_path =
        g_native_boot_capture_directory / "native-loader-layout.json";
    std::ofstream output(output_path, std::ios::trunc);
    if (!output) {
        return;
    }

    char pipe_name[512] = {};
    GetEnvironmentVariableA(
        "SDMOD_LUA_EXEC_PIPE_NAME",
        pipe_name,
        static_cast<DWORD>(sizeof(pipe_name)));
    output << "{\n"
           << "  \"schema\": \"solomon-dark-native-loader-capture-v1\",\n"
           << "  \"instance\": \"" << JsonEscapeMenuCapture(pipe_name) << "\",\n"
           << "  \"process_id\": " << GetCurrentProcessId() << ",\n"
           << "  \"capture_method\": \"MyLoader render detour + live loader globals + native Sprite draw hooks + D3D9 backbuffer\",\n"
           << "  \"samples\": [\n";
    for (std::size_t sample_index = 0;
         sample_index < g_native_boot_capture_samples.size();
         ++sample_index) {
        const auto& sample = g_native_boot_capture_samples[sample_index];
        output << "    {\"elapsed_milliseconds\": "
               << sample.elapsed_milliseconds
               << ", \"numerator\": " << sample.numerator
               << ", \"denominator\": " << sample.denominator
               << ", \"complete\": " << (sample.complete ? "true" : "false")
               << ", \"progress\": " << std::fixed << std::setprecision(6)
               << sample.progress
               << ", \"reference_capture\": \""
               << JsonEscapeMenuCapture(sample.reference_capture)
               << "\", \"elements\": [";
        for (std::size_t element_index = 0;
             element_index < sample.elements.size();
             ++element_index) {
            const auto& element = sample.elements[element_index];
            if (element_index != 0) {
                output << ',';
            }
            output << "{\"art_id\": \""
                   << JsonEscapeMenuCapture(element.art_id)
                   << "\", \"draw_kind\": \""
                   << JsonEscapeMenuCapture(element.draw_kind)
                   << "\", \"rect\": ["
                   << element.left << ',' << element.top << ','
                   << element.right << ',' << element.bottom
                   << "], \"unclipped_rect\": ["
                   << element.unclipped_left << ','
                   << element.unclipped_top << ','
                   << element.unclipped_right << ','
                   << element.unclipped_bottom << "]}";
        }
        output << "]}";
        if (sample_index + 1 != g_native_boot_capture_samples.size()) {
            output << ',';
        }
        output << '\n';
    }
    output << "  ],\n"
           << "  \"settlement\": {\n"
           << "    \"criterion\": \"at least 40 consecutive samples spanning at least 2 seconds with byte-identical structural payloads; animated geometry is measured by the importer\",\n"
           << "    \"settled\": "
           << (g_native_boot_capture_settled ? "true" : "false") << ",\n"
           << "    \"settle_latency_milliseconds\": ";
    if (g_native_boot_capture_settled &&
        !g_native_boot_capture_samples.empty()) {
        output << g_native_boot_capture_samples.back().elapsed_milliseconds;
    } else {
        output << "null";
    }
    const auto stable_span = g_native_boot_capture_samples.empty()
        ? 0
        : g_native_boot_capture_samples.back().elapsed_milliseconds -
            g_native_boot_stable_started_at;
    output << ",\n"
           << "    \"stable_span_milliseconds\": " << stable_span << ",\n"
           << "    \"consecutive_structural_samples\": "
           << g_native_boot_stable_sample_count << ",\n"
           << "    \"total_semantic_samples\": "
           << g_native_boot_capture_samples.size() << "\n"
           << "  }\n}\n";
}

void CaptureNativeLoaderSample() {
    if (g_native_boot_capture_directory.empty() ||
        g_native_boot_capture_settled) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    const auto numerator_address =
        memory.ResolveGameAddressOrZero(kNativeLoaderProgressNumerator);
    const auto denominator_address =
        memory.ResolveGameAddressOrZero(kNativeLoaderProgressDenominator);
    const auto complete_address =
        memory.ResolveGameAddressOrZero(kNativeLoaderCompleteFlag);
    NativeBootCaptureSample sample;
    std::uint8_t complete = 0;
    if (numerator_address == 0 || denominator_address == 0 ||
        complete_address == 0 ||
        !memory.TryReadValue(numerator_address, &sample.numerator) ||
        !memory.TryReadValue(denominator_address, &sample.denominator) ||
        !memory.TryReadValue(complete_address, &complete)) {
        return;
    }
    if (g_native_boot_capture_started_at == 0) {
        g_native_boot_capture_started_at = GetTickCount64();
    }
    sample.elapsed_milliseconds =
        GetTickCount64() - g_native_boot_capture_started_at;
    sample.complete = complete != 0;
    sample.progress = sample.complete
        ? 1.0
        : (sample.denominator == 0
               ? 0.0
               : (std::min)(
                     1.0,
                     static_cast<double>(sample.numerator) /
                         static_cast<double>(sample.denominator)));

    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        sample.elements = g_native_loader_frame_art;
    }

    const auto semantic = SerializeNativeBootStructure(sample);
    const auto semantic_changed = semantic != g_native_boot_stable_semantic;
    if (semantic_changed) {
        g_native_boot_stable_semantic = semantic;
        g_native_boot_stable_sample_count = 1;
        g_native_boot_stable_started_at = sample.elapsed_milliseconds;
        constexpr char filename[] = "native-loader-settled-candidate.bmp";
        const auto path = g_native_boot_capture_directory / filename;
        std::string capture_error;
        if (CaptureD3d9BackBufferBmp(path.wstring(), &capture_error)) {
            sample.reference_capture = filename;
        }
    } else {
        ++g_native_boot_stable_sample_count;
    }
    const auto stable_span =
        sample.elapsed_milliseconds - g_native_boot_stable_started_at;
    g_native_boot_capture_settled =
        g_native_boot_stable_sample_count >= 40 && stable_span >= 2000;
    g_native_boot_capture_samples.push_back(std::move(sample));
    WriteNativeBootCaptureJson();
}

void __fastcall HookNativeLoaderRender(
    void* self,
    void* /*unused_edx*/) {
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_native_loader_frame_art.clear();
        g_native_loader_render_active = true;
    }
    RebuildNativeMenuArtResolver();
    const auto original = GetX86HookTrampoline<MyLoaderRenderFn>(
        g_debug_ui_overlay_state.native_loader_render_hook);
    if (original != nullptr) {
        original(self);
    }
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_native_loader_render_active = false;
    }
    CaptureNativeLoaderSample();
    if (!g_native_boot_capture_directory.empty() &&
        !g_native_boot_capture_settled &&
        !g_native_boot_capture_samples.empty() &&
        g_native_boot_capture_samples.back().progress >= 1.0) {
        const auto deadline = GetTickCount64() + 60000;
        while (!g_native_boot_capture_settled &&
               GetTickCount64() <= deadline) {
            Sleep(50);
            CaptureNativeLoaderSample();
        }
        if (!g_native_boot_capture_settled) {
            Log(
                "STOP: native loader never satisfied the 40-sample, "
                "two-second settlement criterion within 60 seconds.");
        }
    }
}

bool IsTruthyMenuCaptureEnvironment(const char* name) {
    char value[16] = {};
    const auto length = GetEnvironmentVariableA(
        name,
        value,
        static_cast<DWORD>(sizeof(value)));
    if (length == 0 || length >= sizeof(value)) {
        return false;
    }
    const auto normalized = LowerAsciiCopy(value);
    return normalized == "1" || normalized == "true" ||
        normalized == "yes" || normalized == "on";
}

bool InstallMenuLayoutCaptureHooks(std::string* error_message) {
    char boot_directory[32768] = {};
    const auto boot_directory_length = GetEnvironmentVariableA(
        "SDMOD_NATIVE_BOOT_CAPTURE_DIRECTORY",
        boot_directory,
        static_cast<DWORD>(sizeof(boot_directory)));
    if (boot_directory_length > 0 &&
        boot_directory_length < sizeof(boot_directory)) {
        g_native_boot_capture_directory = boot_directory;
    }
    const auto requested =
        IsTruthyMenuCaptureEnvironment(
            "SDMOD_NATIVE_MENU_LAYOUT_CAPTURE") ||
        !g_native_boot_capture_directory.empty() ||
        IsNativeSceneCaptureRequested();
    g_debug_ui_overlay_state.menu_layout_capture_enabled = requested;
    if (!requested) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto centered = memory.ResolveGameAddressOrZero(
        kNativeSpriteCenteredDrawAddress);
    const auto transformed = memory.ResolveGameAddressOrZero(
        kNativeSpriteTransformDrawAddress);
    const auto loader = memory.ResolveGameAddressOrZero(
        kNativeLoaderRenderAddress);
    const auto settings_scalar = memory.ResolveGameAddressOrZero(
        kSettingsScalarRowAddress);
    const auto settings_toggle = memory.ResolveGameAddressOrZero(
        kSettingsToggleRowAddress);
    const auto settings_action = memory.ResolveGameAddressOrZero(
        kSettingsActionRowAddress);
    if (centered == 0 || transformed == 0 || loader == 0 ||
        settings_scalar == 0 || settings_toggle == 0 ||
        settings_action == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Could not resolve native menu-layout capture targets.";
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(centered),
            reinterpret_cast<void*>(&HookMenuSpriteCenteredDraw),
            5,
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook,
            error_message)) {
        return false;
    }
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(transformed),
            reinterpret_cast<void*>(&HookMenuSpriteTransformDraw),
            5,
            &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook,
            error_message)) {
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
        return false;
    }
    if (!g_native_boot_capture_directory.empty() &&
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(loader),
            reinterpret_cast<void*>(&HookNativeLoaderRender),
            5,
            &g_debug_ui_overlay_state.native_loader_render_hook,
            error_message)) {
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
        return false;
    }
    const auto remove_capture_hooks = []() {
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_action_row_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_toggle_row_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_scalar_row_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.native_loader_render_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
    };
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_scalar),
            reinterpret_cast<void*>(&HookSettingsScalarRow),
            5,
            &g_debug_ui_overlay_state.settings_scalar_row_hook,
            error_message) ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_toggle),
            reinterpret_cast<void*>(&HookSettingsToggleRow),
            5,
            &g_debug_ui_overlay_state.settings_toggle_row_hook,
            error_message) ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_action),
            reinterpret_cast<void*>(&HookSettingsActionRow),
            5,
            &g_debug_ui_overlay_state.settings_action_row_hook,
            error_message)) {
        remove_capture_hooks();
        return false;
    }
    RebuildNativeMenuArtResolver();
    return true;
}

void RemoveMenuLayoutCaptureHooks() {
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_action_row_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_toggle_row_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_scalar_row_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.native_loader_render_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
}

void ResetMenuLayoutCaptureStateUnlocked(DebugUiOverlayState* state) {
    if (state == nullptr) {
        return;
    }
    state->menu_sprite_centered_draw_hook = X86Hook{};
    state->menu_sprite_transform_draw_hook = X86Hook{};
    state->native_loader_render_hook = X86Hook{};
    state->settings_scalar_row_hook = X86Hook{};
    state->settings_toggle_row_hook = X86Hook{};
    state->settings_action_row_hook = X86Hook{};
    state->menu_layout_capture_enabled = false;
    state->frame_menu_art_elements.clear();
    state->retained_settings_elements_owner = 0;
    state->retained_settings_exact_text_elements.clear();
    state->retained_settings_exact_control_elements.clear();
    state->latest_layout_snapshot = DebugUiLayoutSnapshot{};
    state->layout_snapshots_by_screen.clear();
    g_native_menu_art_by_address.clear();
    g_native_menu_art_by_signature.clear();
    g_native_menu_art_cache_built_at = 0;
    g_native_menu_art_draw_order = 0;
    g_native_boot_capture_directory.clear();
    g_native_boot_capture_samples.clear();
    g_native_boot_capture_started_at = 0;
    g_native_boot_stable_semantic.clear();
    g_native_boot_stable_sample_count = 0;
    g_native_boot_stable_started_at = 0;
    g_native_boot_capture_settled = false;
    g_native_loader_render_active = false;
    g_native_loader_frame_art.clear();
    g_active_settings_row_captures.clear();
}
