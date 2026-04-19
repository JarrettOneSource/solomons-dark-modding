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
