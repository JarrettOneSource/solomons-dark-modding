void ReleaseFontAtlas(FontAtlas* atlas) {
    if (atlas == nullptr) {
        return;
    }

    if (atlas->texture != nullptr) {
        atlas->texture->Release();
        atlas->texture = nullptr;
    }

    atlas->line_height = 16;
    atlas->glyphs = {};
}

std::string NormalizeSemanticUiToken(std::string_view value) {
    std::string normalized;
    normalized.reserve(value.size());

    auto append_space_if_needed = [&normalized]() {
        if (!normalized.empty() && normalized.back() != ' ') {
            normalized.push_back(' ');
        }
    };

    for (const unsigned char ch : value) {
        if (std::isalnum(ch) != 0) {
            normalized.push_back(static_cast<char>(std::tolower(ch)));
            continue;
        }

        if (std::isspace(ch) != 0 || ch == '_' || ch == '-' || ch == '.') {
            append_space_if_needed();
        }
    }

    while (!normalized.empty() && normalized.back() == ' ') {
        normalized.pop_back();
    }

    return normalized;
}

const UiActionDefinition* FindConfiguredUiActionByLabel(std::string_view surface_id, std::string_view label) {
    const auto* layout = TryGetBinaryLayout();
    if (layout == nullptr || surface_id.empty() || label.empty()) {
        return nullptr;
    }

    const auto normalized_surface_id = NormalizeSemanticUiToken(surface_id);
    const auto normalized_label = NormalizeSemanticUiToken(label);
    if (normalized_surface_id.empty() || normalized_label.empty()) {
        return nullptr;
    }

    for (const auto& action : layout->ui_actions) {
        if (NormalizeSemanticUiToken(action.surface_id) != normalized_surface_id) {
            continue;
        }
        if (NormalizeSemanticUiToken(action.label) != normalized_label) {
            continue;
        }

        return &action;
    }

    return nullptr;
}

std::string ResolveConfiguredUiActionId(std::string_view surface_id, std::string_view label) {
    const auto* action = FindConfiguredUiActionByLabel(surface_id, label);
    if (action == nullptr) {
        return {};
    }

    return action->id;
}

uintptr_t GetDefinitionAddress(
    const std::map<std::string, uintptr_t>& addresses,
    std::string_view key) {
    const auto it = addresses.find(std::string(key));
    if (it == addresses.end()) {
        return 0;
    }

    return it->second;
}

bool IsUsableDebugUiSurfaceSnapshot(const DebugUiSurfaceSnapshot& snapshot) {
    if (snapshot.elements.empty()) {
        return false;
    }

    const auto now = GetTickCount64();
    return now >= snapshot.captured_at_milliseconds &&
           now - snapshot.captured_at_milliseconds <= kLatestSurfaceSnapshotMaximumIdleMs;
}

std::string_view ResolveUiActionDispatchTiming(
    std::string_view surface_root_id,
    std::string_view action_id) {
    if (!action_id.empty()) {
        if (const auto* action_definition = FindUiActionDefinition(action_id);
            action_definition != nullptr && !action_definition->dispatch_timing.empty()) {
            return action_definition->dispatch_timing;
        }
    }

    if (!surface_root_id.empty()) {
        if (const auto* surface_definition = FindUiSurfaceDefinition(surface_root_id);
            surface_definition != nullptr && !surface_definition->dispatch_timing.empty()) {
            return surface_definition->dispatch_timing;
        }
    }

    return "overlay_frame";
}

bool ShouldDispatchUiActionViaOverlayFrame(
    std::string_view surface_root_id,
    std::string_view action_id) {
    return ResolveUiActionDispatchTiming(surface_root_id, action_id) == "overlay_frame";
}

struct UiActionDispatchExpectation {
    uintptr_t expected_vftable_address = 0;
    uintptr_t expected_handler_address = 0;
    uintptr_t owner_context_global_address = 0;
    uintptr_t owner_context_source_global_address = 0;
    uintptr_t owner_context_source_alt_global_address_1 = 0;
    uintptr_t owner_context_source_alt_global_address_2 = 0;
    uintptr_t owner_optional_enabled_byte_pointer_offset = 0;
    uintptr_t owner_ready_pointer_offset = 0;
    bool skip_owner_context_global = false;
    bool owner_context_use_callback_owner = false;
    std::string owner_name;
    std::string dispatch_kind = "owner_control";
};

bool TryReadPointerValueDirect(uintptr_t address, uintptr_t* value);
bool TryReadResolvedGamePointer(uintptr_t absolute_address, uintptr_t* value);
bool IsSettingsRolloutControl(const DebugUiOverlayConfig& config, uintptr_t control_address);
bool TryResolveSettingsActionableControlOwner(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t candidate_object,
    uintptr_t* owner_control_address,
    uintptr_t* child_control_address);
bool TryResolveSettingsDispatchControlAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t owner_control_address,
    uintptr_t matched_control_address,
    std::string_view action_id,
    uintptr_t* dispatch_control_address,
    std::string* error_message);
bool TryResolveUiActionControlChildDispatchAddress(
    uintptr_t owner_address,
    std::string_view action_id,
    uintptr_t* control_address,
    std::string* error_message);
bool TryReadUiActionCallbackOwnerAddress(
    uintptr_t owner_control_address,
    std::string_view action_id,
    uintptr_t* callback_owner_address,
    std::string* error_message) {
    if (callback_owner_address == nullptr) {
        return false;
    }

    *callback_owner_address = 0;
    if (owner_control_address == 0) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' requires a live owner control.";
        }
        return false;
    }

    uintptr_t callback_owner = 0;
    if (!TryReadPointerValueDirect(owner_control_address + 0xC4, &callback_owner) || callback_owner == 0) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' could not resolve a callback owner from the live owner control.";
        }
        return false;
    }

    *callback_owner_address = callback_owner;
    return true;
}

bool TryResolveUiActionChildDispatchControlAddress(
    std::string_view surface_root_id,
    uintptr_t resolved_owner_address,
    uintptr_t matched_control_address,
    std::string_view action_id,
    uintptr_t* dispatch_control_address,
    std::string* error_message) {
    if (dispatch_control_address == nullptr) {
        return false;
    }

    *dispatch_control_address = 0;
    const auto* config = TryGetDebugUiOverlayConfig();
    if (surface_root_id == "settings" && config != nullptr) {
        return TryResolveSettingsDispatchControlAddress(
            *config,
            resolved_owner_address,
            matched_control_address,
            action_id,
            dispatch_control_address,
            error_message);
    }

    return TryResolveUiActionControlChildDispatchAddress(
        resolved_owner_address,
        action_id,
        dispatch_control_address,
        error_message);
}

