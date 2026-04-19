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
        const auto expected_create_vftable =
            surface_definition != nullptr ? GetDefinitionAddress(surface_definition->addresses, "vftable") : 0;
        if (surface_definition != nullptr) {
            const auto object_global = GetDefinitionAddress(surface_definition->addresses, "object_global");
            if (object_global != 0) {
                uintptr_t create_object = 0;
                if (TryResolveCreateSurfaceOwnerPointer(object_global, &create_object) && create_object != 0) {
                    {
                        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
                        g_debug_ui_overlay_state.last_create_owner_object = create_object;
                    }
                    *owner_address = create_object;
                    return true;
                }
            }
        }

        uintptr_t cached_create_object = 0;
        {
            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            cached_create_object = g_debug_ui_overlay_state.last_create_owner_object;
        }
        if (cached_create_object != 0) {
            uintptr_t validated_create_object = 0;
            if (TryResolveValidatedUiOwnerPointer(
                    cached_create_object,
                    expected_create_vftable,
                    &validated_create_object) &&
                validated_create_object != 0) {
                *owner_address = validated_create_object;
                return true;
            }

            std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
            if (g_debug_ui_overlay_state.last_create_owner_object == cached_create_object) {
                g_debug_ui_overlay_state.last_create_owner_object = 0;
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
