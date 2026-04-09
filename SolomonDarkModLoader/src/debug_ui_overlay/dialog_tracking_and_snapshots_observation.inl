const SurfaceObservationRange* MatchSurfaceRange(uintptr_t caller_address) {
    const SurfaceObservationRange* best_match = nullptr;
    uintptr_t best_distance = (std::numeric_limits<uintptr_t>::max)();

    for (const auto& range : g_debug_ui_overlay_state.surface_ranges) {
        if (caller_address < range.start || caller_address >= range.end) {
            continue;
        }

        const auto distance = caller_address - range.start;
        if (best_match == nullptr || distance < best_distance) {
            best_match = &range;
            best_distance = distance;
        }
    }

    return best_match;
}

std::optional<SurfaceStackMatch> TryResolveSurfaceFromCallStack(std::size_t stack_scan_slots) {
#if defined(_MSC_VER) && defined(_M_IX86)
    if (stack_scan_slots == 0) {
        return std::nullopt;
    }

    auto* stack_cursor = reinterpret_cast<const uintptr_t*>(_AddressOfReturnAddress());
    if (stack_cursor == nullptr) {
        return std::nullopt;
    }

    for (std::size_t stack_slot = 0; stack_slot < stack_scan_slots; ++stack_slot) {
        const auto return_address = stack_cursor[stack_slot];
        const auto* matched_surface = MatchSurfaceRange(return_address);
        if (matched_surface == nullptr) {
            continue;
        }

        SurfaceStackMatch match;
        match.range = matched_surface;
        match.return_address = return_address;
        match.stack_slot = stack_slot;
        return match;
    }
#else
    (void)stack_scan_slots;
#endif

    return std::nullopt;
}

std::optional<SurfaceStackMatch> TryResolveSurfaceForDrawCall(uintptr_t caller_address, std::size_t stack_scan_slots) {
    if (auto stack_match = TryResolveSurfaceFromCallStack(stack_scan_slots); stack_match.has_value()) {
        return stack_match;
    }

    if (const auto* matched_surface = MatchSurfaceRange(caller_address); matched_surface != nullptr) {
        SurfaceStackMatch match;
        match.range = matched_surface;
        match.return_address = caller_address;
        match.stack_slot = 0;
        return match;
    }

    return std::nullopt;
}

std::vector<std::string> BuildSurfaceActionLabels(const UiSurfaceDefinition& surface) {
    std::vector<std::string> labels;
    labels.reserve(surface.action_ids.size());

    for (const auto& action_id : surface.action_ids) {
        const auto* action = FindUiActionDefinition(action_id);
        if (action == nullptr || action->label.empty()) {
            continue;
        }

        labels.push_back(action->label);
    }

    return labels;
}

void AddSurfaceRange(
    std::vector<SurfaceObservationRange>* ranges,
    const UiSurfaceDefinition& surface,
    uintptr_t start,
    size_t slop) {
    if (ranges == nullptr || start == 0 || slop == 0) {
        return;
    }

    const auto resolved_start = ProcessMemory::Instance().ResolveGameAddressOrZero(start);
    if (resolved_start == 0) {
        return;
    }

    const auto end = resolved_start + slop;
    for (const auto& existing : *ranges) {
        if (existing.surface_id == surface.id && existing.start == resolved_start && existing.end == end) {
            return;
        }
    }

    SurfaceObservationRange range;
    range.surface_id = surface.id;
    range.surface_title = surface.title;
    range.start = resolved_start;
    range.end = end;
    range.ordered_labels = BuildSurfaceActionLabels(surface);
    ranges->push_back(std::move(range));
}

std::vector<SurfaceObservationRange> BuildSurfaceRanges(const BinaryLayout& binary_layout, size_t slop) {
    std::vector<SurfaceObservationRange> ranges;

    for (const auto& surface : binary_layout.ui_surfaces) {
        for (const auto& entry : surface.addresses) {
            AddSurfaceRange(&ranges, surface, entry.second, slop);
        }

        for (const auto& action_id : surface.action_ids) {
            const auto* action = FindUiActionDefinition(action_id);
            if (action == nullptr) {
                continue;
            }

            for (const auto& entry : action->addresses) {
                AddSurfaceRange(&ranges, surface, entry.second, slop);
            }
        }
    }

    std::sort(ranges.begin(), ranges.end(), [](const SurfaceObservationRange& left, const SurfaceObservationRange& right) {
        if (left.start != right.start) {
            return left.start < right.start;
        }

        return left.surface_id < right.surface_id;
    });
    return ranges;
}

std::uint32_t QuantizeCoordinate(float value) {
    const auto rounded = std::lround(value * 4.0f);
    if (rounded < 0) {
        return 0;
    }

    return static_cast<std::uint32_t>(rounded);
}

uintptr_t BuildObservationIdentityKey(void* identity_source, float x, float y, uintptr_t caller_address, bool prefer_object_identity) {
    const auto object_address = reinterpret_cast<uintptr_t>(identity_source);
    if (prefer_object_identity && object_address != 0) {
        return object_address;
    }

    const auto x_bits = static_cast<uintptr_t>(QuantizeCoordinate(x));
    const auto y_bits = static_cast<uintptr_t>(QuantizeCoordinate(y));
    return (caller_address << 1) ^ (x_bits << 16) ^ y_bits;
}

std::optional<ObservedUiElement> ObserveUiDrawCall(
    const SurfaceStackMatch& surface_match,
    void* identity_source,
    void* label_source,
    float x,
    float y,
    uintptr_t caller_address) {
    if (surface_match.range == nullptr) {
        return std::nullopt;
    }

    if (!std::isfinite(x) || !std::isfinite(y) || x < -4096.0f || y < -4096.0f || x > 32768.0f || y > 32768.0f) {
        return std::nullopt;
    }

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);

    if (g_debug_ui_overlay_state.frame_elements.size() >= g_debug_ui_overlay_state.config.max_tracked_elements_per_frame) {
        return std::nullopt;
    }

    const auto label_source_address = reinterpret_cast<uintptr_t>(label_source);
    std::string label;
    const auto cache_it = g_debug_ui_overlay_state.object_label_cache.find(label_source_address);
    if (cache_it != g_debug_ui_overlay_state.object_label_cache.end()) {
        label = cache_it->second;
    } else {
        if (label_source_address != 0 && TryResolveObjectLabel(label_source_address, &label)) {
            g_debug_ui_overlay_state.object_label_cache.emplace(label_source_address, label);
        }
    }

    const auto object_address =
        BuildObservationIdentityKey(identity_source, x, y, caller_address, !label.empty());

    for (auto& element : g_debug_ui_overlay_state.frame_elements) {
        if (element.object_ptr == object_address && element.surface_id == surface_match.range->surface_id) {
            element.min_x = (std::min)(element.min_x, x);
            element.max_x = (std::max)(element.max_x, x);
            element.min_y = (std::min)(element.min_y, y);
            element.max_y = (std::max)(element.max_y, y);
            ++element.sample_count;
            if (element.label.empty() && !label.empty()) {
                element.label = std::move(label);
            }
            return element;
        }
    }

    ObservedUiElement element;
    element.surface_id = surface_match.range->surface_id;
    element.surface_title = surface_match.range->surface_title;
    element.object_ptr = object_address;
    element.label_source_ptr = label_source_address;
    element.caller_address = caller_address;
    element.surface_return_address = surface_match.return_address;
    element.stack_slot = surface_match.stack_slot;
    element.min_x = x;
    element.max_x = x;
    element.min_y = y;
    element.max_y = y;
    element.sample_count = 1;
    element.label = std::move(label);
    g_debug_ui_overlay_state.frame_elements.push_back(std::move(element));

    if (!g_debug_ui_overlay_state.first_stack_match_logged) {
        g_debug_ui_overlay_state.first_stack_match_logged = true;
        Log(
            "Debug UI overlay resolved its first active surface from the stack. surface=" +
            g_debug_ui_overlay_state.frame_elements.back().surface_id + " slot=" +
            std::to_string(g_debug_ui_overlay_state.frame_elements.back().stack_slot) + " return=" +
            HexString(g_debug_ui_overlay_state.frame_elements.back().surface_return_address));
    }

    if (!g_debug_ui_overlay_state.first_candidate_logged) {
        g_debug_ui_overlay_state.first_candidate_logged = true;
        const auto& first_element = g_debug_ui_overlay_state.frame_elements.back();
        Log(
            "Debug UI overlay matched its first UI draw candidate. surface=" + first_element.surface_id +
            " caller=" + HexString(first_element.caller_address));
    }

    return g_debug_ui_overlay_state.frame_elements.back();
}

std::string GetOverlayLabel(const OverlayRenderElement& element) {
    if (!element.label.empty()) {
        return element.label;
    }

    if (!element.surface_title.empty()) {
        return element.surface_title;
    }

    return element.surface_id;
}

std::string GetOverlaySurfaceRootId(std::string_view surface_id) {
    const auto separator_index = surface_id.find('.');
    if (separator_index == std::string_view::npos) {
        return std::string(surface_id);
    }

    return std::string(surface_id.substr(0, separator_index));
}

std::string BuildDebugUiSnapshotLabelSummary(const DebugUiSurfaceSnapshot& snapshot) {
    std::string summary;
    auto visible_index = 0;
    for (const auto& element : snapshot.elements) {
        if (element.label.empty() && element.action_id.empty()) {
            continue;
        }

        ++visible_index;
        if (!summary.empty()) {
            summary += " || ";
        }

        summary += std::to_string(visible_index) + ":" + SanitizeDebugLogLabel(element.label);
        if (!element.action_id.empty()) {
            summary += "{" + SanitizeDebugLogLabel(element.action_id) + "}";
        }
    }

    return summary;
}

