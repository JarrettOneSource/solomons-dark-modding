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
        return {"LAST GAME", "NEW GAME", "HALL OF FAME", "BACK"};
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
