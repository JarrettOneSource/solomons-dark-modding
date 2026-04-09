bool TryReadPrintableCString(uintptr_t address, std::string* value, std::size_t minimum_length = 1, std::size_t maximum_length = 96) {
    if (address == 0 || value == nullptr || maximum_length == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::string buffer;
    buffer.reserve(maximum_length);
    for (std::size_t index = 0; index < maximum_length; ++index) {
        char ch = '\0';
        if (!memory.TryReadValue(address + index, &ch)) {
            return false;
        }

        if (ch == '\0') {
            break;
        }

        if (!IsPrintableUiCharacter(static_cast<unsigned char>(ch))) {
            return false;
        }

        buffer.push_back(ch);
    }

    if (buffer.size() < minimum_length || !IsPlausibleUiLabel(buffer)) {
        return false;
    }

    *value = std::move(buffer);
    return true;
}

bool TryReadStringObject(uintptr_t object_address, std::string* value) {
    if (object_address == 0 || value == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();

    std::uint32_t text_pointer = 0;
    std::uint32_t length = 0;
    if (!memory.TryReadValue(object_address + 0x4, &text_pointer) ||
        !memory.TryReadValue(object_address + 0x10, &length)) {
        return false;
    }

    if (text_pointer == 0 || length == 0 || length > 96) {
        return false;
    }

    std::string text;
    if (!TryReadPrintableCString(text_pointer, &text, length, length)) {
        return false;
    }

    *value = std::move(text);
    return true;
}

bool TryResolveObjectLabel(uintptr_t object_address, std::string* value) {
    if (object_address == 0 || value == nullptr) {
        return false;
    }

    if (TryReadStringObject(object_address, value)) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    for (std::size_t offset = 0; offset < 0x100; offset += sizeof(std::uint32_t)) {
        std::uint32_t candidate_pointer = 0;
        if (!memory.TryReadValue(object_address + offset, &candidate_pointer) || candidate_pointer == 0) {
            continue;
        }

        if (TryReadStringObject(candidate_pointer, value)) {
            return true;
        }

        if (TryReadPrintableCString(candidate_pointer, value, 2, 96)) {
            return true;
        }
    }

    return false;
}

template <typename T>
bool TryReadPlainField(const void* object, std::size_t byte_offset, T* value) {
    if (object == nullptr || value == nullptr) {
        return false;
    }

    return ProcessMemory::Instance().TryReadField(reinterpret_cast<uintptr_t>(object), byte_offset, value);
}

bool TryReadPointerField(const void* object, std::size_t byte_offset, uintptr_t* value) {
    if (object == nullptr || value == nullptr) {
        return false;
    }

    std::uint32_t raw_value = 0;
    if (!ProcessMemory::Instance().TryReadField(reinterpret_cast<uintptr_t>(object), byte_offset, &raw_value)) {
        return false;
    }

    *value = raw_value;
    return true;
}

bool TryReadPointerAt(uintptr_t address, uintptr_t* value) {
    if (address == 0 || value == nullptr) {
        return false;
    }

    std::uint32_t raw_value = 0;
    if (!ProcessMemory::Instance().TryReadValue(address, &raw_value)) {
        return false;
    }

    *value = raw_value;
    return true;
}

bool TryReadInlineStringObject(const void* object, std::size_t byte_offset, std::string* value) {
    if (object == nullptr) {
        return false;
    }

    return TryReadStringObject(reinterpret_cast<uintptr_t>(object) + byte_offset, value);
}

template <typename T>
bool TryReadResolvedGameValue(uintptr_t absolute_address, T* value) {
    if (value == nullptr) {
        return false;
    }

    const auto resolved_address = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved_address != 0 && ProcessMemory::Instance().TryReadValue(resolved_address, value);
}

bool TryReadResolvedGamePointer(uintptr_t absolute_address, uintptr_t* value) {
    if (value == nullptr) {
        return false;
    }

    std::uint32_t raw_value = 0;
    if (!TryReadResolvedGameValue(absolute_address, &raw_value)) {
        return false;
    }

    *value = raw_value;
    return true;
}

bool IsPlausibleDialogRect(float left, float top, float width, float height) {
    if (!std::isfinite(left) || !std::isfinite(top) || !std::isfinite(width) || !std::isfinite(height)) {
        return false;
    }

    if (left < 0.0f || top < 0.0f || width < 96.0f || height < 96.0f) {
        return false;
    }

    if (left > 8192.0f || top > 8192.0f || width > 8192.0f || height > 8192.0f) {
        return false;
    }

    return true;
}

bool IsPlausibleDialogButtonRect(float left, float top, float width, float height) {
    if (!std::isfinite(left) || !std::isfinite(top) || !std::isfinite(width) || !std::isfinite(height)) {
        return false;
    }

    if (left < 0.0f || top < 0.0f || width < 48.0f || height < 24.0f) {
        return false;
    }

    if (left > 8192.0f || top > 8192.0f || width > 2048.0f || height > 512.0f) {
        return false;
    }

    return true;
}

bool IsPlausibleTitleCoordinate(float value) {
    return std::isfinite(value) && value >= -1024.0f && value <= 8192.0f;
}

bool IsPlausibleSurfaceWidgetRect(float left, float top, float width, float height) {
    if (!std::isfinite(left) || !std::isfinite(top) || !std::isfinite(width) || !std::isfinite(height)) {
        return false;
    }

    if (left < -1024.0f || top < -1024.0f || width < 12.0f || height < 12.0f) {
        return false;
    }

    if (left > 8192.0f || top > 8192.0f || width > 4096.0f || height > 2048.0f) {
        return false;
    }

    return true;
}

bool IsInputKeyCurrentlyDown(int virtual_key) {
    return (GetAsyncKeyState(virtual_key) & 0x8000) != 0;
}

bool IsHostProcessForegroundWindow() {
    const auto foreground_window = GetForegroundWindow();
    if (foreground_window == nullptr) {
        return false;
    }

    DWORD process_id = 0;
    GetWindowThreadProcessId(foreground_window, &process_id);
    return process_id == GetCurrentProcessId();
}

bool TryReadEmbeddedWidgetRect(
    const void* owner_object,
    std::size_t widget_offset,
    std::size_t left_offset,
    std::size_t top_offset,
    std::size_t width_offset,
    std::size_t height_offset,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (owner_object == nullptr || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    const auto widget_object = reinterpret_cast<const void*>(reinterpret_cast<uintptr_t>(owner_object) + widget_offset);
    float widget_left = 0.0f;
    float widget_top = 0.0f;
    float widget_width = 0.0f;
    float widget_height = 0.0f;
    if (!TryReadPlainField(widget_object, left_offset, &widget_left) ||
        !TryReadPlainField(widget_object, top_offset, &widget_top) ||
        !TryReadPlainField(widget_object, width_offset, &widget_width) ||
        !TryReadPlainField(widget_object, height_offset, &widget_height) ||
        !IsPlausibleSurfaceWidgetRect(widget_left, widget_top, widget_width, widget_height)) {
        return false;
    }

    *left = widget_left;
    *top = widget_top;
    *right = widget_left + widget_width;
    *bottom = widget_top + widget_height;
    return true;
}

uintptr_t NormalizeObservedCodeAddress(uintptr_t runtime_address) {
    const auto configured_image_base = GetConfiguredImageBase();
    const auto module_base = ProcessMemory::Instance().ModuleBase();
    if (runtime_address == 0 || configured_image_base == 0 || module_base == 0 || runtime_address < module_base) {
        return runtime_address;
    }

    return configured_image_base + (runtime_address - module_base);
}

bool IsTrustedSettingsSectionHeaderCaller(const DebugUiOverlayConfig& config, uintptr_t normalized_caller_address) {
    return normalized_caller_address == config.settings_section_header_text_caller;
}

bool IsTrustedSettingsPanelTitleCaller(const DebugUiOverlayConfig& config, uintptr_t normalized_caller_address) {
    return normalized_caller_address == config.settings_panel_title_text_caller;
}

bool IsTrustedSettingsControlLabelCaller(const DebugUiOverlayConfig& config, uintptr_t normalized_caller_address) {
    return normalized_caller_address == config.settings_control_label_text_caller_primary ||
           normalized_caller_address == config.settings_control_label_text_caller_secondary;
}

bool IsTrustedSettingsTextCaller(const DebugUiOverlayConfig& config, uintptr_t normalized_caller_address) {
    return IsTrustedSettingsPanelTitleCaller(config, normalized_caller_address) ||
           IsTrustedSettingsSectionHeaderCaller(config, normalized_caller_address) ||
           IsTrustedSettingsControlLabelCaller(config, normalized_caller_address);
}

bool TryTranslateSettingsPanelLocalRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (settings_address == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSettingsPanelRect(config, settings_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return false;
    }

    *left += panel_left;
    *right += panel_left;
    *top += panel_top;
    *bottom += panel_top;
    return true;
}

bool TryReadTranslatedSettingsWidgetRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t source_object_ptr,
    std::size_t left_offset,
    std::size_t top_offset,
    std::size_t width_offset,
    std::size_t height_offset,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (source_object_ptr == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    if (!TryReadEmbeddedWidgetRect(
            reinterpret_cast<const void*>(source_object_ptr),
            0,
            left_offset,
            top_offset,
            width_offset,
            height_offset,
            left,
            top,
            right,
            bottom)) {
        return false;
    }

    return TryTranslateSettingsPanelLocalRect(config, settings_address, left, top, right, bottom);
}

bool TryReadOwnedSettingsTextRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t normalized_caller_address,
    uintptr_t source_object_ptr,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (settings_address == 0 || source_object_ptr == 0 || left == nullptr || top == nullptr || right == nullptr ||
        bottom == nullptr) {
        return false;
    }

    if (IsTrustedSettingsSectionHeaderCaller(config, normalized_caller_address)) {
        return TryReadTranslatedSettingsWidgetRect(
            config,
            settings_address,
            source_object_ptr,
            config.settings_section_widget_left_offset,
            config.settings_section_widget_top_offset,
            config.settings_section_widget_width_offset,
            config.settings_section_widget_height_offset,
            left,
            top,
            right,
            bottom);
    }

    if (IsTrustedSettingsControlLabelCaller(config, normalized_caller_address)) {
        return TryReadTranslatedSettingsWidgetRect(
            config,
            settings_address,
            source_object_ptr,
            config.settings_control_left_offset,
            config.settings_control_top_offset,
            config.settings_control_width_offset,
            config.settings_control_height_offset,
            left,
            top,
            right,
            bottom);
    }

    return false;
}

bool TryReadQuickPanelPanelRect(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (quick_panel_address == 0) {
        return false;
    }

    return TryReadEmbeddedWidgetRect(
        reinterpret_cast<const void*>(quick_panel_address),
        0,
        config.myquick_panel_left_offset,
        config.myquick_panel_top_offset,
        config.myquick_panel_width_offset,
        config.myquick_panel_height_offset,
        left,
        top,
        right,
        bottom);
}

bool TryReadDarkCloudBrowserTextOwnerAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t text_object_address,
    uintptr_t* owner_address) {
    if (text_object_address == 0 || owner_address == nullptr) {
        return false;
    }

    return TryReadPointerField(
               reinterpret_cast<const void*>(text_object_address),
               config.dark_cloud_browser_text_owner_offset,
               owner_address) &&
           *owner_address != 0;
}

bool TryReadMyQuickPanelBuilderOwnerAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t* owner_address) {
    if (quick_panel_address == 0 || owner_address == nullptr) {
        return false;
    }

    return TryReadPointerField(
               reinterpret_cast<const void*>(quick_panel_address),
               config.myquick_panel_builder_owner_offset,
               owner_address) &&
           *owner_address != 0;
}

bool TryReadMyQuickPanelBuilderAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t* builder_address) {
    if (quick_panel_address == 0 || builder_address == nullptr) {
        return false;
    }

    uintptr_t owner_address = 0;
    if (!TryReadMyQuickPanelBuilderOwnerAddress(config, quick_panel_address, &owner_address) || owner_address == 0) {
        return false;
    }

    return TryReadPointerField(
               reinterpret_cast<const void*>(owner_address),
               config.myquick_panel_builder_offset,
               builder_address) &&
           *builder_address != 0;
}

bool TryReadMyQuickPanelBuilderRootControlAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t* root_control_address) {
    if (quick_panel_address == 0 || root_control_address == nullptr) {
        return false;
    }

    uintptr_t builder_address = 0;
    if (!TryReadMyQuickPanelBuilderAddress(config, quick_panel_address, &builder_address) || builder_address == 0) {
        return false;
    }

    return TryReadPointerField(
               reinterpret_cast<const void*>(builder_address),
               config.myquick_panel_builder_root_control_offset,
               root_control_address) &&
           *root_control_address != 0;
}

bool TryReadMyQuickPanelBuilderWidgetPointers(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    std::vector<uintptr_t>* widget_pointers) {
    if (quick_panel_address == 0 || widget_pointers == nullptr) {
        return false;
    }

    uintptr_t builder_address = 0;
    if (!TryReadMyQuickPanelBuilderAddress(config, quick_panel_address, &builder_address) || builder_address == 0) {
        return false;
    }

    uintptr_t widget_entries_begin = 0;
    uintptr_t widget_entries_end = 0;
    if (!TryReadPointerField(
            reinterpret_cast<const void*>(builder_address),
            config.myquick_panel_builder_widget_entries_begin_offset,
            &widget_entries_begin) ||
        !TryReadPointerField(
            reinterpret_cast<const void*>(builder_address),
            config.myquick_panel_builder_widget_entries_end_offset,
            &widget_entries_end) ||
        widget_entries_begin == 0 || widget_entries_end <= widget_entries_begin ||
        config.myquick_panel_builder_widget_entry_stride < sizeof(uintptr_t) ||
        config.myquick_panel_builder_widget_entry_stride > 0x100) {
        return false;
    }

    const auto raw_span = widget_entries_end - widget_entries_begin;
    const auto entry_count = (std::min)(
        raw_span / config.myquick_panel_builder_widget_entry_stride,
        config.max_tracked_elements_per_frame);
    if (entry_count == 0) {
        return false;
    }

    std::vector<uintptr_t> parsed_widgets;
    parsed_widgets.reserve(entry_count * 2);
    for (std::size_t entry_index = 0; entry_index < entry_count; ++entry_index) {
        const auto entry_address =
            widget_entries_begin + entry_index * config.myquick_panel_builder_widget_entry_stride;

        uintptr_t primary_widget = 0;
        if (TryReadPointerAt(
                entry_address + config.myquick_panel_builder_widget_entry_primary_offset,
                &primary_widget) &&
            primary_widget != 0) {
            parsed_widgets.push_back(primary_widget);
        }

        uintptr_t secondary_widget = 0;
        if (TryReadPointerAt(
                entry_address + config.myquick_panel_builder_widget_entry_secondary_offset,
                &secondary_widget) &&
            secondary_widget != 0) {
            parsed_widgets.push_back(secondary_widget);
        }
    }

    std::sort(parsed_widgets.begin(), parsed_widgets.end());
    parsed_widgets.erase(std::unique(parsed_widgets.begin(), parsed_widgets.end()), parsed_widgets.end());
    if (parsed_widgets.empty()) {
        return false;
    }

    *widget_pointers = std::move(parsed_widgets);
    return true;
}

bool IsQuickPanelOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t object_address);
bool TryResolveQuickPanelOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t primary_candidate,
    uintptr_t alternate_candidate,
    uintptr_t* owned_object_address);
bool TryReadTranslatedQuickPanelWidgetRect(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t object_address,
    float* left,
    float* top,
    float* right,
    float* bottom);

bool TryResolveMyQuickPanelBuilderOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t candidate_address,
    uintptr_t* owned_object_address) {
    if (quick_panel_address == 0 || candidate_address == 0 || owned_object_address == nullptr) {
        return false;
    }

    uintptr_t root_control_address = 0;
    std::vector<uintptr_t> widget_pointers;
    if (!TryReadMyQuickPanelBuilderRootControlAddress(config, quick_panel_address, &root_control_address) ||
        root_control_address == 0 ||
        !TryReadMyQuickPanelBuilderWidgetPointers(config, quick_panel_address, &widget_pointers)) {
        return false;
    }

    for (const auto widget_pointer : widget_pointers) {
        if (widget_pointer == 0) {
            continue;
        }

        if (candidate_address == widget_pointer ||
            IsWidgetOwnedByRootAtOffset(
                config,
                widget_pointer,
                candidate_address,
                config.myquick_panel_widget_parent_offset)) {
            *owned_object_address = widget_pointer;
            return true;
        }
    }

    if (candidate_address == root_control_address ||
        IsWidgetOwnedByRootAtOffset(
            config,
            root_control_address,
            candidate_address,
            config.myquick_panel_widget_parent_offset)) {
        *owned_object_address = candidate_address;
        return true;
    }

    return false;
}

bool TryReadTranslatedMyQuickPanelBuilderWidgetRect(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t object_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (quick_panel_address == 0 || object_address == 0 || left == nullptr || top == nullptr || right == nullptr ||
        bottom == nullptr) {
        return false;
    }

    uintptr_t root_control_address = 0;
    if (!TryReadMyQuickPanelBuilderRootControlAddress(config, quick_panel_address, &root_control_address) ||
        root_control_address == 0) {
        return false;
    }

    float local_left = 0.0f;
    float local_top = 0.0f;
    float local_right = 0.0f;
    float local_bottom = 0.0f;
    if (object_address == root_control_address) {
        if (!TryReadExactControlRect(
                config,
                reinterpret_cast<const void*>(object_address),
                &local_left,
                &local_top,
                &local_right,
                &local_bottom)) {
            return false;
        }
    } else if (!TryReadTranslatedWidgetRectToRootAtOffset(
                   config,
                   root_control_address,
                   object_address,
                   config.myquick_panel_widget_parent_offset,
                   &local_left,
                   &local_top,
                   &local_right,
                   &local_bottom)) {
        return false;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadQuickPanelPanelRect(config, quick_panel_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return false;
    }

    *left = panel_left + local_left;
    *top = panel_top + local_top;
    *right = panel_left + local_right;
    *bottom = panel_top + local_bottom;
    return IsPlausibleSurfaceWidgetRect(*left, *top, *right - *left, *bottom - *top);
}

