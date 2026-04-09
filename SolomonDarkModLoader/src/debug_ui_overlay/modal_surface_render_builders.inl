bool HasSurfaceControlElement(
    const std::vector<OverlayRenderElement>& render_elements,
    std::string_view surface_id,
    uintptr_t object_ptr,
    float center_x,
    float center_y) {
    return std::any_of(
        render_elements.begin(),
        render_elements.end(),
        [&](const OverlayRenderElement& render_element) {
            if (render_element.surface_id != surface_id) {
                return false;
            }

            return (object_ptr != 0 && render_element.source_object_ptr == object_ptr) ||
                   PointInsideRect(center_x, center_y, render_element.left, render_element.top, render_element.right, render_element.bottom);
        });
}

void SortOverlayRenderElementsByTopLeft(std::vector<OverlayRenderElement>* render_elements) {
    if (render_elements == nullptr) {
        return;
    }

    std::sort(render_elements->begin(), render_elements->end(), [](const OverlayRenderElement& left, const OverlayRenderElement& right) {
        if (left.top != right.top) {
            return left.top < right.top;
        }
        return left.left < right.left;
    });
}

void DeduplicateOverlayRenderElements(std::vector<OverlayRenderElement>* render_elements) {
    if (render_elements == nullptr) {
        return;
    }

    std::vector<OverlayRenderElement> deduplicated;
    deduplicated.reserve(render_elements->size());
    for (auto& candidate : *render_elements) {
        const auto duplicate = std::any_of(
            deduplicated.begin(),
            deduplicated.end(),
            [&](const OverlayRenderElement& existing) {
                return existing.surface_id == candidate.surface_id &&
                       existing.label == candidate.label &&
                       existing.action_id == candidate.action_id &&
                       existing.source_object_ptr == candidate.source_object_ptr &&
                       existing.surface_object_ptr == candidate.surface_object_ptr &&
                       existing.show_label == candidate.show_label &&
                       existing.left == candidate.left &&
                       existing.top == candidate.top &&
                       existing.right == candidate.right &&
                       existing.bottom == candidate.bottom;
            });
        if (!duplicate) {
            deduplicated.push_back(std::move(candidate));
        }
    }

    *render_elements = std::move(deduplicated);
}

std::string ResolveQuickPanelSurfaceTitle(
    float panel_left,
    float panel_top,
    float panel_right,
    float panel_bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    const auto panel_center_x = (panel_left + panel_right) * 0.5f;
    const auto header_limit = panel_top + (std::min)(72.0f, (panel_bottom - panel_top) * 0.35f);
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "quick_panel" || element.label.empty()) {
            continue;
        }

        const auto center_x = (element.min_x + element.max_x) * 0.5f;
        const auto center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom) ||
            center_y > header_limit) {
            continue;
        }

        const auto score =
            static_cast<float>(element.sample_count) * 64.0f +
            static_cast<float>(element.label.size()) * 4.0f -
            std::fabs(center_y - panel_top) -
            std::fabs(center_x - panel_center_x) * 0.25f;
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    return best_match != nullptr ? best_match->label : std::string("Quick Panel");
}

std::string ResolveBestQuickPanelControlLabel(
    uintptr_t control_address,
    float left,
    float top,
    float right,
    float bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::string label;
    (void)TryReadCachedObjectLabel(control_address, &label);
    if (!label.empty()) {
        return label;
    }

    const auto control_center_x = (left + right) * 0.5f;
    const auto control_center_y = (top + bottom) * 0.5f;
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "quick_panel" || element.label.empty()) {
            continue;
        }

        const auto text_center_x = (element.min_x + element.max_x) * 0.5f;
        const auto text_center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(text_center_x, text_center_y, left, top, right, bottom)) {
            continue;
        }

        const auto dx = std::fabs(text_center_x - control_center_x);
        const auto dy = std::fabs(text_center_y - control_center_y);
        const auto score = static_cast<float>(element.sample_count) * 16.0f - dx - dy;
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        CacheObservedObjectLabel(control_address, best_match->label);
        return best_match->label;
    }

    return {};
}

std::string ResolveBestSettingsControlLabel(
    const DebugUiOverlayConfig& config,
    uintptr_t control_address,
    float left,
    float top,
    float right,
    float bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::string label;
    if (TryReadCachedObjectLabel(control_address, &label) && !label.empty()) {
        return label;
    }

    label = ResolveSettingsControlLabel(config, control_address);
    if (!label.empty()) {
        CacheObservedObjectLabel(control_address, label);
        return label;
    }

    const auto control_center_x = (left + right) * 0.5f;
    const auto control_center_y = (top + bottom) * 0.5f;
    const auto control_height = bottom - top;
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "settings" || element.label.empty()) {
            continue;
        }

        const auto normalized_caller = NormalizeObservedCodeAddress(element.caller_address);
        if (!IsTrustedSettingsSectionHeaderCaller(config, normalized_caller) &&
            !IsTrustedSettingsControlLabelCaller(config, normalized_caller)) {
            continue;
        }

        const auto text_center_x = (element.min_x + element.max_x) * 0.5f;
        const auto text_center_y = (element.min_y + element.max_y) * 0.5f;
        const auto vertical_distance = std::fabs(text_center_y - control_center_y);
        if (vertical_distance > (std::max)(48.0f, control_height * 1.1f)) {
            continue;
        }

        const auto horizontal_gap_left = left - element.max_x;
        const auto horizontal_gap_right = element.min_x - right;
        if (horizontal_gap_left > 640.0f || horizontal_gap_right > 192.0f) {
            continue;
        }

        const auto center_inside = PointInsideRect(text_center_x, text_center_y, left, top, right, bottom);
        const auto overlap_x =
            (std::max)(0.0f, (std::min)(right, element.max_x) - (std::max)(left, element.min_x));
        const auto overlap_y =
            (std::max)(0.0f, (std::min)(bottom, element.max_y) - (std::max)(top, element.min_y));
        const auto dx = std::fabs(text_center_x - control_center_x);
        const auto control_area = (std::max)(0.0f, right - left) * (std::max)(0.0f, bottom - top);
        auto score = static_cast<float>(element.sample_count) * 32.0f - dx * 0.5f - vertical_distance * 4.0f;
        if (center_inside) {
            score += 4096.0f;
        }
        if (overlap_x > 0.0f && overlap_y > 0.0f) {
            score += 2048.0f;
        }
        if (horizontal_gap_left >= -32.0f && horizontal_gap_left <= 512.0f) {
            score += 1024.0f - (std::max)(0.0f, horizontal_gap_left);
        }
        if (IsTrustedSettingsControlLabelCaller(config, normalized_caller)) {
            score += 1024.0f;
        }
        if (IsTrustedSettingsSectionHeaderCaller(config, normalized_caller)) {
            score += 256.0f;
        }
        score -= control_area * 0.0005f;
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        CacheObservedObjectLabel(control_address, best_match->label);
        return best_match->label;
    }

    return {};
}

std::string ResolveBestSimpleMenuControlLabel(
    uintptr_t control_address,
    float left,
    float top,
    float right,
    float bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::string label;
    (void)TryReadCachedObjectLabel(control_address, &label);
    if (!label.empty()) {
        return label;
    }

    const auto control_center_x = (left + right) * 0.5f;
    const auto control_center_y = (top + bottom) * 0.5f;
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "simple_menu" || element.label.empty()) {
            continue;
        }

        const auto text_center_x = (element.min_x + element.max_x) * 0.5f;
        const auto text_center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(text_center_x, text_center_y, left, top, right, bottom)) {
            continue;
        }

        const auto dx = std::fabs(text_center_x - control_center_x);
        const auto dy = std::fabs(text_center_y - control_center_y);
        const auto score = static_cast<float>(element.sample_count) * 16.0f - dx - dy;
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        CacheObservedObjectLabel(control_address, best_match->label);
        return best_match->label;
    }

    return {};
}

const TrackedSimpleMenuEntryState* FindTrackedSimpleMenuEntryForControl(
    uintptr_t control_address,
    const std::vector<uintptr_t>& control_pointers,
    const std::vector<TrackedSimpleMenuEntryState>& tracked_entries) {
    if (control_address == 0 || tracked_entries.empty()) {
        return nullptr;
    }

    const auto it = std::find(control_pointers.begin(), control_pointers.end(), control_address);
    if (it == control_pointers.end()) {
        return nullptr;
    }

    const auto entry_index = static_cast<std::size_t>(std::distance(control_pointers.begin(), it));
    if (entry_index >= tracked_entries.size()) {
        return nullptr;
    }

    return &tracked_entries[entry_index];
}

std::vector<OverlayRenderElement> TryBuildSimpleMenuOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<ObservedUiElement>& exact_control_elements) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return {};
    }

    uintptr_t simple_menu_address = 0;
    if (!TryGetActiveSimpleMenu(&simple_menu_address)) {
        return {};
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSimpleMenuPanelRect(*config, simple_menu_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return {};
    }

    std::vector<uintptr_t> control_pointers;
    (void)TryReadSimpleMenuControlPointers(*config, simple_menu_address, &control_pointers);
    std::vector<TrackedSimpleMenuEntryState> tracked_entries;
    std::string tracked_surface_id;
    std::string tracked_surface_title;
    (void)TryReadTrackedSimpleMenuDefinition(&tracked_entries, &tracked_surface_id, &tracked_surface_title);
    (void)tracked_surface_id;

    const auto surface_title =
        !tracked_surface_title.empty()
            ? tracked_surface_title
            : ResolveSimpleMenuSurfaceTitle(
                  panel_left,
                  panel_top,
                  panel_right,
                  panel_bottom,
                  exact_text_elements);

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(control_pointers.size() + exact_control_elements.size() + exact_text_elements.size() + 1);

    OverlayRenderElement panel;
    panel.surface_id = "simple_menu.panel";
    panel.surface_title = surface_title;
    panel.label = surface_title;
    panel.source_object_ptr = simple_menu_address;
    panel.surface_object_ptr = simple_menu_address;
    panel.show_label = false;
    panel.left = panel_left;
    panel.top = panel_top;
    panel.right = panel_right;
    panel.bottom = panel_bottom;
    render_elements.push_back(std::move(panel));

    for (const auto& exact_control : exact_control_elements) {
        if (exact_control.surface_id != "simple_menu") {
            continue;
        }

        const auto center_x = (exact_control.min_x + exact_control.max_x) * 0.5f;
        const auto center_y = (exact_control.min_y + exact_control.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom) ||
            HasSurfaceControlElement(render_elements, "simple_menu", exact_control.object_ptr, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "simple_menu";
        render_element.surface_title = surface_title;
        render_element.label = ResolveBestSimpleMenuControlLabel(
            exact_control.object_ptr,
            exact_control.min_x,
            exact_control.min_y,
            exact_control.max_x,
            exact_control.max_y,
            exact_text_elements);
        if (const auto* tracked_entry =
                FindTrackedSimpleMenuEntryForControl(exact_control.object_ptr, control_pointers, tracked_entries);
            tracked_entry != nullptr) {
            if (render_element.label.empty()) {
                render_element.label = tracked_entry->label;
            }
            render_element.action_id = tracked_entry->action_id;
        }
        render_element.source_object_ptr = exact_control.object_ptr;
        render_element.surface_object_ptr = simple_menu_address;
        render_element.left = exact_control.min_x;
        render_element.top = exact_control.min_y;
        render_element.right = exact_control.max_x;
        render_element.bottom = exact_control.max_y;
        render_element.show_label = !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    for (const auto control_pointer : control_pointers) {
        float left = 0.0f;
        float top = 0.0f;
        float right = 0.0f;
        float bottom = 0.0f;
        if (!TryReadEmbeddedWidgetRect(
                reinterpret_cast<const void*>(control_pointer),
                0,
                config->simple_menu_control_left_offset,
                config->simple_menu_control_top_offset,
                config->simple_menu_control_width_offset,
                config->simple_menu_control_height_offset,
                &left,
                &top,
                &right,
                &bottom)) {
            continue;
        }

        const auto center_x = (left + right) * 0.5f;
        const auto center_y = (top + bottom) * 0.5f;
        if (HasSurfaceControlElement(render_elements, "simple_menu", control_pointer, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "simple_menu";
        render_element.surface_title = surface_title;
        render_element.label = ResolveBestSimpleMenuControlLabel(control_pointer, left, top, right, bottom, exact_text_elements);
        if (const auto* tracked_entry =
                FindTrackedSimpleMenuEntryForControl(control_pointer, control_pointers, tracked_entries);
            tracked_entry != nullptr) {
            if (render_element.label.empty()) {
                render_element.label = tracked_entry->label;
            }
            render_element.action_id = tracked_entry->action_id;
        }
        render_element.source_object_ptr = control_pointer;
        render_element.surface_object_ptr = simple_menu_address;
        render_element.left = left;
        render_element.top = top;
        render_element.right = right;
        render_element.bottom = bottom;
        render_element.show_label = !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    for (const auto& text_element : exact_text_elements) {
        if (text_element.surface_id != "simple_menu" || text_element.label.empty()) {
            continue;
        }

        const auto center_x = (text_element.min_x + text_element.max_x) * 0.5f;
        const auto center_y = (text_element.min_y + text_element.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom) ||
            HasSurfaceControlElement(render_elements, "simple_menu", text_element.object_ptr, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "simple_menu.text";
        render_element.surface_title = surface_title;
        render_element.label = text_element.label;
        render_element.source_object_ptr = text_element.object_ptr;
        render_element.surface_object_ptr = simple_menu_address;
        render_element.show_label = false;
        render_element.left = text_element.min_x;
        render_element.top = text_element.min_y;
        render_element.right = text_element.max_x;
        render_element.bottom = text_element.max_y;
        render_elements.push_back(std::move(render_element));
    }

    if (render_elements.size() <= 1) {
        return {};
    }

    DeduplicateOverlayRenderElements(&render_elements);
    SortOverlayRenderElementsByTopLeft(&render_elements);
    return render_elements;
}

std::vector<OverlayRenderElement> TryBuildQuickPanelOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<ObservedUiElement>& exact_control_elements) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return {};
    }

    uintptr_t quick_panel_address = 0;
    if (!TryReadTrackedMyQuickPanel(&quick_panel_address) || quick_panel_address == 0) {
        return {};
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadQuickPanelPanelRect(*config, quick_panel_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return {};
    }

    const auto surface_title = ResolveQuickPanelSurfaceTitle(
        panel_left,
        panel_top,
        panel_right,
        panel_bottom,
        exact_text_elements);

    std::vector<uintptr_t> control_pointers;
    (void)TryReadMyQuickPanelBuilderWidgetPointers(*config, quick_panel_address, &control_pointers);

    uintptr_t root_control_address = 0;
    (void)TryReadMyQuickPanelBuilderRootControlAddress(*config, quick_panel_address, &root_control_address);

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(control_pointers.size() + exact_control_elements.size() + exact_text_elements.size() + 1);

    OverlayRenderElement panel;
    panel.surface_id = "quick_panel.panel";
    panel.surface_title = surface_title;
    panel.label = surface_title;
    panel.source_object_ptr = quick_panel_address;
    panel.surface_object_ptr = quick_panel_address;
    panel.show_label = false;
    panel.left = panel_left;
    panel.top = panel_top;
    panel.right = panel_right;
    panel.bottom = panel_bottom;
    render_elements.push_back(std::move(panel));

    for (const auto& exact_control : exact_control_elements) {
        if (exact_control.surface_id != "quick_panel") {
            continue;
        }

        const auto center_x = (exact_control.min_x + exact_control.max_x) * 0.5f;
        const auto center_y = (exact_control.min_y + exact_control.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom) ||
            HasSurfaceControlElement(render_elements, "quick_panel", exact_control.object_ptr, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "quick_panel";
        render_element.surface_title = surface_title;
        render_element.label = ResolveBestQuickPanelControlLabel(
            exact_control.object_ptr,
            exact_control.min_x,
            exact_control.min_y,
            exact_control.max_x,
            exact_control.max_y,
            exact_text_elements);
        render_element.source_object_ptr = exact_control.object_ptr;
        render_element.surface_object_ptr = quick_panel_address;
        render_element.left = exact_control.min_x;
        render_element.top = exact_control.min_y;
        render_element.right = exact_control.max_x;
        render_element.bottom = exact_control.max_y;
        render_element.show_label = !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    for (const auto control_pointer : control_pointers) {
        if (control_pointer == 0 || control_pointer == root_control_address) {
            continue;
        }

        float left = 0.0f;
        float top = 0.0f;
        float right = 0.0f;
        float bottom = 0.0f;
        if (!TryReadTranslatedQuickPanelWidgetRect(
                *config,
                quick_panel_address,
                control_pointer,
                &left,
                &top,
                &right,
                &bottom)) {
            continue;
        }

        const auto center_x = (left + right) * 0.5f;
        const auto center_y = (top + bottom) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom) ||
            HasSurfaceControlElement(render_elements, "quick_panel", control_pointer, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "quick_panel";
        render_element.surface_title = surface_title;
        render_element.label = ResolveBestQuickPanelControlLabel(
            control_pointer,
            left,
            top,
            right,
            bottom,
            exact_text_elements);
        render_element.source_object_ptr = control_pointer;
        render_element.surface_object_ptr = quick_panel_address;
        render_element.left = left;
        render_element.top = top;
        render_element.right = right;
        render_element.bottom = bottom;
        render_element.show_label = !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    for (const auto& text_element : exact_text_elements) {
        if (text_element.surface_id != "quick_panel" || text_element.label.empty()) {
            continue;
        }

        const auto center_x = (text_element.min_x + text_element.max_x) * 0.5f;
        const auto center_y = (text_element.min_y + text_element.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom) ||
            HasSurfaceControlElement(render_elements, "quick_panel", text_element.object_ptr, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "quick_panel.text";
        render_element.surface_title = surface_title;
        render_element.label = text_element.label;
        render_element.source_object_ptr = text_element.object_ptr;
        render_element.surface_object_ptr = quick_panel_address;
        render_element.show_label = false;
        render_element.left = text_element.min_x;
        render_element.top = text_element.min_y;
        render_element.right = text_element.max_x;
        render_element.bottom = text_element.max_y;
        render_elements.push_back(std::move(render_element));
    }

    if (render_elements.size() <= 1) {
        return {};
    }

    SortOverlayRenderElementsByTopLeft(&render_elements);
    return render_elements;
}
