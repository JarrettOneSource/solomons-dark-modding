bool HasMeaningfulDebugUiSnapshotChange(
    const DebugUiSurfaceSnapshot& previous,
    const DebugUiSurfaceSnapshot& next) {
    if (!IsUsableDebugUiSurfaceSnapshot(previous)) {
        return true;
    }

    if (previous.surface_id != next.surface_id ||
        previous.surface_title != next.surface_title ||
        previous.elements.size() != next.elements.size()) {
        return true;
    }

    for (std::size_t index = 0; index < next.elements.size(); ++index) {
        const auto& previous_element = previous.elements[index];
        const auto& next_element = next.elements[index];
        if (previous_element.surface_id != next_element.surface_id ||
            previous_element.label != next_element.label ||
            previous_element.action_id != next_element.action_id ||
            previous_element.show_label != next_element.show_label) {
            return true;
        }
    }

    return false;
}

void StoreLatestSurfaceSnapshotUnlocked(
    DebugUiOverlayState* state,
    const std::vector<OverlayRenderElement>& render_elements) {
    if (state == nullptr) {
        return;
    }

    if (render_elements.empty()) {
        if (!IsUsableDebugUiSurfaceSnapshot(state->latest_surface_snapshot)) {
            state->latest_surface_snapshot = DebugUiSurfaceSnapshot{};
        }
        return;
    }

    auto snapshot = DebugUiSurfaceSnapshot{};
    snapshot.captured_at_milliseconds = GetTickCount64();
    snapshot.surface_id = GetOverlaySurfaceRootId(render_elements.front().surface_id);

    for (const auto& render_element : render_elements) {
        if (!render_element.surface_title.empty()) {
            snapshot.surface_title = render_element.surface_title;
            break;
        }
    }
    if (snapshot.surface_title.empty()) {
        snapshot.surface_title = snapshot.surface_id;
    }

    snapshot.elements.reserve(render_elements.size());
    for (const auto& render_element : render_elements) {
        DebugUiSnapshotElement element;
        element.surface_id = render_element.surface_id;
        element.surface_title = render_element.surface_title;
        element.label = render_element.label;
        element.action_id = render_element.action_id;
        element.source_object_ptr = render_element.source_object_ptr;
        element.surface_object_ptr = render_element.surface_object_ptr;
        element.show_label = render_element.show_label;
        element.left = render_element.left;
        element.top = render_element.top;
        element.right = render_element.right;
        element.bottom = render_element.bottom;
        snapshot.elements.push_back(std::move(element));
    }

    if (!HasMeaningfulDebugUiSnapshotChange(state->latest_surface_snapshot, snapshot)) {
        state->latest_surface_snapshot.captured_at_milliseconds = snapshot.captured_at_milliseconds;
        return;
    }

    snapshot.generation = ++state->latest_surface_snapshot_generation;
    Log(
        "Debug UI semantic snapshot update: generation=" + std::to_string(snapshot.generation) +
        " surface=" + snapshot.surface_id + " title=" + SanitizeDebugLogLabel(snapshot.surface_title) +
        " elements=" + std::to_string(snapshot.elements.size()) +
        " labels=" + BuildDebugUiSnapshotLabelSummary(snapshot));

    state->latest_surface_snapshot = std::move(snapshot);
    TryCompleteActiveSemanticUiActionOnSurfaceTransitionUnlocked(state, state->latest_surface_snapshot);
}

void LogOverlayRenderElementsSummary(
    const std::string& surface_name,
    const std::vector<OverlayRenderElement>& render_elements) {
    for (const auto& element : render_elements) {
        Log(
            "Debug UI " + surface_name + " element: label=" + SanitizeDebugLogLabel(GetOverlayLabel(element)) +
            " action=" + SanitizeDebugLogLabel(element.action_id) + " object=" + HexString(element.source_object_ptr) +
            " owner=" + HexString(element.surface_object_ptr) + " left=" + std::to_string(element.left) +
            " top=" + std::to_string(element.top) + " right=" + std::to_string(element.right) +
            " bottom=" + std::to_string(element.bottom));
    }
}

void DrawObservedOverlayElement(IDirect3DDevice9* device, const FontAtlas& atlas, const OverlayRenderElement& element) {
    const auto label = GetOverlayLabel(element);
    const auto label_width = MeasureLabelWidth(atlas, label);
    const auto box_left = element.left;
    const auto box_top = element.top;
    const auto minimum_width = element.show_label ? static_cast<float>(label_width + 6) : 0.0f;
    const auto box_right = (std::max)(element.right, element.left + minimum_width);
    const auto box_bottom = element.bottom;
    DrawRectOutline(device, box_left, box_top, box_right, box_bottom, kBoxColor);

    if (!element.show_label) {
        return;
    }

    const auto label_left = box_left;
    const auto label_top = (std::max)(0.0f, box_top - static_cast<float>(atlas.line_height + 6));
    const auto label_right = label_left + static_cast<float>(label_width + 6);
    const auto label_bottom = label_top + static_cast<float>(atlas.line_height + 4);
    DrawFilledRect(device, label_left, label_top, label_right, label_bottom, kLabelBackgroundColor);
    DrawRectOutline(device, label_left, label_top, label_right, label_bottom, kLabelOutlineColor);
    DrawLabelText(device, atlas, label_left + 3.0f, label_top + 2.0f, label, kLabelTextColor);
}

const SurfaceObservationRange* FindSurfaceRangeById(std::string_view surface_id) {
    for (const auto& range : g_debug_ui_overlay_state.surface_ranges) {
        if (range.surface_id == surface_id) {
            return &range;
        }
    }

    return nullptr;
}

std::vector<OverlayRenderElement> BuildOverlayRenderElements(const std::vector<ObservedUiElement>& elements, const FontAtlas& atlas) {
    std::vector<OverlayRenderElement> render_elements;
    if (elements.empty()) {
        return render_elements;
    }

    std::unordered_map<std::string, std::vector<std::size_t>> grouped_indices;
    grouped_indices.reserve(elements.size());
    for (std::size_t index = 0; index < elements.size(); ++index) {
        grouped_indices[elements[index].surface_id].push_back(index);
    }

    render_elements.reserve(elements.size());

    for (auto& group : grouped_indices) {
        auto indices = std::move(group.second);
        std::sort(indices.begin(), indices.end(), [&](std::size_t left, std::size_t right) {
            const auto& left_element = elements[left];
            const auto& right_element = elements[right];
            if (std::fabs(left_element.min_y - right_element.min_y) > 1.0f) {
                return left_element.min_y < right_element.min_y;
            }
            return left_element.min_x < right_element.min_x;
        });

        const auto* surface_range = FindSurfaceRangeById(group.first);
        std::size_t fallback_index = 0;
        for (const auto index : indices) {
            const auto& observed = elements[index];
            OverlayRenderElement render_element;
            render_element.surface_id = observed.surface_id;
            render_element.surface_title = observed.surface_title;
            render_element.source_object_ptr = observed.object_ptr;
            render_element.label = observed.label;
            if (render_element.label.empty() && surface_range != nullptr && fallback_index < surface_range->ordered_labels.size()) {
                render_element.label = surface_range->ordered_labels[fallback_index];
            }
            if (render_element.label.empty()) {
                ++fallback_index;
                continue;
            }

            const auto label_width = static_cast<float>(MeasureLabelWidth(atlas, render_element.label));
            render_element.left = observed.min_x - 2.0f;
            render_element.top = (std::max)(0.0f, observed.min_y - kOverlayTextVerticalPadding);
            render_element.right = (std::max)(
                observed.max_x + label_width + kOverlayTextHorizontalPadding,
                render_element.left + kOverlayClusterMinimumWidth);
            render_element.bottom = (std::max)(
                render_element.top + static_cast<float>(atlas.line_height + 6),
                observed.max_y + static_cast<float>(atlas.line_height) + kOverlayTextVerticalPadding);
            render_elements.push_back(std::move(render_element));

            ++fallback_index;
        }
    }

    std::sort(render_elements.begin(), render_elements.end(), [](const OverlayRenderElement& left, const OverlayRenderElement& right) {
        if (std::fabs(left.top - right.top) > 1.0f) {
            return left.top < right.top;
        }
        return left.left < right.left;
    });
    return render_elements;
}

std::vector<ObservedUiElement> FilterElementsToDominantSurface(const std::vector<ObservedUiElement>& elements) {
    if (elements.size() <= 1) {
        return elements;
    }

    struct SurfaceScore {
        std::string surface_id;
        std::uint32_t labeled_count = 0;
        std::uint32_t sample_count = 0;
        std::uint32_t element_count = 0;
        std::size_t best_stack_slot = (std::numeric_limits<std::size_t>::max)();
    };

    std::unordered_map<std::string, SurfaceScore> scores;
    scores.reserve(elements.size());
    for (const auto& element : elements) {
        auto& score = scores[element.surface_id];
        score.surface_id = element.surface_id;
        score.sample_count += element.sample_count;
        score.element_count += 1;
        if (!element.label.empty()) {
            score.labeled_count += 1;
        }
        score.best_stack_slot = (std::min)(score.best_stack_slot, element.stack_slot);
    }

    const SurfaceScore* best_score = nullptr;
    for (const auto& [surface_id, score] : scores) {
        (void)surface_id;
        if (best_score == nullptr || score.labeled_count > best_score->labeled_count ||
            (score.labeled_count == best_score->labeled_count && score.sample_count > best_score->sample_count) ||
            (score.labeled_count == best_score->labeled_count && score.sample_count == best_score->sample_count &&
             score.element_count > best_score->element_count) ||
            (score.labeled_count == best_score->labeled_count && score.sample_count == best_score->sample_count &&
             score.element_count == best_score->element_count && score.best_stack_slot < best_score->best_stack_slot)) {
            best_score = &score;
        }
    }

    if (best_score == nullptr) {
        return elements;
    }

    std::vector<ObservedUiElement> filtered;
    filtered.reserve(best_score->element_count);
    for (const auto& element : elements) {
        if (element.surface_id == best_score->surface_id) {
            filtered.push_back(element);
        }
    }
    return filtered;
}

std::string ResolveExactTextRenderLabel(void* string_object, char* text) {
    if (text != nullptr) {
        auto raw_label = TrimAsciiWhitespace(text);
        if (!raw_label.empty()) {
            return raw_label;
        }
    }

    if (string_object != nullptr) {
        std::string string_label;
        if (TryReadStringObject(reinterpret_cast<uintptr_t>(string_object), &string_label)) {
            string_label = TrimAsciiWhitespace(string_label);
            if (!string_label.empty()) {
                return string_label;
            }
        }
    }

    return {};
}
