bool ShouldDismissTrackedDialogUnlocked(ULONGLONG now) {
    const auto left_button_down = IsInputKeyCurrentlyDown(VK_LBUTTON);
    const auto host_process_is_foreground = IsHostProcessForegroundWindow();

    auto dismiss = false;
    const auto& tracked_dialog = g_debug_ui_overlay_state.tracked_dialog;
    if (host_process_is_foreground && tracked_dialog.object_ptr != 0 && tracked_dialog.has_geometry &&
        now - tracked_dialog.captured_at >= kTrackedDialogDismissArmDelayMs) {
        dismiss = left_button_down && !g_debug_ui_overlay_state.previous_left_button_down;
    }

    g_debug_ui_overlay_state.previous_left_button_down = left_button_down;
    return dismiss;
}

bool TryReadMsgBoxGeometry(const void* object, const DebugUiOverlayConfig& config, DialogGeometry* geometry) {
    if (object == nullptr || geometry == nullptr) {
        return false;
    }

    const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config.msgbox_vftable);
    uintptr_t object_vftable = 0;
    if (resolved_vftable == 0 || !TryReadPointerField(object, 0, &object_vftable) || object_vftable != resolved_vftable) {
        return false;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_width = 0.0f;
    float panel_height = 0.0f;
    if (!TryReadPlainField(object, config.msgbox_panel_left_offset, &panel_left) ||
        !TryReadPlainField(object, config.msgbox_panel_top_offset, &panel_top) ||
        !TryReadPlainField(object, config.msgbox_panel_width_offset, &panel_width) ||
        !TryReadPlainField(object, config.msgbox_panel_height_offset, &panel_height)) {
        return false;
    }

    if (!IsPlausibleDialogRect(panel_left, panel_top, panel_width, panel_height)) {
        return false;
    }

    geometry->left = panel_left;
    geometry->top = panel_top;
    geometry->right = geometry->left + panel_width;
    geometry->bottom = geometry->top + panel_height;
    geometry->primary_button = DialogButtonState{};
    geometry->secondary_button = DialogButtonState{};
    if (config.msgbox_primary_button_control_offset != 0) {
        geometry->primary_button.action_id = "dialog.primary";
        geometry->primary_button.object_ptr =
            reinterpret_cast<uintptr_t>(object) + config.msgbox_primary_button_control_offset;
    }
    if (config.msgbox_secondary_button_control_offset != 0) {
        geometry->secondary_button.action_id = "dialog.secondary";
        geometry->secondary_button.object_ptr =
            reinterpret_cast<uintptr_t>(object) + config.msgbox_secondary_button_control_offset;
    }
    (void)TryReadInlineStringObject(object, config.msgbox_primary_label_offset, &geometry->primary_button.label);
    (void)TryReadInlineStringObject(object, config.msgbox_secondary_label_offset, &geometry->secondary_button.label);

    float left = 0.0f;
    float top = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
    if (TryReadPlainField(object, config.msgbox_primary_button_left_offset, &left) &&
        TryReadPlainField(object, config.msgbox_primary_button_top_offset, &top) &&
        TryReadPlainField(object, config.msgbox_primary_button_width_offset, &width) &&
        TryReadPlainField(object, config.msgbox_primary_button_height_offset, &height) &&
        IsPlausibleDialogButtonRect(left, top, width, height)) {
        geometry->primary_button.has_bounds = true;
        geometry->primary_button.left = left;
        geometry->primary_button.top = top;
        geometry->primary_button.right = left + width;
        geometry->primary_button.bottom = top + height;
    }

    float half_width = 0.0f;
    float half_height = 0.0f;
    if (TryReadPlainField(object, config.msgbox_secondary_button_left_offset, &left) &&
        TryReadPlainField(object, config.msgbox_secondary_button_top_offset, &top) &&
        TryReadPlainField(object, config.msgbox_secondary_button_half_width_offset, &half_width) &&
        TryReadPlainField(object, config.msgbox_secondary_button_half_height_offset, &half_height)) {
        const auto resolved_width = half_width * 2.0f;
        const auto resolved_height = half_height * 2.0f;
        if (IsPlausibleDialogButtonRect(left, top, resolved_width, resolved_height)) {
            geometry->secondary_button.has_bounds = true;
            geometry->secondary_button.left = left;
            geometry->secondary_button.top = top;
            geometry->secondary_button.right = left + resolved_width;
            geometry->secondary_button.bottom = top + resolved_height;
        }
    }

    return true;
}

bool TryReadActiveTitleMainMenu(
    const DebugUiOverlayConfig& config,
    uintptr_t* bundle_address,
    uintptr_t* main_menu_address) {
    if (main_menu_address == nullptr) {
        return false;
    }

    uintptr_t tracked_main_menu = 0;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        tracked_main_menu = g_debug_ui_overlay_state.tracked_title_main_menu_object;
    }

    if (tracked_main_menu == 0) {
        return false;
    }

    const auto resolved_main_menu_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(config.title_main_menu_vftable);
    uintptr_t object_vftable = 0;
    if (resolved_main_menu_vftable == 0 ||
        !TryReadPointerField(reinterpret_cast<const void*>(tracked_main_menu), 0, &object_vftable) ||
        object_vftable != resolved_main_menu_vftable) {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        if (g_debug_ui_overlay_state.tracked_title_main_menu_object == tracked_main_menu) {
            g_debug_ui_overlay_state.tracked_title_main_menu_object = 0;
        }
        return false;
    }

    if (bundle_address != nullptr) {
        *bundle_address = 0;
    }
    *main_menu_address = tracked_main_menu;
    return true;
}

bool TryReadTrackedDarkCloudBrowser(uintptr_t* browser_address) {
    if (browser_address == nullptr) {
        return false;
    }

    const auto now = GetTickCount64();
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_browser = g_debug_ui_overlay_state.dark_cloud_browser_render;
    if (tracked_browser.tracked_object_ptr == 0) {
        return false;
    }

    if (tracked_browser.render_depth == 0 &&
        now - tracked_browser.captured_at > kTrackedDarkCloudBrowserMaximumIdleMs) {
        tracked_browser.tracked_object_ptr = 0;
        g_debug_ui_overlay_state.dark_cloud_browser_panel = TrackedWidgetRectState{};
        g_debug_ui_overlay_state.dark_cloud_browser_modal_root = TrackedWidgetRectState{};
        return false;
    }

    *browser_address = tracked_browser.tracked_object_ptr;
    return true;
}

bool TryReadTrackedDialogObject(uintptr_t* dialog_address) {
    if (dialog_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.tracked_dialog.object_ptr == 0) {
        return false;
    }

    *dialog_address = g_debug_ui_overlay_state.tracked_dialog.object_ptr;
    return true;
}

bool TryGetActiveDarkCloudBrowserRender(uintptr_t* browser_address) {
    if (browser_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.dark_cloud_browser_render.render_depth == 0 ||
        g_debug_ui_overlay_state.dark_cloud_browser_render.active_object_ptr == 0) {
        return false;
    }

    *browser_address = g_debug_ui_overlay_state.dark_cloud_browser_render.active_object_ptr;
    return true;
}

bool TryGetCurrentDarkCloudBrowser(uintptr_t* browser_address) {
    if (TryGetActiveDarkCloudBrowserRender(browser_address)) {
        return true;
    }

    return TryReadTrackedDarkCloudBrowser(browser_address);
}

bool TryGetActiveHallOfFameRender(uintptr_t* hof_address) {
    if (hof_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.hall_of_fame_render.render_depth == 0 ||
        g_debug_ui_overlay_state.hall_of_fame_render.active_object_ptr == 0) {
        return false;
    }

    *hof_address = g_debug_ui_overlay_state.hall_of_fame_render.active_object_ptr;
    return true;
}

bool TryGetCurrentHallOfFame(uintptr_t* hof_address) {
    if (hof_address == nullptr) {
        return false;
    }

    const auto now = GetTickCount64();
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_hof = g_debug_ui_overlay_state.hall_of_fame_render;

    if (tracked_hof.render_depth > 0 && tracked_hof.active_object_ptr != 0) {
        *hof_address = tracked_hof.active_object_ptr;
        return true;
    }

    if (tracked_hof.tracked_object_ptr == 0) {
        return false;
    }

    if (now - tracked_hof.captured_at > kTrackedHallOfFameMaximumIdleMs) {
        tracked_hof.tracked_object_ptr = 0;
        return false;
    }

    *hof_address = tracked_hof.tracked_object_ptr;
    return true;
}

bool TryGetActiveSpellPickerRender(uintptr_t* picker_address) {
    if (picker_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.spell_picker_render.render_depth == 0 ||
        g_debug_ui_overlay_state.spell_picker_render.active_object_ptr == 0) {
        return false;
    }

    *picker_address = g_debug_ui_overlay_state.spell_picker_render.active_object_ptr;
    return true;
}

void RememberDarkCloudBrowserPanelRect(
    uintptr_t browser_address,
    float left,
    float top,
    float right,
    float bottom) {
    if (browser_address == 0 ||
        !IsPlausibleSurfaceWidgetRect(left, top, right - left, bottom - top)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_panel = g_debug_ui_overlay_state.dark_cloud_browser_panel;
    tracked_panel.root_object_ptr = browser_address;
    tracked_panel.captured_at = GetTickCount64();
    tracked_panel.has_rect = true;
    tracked_panel.left = left;
    tracked_panel.top = top;
    tracked_panel.right = right;
    tracked_panel.bottom = bottom;
}

bool TryReadTrackedDarkCloudBrowserPanelRect(
    uintptr_t browser_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (browser_address == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    const auto& tracked_panel = g_debug_ui_overlay_state.dark_cloud_browser_panel;
    if (!tracked_panel.has_rect || tracked_panel.root_object_ptr != browser_address) {
        return false;
    }

    if (GetTickCount64() - tracked_panel.captured_at > kTrackedDarkCloudBrowserPanelMaximumIdleMs) {
        return false;
    }

    *left = tracked_panel.left;
    *top = tracked_panel.top;
    *right = tracked_panel.right;
    *bottom = tracked_panel.bottom;
    return true;
}

void RememberDarkCloudBrowserModalRootRect(
    uintptr_t browser_address,
    float left,
    float top,
    float right,
    float bottom) {
    if (browser_address == 0 ||
        !IsPlausibleSurfaceWidgetRect(left, top, right - left, bottom - top)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_modal_root = g_debug_ui_overlay_state.dark_cloud_browser_modal_root;
    tracked_modal_root.root_object_ptr = browser_address;
    tracked_modal_root.captured_at = GetTickCount64();
    tracked_modal_root.has_rect = true;
    tracked_modal_root.left = left;
    tracked_modal_root.top = top;
    tracked_modal_root.right = right;
    tracked_modal_root.bottom = bottom;
}

bool TryReadTrackedDarkCloudBrowserModalRootRect(
    uintptr_t browser_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (browser_address == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    const auto& tracked_modal_root = g_debug_ui_overlay_state.dark_cloud_browser_modal_root;
    if (!tracked_modal_root.has_rect || tracked_modal_root.root_object_ptr != browser_address) {
        return false;
    }

    if (GetTickCount64() - tracked_modal_root.captured_at > kTrackedDarkCloudBrowserModalMaximumIdleMs) {
        return false;
    }

    *left = tracked_modal_root.left;
    *top = tracked_modal_root.top;
    *right = tracked_modal_root.right;
    *bottom = tracked_modal_root.bottom;
    return true;
}

bool TryGetLiveSettingsRender(uintptr_t* settings_address) {
    if (settings_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.settings_render.render_depth != 0 &&
        g_debug_ui_overlay_state.settings_render.active_object_ptr != 0) {
        *settings_address = g_debug_ui_overlay_state.settings_render.active_object_ptr;
        return true;
    }

    return false;
}

bool TryGetActiveSettingsRender(uintptr_t* settings_address) {
    if (TryGetLiveSettingsRender(settings_address)) {
        return true;
    }

    if (settings_address == nullptr) {
        return false;
    }

    const auto now = GetTickCount64();
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.settings_render.tracked_object_ptr == 0) {
        return false;
    }

    if (now - g_debug_ui_overlay_state.settings_render.captured_at > kTrackedSettingsMaximumIdleMs) {
        g_debug_ui_overlay_state.settings_render.tracked_object_ptr = 0;
        return false;
    }

    *settings_address = g_debug_ui_overlay_state.settings_render.tracked_object_ptr;
    return true;
}

bool TryGetActiveMyQuickPanelRender(uintptr_t* quick_panel_address) {
    if (quick_panel_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.myquick_panel_render.render_depth == 0 ||
        g_debug_ui_overlay_state.myquick_panel_render.active_object_ptr == 0) {
        return false;
    }

    *quick_panel_address = g_debug_ui_overlay_state.myquick_panel_render.active_object_ptr;
    return true;
}

bool TryReadTrackedMyQuickPanel(uintptr_t* quick_panel_address) {
    if (quick_panel_address == nullptr) {
        return false;
    }

    const auto now = GetTickCount64();
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.myquick_panel_modal.modal_depth != 0 &&
        g_debug_ui_overlay_state.myquick_panel_modal.active_object_ptr != 0) {
        *quick_panel_address = g_debug_ui_overlay_state.myquick_panel_modal.active_object_ptr;
        return true;
    }

    if (g_debug_ui_overlay_state.myquick_panel_render.tracked_object_ptr == 0 ||
        now - g_debug_ui_overlay_state.myquick_panel_render.captured_at > kTrackedMyQuickPanelMaximumIdleMs) {
        return false;
    }

    *quick_panel_address = g_debug_ui_overlay_state.myquick_panel_render.tracked_object_ptr;
    return true;
}

bool TryGetActiveSimpleMenu(uintptr_t* simple_menu_address) {
    if (simple_menu_address == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.simple_menu.modal_depth == 0 ||
        g_debug_ui_overlay_state.simple_menu.active_object_ptr == 0) {
        return false;
    }

    *simple_menu_address = g_debug_ui_overlay_state.simple_menu.active_object_ptr;
    return true;
}

uintptr_t GetTrackedDialogObject() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    return g_debug_ui_overlay_state.tracked_dialog.object_ptr;
}

bool TryReadUiRenderContext(const DebugUiOverlayConfig& config, uintptr_t* render_context_address) {
    if (render_context_address == nullptr) {
        return false;
    }

    uintptr_t render_context = 0;
    if (!TryReadResolvedGamePointer(config.ui_render_context_global, &render_context) || render_context == 0) {
        return false;
    }

    *render_context_address = render_context;
    return true;
}

bool IsRecognizedTitleMainMenuLine(std::string_view label) {
    return label == "PLAY" || label == "explore the" || label == "DARK CLOUD" || label == "SETTINGS" ||
           label == "HALL of FAME" || label == "resume" || label == "LAST GAME" || label == "NEW GAME" ||
           label == "BACK" || label == "quit";
}

std::size_t CountRecognizedTitleMainMenuLines(const std::vector<ObservedUiElement>& exact_lines) {
    std::size_t count = 0;
    for (const auto& line : exact_lines) {
        if (IsRecognizedTitleMainMenuLine(line.label)) {
            ++count;
        }
    }
    return count;
}

bool TryReadMainMenuMode(const DebugUiOverlayConfig& config, uintptr_t main_menu_address, int* mode) {
    if (mode == nullptr || main_menu_address == 0) {
        return false;
    }

    return TryReadPlainField(reinterpret_cast<const void*>(main_menu_address), config.title_main_menu_mode_offset, mode);
}

bool TryReadMainMenuButtonRect(
    const DebugUiOverlayConfig& config,
    uintptr_t main_menu_address,
    std::size_t button_index,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (main_menu_address == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr ||
        button_index >= config.title_main_menu_button_count) {
        return false;
    }

    const auto button_address = main_menu_address + config.title_main_menu_button_array_offset +
                                button_index * config.title_main_menu_button_stride;

    float rect_left = 0.0f;
    float rect_top = 0.0f;
    float rect_width = 0.0f;
    float rect_height = 0.0f;
    const auto* button_object = reinterpret_cast<const void*>(button_address);
    if (!TryReadPlainField(button_object, config.title_main_menu_button_left_offset, &rect_left) ||
        !TryReadPlainField(button_object, config.title_main_menu_button_top_offset, &rect_top) ||
        !TryReadPlainField(button_object, config.title_main_menu_button_width_offset, &rect_width) ||
        !TryReadPlainField(button_object, config.title_main_menu_button_height_offset, &rect_height) ||
        !IsPlausibleDialogButtonRect(rect_left, rect_top, rect_width, rect_height)) {
        return false;
    }

    *left = rect_left;
    *top = rect_top;
    *right = rect_left + rect_width;
    *bottom = rect_top + rect_height;
    return true;
}

std::vector<std::string> BuildMainMenuButtonLabels(int mode) {
    switch (mode) {
    case 0:
        return {"PLAY", "EXPLORE THE DARK CLOUD", "SETTINGS", "HALL OF FAME"};
    case 1:
        return {"RESUME LAST GAME", "NEW GAME", "HALL OF FAME", "BACK"};
    default:
        return {};
    }
}

void MergeTrackedDialogGeometryLocked(TrackedDialogState* tracked_dialog, const DialogGeometry& geometry) {
    if (tracked_dialog == nullptr) {
        return;
    }

    tracked_dialog->has_geometry = true;
    tracked_dialog->left = geometry.left;
    tracked_dialog->top = geometry.top;
    tracked_dialog->right = geometry.right;
    tracked_dialog->bottom = geometry.bottom;
    if (!geometry.primary_button.label.empty()) {
        tracked_dialog->primary_button.label = geometry.primary_button.label;
    }
    if (!geometry.primary_button.action_id.empty()) {
        tracked_dialog->primary_button.action_id = geometry.primary_button.action_id;
    }
    if (geometry.primary_button.object_ptr != 0) {
        tracked_dialog->primary_button.object_ptr = geometry.primary_button.object_ptr;
    }
    if (geometry.primary_button.has_bounds) {
        tracked_dialog->primary_button.has_bounds = true;
        tracked_dialog->primary_button.left = geometry.primary_button.left;
        tracked_dialog->primary_button.top = geometry.primary_button.top;
        tracked_dialog->primary_button.right = geometry.primary_button.right;
        tracked_dialog->primary_button.bottom = geometry.primary_button.bottom;
    }

    if (!geometry.secondary_button.label.empty()) {
        tracked_dialog->secondary_button.label = geometry.secondary_button.label;
    }
    if (!geometry.secondary_button.action_id.empty()) {
        tracked_dialog->secondary_button.action_id = geometry.secondary_button.action_id;
    }
    if (geometry.secondary_button.object_ptr != 0) {
        tracked_dialog->secondary_button.object_ptr = geometry.secondary_button.object_ptr;
    }
    if (geometry.secondary_button.has_bounds) {
        tracked_dialog->secondary_button.has_bounds = true;
        tracked_dialog->secondary_button.left = geometry.secondary_button.left;
        tracked_dialog->secondary_button.top = geometry.secondary_button.top;
        tracked_dialog->secondary_button.right = geometry.secondary_button.right;
        tracked_dialog->secondary_button.bottom = geometry.secondary_button.bottom;
    }
}

std::string TrimAsciiWhitespace(std::string_view value) {
    std::size_t start = 0;
    while (start < value.size() && std::isspace(static_cast<unsigned char>(value[start])) != 0) {
        ++start;
    }

    std::size_t end = value.size();
    while (end > start && std::isspace(static_cast<unsigned char>(value[end - 1])) != 0) {
        --end;
    }

    return std::string(value.substr(start, end - start));
}

std::string ToLowerAscii(std::string_view value) {
    std::string lowered;
    lowered.reserve(value.size());
    for (const unsigned char ch : value) {
        lowered.push_back(static_cast<char>(std::tolower(ch)));
    }
    return lowered;
}

bool ContainsCaseInsensitive(std::string_view value, std::string_view needle) {
    return ToLowerAscii(value).find(ToLowerAscii(needle)) != std::string::npos;
}
