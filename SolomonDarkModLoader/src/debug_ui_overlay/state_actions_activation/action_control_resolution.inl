bool TryResolveUiActionControlAddress(
    std::string_view surface_root_id,
    uintptr_t owner_address,
    std::string_view action_id,
    uintptr_t fallback_control_address,
    uintptr_t* control_address,
    std::string* error_message) {
    if (control_address == nullptr) {
        return false;
    }

    *control_address = 0;

    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a live owner for action " + std::string(action_id) + ".";
        }
        return false;
    }

    const auto* action_definition = FindUiActionDefinition(action_id);
    if (action_definition == nullptr) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' is not defined in binary-layout.ini.";
        }
        return false;
    }

    const auto control_offset = GetDefinitionAddress(action_definition->addresses, "control_offset");
    if (control_offset != 0) {
        *control_address = owner_address + control_offset;
        return true;
    }

    if (fallback_control_address != 0) {
        *control_address = fallback_control_address;
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "UI action '" + std::string(action_id) + "' on surface " + std::string(surface_root_id) +
            " does not have a configured live control pointer path.";
    }
    return false;
}

bool TryResolveUiActionControlChildDispatchAddress(
    uintptr_t owner_address,
    std::string_view action_id,
    uintptr_t* control_address,
    std::string* error_message) {
    if (control_address == nullptr) {
        return false;
    }

    *control_address = 0;
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' requires a live rollout control owner.";
        }
        return false;
    }

    const auto* action_definition = FindUiActionDefinition(action_id);
    if (action_definition == nullptr) {
        if (error_message != nullptr) {
            *error_message = "UI action '" + std::string(action_id) + "' is not defined in binary-layout.ini.";
        }
        return false;
    }

    const auto count_offset = GetDefinitionAddress(action_definition->addresses, "control_child_count_offset");
    const auto list_offset = GetDefinitionAddress(action_definition->addresses, "control_child_list_offset");
    const auto child_index = GetDefinitionAddress(action_definition->addresses, "control_child_index");
    const auto dispatch_offset = GetDefinitionAddress(action_definition->addresses, "control_child_dispatch_offset");
    const auto use_raw_child = GetDefinitionAddress(action_definition->addresses, "control_child_use_raw") != 0;
    if (count_offset == 0 || list_offset == 0 || (!use_raw_child && dispatch_offset == 0)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' is missing rollout child dispatch offsets.";
        }
        return false;
    }

    std::uint32_t child_count = 0;
    uintptr_t child_list = 0;
    if (!TryReadUInt32ValueDirect(owner_address + count_offset, &child_count) ||
        !TryReadPointerValueDirect(owner_address + list_offset, &child_list) ||
        child_count == 0 || child_list == 0) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' could not resolve rollout child list state.";
        }
        return false;
    }

    if (child_index >= child_count) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' requested rollout child index " +
                std::to_string(child_index) + " but only " + std::to_string(child_count) + " child entries exist.";
        }
        return false;
    }

    uintptr_t child_address = 0;
    if (!TryReadPointerValueDirect(
            child_list + child_index * sizeof(uintptr_t),
            &child_address) ||
        child_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_id) + "' could not resolve the selected rollout child entry.";
        }
        return false;
    }

    *control_address = use_raw_child ? child_address : (child_address + dispatch_offset);
    Log(
        "Debug UI control_child dispatch state: action=" + std::string(action_id) +
        " owner=" + HexString(owner_address) +
        " child_count=" + std::to_string(child_count) +
        " child_list=" + HexString(child_list) +
        " child_index=" + std::to_string(child_index) +
        " child=" + HexString(child_address) +
        " use_raw_child=" + std::to_string(use_raw_child ? 1 : 0) +
        " dispatch_control=" + HexString(*control_address));
    if (action_id == "settings.controls") {
        MaybeLogSettingsControlsLiveState(
            "control_child_dispatch_resolve",
            0,
            owner_address,
            child_address,
            "CUSTOMIZE KEYBOARD",
            0.0f,
            0.0f,
            0.0f,
            0.0f);
    }
    return true;
}

namespace {

constexpr std::size_t kTitleMainMenuHasPreviousSaveOffset = 0x474;

std::filesystem::path GetStagedSurvivalSaveDirectoryPath() {
    return GetHostProcessDirectory() / "savegames" / "solomondark" / "savegames" / "_survival";
}
