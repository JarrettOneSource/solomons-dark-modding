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
    const std::vector<CapturedMenuArtElement>& art_elements,
    std::string_view active_action_id) {
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
    const auto has_dark_cloud_blocking_modal_chrome =
        visible_art_count("UI.18") == 2 &&
        visible_art_count("UI.17") == 12;
    if (has_dark_cloud_blocking_modal_chrome) {
        if (active_action_id == "dark_cloud_browser.sort") {
            return "dark_cloud_sort";
        }
        if (active_action_id == "dark_cloud_browser.options") {
            return "dark_cloud_options";
        }
    }
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
    if (contains_text("item 1") && has_art("ControlPanel.0")) {
        return "dark_cloud_login_settings";
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
    const auto active_action_id =
        state->active_semantic_ui_action_dispatch.active &&
            state->active_semantic_ui_action_dispatch.status == "dispatching"
        ? state->active_semantic_ui_action_dispatch.action_id
        : std::string{};
    snapshot.screen_id = ResolveCapturedLayoutScreenId(
        semantic_elements,
        exact_text_elements,
        art_elements,
        active_action_id);
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

