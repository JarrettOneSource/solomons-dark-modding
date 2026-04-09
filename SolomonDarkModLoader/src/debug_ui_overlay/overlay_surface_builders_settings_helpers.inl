std::string ResolveBestSettingsControlLabel(
    const DebugUiOverlayConfig& config,
    uintptr_t control_pointer,
    float left,
    float top,
    float right,
    float bottom,
    const std::vector<ObservedUiElement>& exact_text_elements);

std::string ResolveSettingsSurfaceTitle(
    const DebugUiOverlayConfig& config,
    float panel_left,
    float panel_top,
    float panel_right,
    float panel_bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    const auto title_band_bottom = panel_top + (panel_bottom - panel_top) * 0.35f;

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "settings" || element.label.empty()) {
            continue;
        }

        const auto center_x = (element.min_x + element.max_x) * 0.5f;
        const auto center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, title_band_bottom)) {
            continue;
        }

        const auto normalized_caller = NormalizeObservedCodeAddress(element.caller_address);
        auto score = static_cast<float>(element.sample_count) * 32.0f - center_y;
        if (IsTrustedSettingsPanelTitleCaller(config, normalized_caller)) {
            score += 4096.0f;
        } else if (IsTrustedSettingsSectionHeaderCaller(config, normalized_caller)) {
            score += 256.0f;
        }

        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        return best_match->label;
    }

    return "GAME SETTINGS";
}

std::string ResolveSettingsProbeLabel(
    const DebugUiOverlayConfig& config,
    float left,
    float top,
    float right,
    float bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::string label;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& text_element : exact_text_elements) {
        if (text_element.surface_id != "settings" || text_element.label.empty()) {
            continue;
        }

        const auto normalized_caller = NormalizeObservedCodeAddress(text_element.caller_address);
        if (!IsTrustedSettingsTextCaller(config, normalized_caller)) {
            continue;
        }

        const auto overlap_x =
            (std::max)(0.0f, (std::min)(right, text_element.max_x) - (std::max)(left, text_element.min_x));
        const auto overlap_y =
            (std::max)(0.0f, (std::min)(bottom, text_element.max_y) - (std::max)(top, text_element.min_y));
        if (overlap_x <= 0.0f || overlap_y <= 0.0f) {
            continue;
        }

        const auto score = overlap_x * overlap_y + static_cast<float>(text_element.sample_count) * 8.0f;
        if (score > best_score) {
            best_score = score;
            label = text_element.label;
        }
    }

    return label;
}

void LogSettingsEmbeddedControlProbe(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    float panel_left,
    float panel_top,
    float panel_right,
    float panel_bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    static std::set<uintptr_t> s_logged_settings_addresses;
    if (settings_address == 0 || s_logged_settings_addresses.find(settings_address) != s_logged_settings_addresses.end()) {
        return;
    }

    s_logged_settings_addresses.insert(settings_address);
    const auto configured_image_base = GetConfiguredImageBase();
    constexpr uintptr_t kMaximumNormalizedImageSpan = 0x01000000;

    struct CandidateControl {
        std::size_t offset = 0;
        uintptr_t address = 0;
        uintptr_t vftable = 0;
        uintptr_t normalized_vftable = 0;
        float left = 0.0f;
        float top = 0.0f;
        float right = 0.0f;
        float bottom = 0.0f;
        std::string label;
    };

    std::vector<CandidateControl> candidates;
    candidates.reserve(64);

    for (std::size_t offset = 0; offset <= 0x2000; offset += sizeof(std::uint32_t)) {
        const auto candidate_address = settings_address + offset;

        float left = 0.0f;
        float top = 0.0f;
        float right = 0.0f;
        float bottom = 0.0f;
        if (!TryReadExactControlRect(config, reinterpret_cast<const void*>(candidate_address), &left, &top, &right, &bottom)) {
            continue;
        }

        if (IsLocalSubsurfaceRect(left, top, right, bottom)) {
            if (!TryTranslateSettingsPanelLocalRect(config, settings_address, &left, &top, &right, &bottom)) {
                continue;
            }
        }

        if (!IsPlausibleSurfaceWidgetRect(left, top, right - left, bottom - top)) {
            continue;
        }

        const auto overlap_x =
            (std::max)(0.0f, (std::min)(right, panel_right) - (std::max)(left, panel_left));
        const auto overlap_y =
            (std::max)(0.0f, (std::min)(bottom, panel_bottom) - (std::max)(top, panel_top));
        if (overlap_x <= 0.0f || overlap_y <= 0.0f) {
            continue;
        }

        uintptr_t vftable = 0;
        if (!TryReadPointerValueDirect(candidate_address, &vftable) || vftable == 0) {
            continue;
        }

        const auto normalized_vftable = NormalizeObservedCodeAddress(vftable);
        if (configured_image_base == 0 ||
            normalized_vftable < configured_image_base ||
            normalized_vftable > configured_image_base + kMaximumNormalizedImageSpan) {
            continue;
        }

        const auto duplicate = std::find_if(
            candidates.begin(),
            candidates.end(),
            [&](const CandidateControl& candidate) {
                return candidate.vftable == vftable &&
                       std::fabs(candidate.left - left) <= 1.0f &&
                       std::fabs(candidate.top - top) <= 1.0f &&
                       std::fabs(candidate.right - right) <= 1.0f &&
                       std::fabs(candidate.bottom - bottom) <= 1.0f;
            });
        if (duplicate != candidates.end()) {
            continue;
        }

        CandidateControl candidate;
        candidate.offset = offset;
        candidate.address = candidate_address;
        candidate.vftable = vftable;
        candidate.normalized_vftable = normalized_vftable;
        candidate.left = left;
        candidate.top = top;
        candidate.right = right;
        candidate.bottom = bottom;
        candidate.label = ResolveSettingsProbeLabel(config, left, top, right, bottom, exact_text_elements);
        candidates.push_back(std::move(candidate));
    }

    std::sort(
        candidates.begin(),
        candidates.end(),
        [](const CandidateControl& left, const CandidateControl& right) {
            if (std::fabs(left.top - right.top) > 1.0f) {
                return left.top < right.top;
            }
            if (std::fabs(left.left - right.left) > 1.0f) {
                return left.left < right.left;
            }
            return left.offset < right.offset;
        });

    constexpr std::size_t kMaxLoggedCandidates = 24;
    Log(
        "Debug UI settings embedded control probe: settings=" + HexString(settings_address) +
        " candidate_count=" + std::to_string(candidates.size()));
    for (std::size_t index = 0; index < candidates.size() && index < kMaxLoggedCandidates; ++index) {
        const auto& candidate = candidates[index];
        Log(
            "Debug UI settings embedded control candidate: settings=" + HexString(settings_address) +
            " offset=" + HexString(candidate.offset) +
            " control=" + HexString(candidate.address) +
            " vftable=" + HexString(candidate.vftable) +
            " normalized_vftable=" + HexString(candidate.normalized_vftable) +
            " left=" + std::to_string(candidate.left) +
            " top=" + std::to_string(candidate.top) +
            " right=" + std::to_string(candidate.right) +
            " bottom=" + std::to_string(candidate.bottom) +
            " label=" + SanitizeDebugLogLabel(candidate.label));
    }
}

const ObservedUiElement* FindBestSettingsExactControlForText(
    const DebugUiOverlayConfig& config,
    const ObservedUiElement& text_element,
    const std::vector<ObservedUiElement>& exact_control_elements,
    const std::map<uintptr_t, std::string>& mapped_control_labels,
    const std::set<uintptr_t>& consumed_control_addresses) {
    if (text_element.surface_id != "settings" || text_element.object_ptr == 0 || text_element.label.empty()) {
        return nullptr;
    }

    const auto normalized_caller = NormalizeObservedCodeAddress(text_element.caller_address);
    if (!IsTrustedSettingsControlLabelCaller(config, normalized_caller)) {
        return nullptr;
    }

    const auto text_center_x = (text_element.min_x + text_element.max_x) * 0.5f;
    const auto text_center_y = (text_element.min_y + text_element.max_y) * 0.5f;
    const auto text_height = text_element.max_y - text_element.min_y;
    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    for (const auto& exact_control : exact_control_elements) {
        if (exact_control.surface_id != "settings" || exact_control.object_ptr == 0) {
            continue;
        }

        if (consumed_control_addresses.find(exact_control.object_ptr) != consumed_control_addresses.end()) {
            continue;
        }

        const auto label_it = mapped_control_labels.find(exact_control.object_ptr);
        if (label_it != mapped_control_labels.end() && !label_it->second.empty() &&
            NormalizeSemanticUiToken(label_it->second) != NormalizeSemanticUiToken(text_element.label)) {
            continue;
        }

        const auto control_center_x = (exact_control.min_x + exact_control.max_x) * 0.5f;
        const auto control_center_y = (exact_control.min_y + exact_control.max_y) * 0.5f;
        const auto vertical_distance = std::fabs(control_center_y - text_center_y);
        if (vertical_distance > (std::max)(48.0f, text_height * 1.5f)) {
            continue;
        }

        const auto overlap_x =
            (std::max)(0.0f, (std::min)(exact_control.max_x, text_element.max_x) -
                                    (std::max)(exact_control.min_x, text_element.min_x));
        const auto overlap_y =
            (std::max)(0.0f, (std::min)(exact_control.max_y, text_element.max_y) -
                                    (std::max)(exact_control.min_y, text_element.min_y));
        const auto dx = std::fabs(control_center_x - text_center_x);
        auto score = static_cast<float>(exact_control.sample_count) * 16.0f - dx * 0.1f - vertical_distance * 4.0f;
        if (overlap_x > 0.0f && overlap_y > 0.0f) {
            score += 4096.0f;
        }
        if (label_it != mapped_control_labels.end() && !label_it->second.empty()) {
            score += 2048.0f;
        }
        if (best_match == nullptr || score > best_score) {
            best_match = &exact_control;
            best_score = score;
        }
    }

    return best_match;
}

const ObservedUiElement* FindSettingsControlByLabel(
    const ObservedUiElement& text_element,
    const std::vector<ObservedUiElement>& exact_control_elements,
    const std::set<uintptr_t>& consumed_control_addresses) {
    if (text_element.surface_id != "settings" || text_element.label.empty()) {
        return nullptr;
    }

    const auto normalized_label = NormalizeSemanticUiToken(text_element.label);
    if (normalized_label.empty()) {
        return nullptr;
    }

    for (const auto& exact_control : exact_control_elements) {
        if (exact_control.surface_id != "settings" || exact_control.object_ptr == 0) {
            continue;
        }

        if (consumed_control_addresses.find(exact_control.object_ptr) != consumed_control_addresses.end()) {
            continue;
        }

        if (NormalizeSemanticUiToken(exact_control.label) == normalized_label) {
            return &exact_control;
        }
    }

    return nullptr;
}

std::string ResolveSimpleMenuSurfaceTitle(
    float panel_left,
    float panel_top,
    float panel_right,
    float panel_bottom,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    std::vector<TrackedSimpleMenuEntryState> tracked_entries;
    std::string tracked_surface_id;
    std::string tracked_surface_title;
    if (TryReadTrackedSimpleMenuDefinition(&tracked_entries, &tracked_surface_id, &tracked_surface_title) &&
        !tracked_surface_title.empty()) {
        return tracked_surface_title;
    }

    const ObservedUiElement* best_match = nullptr;
    auto best_score = (std::numeric_limits<float>::lowest)();
    const auto title_band_bottom = panel_top + (panel_bottom - panel_top) * 0.35f;

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "simple_menu" || element.label.empty()) {
            continue;
        }

        const auto center_x = (element.min_x + element.max_x) * 0.5f;
        const auto center_y = (element.min_y + element.max_y) * 0.5f;
        if (!PointInsideRect(center_x, center_y, panel_left, panel_top, panel_right, title_band_bottom)) {
            continue;
        }

        const auto width = element.max_x - element.min_x;
        const auto height = element.max_y - element.min_y;
        if (width < 24.0f || height < 6.0f) {
            continue;
        }

        const auto score = static_cast<float>(element.sample_count) * 32.0f + width - center_y;
        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    if (best_match != nullptr) {
        return best_match->label;
    }

    return "Simple Menu";
}

bool TryIsCustomizeKeyboardRolloutExpanded(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t* owner_control_address,
    uintptr_t* rollout_child_control_address,
    std::uint8_t* rollout_child_enabled_byte) {
    if (owner_control_address != nullptr) {
        *owner_control_address = 0;
    }
    if (rollout_child_control_address != nullptr) {
        *rollout_child_control_address = 0;
    }
    if (rollout_child_enabled_byte != nullptr) {
        *rollout_child_enabled_byte = 0xff;
    }
    if (settings_address == 0) {
        return false;
    }

    std::vector<uintptr_t> root_controls;
    if (!TryReadSettingsControlPointers(config, settings_address, &root_controls) || root_controls.empty()) {
        return false;
    }

    uintptr_t owner_context_settings_address = 0;
    (void)TryReadResolvedGamePointer(0x0081C264, &owner_context_settings_address);
    const auto normalized_target_label = NormalizeSemanticUiToken("CUSTOMIZE KEYBOARD");

    for (const auto root_control : root_controls) {
        if (root_control == 0) {
            continue;
        }

        std::string control_label = ResolveSettingsControlLabel(config, root_control);
        if (control_label.empty()) {
            (void)TryReadCachedObjectLabel(root_control, &control_label);
        }
        if (NormalizeSemanticUiToken(control_label) != normalized_target_label) {
            continue;
        }

        std::vector<uintptr_t> child_controls;
        (void)TryReadSettingsControlChildPointers(config, root_control, &child_controls);
        if (child_controls.size() <= 2 || child_controls[2] == 0) {
            return false;
        }

        const auto rollout_child_control = child_controls[2];
        std::uint8_t rollout_child_enabled = 0xff;
        if (!TryReadByteValueDirect(rollout_child_control + 0x35, &rollout_child_enabled)) {
            return false;
        }

        if (owner_control_address != nullptr) {
            *owner_control_address = root_control;
        }
        if (rollout_child_control_address != nullptr) {
            *rollout_child_control_address = rollout_child_control;
        }
        if (rollout_child_enabled_byte != nullptr) {
            *rollout_child_enabled_byte = rollout_child_enabled;
        }

        return owner_context_settings_address == settings_address && rollout_child_enabled == 0;
    }

    return false;
}

