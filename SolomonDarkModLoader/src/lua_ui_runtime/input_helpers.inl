std::vector<std::uint64_t> EnabledButtons(const LuaUiSurfaceState& surface) {
    std::vector<std::uint64_t> handles;
    for (const auto& element : surface.elements) {
        if (element.definition.kind == LuaUiElementKind::Button &&
            element.definition.enabled) {
            handles.push_back(element.handle);
        }
    }
    return handles;
}

void EnsureFocusLocked(LuaUiSurfaceState* surface) {
    if (surface == nullptr) {
        return;
    }
    const auto buttons = EnabledButtons(*surface);
    if (buttons.empty()) {
        surface->focused_button_handle = 0;
        return;
    }
    if (std::find(
            buttons.begin(), buttons.end(), surface->focused_button_handle) ==
        buttons.end()) {
        surface->focused_button_handle = buttons.front();
    }
}

LuaUiSurfaceState* TopVisibleSurfaceLocked() {
    for (auto it = g_lua_ui_runtime.surface_order.rbegin();
         it != g_lua_ui_runtime.surface_order.rend(); ++it) {
        const auto found = g_lua_ui_runtime.surfaces.find(*it);
        if (found != g_lua_ui_runtime.surfaces.end() && found->second.visible) {
            return &found->second;
        }
    }
    return nullptr;
}

LuaUiRect ComposeRect(const LuaUiRect& parent, const LuaUiRect& child) {
    return LuaUiRect{
        parent.x + child.x * parent.width,
        parent.y + child.y * parent.height,
        child.width * parent.width,
        child.height * parent.height,
    };
}

bool ResolveElementRectLocked(
    const LuaUiSurfaceState& surface,
    const LuaUiElementState& element,
    LuaUiRect* rect,
    std::size_t depth = 0) {
    if (rect == nullptr || depth > kLuaUiMaximumPanelsPerSurface + 1) {
        return false;
    }
    LuaUiRect parent_rect = surface.definition.rect;
    if (element.parent_handle != surface.handle) {
        const auto parent = std::find_if(
            surface.elements.begin(), surface.elements.end(),
            [&](const LuaUiElementState& candidate) {
                return candidate.handle == element.parent_handle;
            });
        if (parent == surface.elements.end() ||
            !ResolveElementRectLocked(surface, *parent, &parent_rect, depth + 1)) {
            return false;
        }
    }
    *rect = ComposeRect(parent_rect, element.definition.rect);
    return true;
}

void QueueButtonActionLocked(
    LuaUiSurfaceState* surface,
    LuaUiElementState* button,
    std::uint64_t participant_id,
    std::uint64_t request_id,
    bool routed) {
    if (surface == nullptr || button == nullptr ||
        button->definition.kind != LuaUiElementKind::Button ||
        !button->definition.enabled) {
        return;
    }
    if (request_id == 0) {
        request_id = g_lua_ui_runtime.next_action_request_id++;
    }
    if (g_lua_ui_runtime.pending_actions.size() >= kMaximumPendingActions) {
        g_lua_ui_runtime.pending_actions.pop_front();
    }
    g_lua_ui_runtime.pending_actions.push_back(LuaUiPendingAction{
        surface->mod_id,
        surface->definition.id,
        button->definition.id,
        button->definition.action_class,
        participant_id,
        request_id,
        routed,
    });
    if (button->definition.close_on_activate && !routed) {
        surface->visible = false;
    }
}

void CycleFocusLocked(LuaUiSurfaceState* surface, int direction) {
    if (surface == nullptr) {
        return;
    }
    const auto buttons = EnabledButtons(*surface);
    if (buttons.empty()) {
        surface->focused_button_handle = 0;
        return;
    }
    const auto current = std::find(
        buttons.begin(), buttons.end(), surface->focused_button_handle);
    std::size_t index = current == buttons.end()
        ? 0
        : static_cast<std::size_t>(current - buttons.begin());
    if (direction < 0) {
        index = index == 0 ? buttons.size() - 1 : index - 1;
    } else {
        index = (index + 1) % buttons.size();
    }
    surface->focused_button_handle = buttons[index];
}

bool IsUiKeyboardMessage(UINT message) {
    return message == WM_KEYDOWN || message == WM_KEYUP ||
        message == WM_SYSKEYDOWN || message == WM_SYSKEYUP ||
        message == WM_CHAR || message == WM_SYSCHAR;
}

bool IsUiMouseMessage(UINT message) {
    return message >= WM_MOUSEFIRST && message <= WM_MOUSELAST;
}
