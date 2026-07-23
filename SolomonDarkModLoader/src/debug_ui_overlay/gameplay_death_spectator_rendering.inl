// Local-only spectator status rendered independently of stock HUD surfaces.

enum class GameplayDeathSpectatorDrawResult {
    Hidden,
    Drawn,
    Failed,
};

float MeasureGameplayDeathSpectatorText(
    const FontAtlas& atlas,
    std::string_view text) {
    float width = 0.0f;
    for (const unsigned char character : text) {
        if (character < kFirstGlyph || character > kLastGlyph) {
            width += static_cast<float>(atlas.line_height) * 0.5f;
            continue;
        }
        const auto& glyph = atlas.glyphs[character - kFirstGlyph];
        width += static_cast<float>((std::max)(glyph.width, 1));
    }
    return width;
}

GameplayDeathSpectatorDrawResult DrawGameplayDeathSpectatorStatus(
    IDirect3DDevice9* device,
    const FontAtlas& atlas,
    std::string_view text) {
    if (text.empty()) {
        return GameplayDeathSpectatorDrawResult::Hidden;
    }
    if (device == nullptr || atlas.texture == nullptr ||
        atlas.line_height <= 0) {
        return GameplayDeathSpectatorDrawResult::Failed;
    }

    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 || viewport.Height == 0) {
        return GameplayDeathSpectatorDrawResult::Failed;
    }

    constexpr float kHorizontalPadding = 12.0f;
    constexpr float kVerticalPadding = 6.0f;
    const float text_width =
        MeasureGameplayDeathSpectatorText(atlas, text);
    if (!std::isfinite(text_width) || text_width <= 0.0f) {
        return GameplayDeathSpectatorDrawResult::Failed;
    }

    const float box_width = text_width + kHorizontalPadding * 2.0f;
    const float box_height =
        static_cast<float>(atlas.line_height) +
        kVerticalPadding * 2.0f;
    const float left =
        static_cast<float>(viewport.X) +
        (static_cast<float>(viewport.Width) - box_width) * 0.5f;
    const float top =
        static_cast<float>(viewport.Y) +
        static_cast<float>(viewport.Height) * 0.10f;
    const float right = left + box_width;
    const float bottom = top + box_height;

    constexpr D3DCOLOR kBackgroundColor =
        D3DCOLOR_ARGB(220, 10, 12, 18);
    constexpr D3DCOLOR kOutlineColor =
        D3DCOLOR_ARGB(245, 112, 176, 232);
    constexpr D3DCOLOR kTextColor =
        D3DCOLOR_ARGB(255, 225, 240, 255);
    if (!DrawFilledRect(
            device,
            left,
            top,
            right,
            bottom,
            kBackgroundColor) ||
        !DrawRectOutline(
            device,
            left,
            top,
            right,
            bottom,
            kOutlineColor)) {
        return GameplayDeathSpectatorDrawResult::Failed;
    }
    DrawLabelText(
        device,
        atlas,
        left + kHorizontalPadding,
        top + kVerticalPadding,
        text,
        kTextColor);
    return GameplayDeathSpectatorDrawResult::Drawn;
}

void LogGameplayDeathSpectatorStatusDraw(
    std::string_view text,
    GameplayDeathSpectatorDrawResult result) {
    static std::string s_last_text;
    static GameplayDeathSpectatorDrawResult s_last_result =
        GameplayDeathSpectatorDrawResult::Hidden;
    if (text.empty()) {
        s_last_text.clear();
        s_last_result = GameplayDeathSpectatorDrawResult::Hidden;
        return;
    }
    if (text == s_last_text && result == s_last_result) {
        return;
    }
    s_last_text.assign(text.begin(), text.end());
    s_last_result = result;
    Log(
        "Multiplayer spectator HUD draw. ok=" +
        std::string(
            result == GameplayDeathSpectatorDrawResult::Drawn
                ? "1"
                : "0") +
        " text=\"" + s_last_text + "\"");
}
