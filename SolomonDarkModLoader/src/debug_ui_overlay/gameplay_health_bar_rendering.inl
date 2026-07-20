// Native-name anchored DX9 health bars for remote participants.

struct GameplayParticipantHealthBarRenderItem {
    std::uint64_t participant_id = 0;
    float health_ratio = 0.0f;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    float name_left = 0.0f;
    float name_top = 0.0f;
    float name_right = 0.0f;
    float name_bottom = 0.0f;
};

enum class GameplayParticipantHealthBarDrawResult {
    Culled,
    Drawn,
    Failed,
};

std::vector<GameplayParticipantHealthBarRenderItem>
BuildGameplayParticipantHealthBarRenderItems(
    const std::vector<ObservedUiElement>& exact_text_elements) {
    constexpr float kBarMinimumWidth = 64.0f;
    constexpr float kBarHeight = 7.0f;
    // Flush under the captured name: one pixel keeps glyph descenders off the
    // bar border without opening a visible gap.
    constexpr float kBarVerticalGap = 1.0f;

    std::vector<GameplayParticipantHealthBarRenderItem> items;
    items.reserve(exact_text_elements.size());
    for (const auto& element : exact_text_elements) {
        if (element.surface_id != "gameplay_nameplate" ||
            element.gameplay_participant_id == 0 ||
            element.sample_count == 0 ||
            !std::isfinite(element.min_x) ||
            !std::isfinite(element.max_x) ||
            !std::isfinite(element.min_y) ||
            !std::isfinite(element.max_y) ||
            element.max_x < element.min_x ||
            element.max_y < element.min_y) {
            continue;
        }

        const float center_x =
            (element.min_x + element.max_x) * 0.5f;
        const float bar_width = (std::max)(
            kBarMinimumWidth,
            element.max_x - element.min_x);
        GameplayParticipantHealthBarRenderItem item;
        item.participant_id = element.gameplay_participant_id;
        item.health_ratio = std::clamp(
            element.gameplay_health_ratio,
            0.0f,
            1.0f);
        item.left = center_x - (bar_width * 0.5f);
        item.top = element.max_y + kBarVerticalGap;
        item.right = item.left + bar_width;
        item.bottom = item.top + kBarHeight;
        item.name_left = element.min_x;
        item.name_top = element.min_y;
        item.name_right = element.max_x;
        item.name_bottom = element.max_y;

        const auto existing = std::find_if(
            items.begin(),
            items.end(),
            [&](const GameplayParticipantHealthBarRenderItem& candidate) {
                return candidate.participant_id == item.participant_id;
            });
        if (existing == items.end()) {
            items.push_back(item);
        } else {
            *existing = item;
        }
    }
    return items;
}

GameplayParticipantHealthBarDrawResult DrawGameplayParticipantHealthBar(
    IDirect3DDevice9* device,
    const GameplayParticipantHealthBarRenderItem& item) {
    if (device == nullptr ||
        item.participant_id == 0 ||
        !std::isfinite(item.left) ||
        !std::isfinite(item.top) ||
        !std::isfinite(item.right) ||
        !std::isfinite(item.bottom) ||
        item.right <= item.left ||
        item.bottom <= item.top) {
        return GameplayParticipantHealthBarDrawResult::Failed;
    }

    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport))) {
        return GameplayParticipantHealthBarDrawResult::Failed;
    }
    const float viewport_left = static_cast<float>(viewport.X);
    const float viewport_top = static_cast<float>(viewport.Y);
    const float viewport_right =
        viewport_left + static_cast<float>(viewport.Width);
    const float viewport_bottom =
        viewport_top + static_cast<float>(viewport.Height);
    if (item.right <= viewport_left ||
        item.left >= viewport_right ||
        item.bottom <= viewport_top ||
        item.top >= viewport_bottom) {
        return GameplayParticipantHealthBarDrawResult::Culled;
    }

    constexpr float kInset = 1.0f;
    constexpr D3DCOLOR kBorderColor =
        D3DCOLOR_ARGB(235, 12, 6, 6);
    constexpr D3DCOLOR kEmptyColor =
        D3DCOLOR_ARGB(220, 54, 13, 13);
    constexpr D3DCOLOR kHealthColor =
        D3DCOLOR_ARGB(240, 190, 31, 24);
    constexpr D3DCOLOR kHealthHighlightColor =
        D3DCOLOR_ARGB(210, 255, 105, 78);

    if (!DrawFilledRect(
            device,
            item.left,
            item.top,
            item.right,
            item.bottom,
            kBorderColor)) {
        return GameplayParticipantHealthBarDrawResult::Failed;
    }

    const float inner_left = item.left + kInset;
    const float inner_top = item.top + kInset;
    const float inner_right = item.right - kInset;
    const float inner_bottom = item.bottom - kInset;
    if (!DrawFilledRect(
            device,
            inner_left,
            inner_top,
            inner_right,
            inner_bottom,
            kEmptyColor)) {
        return GameplayParticipantHealthBarDrawResult::Failed;
    }

    const float health_ratio =
        std::clamp(item.health_ratio, 0.0f, 1.0f);
    const float health_right =
        inner_left + ((inner_right - inner_left) * health_ratio);
    if (health_right > inner_left) {
        if (!DrawFilledRect(
                device,
                inner_left,
                inner_top,
                health_right,
                inner_bottom,
                kHealthColor) ||
            !DrawFilledRect(
                device,
                inner_left,
                inner_top,
                health_right,
                (std::min)(inner_top + 1.0f, inner_bottom),
                kHealthHighlightColor)) {
            return GameplayParticipantHealthBarDrawResult::Failed;
        }
    }

    if (!DrawRectOutline(
            device,
            item.left,
            item.top,
            item.right,
            item.bottom,
            kBorderColor)) {
        return GameplayParticipantHealthBarDrawResult::Failed;
    }
    return GameplayParticipantHealthBarDrawResult::Drawn;
}

void LogGameplayParticipantHealthBarDraw(
    const GameplayParticipantHealthBarRenderItem& item,
    GameplayParticipantHealthBarDrawResult result) {
    if (result == GameplayParticipantHealthBarDrawResult::Culled) {
        return;
    }

    static std::unordered_map<std::uint64_t, int> s_logged_health_percent;
    static int s_failed_draw_logs_remaining = 8;

    const bool drew_bar =
        result == GameplayParticipantHealthBarDrawResult::Drawn;
    const int health_percent = std::clamp(
        static_cast<int>(std::lround(item.health_ratio * 100.0f)),
        0,
        100);
    const auto logged = s_logged_health_percent.find(item.participant_id);
    const bool health_changed =
        logged == s_logged_health_percent.end() ||
        logged->second != health_percent;
    if (drew_bar && !health_changed) {
        return;
    }
    if (!drew_bar && s_failed_draw_logs_remaining <= 0) {
        return;
    }

    if (drew_bar) {
        s_logged_health_percent[item.participant_id] = health_percent;
    } else {
        --s_failed_draw_logs_remaining;
    }
    Log(
        "Multiplayer participant health bar draw. source=dx9_nameplate_healthbar" +
        std::string(" participant=") + std::to_string(item.participant_id) +
        " ok=" + std::string(drew_bar ? "1" : "0") +
        " health_ratio=" + std::to_string(item.health_ratio) +
        " health_percent=" + std::to_string(health_percent) +
        " bounds=(" + std::to_string(item.left) + "," +
            std::to_string(item.top) + "," +
            std::to_string(item.right) + "," +
            std::to_string(item.bottom) + ")" +
        " name_bounds=(" + std::to_string(item.name_left) + "," +
            std::to_string(item.name_top) + "," +
            std::to_string(item.name_right) + "," +
            std::to_string(item.name_bottom) + ")");
}
