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
