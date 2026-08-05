#include "public_api_initialization.inl"
#include "public_api_surface_dispatch.inl"
#include "public_api_actions.inl"

bool TryPrepareMainMenuNewGameSaveReset(
    std::uintptr_t main_menu_address,
    std::string* error_message) {
    return TryPrepareMainMenuNewGameSaveResetImpl(main_menu_address, error_message);
}

void ObserveDebugUiExactTextGlyph(float x, float y) {
    ObserveActiveExactTextGlyph(x, y);
}

void ObserveDebugUiMenuSpritePositionDraw(
    void* sprite,
    float x,
    float y) {
    ObserveMenuSpritePositionDraw(sprite, x, y, false);
}
