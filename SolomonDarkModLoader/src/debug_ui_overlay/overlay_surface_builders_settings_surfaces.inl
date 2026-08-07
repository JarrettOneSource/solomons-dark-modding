bool HasCurrentSettingsPanelArt(
    const std::vector<CapturedMenuArtElement>& art_elements) {
    constexpr std::string_view kRequiredArtIds[] = {
        "ControlPanel.0",
        "ControlPanel.8",
        "ControlPanel.18",
    };
    return std::all_of(
        std::begin(kRequiredArtIds),
        std::end(kRequiredArtIds),
        [&](std::string_view required_art_id) {
            return std::any_of(
                art_elements.begin(),
                art_elements.end(),
                [&](const CapturedMenuArtElement& element) {
                    return element.visible &&
                        element.art_id == required_art_id;
                });
        });
}

bool HasAnyCurrentSettingsPanelArt(
    const std::vector<CapturedMenuArtElement>& art_elements) {
    return std::any_of(
        art_elements.begin(),
        art_elements.end(),
        [](const CapturedMenuArtElement& element) {
            return element.visible &&
                element.art_id.rfind("ControlPanel.", 0) == 0;
        });
}

struct CachedSettingsFamilyOverlayArt {
    uintptr_t settings_address = 0;
    std::vector<CapturedMenuArtElement> elements;
};

struct SettingsFamilyOverlayArtCacheState {
    CachedSettingsFamilyOverlayArt settings;
    CachedSettingsFamilyOverlayArt controls;
    CachedSettingsFamilyOverlayArt transition;
    uintptr_t settings_address = 0;
    SettingsRolloutPageState last_page =
        SettingsRolloutPageState::Unknown;
    std::vector<CapturedMenuArtElement> settings_underlay;
};

SettingsFamilyOverlayArtCacheState& GetSettingsFamilyOverlayArtCacheState() {
    static SettingsFamilyOverlayArtCacheState state;
    return state;
}

SettingsRolloutPageState ResolveSettingsRolloutPageForCapture(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address) {
    SettingsRolloutPageObservation observation;
    if (TryResolveSettingsRolloutPageState(
            config,
            settings_address,
            &observation)) {
        return observation.page;
    }

    const auto& cache_state = GetSettingsFamilyOverlayArtCacheState();
    if (cache_state.settings_address == settings_address) {
        return cache_state.last_page;
    }
    return SettingsRolloutPageState::Unknown;
}

std::string GetCapturedMenuArtSemanticKey(
    const CapturedMenuArtElement& element) {
    std::ostringstream key;
    key << element.art_id.size() << ':' << element.art_id
        << element.draw_kind.size() << ':' << element.draw_kind
        << ':' << (element.visible ? 1 : 0)
        << ':' << std::hexfloat
        << element.left << ':' << element.top << ':'
        << element.right << ':' << element.bottom << ':'
        << element.unclipped_left << ':' << element.unclipped_top << ':'
        << element.unclipped_right << ':' << element.unclipped_bottom;
    return key.str();
}

bool TryExtractControlsPageArtDifference(
    const std::vector<CapturedMenuArtElement>& settings_underlay,
    const std::vector<CapturedMenuArtElement>& current_elements,
    std::vector<CapturedMenuArtElement>* controls_elements) {
    if (settings_underlay.empty() || controls_elements == nullptr) {
        return false;
    }

    std::unordered_map<std::string, std::size_t> underlay_counts;
    for (const auto& element : settings_underlay) {
        ++underlay_counts[GetCapturedMenuArtSemanticKey(element)];
    }

    controls_elements->clear();
    for (const auto& element : current_elements) {
        const auto semantic_key = GetCapturedMenuArtSemanticKey(element);
        auto underlay = underlay_counts.find(semantic_key);
        if (underlay != underlay_counts.end() && underlay->second > 0) {
            --underlay->second;
            continue;
        }
        if (element.art_id.rfind("Title.", 0) == 0) {
            continue;
        }
        if (element.art_id.rfind("ControlPanel.", 0) == 0) {
            controls_elements->clear();
            return false;
        }
        controls_elements->push_back(element);
    }
    return !controls_elements->empty();
}

bool TryExtractSettingsFamilyOverlayArt(
    const std::vector<CapturedMenuArtElement>& current_elements,
    std::vector<CapturedMenuArtElement>* overlay_elements) {
    if (overlay_elements == nullptr ||
        !HasCurrentSettingsPanelArt(current_elements)) {
        return false;
    }

    const auto first_panel_art = std::min_element(
        current_elements.begin(),
        current_elements.end(),
        [](const CapturedMenuArtElement& left,
           const CapturedMenuArtElement& right) {
            const auto left_is_panel =
                left.visible &&
                left.art_id.rfind("ControlPanel.", 0) == 0;
            const auto right_is_panel =
                right.visible &&
                right.art_id.rfind("ControlPanel.", 0) == 0;
            if (left_is_panel != right_is_panel) {
                return left_is_panel;
            }
            return left.draw_order < right.draw_order;
        });
    if (first_panel_art == current_elements.end() ||
        !first_panel_art->visible ||
        first_panel_art->art_id.rfind("ControlPanel.", 0) != 0) {
        return false;
    }

    const auto overlay_first_draw_order = first_panel_art->draw_order;
    overlay_elements->clear();
    for (const auto& element : current_elements) {
        if (element.draw_order >= overlay_first_draw_order) {
            overlay_elements->push_back(element);
        }
    }

    const auto includes_title_backdrop = std::any_of(
        overlay_elements->begin(),
        overlay_elements->end(),
        [](const CapturedMenuArtElement& element) {
            return element.art_id.rfind("Title.", 0) == 0;
        });
    return !overlay_elements->empty() && !includes_title_backdrop;
}

std::vector<CapturedMenuArtElement> ResolveSettingsFamilyMenuArtElements(
    std::vector<CapturedMenuArtElement> current_elements) {
    auto& cache_state = GetSettingsFamilyOverlayArtCacheState();

    const auto clear_caches = [&]() {
        cache_state = SettingsFamilyOverlayArtCacheState{};
    };

    const auto replay_cached_overlay = [&current_elements](
        const CachedSettingsFamilyOverlayArt& cache,
        uintptr_t settings_address) {
        if (HasAnyCurrentSettingsPanelArt(current_elements) ||
            cache.settings_address != settings_address ||
            cache.elements.empty()) {
            return;
        }

        auto cached_overlay = cache.elements;
        std::stable_sort(
            cached_overlay.begin(),
            cached_overlay.end(),
            [](const CapturedMenuArtElement& left,
               const CapturedMenuArtElement& right) {
                return left.draw_order < right.draw_order;
            });
        std::uint32_t next_draw_order = 0;
        for (const auto& element : current_elements) {
            next_draw_order = (std::max)(
                next_draw_order,
                element.draw_order + 1);
        }
        for (auto& element : cached_overlay) {
            element.draw_order = next_draw_order++;
            current_elements.push_back(std::move(element));
        }
    };

    const auto* config = TryGetDebugUiOverlayConfig();
    uintptr_t settings_address = 0;
    if (config == nullptr ||
        !TryReadTrackedSettingsRender(&settings_address) ||
        settings_address == 0) {
        clear_caches();
        return current_elements;
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSettingsPanelRect(
            *config,
            settings_address,
            &panel_left,
            &panel_top,
            &panel_right,
            &panel_bottom)) {
        clear_caches();
        return current_elements;
    }
    if (cache_state.settings_address != 0 &&
        cache_state.settings_address != settings_address) {
        clear_caches();
    }
    cache_state.settings_address = settings_address;

    SettingsRolloutPageObservation page_observation;
    if (!TryResolveSettingsRolloutPageState(
            *config,
            settings_address,
            &page_observation)) {
        std::vector<CapturedMenuArtElement> transition_overlay;
        if (TryExtractSettingsFamilyOverlayArt(
                current_elements,
                &transition_overlay)) {
            cache_state.settings.settings_address = settings_address;
            cache_state.settings.elements =
                std::move(transition_overlay);
            cache_state.settings_underlay = current_elements;
            cache_state.transition = CachedSettingsFamilyOverlayArt{};
        } else if (TryExtractControlsPageArtDifference(
                cache_state.settings_underlay,
                current_elements,
                &transition_overlay)) {
            cache_state.transition.settings_address = settings_address;
            cache_state.transition.elements =
                std::move(transition_overlay);
            static int s_transition_difference_logs_remaining = 8;
            if (s_transition_difference_logs_remaining > 0) {
                --s_transition_difference_logs_remaining;
                Log(
                    "Debug UI settings-family measured transition page art "
                    "as a semantic multiset difference from the live "
                    "Settings underlay. settings=" +
                    HexString(settings_address) + " elements=" +
                    std::to_string(
                        cache_state.transition.elements.size()));
            }
        }

        const auto* last_cache =
            cache_state.last_page == SettingsRolloutPageState::Controls
            ? &cache_state.controls
            : &cache_state.settings;
        replay_cached_overlay(*last_cache, settings_address);
        return current_elements;
    }

    auto* active_cache =
        page_observation.page == SettingsRolloutPageState::Controls
        ? &cache_state.controls
        : &cache_state.settings;
    std::vector<CapturedMenuArtElement> measured_overlay;
    if (page_observation.page == SettingsRolloutPageState::Settings &&
        TryExtractSettingsFamilyOverlayArt(
            current_elements,
            &measured_overlay)) {
        active_cache->settings_address = settings_address;
        active_cache->elements = std::move(measured_overlay);
        cache_state.transition = CachedSettingsFamilyOverlayArt{};
        cache_state.last_page = page_observation.page;
        if (page_observation.page == SettingsRolloutPageState::Settings) {
            cache_state.settings_underlay = current_elements;
        }
        return current_elements;
    }

    if (cache_state.last_page == SettingsRolloutPageState::Settings) {
        std::vector<CapturedMenuArtElement> controls_overlay;
        if (TryExtractControlsPageArtDifference(
                cache_state.settings_underlay,
                current_elements,
                &controls_overlay)) {
            cache_state.transition.settings_address = settings_address;
            cache_state.transition.elements = std::move(controls_overlay);
            static int s_controls_difference_logs_remaining = 8;
            if (s_controls_difference_logs_remaining > 0) {
                --s_controls_difference_logs_remaining;
                Log(
                    "Debug UI settings-family measured Controls page art "
                    "as a semantic multiset difference from the live "
                    "Settings underlay. settings=" +
                    HexString(settings_address) + " elements=" +
                    std::to_string(
                        cache_state.transition.elements.size()));
            }
        } else if (
            page_observation.page == SettingsRolloutPageState::Settings
        ) {
            cache_state.settings_underlay = current_elements;
        }
    }

    if (cache_state.last_page != page_observation.page &&
        cache_state.transition.settings_address == settings_address &&
        !cache_state.transition.elements.empty()) {
        active_cache->settings_address = settings_address;
        active_cache->elements =
            std::move(cache_state.transition.elements);
        cache_state.transition = CachedSettingsFamilyOverlayArt{};
        static int s_transition_cache_adoption_logs_remaining = 8;
        if (s_transition_cache_adoption_logs_remaining > 0) {
            --s_transition_cache_adoption_logs_remaining;
            Log(
                "Debug UI settings-family adopted the last complete "
                "transition draw for the native page that reached local "
                "origin. settings=" + HexString(settings_address));
        }
    }
    cache_state.last_page = page_observation.page;
    replay_cached_overlay(*active_cache, settings_address);
    return current_elements;
}

bool TryBuildSettingsRolloutMarkerElements(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    std::string_view surface_title,
    float panel_left,
    float panel_top,
    float panel_right,
    float panel_bottom,
    const std::vector<CapturedMenuArtElement>& art_elements,
    std::vector<OverlayRenderElement>* render_elements) {
    if (settings_address == 0 || render_elements == nullptr) {
        return false;
    }

    struct RolloutRow {
        uintptr_t control_address = 0;
        std::string label;
    };

    std::vector<uintptr_t> root_controls;
    if (!TryReadSettingsControlPointers(
            config,
            settings_address,
            &root_controls)) {
        return false;
    }

    const auto normalized_surface_title =
        NormalizeSemanticUiToken(surface_title);
    std::vector<RolloutRow> rollout_rows;
    std::set<uintptr_t> seen_rollout_controls;
    for (const auto root_control : root_controls) {
        if (!IsSettingsRolloutControl(config, root_control)) {
            continue;
        }
        if (!seen_rollout_controls.insert(root_control).second) {
            Log(
                "Debug UI settings rollout marker pairing refused duplicate "
                "root control. settings=" + HexString(settings_address) +
                " control=" + HexString(root_control));
            return false;
        }

        std::string label;
        if (!TryReadCachedObjectLabel(root_control, &label)) {
            label = ResolveSettingsControlLabel(config, root_control);
        }
        if (label.empty() ||
            NormalizeSemanticUiToken(label) == normalized_surface_title) {
            continue;
        }

        rollout_rows.push_back(RolloutRow{root_control, std::move(label)});
    }

    std::vector<const CapturedMenuArtElement*> marker_draws;
    for (const auto& art_element : art_elements) {
        const auto center_x =
            (art_element.left + art_element.right) * 0.5f;
        const auto center_y =
            (art_element.top + art_element.bottom) * 0.5f;
        if (!art_element.visible ||
            art_element.art_id != "ControlPanel.0" ||
            art_element.right <= art_element.left ||
            art_element.bottom <= art_element.top ||
            !PointInsideRect(
                center_x,
                center_y,
                panel_left,
                panel_top,
                panel_right,
                panel_bottom)) {
            continue;
        }
        marker_draws.push_back(&art_element);
    }
    std::sort(
        marker_draws.begin(),
        marker_draws.end(),
        [](const CapturedMenuArtElement* left,
           const CapturedMenuArtElement* right) {
            if (left->top != right->top) {
                return left->top < right->top;
            }
            if (left->left != right->left) {
                return left->left < right->left;
            }
            return left->draw_order < right->draw_order;
        });

    if (rollout_rows.empty() ||
        rollout_rows.size() != marker_draws.size()) {
        Log(
            "Debug UI settings rollout marker pairing refused ambiguity. "
            "settings=" + HexString(settings_address) +
            " rollout_rows=" + std::to_string(rollout_rows.size()) +
            " marker_draws=" + std::to_string(marker_draws.size()));
        return false;
    }

    for (std::size_t index = 1; index < marker_draws.size(); ++index) {
        const auto* previous = marker_draws[index - 1];
        const auto* current = marker_draws[index];
        if (previous->left == current->left &&
            previous->top == current->top &&
            previous->right == current->right &&
            previous->bottom == current->bottom) {
            Log(
                "Debug UI settings rollout marker pairing refused duplicate "
                "live geometry. settings=" + HexString(settings_address));
            return false;
        }
    }

    const auto original_size = render_elements->size();
    for (std::size_t index = 0; index < rollout_rows.size(); ++index) {
        const auto& row = rollout_rows[index];
        const auto* marker = marker_draws[index];

        OverlayRenderElement element;
        element.surface_id = "settings";
        element.surface_title = std::string(surface_title);
        element.label = row.label;
        element.action_id = ResolveConfiguredUiActionId(
            "settings",
            row.label);
        if (element.action_id.empty()) {
            element.surface_id = "settings.control";
        }
        element.source_object_ptr = row.control_address;
        element.surface_object_ptr = settings_address;
        element.show_label = true;
        element.left = marker->left;
        element.top = marker->top;
        element.right = marker->right;
        element.bottom = marker->bottom;
        render_elements->push_back(std::move(element));
    }

    Log(
        "Debug UI settings rollout rows paired with machine-measured live "
        "affordances. settings=" + HexString(settings_address) +
        " paired=" +
        std::to_string(render_elements->size() - original_size));
    return true;
}

std::vector<OverlayRenderElement> TryBuildControlsOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<ObservedUiElement>& exact_control_elements,
    const std::vector<CapturedMenuArtElement>& art_elements) {
    (void)exact_control_elements;
    (void)art_elements;

    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return {};
    }

    uintptr_t settings_address = 0;
    if (!TryReadTrackedSettingsRender(&settings_address) ||
        settings_address == 0) {
        return {};
    }
    const auto& cache_state = GetSettingsFamilyOverlayArtCacheState();
    if (
        ResolveSettingsRolloutPageForCapture(*config, settings_address) !=
            SettingsRolloutPageState::Controls ||
        cache_state.controls.settings_address != settings_address ||
        cache_state.controls.elements.empty()
    ) {
        return {};
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSettingsPanelRect(*config, settings_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return {};
    }

    uintptr_t customize_owner_control = 0;
    uintptr_t rollout_child_control = 0;
    std::uint8_t rollout_child_enabled = 0xff;
    if (!TryIsCustomizeKeyboardRolloutExpanded(
            *config,
            settings_address,
            &customize_owner_control,
            &rollout_child_control,
            &rollout_child_enabled)) {
        return {};
    }

    const auto* controls_surface = FindUiSurfaceDefinition("controls");
    if (controls_surface == nullptr || controls_surface->action_ids.empty()) {
        return {};
    }

    float customize_label_bottom = panel_top + 96.0f;
    const auto normalized_customize_label =
        NormalizeSemanticUiToken("CUSTOMIZE KEYBOARD");
    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "settings" || element.label.empty()) {
            continue;
        }

        if (NormalizeSemanticUiToken(element.label) != normalized_customize_label) {
            continue;
        }

        customize_label_bottom = (std::max)(customize_label_bottom, element.max_y);
    }

    const auto title = controls_surface->title.empty() ? std::string("Wizard Controls") : controls_surface->title;
    const auto content_left = panel_left + (panel_right - panel_left) * 0.20f;
    const auto content_right = panel_right - (panel_right - panel_left) * 0.12f;
    const auto content_top =
        (std::max)(panel_top + 120.0f, (std::min)(panel_bottom - 60.0f, customize_label_bottom + 28.0f));
    const auto content_bottom = panel_bottom - 36.0f;
    constexpr float kControlsRowHeight = 20.0f;
    constexpr float kControlsRowStep = 22.0f;

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(controls_surface->action_ids.size() + 2);

    OverlayRenderElement panel;
    panel.surface_id = "controls.panel";
    panel.surface_title = title;
    panel.label = title;
    panel.source_object_ptr = customize_owner_control;
    panel.surface_object_ptr = settings_address;
    panel.show_label = false;
    panel.left = panel_left;
    panel.top = panel_top;
    panel.right = panel_right;
    panel.bottom = panel_bottom;
    render_elements.push_back(panel);

    std::size_t rendered_action_count = 0;
    for (std::size_t index = 0; index < controls_surface->action_ids.size(); ++index) {
        const auto* action_definition = FindUiActionDefinition(controls_surface->action_ids[index]);
        if (action_definition == nullptr || action_definition->label.empty()) {
            continue;
        }

        const auto row_top = content_top + kControlsRowStep * static_cast<float>(rendered_action_count);
        const auto row_bottom = row_top + kControlsRowHeight;
        if (row_bottom > content_bottom) {
            break;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = "controls.text";
        render_element.surface_title = title;
        render_element.label = action_definition->label;
        render_element.source_object_ptr = customize_owner_control;
        render_element.surface_object_ptr = settings_address;
        render_element.show_label = true;
        render_element.left = content_left;
        render_element.top = row_top;
        render_element.right = content_right;
        render_element.bottom = row_bottom;
        render_elements.push_back(std::move(render_element));
        ++rendered_action_count;
    }

    float back_left = 0.0f;
    float back_top = 0.0f;
    float back_right = 0.0f;
    float back_bottom = 0.0f;
    uintptr_t back_button_address = 0;
    (void)TryGetSettingsDoneButtonAddress(
        *config,
        settings_address,
        &back_button_address);
    if (!TryReadSettingsDoneButtonRect(
            *config,
            settings_address,
            &back_left,
            &back_top,
            &back_right,
            &back_bottom)) {
        return {};
    }

    OverlayRenderElement back_button;
    back_button.surface_id = "controls";
    back_button.surface_title = title;
    back_button.label = "BACK";
    back_button.action_id = ResolveConfiguredUiActionId(
        "controls",
        back_button.label);
    if (back_button.action_id.empty()) {
        return {};
    }
    back_button.source_object_ptr = back_button_address;
    back_button.surface_object_ptr = settings_address;
    back_button.show_label = true;
    back_button.left = back_left;
    back_button.top = back_top;
    back_button.right = back_right;
    back_button.bottom = back_bottom;
    render_elements.push_back(std::move(back_button));

    static int s_controls_surface_logs_remaining = 8;
    if (s_controls_surface_logs_remaining > 0) {
        --s_controls_surface_logs_remaining;
        Log(
            "Debug UI synthesized controls surface from the expanded Customize Keyboard rollout. settings=" +
            HexString(settings_address) +
            " owner=" + HexString(customize_owner_control) +
            " rollout_child=" + HexString(rollout_child_control) +
            " rollout_child_35=" + std::to_string(rollout_child_enabled) +
            " actions=" + std::to_string(rendered_action_count) + "/" +
            std::to_string(controls_surface->action_ids.size()));
    }

    return render_elements;
}

std::vector<OverlayRenderElement> TryBuildSettingsOverlayRenderElements(
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<ObservedUiElement>& exact_control_elements,
    const std::vector<CapturedMenuArtElement>& art_elements) {
    const auto* config = TryGetDebugUiOverlayConfig();
    if (config == nullptr) {
        return {};
    }

    uintptr_t settings_address = 0;
    if (!HasCurrentSettingsPanelArt(art_elements) ||
        !TryReadTrackedSettingsRender(&settings_address)) {
        return {};
    }

    if (
        ResolveSettingsRolloutPageForCapture(*config, settings_address) !=
        SettingsRolloutPageState::Settings
    ) {
        return {};
    }

    float panel_left = 0.0f;
    float panel_top = 0.0f;
    float panel_right = 0.0f;
    float panel_bottom = 0.0f;
    if (!TryReadSettingsPanelRect(*config, settings_address, &panel_left, &panel_top, &panel_right, &panel_bottom)) {
        return {};
    }

    LogSettingsEmbeddedControlProbe(
        *config,
        settings_address,
        panel_left,
        panel_top,
        panel_right,
        panel_bottom,
        exact_text_elements);

    std::vector<ObservedUiElement> settings_control_elements;
    settings_control_elements.reserve(exact_control_elements.size() + 16);
    for (const auto& exact_control_element : exact_control_elements) {
        if (exact_control_element.surface_id == "settings" || exact_control_element.surface_id == "settings.panel") {
            settings_control_elements.push_back(exact_control_element);
        }
    }

    std::vector<uintptr_t> live_settings_controls;
    if (TryReadSettingsActionableControlPointers(*config, settings_address, &live_settings_controls)) {
        static int s_settings_control_list_logs_remaining = 48;
        for (const auto control_address : live_settings_controls) {
            if (control_address == 0) {
                continue;
            }

            const auto already_recorded = std::any_of(
                settings_control_elements.begin(),
                settings_control_elements.end(),
                [&](const ObservedUiElement& element) {
                    return element.surface_id == "settings" && element.object_ptr == control_address;
                });
            if (already_recorded) {
                continue;
            }

            float left = 0.0f;
            float top = 0.0f;
            float right = 0.0f;
            float bottom = 0.0f;
            if (!TryReadResolvedSettingsOwnedRect(
                    *config,
                    settings_address,
                    control_address,
                    &left,
                    &top,
                    &right,
                    &bottom)) {
                continue;
            }

            std::string label = ResolveSettingsControlLabel(*config, control_address);
            if (label.empty()) {
                (void)TryReadCachedObjectLabel(control_address, &label);
            }

            uintptr_t vftable = 0;
            (void)TryReadPointerValueDirect(control_address, &vftable);
            std::uint32_t child_count = 0;
            uintptr_t child_list = 0;
            uintptr_t first_child = 0;
            (void)TryReadPlainField(
                reinterpret_cast<const void*>(control_address),
                config->settings_control_child_count_offset,
                &child_count);
            (void)TryReadPointerField(
                reinterpret_cast<const void*>(control_address),
                config->settings_control_child_list_offset,
                &child_list);
            if (child_list != 0) {
                (void)TryReadPointerAt(child_list, &first_child);
            }
            if (s_settings_control_list_logs_remaining > 0) {
                --s_settings_control_list_logs_remaining;
                Log(
                    "Debug UI settings control list entry: settings=" + HexString(settings_address) +
                    " control=" + HexString(control_address) +
                    " vftable=" + HexString(vftable) +
                    " child_count=" + std::to_string(child_count) +
                    " child_list=" + HexString(child_list) +
                    " first_child=" + HexString(first_child) +
                    " left=" + std::to_string(left) +
                    " top=" + std::to_string(top) +
                    " right=" + std::to_string(right) +
                    " bottom=" + std::to_string(bottom) +
                    " label=" + SanitizeDebugLogLabel(label));
            }

            static int s_settings_control_child_logs_remaining = 128;
            if (s_settings_control_child_logs_remaining > 0) {
                std::vector<uintptr_t> child_controls;
                if (TryReadSettingsControlChildPointers(*config, control_address, &child_controls)) {
                    for (std::size_t child_index = 0;
                         child_index < child_controls.size() && s_settings_control_child_logs_remaining > 0;
                         ++child_index) {
                        const auto child_control = child_controls[child_index];
                        if (child_control == 0) {
                            continue;
                        }

                        --s_settings_control_child_logs_remaining;
                        uintptr_t child_vftable = 0;
                        (void)TryReadPointerValueDirect(child_control, &child_vftable);

                        std::string child_label = ResolveSettingsControlLabel(*config, child_control);
                        if (child_label.empty()) {
                            (void)TryReadCachedObjectLabel(child_control, &child_label);
                        }

                        float child_left = 0.0f;
                        float child_top = 0.0f;
                        float child_right = 0.0f;
                        float child_bottom = 0.0f;
                        const auto has_child_rect = TryReadResolvedSettingsOwnedRect(
                            *config,
                            settings_address,
                            child_control,
                            &child_left,
                            &child_top,
                            &child_right,
                            &child_bottom);

                        Log(
                            "Debug UI settings control list child: settings=" + HexString(settings_address) +
                            " owner=" + HexString(control_address) +
                            " child_index=" + std::to_string(child_index) +
                            " control=" + HexString(child_control) +
                            " vftable=" + HexString(child_vftable) +
                            " has_rect=" + std::string(has_child_rect ? "1" : "0") +
                            " left=" + std::to_string(child_left) +
                            " top=" + std::to_string(child_top) +
                            " right=" + std::to_string(child_right) +
                            " bottom=" + std::to_string(child_bottom) +
                            " label=" + SanitizeDebugLogLabel(child_label));
                    }
                }
            }

            ObservedUiElement control_element;
            control_element.surface_id = "settings";
            control_element.surface_title = "Game Settings";
            control_element.object_ptr = control_address;
            control_element.min_x = left;
            control_element.min_y = top;
            control_element.max_x = right;
            control_element.max_y = bottom;
            control_element.sample_count = 1;
            control_element.label = std::move(label);
            settings_control_elements.push_back(std::move(control_element));
        }
    }

    const auto surface_title = ResolveSettingsSurfaceTitle(
        *config,
        panel_left,
        panel_top,
        panel_right,
        panel_bottom,
        exact_text_elements);

    OverlayRenderElement panel;
    panel.surface_id = "settings.panel";
    panel.surface_title = surface_title;
    panel.label = surface_title;
    panel.source_object_ptr = settings_address;
    panel.show_label = false;
    panel.left = panel_left;
    panel.top = panel_top;
    panel.right = panel_right;
    panel.bottom = panel_bottom;

    std::map<uintptr_t, std::string> mapped_control_labels;
    for (const auto& exact_control_element : settings_control_elements) {
        if (exact_control_element.surface_id != "settings" || exact_control_element.object_ptr == 0) {
            continue;
        }

        mapped_control_labels.emplace(
            exact_control_element.object_ptr,
            ResolveBestSettingsControlLabel(
                *config,
                exact_control_element.object_ptr,
                exact_control_element.min_x,
                exact_control_element.min_y,
                exact_control_element.max_x,
                exact_control_element.max_y,
                exact_text_elements));
    }

    std::vector<OverlayRenderElement> render_elements;
    render_elements.reserve(exact_control_elements.size() + exact_text_elements.size() + 1);
    render_elements.push_back(panel);

    (void)TryBuildSettingsRolloutMarkerElements(
        *config,
        settings_address,
        surface_title,
        panel_left,
        panel_top,
        panel_right,
        panel_bottom,
        art_elements,
        &render_elements);

    float done_left = 0.0f;
    float done_top = 0.0f;
    float done_right = 0.0f;
    float done_bottom = 0.0f;
    uintptr_t done_button_address = 0;
    (void)TryGetSettingsDoneButtonAddress(*config, settings_address, &done_button_address);
    if (TryReadSettingsDoneButtonRect(*config, settings_address, &done_left, &done_top, &done_right, &done_bottom)) {
        OverlayRenderElement done_button;
        done_button.surface_id = "settings";
        done_button.surface_title = surface_title;
        done_button.label = "DONE";
        done_button.action_id = ResolveConfiguredUiActionId("settings", done_button.label);
        done_button.source_object_ptr = done_button_address;
        done_button.surface_object_ptr = settings_address;
        done_button.left = done_left;
        done_button.top = done_top;
        done_button.right = done_right;
        done_button.bottom = done_bottom;
        done_button.show_label = !done_button.label.empty();
        render_elements.push_back(std::move(done_button));
    }

    std::set<uintptr_t> consumed_control_addresses;
    if (done_button_address != 0) {
        consumed_control_addresses.insert(done_button_address);
    }
    for (const auto& render_element : render_elements) {
        if (render_element.surface_id == "settings" &&
            !render_element.action_id.empty() &&
            render_element.source_object_ptr != 0) {
            consumed_control_addresses.insert(
                render_element.source_object_ptr);
        }
    }

    for (const auto& text_element : exact_text_elements) {
        if (text_element.surface_id != "settings" || text_element.label.empty()) {
            continue;
        }

        const auto normalized_caller_address = NormalizeObservedCodeAddress(text_element.caller_address);
        if (IsTrustedSettingsPanelTitleCaller(*config, normalized_caller_address)) {
            continue;
        }

        const auto trusted_section_header = IsTrustedSettingsSectionHeaderCaller(*config, normalized_caller_address);
        const auto trusted_control_label = IsTrustedSettingsControlLabelCaller(*config, normalized_caller_address);
        if (!trusted_section_header && !trusted_control_label) {
            continue;
        }

        const auto action_id = ResolveConfiguredUiActionId("settings", text_element.label);
        const auto actionable = !action_id.empty() && text_element.object_ptr != 0;
        const auto target_surface_id = actionable ? "settings" : (trusted_section_header ? "settings.section" : "settings.text");
        const auto* action_definition = actionable ? FindUiActionDefinition(action_id) : nullptr;

        uintptr_t resolved_action_owner_control = 0;
        uintptr_t resolved_action_child_control = 0;
        std::size_t resolved_action_match_count = 0;
        bool resolved_action_matched_container_only = false;
        if (actionable) {
            (void)TryResolveSettingsActionableLabelControl(
                *config,
                settings_address,
                text_element.object_ptr,
                text_element.label,
                &resolved_action_owner_control,
                &resolved_action_child_control,
                &resolved_action_match_count,
                &resolved_action_matched_container_only);
        }

        const auto already_added = std::any_of(
            render_elements.begin(),
            render_elements.end(),
            [&](const OverlayRenderElement& render_element) {
                if (render_element.source_object_ptr != 0 && render_element.source_object_ptr == text_element.object_ptr &&
                    render_element.surface_id == target_surface_id) {
                    return true;
                }

                return actionable && !render_element.action_id.empty() && render_element.action_id == action_id &&
                       render_element.surface_id == "settings";
            });
        if (already_added) {
            continue;
        }

        const auto* matched_control = actionable
            ? FindBestSettingsExactControlForText(
                  *config,
                  text_element,
                  settings_control_elements,
                  mapped_control_labels,
                  consumed_control_addresses)
            : nullptr;
        if (matched_control == nullptr && actionable) {
            matched_control = FindSettingsControlByLabel(
                text_element,
                settings_control_elements,
                consumed_control_addresses);
        }

        const auto use_matched_control_geometry =
            matched_control != nullptr &&
            (matched_control->max_x - matched_control->min_x) < (panel_right - panel_left) * 0.95f &&
            (matched_control->max_y - matched_control->min_y) < (panel_bottom - panel_top) * 0.95f;

        uintptr_t actionable_source_object = text_element.object_ptr;
        if (actionable && action_definition != nullptr &&
            (action_definition->dispatch_kind == "control_child" ||
             action_definition->dispatch_kind == "control_child_callback_owner")) {
            if (resolved_action_child_control != 0) {
                actionable_source_object = resolved_action_child_control;
            } else if (resolved_action_owner_control != 0) {
                actionable_source_object = resolved_action_owner_control;
            }
        } else if (matched_control != nullptr) {
            actionable_source_object = matched_control->object_ptr;
        } else if (actionable && resolved_action_child_control != 0) {
            actionable_source_object = resolved_action_child_control;
        }

        OverlayRenderElement render_element;
        render_element.surface_id = target_surface_id;
        render_element.surface_title = surface_title;
        render_element.label = text_element.label;
        render_element.action_id = actionable ? action_id : std::string{};
        render_element.source_object_ptr = actionable_source_object;
        render_element.surface_object_ptr = settings_address;
        render_element.show_label = true;
        render_element.left = use_matched_control_geometry ? matched_control->min_x : text_element.min_x;
        render_element.top = use_matched_control_geometry ? matched_control->min_y : text_element.min_y;
        render_element.right = use_matched_control_geometry ? matched_control->max_x : text_element.max_x;
        render_element.bottom = use_matched_control_geometry ? matched_control->max_y : text_element.max_y;
        render_elements.push_back(std::move(render_element));
        if (matched_control != nullptr) {
            consumed_control_addresses.insert(matched_control->object_ptr);
        }

        static int s_settings_action_owner_logs_remaining = 24;
        if (actionable && s_settings_action_owner_logs_remaining > 0) {
            --s_settings_action_owner_logs_remaining;
            uintptr_t callback_owner = 0;
            uintptr_t callback_owner_vftable = 0;
            uintptr_t callback_owner_slot_cc = 0;
            const auto callback_source_object =
                resolved_action_owner_control != 0 ? resolved_action_owner_control : actionable_source_object;
            if (callback_source_object != 0 &&
                TryReadPointerValueDirect(
                    callback_source_object + config->settings_control_callback_owner_offset,
                    &callback_owner) &&
                callback_owner != 0) {
                (void)TryReadPointerValueDirect(callback_owner, &callback_owner_vftable);
                if (callback_owner_vftable != 0) {
                    (void)TryReadPointerValueDirect(
                        callback_owner_vftable + config->ui_owner_control_action_vtable_byte_offset,
                        &callback_owner_slot_cc);
                }
            }
            Log(
                "Debug UI settings action mapped: settings=" + HexString(settings_address) +
                " label=" + SanitizeDebugLogLabel(text_element.label) +
                " action=" + SanitizeDebugLogLabel(action_id) +
                " source=" + HexString(actionable_source_object) +
                " owner=" + HexString(resolved_action_owner_control) +
                " child=" + HexString(resolved_action_child_control) +
                " callback_owner=" + HexString(callback_owner) +
                " callback_owner_vftable=" + HexString(callback_owner_vftable) +
                " callback_owner_slot_cc=" + HexString(callback_owner_slot_cc) +
                " matches=" + std::to_string(resolved_action_match_count) +
                " container_only=" + std::to_string(resolved_action_matched_container_only ? 1 : 0));
        }
        if (action_id == "settings.controls") {
            MaybeLogSettingsControlsLiveState(
                "overlay_bbox_mapped",
                settings_address,
                resolved_action_owner_control,
                resolved_action_child_control,
                text_element.label,
                render_elements.back().left,
                render_elements.back().top,
                render_elements.back().right,
                render_elements.back().bottom);
        }
    }

    static int s_settings_exact_control_mapping_logs_remaining = 24;
    for (const auto& exact_control_element : settings_control_elements) {
        if (exact_control_element.surface_id != "settings" || exact_control_element.object_ptr == 0) {
            continue;
        }

        if (consumed_control_addresses.find(exact_control_element.object_ptr) != consumed_control_addresses.end()) {
            continue;
        }

        const auto overlaps_done =
            done_left < done_right && done_top < done_bottom &&
            exact_control_element.min_x < done_right &&
            exact_control_element.max_x > done_left &&
            exact_control_element.min_y < done_bottom &&
            exact_control_element.max_y > done_top;
        if (overlaps_done) {
            continue;
        }

        OverlayRenderElement render_element;
        render_element.surface_title = surface_title;
        if (const auto label_it = mapped_control_labels.find(exact_control_element.object_ptr);
            label_it != mapped_control_labels.end()) {
            render_element.label = label_it->second;
        }

        render_element.action_id.clear();
        render_element.surface_id = "settings.control";
        if (s_settings_exact_control_mapping_logs_remaining > 0) {
            --s_settings_exact_control_mapping_logs_remaining;
            Log(
                "Debug UI settings exact control mapped: settings=" + HexString(settings_address) +
                " control=" + HexString(exact_control_element.object_ptr) +
                " left=" + std::to_string(exact_control_element.min_x) +
                " top=" + std::to_string(exact_control_element.min_y) +
                " right=" + std::to_string(exact_control_element.max_x) +
                " bottom=" + std::to_string(exact_control_element.max_y) +
                " label=" + SanitizeDebugLogLabel(render_element.label) +
                " action=" + SanitizeDebugLogLabel(render_element.action_id));
        }

        render_element.source_object_ptr = exact_control_element.object_ptr;
        render_element.surface_object_ptr = settings_address;
        render_element.left = exact_control_element.min_x;
        render_element.top = exact_control_element.min_y;
        render_element.right = exact_control_element.max_x;
        render_element.bottom = exact_control_element.max_y;
        render_element.show_label = !render_element.label.empty();
        render_elements.push_back(std::move(render_element));
    }

    if (render_elements.size() <= 1) {
        return {};
    }

    std::sort(render_elements.begin(), render_elements.end(), [](const OverlayRenderElement& left, const OverlayRenderElement& right) {
        if (std::fabs(left.top - right.top) > 1.0f) {
            return left.top < right.top;
        }
        return left.left < right.left;
    });
    return render_elements;
}
