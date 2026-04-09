bool TryReadUiWidgetParentAtOffset(
    uintptr_t object_address,
    std::size_t parent_offset,
    uintptr_t* parent_address) {
    if (object_address == 0 || parent_address == nullptr) {
        return false;
    }

    return TryReadPointerField(
        reinterpret_cast<const void*>(object_address),
        parent_offset,
        parent_address);
}

bool TryReadUiWidgetParent(
    const DebugUiOverlayConfig& config,
    uintptr_t object_address,
    uintptr_t* parent_address) {
    return TryReadUiWidgetParentAtOffset(object_address, config.ui_widget_parent_offset, parent_address);
}

bool IsWidgetOwnedByRootAtOffset(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address,
    std::size_t parent_offset) {
    (void)config;
    if (root_address == 0 || object_address == 0) {
        return false;
    }

    auto current_address = object_address;
    for (std::size_t depth = 0; depth < kMaximumUiWidgetParentDepth && current_address != 0; ++depth) {
        if (current_address == root_address) {
            return true;
        }

        uintptr_t parent_address = 0;
        if (!TryReadUiWidgetParentAtOffset(current_address, parent_offset, &parent_address) || parent_address == 0 ||
            parent_address == current_address) {
            return false;
        }

        current_address = parent_address;
    }

    return false;
}

bool IsWidgetOwnedByRoot(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address) {
    return IsWidgetOwnedByRootAtOffset(config, root_address, object_address, config.ui_widget_parent_offset);
}

bool TryReadTranslatedWidgetRectToRootAtOffset(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address,
    std::size_t parent_offset,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (root_address == 0 || object_address == 0 || left == nullptr || top == nullptr || right == nullptr ||
        bottom == nullptr) {
        return false;
    }

    float local_left = 0.0f;
    float local_top = 0.0f;
    float local_right = 0.0f;
    float local_bottom = 0.0f;
    if (!TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(object_address),
            &local_left,
            &local_top,
            &local_right,
            &local_bottom)) {
        return false;
    }

    auto accumulated_left = local_left;
    auto accumulated_top = local_top;
    auto current_address = object_address;
    for (std::size_t depth = 0; depth < kMaximumUiWidgetParentDepth; ++depth) {
        if (current_address == root_address) {
            *left = accumulated_left;
            *top = accumulated_top;
            *right = accumulated_left + (local_right - local_left);
            *bottom = accumulated_top + (local_bottom - local_top);
            return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
        }

        uintptr_t parent_address = 0;
        if (!TryReadUiWidgetParentAtOffset(current_address, parent_offset, &parent_address) || parent_address == 0 ||
            parent_address == current_address) {
            return false;
        }

        float parent_left = 0.0f;
        float parent_top = 0.0f;
        float parent_right = 0.0f;
        float parent_bottom = 0.0f;
        if (!TryReadExactControlRect(
                config,
                reinterpret_cast<const void*>(parent_address),
                &parent_left,
                &parent_top,
                &parent_right,
                &parent_bottom)) {
            return false;
        }

        accumulated_left += parent_left;
        accumulated_top += parent_top;
        current_address = parent_address;
    }

    return false;
}

bool TryReadTranslatedWidgetRectToRoot(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    return TryReadTranslatedWidgetRectToRootAtOffset(
        config,
        root_address,
        object_address,
        config.ui_widget_parent_offset,
        left,
        top,
        right,
        bottom);
}

bool IsLocalSubsurfaceRect(float left, float top, float right, float bottom) {
    const auto width = right - left;
    const auto height = bottom - top;
    if (!std::isfinite(left) || !std::isfinite(top) || !std::isfinite(right) || !std::isfinite(bottom)) {
        return false;
    }

    if (left < -64.0f || top < -64.0f || right > 640.0f || bottom > 256.0f) {
        return false;
    }

    return width >= 8.0f && height >= 8.0f;
}

bool IsDarkCloudBrowserLayoutSlot(
    const DebugUiOverlayConfig& config,
    uintptr_t browser_address,
    uintptr_t object_address) {
    if (browser_address == 0 || object_address < browser_address) {
        return false;
    }

    const auto relative_offset = static_cast<std::size_t>(object_address - browser_address);
    return relative_offset == config.dark_cloud_browser_primary_action_control_offset ||
           relative_offset == config.dark_cloud_browser_secondary_action_control_offset ||
           relative_offset == config.dark_cloud_browser_aux_left_control_offset ||
           relative_offset == config.dark_cloud_browser_aux_right_control_offset ||
           relative_offset == config.dark_cloud_browser_recent_tab_control_offset ||
           relative_offset == config.dark_cloud_browser_online_levels_tab_control_offset ||
           relative_offset == config.dark_cloud_browser_my_levels_tab_control_offset ||
           relative_offset == config.dark_cloud_browser_footer_action_control_offset;
}

bool IsQuickPanelOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t object_address) {
    if (quick_panel_address == 0 || object_address == 0) {
        return false;
    }

    if (IsWidgetOwnedByRootAtOffset(
            config,
            quick_panel_address,
            object_address,
            config.myquick_panel_widget_parent_offset)) {
        return true;
    }

    uintptr_t builder_owned_object = 0;
    return TryResolveMyQuickPanelBuilderOwnedObject(
        config,
        quick_panel_address,
        object_address,
        &builder_owned_object);
}

bool TryResolveQuickPanelOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t primary_candidate,
    uintptr_t alternate_candidate,
    uintptr_t* owned_object_address) {
    if (owned_object_address == nullptr) {
        return false;
    }

    if (TryResolveMyQuickPanelBuilderOwnedObject(
            config,
            quick_panel_address,
            primary_candidate,
            owned_object_address)) {
        return true;
    }

    if (TryResolveMyQuickPanelBuilderOwnedObject(
            config,
            quick_panel_address,
            alternate_candidate,
            owned_object_address)) {
        return true;
    }

    if (IsWidgetOwnedByRootAtOffset(
            config,
            quick_panel_address,
            primary_candidate,
            config.myquick_panel_widget_parent_offset)) {
        *owned_object_address = primary_candidate;
        return true;
    }

    if (IsWidgetOwnedByRootAtOffset(
            config,
            quick_panel_address,
            alternate_candidate,
            config.myquick_panel_widget_parent_offset)) {
        *owned_object_address = alternate_candidate;
        return true;
    }

    return false;
}

bool TryReadTranslatedQuickPanelWidgetRect(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t object_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (TryReadTranslatedWidgetRectToRootAtOffset(
            config,
            quick_panel_address,
            object_address,
            config.myquick_panel_widget_parent_offset,
            left,
            top,
            right,
            bottom)) {
        return true;
    }

    return TryReadTranslatedMyQuickPanelBuilderWidgetRect(
        config,
        quick_panel_address,
        object_address,
        left,
        top,
        right,
        bottom);
}

bool TryReadPointerListEntries(
    const void* owner_object,
    std::size_t list_offset,
    std::size_t list_count_offset,
    std::size_t list_entries_offset,
    std::size_t max_entries,
    std::vector<uintptr_t>* entries) {
    if (owner_object == nullptr || entries == nullptr) {
        return false;
    }

    const auto* list_object =
        reinterpret_cast<const void*>(reinterpret_cast<uintptr_t>(owner_object) + list_offset);
    std::uint32_t entry_count = 0;
    uintptr_t entry_array = 0;
    if (!TryReadPlainField(list_object, list_count_offset, &entry_count) ||
        !TryReadPointerField(list_object, list_entries_offset, &entry_array) ||
        entry_count == 0 || entry_array == 0) {
        return false;
    }

    entry_count = (std::min)(entry_count, static_cast<std::uint32_t>(max_entries));
    std::vector<uintptr_t> parsed_entries;
    parsed_entries.reserve(entry_count);
    for (std::uint32_t index = 0; index < entry_count; ++index) {
        uintptr_t entry = 0;
        if (!TryReadPointerAt(entry_array + index * sizeof(std::uint32_t), &entry) || entry == 0) {
            continue;
        }
        parsed_entries.push_back(entry);
    }

    if (parsed_entries.empty()) {
        return false;
    }

    *entries = std::move(parsed_entries);
    return true;
}

bool TryReadSettingsPanelRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (settings_address == 0) {
        return false;
    }

    return TryReadEmbeddedWidgetRect(
        reinterpret_cast<const void*>(settings_address),
        0,
        config.settings_control_left_offset,
        config.settings_control_top_offset,
        config.settings_control_width_offset,
        config.settings_control_height_offset,
        left,
        top,
        right,
        bottom);
}

bool TryReadSettingsControlChildPointers(
    const DebugUiOverlayConfig& config,
    uintptr_t control_address,
    std::vector<uintptr_t>* children) {
    if (control_address == 0) {
        return false;
    }

    return TryReadPointerListEntries(
        reinterpret_cast<const void*>(control_address),
        0,
        config.settings_control_child_count_offset,
        config.settings_control_child_list_offset,
        16,
        children);
}

bool TryReadResolvedSettingsOwnedRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t object_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (settings_address == 0 || object_address == 0 || left == nullptr || top == nullptr || right == nullptr ||
        bottom == nullptr) {
        return false;
    }

    if (!TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(object_address),
            left,
            top,
            right,
            bottom)) {
        return false;
    }

    if (IsLocalSubsurfaceRect(*left, *top, *right, *bottom)) {
        (void)TryTranslateSettingsPanelLocalRect(config, settings_address, left, top, right, bottom);
    }

    return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
}

bool TryGetSettingsDoneButtonAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t* control_address) {
    if (settings_address == 0 || control_address == nullptr || config.settings_done_button_control_offset == 0) {
        return false;
    }

    *control_address = settings_address + config.settings_done_button_control_offset;
    return true;
}

bool TryReadSettingsDoneButtonRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    uintptr_t control_address = 0;
    if (!TryGetSettingsDoneButtonAddress(config, settings_address, &control_address)) {
        return false;
    }

    return TryReadTranslatedSettingsWidgetRect(
        config,
        settings_address,
        control_address,
        config.settings_control_left_offset,
        config.settings_control_top_offset,
        config.settings_control_width_offset,
        config.settings_control_height_offset,
        left,
        top,
        right,
        bottom);
}

bool TryReadSimpleMenuPanelRect(
    const DebugUiOverlayConfig& config,
    uintptr_t simple_menu_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (simple_menu_address == 0) {
        return false;
    }

    const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config.simple_menu_vftable);
    uintptr_t object_vftable = 0;
    if (resolved_vftable == 0 ||
        !TryReadPointerField(reinterpret_cast<const void*>(simple_menu_address), 0, &object_vftable) ||
        object_vftable != resolved_vftable) {
        return false;
    }

    return TryReadEmbeddedWidgetRect(
        reinterpret_cast<const void*>(simple_menu_address),
        0,
        config.simple_menu_left_offset,
        config.simple_menu_top_offset,
        config.simple_menu_width_offset,
        config.simple_menu_height_offset,
        left,
        top,
        right,
        bottom);
}
