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

bool TryResolveValidatedUiOwnerPointer(
    uintptr_t owner_pointer,
    uintptr_t expected_vftable_address,
    uintptr_t* resolved_owner_address) {
    if (resolved_owner_address == nullptr) {
        return false;
    }

    *resolved_owner_address = 0;
    if (owner_pointer == 0) {
        return false;
    }

    if (expected_vftable_address == 0) {
        *resolved_owner_address = owner_pointer;
        return true;
    }

    const auto resolved_expected_vftable =
        ProcessMemory::Instance().ResolveGameAddressOrZero(expected_vftable_address);
    if (resolved_expected_vftable == 0) {
        return false;
    }

    uintptr_t owner_vftable = 0;
    if (!TryReadPointerValueDirect(owner_pointer, &owner_vftable) ||
        owner_vftable != resolved_expected_vftable) {
        return false;
    }

    *resolved_owner_address = owner_pointer;
    return true;
}

bool TryResolveCreateSurfaceOwnerPointer(uintptr_t object_global_address, uintptr_t* owner_address) {
    if (owner_address == nullptr || object_global_address == 0) {
        return false;
    }

    *owner_address = 0;

    const auto* surface_definition = FindUiSurfaceDefinition("create");
    const auto expected_vftable_address =
        surface_definition != nullptr ? GetDefinitionAddress(surface_definition->addresses, "vftable") : 0;

    uintptr_t candidate_pointer = 0;
    if (!TryReadResolvedGamePointer(object_global_address, &candidate_pointer) || candidate_pointer == 0) {
        return false;
    }

    if (TryResolveValidatedUiOwnerPointer(candidate_pointer, expected_vftable_address, owner_address) &&
        *owner_address != 0) {
        return true;
    }

    uintptr_t nested_owner_pointer = 0;
    if (!TryReadPointerValueDirect(candidate_pointer, &nested_owner_pointer) || nested_owner_pointer == 0) {
        return false;
    }

    return TryResolveValidatedUiOwnerPointer(nested_owner_pointer, expected_vftable_address, owner_address) &&
           *owner_address != 0;
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
