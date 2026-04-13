bool TryReadByteValueDirect(uintptr_t address, std::uint8_t* value) {
    if (address == 0 || value == nullptr) {
        return false;
    }

    __try {
        *value = *reinterpret_cast<const std::uint8_t*>(address);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryReadUInt32ValueDirect(uintptr_t address, std::uint32_t* value) {
    if (address == 0 || value == nullptr) {
        return false;
    }

    __try {
        *value = *reinterpret_cast<const std::uint32_t*>(address);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

std::string SanitizeSettingsLiveStateLabel(std::string_view value) {
    std::string sanitized(value);
    for (auto& ch : sanitized) {
        if (ch == '\r' || ch == '\n' || ch == '\t') {
            ch = ' ';
        }
    }
    return sanitized;
}

void MaybeLogSettingsControlsLiveState(
    std::string_view reason,
    uintptr_t settings_address,
    uintptr_t owner_control_address,
    uintptr_t child_control_address,
    std::string_view label,
    float left,
    float top,
    float right,
    float bottom) {
    if (owner_control_address == 0 && child_control_address == 0) {
        return;
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    uintptr_t owner_vftable = 0;
    uintptr_t owner_child_list = 0;
    uintptr_t callback_owner = 0;
    uintptr_t callback_owner_vftable = 0;
    uintptr_t callback_owner_action_slot = 0;
    std::uint32_t owner_child_count = 0;
    uintptr_t matched_child_base_address = 0;
    uintptr_t dispatch_control_address = 0;
    std::uint8_t child_enabled = 0xff;
    uintptr_t child_vftable = 0;
    std::string owner_child_states;
    const auto settings_owner_global_address = GetUiSurfaceAddress("settings", "owner_global");
    const auto settings_owner_alt_global_address_1 = GetUiSurfaceAddress("settings", "owner_alt_global_1");
    const auto settings_owner_alt_global_address_2 = GetUiSurfaceAddress("settings", "owner_alt_global_2");

    if (owner_control_address != 0) {
        (void)TryReadPointerValueDirect(owner_control_address, &owner_vftable);
        if (config != nullptr) {
            (void)TryReadUInt32ValueDirect(
                owner_control_address + config->settings_control_child_count_offset,
                &owner_child_count);
            (void)TryReadPointerValueDirect(
                owner_control_address + config->settings_control_child_list_offset,
                &owner_child_list);
            if (TryReadPointerValueDirect(
                    owner_control_address + config->settings_control_callback_owner_offset,
                    &callback_owner) &&
                callback_owner != 0) {
                (void)TryReadPointerValueDirect(callback_owner, &callback_owner_vftable);
                if (callback_owner_vftable != 0) {
                    (void)TryReadPointerValueDirect(
                        callback_owner_vftable + config->ui_owner_control_action_vtable_byte_offset,
                        &callback_owner_action_slot);
                }
            }
        }

        if (config != nullptr &&
            owner_child_list != 0 &&
            owner_child_count != 0 &&
            config->settings_control_dispatch_offset != 0) {
            const std::uint32_t max_logged_children = (owner_child_count < 8u) ? owner_child_count : 8u;
            owner_child_states.reserve(static_cast<std::size_t>(max_logged_children) * 48u);

            for (std::uint32_t index = 0; index < max_logged_children; ++index) {
                uintptr_t candidate_child = 0;
                const uintptr_t candidate_slot = owner_child_list + (static_cast<uintptr_t>(index) * sizeof(uintptr_t));
                if (!TryReadPointerValueDirect(candidate_slot, &candidate_child) || candidate_child == 0) {
                    continue;
                }

                const uintptr_t candidate_dispatch =
                    candidate_child + config->settings_control_dispatch_offset;
                std::uint8_t candidate_enabled = 0xff;
                (void)TryReadByteValueDirect(
                    candidate_child + config->settings_control_enabled_byte_offset,
                    &candidate_enabled);

                if (!owner_child_states.empty()) {
                    owner_child_states += ";";
                }

                owner_child_states += std::to_string(index) + ":" + HexString(candidate_child) +
                    "[" + std::to_string(candidate_enabled) + "]" +
                    "->" + HexString(candidate_dispatch);

                if (candidate_child == child_control_address) {
                    owner_child_states += "*base";
                    matched_child_base_address = candidate_child;
                    dispatch_control_address = candidate_dispatch;
                } else if (candidate_dispatch == child_control_address) {
                    owner_child_states += "*dispatch";
                    matched_child_base_address = candidate_child;
                    dispatch_control_address = candidate_dispatch;
                }
            }

            if (owner_child_count > max_logged_children) {
                if (!owner_child_states.empty()) {
                    owner_child_states += ";";
                }
                owner_child_states += "...";
            }
        }
    }

    if (matched_child_base_address == 0 && child_control_address != 0) {
        matched_child_base_address = child_control_address;
        dispatch_control_address =
            config != nullptr
                ? child_control_address + config->settings_control_dispatch_offset
                : child_control_address;
    }

    if (matched_child_base_address != 0) {
        (void)TryReadPointerValueDirect(matched_child_base_address, &child_vftable);
        if (config != nullptr) {
            (void)TryReadByteValueDirect(
                matched_child_base_address + config->settings_control_enabled_byte_offset,
                &child_enabled);
        }
    }

    auto format_settings_global_probe = [&](std::string_view field_name, uintptr_t global_address) {
        const auto resolved_global_address =
            ProcessMemory::Instance().ResolveGameAddressOrZero(global_address);
        uintptr_t global_value = 0;
        const auto has_global_value =
            resolved_global_address != 0 &&
            TryReadPointerValueDirect(resolved_global_address, &global_value);
        std::string probe =
            std::string(field_name) +
            "{abs=" + HexString(global_address) +
            " resolved=" + HexString(resolved_global_address) +
            " value=" + (has_global_value ? HexString(global_value) : std::string("unreadable"));
        probe += "}";
        return probe;
    };

    std::string message =
        "Debug UI settings.controls live state: reason=" + std::string(reason) +
        " settings=" + HexString(settings_address) +
        " " + format_settings_global_probe("owner_global", settings_owner_global_address) +
        " " + format_settings_global_probe("owner_alt_global_1", settings_owner_alt_global_address_1) +
        " " + format_settings_global_probe("owner_alt_global_2", settings_owner_alt_global_address_2) +
        " owner=" + HexString(owner_control_address) +
        " owner_vftable=" + HexString(owner_vftable) +
        " owner_child_count=" + std::to_string(owner_child_count) +
        " owner_child_list=" + HexString(owner_child_list) +
        " callback_owner=" + HexString(callback_owner) +
        " callback_owner_vftable=" + HexString(callback_owner_vftable) +
        " callback_owner_action_slot=" + HexString(callback_owner_action_slot) +
        " child_input=" + HexString(child_control_address) +
        " child=" + HexString(matched_child_base_address) +
        " child_vftable=" + HexString(child_vftable) +
        " child_enabled=" + std::to_string(child_enabled) +
        " dispatch_control=" + HexString(dispatch_control_address) +
        " owner_children=" + owner_child_states +
        " label=" + SanitizeSettingsLiveStateLabel(label) +
        " rect=(" + std::to_string(left) + "," + std::to_string(top) + "," +
        std::to_string(right) + "," + std::to_string(bottom) + ")";

    static std::string s_last_message;
    static int s_repeat_count = 0;
    if (message == s_last_message) {
        ++s_repeat_count;
        if ((s_repeat_count % 24) != 0) {
            return;
        }

        Log(message + " repeat=" + std::to_string(s_repeat_count + 1));
        return;
    }

    s_last_message = message;
    s_repeat_count = 0;
    Log(message);
}

const UiActionDefinition* TryGetResolvedUiActionDefinition(
    std::string_view surface_root_id,
    std::string_view action_id,
    const UiSurfaceDefinition** surface_definition) {
    if (surface_definition != nullptr) {
        *surface_definition = nullptr;
    }

    const UiActionDefinition* action_definition = nullptr;
    if (!action_id.empty()) {
        action_definition = FindUiActionDefinition(action_id);
    }

    const UiSurfaceDefinition* resolved_surface_definition = nullptr;
    if (action_definition != nullptr && !action_definition->surface_id.empty()) {
        resolved_surface_definition = FindUiSurfaceDefinition(action_definition->surface_id);
    }
    if (resolved_surface_definition == nullptr && !surface_root_id.empty()) {
        resolved_surface_definition = FindUiSurfaceDefinition(surface_root_id);
    }

    if (surface_definition != nullptr) {
        *surface_definition = resolved_surface_definition;
    }
    return action_definition;
}

bool CollectUiActionOwnerCandidateAddresses(
    std::string_view,
    const UiActionDefinition* action_definition,
    const UiSurfaceDefinition* surface_definition,
    uintptr_t fallback_owner_address,
    uintptr_t live_control_address,
    std::vector<std::pair<std::string, uintptr_t>>* candidates) {
    if (candidates == nullptr) {
        return false;
    }

    candidates->clear();
    auto append_candidate = [&](std::string source, uintptr_t address) {
        if (address == 0) {
            return;
        }
        const auto duplicate = std::find_if(
            candidates->begin(),
            candidates->end(),
            [&](const auto& candidate) { return candidate.second == address; });
        if (duplicate != candidates->end()) {
            if (!source.empty() && duplicate->first.find(source) == std::string::npos) {
                duplicate->first += "|" + source;
            }
            return;
        }
        candidates->emplace_back(std::move(source), address);
    };

    if (action_definition != nullptr) {
        const auto owner_offset = GetDefinitionAddress(action_definition->addresses, "owner_offset");
        if (owner_offset != 0 && fallback_owner_address != 0) {
            append_candidate("snapshot_plus_owner_offset", fallback_owner_address + owner_offset);
        }
    }

    // `owner_context_global` is dispatch-time ambient state, not an owner-object source.
    struct OwnerGlobalCandidateKey {
        std::string_view pointer_key;
        std::string_view object_key;
    };
    constexpr OwnerGlobalCandidateKey kOwnerGlobalKeys[] = {
        {"owner_global", "owner_global_object"},
        {"owner_alt_global_1", "owner_alt_global_1_object"},
        {"owner_alt_global_2", "owner_alt_global_2_object"},
    };

    for (const auto& key : kOwnerGlobalKeys) {
        uintptr_t pointer_game_address = 0;
        if (action_definition != nullptr) {
            pointer_game_address = GetDefinitionAddress(action_definition->addresses, key.pointer_key);
        }
        if (pointer_game_address == 0 && surface_definition != nullptr) {
            pointer_game_address = GetDefinitionAddress(surface_definition->addresses, key.pointer_key);
        }
        if (pointer_game_address != 0) {
            uintptr_t candidate_address = 0;
            if (TryReadResolvedGamePointer(pointer_game_address, &candidate_address) && candidate_address != 0) {
                append_candidate(std::string(key.pointer_key), candidate_address);
            }
        }

        uintptr_t object_game_address = 0;
        if (action_definition != nullptr) {
            object_game_address = GetDefinitionAddress(action_definition->addresses, key.object_key);
        }
        if (object_game_address == 0 && surface_definition != nullptr) {
            object_game_address = GetDefinitionAddress(surface_definition->addresses, key.object_key);
        }
        if (object_game_address != 0) {
            const auto candidate_address =
                ProcessMemory::Instance().ResolveGameAddressOrZero(object_game_address);
            if (candidate_address != 0) {
                append_candidate(std::string(key.object_key), candidate_address);
            }
        }
    }

    const bool action_has_explicit_owner =
        action_definition != nullptr && GetDefinitionAddress(action_definition->addresses, "owner") != 0;
    const bool prefer_surface_owner =
        (action_definition != nullptr &&
         (action_definition->dispatch_kind == "owner_noarg" ||
          action_definition->dispatch_kind == "owner_point_click" ||
          action_definition->dispatch_kind == "direct_write")) ||
        action_has_explicit_owner;
    const bool prefer_control_minus_offset =
        action_definition != nullptr &&
        GetDefinitionAddress(action_definition->addresses, "owner_from_control_offset") != 0;
    const bool prefer_live_control_owner =
        action_definition != nullptr &&
        (action_definition->dispatch_kind == "control_child" ||
         action_definition->dispatch_kind == "control_child_callback_owner" ||
         action_definition->dispatch_kind == "control_noarg");

    if (prefer_live_control_owner) {
        if (surface_definition != nullptr && surface_definition->id == "settings" && live_control_address != 0) {
            const auto* config = TryGetDebugUiOverlayConfig();
            uintptr_t settings_address = fallback_owner_address;
            if (settings_address == 0) {
                (void)TryGetActiveSettingsRender(&settings_address);
            }

            uintptr_t settings_owner_control = 0;
            uintptr_t settings_child_control = 0;
            if (config != nullptr &&
                TryResolveSettingsActionableControlOwner(
                    *config,
                    settings_address,
                    live_control_address,
                    &settings_owner_control,
                    &settings_child_control) &&
                settings_owner_control != 0) {
                append_candidate("settings_control_owner", settings_owner_control);
            }
        }

        append_candidate("control", live_control_address);
        return !candidates->empty();
    }

    if (action_definition != nullptr && live_control_address != 0 &&
        (prefer_control_minus_offset || !prefer_surface_owner)) {
        const auto control_offset = GetDefinitionAddress(action_definition->addresses, "control_offset");
        if (control_offset != 0 && live_control_address > control_offset) {
            const auto derived_owner_address = live_control_address - control_offset;
            append_candidate("control_minus_offset", derived_owner_address);
        }
    }

    if (prefer_surface_owner) {
        append_candidate("snapshot", fallback_owner_address);
    }

    if (!prefer_surface_owner) {
        append_candidate("snapshot", fallback_owner_address);
    }

    return !candidates->empty();
}

bool IsUiActionOwnerCandidateSane(
    uintptr_t owner_address,
    const UiActionDefinition* action_definition,
    std::string* rejection_reason) {
    auto set_rejection_reason = [&](std::string reason) {
        if (rejection_reason != nullptr) {
            *rejection_reason = std::move(reason);
        }
    };

    if (owner_address == 0) {
        set_rejection_reason("owner_is_null");
        return false;
    }

    if (action_definition == nullptr) {
        return true;
    }

    const auto owner_required_pointer_offset =
        GetDefinitionAddress(action_definition->addresses, "owner_required_pointer_offset");
    if (owner_required_pointer_offset != 0) {
        uintptr_t required_pointer = 0;
        if (!TryReadPointerValueDirect(owner_address + owner_required_pointer_offset, &required_pointer)) {
            set_rejection_reason(
                "owner_required_pointer_unreadable@" + HexString(owner_required_pointer_offset));
            return false;
        }
        if (required_pointer == 0) {
            set_rejection_reason("owner_required_pointer_null@" + HexString(owner_required_pointer_offset));
            return false;
        }
    }

    const auto control_offset = GetDefinitionAddress(action_definition->addresses, "control_offset");
    const auto validation_pointer_offset =
        GetDefinitionAddress(action_definition->addresses, "control_validation_pointer_offset");
    if (control_offset == 0 || validation_pointer_offset == 0) {
        return true;
    }

    uintptr_t validation_pointer = 0;
    if (!TryReadPointerValueDirect(owner_address + control_offset + validation_pointer_offset, &validation_pointer)) {
        set_rejection_reason(
            "control_validation_pointer_unreadable@" +
            HexString(control_offset + validation_pointer_offset));
        return false;
    }

    if (validation_pointer == 0) {
        return true;
    }

    std::uint8_t ignored = 0;
    if (!TryReadByteValueDirect(validation_pointer, &ignored)) {
        set_rejection_reason("control_validation_target_unreadable@" + HexString(validation_pointer));
        return false;
    }

    return true;
}

bool TryResolvePreferredUiActionOwnerAddress(
    std::string_view surface_root_id,
    uintptr_t fallback_owner_address,
    uintptr_t live_control_address,
    std::string_view action_id,
    uintptr_t* owner_address,
    std::string* error_message) {
    if (owner_address == nullptr) {
        return false;
    }

    *owner_address = 0;
    const UiSurfaceDefinition* surface_definition = nullptr;
    const auto* action_definition =
        TryGetResolvedUiActionDefinition(surface_root_id, action_id, &surface_definition);

    std::vector<std::pair<std::string, uintptr_t>> candidates;
    if (!CollectUiActionOwnerCandidateAddresses(
            surface_root_id,
            action_definition,
            surface_definition,
            fallback_owner_address,
            live_control_address,
            &candidates)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve any candidate owner object for UI action '" +
                             std::string(action_id) + "'.";
        }
        return false;
    }

    if (surface_root_id == "settings" && action_id == "settings.controls") {
        static int s_settings_controls_owner_probe_logs_remaining = 8;
        if (s_settings_controls_owner_probe_logs_remaining > 0) {
            --s_settings_controls_owner_probe_logs_remaining;
            std::string probe_log = "Debug UI settings.controls owner candidate probe:";

            const auto owner_global_address =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_global")
                    : 0;
            const auto owner_global_object_address =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_global_object")
                    : 0;
            const auto surface_owner_global_address =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_global")
                    : 0;
            const auto surface_owner_global_object_address =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_global_object")
                    : 0;
            const auto owner_context_global_address =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_context_global")
                    : 0;
            const auto surface_owner_context_global_address =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_context_global")
                    : 0;
            const auto owner_alt_global_address_1 =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_alt_global_1")
                    : 0;
            const auto owner_alt_global_object_address_1 =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_alt_global_1_object")
                    : 0;
            const auto surface_owner_alt_global_address_1 =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_alt_global_1")
                    : 0;
            const auto surface_owner_alt_global_object_address_1 =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_alt_global_1_object")
                    : 0;
            const auto owner_alt_global_address_2 =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_alt_global_2")
                    : 0;
            const auto owner_alt_global_object_address_2 =
                action_definition != nullptr
                    ? GetDefinitionAddress(action_definition->addresses, "owner_alt_global_2_object")
                    : 0;
            const auto surface_owner_alt_global_address_2 =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_alt_global_2")
                    : 0;
            const auto surface_owner_alt_global_object_address_2 =
                surface_definition != nullptr
                    ? GetDefinitionAddress(surface_definition->addresses, "owner_alt_global_2_object")
                    : 0;

            const auto append_global_probe =
                [&](std::string_view label, uintptr_t configured_absolute_address) {
                    if (configured_absolute_address == 0) {
                        probe_log += " " + std::string(label) + "=unset";
                        return;
                    }

                    const auto resolved_global_address =
                        ProcessMemory::Instance().ResolveGameAddressOrZero(configured_absolute_address);
                    uintptr_t current_value = 0;
                    const auto has_value =
                        resolved_global_address != 0 &&
                        TryReadPointerValueDirect(resolved_global_address, &current_value);
                    probe_log +=
                        " " + std::string(label) +
                        "{abs=" + HexString(configured_absolute_address) +
                        " resolved=" + HexString(resolved_global_address) +
                        " value=" + (has_value ? HexString(current_value) : std::string("unreadable")) + "}";
                };

            const auto append_object_probe =
                [&](std::string_view label, uintptr_t configured_absolute_address) {
                    if (configured_absolute_address == 0) {
                        probe_log += " " + std::string(label) + "=unset";
                        return;
                    }

                    const auto resolved_global_address =
                        ProcessMemory::Instance().ResolveGameAddressOrZero(configured_absolute_address);
                    uintptr_t object_vftable = 0;
                    const auto has_vftable =
                        resolved_global_address != 0 &&
                        TryReadPointerValueDirect(resolved_global_address, &object_vftable);
                    probe_log +=
                        " " + std::string(label) +
                        "{abs=" + HexString(configured_absolute_address) +
                        " resolved=" + HexString(resolved_global_address) +
                        " vft=" + (has_vftable ? HexString(object_vftable) : std::string("unreadable")) + "}";
                };

            append_global_probe(
                "action.owner_global",
                owner_global_address != 0 ? owner_global_address : surface_owner_global_address);
            append_object_probe(
                "action.owner_global_object",
                owner_global_object_address != 0 ? owner_global_object_address : surface_owner_global_object_address);
            append_global_probe(
                "action.owner_context_global",
                owner_context_global_address != 0
                    ? owner_context_global_address
                    : surface_owner_context_global_address);
            append_global_probe(
                "action.owner_alt_global_1",
                owner_alt_global_address_1 != 0
                    ? owner_alt_global_address_1
                    : surface_owner_alt_global_address_1);
            append_object_probe(
                "action.owner_alt_global_1_object",
                owner_alt_global_object_address_1 != 0
                    ? owner_alt_global_object_address_1
                    : surface_owner_alt_global_object_address_1);
            append_global_probe(
                "action.owner_alt_global_2",
                owner_alt_global_address_2 != 0
                    ? owner_alt_global_address_2
                    : surface_owner_alt_global_address_2);
            append_object_probe(
                "action.owner_alt_global_2_object",
                owner_alt_global_object_address_2 != 0
                    ? owner_alt_global_object_address_2
                    : surface_owner_alt_global_object_address_2);

            for (const auto& [source, candidate_address] : candidates) {
                uintptr_t candidate_vftable = 0;
                (void)TryReadPointerValueDirect(candidate_address, &candidate_vftable);
                probe_log +=
                    " " + source +
                    "=" + HexString(candidate_address) +
                    "{vft=" + HexString(candidate_vftable) + "}";
            }
            Log(probe_log);
        }
    }

    std::string rejected_candidates;
    for (const auto& [source, candidate_address] : candidates) {
        std::string rejection_reason;
        if (!IsUiActionOwnerCandidateSane(candidate_address, action_definition, &rejection_reason)) {
            if (!rejected_candidates.empty()) {
                rejected_candidates += ", ";
            }
            rejected_candidates += source + "=" + HexString(candidate_address);
            if (!rejection_reason.empty()) {
                rejected_candidates += "{" + rejection_reason + "}";
            }
            continue;
        }

        *owner_address = candidate_address;
        if (!rejected_candidates.empty()) {
            Log(
                "Debug UI overlay rejected owner candidates before selecting action '" +
                std::string(action_id) + "'. rejected=" + rejected_candidates +
                " selected=" + source + "=" + HexString(candidate_address));
        }
        if (source != "snapshot") {
            Log(
                "Debug UI overlay resolved a preferred owner candidate for action '" +
                std::string(action_id) + "'. source=" + source + " owner=" + HexString(candidate_address) +
                " fallback=" + HexString(fallback_owner_address));
        }
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "No candidate UI owner for action '" + std::string(action_id) + "' passed validation. rejected=" +
            rejected_candidates;
    }
    return false;
}

bool TryResolveLiveUiSurfaceOwner(
    std::string_view surface_root_id,
    uintptr_t fallback_owner_address,
    uintptr_t* owner_address) {
    if (owner_address == nullptr) {
        return false;
    }

    *owner_address = 0;
    const auto* config = TryGetDebugUiOverlayConfig();
    if (surface_root_id == "dark_cloud_browser") {
        if (TryGetCurrentDarkCloudBrowser(owner_address) && *owner_address != 0) {
            return true;
        }
    } else if (surface_root_id == "main_menu") {
        if (config != nullptr && TryReadActiveTitleMainMenu(*config, nullptr, owner_address) && *owner_address != 0) {
            return true;
        }
    } else if (surface_root_id == "dialog") {
        if (TryReadTrackedDialogObject(owner_address) && *owner_address != 0) {
            return true;
        }
    } else if (surface_root_id == "settings") {
        if (TryGetActiveSettingsRender(owner_address) && *owner_address != 0) {
            return true;
        }
    } else if (surface_root_id == "dark_cloud_search" || surface_root_id == "quick_panel") {
        if (TryReadTrackedMyQuickPanel(owner_address) && *owner_address != 0) {
            return true;
        }
    } else if (surface_root_id == "simple_menu" || surface_root_id == "pause_menu") {
        if (TryGetActiveSimpleMenu(owner_address) && *owner_address != 0) {
            return true;
        }
    } else if (surface_root_id == "create") {
        const auto* surface_definition = FindUiSurfaceDefinition("create");
        if (surface_definition != nullptr) {
            const auto object_global = GetDefinitionAddress(surface_definition->addresses, "object_global");
            if (object_global != 0) {
                uintptr_t create_object = 0;
                if (TryReadResolvedGamePointer(object_global, &create_object) && create_object != 0) {
                    *owner_address = create_object;
                    return true;
                }
            }
        }
    }

    if (fallback_owner_address != 0) {
        *owner_address = fallback_owner_address;
        return true;
    }

    return false;
}

bool TryResolveUiActionDispatchExpectation(
    std::string_view surface_root_id,
    std::string_view action_id,
    UiActionDispatchExpectation* expectation) {
    if (expectation == nullptr) {
        return false;
    }

    *expectation = UiActionDispatchExpectation{};
    expectation->owner_name.assign(surface_root_id);

    const UiActionDefinition* action_definition = nullptr;
    if (!action_id.empty()) {
        action_definition = FindUiActionDefinition(action_id);
    }

    const UiSurfaceDefinition* surface_definition = nullptr;
    if (action_definition != nullptr && !action_definition->surface_id.empty()) {
        surface_definition = FindUiSurfaceDefinition(action_definition->surface_id);
    }
    if (surface_definition == nullptr && !surface_root_id.empty()) {
        surface_definition = FindUiSurfaceDefinition(surface_root_id);
    }

    if (action_definition != nullptr) {
        expectation->expected_vftable_address = GetDefinitionAddress(action_definition->addresses, "vftable");
        expectation->expected_handler_address = GetDefinitionAddress(action_definition->addresses, "handler");
        expectation->owner_context_global_address =
            GetDefinitionAddress(action_definition->addresses, "owner_context_global");
        expectation->owner_context_source_global_address =
            GetDefinitionAddress(action_definition->addresses, "owner_context_source_global");
        expectation->owner_context_source_alt_global_address_1 =
            GetDefinitionAddress(action_definition->addresses, "owner_context_source_alt_global_1");
        expectation->owner_context_source_alt_global_address_2 =
            GetDefinitionAddress(action_definition->addresses, "owner_context_source_alt_global_2");
        expectation->owner_optional_enabled_byte_pointer_offset =
            GetDefinitionAddress(action_definition->addresses, "owner_optional_enabled_byte_pointer_offset");
        expectation->owner_ready_pointer_offset =
            GetDefinitionAddress(action_definition->addresses, "owner_ready_pointer_offset");
        expectation->skip_owner_context_global =
            GetDefinitionAddress(action_definition->addresses, "skip_owner_context_global") != 0;
        expectation->owner_context_use_callback_owner =
            GetDefinitionAddress(action_definition->addresses, "owner_context_use_callback_owner") != 0;
        if (!action_definition->dispatch_kind.empty()) {
            expectation->dispatch_kind = action_definition->dispatch_kind;
        }
    }

    const auto action_uses_non_surface_owner_vftable =
        expectation->dispatch_kind == "control_child" ||
        expectation->dispatch_kind == "control_noarg" ||
        expectation->dispatch_kind == "direct_write";
    const auto action_uses_non_surface_owner_handler =
        expectation->dispatch_kind == "control_child" ||
        expectation->dispatch_kind == "control_child_callback_owner" ||
        expectation->dispatch_kind == "control_noarg" ||
        expectation->dispatch_kind == "owner_point_click" ||
        expectation->dispatch_kind == "direct_write";

    if (surface_definition != nullptr) {
        if (!surface_definition->title.empty()) {
            expectation->owner_name = surface_definition->title;
        }
        if (!action_uses_non_surface_owner_vftable && expectation->expected_vftable_address == 0) {
            expectation->expected_vftable_address = GetDefinitionAddress(surface_definition->addresses, "vftable");
        }
        if (!action_uses_non_surface_owner_handler && expectation->expected_handler_address == 0) {
            expectation->expected_handler_address = GetDefinitionAddress(surface_definition->addresses, "handler");
        }
        if (!action_uses_non_surface_owner_vftable &&
            !expectation->skip_owner_context_global &&
            expectation->owner_context_global_address == 0) {
            expectation->owner_context_global_address =
                GetDefinitionAddress(surface_definition->addresses, "owner_context_global");
        }
        if (expectation->owner_context_source_global_address == 0) {
            expectation->owner_context_source_global_address =
                GetDefinitionAddress(surface_definition->addresses, "owner_context_source_global");
        }
        if (expectation->owner_context_source_alt_global_address_1 == 0) {
            expectation->owner_context_source_alt_global_address_1 =
                GetDefinitionAddress(surface_definition->addresses, "owner_context_source_alt_global_1");
        }
        if (expectation->owner_context_source_alt_global_address_2 == 0) {
            expectation->owner_context_source_alt_global_address_2 =
                GetDefinitionAddress(surface_definition->addresses, "owner_context_source_alt_global_2");
        }
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config != nullptr) {
        // Modal menu actions are dispatched by the live simple-menu owner, not by the
        // title/profile/pause builder function that originally produced the action id.
        if (surface_root_id == "simple_menu" || surface_root_id == "pause_menu") {
            expectation->owner_name = surface_root_id == "pause_menu" ? "Pause Menu" : "Simple Menu";
            expectation->expected_vftable_address = config->simple_menu_vftable;
            expectation->expected_handler_address = 0;
        } else if (surface_root_id == "dark_cloud_search" || surface_root_id == "quick_panel") {
            expectation->owner_name = surface_root_id == "dark_cloud_search" ? "Dark Cloud Search" : "Quick Panel";
            expectation->expected_vftable_address = config->myquick_panel_vftable;
            expectation->expected_handler_address = 0;
        } else if (!action_uses_non_surface_owner_vftable && expectation->expected_vftable_address == 0) {
            if (surface_root_id == "dark_cloud_browser") {
                expectation->expected_vftable_address = config->dark_cloud_browser_vftable;
            } else if (surface_root_id == "main_menu") {
                expectation->expected_vftable_address = config->title_main_menu_vftable;
            } else if (surface_root_id == "dialog") {
                expectation->expected_vftable_address = config->msgbox_vftable;
            }
        }
    }

    return expectation->dispatch_kind == "control_child" ||
           expectation->dispatch_kind == "control_child_callback_owner" ||
           expectation->dispatch_kind == "control_noarg" ||
           expectation->dispatch_kind == "owner_point_click" ||
           expectation->dispatch_kind == "direct_write" ||
           expectation->expected_vftable_address != 0 ||
           expectation->expected_handler_address != 0;
}

std::optional<std::string_view> TryGetDarkCloudBrowserActionId(PendingDarkCloudBrowserAction action) {
    switch (action) {
        case PendingDarkCloudBrowserAction::Search:
            return "dark_cloud_browser.search";
        case PendingDarkCloudBrowserAction::Sort:
            return "dark_cloud_browser.sort";
        case PendingDarkCloudBrowserAction::Options:
            return "dark_cloud_browser.options";
        case PendingDarkCloudBrowserAction::Recent:
            return "dark_cloud_browser.recent";
        case PendingDarkCloudBrowserAction::OnlineLevels:
            return "dark_cloud_browser.online_levels";
        case PendingDarkCloudBrowserAction::MyLevels:
            return "dark_cloud_browser.my_levels";
        case PendingDarkCloudBrowserAction::None:
        default:
            return std::nullopt;
    }
}

std::optional<PendingDarkCloudBrowserAction> PollDarkCloudBrowserActionHotkey() {
    struct HotkeyBinding {
        int virtual_key = 0;
        PendingDarkCloudBrowserAction action = PendingDarkCloudBrowserAction::None;
    };

    constexpr HotkeyBinding kBindings[] = {
        {VK_F6, PendingDarkCloudBrowserAction::Search},
        {VK_F7, PendingDarkCloudBrowserAction::Sort},
        {VK_F8, PendingDarkCloudBrowserAction::Options},
        {VK_F9, PendingDarkCloudBrowserAction::Recent},
        {VK_F10, PendingDarkCloudBrowserAction::OnlineLevels},
        {VK_F11, PendingDarkCloudBrowserAction::MyLevels},
    };

    for (const auto& binding : kBindings) {
        if ((GetAsyncKeyState(binding.virtual_key) & 1) != 0) {
            return binding.action;
        }
    }

    return std::nullopt;
}

void StoreCompletedSemanticUiActionDispatchUnlocked(
    DebugUiOverlayState* state,
    std::string_view status,
    std::string_view error_message) {
    if (state == nullptr || !state->active_semantic_ui_action_dispatch.active) {
        return;
    }

    auto& result = state->last_semantic_ui_action_dispatch;
    result.valid = true;
    result.request_id = state->active_semantic_ui_action_dispatch.request_id;
    result.queued_at = state->active_semantic_ui_action_dispatch.queued_at;
    result.started_at = state->active_semantic_ui_action_dispatch.started_at;
    result.completed_at = GetTickCount64();
    result.snapshot_generation = state->active_semantic_ui_action_dispatch.snapshot_generation;
    result.owner_address = state->active_semantic_ui_action_dispatch.owner_address;
    result.control_address = state->active_semantic_ui_action_dispatch.control_address;
    result.action_id = state->active_semantic_ui_action_dispatch.action_id;
    result.target_label = state->active_semantic_ui_action_dispatch.target_label;
    result.surface_id = state->active_semantic_ui_action_dispatch.surface_id;
    result.dispatch_kind = state->active_semantic_ui_action_dispatch.dispatch_kind;
    result.status = std::string(status);
    result.error_message = std::string(error_message);
    state->active_semantic_ui_action_dispatch = ActiveSemanticUiActionDispatch{};
}

void StoreActiveSemanticUiActionDispatchResolution(
    uintptr_t owner_address,
    uintptr_t control_address,
    std::string_view dispatch_kind) {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (!g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.active) {
        return;
    }

    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.owner_address = owner_address;
    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.control_address = control_address;
    g_debug_ui_overlay_state.active_semantic_ui_action_dispatch.dispatch_kind = std::string(dispatch_kind);
}

bool TryCompleteActiveSemanticUiActionOnSurfaceTransitionUnlocked(
    DebugUiOverlayState* state,
    const DebugUiSurfaceSnapshot& snapshot) {
    if (state == nullptr || !state->active_semantic_ui_action_dispatch.active || snapshot.elements.empty()) {
        return false;
    }

    const auto active_surface_root_id = GetOverlaySurfaceRootId(state->active_semantic_ui_action_dispatch.surface_id);
    if (active_surface_root_id.empty() || snapshot.surface_id.empty() || active_surface_root_id == snapshot.surface_id) {
        return false;
    }

    if (state->active_semantic_ui_action_dispatch.started_at != 0 &&
        snapshot.captured_at_milliseconds < state->active_semantic_ui_action_dispatch.started_at) {
        return false;
    }

    StoreCompletedSemanticUiActionDispatchUnlocked(state, "dispatched", "");
    return true;
}
