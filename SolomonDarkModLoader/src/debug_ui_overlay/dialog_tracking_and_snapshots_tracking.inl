bool IsDarkCloudSortProbeLabel(std::string_view label) {
    const auto trimmed = TrimAsciiWhitespace(label);
    if (trimmed.empty()) {
        return false;
    }

    return trimmed == "SORT LEVELS BY..." || trimmed == "NEWEST" || trimmed == "OLDEST" ||
           trimmed == "UPDATED RECENTLY" || trimmed == "BEST RATING";
}

bool LooksLikeResourcePathString(std::string_view value) {
    const auto lowered = ToLowerAscii(value);
    if (lowered.find(":\\") != std::string::npos || lowered.find('\\') != std::string::npos ||
        lowered.find('/') != std::string::npos) {
        return true;
    }

    for (const auto extension : {".png", ".jpg", ".jpeg", ".dds", ".wav", ".ogg", ".mp3"}) {
        if (lowered.find(extension) != std::string::npos) {
            return true;
        }
    }

    return false;
}

bool LooksLikeDialogButtonLabel(std::string_view value) {
    if (value.empty() || value.size() > 16) {
        return false;
    }

    int alpha_count = 0;
    int uppercase_alpha_count = 0;
    for (const unsigned char ch : value) {
        if (std::isalpha(ch) != 0) {
            ++alpha_count;
            if (std::isupper(ch) != 0) {
                ++uppercase_alpha_count;
            }
            continue;
        }

        if (std::isdigit(ch) != 0 || std::isspace(ch) != 0 || ch == '-' || ch == '_' || ch == '&') {
            continue;
        }

        return false;
    }

    return alpha_count > 0 && alpha_count == uppercase_alpha_count;
}

bool ShouldKeepTrackedDialogLine(std::string_view value) {
    if (value.empty() || value.size() > 160) {
        return false;
    }

    if (LooksLikeResourcePathString(value) || LooksLikeDialogButtonLabel(value)) {
        return false;
    }

    return IsPlausibleUiLabel(value);
}

void PushRecentAssignedString(std::string value) {
    if (!IsPlausibleUiLabel(value)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& recent = g_debug_ui_overlay_state.recent_assigned_strings;
    if (recent.empty() || recent.back() != value) {
        if (recent.size() >= 24) {
            recent.erase(recent.begin());
        }
        recent.push_back(std::move(value));
    }
    g_debug_ui_overlay_state.recent_assigned_strings_updated_at = GetTickCount64();

    if (!g_debug_ui_overlay_state.first_string_assign_call_logged) {
        g_debug_ui_overlay_state.first_string_assign_call_logged = true;
        Log("Debug UI overlay intercepted its first configured string assignment helper call.");
    }
}

bool TryParseSimpleMenuDefinitionEntry(
    std::string_view token,
    TrackedSimpleMenuEntryState* entry) {
    if (entry == nullptr) {
        return false;
    }

    *entry = TrackedSimpleMenuEntryState{};
    const auto trimmed = TrimAsciiWhitespace(token);
    if (trimmed.empty()) {
        return false;
    }

    const auto bracket_open = trimmed.rfind('[');
    const auto bracket_close = trimmed.rfind(']');
    if (bracket_open == std::string::npos || bracket_close != trimmed.size() - 1 || bracket_open >= bracket_close) {
        return false;
    }

    int selection_index = 0;
    for (std::size_t index = bracket_open + 1; index < bracket_close; ++index) {
        const auto ch = static_cast<unsigned char>(trimmed[index]);
        if (std::isdigit(ch) == 0) {
            return false;
        }

        selection_index = selection_index * 10 + static_cast<int>(ch - '0');
    }

    auto label = TrimAsciiWhitespace(trimmed.substr(0, bracket_open));
    if (label.empty()) {
        return false;
    }

    entry->label = std::move(label);
    entry->selection_index = selection_index;
    return true;
}

bool LooksLikeSimpleMenuDefinitionString(std::string_view value) {
    if (value.find('|') == std::string_view::npos) {
        return false;
    }

    std::size_t parsed_entry_count = 0;
    std::size_t token_start = 0;
    while (token_start <= value.size()) {
        const auto separator = value.find('|', token_start);
        const auto token_length =
            separator == std::string_view::npos ? value.size() - token_start : separator - token_start;
        TrackedSimpleMenuEntryState parsed_entry;
        if (TryParseSimpleMenuDefinitionEntry(value.substr(token_start, token_length), &parsed_entry)) {
            ++parsed_entry_count;
        }

        if (separator == std::string_view::npos) {
            break;
        }

        token_start = separator + 1;
    }

    return parsed_entry_count >= 2;
}

std::optional<std::string> FindLatestRecentAssignedSimpleMenuDefinitionUnlocked(ULONGLONG now) {
    constexpr ULONGLONG kRecentSimpleMenuDefinitionMaximumAgeMs = 1000;

    if (g_debug_ui_overlay_state.recent_assigned_strings.empty() ||
        now < g_debug_ui_overlay_state.recent_assigned_strings_updated_at ||
        now - g_debug_ui_overlay_state.recent_assigned_strings_updated_at >
            kRecentSimpleMenuDefinitionMaximumAgeMs) {
        return std::nullopt;
    }

    for (auto it = g_debug_ui_overlay_state.recent_assigned_strings.rbegin();
         it != g_debug_ui_overlay_state.recent_assigned_strings.rend();
         ++it) {
        if (LooksLikeSimpleMenuDefinitionString(*it)) {
            return *it;
        }
    }

    return std::nullopt;
}

bool TryResolveSimpleMenuSemanticSurface(
    std::vector<TrackedSimpleMenuEntryState>* entries,
    std::string* surface_id,
    std::string* surface_title) {
    if (entries == nullptr || surface_id == nullptr || surface_title == nullptr || entries->empty()) {
        return false;
    }

    *surface_id = {};
    *surface_title = {};

    const auto* layout = TryGetBinaryLayout();
    if (layout == nullptr) {
        return false;
    }

    const UiSurfaceDefinition* best_surface = nullptr;
    std::size_t best_match_count = 0;
    std::size_t best_action_count = (std::numeric_limits<std::size_t>::max)();
    for (const auto& candidate_surface : layout->ui_surfaces) {
        std::size_t match_count = 0;
        for (const auto& entry : *entries) {
            if (FindConfiguredUiActionByLabel(candidate_surface.id, entry.label) != nullptr) {
                ++match_count;
            }
        }

        if (match_count == 0) {
            continue;
        }

        const auto complete_match = match_count == entries->size();
        const auto best_complete_match = best_match_count == entries->size();
        const auto action_count = candidate_surface.action_ids.size();
        const auto better_match =
            best_surface == nullptr ||
            (complete_match != best_complete_match && complete_match) ||
            (complete_match == best_complete_match && match_count > best_match_count) ||
            (complete_match == best_complete_match && match_count == best_match_count &&
             action_count < best_action_count);
        if (better_match) {
            best_surface = &candidate_surface;
            best_match_count = match_count;
            best_action_count = action_count;
        }
    }

    if (best_surface == nullptr || best_match_count == 0) {
        return false;
    }

    *surface_id = best_surface->id;
    *surface_title = best_surface->title;
    for (auto& entry : *entries) {
        entry.action_id = ResolveConfiguredUiActionId(best_surface->id, entry.label);
    }
    return true;
}

void CaptureTrackedSimpleMenuDefinitionUnlocked(
    TrackedSimpleMenuState* state,
    std::string definition,
    ULONGLONG now) {
    if (state == nullptr) {
        return;
    }

    std::vector<TrackedSimpleMenuEntryState> parsed_entries;
    std::size_t token_start = 0;
    while (token_start <= definition.size()) {
        const auto separator = definition.find('|', token_start);
        const auto token_length =
            separator == std::string::npos ? definition.size() - token_start : separator - token_start;
        TrackedSimpleMenuEntryState parsed_entry;
        if (TryParseSimpleMenuDefinitionEntry(
                std::string_view(definition).substr(token_start, token_length),
                &parsed_entry)) {
            parsed_entries.push_back(std::move(parsed_entry));
        }

        if (separator == std::string::npos) {
            break;
        }

        token_start = separator + 1;
    }

    if (parsed_entries.size() < 2) {
        return;
    }

    auto semantic_surface_id = std::string{};
    auto semantic_surface_title = std::string{};
    (void)TryResolveSimpleMenuSemanticSurface(&parsed_entries, &semantic_surface_id, &semantic_surface_title);

    state->raw_definition = std::move(definition);
    state->definition_captured_at = now;
    state->entries = std::move(parsed_entries);
    state->semantic_surface_id = std::move(semantic_surface_id);
    state->semantic_surface_title = std::move(semantic_surface_title);

    static int s_simple_menu_definition_logs_remaining = 24;
    if (s_simple_menu_definition_logs_remaining > 0) {
        --s_simple_menu_definition_logs_remaining;
        std::string entry_summary;
        for (std::size_t index = 0; index < state->entries.size(); ++index) {
            if (!entry_summary.empty()) {
                entry_summary += " | ";
            }

            entry_summary += "[" + std::to_string(index) + "] " + SanitizeDebugLogLabel(state->entries[index].label);
            if (!state->entries[index].action_id.empty()) {
                entry_summary += " => " + state->entries[index].action_id;
            }
        }

        Log(
            "Debug UI SimpleMenu definition capture: menu=" + HexString(state->active_object_ptr) +
            " surface=" + (state->semantic_surface_id.empty() ? std::string("simple_menu")
                                                              : state->semantic_surface_id) +
            " raw=" + SanitizeDebugLogLabel(state->raw_definition) + " entries=" + entry_summary);
    }
}

void RefreshTrackedSimpleMenuDefinitionUnlocked(TrackedSimpleMenuState* state, ULONGLONG now) {
    if (state == nullptr) {
        return;
    }

    const auto latest_definition = FindLatestRecentAssignedSimpleMenuDefinitionUnlocked(now);
    if (!latest_definition.has_value()) {
        return;
    }

    if (state->raw_definition == *latest_definition && !state->entries.empty()) {
        state->definition_captured_at = now;
        return;
    }

    CaptureTrackedSimpleMenuDefinitionUnlocked(state, *latest_definition, now);
}

bool TryReadTrackedSimpleMenuDefinition(
    std::vector<TrackedSimpleMenuEntryState>* entries,
    std::string* semantic_surface_id,
    std::string* semantic_surface_title) {
    if (entries == nullptr || semantic_surface_id == nullptr || semantic_surface_title == nullptr) {
        return false;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    const auto& simple_menu = g_debug_ui_overlay_state.simple_menu;
    if (simple_menu.active_object_ptr == 0 || simple_menu.modal_depth == 0 || simple_menu.entries.empty()) {
        return false;
    }

    *entries = simple_menu.entries;
    *semantic_surface_id = simple_menu.semantic_surface_id;
    *semantic_surface_title = simple_menu.semantic_surface_title;
    return true;
}

std::vector<std::string> ConsumeRecentAssignedStringsUnlocked() {
    std::vector<std::string> lines = std::move(g_debug_ui_overlay_state.recent_assigned_strings);
    g_debug_ui_overlay_state.recent_assigned_strings.clear();
    lines.erase(
        std::remove_if(lines.begin(), lines.end(), [](const std::string& value) { return value.empty(); }),
        lines.end());
    if (lines.size() > 12) {
        lines.erase(lines.begin(), lines.end() - 12);
    }
    return lines;
}

std::optional<std::string> PeekRecentAssignedStringUnlocked() {
    auto& recent = g_debug_ui_overlay_state.recent_assigned_strings;
    if (recent.empty()) {
        return std::nullopt;
    }

    return recent.back();
}

void TrackDialogLine(void* dialog_object, uintptr_t caller_address) {
    if (dialog_object == nullptr) {
        return;
    }

    DialogGeometry geometry;
    const auto has_geometry = TryReadMsgBoxGeometry(dialog_object, g_debug_ui_overlay_state.config, &geometry);
    const auto dialog_address = reinterpret_cast<uintptr_t>(dialog_object);
    const auto line_list_address = dialog_address + g_debug_ui_overlay_state.config.msgbox_line_list_offset;
    const auto line_count =
        ProcessMemory::Instance().ReadFieldOr<int>(
            line_list_address,
            g_debug_ui_overlay_state.config.msgbox_line_list_count_offset,
            0);
    const auto line_entries =
        ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
            line_list_address,
            g_debug_ui_overlay_state.config.msgbox_line_list_entries_offset,
            0);

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_dialog = g_debug_ui_overlay_state.tracked_dialog;
    if (tracked_dialog.object_ptr != dialog_address) {
        tracked_dialog = TrackedDialogState{};
        tracked_dialog.object_ptr = dialog_address;
    }

    tracked_dialog.captured_at = GetTickCount64();
    if (has_geometry) {
        MergeTrackedDialogGeometryLocked(&tracked_dialog, geometry);
        if (!g_debug_ui_overlay_state.first_dialog_finalize_logged) {
            g_debug_ui_overlay_state.first_dialog_finalize_logged = true;
            Log(
                "Debug UI overlay captured its first live dialog object. left=" + std::to_string(geometry.left) +
                " top=" + std::to_string(geometry.top) + " width=" +
                std::to_string(geometry.right - geometry.left) + " height=" +
                std::to_string(geometry.bottom - geometry.top));
        }
    }

    const auto recent_line = PeekRecentAssignedStringUnlocked();
    if (!recent_line.has_value() || recent_line->empty()) {
        return;
    }

    const auto line = TrimAsciiWhitespace(*recent_line);
    if (!ShouldKeepTrackedDialogLine(line)) {
        return;
    }

    if (std::find(tracked_dialog.lines.begin(), tracked_dialog.lines.end(), line) == tracked_dialog.lines.end()) {
        tracked_dialog.lines.push_back(line);
    }
    if (tracked_dialog.title.empty() ||
        (!ContainsCaseInsensitive(tracked_dialog.title, "version") && ContainsCaseInsensitive(line, "version"))) {
        tracked_dialog.title = line;
    }

    if (!g_debug_ui_overlay_state.first_dialog_add_line_logged) {
        g_debug_ui_overlay_state.first_dialog_add_line_logged = true;
        Log(
            "Debug UI overlay intercepted its first dialog line builder call. line=" + line +
            " object=" + HexString(dialog_address) + " caller=" + HexString(caller_address) +
            " line_list=" + HexString(line_list_address) + " line_entries=" + HexString(line_entries) +
            " line_count=" + std::to_string(line_count));
    }
}

void TrackDialogButton(void* dialog_object, bool primary_button, uintptr_t caller_address) {
    if (dialog_object == nullptr) {
        return;
    }

    DialogGeometry geometry;
    const auto has_geometry = TryReadMsgBoxGeometry(dialog_object, g_debug_ui_overlay_state.config, &geometry);

    std::string label;
    const auto button_offset = primary_button ? g_debug_ui_overlay_state.config.msgbox_primary_label_offset
                                              : g_debug_ui_overlay_state.config.msgbox_secondary_label_offset;
    if (!TryReadInlineStringObject(dialog_object, button_offset, &label) || label.empty()) {
        return;
    }
    label = TrimAsciiWhitespace(label);
    if (!LooksLikeDialogButtonLabel(label)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_dialog = g_debug_ui_overlay_state.tracked_dialog;
    const auto dialog_address = reinterpret_cast<uintptr_t>(dialog_object);
    if (tracked_dialog.object_ptr != dialog_address) {
        tracked_dialog = TrackedDialogState{};
        tracked_dialog.object_ptr = dialog_address;
    }

    tracked_dialog.captured_at = GetTickCount64();
    if (has_geometry) {
        MergeTrackedDialogGeometryLocked(&tracked_dialog, geometry);
        if (!g_debug_ui_overlay_state.first_dialog_finalize_logged) {
            g_debug_ui_overlay_state.first_dialog_finalize_logged = true;
            Log(
                "Debug UI overlay captured its first live dialog object. left=" + std::to_string(geometry.left) +
                " top=" + std::to_string(geometry.top) + " width=" +
                std::to_string(geometry.right - geometry.left) + " height=" +
                std::to_string(geometry.bottom - geometry.top));
        }
    }
    auto& button_state = primary_button ? tracked_dialog.primary_button : tracked_dialog.secondary_button;
    button_state.label = label;
    if (!has_geometry) {
        button_state.has_bounds = false;
    }

    if (!g_debug_ui_overlay_state.first_dialog_button_logged) {
        g_debug_ui_overlay_state.first_dialog_button_logged = true;
        Log(
            "Debug UI overlay intercepted its first dialog button builder call. label=" + label +
            " object=" + HexString(dialog_address) + " caller=" + HexString(caller_address));
    }
}

void ObserveDialogFinalize(void* object_ptr, uintptr_t caller_address) {
    if (object_ptr == nullptr) {
        return;
    }

    DialogGeometry geometry;
    if (!TryReadMsgBoxGeometry(object_ptr, g_debug_ui_overlay_state.config, &geometry)) {
        return;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& tracked_dialog = g_debug_ui_overlay_state.tracked_dialog;
    const auto dialog_address = reinterpret_cast<uintptr_t>(object_ptr);
    if (tracked_dialog.object_ptr != dialog_address) {
        tracked_dialog = TrackedDialogState{};
        tracked_dialog.object_ptr = dialog_address;
    }

    tracked_dialog.captured_at = GetTickCount64();
    MergeTrackedDialogGeometryLocked(&tracked_dialog, geometry);
    if (tracked_dialog.title.empty()) {
        if (!tracked_dialog.lines.empty()) {
            tracked_dialog.title = tracked_dialog.lines.front();
        } else {
            tracked_dialog.title = "Dialog";
        }
    }
    if (tracked_dialog.primary_button.label.empty()) {
        tracked_dialog.primary_button.label = geometry.primary_button.label.empty() ? std::string("OK")
                                                                                   : geometry.primary_button.label;
    }

    if (!g_debug_ui_overlay_state.first_dialog_finalize_logged) {
        g_debug_ui_overlay_state.first_dialog_finalize_logged = true;
        Log(
            "Debug UI overlay captured its first live dialog object. left=" + std::to_string(geometry.left) +
            " top=" + std::to_string(geometry.top) + " width=" +
            std::to_string(geometry.right - geometry.left) + " height=" +
            std::to_string(geometry.bottom - geometry.top) + " caller=" + HexString(caller_address));
    }
}

