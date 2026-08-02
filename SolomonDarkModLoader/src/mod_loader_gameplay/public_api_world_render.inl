bool DrawNativeWorldIndicatorExactText(
    std::string_view text,
    float x,
    float y) {
    if (text.empty() || !std::isfinite(x) || !std::isfinite(y)) {
        return false;
    }
    DWORD exception_code = 0;
    return DrawGameplayHudExactTextAt(
        std::string(text),
        x,
        y,
        &exception_code);
}

void RenderGameplayWorldIndicatorsInNativePass() {
    RenderGameplayWorldIndicatorsInNativePassImpl();
}
