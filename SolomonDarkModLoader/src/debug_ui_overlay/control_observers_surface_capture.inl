void RecordExactControlElement(
    std::string surface_id,
    std::string surface_title,
    uintptr_t source_object_ptr,
    uintptr_t caller_address,
    float left,
    float top,
    float right,
    float bottom,
    std::string label) {
    if (!IsPlausibleSurfaceWidgetRect(left, top, right - left, bottom - top)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.frame_exact_control_elements.size() >=
        g_debug_ui_overlay_state.config.max_tracked_elements_per_frame) {
        return;
    }

    const auto identity = source_object_ptr != 0
        ? source_object_ptr
        : BuildObservationIdentityKey(reinterpret_cast<void*>(caller_address), left, top, caller_address, false);

    for (auto& element : g_debug_ui_overlay_state.frame_exact_control_elements) {
        if (element.object_ptr == identity && element.surface_id == surface_id) {
            element.min_x = (std::min)(element.min_x, left);
            element.max_x = (std::max)(element.max_x, right);
            element.min_y = (std::min)(element.min_y, top);
            element.max_y = (std::max)(element.max_y, bottom);
            ++element.sample_count;
            if (element.label.empty() && !label.empty()) {
                element.label = std::move(label);
            }
            return;
        }
    }

    ObservedUiElement element;
    element.surface_id = std::move(surface_id);
    element.surface_title = std::move(surface_title);
    element.object_ptr = identity;
    element.caller_address = caller_address;
    element.min_x = left;
    element.max_x = right;
    element.min_y = top;
    element.max_y = bottom;
    element.sample_count = 1;
    element.label = std::move(label);
    g_debug_ui_overlay_state.frame_exact_control_elements.push_back(std::move(element));

    if (!g_debug_ui_overlay_state.first_exact_control_render_logged) {
        g_debug_ui_overlay_state.first_exact_control_render_logged = true;
        const auto& first_element = g_debug_ui_overlay_state.frame_exact_control_elements.back();
        Log(
            "Debug UI overlay captured its first exact control render. surface=" + first_element.surface_id +
            " label=" + SanitizeDebugLogLabel(first_element.label) + " caller=" +
            HexString(first_element.caller_address));
    }
}

void ObserveMainMenuControlRender(void* control_object, uintptr_t caller_address, std::string label) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr || control_object == nullptr) {
        return;
    }

    uintptr_t settings_address = 0;
    if (TryGetActiveSettingsRender(&settings_address) && settings_address != 0) {
        return;
    }

    uintptr_t browser_address = 0;
    if (TryGetActiveDarkCloudBrowserRender(&browser_address) && browser_address != 0) {
        return;
    }

    uintptr_t simple_menu_address = 0;
    if (TryGetActiveSimpleMenu(&simple_menu_address) && simple_menu_address != 0) {
        return;
    }

    uintptr_t quick_panel_address = 0;
    if (TryReadTrackedMyQuickPanel(&quick_panel_address) && quick_panel_address != 0) {
        return;
    }

    uintptr_t main_menu_address = 0;
    if (!TryReadActiveTitleMainMenu(*config, nullptr, &main_menu_address) || main_menu_address == 0) {
        return;
    }

    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryReadExactControlRect(*config, control_object, &left, &top, &right, &bottom)) {
        return;
    }

    const auto control_address = reinterpret_cast<uintptr_t>(control_object);
    static int s_main_menu_exact_control_logs_remaining = 16;
    if (s_main_menu_exact_control_logs_remaining > 0) {
        --s_main_menu_exact_control_logs_remaining;
        std::string cached_label;
        (void)TryReadCachedObjectLabel(control_address, &cached_label);
        Log(
            "Debug UI main menu exact control capture: menu=" + HexString(main_menu_address) +
            " control=" + HexString(control_address) + " left=" +
            std::to_string(left) + " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom) + " observedLabel=" + SanitizeDebugLogLabel(label) +
            " cachedLabel=" + SanitizeDebugLogLabel(cached_label) + " caller=" + HexString(caller_address));
    }

    RecordExactControlElement(
        "main_menu",
        "Main Menu",
        control_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveDarkCloudBrowserControlRender(void* control_object, uintptr_t caller_address, std::string label) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr || control_object == nullptr) {
        return;
    }

    uintptr_t browser_address = 0;
    if (!TryGetActiveDarkCloudBrowserRender(&browser_address) || browser_address == 0) {
        return;
    }

    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryReadExactControlRect(*config, control_object, &left, &top, &right, &bottom)) {
        return;
    }

    const auto control_address = reinterpret_cast<uintptr_t>(control_object);
    auto surface_id = std::string("dark_cloud_browser");
    auto surface_title = std::string("Dark Cloud Browser");
    const auto recorded_left = left;
    const auto recorded_top = top;
    const auto recorded_right = right;
    const auto recorded_bottom = bottom;

    static int s_dark_cloud_exact_control_logs_remaining = 24;
    if (s_dark_cloud_exact_control_logs_remaining > 0) {
        --s_dark_cloud_exact_control_logs_remaining;
        const auto relative_offset =
            control_address >= browser_address ? static_cast<std::size_t>(control_address - browser_address) : 0;
        std::string cached_label;
        (void)TryReadCachedObjectLabel(control_address, &cached_label);
        Log(
            "Debug UI Dark Cloud browser exact control capture: browser=" + HexString(browser_address) +
            " control=" + HexString(control_address) + " relative=" + HexString(relative_offset) + " left=" +
            std::to_string(recorded_left) + " top=" + std::to_string(recorded_top) + " right=" +
            std::to_string(recorded_right) + " bottom=" + std::to_string(recorded_bottom) +
            " observedLabel=" + SanitizeDebugLogLabel(label) +
            " cachedLabel=" + SanitizeDebugLogLabel(cached_label) + " caller=" + HexString(caller_address) +
            " surface=" + surface_id);
    }

    RecordExactControlElement(
        surface_id,
        surface_title,
        control_address,
        caller_address,
        recorded_left,
        recorded_top,
        recorded_right,
        recorded_bottom,
        ResolveDarkCloudBrowserControlLabel(
            *config,
            browser_address,
            control_address,
            std::move(label)));
}

void ObserveDarkCloudBrowserPanelRender(
    uintptr_t caller_address,
    float left,
    float top,
    float right,
    float bottom) {
    uintptr_t browser_address = 0;
    if (!TryGetActiveDarkCloudBrowserRender(&browser_address) || browser_address == 0) {
        return;
    }

    RememberDarkCloudBrowserPanelRect(browser_address, left, top, right, bottom);

    RecordExactControlElement(
        "dark_cloud_browser.panel",
        "Dark Cloud Browser",
        browser_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        "BROWSER PANEL");
}

void ObserveDarkCloudBrowserControlLayoutSlot(
    const DebugUiOverlayConfig& config,
    uintptr_t browser_address,
    uintptr_t caller_address,
    std::size_t relative_offset,
    std::string label) {
    if (browser_address == 0 || relative_offset == 0) {
        return;
    }

    const auto control_address = browser_address + relative_offset;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(control_address),
            &left,
            &top,
            &right,
            &bottom)) {
        return;
    }

    RecordExactControlElement(
        "dark_cloud_browser",
        "Dark Cloud Browser",
        control_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveDarkCloudBrowserControlsFromLayout(const DebugUiOverlayConfig& config, uintptr_t browser_address, uintptr_t caller_address) {
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_primary_action_control_offset,
        "PLAY");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_secondary_action_control_offset,
        "SEARCH");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_aux_left_control_offset,
        "SORT");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_aux_right_control_offset,
        "OPTIONS");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_recent_tab_control_offset,
        "RECENT");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_online_levels_tab_control_offset,
        "ONLINE LEVELS");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_my_levels_tab_control_offset,
        "MY LEVELS");
    ObserveDarkCloudBrowserControlLayoutSlot(
        config,
        browser_address,
        caller_address,
        config.dark_cloud_browser_footer_action_control_offset,
        "MENU");
}

void ObserveDarkCloudBrowserRectDispatch(
    void* control_object,
    uintptr_t caller_address,
    float left,
    float top,
    float width,
    float height) {
    if (control_object == nullptr || !IsPlausibleSurfaceWidgetRect(left, top, width, height)) {
        return;
    }

    uintptr_t browser_address = 0;
    if (!TryGetActiveDarkCloudBrowserRender(&browser_address) || browser_address == 0) {
        return;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return;
    }

    const auto control_address = reinterpret_cast<uintptr_t>(control_object);
    auto surface_id = std::string("dark_cloud_browser");
    auto surface_title = std::string("Dark Cloud Browser");
    const auto recorded_left = left;
    const auto recorded_top = top;
    const auto recorded_right = left + width;
    const auto recorded_bottom = top + height;

    static int s_dark_cloud_browser_rect_dispatch_logs_remaining = 24;
    if (s_dark_cloud_browser_rect_dispatch_logs_remaining > 0) {
        --s_dark_cloud_browser_rect_dispatch_logs_remaining;
        Log(
            "Debug UI Dark Cloud browser exact rect dispatch: browser=" + HexString(browser_address) +
            " object=" + HexString(control_address) +
            " caller=" + HexString(caller_address) + " left=" + std::to_string(recorded_left) +
            " top=" + std::to_string(recorded_top) + " right=" + std::to_string(recorded_right) +
            " bottom=" + std::to_string(recorded_bottom) + " surface=" + surface_id);
    }

    RecordExactControlElement(
        surface_id,
        surface_title,
        control_address,
        caller_address,
        recorded_left,
        recorded_top,
        recorded_right,
        recorded_bottom,
        {});
}

void ObserveSettingsControlRender(void* control_object, uintptr_t caller_address, std::string label) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr || control_object == nullptr) {
        return;
    }

    uintptr_t settings_address = 0;
    if (!TryGetActiveSettingsRender(&settings_address) || settings_address == 0) {
        return;
    }

    uintptr_t control_address = 0;
    if (!TryResolveSettingsOwnedObject(
            *config,
            settings_address,
            reinterpret_cast<uintptr_t>(control_object),
            &control_address) ||
        control_address == 0) {
        return;
    }

    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryReadResolvedSettingsOwnedRect(
            *config,
            settings_address,
            control_address,
            &left,
            &top,
            &right,
            &bottom)) {
        return;
    }

    static int s_settings_exact_control_logs_remaining = 24;
    if (s_settings_exact_control_logs_remaining > 0) {
        --s_settings_exact_control_logs_remaining;
        std::string stored_label;
        stored_label = ResolveSettingsControlLabel(*config, control_address);

        Log(
            "Debug UI settings exact control capture: settings=" + HexString(settings_address) +
            " control=" + HexString(control_address) + " left=" +
            std::to_string(left) + " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom) + " observedLabel=" + SanitizeDebugLogLabel(label) +
            " storedLabel=" + SanitizeDebugLogLabel(stored_label) + " caller=" + HexString(caller_address));
    }

    RecordExactControlElement(
        "settings",
        "Game Settings",
        control_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveSettingsPanelRender(
    uintptr_t caller_address,
    float left,
    float top,
    float right,
    float bottom) {
    uintptr_t settings_address = 0;
    if (!TryGetActiveSettingsRender(&settings_address) || settings_address == 0) {
        return;
    }

    RecordExactControlElement(
        "settings.panel",
        "Game Settings",
        settings_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        "GAME SETTINGS");
}

void ObserveSettingsRectDispatch(
    void* control_object,
    uintptr_t caller_address,
    float left,
    float top,
    float width,
    float height) {
    if (control_object == nullptr || !IsPlausibleSurfaceWidgetRect(left, top, width, height)) {
        return;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return;
    }

    uintptr_t settings_address = 0;
    if (!TryGetActiveSettingsRender(&settings_address) || settings_address == 0) {
        return;
    }

    uintptr_t control_address = 0;
    if (!TryResolveSettingsOwnedObject(
            *config,
            settings_address,
            reinterpret_cast<uintptr_t>(control_object),
            &control_address) ||
        control_address == 0) {
        return;
    }

    auto recorded_left = left;
    auto recorded_top = top;
    auto recorded_right = left + width;
    auto recorded_bottom = top + height;
    if (IsLocalSubsurfaceRect(left, top, left + width, top + height)) {
        (void)TryTranslateSettingsPanelLocalRect(
            *config,
            settings_address,
            &recorded_left,
            &recorded_top,
            &recorded_right,
            &recorded_bottom);
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSettingsPanelRect(*config, settings_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return;
    }

    const auto center_x = (recorded_left + recorded_right) * 0.5f;
    const auto center_y = (recorded_top + recorded_bottom) * 0.5f;
    if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom)) {
        return;
    }

    std::string label;
    if (control_address == settings_address + config->settings_done_button_control_offset) {
        label = "DONE";
    } else {
        label = ResolveSettingsControlLabel(*config, control_address);
    }
    if (label.empty()) {
        (void)TryReadCachedObjectLabel(control_address, &label);
    }

    static int s_settings_rect_dispatch_logs_remaining = 32;
    if (s_settings_rect_dispatch_logs_remaining > 0) {
        --s_settings_rect_dispatch_logs_remaining;
        Log(
            "Debug UI settings exact rect dispatch: settings=" + HexString(settings_address) +
            " object=" + HexString(control_address) + " caller=" + HexString(caller_address) +
            " left=" + std::to_string(recorded_left) + " top=" + std::to_string(recorded_top) +
            " right=" + std::to_string(recorded_right) + " bottom=" +
            std::to_string(recorded_bottom) + " label=" + SanitizeDebugLogLabel(label));
    }

    RecordExactControlElement(
        "settings",
        "Game Settings",
        control_address,
        caller_address,
        recorded_left,
        recorded_top,
        recorded_right,
        recorded_bottom,
        std::move(label));
}

void ObserveSimpleMenuControlRender(void* control_object, uintptr_t caller_address, std::string label) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr || control_object == nullptr) {
        return;
    }

    uintptr_t simple_menu_address = 0;
    if (!TryGetActiveSimpleMenu(&simple_menu_address) || simple_menu_address == 0) {
        return;
    }

    uintptr_t control_address = 0;
    if (!TryResolveSimpleMenuOwnedObject(
            *config,
            simple_menu_address,
            reinterpret_cast<uintptr_t>(control_object),
            &control_address) ||
        control_address == 0) {
        return;
    }

    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryReadEmbeddedWidgetRect(
            control_object,
            0,
            config->simple_menu_control_left_offset,
            config->simple_menu_control_top_offset,
            config->simple_menu_control_width_offset,
            config->simple_menu_control_height_offset,
            &left,
            &top,
            &right,
            &bottom)) {
        return;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSimpleMenuPanelRect(*config, simple_menu_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return;
    }

    const auto center_x = (left + right) * 0.5f;
    const auto center_y = (top + bottom) * 0.5f;
    if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom)) {
        return;
    }

    std::string cached_label;
    (void)TryReadCachedObjectLabel(control_address, &cached_label);
    if (label.empty()) {
        label = cached_label;
    }

    static int s_simple_menu_exact_control_logs_remaining = 24;
    if (s_simple_menu_exact_control_logs_remaining > 0) {
        --s_simple_menu_exact_control_logs_remaining;
        Log(
            "Debug UI SimpleMenu exact control capture: menu=" + HexString(simple_menu_address) +
            " control=" + HexString(control_address) + " left=" + std::to_string(left) +
            " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom) + " label=" + SanitizeDebugLogLabel(label) +
            " caller=" + HexString(caller_address));
    }

    RecordExactControlElement(
        "simple_menu",
        "Simple Menu",
        control_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveSimpleMenuRectDispatch(
    void* control_object,
    uintptr_t caller_address,
    float left,
    float top,
    float width,
    float height) {
    if (control_object == nullptr || !IsPlausibleSurfaceWidgetRect(left, top, width, height)) {
        return;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return;
    }

    uintptr_t simple_menu_address = 0;
    if (!TryGetActiveSimpleMenu(&simple_menu_address) || simple_menu_address == 0) {
        return;
    }

    uintptr_t control_address = 0;
    if (!TryResolveSimpleMenuOwnedObject(
            *config,
            simple_menu_address,
            reinterpret_cast<uintptr_t>(control_object),
            &control_address) ||
        control_address == 0) {
        return;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSimpleMenuPanelRect(*config, simple_menu_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return;
    }

    const auto right = left + width;
    const auto bottom = top + height;
    const auto center_x = (left + right) * 0.5f;
    const auto center_y = (top + bottom) * 0.5f;
    if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom)) {
        return;
    }

    std::string label;
    (void)TryReadCachedObjectLabel(control_address, &label);

    static int s_simple_menu_rect_dispatch_logs_remaining = 24;
    if (s_simple_menu_rect_dispatch_logs_remaining > 0) {
        --s_simple_menu_rect_dispatch_logs_remaining;
        Log(
            "Debug UI SimpleMenu exact rect dispatch: menu=" + HexString(simple_menu_address) +
            " object=" + HexString(control_address) + " caller=" + HexString(caller_address) +
            " left=" + std::to_string(left) + " top=" + std::to_string(top) +
            " right=" + std::to_string(right) + " bottom=" + std::to_string(bottom) +
            " label=" + SanitizeDebugLogLabel(label));
    }

    RecordExactControlElement(
        "simple_menu",
        "Simple Menu",
        control_address,
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveQuickPanelControlRender(void* control_object, uintptr_t caller_address, std::string label) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr || control_object == nullptr) {
        return;
    }

    uintptr_t quick_panel_address = 0;
    if (!TryReadTrackedMyQuickPanel(&quick_panel_address) || quick_panel_address == 0) {
        return;
    }

    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryReadTranslatedQuickPanelWidgetRect(
            *config,
            quick_panel_address,
            reinterpret_cast<uintptr_t>(control_object),
            &left,
            &top,
            &right,
            &bottom)) {
        return;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadQuickPanelPanelRect(*config, quick_panel_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return;
    }

    const auto center_x = (left + right) * 0.5f;
    const auto center_y = (top + bottom) * 0.5f;
    if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom)) {
        return;
    }

    std::string cached_label;
    if (cached_label.empty()) {
        (void)TryReadCachedObjectLabel(reinterpret_cast<uintptr_t>(control_object), &cached_label);
    }
    if (label.empty()) {
        label = cached_label;
    }

    static int s_quick_panel_exact_control_logs_remaining = 24;
    if (s_quick_panel_exact_control_logs_remaining > 0) {
        --s_quick_panel_exact_control_logs_remaining;
        Log(
            "Debug UI MyQuickCPanel exact control capture: panel=" + HexString(quick_panel_address) +
            " control=" + HexString(reinterpret_cast<uintptr_t>(control_object)) + " left=" +
            std::to_string(left) + " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom) + " label=" + SanitizeDebugLogLabel(label) +
            " caller=" + HexString(caller_address));
    }

    RecordExactControlElement(
        "quick_panel",
        "Quick Panel",
        reinterpret_cast<uintptr_t>(control_object),
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveQuickPanelRectDispatch(
    void* control_object,
    uintptr_t caller_address,
    float left,
    float top,
    float width,
    float height) {
    if (control_object == nullptr || !IsPlausibleSurfaceWidgetRect(left, top, width, height)) {
        return;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return;
    }

    uintptr_t quick_panel_address = 0;
    if (!TryReadTrackedMyQuickPanel(&quick_panel_address) || quick_panel_address == 0) {
        return;
    }

    if (reinterpret_cast<uintptr_t>(control_object) == quick_panel_address) {
        return;
    }
    if (!IsQuickPanelOwnedObject(*config, quick_panel_address, reinterpret_cast<uintptr_t>(control_object))) {
        return;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadQuickPanelPanelRect(*config, quick_panel_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return;
    }

    const auto right = left + width;
    const auto bottom = top + height;
    const auto center_x = (left + right) * 0.5f;
    const auto center_y = (top + bottom) * 0.5f;
    if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, panel_bottom)) {
        return;
    }

    std::string label;
    (void)TryReadCachedObjectLabel(reinterpret_cast<uintptr_t>(control_object), &label);

    static int s_quick_panel_rect_dispatch_logs_remaining = 24;
    if (s_quick_panel_rect_dispatch_logs_remaining > 0) {
        --s_quick_panel_rect_dispatch_logs_remaining;
        Log(
            "Debug UI MyQuickCPanel exact rect dispatch: panel=" + HexString(quick_panel_address) +
            " object=" + HexString(reinterpret_cast<uintptr_t>(control_object)) +
            " caller=" + HexString(caller_address) + " left=" + std::to_string(left) +
            " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom) + " label=" + SanitizeDebugLogLabel(label));
    }

    RecordExactControlElement(
        "quick_panel",
        "Quick Panel",
        reinterpret_cast<uintptr_t>(control_object),
        caller_address,
        left,
        top,
        right,
        bottom,
        std::move(label));
}

void ObserveControlRenderForAllSurfaces(void* control_object, uintptr_t caller_address, std::string label) {
    ObserveMainMenuControlRender(control_object, caller_address, label);
    ObserveDarkCloudBrowserControlRender(control_object, caller_address, label);
    ObserveSettingsControlRender(control_object, caller_address, label);
    ObserveSimpleMenuControlRender(control_object, caller_address, label);
    ObserveQuickPanelControlRender(control_object, caller_address, std::move(label));
}
