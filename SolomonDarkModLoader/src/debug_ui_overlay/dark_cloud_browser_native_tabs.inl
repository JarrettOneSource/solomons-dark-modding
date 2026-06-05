int CaptureDarkCloudBrowserNativeTabSeh(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code) {
    if (exception_code != nullptr && exception_pointers != nullptr && exception_pointers->ExceptionRecord != nullptr) {
        *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool TryResolveDarkCloudBrowserNativeTabTargets(
    const DebugUiOverlayConfig& config,
    uintptr_t* tab_asset_address,
    uintptr_t* text_object_address,
    DarkCloudBrowserTabRenderFn* tab_render,
    DarkCloudBrowserTextRenderFn* text_render,
    UiRenderContextColorFn* color_render,
    StringAssignHelperFn* string_assign) {
    if (tab_asset_address == nullptr || text_object_address == nullptr || tab_render == nullptr ||
        text_render == nullptr || color_render == nullptr || string_assign == nullptr) {
        return false;
    }

    *tab_asset_address = 0;
    *text_object_address = 0;
    *tab_render = nullptr;
    *text_render = nullptr;
    *color_render = nullptr;
    *string_assign = nullptr;

    uintptr_t asset_base = 0;
    uintptr_t text_object_base = 0;
    if (!TryReadResolvedGamePointer(config.dark_cloud_browser_asset_global, &asset_base) || asset_base == 0 ||
        !TryReadResolvedGamePointer(config.dark_cloud_browser_text_object_global, &text_object_base) ||
        text_object_base == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto tab_render_address = memory.ResolveGameAddressOrZero(config.dark_cloud_browser_tab_render_helper);
    const auto text_render_address =
        memory.ResolveGameAddressOrZero(config.dark_cloud_browser_text_render_wrapper_helper);
    const auto color_render_address = memory.ResolveGameAddressOrZero(config.ui_render_context_color_helper);
    auto* string_assign_trampoline =
        GetX86HookTrampoline<StringAssignHelperFn>(g_debug_ui_overlay_state.string_assign_hook);
    if (tab_render_address == 0 || text_render_address == 0 || color_render_address == 0 ||
        string_assign_trampoline == nullptr || config.dark_cloud_browser_tab_asset_offset == 0 ||
        config.dark_cloud_browser_text_object_offset == 0) {
        return false;
    }

    *tab_asset_address = asset_base + config.dark_cloud_browser_tab_asset_offset;
    *text_object_address = text_object_base + config.dark_cloud_browser_text_object_offset;
    *tab_render = reinterpret_cast<DarkCloudBrowserTabRenderFn>(tab_render_address);
    *text_render = reinterpret_cast<DarkCloudBrowserTextRenderFn>(text_render_address);
    *color_render = reinterpret_cast<UiRenderContextColorFn>(color_render_address);
    *string_assign = string_assign_trampoline;
    return true;
}

bool TryBuildDarkCloudBrowserMultiplayerNativeTabRect(
    const DebugUiOverlayConfig& config,
    uintptr_t browser_address,
    float* left,
    float* top,
    float* right,
    float* bottom) {
    if (browser_address == 0 || left == nullptr || top == nullptr || right == nullptr || bottom == nullptr) {
        return false;
    }

    float my_left = 0.0f;
    float my_top = 0.0f;
    float my_right = 0.0f;
    float my_bottom = 0.0f;
    if (!TryReadExactControlRect(
            config,
            reinterpret_cast<const void*>(browser_address + config.dark_cloud_browser_my_levels_tab_control_offset),
            &my_left,
            &my_top,
            &my_right,
            &my_bottom)) {
        return false;
    }

    const auto width = my_right - my_left;
    if (!IsPlausibleSurfaceWidgetRect(my_right, my_top, width, my_bottom - my_top)) {
        return false;
    }

    *left = my_right + kDarkCloudBrowserNativeMultiplayerTabGap;
    *top = my_top;
    *right = *left + width + kDarkCloudBrowserMultiplayerTabHorizontalPadding * 2.0f;
    *bottom = my_bottom;
    return true;
}

bool CallDarkCloudBrowserNativeColorSafe(
    UiRenderContextColorFn color_render,
    void* render_context,
    float red,
    float green,
    float blue,
    float alpha,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (color_render == nullptr || render_context == nullptr) {
        return false;
    }

    __try {
        color_render(render_context, red, green, blue, alpha);
    } __except (CaptureDarkCloudBrowserNativeTabSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
    return true;
}

bool CallDarkCloudBrowserNativeTabBackgroundSafe(
    DarkCloudBrowserTabRenderFn tab_render,
    void* tab_asset,
    float left,
    float top,
    float width,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (tab_render == nullptr || tab_asset == nullptr || width <= 0.0f) {
        return false;
    }

    __try {
        tab_render(tab_asset, left, top, width);
    } __except (CaptureDarkCloudBrowserNativeTabSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
    return true;
}

bool CallDarkCloudBrowserNativeTextSafe(
    StringAssignHelperFn string_assign,
    DarkCloudBrowserTextRenderFn text_render,
    void* text_object,
    const char* label,
    float x,
    float y,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (string_assign == nullptr || text_render == nullptr || text_object == nullptr ||
        label == nullptr || label[0] == '\0') {
        return false;
    }

    NativeUiString native_text{};
    bool assigned = false;
    __try {
        string_assign(&native_text, const_cast<char*>(label));
        assigned = true;
    } __except (CaptureDarkCloudBrowserNativeTabSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }

    bool rendered = false;
    __try {
        text_render(text_object, native_text, x, y);
        rendered = true;
    } __except (CaptureDarkCloudBrowserNativeTabSeh(GetExceptionInformation(), exception_code)) {
        rendered = false;
    }

    if (assigned) {
        DWORD cleanup_exception_code = 0;
        __try {
            string_assign(&native_text, nullptr);
        } __except (CaptureDarkCloudBrowserNativeTabSeh(GetExceptionInformation(), &cleanup_exception_code)) {
            if (exception_code != nullptr && *exception_code == 0) {
                *exception_code = cleanup_exception_code;
            }
            return false;
        }
    }

    return rendered;
}

void DrawNativeDarkCloudBrowserMultiplayerTab(uintptr_t browser_address, uintptr_t caller_address) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr || browser_address == 0) {
        return;
    }

    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    if (!TryBuildDarkCloudBrowserMultiplayerNativeTabRect(*config, browser_address, &left, &top, &right, &bottom)) {
        return;
    }

    uintptr_t render_context_address = 0;
    if (!TryReadUiRenderContext(*config, &render_context_address) || render_context_address == 0) {
        return;
    }

    uintptr_t tab_asset_address = 0;
    uintptr_t text_object_address = 0;
    DarkCloudBrowserTabRenderFn tab_render = nullptr;
    DarkCloudBrowserTextRenderFn text_render = nullptr;
    UiRenderContextColorFn color_render = nullptr;
    StringAssignHelperFn string_assign = nullptr;
    if (!TryResolveDarkCloudBrowserNativeTabTargets(
            *config,
            &tab_asset_address,
            &text_object_address,
            &tab_render,
            &text_render,
            &color_render,
            &string_assign)) {
        static bool s_logged_missing_targets = false;
        if (!s_logged_missing_targets) {
            s_logged_missing_targets = true;
            Log("Debug UI native Dark Cloud multiplayer tab skipped because a native target could not be resolved.");
        }
        return;
    }

    auto* render_context = reinterpret_cast<void*>(render_context_address + kUiRenderContextDrawStateOffset);
    auto* tab_asset = reinterpret_cast<void*>(tab_asset_address);
    auto* text_object = reinterpret_cast<void*>(text_object_address);
    const auto width = right - left;
    DWORD exception_code = 0;

    if (!CallDarkCloudBrowserNativeTabBackgroundSafe(
            tab_render,
            tab_asset,
            left,
            top,
            width,
            &exception_code)) {
        static bool s_logged_tab_failure = false;
        if (!s_logged_tab_failure) {
            s_logged_tab_failure = true;
            Log(
                "Debug UI native Dark Cloud multiplayer tab background failed. exception=" +
                HexString(exception_code));
        }
        return;
    }

    (void)CallDarkCloudBrowserNativeColorSafe(
        color_render,
        render_context,
        kDarkCloudBrowserInactiveTabTextRed,
        kDarkCloudBrowserInactiveTabTextGreen,
        kDarkCloudBrowserInactiveTabTextBlue,
        1.0f,
        &exception_code);
    const auto text_x = left + width * 0.5f;
    const auto text_y = top + kDarkCloudBrowserInactiveTabTextYOffset;
    const auto text_rendered = CallDarkCloudBrowserNativeTextSafe(
        string_assign,
        text_render,
        text_object,
        kDarkCloudBrowserMultiplayerTabLabel.data(),
        text_x,
        text_y,
        &exception_code);
    (void)CallDarkCloudBrowserNativeColorSafe(color_render, render_context, 1.0f, 1.0f, 1.0f, 1.0f, nullptr);

    if (!text_rendered) {
        static bool s_logged_text_failure = false;
        if (!s_logged_text_failure) {
            s_logged_text_failure = true;
            Log(
                "Debug UI native Dark Cloud multiplayer tab text failed. exception=" +
                HexString(exception_code));
        }
        return;
    }

    RecordExactControlElement(
        "dark_cloud_browser",
        "Dark Cloud Browser",
        0,
        caller_address,
        left,
        top,
        right,
        bottom,
        std::string(kDarkCloudBrowserMultiplayerTabLabel));

    static bool s_logged_success = false;
    if (!s_logged_success) {
        s_logged_success = true;
        Log(
            "Debug UI rendered native Dark Cloud multiplayer tab at left=" + std::to_string(left) +
            " top=" + std::to_string(top) + " right=" + std::to_string(right) +
            " bottom=" + std::to_string(bottom));
    }
}
