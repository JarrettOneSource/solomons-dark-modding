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
    ULONGLONG transition_started_at = 0;
    SettingsRolloutPageState last_page =
        SettingsRolloutPageState::Unknown;
    std::vector<CapturedMenuArtElement> settings_underlay;
};

SettingsFamilyOverlayArtCacheState& GetSettingsFamilyOverlayArtCacheState() {
    static SettingsFamilyOverlayArtCacheState state;
    return state;
}

void MarkSettingsFamilyPageTransitionPending(
    SettingsFamilyOverlayArtCacheState* state) {
    if (state != nullptr && state->transition_started_at == 0) {
        state->transition_started_at = GetTickCount64();
    }
}

bool ShouldRetainSettingsTrackingAcrossMainMenuFallback() {
    const auto& state = GetSettingsFamilyOverlayArtCacheState();
    if (state.settings_address == 0 || state.transition_started_at == 0) {
        return false;
    }
    const auto now = GetTickCount64();
    return now >= state.transition_started_at &&
        now - state.transition_started_at <= kTrackedSettingsMaximumIdleMs;
}

void LogSettingsFamilyTransitionArtFrame(
    SettingsRolloutPageState page,
    SettingsRolloutPageState last_page,
    const std::vector<CapturedMenuArtElement>& current_elements,
    const std::vector<CapturedMenuArtElement>& settings_underlay) {
    static int s_logs_remaining = 12;
    if (s_logs_remaining <= 0) {
        return;
    }
    --s_logs_remaining;
    std::ostringstream message;
    message << "Debug UI settings-family transition art frame: page="
            << static_cast<int>(page)
            << " last_page=" << static_cast<int>(last_page)
            << " current=" << current_elements.size()
            << " underlay=" << settings_underlay.size();
    for (const auto& element : current_elements) {
        message << " |" << element.art_id
                << '@' << HexString(element.source_object_ptr)
                << '@' << element.draw_order
                << '@' << std::hexfloat
                << element.left << ',' << element.top << ','
                << element.right << ',' << element.bottom;
    }
    Log(message.str());
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
        LogSettingsFamilyTransitionArtFrame(
            SettingsRolloutPageState::Unknown,
            cache_state.last_page,
            current_elements,
            cache_state.settings_underlay);
        if (cache_state.last_page != SettingsRolloutPageState::Unknown) {
            MarkSettingsFamilyPageTransitionPending(&cache_state);
        }
        const auto now = GetTickCount64();
        if (cache_state.transition_started_at != 0 &&
            now - cache_state.transition_started_at >
                kTrackedSettingsMaximumIdleMs) {
            Log("Debug UI settings-family cached page retired after bounded unresolved transition.");
            clear_caches();
            return current_elements;
        }
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
    if (cache_state.last_page != page_observation.page) {
        LogSettingsFamilyTransitionArtFrame(
            page_observation.page,
            cache_state.last_page,
            current_elements,
            cache_state.settings_underlay);
    }
    std::vector<CapturedMenuArtElement> measured_overlay;
    if (page_observation.page == SettingsRolloutPageState::Settings &&
        TryExtractSettingsFamilyOverlayArt(
            current_elements,
            &measured_overlay)) {
        active_cache->settings_address = settings_address;
        active_cache->elements = std::move(measured_overlay);
        cache_state.transition = CachedSettingsFamilyOverlayArt{};
        cache_state.last_page = page_observation.page;
        cache_state.transition_started_at = 0;
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
    if (page_observation.page == SettingsRolloutPageState::Controls &&
        (active_cache->settings_address != settings_address ||
         active_cache->elements.empty())) {
        // The Controls modal is painted by its own nested loop.  Its native
        // rollout root reaches the unique local origin even when the
        // one-shot Sprite draw never enters this frame's art cache.  That
        // machine state is the page identity; an unrelated draw cache must
        // not veto it.
        cache_state.last_page = page_observation.page;
        cache_state.transition_started_at = 0;
        return current_elements;
    }
    cache_state.last_page = page_observation.page;
    cache_state.transition_started_at = 0;
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

