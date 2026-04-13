void SortOverlayRenderElementsByTopLeft(std::vector<OverlayRenderElement>* render_elements);

std::vector<OverlayRenderElement> TryBuildHallOfFameOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements) {
    uintptr_t hof_address = 0;
    if (!TryGetCurrentHallOfFame(&hof_address) || hof_address == 0) {
        return {};
    }

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(32);

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "hall_of_fame" || element.label.empty()) {
            continue;
        }

        const auto width = element.max_x - element.min_x;
        const auto height = element.max_y - element.min_y;
        if (width < 4.0f || height < 4.0f || width > 2048.0f || height > 256.0f) {
            continue;
        }

        if (element.min_x < 0.0f || element.min_y < 0.0f) {
            continue;
        }

        const auto overlaps_existing = std::any_of(
            render_elements.begin(),
            render_elements.end(),
            [&](const OverlayRenderElement& re) {
                return std::fabs(re.left - element.min_x) <= 2.0f &&
                       std::fabs(re.top - element.min_y) <= 2.0f &&
                       std::fabs(re.right - element.max_x) <= 2.0f &&
                       std::fabs(re.bottom - element.max_y) <= 2.0f;
            });
        if (overlaps_existing) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "hall_of_fame";
        render_element.surface_title = "Hall of Fame";
        render_element.label = element.label;
        render_element.source_object_ptr = element.object_ptr;
        render_element.surface_object_ptr = hof_address;
        render_element.left = element.min_x;
        render_element.top = element.min_y;
        render_element.right = element.max_x;
        render_element.bottom = element.max_y;
        render_element.show_label = true;
        render_elements.push_back(std::move(render_element));
    }

    if (!render_elements.empty()) {
        static bool s_logged_hall_of_fame_first_elements = false;
        if (!s_logged_hall_of_fame_first_elements) {
            s_logged_hall_of_fame_first_elements = true;
            Log(
                "Debug UI overlay built first Hall of Fame elements: count=" +
                std::to_string(render_elements.size()) + " hof_object=" + HexString(hof_address));
        }

        SortOverlayRenderElementsByTopLeft(&render_elements);
    }

    return render_elements;
}

std::vector<OverlayRenderElement> TryBuildSpellPickerOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements) {
    uintptr_t picker_address = 0;
    if (!TryGetActiveSpellPickerRender(&picker_address) || picker_address == 0) {
        return {};
    }

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(16);

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "spell_picker" || element.label.empty()) {
            continue;
        }

        const auto width = element.max_x - element.min_x;
        const auto height = element.max_y - element.min_y;
        if (width < 4.0f || height < 4.0f || width > 2048.0f || height > 256.0f) {
            continue;
        }

        if (element.min_x < 0.0f || element.min_y < 0.0f) {
            continue;
        }

        const auto overlaps_existing = std::any_of(
            render_elements.begin(),
            render_elements.end(),
            [&](const OverlayRenderElement& re) {
                return std::fabs(re.left - element.min_x) <= 2.0f &&
                       std::fabs(re.top - element.min_y) <= 2.0f &&
                       std::fabs(re.right - element.max_x) <= 2.0f &&
                       std::fabs(re.bottom - element.max_y) <= 2.0f;
            });
        if (overlaps_existing) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "spell_picker";
        render_element.surface_title = "Spell Picker";
        render_element.label = element.label;
        render_element.source_object_ptr = element.object_ptr;
        render_element.surface_object_ptr = picker_address;
        render_element.left = element.min_x;
        render_element.top = element.min_y;
        render_element.right = element.max_x;
        render_element.bottom = element.max_y;
        render_element.show_label = true;
        render_elements.push_back(std::move(render_element));
    }

    if (!render_elements.empty()) {
        static bool s_logged_spell_picker_first_elements = false;
        if (!s_logged_spell_picker_first_elements) {
            s_logged_spell_picker_first_elements = true;
            Log(
                "Debug UI overlay built first Spell Picker elements: count=" +
                std::to_string(render_elements.size()) + " picker_object=" + HexString(picker_address));
        }

        SortOverlayRenderElementsByTopLeft(&render_elements);
    }

    return render_elements;
}

std::vector<ObservedUiElement> TakeObservedFrameElements() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto elements = std::move(g_debug_ui_overlay_state.frame_elements);
    g_debug_ui_overlay_state.frame_elements.clear();
    return elements;
}

std::vector<ObservedUiElement> TakeExactTextFrameElements() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto elements = std::move(g_debug_ui_overlay_state.frame_exact_text_elements);
    g_debug_ui_overlay_state.frame_exact_text_elements.clear();
    return elements;
}

std::vector<ObservedUiElement> TakeExactControlFrameElements() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto elements = std::move(g_debug_ui_overlay_state.frame_exact_control_elements);
    g_debug_ui_overlay_state.frame_exact_control_elements.clear();
    return elements;
}

std::optional<DialogOverlaySnapshot> TryBuildTrackedDialogOverlaySnapshot(
    IDirect3DDevice9* device,
    const std::vector<ObservedUiElement>& elements,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    (void)elements;
    (void)device;

    TrackedDialogState tracked_dialog;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        const auto now = GetTickCount64();
        if (ShouldDismissTrackedDialogUnlocked(now) ||
            (g_debug_ui_overlay_state.tracked_dialog.object_ptr != 0 &&
             now - g_debug_ui_overlay_state.tracked_dialog.captured_at > kTrackedDialogMaximumLifetimeMs)) {
            g_debug_ui_overlay_state.tracked_dialog = TrackedDialogState{};
        }

        if (g_debug_ui_overlay_state.tracked_dialog.object_ptr == 0) {
            return std::nullopt;
        }

        tracked_dialog = g_debug_ui_overlay_state.tracked_dialog;
    }

    const auto object_ptr = reinterpret_cast<const void*>(tracked_dialog.object_ptr);
    const auto now = GetTickCount64();
    DialogGeometry geometry;
    if (!TryReadMsgBoxGeometry(object_ptr, g_debug_ui_overlay_state.config, &geometry)) {
        if (now - tracked_dialog.captured_at > 1000) {
            std::scoped_lock clear_lock(g_debug_ui_overlay_state.mutex);
            if (g_debug_ui_overlay_state.tracked_dialog.object_ptr == tracked_dialog.object_ptr) {
                g_debug_ui_overlay_state.tracked_dialog = TrackedDialogState{};
            }
        }
        return std::nullopt;
    }

    if (!tracked_dialog.has_geometry || tracked_dialog.left != geometry.left || tracked_dialog.top != geometry.top ||
        tracked_dialog.right != geometry.right || tracked_dialog.bottom != geometry.bottom) {
        std::scoped_lock refresh_lock(g_debug_ui_overlay_state.mutex);
        auto& live_dialog = g_debug_ui_overlay_state.tracked_dialog;
        if (live_dialog.object_ptr == tracked_dialog.object_ptr) {
            MergeTrackedDialogGeometryLocked(&live_dialog, geometry);
        }
    }

    DialogOverlaySnapshot snapshot;
    snapshot.object_ptr = tracked_dialog.object_ptr;
    snapshot.captured_at = tracked_dialog.captured_at;
    snapshot.uses_cached_geometry = false;
    snapshot.left = geometry.left;
    snapshot.top = geometry.top;
    snapshot.right = geometry.right;
    snapshot.bottom = geometry.bottom;
    if (geometry.primary_button.has_bounds) {
        snapshot.buttons.push_back(geometry.primary_button);
    }
    if (geometry.secondary_button.has_bounds) {
        snapshot.buttons.push_back(geometry.secondary_button);
    }

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "dialog" || element.label.empty()) {
            continue;
        }

        const auto width = element.max_x - element.min_x;
        const auto height = element.max_y - element.min_y;
        if (width < 4.0f || height < 4.0f || width > 1024.0f || height > 256.0f) {
            continue;
        }

        const auto center_x = (element.min_x + element.max_x) * 0.5f;
        const auto center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, geometry.left, geometry.top, geometry.right, geometry.bottom)) {
            continue;
        }

        const auto overlaps_dialog_button = std::any_of(snapshot.buttons.begin(), snapshot.buttons.end(), [&](const DialogButtonState& button_state) {
            return button_state.has_bounds &&
                   PointInsideRect(center_x, center_y, button_state.left, button_state.top, button_state.right, button_state.bottom);
        });
        if (overlaps_dialog_button) {
            continue;
        }

        DialogLineState line_state;
        line_state.object_ptr = element.object_ptr;
        line_state.label = element.label;
        line_state.logical_height = height;
        line_state.has_bounds = true;
        line_state.left = element.min_x;
        line_state.top = element.min_y;
        line_state.right = element.max_x;
        line_state.bottom = element.max_y;
        snapshot.line_states.push_back(std::move(line_state));
    }

    std::sort(snapshot.line_states.begin(), snapshot.line_states.end(), [](const DialogLineState& left, const DialogLineState& right) {
        if (std::fabs(left.top - right.top) > 1.0f) {
            return left.top < right.top;
        }
        return left.left < right.left;
    });

    snapshot.line_states.erase(
        std::unique(
            snapshot.line_states.begin(),
            snapshot.line_states.end(),
            [](const DialogLineState& left, const DialogLineState& right) {
                return left.label == right.label && std::fabs(left.left - right.left) <= 1.0f &&
                       std::fabs(left.top - right.top) <= 1.0f && std::fabs(left.right - right.right) <= 1.0f &&
                       std::fabs(left.bottom - right.bottom) <= 1.0f;
            }),
        snapshot.line_states.end());

    snapshot.lines.reserve((std::max)(snapshot.line_states.size(), tracked_dialog.lines.size()));
    if (!snapshot.line_states.empty()) {
        for (const auto& line_state : snapshot.line_states) {
            snapshot.lines.push_back(line_state.label);
        }
    } else {
        snapshot.lines = tracked_dialog.lines;
    }
    if (!tracked_dialog.title.empty()) {
        snapshot.title = tracked_dialog.title;
    } else if (!snapshot.line_states.empty()) {
        snapshot.title = snapshot.line_states.front().label;
    } else if (!snapshot.lines.empty()) {
        snapshot.title = snapshot.lines.front();
    } else {
        snapshot.title = "Dialog";
    }

    static bool s_logged_dialog_snapshot_details = false;
    if (!s_logged_dialog_snapshot_details) {
        s_logged_dialog_snapshot_details = true;
        std::string summary;
        std::size_t sample_count = 0;
        for (const auto& line_state : snapshot.line_states) {
            if (sample_count >= 8) {
                break;
            }
            if (!summary.empty()) {
                summary += " || ";
            }
            summary += "[" + SanitizeDebugLogLabel(line_state.label) + " h=" +
                       std::to_string(line_state.logical_height) + "]";
            ++sample_count;
        }
        Log(
            "Debug UI dialog snapshot details: line_count=" + std::to_string(snapshot.line_states.size()) +
            " lines=" + summary);
    }

    return snapshot;
}

void ClearTrackedDialogBecauseHigherPrioritySurfaceBecameDominant(std::string_view surface_name) {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.tracked_dialog.object_ptr == 0) {
        return;
    }

    g_debug_ui_overlay_state.tracked_dialog = TrackedDialogState{};
    Log(
        "Debug UI overlay cleared a stale tracked dialog because exact " + std::string(surface_name) +
        " evidence became dominant.");
}

void ClearTrackedDialogForTitleMainMenuCutover() {
    ClearTrackedDialogBecauseHigherPrioritySurfaceBecameDominant("MainMenu");
}

std::vector<OverlayRenderElement> BuildDialogOverlayRenderElements(const DialogOverlaySnapshot& snapshot) {
    std::vector<OverlayRenderElement> render_elements;

    OverlayRenderElement panel;
    panel.surface_id = "dialog";
    panel.surface_title = "Dialog";
    panel.label = snapshot.title.empty() ? std::string("Dialog") : snapshot.title;
    panel.surface_object_ptr = snapshot.object_ptr;
    panel.left = snapshot.left;
    panel.top = snapshot.top;
    panel.right = snapshot.right;
    panel.bottom = snapshot.bottom;
    render_elements.push_back(panel);

    for (const auto& line_state : snapshot.line_states) {
        if (!line_state.has_bounds) {
            continue;
        }

        OverlayRenderElement line;
        line.surface_id = "dialog.line";
        line.surface_title = panel.surface_title;
        line.label = line_state.label;
        line.source_object_ptr = line_state.object_ptr;
        line.surface_object_ptr = snapshot.object_ptr;
        line.show_label = false;
        line.left = line_state.left;
        line.top = line_state.top;
        line.right = line_state.right;
        line.bottom = line_state.bottom;
        render_elements.push_back(std::move(line));
    }

    if (snapshot.buttons.size() == 1) {
        if (snapshot.buttons.front().has_bounds) {
            OverlayRenderElement button;
            button.surface_id = "dialog.button";
            button.surface_title = panel.surface_title;
            button.label = snapshot.buttons.front().label;
            button.action_id = snapshot.buttons.front().action_id;
            button.source_object_ptr = snapshot.buttons.front().object_ptr;
            button.surface_object_ptr = snapshot.object_ptr;
            button.left = snapshot.buttons.front().left;
            button.top = snapshot.buttons.front().top;
            button.right = snapshot.buttons.front().right;
            button.bottom = snapshot.buttons.front().bottom;
            render_elements.push_back(std::move(button));
        }
    } else {
        for (const auto& button_state : snapshot.buttons) {
            if (!button_state.has_bounds) {
                continue;
            }

            OverlayRenderElement button;
            button.surface_id = "dialog.button";
            button.surface_title = panel.surface_title;
            button.label = button_state.label;
            button.action_id = button_state.action_id;
            button.source_object_ptr = button_state.object_ptr;
            button.surface_object_ptr = snapshot.object_ptr;
            button.left = button_state.left;
            button.top = button_state.top;
            button.right = button_state.right;
            button.bottom = button_state.bottom;
            render_elements.push_back(std::move(button));
        }
    }

    return render_elements;
}
