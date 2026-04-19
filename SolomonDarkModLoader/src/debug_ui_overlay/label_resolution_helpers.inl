std::string ResolveBestControlLabelFromTextSurface(
    std::string_view surface_id,
    uintptr_t control_address,
    float left,
    float top,
    float right,
    float bottom,
    std::string fallback_label,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::string cached_label;
    if (TryReadCachedObjectLabel(control_address, &cached_label)) {
        return cached_label;
    }

    const auto control_center_x = (left + right) * 0.5f;
    const auto control_center_y = (top + bottom) * 0.5f;
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& element : exact_text_elements) {
        if (element.surface_id != surface_id || element.label.empty()) {
            continue;
        }

        const auto text_center_x = (element.min_x + element.max_x) * 0.5f;
        const auto text_center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(text_center_x, text_center_y, left, top, right, bottom)) {
            continue;
        }

        const auto dx = std::fabs(text_center_x - control_center_x);
        const auto dy = std::fabs(text_center_y - control_center_y);
        const auto score = static_cast<float>(element.sample_count) * 16.0f - dx - dy;
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        if (control_address != 0) {
            CacheObservedObjectLabel(control_address, best_match->label);
        }
        return best_match->label;
    }

    return TrimAsciiWhitespace(std::move(fallback_label));
}

std::string ResolveBestLabelForObject(
    uintptr_t object_address,
    std::string fallback_label,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::string cached_label;
    if (TryReadCachedObjectLabel(object_address, &cached_label)) {
        return cached_label;
    }

    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& element : exact_text_elements) {
        if (element.object_ptr != object_address || element.label.empty()) {
            continue;
        }

        const auto score =
            static_cast<float>(element.sample_count) * 32.0f + static_cast<float>(element.label.size());
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        if (object_address != 0) {
            CacheObservedObjectLabel(object_address, best_match->label);
        }
        return best_match->label;
    }

    return TrimAsciiWhitespace(std::move(fallback_label));
}

std::string ResolveBestDarkCloudBrowserControlLabel(
    uintptr_t control_address,
    float left,
    float top,
    float right,
    float bottom,
    std::string fallback_label,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    return ResolveBestControlLabelFromTextSurface(
        "dark_cloud_browser",
        control_address,
        left,
        top,
        right,
        bottom,
        std::move(fallback_label),
        exact_text_elements);
}
