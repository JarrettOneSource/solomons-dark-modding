// Native DX9 level-up barrier status rendered independently of stock HUD passes.

enum class GameplayLevelUpWaitDrawResult {
    Hidden,
    Drawn,
    Failed,
};

float MeasureGameplayLevelUpWaitText(
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

GameplayLevelUpWaitDrawResult DrawGameplayLevelUpWaitStatus(
    IDirect3DDevice9* device,
    const FontAtlas& atlas,
    std::string_view text) {
    if (text.empty()) {
        return GameplayLevelUpWaitDrawResult::Hidden;
    }
    if (device == nullptr || atlas.texture == nullptr || atlas.line_height <= 0) {
        return GameplayLevelUpWaitDrawResult::Failed;
    }

    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 || viewport.Height == 0) {
        return GameplayLevelUpWaitDrawResult::Failed;
    }

    constexpr float kHorizontalPadding = 12.0f;
    constexpr float kVerticalPadding = 6.0f;
    const float text_width = MeasureGameplayLevelUpWaitText(atlas, text);
    if (!std::isfinite(text_width) || text_width <= 0.0f) {
        return GameplayLevelUpWaitDrawResult::Failed;
    }

    const float viewport_left = static_cast<float>(viewport.X);
    const float viewport_top = static_cast<float>(viewport.Y);
    const float viewport_width = static_cast<float>(viewport.Width);
    const float viewport_height = static_cast<float>(viewport.Height);
    const float box_width = text_width + kHorizontalPadding * 2.0f;
    const float box_height =
        static_cast<float>(atlas.line_height) + kVerticalPadding * 2.0f;
    const float left =
        viewport_left + (viewport_width - box_width) * 0.5f;
    const float top = viewport_top + viewport_height * 0.18f;
    const float right = left + box_width;
    const float bottom = top + box_height;

    constexpr D3DCOLOR kBackgroundColor =
        D3DCOLOR_ARGB(220, 17, 12, 9);
    constexpr D3DCOLOR kOutlineColor =
        D3DCOLOR_ARGB(245, 174, 125, 57);
    constexpr D3DCOLOR kTextColor =
        D3DCOLOR_ARGB(255, 244, 225, 180);
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
        return GameplayLevelUpWaitDrawResult::Failed;
    }
    DrawLabelText(
        device,
        atlas,
        left + kHorizontalPadding,
        top + kVerticalPadding,
        text,
        kTextColor);
    return GameplayLevelUpWaitDrawResult::Drawn;
}

void LogGameplayLevelUpWaitStatusDraw(
    std::string_view text,
    GameplayLevelUpWaitDrawResult result) {
    static std::string s_last_text;
    static GameplayLevelUpWaitDrawResult s_last_result =
        GameplayLevelUpWaitDrawResult::Hidden;

    if (text.empty()) {
        s_last_text.clear();
        s_last_result = GameplayLevelUpWaitDrawResult::Hidden;
        return;
    }
    if (text == s_last_text && result == s_last_result) {
        return;
    }

    s_last_text.assign(text.begin(), text.end());
    s_last_result = result;
    Log(
        "Multiplayer level-up wait HUD draw. source=dx9_level_up_barrier" +
        std::string(" ok=") +
        (result == GameplayLevelUpWaitDrawResult::Drawn ? "1" : "0") +
        " text=\"" + s_last_text + "\"");
}
