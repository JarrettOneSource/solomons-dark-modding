#include "label_resolution_helpers.inl"

std::vector<OverlayRenderElement> TryBuildDarkCloudSearchOverlayRenderElements(
    const std::vector<OverlayRenderElement>& quick_panel_render_elements) {
    if (quick_panel_render_elements.empty()) {
        return {};
    }

    auto same_rect = [](const OverlayRenderElement& left, const OverlayRenderElement& right) {
        return std::fabs(left.left - right.left) <= 1.0f &&
               std::fabs(left.top - right.top) <= 1.0f &&
               std::fabs(left.right - right.right) <= 1.0f &&
               std::fabs(left.bottom - right.bottom) <= 1.0f;
    };

    const OverlayRenderElement* panel = nullptr;
    const OverlayRenderElement* name_field = nullptr;
    const OverlayRenderElement* author_field = nullptr;
    const OverlayRenderElement* search_now_button = nullptr;

    for (const auto& element : quick_panel_render_elements) {
        if (element.surface_id == "quick_panel.panel") {
            panel = &element;
            break;
        }
    }

    if (panel == nullptr) {
        return {};
    }

    for (const auto& element : quick_panel_render_elements) {
        if (element.surface_id != "quick_panel" && element.surface_id != "quick_panel.text") {
            continue;
        }
        if (same_rect(element, *panel)) {
            continue;
        }

        const auto normalized_label = NormalizeSemanticUiToken(element.label);
        if (normalized_label == "search now") {
            search_now_button = &element;
        } else if (normalized_label == "author" && author_field == nullptr) {
            author_field = &element;
        } else if (normalized_label == "name" && name_field == nullptr) {
            name_field = &element;
        }
    }

    if (name_field == nullptr || author_field == nullptr || search_now_button == nullptr) {
        return {};
    }

    auto build_element = [&](const OverlayRenderElement& source, std::string surface_id, std::string label) {
        OverlayRenderElement render_element;
        render_element.surface_id = std::move(surface_id);
        render_element.surface_title = "Dark Cloud Search";
        render_element.label = std::move(label);
        render_element.action_id = ResolveConfiguredUiActionId("dark_cloud_search", render_element.label);
        render_element.source_object_ptr = source.source_object_ptr;
        render_element.surface_object_ptr = panel->surface_object_ptr;
        render_element.show_label = true;
        render_element.left = source.left;
        render_element.top = source.top;
        render_element.right = source.right;
        render_element.bottom = source.bottom;
        return render_element;
    };

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(4);

    OverlayRenderElement panel_element;
    panel_element.surface_id = "dark_cloud_search.panel";
    panel_element.surface_title = "Dark Cloud Search";
    panel_element.label = "Dark Cloud Search";
    panel_element.source_object_ptr = panel->source_object_ptr;
    panel_element.surface_object_ptr = panel->surface_object_ptr;
    panel_element.show_label = false;
    panel_element.left = panel->left;
    panel_element.top = panel->top;
    panel_element.right = panel->right;
    panel_element.bottom = panel->bottom;
    render_elements.push_back(std::move(panel_element));
    render_elements.push_back(build_element(*name_field, "dark_cloud_search", "NAME"));
    render_elements.push_back(build_element(*author_field, "dark_cloud_search", "AUTHOR"));
    render_elements.push_back(build_element(*search_now_button, "dark_cloud_search", "SEARCH NOW"));

    SortOverlayRenderElementsByTopLeft(&render_elements);
    return render_elements;
}

std::vector<OverlayRenderElement> TryBuildDarkCloudBrowserOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<ObservedUiElement>& exact_control_elements,
    const std::vector<ObservedUiElement>& observed_elements) {
    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(exact_control_elements.size() + exact_text_elements.size() + observed_elements.size());
    uintptr_t browser_address = 0;
    (void)TryGetCurrentDarkCloudBrowser(&browser_address);

    auto is_trustworthy_browser_text_bounds = [](const ObservedUiElement& element) {
        const auto width = element.max_x - element.min_x;
        const auto height = element.max_y - element.min_y;
        return element.min_x >= 0.0f && element.min_y >= 0.0f && width >= 4.0f && height >= 6.0f &&
               width <= 512.0f && height <= 96.0f;
    };

    for (const auto& element : exact_control_elements) {
        if (element.surface_id != "dark_cloud_browser" && element.surface_id != "dark_cloud_browser.panel") {
            continue;
        }
        if (browser_address != 0 && element.object_ptr == browser_address) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = element.surface_id;
        render_element.surface_title = element.surface_title;
        render_element.label = ResolveBestDarkCloudBrowserControlLabel(
            element.object_ptr,
            element.min_x,
            element.min_y,
            element.max_x,
            element.max_y,
            element.label,
            exact_text_elements);
        render_element.action_id = ResolveConfiguredUiActionId("dark_cloud_browser", render_element.label);
        render_element.source_object_ptr = element.object_ptr;
        render_element.surface_object_ptr = browser_address;
        render_element.left = element.min_x;
        render_element.top = element.min_y;
        render_element.right = element.max_x;
        render_element.bottom = element.max_y;
        render_element.show_label =
            element.surface_id != "dark_cloud_browser.panel" && !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "dark_cloud_browser") {
            continue;
        }
        if (!is_trustworthy_browser_text_bounds(element)) {
            continue;
        }

        const auto center_x = (element.min_x + element.max_x) * 0.5f;
        const auto center_y = (element.min_y + element.max_y) * 0.5f;
        const auto overlaps_existing_control = std::any_of(
            render_elements.begin(),
            render_elements.end(),
            [&](const OverlayRenderElement& render_element) {
                return render_element.surface_id == "dark_cloud_browser" &&
                       PointInsideRect(center_x, center_y, render_element.left, render_element.top, render_element.right, render_element.bottom);
            });
        if (overlaps_existing_control) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "dark_cloud_browser.text";
        render_element.surface_title = "Dark Cloud Browser";
        render_element.label = element.label;
        render_element.source_object_ptr = element.object_ptr;
        render_element.surface_object_ptr = browser_address;
        render_element.left = element.min_x;
        render_element.top = element.min_y;
        render_element.right = element.max_x;
        render_element.bottom = element.max_y;
        render_elements.push_back(std::move(render_element));
    }

    if (browser_address != 0) {
        uintptr_t list_widget = 0;
        TryReadPointerField(
            reinterpret_cast<const void*>(browser_address),
            g_debug_ui_overlay_state.config.dark_cloud_browser_list_widget_offset,
            &list_widget);

        if (list_widget != 0) {
            float list_left = 0, list_top = 0, list_right = 0, list_bottom = 0;
            float list_row_height = 0;
            int entry_count = 0;
            int max_visible = 0;

            TryReadExactControlRect(g_debug_ui_overlay_state.config,
                reinterpret_cast<const void*>(list_widget), &list_left, &list_top, &list_right, &list_bottom);
            TryReadPlainField(
                reinterpret_cast<const void*>(list_widget),
                g_debug_ui_overlay_state.config.dark_cloud_browser_list_widget_row_height_offset,
                &list_row_height);
            TryReadPlainField(
                reinterpret_cast<const void*>(list_widget),
                g_debug_ui_overlay_state.config.dark_cloud_browser_list_widget_entry_count_offset,
                &entry_count);
            TryReadPlainField(
                reinterpret_cast<const void*>(list_widget),
                g_debug_ui_overlay_state.config.dark_cloud_browser_list_widget_max_visible_rows_offset,
                &max_visible);

            if (list_row_height > 1.0f && list_right > list_left && list_bottom > list_top) {
                const int clamped_max_visible = max_visible > 0 ? max_visible : 15;
                int probed_content_count = 0;
                uintptr_t row_data_base = 0;
                TryReadPointerField(
                    reinterpret_cast<const void*>(list_widget),
                    g_debug_ui_overlay_state.config.dark_cloud_browser_list_widget_row_data_base_offset,
                    &row_data_base);

                if (row_data_base != 0 && row_data_base > 0x100000) {
                    for (int ri = 0; ri < clamped_max_visible; ++ri) {
                        uintptr_t row_ptr = 0;
                        if (TryReadPointerField(reinterpret_cast<const void*>(row_data_base), ri * 4, &row_ptr) &&
                            row_ptr != 0 && row_ptr > 0x10000) {
                            ++probed_content_count;
                        } else {
                            break;
                        }
                    }
                }

                const int draw_count =
                    probed_content_count > 0 ? probed_content_count : (std::min)(entry_count, clamped_max_visible);
                constexpr int kHeaderRowCount = 1;
                for (int i = 0; i < draw_count; ++i) {
                    const float row_top = list_top + static_cast<float>(i + kHeaderRowCount) * list_row_height;
                    const float row_bottom = row_top + list_row_height;

                    if (row_bottom > list_bottom) break;

                    OverlayRenderElement render_element;
                    render_element.surface_id = "dark_cloud_browser.item";
                    render_element.surface_title = "Dark Cloud Browser";
                    render_element.label = "Item " + std::to_string(i + 1);
                    render_element.source_object_ptr = list_widget;
                    render_element.surface_object_ptr = browser_address;
                    render_element.left = list_left;
                    render_element.top = row_top;
                    render_element.right = list_right;
                    render_element.bottom = row_bottom;
                    render_element.show_label = true;
                    render_elements.push_back(std::move(render_element));
                }
            }
        }
    }

    // Collect the list widget rect so observed elements inside it are skipped
    // (the list items are handled by the struct-based list widget reader above).
    float list_area_left = 0, list_area_top = 0, list_area_right = 0, list_area_bottom = 0;
    {
        uintptr_t lw = 0;
        if (browser_address != 0 &&
            TryReadPointerField(
                reinterpret_cast<const void*>(browser_address),
                g_debug_ui_overlay_state.config.dark_cloud_browser_list_widget_offset,
                &lw) &&
            lw != 0) {
            TryReadExactControlRect(g_debug_ui_overlay_state.config,
                reinterpret_cast<const void*>(lw), &list_area_left, &list_area_top, &list_area_right, &list_area_bottom);
        }
    }

    for (const auto& element : observed_elements) {
        if (element.surface_id != "dark_cloud_browser" || element.label.empty()) {
            continue;
        }
        if (!is_trustworthy_browser_text_bounds(element)) {
            continue;
        }
        // Skip elements inside the list widget area — those are handled by the struct reader.
        if (list_area_right > list_area_left && list_area_bottom > list_area_top) {
            const auto cy = (element.min_y + element.max_y) * 0.5f;
            if (cy >= list_area_top && cy <= list_area_bottom) {
                continue;
            }
        }

        const auto center_x = (element.min_x + element.max_x) * 0.5f;
        const auto center_y = (element.min_y + element.max_y) * 0.5f;
        const auto overlaps_existing = std::any_of(
            render_elements.begin(),
            render_elements.end(),
            [&](const OverlayRenderElement& re) {
                return PointInsideRect(center_x, center_y, re.left, re.top, re.right, re.bottom);
            });
        if (overlaps_existing) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "dark_cloud_browser.item";
        render_element.surface_title = "Dark Cloud Browser";
        render_element.label = element.label;
        render_element.source_object_ptr = element.object_ptr;
        render_element.surface_object_ptr = browser_address;
        render_element.left = element.min_x;
        render_element.top = element.min_y;
        render_element.right = element.max_x;
        render_element.bottom = element.max_y;
        render_element.show_label = true;
        render_elements.push_back(std::move(render_element));
    }

    std::sort(render_elements.begin(), render_elements.end(), [](const OverlayRenderElement& left, const OverlayRenderElement& right) {
        if (left.top != right.top) {
            return left.top < right.top;
        }
        return left.left < right.left;
    });
    return render_elements;
}

std::vector<OverlayRenderElement> TryBuildTitleMainMenuOverlayRenderElements(
    const FontAtlas& /*atlas*/,
    const std::vector<ObservedUiElement>& exact_lines,
    const std::vector<ObservedUiElement>& exact_control_elements,
    const std::vector<ObservedUiElement>& observed_elements) {
    uintptr_t active_settings_address = 0;
    if (TryGetActiveSettingsRender(&active_settings_address) && active_settings_address != 0) {
        return {};
    }

    uintptr_t active_dark_cloud_browser_address = 0;
    if (TryGetActiveDarkCloudBrowserRender(&active_dark_cloud_browser_address) &&
        active_dark_cloud_browser_address != 0) {
        return {};
    }

    uintptr_t quick_panel_address = 0;
    if (TryReadTrackedMyQuickPanel(&quick_panel_address) && quick_panel_address != 0) {
        return {};
    }

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return {};
    }

    std::size_t observed_main_menu_elements = 0;
    for (const auto& observed : observed_elements) {
        if (observed.surface_id == "main_menu") {
            ++observed_main_menu_elements;
        }
    }

    uintptr_t main_menu_address = 0;
    if (!TryReadActiveTitleMainMenu(*config, nullptr, &main_menu_address) ||
        main_menu_address == 0) {
        return {};
    }

    int menu_mode = 0;
    if (!TryReadMainMenuMode(*config, main_menu_address, &menu_mode)) {
        return {};
    }

    const auto button_labels = BuildMainMenuButtonLabels(menu_mode);
    const auto has_main_menu_exact_controls = std::any_of(
        exact_control_elements.begin(),
        exact_control_elements.end(),
        [](const ObservedUiElement& element) {
            return element.surface_id == "main_menu";
        });
    const auto has_main_menu_exact_text = std::any_of(
        exact_lines.begin(),
        exact_lines.end(),
        [](const ObservedUiElement& element) {
            return element.surface_id == "main_menu";
        });
    if (button_labels.empty() && !has_main_menu_exact_controls && !has_main_menu_exact_text) {
        return {};
    }

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(button_labels.size() + exact_control_elements.size() + exact_lines.size());
    for (std::size_t button_index = 0; button_index < button_labels.size(); ++button_index) {
        float left = 0.0f;
        float top = 0.0f;
        float right = 0.0f;
        float bottom = 0.0f;
        if (!TryReadMainMenuButtonRect(*config, main_menu_address, button_index, &left, &top, &right, &bottom)) {
            continue;
        }

        OverlayRenderElement element;
        element.surface_id = "main_menu";
        element.surface_title = "Main Menu";
        element.label = button_labels[button_index];
        element.action_id = ResolveConfiguredUiActionId("main_menu", element.label);
        element.source_object_ptr = main_menu_address + config->title_main_menu_button_array_offset +
                                    button_index * config->title_main_menu_button_stride;
        element.surface_object_ptr = main_menu_address;
        element.left = left;
        element.top = top;
        element.right = right;
        element.bottom = bottom;
        render_elements.push_back(std::move(element));
    }

    for (const auto& exact_control : exact_control_elements) {
        if (exact_control.surface_id != "main_menu") {
            continue;
        }

        const auto center_x = (exact_control.min_x + exact_control.max_x) * 0.5f;
        const auto center_y = (exact_control.min_y + exact_control.max_y) * 0.5f;
        auto label = ResolveBestControlLabelFromTextSurface(
            "main_menu",
            exact_control.object_ptr,
            exact_control.min_x,
            exact_control.min_y,
            exact_control.max_x,
            exact_control.max_y,
            exact_control.label,
            exact_lines);
        if (label.empty()) {
            (void)TryReadCachedObjectLabel(exact_control.object_ptr, &label);
        }

        auto existing_it = std::find_if(
            render_elements.begin(),
            render_elements.end(),
            [&](const OverlayRenderElement& render_element) {
                return render_element.surface_id == "main_menu" &&
                       ((exact_control.object_ptr != 0 &&
                         render_element.source_object_ptr == exact_control.object_ptr) ||
                        PointInsideRect(center_x, center_y, render_element.left, render_element.top, render_element.right, render_element.bottom));
            });
        if (existing_it != render_elements.end()) {
            existing_it->left = exact_control.min_x;
            existing_it->top = exact_control.min_y;
            existing_it->right = exact_control.max_x;
            existing_it->bottom = exact_control.max_y;
            existing_it->source_object_ptr = exact_control.object_ptr;
            existing_it->surface_object_ptr = main_menu_address;
            const auto exact_action_id = ResolveConfiguredUiActionId("main_menu", label);
            const bool can_override_with_exact_label =
                !label.empty() &&
                (existing_it->action_id.empty() ||
                 (!exact_action_id.empty() && exact_action_id == existing_it->action_id) ||
                 existing_it->label.empty());
            if (can_override_with_exact_label) {
                existing_it->label = label;
                existing_it->action_id = exact_action_id;
            }
            existing_it->show_label = !existing_it->label.empty();
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "main_menu";
        render_element.surface_title = "Main Menu";
        render_element.label = std::move(label);
        render_element.action_id = ResolveConfiguredUiActionId("main_menu", render_element.label);
        render_element.source_object_ptr = exact_control.object_ptr;
        render_element.surface_object_ptr = main_menu_address;
        render_element.left = exact_control.min_x;
        render_element.top = exact_control.min_y;
        render_element.right = exact_control.max_x;
        render_element.bottom = exact_control.max_y;
        render_element.show_label = !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    auto is_trustworthy_main_menu_text_bounds = [](const ObservedUiElement& element) {
        const auto width = element.max_x - element.min_x;
        const auto height = element.max_y - element.min_y;
        return element.min_x >= 0.0f && element.min_y >= 0.0f && width >= 4.0f && height >= 6.0f &&
               width <= 512.0f && height <= 96.0f;
    };

    for (const auto& exact_line : exact_lines) {
        if (exact_line.surface_id != "main_menu" || exact_line.label.empty()) {
            continue;
        }
        if (!is_trustworthy_main_menu_text_bounds(exact_line)) {
            continue;
        }

        const auto center_x = (exact_line.min_x + exact_line.max_x) * 0.5f;
        const auto center_y = (exact_line.min_y + exact_line.max_y) * 0.5f;
        if (HasSurfaceControlElement(render_elements, "main_menu", exact_line.object_ptr, center_x, center_y)) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "main_menu.text";
        render_element.surface_title = "Main Menu";
        render_element.label = exact_line.label;
        render_element.action_id = ResolveConfiguredUiActionId("main_menu", render_element.label);
        render_element.source_object_ptr = exact_line.object_ptr;
        render_element.surface_object_ptr = main_menu_address;
        render_element.show_label = false;
        render_element.left = exact_line.min_x;
        render_element.top = exact_line.min_y;
        render_element.right = exact_line.max_x;
        render_element.bottom = exact_line.max_y;
        render_elements.push_back(std::move(render_element));
    }

    SortOverlayRenderElementsByTopLeft(&render_elements);
    return render_elements;
}

#include "label_resolution_surface_registry_and_frame_render.inl"
