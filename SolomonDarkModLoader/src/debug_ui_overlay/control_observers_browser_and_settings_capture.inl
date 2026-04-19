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
