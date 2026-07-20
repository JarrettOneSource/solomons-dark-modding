uintptr_t BuildObservationIdentityKey(
    void* identity_source,
    float x,
    float y,
    uintptr_t caller_address,
    bool prefer_object_identity);
bool TryGetActiveDarkCloudBrowserRender(uintptr_t* browser_address);
bool TryGetCurrentDarkCloudBrowser(uintptr_t* browser_address);
bool TryReadTrackedDialogObject(uintptr_t* dialog_address);
bool TryReadActiveTitleMainMenu(
    const DebugUiOverlayConfig& config,
    uintptr_t* bundle_address,
    uintptr_t* main_menu_address);
void RememberDarkCloudBrowserPanelRect(
    uintptr_t browser_address,
    float left,
    float top,
    float right,
    float bottom);
bool TryReadTrackedDarkCloudBrowserPanelRect(
    uintptr_t browser_address,
    float* left,
    float* top,
    float* right,
    float* bottom);
void RememberDarkCloudBrowserModalRootRect(
    uintptr_t browser_address,
    float left,
    float top,
    float right,
    float bottom);
bool TryReadTrackedDarkCloudBrowserModalRootRect(
    uintptr_t browser_address,
    float* left,
    float* top,
    float* right,
    float* bottom);
bool TryGetLiveSettingsRender(uintptr_t* settings_address);
bool TryGetActiveSettingsRender(uintptr_t* settings_address);
bool TryGetActiveMyQuickPanelRender(uintptr_t* quick_panel_address);
bool TryReadTrackedMyQuickPanel(uintptr_t* quick_panel_address);
bool TryGetActiveSimpleMenu(uintptr_t* simple_menu_address);
bool TryGetActiveHallOfFameRender(uintptr_t* hof_address);
bool TryGetCurrentHallOfFame(uintptr_t* hof_address);
bool TryGetActiveSpellPickerRender(uintptr_t* picker_address);
bool TryGetCurrentSpellPicker(uintptr_t* picker_address);
bool TryReadMyQuickPanelBuilderOwnerAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t* owner_address);
bool TryReadMyQuickPanelBuilderAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t* builder_address);
bool TryReadMyQuickPanelBuilderRootControlAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    uintptr_t* root_control_address);
bool TryReadMyQuickPanelBuilderWidgetPointers(
    const DebugUiOverlayConfig& config,
    uintptr_t quick_panel_address,
    std::vector<uintptr_t>* widget_pointers);
bool TryReadExactControlRect(
    const DebugUiOverlayConfig& config,
    const void* control_object,
    float* left,
    float* top,
    float* right,
    float* bottom);
bool TryReadDarkCloudBrowserTextOwnerAddress(
    const DebugUiOverlayConfig& config,
    uintptr_t text_object_address,
    uintptr_t* owner_address);
bool IsLocalSubsurfaceRect(float left, float top, float right, float bottom);
bool IsWidgetOwnedByRootAtOffset(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address,
    std::size_t parent_offset);
bool IsWidgetOwnedByRoot(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address);
bool TryResolveDarkCloudBrowserModalHeaderTextRect(
    const DebugUiOverlayConfig& config,
    uintptr_t caller_address,
    uintptr_t source_object_ptr,
    float raw_left,
    float raw_top,
    float raw_right,
    float raw_bottom,
    float* left,
    float* top,
    float* right,
    float* bottom);
bool TryReadTranslatedWidgetRectToRootAtOffset(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address,
    std::size_t parent_offset,
    float* left,
    float* top,
    float* right,
    float* bottom);
bool TryReadTranslatedWidgetRectToRoot(
    const DebugUiOverlayConfig& config,
    uintptr_t root_address,
    uintptr_t object_address,
    float* left,
    float* top,
    float* right,
    float* bottom);
bool TryReadPointerListEntries(
    const void* owner_object,
    std::size_t list_offset,
    std::size_t list_count_offset,
    std::size_t list_entries_offset,
    std::size_t max_entries,
    std::vector<uintptr_t>* entries);
bool TryReadSettingsPanelRect(
    const DebugUiOverlayConfig& config,
    uintptr_t settings_address,
    float* left,
    float* top,
    float* right,
    float* bottom);
bool TryReadPointerField(const void* object, std::size_t byte_offset, uintptr_t* value);
std::string GetOverlaySurfaceRootId(std::string_view surface_id);

#include "debug_ui_overlay/state_and_actions.inl"
#include "debug_ui_overlay/string_and_memory_readers.inl"
#include "debug_ui_overlay/exact_widget_resolution.inl"
#include "debug_ui_overlay/widget_geometry_readers.inl"
#include "debug_ui_overlay/control_observers.inl"
#include "debug_ui_overlay/tracked_surfaces_and_main_menu.inl"
#include "debug_ui_overlay/dark_cloud_browser_native_tabs.inl"
#include "debug_ui_overlay/dialog_tracking_and_snapshots.inl"
#include "debug_ui_overlay/exact_text_capture_and_hooks.inl"
#include "debug_ui_overlay/surface_render_hooks.inl"
#include "debug_ui_overlay/font_atlas_rendering.inl"
#include "debug_ui_overlay/gameplay_dampen_rendering.inl"
#include "debug_ui_overlay/gameplay_health_bar_rendering.inl"
#include "debug_ui_overlay/gameplay_level_up_wait_rendering.inl"
#include "debug_ui_overlay/overlay_surface_builders.inl"
#include "debug_ui_overlay/modal_surface_render_builders.inl"
#include "debug_ui_overlay/label_resolution_and_frame_render.inl"
#include "debug_ui_overlay/ui_navigation_element_builders.inl"

}  // namespace

#include "debug_ui_overlay/install_hooks.inl"
#include "debug_ui_overlay/public_api.inl"
#include "debug_ui_overlay/ui_navigation_public.inl"

}  // namespace sdmod
