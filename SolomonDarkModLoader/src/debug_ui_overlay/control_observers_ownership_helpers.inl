bool TryReadSimpleMenuControlPointers(
    const DebugUiOverlayConfig& config,
    uintptr_t simple_menu_address,
    std::vector<uintptr_t>* controls) {
    if (simple_menu_address == 0) {
        return false;
    }

    return TryReadPointerListEntries(
        reinterpret_cast<const void*>(simple_menu_address),
        config.simple_menu_control_list_offset,
        config.simple_menu_control_list_count_offset,
        config.simple_menu_control_list_entries_offset,
        16,
        controls);
}

bool IsSimpleMenuOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t simple_menu_address,
    uintptr_t control_address) {
    if (simple_menu_address == 0 || control_address == 0 || control_address == simple_menu_address) {
        return false;
    }

    std::vector<uintptr_t> control_pointers;
    if (!TryReadSimpleMenuControlPointers(config, simple_menu_address, &control_pointers)) {
        return false;
    }

    return std::find(control_pointers.begin(), control_pointers.end(), control_address) != control_pointers.end();
}

bool TryResolveSimpleMenuOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t simple_menu_address,
    uintptr_t candidate_object,
    uintptr_t* owned_object_address) {
    if (owned_object_address == nullptr) {
        return false;
    }

    *owned_object_address = 0;
    if (simple_menu_address == 0 || candidate_object == 0 || candidate_object == simple_menu_address) {
        return false;
    }

    std::vector<uintptr_t> control_pointers;
    if (!TryReadSimpleMenuControlPointers(config, simple_menu_address, &control_pointers)) {
        return false;
    }

    if (std::find(control_pointers.begin(), control_pointers.end(), candidate_object) != control_pointers.end()) {
        *owned_object_address = candidate_object;
        return true;
    }

    for (const auto control_pointer : control_pointers) {
        if (control_pointer == 0) {
            continue;
        }

        if (IsWidgetOwnedByRoot(config, control_pointer, candidate_object)) {
            *owned_object_address = control_pointer;
            return true;
        }
    }

    return false;
}

bool TryReadSettingsControlPointers(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    std::vector<uintptr_t>* controls) {
    if (settings_address == 0) {
        return false;
    }

    return TryReadPointerListEntries(
        reinterpret_cast<const void*>(settings_address),
        0,
        config.settings_control_list_count_offset,
        config.settings_control_list_entries_offset,
        16,
        controls);
}

bool TryReadSettingsActionableControlPointers(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    std::vector<uintptr_t>* controls) {
    if (controls == nullptr) {
        return false;
    }

    controls->clear();

    std::vector<uintptr_t> root_controls;
    if (!TryReadSettingsControlPointers(config, settings_address, &root_controls)) {
        return false;
    }

    auto append_control = [&](uintptr_t control_address) {
        if (control_address == 0) {
            return;
        }

        if (std::find(controls->begin(), controls->end(), control_address) != controls->end()) {
            return;
        }

        controls->push_back(control_address);
    };

    for (const auto root_control : root_controls) {
        append_control(root_control);

        std::vector<uintptr_t> child_controls;
        if (!TryReadSettingsControlChildPointers(config, root_control, &child_controls)) {
            continue;
        }

        for (const auto child_control : child_controls) {
            append_control(child_control);
        }
    }

    return !controls->empty();
}

bool TryResolveSettingsControlChildObject(
    const DebugUiOverlayConfig& config,
    uintptr_t control_address,
    uintptr_t candidate_object,
    uintptr_t* owned_object_address) {
    if (owned_object_address == nullptr) {
        return false;
    }

    *owned_object_address = 0;
    if (control_address == 0 || candidate_object == 0) {
        return false;
    }

    std::vector<uintptr_t> child_controls;
    if (!TryReadSettingsControlChildPointers(config, control_address, &child_controls)) {
        return false;
    }

    for (const auto child_control : child_controls) {
        if (child_control == 0) {
            continue;
        }

        if (candidate_object == child_control || IsWidgetOwnedByRoot(config, child_control, candidate_object)) {
            *owned_object_address = child_control;
            return true;
        }
    }

    return false;
}

bool TryResolveSettingsOwnedObject(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t candidate_object,
    uintptr_t* owned_object_address) {
    if (owned_object_address == nullptr) {
        return false;
    }

    *owned_object_address = 0;
    if (settings_address == 0 || candidate_object == 0 || candidate_object == settings_address) {
        return false;
    }

    std::vector<uintptr_t> control_pointers;
    if (TryReadSettingsControlPointers(config, settings_address, &control_pointers)) {
        if (std::find(control_pointers.begin(), control_pointers.end(), candidate_object) != control_pointers.end()) {
            *owned_object_address = candidate_object;
            return true;
        }

        for (const auto control_pointer : control_pointers) {
            if (control_pointer == 0) {
                continue;
            }

            uintptr_t child_owned_object = 0;
            if (TryResolveSettingsControlChildObject(
                    config,
                    control_pointer,
                    candidate_object,
                    &child_owned_object) &&
                child_owned_object != 0) {
                *owned_object_address = child_owned_object;
                return true;
            }

            if (IsWidgetOwnedByRoot(config, control_pointer, candidate_object)) {
                *owned_object_address = control_pointer;
                return true;
            }
        }
    }

    uintptr_t done_button_address = 0;
    if (TryGetSettingsDoneButtonAddress(config, settings_address, &done_button_address) &&
        done_button_address != 0) {
        if (candidate_object == done_button_address) {
            *owned_object_address = done_button_address;
            return true;
        }

        if (IsWidgetOwnedByRoot(config, done_button_address, candidate_object)) {
            *owned_object_address = done_button_address;
            return true;
        }
    }

    return false;
}

bool TryResolveSettingsActionableControlOwner(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t candidate_object,
    uintptr_t* owner_control_address,
    uintptr_t* child_control_address) {
    if (owner_control_address == nullptr || child_control_address == nullptr) {
        return false;
    }

    *owner_control_address = 0;
    *child_control_address = 0;
    if (settings_address == 0 || candidate_object == 0) {
        return false;
    }

    std::vector<uintptr_t> root_controls;
    if (!TryReadSettingsControlPointers(config, settings_address, &root_controls) || root_controls.empty()) {
        return false;
    }

    for (const auto root_control : root_controls) {
        if (root_control == 0) {
            continue;
        }

        std::vector<uintptr_t> child_controls;
        (void)TryReadSettingsControlChildPointers(config, root_control, &child_controls);

        for (const auto child_control : child_controls) {
            if (child_control == 0) {
                continue;
            }

            if (candidate_object == child_control || IsWidgetOwnedByRoot(config, child_control, candidate_object)) {
                *owner_control_address = root_control;
                *child_control_address = child_control;
                return true;
            }
        }

        if (candidate_object == root_control || IsWidgetOwnedByRoot(config, root_control, candidate_object)) {
            if (IsSettingsRolloutControl(config, root_control)) {
                *owner_control_address = root_control;
                *child_control_address = root_control;
                return true;
            }

            if (child_controls.size() == 1 && child_controls.front() != 0) {
                *owner_control_address = root_control;
                *child_control_address = child_controls.front();
                return true;
            }
        }
    }

    return false;
}

std::size_t CountSettingsChildControlsWithResolvedLabels(
    const DebugUiOverlayConfig& config,
    const std::vector<uintptr_t>& child_controls) {
    std::size_t labeled_child_count = 0;

    for (const auto child_control : child_controls) {
        if (child_control == 0) {
            continue;
        }

        std::string child_label = ResolveSettingsControlLabel(config, child_control);
        if (child_label.empty()) {
            (void)TryReadCachedObjectLabel(child_control, &child_label);
        }

        if (!NormalizeSemanticUiToken(child_label).empty()) {
            ++labeled_child_count;
        }
    }

    return labeled_child_count;
}

bool TryResolveSettingsActionableLabelControl(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    uintptr_t candidate_object,
    std::string_view label,
    uintptr_t* owner_control_address,
    uintptr_t* child_control_address,
    std::size_t* match_count,
    bool* matched_container_only) {
    if (owner_control_address == nullptr || child_control_address == nullptr) {
        return false;
    }

    *owner_control_address = 0;
    *child_control_address = 0;
    if (match_count != nullptr) {
        *match_count = 0;
    }
    if (matched_container_only != nullptr) {
        *matched_container_only = false;
    }

    if (settings_address == 0) {
        return false;
    }

    const auto normalized_label = NormalizeSemanticUiToken(label);
    if (normalized_label.empty()) {
        return false;
    }

    uintptr_t candidate_owner_control = 0;
    uintptr_t candidate_child_control = 0;
    if (candidate_object != 0) {
        (void)TryResolveSettingsActionableControlOwner(
            config,
            settings_address,
            candidate_object,
            &candidate_owner_control,
            &candidate_child_control);
    }

    std::vector<uintptr_t> root_controls;
    if (!TryReadSettingsControlPointers(config, settings_address, &root_controls) || root_controls.empty()) {
        return false;
    }

    std::vector<std::pair<uintptr_t, uintptr_t>> matches;
    matches.reserve(8);
    bool matched_container_without_unique_child = false;

    const auto read_control_label = [&](uintptr_t control_address) {
        std::string resolved_label = ResolveSettingsControlLabel(config, control_address);
        if (resolved_label.empty()) {
            (void)TryReadCachedObjectLabel(control_address, &resolved_label);
        }
        return resolved_label;
    };

    const auto record_match = [&](uintptr_t owner_address, uintptr_t control_address) {
        if (owner_address == 0 || control_address == 0) {
            return;
        }

        const auto duplicate = std::find(
            matches.begin(),
            matches.end(),
            std::make_pair(owner_address, control_address));
        if (duplicate == matches.end()) {
            matches.emplace_back(owner_address, control_address);
        }
    };

    for (const auto root_control : root_controls) {
        if (root_control == 0) {
            continue;
        }

        std::vector<uintptr_t> child_controls;
        (void)TryReadSettingsControlChildPointers(config, root_control, &child_controls);

        for (const auto child_control : child_controls) {
            if (child_control == 0) {
                continue;
            }

            const auto child_label = read_control_label(child_control);
            if (!child_label.empty() &&
                NormalizeSemanticUiToken(child_label) == normalized_label) {
                record_match(root_control, child_control);
            }
        }

        const auto root_label = read_control_label(root_control);
        if (!root_label.empty() &&
            NormalizeSemanticUiToken(root_label) == normalized_label) {
            if (IsSettingsRolloutControl(config, root_control)) {
                record_match(root_control, root_control);
            } else if (child_controls.size() == 1 && child_controls.front() != 0) {
                record_match(root_control, child_controls.front());
            } else if (CountSettingsChildControlsWithResolvedLabels(config, child_controls) == 0 &&
                       !child_controls.empty() &&
                        child_controls.front() != 0) {
                record_match(root_control, child_controls.front());
            } else {
                matched_container_without_unique_child = true;
            }
        }
    }

    if (match_count != nullptr) {
        *match_count = matches.size();
    }
    if (matched_container_only != nullptr) {
        *matched_container_only = matched_container_without_unique_child;
    }

    if (matches.size() == 1) {
        *owner_control_address = matches.front().first;
        *child_control_address = matches.front().second;
        return true;
    }

    if (candidate_owner_control != 0 && candidate_child_control != 0) {
        const auto candidate_match = std::make_pair(candidate_owner_control, candidate_child_control);
        if (matches.empty()) {
            if (match_count != nullptr) {
                *match_count = 1;
            }
            *owner_control_address = candidate_owner_control;
            *child_control_address = candidate_child_control;
            return true;
        }

        const auto candidate_it = std::find(matches.begin(), matches.end(), candidate_match);
        if (candidate_it != matches.end()) {
            if (match_count != nullptr) {
                *match_count = 1;
            }
            *owner_control_address = candidate_owner_control;
            *child_control_address = candidate_child_control;
            return true;
        }
    }

    return false;
}

