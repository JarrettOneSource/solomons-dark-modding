// Multiplayer Dampen cannot safely run the stock animation-object routine:
// that routine corrupts the game's shared pointer-list heap with multiple
// wizards.  Render its synchronized cast pulse directly through D3D9 instead.

struct GameplayDampenPresentationRenderItem {
    std::uint64_t owner_participant_id = 0;
    std::uint32_t cast_sequence = 0;
    float center_x = 0.0f;
    float center_y = 0.0f;
    float radius = 0.0f;
    std::uint8_t alpha = 0;
};

std::vector<GameplayDampenPresentationRenderItem>
BuildGameplayDampenPresentationRenderItems(
    IDirect3DDevice9* device,
    const std::vector<ObservedUiElement>& exact_text_elements) {
    constexpr ULONGLONG kPresentationDurationMilliseconds = 900;
    constexpr float kInitialRadius = 18.0f;
    constexpr float kFinalRadius = 96.0f;

    std::vector<DebugUiOverlayState::MultiplayerDampenPresentation> active;
    const auto now = GetTickCount64();
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        auto& presentations =
            g_debug_ui_overlay_state.multiplayer_dampen_presentations;
        presentations.erase(
            std::remove_if(
                presentations.begin(),
                presentations.end(),
                [&](const auto& presentation) {
                    return now - presentation.started_at_milliseconds >=
                           kPresentationDurationMilliseconds;
                }),
            presentations.end());
        active = presentations;
    }
    if (device == nullptr || active.empty()) {
        return {};
    }

    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 || viewport.Height == 0) {
        return {};
    }

    const auto local_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    std::vector<GameplayDampenPresentationRenderItem> items;
    items.reserve(active.size());
    for (const auto& presentation : active) {
        float center_x = 0.0f;
        float center_y = 0.0f;
        if (presentation.owner_participant_id == local_participant_id) {
            center_x = static_cast<float>(viewport.X) +
                static_cast<float>(viewport.Width) * 0.5f;
            center_y = static_cast<float>(viewport.Y) +
                static_cast<float>(viewport.Height) * 0.52f;
        } else {
            const auto nameplate = std::find_if(
                exact_text_elements.begin(),
                exact_text_elements.end(),
                [&](const ObservedUiElement& element) {
                    return element.surface_id == "gameplay_nameplate" &&
                        element.gameplay_participant_id ==
                            presentation.owner_participant_id &&
                        element.sample_count != 0 &&
                        std::isfinite(element.min_x) &&
                        std::isfinite(element.max_x) &&
                        std::isfinite(element.max_y);
                });
            if (nameplate == exact_text_elements.end()) {
                continue;
            }
            center_x = (nameplate->min_x + nameplate->max_x) * 0.5f;
            center_y = nameplate->max_y + 28.0f;
        }

        const auto elapsed = now - presentation.started_at_milliseconds;
        const float progress = std::clamp(
            static_cast<float>(elapsed) /
                static_cast<float>(kPresentationDurationMilliseconds),
            0.0f,
            1.0f);
        GameplayDampenPresentationRenderItem item;
        item.owner_participant_id = presentation.owner_participant_id;
        item.cast_sequence = presentation.cast_sequence;
        item.center_x = center_x;
        item.center_y = center_y;
        item.radius = kInitialRadius +
            (kFinalRadius - kInitialRadius) * progress;
        item.alpha = static_cast<std::uint8_t>(
            std::lround(230.0f * (1.0f - progress)));
        items.push_back(item);
    }
    return items;
}

bool DrawGameplayDampenRing(
    IDirect3DDevice9* device,
    float center_x,
    float center_y,
    float radius,
    D3DCOLOR color) {
    constexpr std::size_t kSegmentCount = 48;
    constexpr float kTwoPi = 6.2831853071795864769f;
    if (device == nullptr ||
        !std::isfinite(center_x) ||
        !std::isfinite(center_y) ||
        !std::isfinite(radius) ||
        radius <= 0.0f) {
        return false;
    }

    std::array<ColorVertex, kSegmentCount + 1> vertices{};
    for (std::size_t index = 0; index <= kSegmentCount; ++index) {
        const float angle =
            kTwoPi * static_cast<float>(index) /
            static_cast<float>(kSegmentCount);
        vertices[index] = {
            center_x + std::cos(angle) * radius,
            center_y + std::sin(angle) * radius,
            0.0f,
            1.0f,
            color,
        };
    }
    return SUCCEEDED(device->SetFVF(kColorVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_LINESTRIP,
            static_cast<UINT>(kSegmentCount),
            vertices.data(),
            sizeof(ColorVertex)));
}

bool DrawGameplayDampenPresentation(
    IDirect3DDevice9* device,
    const GameplayDampenPresentationRenderItem& item) {
    const auto outer_color = D3DCOLOR_ARGB(
        item.alpha,
        146,
        210,
        255);
    const auto inner_color = D3DCOLOR_ARGB(
        static_cast<std::uint8_t>(item.alpha * 3 / 4),
        229,
        246,
        255);
    return DrawGameplayDampenRing(
               device,
               item.center_x,
               item.center_y,
               item.radius,
               outer_color) &&
        DrawGameplayDampenRing(
               device,
               item.center_x,
               item.center_y,
               (std::max)(item.radius - 3.0f, 1.0f),
               inner_color);
}

void LogGameplayDampenPresentationDraw(
    const GameplayDampenPresentationRenderItem& item,
    bool drawn) {
    bool should_log = false;
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        const auto presentation = std::find_if(
            g_debug_ui_overlay_state.multiplayer_dampen_presentations.begin(),
            g_debug_ui_overlay_state.multiplayer_dampen_presentations.end(),
            [&](const auto& candidate) {
                return candidate.owner_participant_id ==
                           item.owner_participant_id &&
                    candidate.cast_sequence == item.cast_sequence;
            });
        if (presentation !=
                g_debug_ui_overlay_state.multiplayer_dampen_presentations.end() &&
            !presentation->draw_logged) {
            presentation->draw_logged = true;
            should_log = true;
        }
    }
    if (should_log) {
        Log(
            "Multiplayer Dampen DX9 presentation drawn. owner_participant_id=" +
            std::to_string(item.owner_participant_id) +
            " cast_sequence=" + std::to_string(item.cast_sequence) +
            " success=" + std::to_string(drawn ? 1 : 0));
    }
}
