std::string LowerAsciiCopy(std::string_view value) {
    std::string result(value);
    std::transform(
        result.begin(),
        result.end(),
        result.begin(),
        [](unsigned char character) {
            return static_cast<char>(std::tolower(character));
        });
    return result;
}

bool TryReadCurrentHallOfFameController(uintptr_t* hof_address) {
    if (hof_address == nullptr) {
        return false;
    }

    uintptr_t application_global = 0;
    uintptr_t hall_of_fame_offset = 0;
    uintptr_t hall_of_fame_vftable = 0;
    if (!TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "application_global",
            &application_global) ||
        !TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "application_hall_of_fame_offset",
            &hall_of_fame_offset) ||
        !TryGetBinaryLayoutNumericValue(
            "game_over.native",
            "hall_of_fame_vftable",
            &hall_of_fame_vftable) ||
        application_global == 0 || hall_of_fame_offset == 0 ||
        hall_of_fame_vftable == 0) {
        return false;
    }

    uintptr_t application = 0;
    uintptr_t hall_of_fame = 0;
    uintptr_t object_vftable = 0;
    const auto expected_vftable =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            hall_of_fame_vftable);
    if (expected_vftable == 0 ||
        !TryReadResolvedGamePointer(application_global, &application) ||
        application == 0 ||
        !TryReadPointerValueDirect(
            application + hall_of_fame_offset,
            &hall_of_fame) ||
        hall_of_fame == 0 ||
        !TryReadPointerField(
            reinterpret_cast<const void*>(hall_of_fame),
            0,
            &object_vftable) ||
        object_vftable != expected_vftable) {
        return false;
    }

    *hof_address = hall_of_fame;
    return true;
}

bool ContainsObservedText(
    const std::vector<ObservedUiElement>& elements,
    std::string_view expected) {
    const auto normalized_expected = LowerAsciiCopy(expected);
    return std::any_of(
        elements.begin(),
        elements.end(),
        [&](const ObservedUiElement& element) {
            return LowerAsciiCopy(element.label).find(normalized_expected) !=
                std::string::npos;
        });
}

bool ContainsObservedTextAbove(
    const std::vector<ObservedUiElement>& elements,
    std::string_view expected,
    float maximum_top) {
    const auto normalized_expected = LowerAsciiCopy(expected);
    return std::any_of(
        elements.begin(),
        elements.end(),
        [&](const ObservedUiElement& element) {
            return element.min_y <= maximum_top &&
                LowerAsciiCopy(element.label).find(normalized_expected) !=
                    std::string::npos;
        });
}

std::string ResolveCapturedLayoutScreenId(
    const std::vector<OverlayRenderElement>& semantic_elements,
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<CapturedMenuArtElement>& art_elements) {
    const auto semantic_root = semantic_elements.empty()
        ? std::string{}
        : GetOverlaySurfaceRootId(semantic_elements.front().surface_id);
    const auto has_action_prefix =
        [&](std::string_view prefix) {
            return std::any_of(
                semantic_elements.begin(),
                semantic_elements.end(),
                [&](const OverlayRenderElement& element) {
                    return element.action_id.rfind(prefix, 0) == 0;
                });
        };
    const auto has_action =
        [&](std::string_view action_id) {
            return std::any_of(
                semantic_elements.begin(),
                semantic_elements.end(),
                [&](const OverlayRenderElement& element) {
                    return element.action_id == action_id;
                });
        };
    const auto visible_art_count =
        [&](std::string_view art_id) {
            return std::count_if(
                art_elements.begin(),
                art_elements.end(),
                [&](const CapturedMenuArtElement& element) {
                    return element.visible && element.art_id == art_id;
                });
        };
    const auto has_art =
        [&](std::string_view art_id) {
            return visible_art_count(art_id) != 0;
        };
    const auto contains_text =
        [&](std::string_view expected) {
            if (ContainsObservedText(exact_text_elements, expected)) {
                return true;
            }
            const auto normalized_expected = LowerAsciiCopy(expected);
            return std::any_of(
                semantic_elements.begin(),
                semantic_elements.end(),
                [&](const OverlayRenderElement& element) {
                    return LowerAsciiCopy(element.label).find(
                               normalized_expected) != std::string::npos;
                });
        };
    if (semantic_root == "settings" || semantic_root == "controls") {
        return semantic_root;
    }
    if (semantic_root == "dialog" && contains_text("beta version v.0.72")) {
        return "beta_notice";
    }
    if (has_action_prefix("pause_menu.")) {
        return "pause_menu";
    }
    if (has_action_prefix("profile.")) {
        return "dark_cloud_menu";
    }
    if (has_action("main_menu.resume_last_game") ||
        has_action("main_menu.new_game") ||
        has_action("main_menu.back")) {
        return "profile_save_select";
    }
    if (contains_text("resume game") && contains_text("leave game") &&
        contains_text("game settings")) {
        return "pause_menu";
    }
    if (contains_text("last game") && contains_text("new game") &&
        contains_text("back")) {
        return "profile_save_select";
    }
    struct TextScreen {
        const char* text;
        const char* screen_id;
    };
    constexpr TextScreen kTextScreens[] = {
        {"select a control scheme", "control_scheme_picker"},
        {"search cloud for boneyards", "dark_cloud_search"},
        {"sort levels by", "dark_cloud_sort"},
        {"level options", "dark_cloud_options"},
        {"item 1", "dark_cloud_login_settings"},
        {"dark cloud settings", "dark_cloud_settings"},
        {"tweak performance", "performance"},
        {"game over", "game_over"},
    };
    for (const auto& candidate : kTextScreens) {
        if (contains_text(candidate.text)) {
            return candidate.screen_id;
        }
    }
    if (ContainsObservedTextAbove(
            exact_text_elements,
            "hall of fame",
            100.0f)) {
        return "hall_of_fame";
    }
    if (semantic_root == "create") {
        if (has_art("Create.9")) {
            return "create_element";
        }
        if (has_art("Create.16")) {
            return "create_discipline";
        }
    }
    if (has_art("GameOver.0") && has_art("GameOver.1")) {
        return "game_over";
    }
    if (has_art("ControlPanel.9")) {
        return "performance";
    }
    if (has_art("ControlPanel.0") && has_art("ControlPanel.18")) {
        return "settings";
    }
    if (has_art("UI.51") && has_art("Skills.13")) {
        return "skill_picker";
    }
    if (has_art("LevelPicker.3")) {
        return "map_picker";
    }
    if (visible_art_count("UI.101") >= 5 &&
        visible_art_count("UI.54") >= 10 &&
        visible_art_count("UI.13") >= 8) {
        return "dark_cloud_menu";
    }
    if (visible_art_count("UI.17") >= 4 &&
        visible_art_count("UI.18") >= 2 && has_art("UI.28")) {
        return "dark_cloud_settings";
    }
    if (has_art("Skills.43") && has_art("UI.42") &&
        (has_art("LevelPicker.0") || has_art("UI.28"))) {
        return "hub";
    }
    if (!semantic_root.empty()) {
        return semantic_root;
    }
    return {};
}

std::string SlugifyLayoutToken(std::string_view token) {
    std::string result;
    bool previous_separator = false;
    for (const auto character : token) {
        const auto byte = static_cast<unsigned char>(character);
        if (std::isalnum(byte) != 0) {
            result.push_back(static_cast<char>(std::tolower(byte)));
            previous_separator = false;
        } else if (!result.empty() && !previous_separator) {
            result.push_back('_');
            previous_separator = true;
        }
    }
    while (!result.empty() && result.back() == '_') {
        result.pop_back();
    }
    return result.empty() ? std::string("element") : result;
}

void StoreLatestMenuLayoutSnapshotUnlocked(
    DebugUiOverlayState* state,
    const std::vector<OverlayRenderElement>& semantic_elements,
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<CapturedMenuArtElement>& art_elements) {
    if (state == nullptr || !state->menu_layout_capture_enabled) {
        return;
    }

    DebugUiLayoutSnapshot snapshot;
    snapshot.generation = state->latest_surface_snapshot_generation;
    snapshot.captured_at_milliseconds = GetTickCount64();
    snapshot.screen_id = ResolveCapturedLayoutScreenId(
        semantic_elements,
        exact_text_elements,
        art_elements);
    if (!semantic_elements.empty()) {
        snapshot.screen_title = semantic_elements.front().surface_title;
    }
    snapshot.capture_method =
        "live native UI tree + exact text/font hooks + native Sprite draw hooks";
    snapshot.elements.reserve(
        semantic_elements.size() + exact_text_elements.size() +
        art_elements.size());

    for (const auto& source : semantic_elements) {
        DebugUiLayoutElement element;
        const auto lowered_surface = LowerAsciiCopy(source.surface_id);
        element.kind =
            lowered_surface.size() >= 6 &&
                lowered_surface.compare(
                    lowered_surface.size() - 6,
                    6,
                    ".panel") == 0
            ? "panel"
            : (!source.action_id.empty() ? "control" : "text");
        element.text = source.label;
        element.action_id = source.action_id;
        element.source_object_ptr = source.source_object_ptr;
        element.interactive = !source.action_id.empty();
        element.left = source.left;
        element.top = source.top;
        element.right = source.right;
        element.bottom = source.bottom;
        element.unclipped_left = source.left;
        element.unclipped_top = source.top;
        element.unclipped_right = source.right;
        element.unclipped_bottom = source.bottom;
        snapshot.elements.push_back(std::move(element));
    }

    for (const auto& source : exact_text_elements) {
        const auto semantic_root = semantic_elements.empty()
            ? std::string{}
            : GetOverlaySurfaceRootId(
                  semantic_elements.front().surface_id);
        const auto source_root = GetOverlaySurfaceRootId(source.surface_id);
        if (!semantic_root.empty() && source_root != semantic_root &&
            !(semantic_root == "controls" && source_root == "settings")) {
            continue;
        }
        if (source.label.empty() ||
            source.max_x <= source.min_x ||
            source.max_y <= source.min_y) {
            continue;
        }
        DebugUiLayoutElement element;
        if (source.surface_id == "settings") {
            element.action_id = ResolveConfiguredUiActionId(
                "settings",
                source.label);
        }
        element.kind = element.action_id.empty() ? "text" : "control";
        element.text = source.label;
        element.font_id = source.font_id;
        element.text_style = source.font_id.empty()
            ? "native_atlas_text"
            : "native_atlas_text:" + source.font_id;
        element.source_object_ptr = source.object_ptr;
        element.interactive = !element.action_id.empty();
        element.left = source.min_x;
        element.top = source.min_y;
        element.right = source.max_x;
        element.bottom = source.max_y;
        element.unclipped_left = source.min_x;
        element.unclipped_top = source.min_y;
        element.unclipped_right = source.max_x;
        element.unclipped_bottom = source.max_y;
        snapshot.elements.push_back(std::move(element));
    }

    for (const auto& source : art_elements) {
        DebugUiLayoutElement element;
        element.kind = "art";
        element.art_id = source.art_id;
        element.text_style = source.draw_kind;
        element.source_object_ptr = source.source_object_ptr;
        element.visible = source.visible;
        element.draw_order = source.draw_order;
        element.left = source.left;
        element.top = source.top;
        element.right = source.right;
        element.bottom = source.bottom;
        element.unclipped_left = source.unclipped_left;
        element.unclipped_top = source.unclipped_top;
        element.unclipped_right = source.unclipped_right;
        element.unclipped_bottom = source.unclipped_bottom;
        snapshot.elements.push_back(std::move(element));
    }

    std::stable_sort(
        snapshot.elements.begin(),
        snapshot.elements.end(),
        [](const DebugUiLayoutElement& left,
           const DebugUiLayoutElement& right) {
            if (left.kind != right.kind) {
                return left.kind < right.kind;
            }
            if (left.top != right.top) {
                return left.top < right.top;
            }
            if (left.left != right.left) {
                return left.left < right.left;
            }
            if (left.art_id != right.art_id) {
                return left.art_id < right.art_id;
            }
            return left.text < right.text;
        });

    std::unordered_map<std::string, std::uint32_t> id_counts;
    for (auto& element : snapshot.elements) {
        const auto token = !element.art_id.empty()
            ? element.art_id
            : (!element.action_id.empty() ? element.action_id : element.text);
        const auto id_base =
            SlugifyLayoutToken(snapshot.screen_id) + "." + element.kind +
            "." + SlugifyLayoutToken(token);
        const auto ordinal = ++id_counts[id_base];
        element.id = id_base + "." + std::to_string(ordinal);
    }

    if (!snapshot.screen_id.empty() && !snapshot.elements.empty()) {
        state->layout_snapshots_by_screen[snapshot.screen_id] = snapshot;
    }
    uintptr_t hall_of_fame = 0;
    if (snapshot.elements.empty() &&
        state->latest_layout_snapshot.screen_id == "hall_of_fame" &&
        TryReadCurrentHallOfFameController(&hall_of_fame)) {
        return;
    }

    state->latest_layout_snapshot = std::move(snapshot);
}

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
