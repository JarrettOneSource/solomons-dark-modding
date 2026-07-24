#include "debug_ui_overlay.h"
#include "ui_navigation.h"

#include "binary_layout.h"
#include "d3d9_end_scene_hook.h"
#include "d3d9_font_atlas.h"
#include "debug_ui_config.h"
#include "logger.h"
#include "lua_engine_events.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_join_flow.h"
#include "multiplayer_local_transport.h"
#include "x86_hook.h"

#include <Windows.h>
#include <d3d9.h>
#include <intrin.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <limits>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

using TextDrawHelperFn = void(__thiscall*)(void* self, float x, float y, std::uint32_t arg3, std::uint32_t arg4);
using StringAssignHelperFn = void(__thiscall*)(void* self, char* text);
using DialogAddLineHelperFn = void(__thiscall*)(
    void* self,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    std::uint32_t arg7,
    std::uint32_t arg8,
    std::uint32_t arg9,
    std::uint32_t arg10,
    std::uint32_t arg11,
    uintptr_t arg12,
    float arg13,
    uintptr_t arg14);
using DialogButtonHelperFn = void(__thiscall*)(
    void* self,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8);
using DialogFinalizeHelperFn =
    void(__thiscall*)(void* self, std::uint32_t arg2, std::uint32_t arg3, std::uint32_t arg4, float arg5);
using ExactTextRenderFn = void(__thiscall*)(
    void* self,
    void* arg2,
    char* text,
    uintptr_t arg4,
    int* arg5,
    void* arg6,
    uintptr_t arg7,
    uintptr_t arg8,
    float arg9,
    float arg10);
using GlyphDrawHelperFn = void(__thiscall*)(void* self, float arg2, float arg3);
using TextQuadDrawHelperFn = void(__thiscall*)(void* self, const float* arg2, const float* arg3);
using SurfaceRenderHelperFn = void(__thiscall*)(void* self);
using UiOwnerControlActionFn = void(__thiscall*)(void* self, void* control);
using UiOwnerNoArgActionFn = void(__thiscall*)(void* self);
using UiOwnerPointClickActionFn = void(__thiscall*)(void* self, std::int32_t x, std::int32_t y);
using MyQuickPanelModalLoopFn = int(__thiscall*)(void* self, void* arg2);
// Ghidra shows the helper at 0x005ABF10 returns with `ret 1Ch`, so it consumes
// seven stack arguments in addition to `this`. Keep the detour signature wide
// and untyped until the semantic meaning of each slot is recovered.
using SimpleMenuModalLoopFn = int(__thiscall*)(
    void* self,
    uintptr_t arg2,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8);
using UiLabeledControlRenderFn = void(__cdecl*)(
    void* self,
    void* arg2,
    char* text,
    uintptr_t arg4,
    int* arg5,
    uintptr_t arg6,
    uintptr_t arg7,
    uintptr_t arg8,
    float arg9);
using UiUnlabeledControlRenderFn = void(__cdecl*)(void* self, int arg2, int arg3);
using UiPanelRenderFn = void(__cdecl*)(float arg1, float arg2, float arg3, float arg4, float arg5);
using UiRectDispatchFn = void(__thiscall*)(void* self, float arg2, float arg3, float arg4, float arg5);

struct NativeUiString {
    uintptr_t vtable = 0;
    char* text = nullptr;
    std::uint32_t unknown_08 = 0;
    std::int32_t* ref_count = nullptr;
    std::uint32_t length = 0;
    std::uint8_t flags_14 = 0;
    std::uint8_t flags_15 = 0;
    std::uint16_t padding_16 = 0;
    std::uint32_t unknown_18 = 0;
};
static_assert(sizeof(NativeUiString) == 0x1C, "Native UI string layout changed");

using UiRenderContextColorFn = void(__thiscall*)(void* self, float red, float green, float blue, float alpha);
using DarkCloudBrowserTabRenderFn = void(__thiscall*)(void* self, float left, float top, float width);
using DarkCloudBrowserTextRenderFn = void(__thiscall*)(void* self, NativeUiString text, float x, float y);

void (*g_reset_surface_registry_first_frame_flags)() = nullptr;

constexpr D3DCOLOR kBoxColor = D3DCOLOR_ARGB(220, 64, 255, 160);
constexpr D3DCOLOR kLabelTextColor = D3DCOLOR_ARGB(255, 255, 255, 255);
constexpr D3DCOLOR kLabelBackgroundColor = D3DCOLOR_ARGB(180, 0, 0, 0);
constexpr D3DCOLOR kLabelOutlineColor = D3DCOLOR_ARGB(220, 0, 0, 0);
constexpr std::string_view kDarkCloudBrowserMultiplayerTabLabel = "multiplayer";
constexpr float kDarkCloudBrowserInactiveTabTextRed = 0.850000024f;
constexpr float kDarkCloudBrowserInactiveTabTextGreen = 0.730000019f;
constexpr float kDarkCloudBrowserInactiveTabTextBlue = 0.439999998f;
constexpr float kDarkCloudBrowserNativeMultiplayerTabGap = 0.0f;
constexpr float kDarkCloudBrowserMultiplayerTabHorizontalPadding = 16.0f;
constexpr float kDarkCloudBrowserInactiveTabTextYOffset = 52.0f;
constexpr std::size_t kUiRenderContextDrawStateOffset = 0x1D0;
// TextQuad_Draw reads this Z value from its draw-state `this` object before
// submitting XYZ + diffuse + UV vertices through the fixed-function pipeline.
constexpr std::size_t kTextQuadDrawStateDepthOffset = 0x448;
constexpr std::size_t kTextDrawHookPatchSize = 6;
constexpr std::size_t kStringAssignHookPatchSize = 5;
constexpr std::size_t kDialogAddLineHookPatchSize = 7;
constexpr std::size_t kDialogButtonHookPatchSize = 7;
constexpr std::size_t kDialogFinalizeHookPatchSize = 7;
constexpr std::size_t kExactTextRenderHookPatchSize = 5;
constexpr std::size_t kGlyphDrawHookPatchSize = 6;
constexpr std::size_t kSurfaceRenderHookPatchSize = 7;
// 0x005D9A50 starts with 1+2+3+2-byte instructions, so 7 would split `push 0xff`.
constexpr std::size_t kSettingsRenderHookPatchSize = 8;
constexpr std::size_t kMainMenuRenderHookPatchSize = 6;
constexpr std::size_t kHallOfFameRenderHookPatchSize = 6;
constexpr std::size_t kSpellPickerRenderHookPatchSize = 7;
constexpr std::size_t kMyQuickPanelModalLoopHookPatchSize = 7;
constexpr std::size_t kSimpleMenuModalLoopHookPatchSize = 7;
constexpr std::size_t kUiLabeledControlRenderHookPatchSize = 7;
constexpr std::size_t kUiUnlabeledControlRenderHookPatchSize = 6;
constexpr std::size_t kUiPanelRenderHookPatchSize = 7;
constexpr std::size_t kUiRectDispatchHookPatchSize = 6;
constexpr int kFirstGlyph = kD3d9FontFirstGlyph;
constexpr int kLastGlyph = kD3d9FontLastGlyph;
constexpr float kOverlayTextHorizontalPadding = 8.0f;
constexpr float kOverlayTextVerticalPadding = 3.0f;
constexpr float kOverlayClusterMinimumWidth = 24.0f;
constexpr ULONGLONG kTrackedDialogDismissArmDelayMs = 300;
constexpr ULONGLONG kTrackedDialogMaximumLifetimeMs = 300000;
constexpr ULONGLONG kTrackedDialogHigherPrioritySurfaceCutoverDelayMs = 200;
constexpr std::size_t kMaximumUiWidgetParentDepth = 16;
constexpr std::size_t kUiOwnerControlActionVtableSlotIndex = 4;

struct SurfaceObservationRange {
    std::string surface_id;
    std::string surface_title;
    uintptr_t start = 0;
    uintptr_t end = 0;
    std::vector<std::string> ordered_labels;
};

struct ObservedUiElement {
    std::string surface_id;
    std::string surface_title;
    uintptr_t object_ptr = 0;
    uintptr_t label_source_ptr = 0;
    uintptr_t caller_address = 0;
    uintptr_t surface_return_address = 0;
    std::size_t stack_slot = 0;
    float min_x = 0.0f;
    float max_x = 0.0f;
    float min_y = 0.0f;
    float max_y = 0.0f;
    std::uint32_t sample_count = 0;
    std::uint64_t gameplay_participant_id = 0;
    float gameplay_health_ratio = 0.0f;
    std::string label;
};

struct OverlayRenderElement {
    std::string surface_id;
    std::string surface_title;
    std::string label;
    std::string action_id;
    uintptr_t source_object_ptr = 0;
    uintptr_t surface_object_ptr = 0;
    bool show_label = true;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
};

struct SurfaceStackMatch {
    const SurfaceObservationRange* range = nullptr;
    uintptr_t return_address = 0;
    std::size_t stack_slot = 0;
};

struct DialogButtonState {
    std::string label;
    std::string action_id;
    uintptr_t object_ptr = 0;
    bool has_bounds = false;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
};

struct DialogLineState {
    uintptr_t wrapper_ptr = 0;
    uintptr_t object_ptr = 0;
    float logical_height = 0.0f;
    bool has_bounds = false;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    std::string label;
};

struct DialogOverlaySnapshot {
    uintptr_t object_ptr = 0;
    ULONGLONG captured_at = 0;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    bool uses_cached_geometry = false;
    std::string title;
    std::vector<std::string> lines;
    std::vector<DialogLineState> line_states;
    std::vector<DialogButtonState> buttons;
};

struct DialogGeometry {
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    DialogButtonState primary_button;
    DialogButtonState secondary_button;
};

struct ExactTextRenderCapture {
    bool capture_enabled = false;
    bool has_expected_origin = false;
    uintptr_t source_object_ptr = 0;
    uintptr_t caller_address = 0;
    uintptr_t surface_return_address = 0;
    std::size_t stack_slot = 0;
    std::string surface_id;
    std::string surface_title;
    std::string label;
    float expected_origin_x = 0.0f;
    float expected_origin_y = 0.0f;
    float min_x = (std::numeric_limits<float>::max)();
    float min_y = (std::numeric_limits<float>::max)();
    float max_x = (std::numeric_limits<float>::lowest)();
    float max_y = (std::numeric_limits<float>::lowest)();
    std::uint32_t glyph_count = 0;
    std::uint64_t gameplay_participant_id = 0;
    float gameplay_health_ratio = 0.0f;
    float gameplay_world_width = 0.0f;
    bool gameplay_viewport_offset_resolved = false;
    float gameplay_viewport_offset_x = 0.0f;
    float gameplay_viewport_offset_y = 0.0f;
};

struct GameplayParticipantNameplateCaptureRequest {
    bool active = false;
    std::uint64_t participant_id = 0;
    float health_ratio = 0.0f;
    float world_width = 0.0f;
    std::string exact_text;
};

struct TrackedDialogState {
    uintptr_t object_ptr = 0;
    ULONGLONG captured_at = 0;
    bool has_geometry = false;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
    std::string title;
    std::vector<std::string> lines;
    DialogButtonState primary_button;
    DialogButtonState secondary_button;
};

struct TrackedSurfaceRenderState {
    uintptr_t active_object_ptr = 0;
    uintptr_t tracked_object_ptr = 0;
    ULONGLONG captured_at = 0;
    std::uint32_t render_depth = 0;
};

struct PendingSemanticUiActionRequest {
    bool active = false;
    std::uint64_t request_id = 0;
    ULONGLONG queued_at = 0;
    std::uint64_t snapshot_generation = 0;
    std::string action_id;
    std::string target_label;
    std::string surface_id;
};

struct ActiveSemanticUiActionDispatch {
    bool active = false;
    std::uint64_t request_id = 0;
    ULONGLONG queued_at = 0;
    ULONGLONG started_at = 0;
    std::uint64_t snapshot_generation = 0;
    uintptr_t owner_address = 0;
    uintptr_t control_address = 0;
    std::string action_id;
    std::string target_label;
    std::string surface_id;
    std::string dispatch_kind;
    std::string status = "dispatching";
};

struct CompletedSemanticUiActionDispatch {
    bool valid = false;
    std::uint64_t request_id = 0;
    ULONGLONG queued_at = 0;
    ULONGLONG started_at = 0;
    ULONGLONG completed_at = 0;
    std::uint64_t snapshot_generation = 0;
    uintptr_t owner_address = 0;
    uintptr_t control_address = 0;
    std::string action_id;
    std::string target_label;
    std::string surface_id;
    std::string dispatch_kind;
    std::string status;
    std::string error_message;
};

struct TrackedSimpleMenuEntryState {
    std::string label;
    std::string action_id;
    int selection_index = -1;
};

struct TrackedSimpleMenuState {
    uintptr_t active_object_ptr = 0;
    ULONGLONG captured_at = 0;
    ULONGLONG definition_captured_at = 0;
    std::uint32_t modal_depth = 0;
    std::string raw_definition;
    std::string semantic_surface_id;
    std::string semantic_surface_title;
    std::vector<TrackedSimpleMenuEntryState> entries;
};

struct TrackedWidgetRectState {
    uintptr_t root_object_ptr = 0;
    ULONGLONG captured_at = 0;
    bool has_rect = false;
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
};

enum class PendingDarkCloudBrowserAction {
    None,
    Search,
    Sort,
    Options,
    Recent,
    OnlineLevels,
    MyLevels,
};

using FontAtlas = D3d9FontAtlas;

struct ColorVertex {
    float x;
    float y;
    float z;
    float rhw;
    D3DCOLOR color;
};

struct TexturedVertex {
    float x;
    float y;
    float z;
    float rhw;
    D3DCOLOR color;
    float u;
    float v;
};

constexpr DWORD kColorVertexFvf = D3DFVF_XYZRHW | D3DFVF_DIFFUSE;
constexpr DWORD kTexturedVertexFvf = D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1;
constexpr ULONGLONG kLatestSurfaceSnapshotMaximumIdleMs = 1000;
constexpr ULONGLONG kPendingSemanticUiActionRequestMaximumAgeMs = 3000;
constexpr ULONGLONG kTrackedMyQuickPanelMaximumIdleMs = 250;
constexpr ULONGLONG kTrackedDarkCloudBrowserMaximumIdleMs = 250;
constexpr ULONGLONG kTrackedHallOfFameMaximumIdleMs = 250;
constexpr ULONGLONG kTrackedSpellPickerMaximumIdleMs = 250;
constexpr ULONGLONG kTrackedSettingsMaximumIdleMs = 1000;
constexpr ULONGLONG kTrackedDarkCloudBrowserPanelMaximumIdleMs = 250;
constexpr ULONGLONG kTrackedDarkCloudBrowserModalMaximumIdleMs = 250;

struct DebugUiOverlayState {
    bool initialized = false;
    bool diagnostic_visuals_enabled = false;
    bool first_frame_logged = false;
    bool first_d3d_frame_logged = false;
    bool first_font_atlas_ready_logged = false;
    bool first_font_atlas_failure_logged = false;
    bool first_candidate_logged = false;
    bool first_text_draw_call_logged = false;
    bool first_exact_text_render_call_logged = false;
    bool first_glyph_draw_call_logged = false;
    bool first_string_assign_call_logged = false;
    bool first_dialog_add_line_logged = false;
    bool first_dialog_button_logged = false;
    bool first_dialog_finalize_logged = false;
    bool first_tracked_dialog_frame_logged = false;
    bool first_dark_cloud_browser_render_logged = false;
    bool first_settings_render_logged = false;
    bool first_myquick_panel_render_logged = false;
    bool first_myquick_panel_modal_logged = false;
    bool first_exact_control_render_logged = false;
    bool first_simple_menu_modal_logged = false;
    bool first_main_menu_render_logged = false;
    bool first_hall_of_fame_render_logged = false;
    bool first_spell_picker_render_logged = false;
    bool first_viewport_calibrated_dialog_logged = false;
    bool first_cached_dialog_geometry_logged = false;
    bool first_stack_match_logged = false;
    bool previous_left_button_down = false;
    DebugUiOverlayConfig config;
    X86Hook text_draw_hook;
    X86Hook string_assign_hook;
    X86Hook dialog_add_line_hook;
    X86Hook dialog_primary_button_hook;
    X86Hook dialog_secondary_button_hook;
    X86Hook dialog_finalize_hook;
    X86Hook exact_text_render_hook;
    X86Hook dark_cloud_browser_exact_text_render_hook;
    X86Hook glyph_draw_hook;
    X86Hook text_quad_draw_hook;
    X86Hook dark_cloud_browser_render_hook;
    X86Hook settings_render_hook;
    X86Hook myquick_panel_render_hook;
    X86Hook myquick_panel_modal_loop_hook;
    X86Hook simple_menu_modal_loop_hook;
    X86Hook main_menu_render_hook;
    X86Hook hall_of_fame_render_hook;
    X86Hook spell_picker_render_hook;
    X86Hook ui_labeled_control_render_hook;
    X86Hook ui_labeled_control_alt_render_hook;
    X86Hook ui_unlabeled_control_render_hook;
    X86Hook ui_panel_render_hook;
    X86Hook ui_rect_dispatch_hook;
    FontAtlas font_atlas;
    IDirect3DDevice9* font_device = nullptr;
    std::vector<SurfaceObservationRange> surface_ranges;
    std::vector<ObservedUiElement> frame_elements;
    std::vector<ObservedUiElement> frame_exact_text_elements;
    std::vector<ObservedUiElement> frame_exact_control_elements;
    std::vector<ExactTextRenderCapture> active_exact_text_renders;
    struct MultiplayerDampenPresentation {
        std::uint64_t owner_participant_id = 0;
        std::uint32_t cast_sequence = 0;
        ULONGLONG started_at_milliseconds = 0;
        bool draw_logged = false;
    };
    std::vector<MultiplayerDampenPresentation>
        multiplayer_dampen_presentations;
    std::vector<std::string> recent_assigned_strings;
    ULONGLONG recent_assigned_strings_updated_at = 0;
    uintptr_t tracked_title_main_menu_object = 0;
    uintptr_t last_create_owner_object = 0;
    TrackedSurfaceRenderState dark_cloud_browser_render;
    TrackedSurfaceRenderState settings_render;
    TrackedSurfaceRenderState myquick_panel_render;
    TrackedSurfaceRenderState hall_of_fame_render;
    TrackedSurfaceRenderState spell_picker_render;
    TrackedSimpleMenuState myquick_panel_modal;
    TrackedSimpleMenuState simple_menu;
    TrackedWidgetRectState dark_cloud_browser_panel;
    TrackedWidgetRectState dark_cloud_browser_modal_root;
    TrackedDialogState tracked_dialog;
    PendingSemanticUiActionRequest pending_semantic_ui_action;
    ActiveSemanticUiActionDispatch active_semantic_ui_action_dispatch;
    CompletedSemanticUiActionDispatch last_semantic_ui_action_dispatch;
    std::unordered_map<uintptr_t, std::string> object_label_cache;
    std::uint64_t latest_surface_snapshot_generation = 0;
    std::uint64_t last_logged_action_query_rejection_generation = 0;
    std::string last_logged_action_query_rejection_action_id;
    std::uint64_t next_semantic_ui_action_request_id = 0;
    DebugUiSurfaceSnapshot latest_surface_snapshot;
    std::mutex mutex;
};

DebugUiOverlayState g_debug_ui_overlay_state;
thread_local GameplayParticipantNameplateCaptureRequest
    g_gameplay_participant_nameplate_capture;

bool InitializeFontAtlas(IDirect3DDevice9* device, FontAtlas* atlas, std::string* error_message);
int MeasureLabelWidth(const FontAtlas& atlas, std::string_view label);
bool DrawFilledRect(IDirect3DDevice9* device, float left, float top, float right, float bottom, D3DCOLOR color);
bool DrawRectOutline(IDirect3DDevice9* device, float left, float top, float right, float bottom, D3DCOLOR color);
void DrawLabelText(IDirect3DDevice9* device, const FontAtlas& atlas, float left, float top, std::string_view label, D3DCOLOR color);
void ConfigureOverlayRenderState(IDirect3DDevice9* device);
bool IsPlausibleDialogRect(float left, float top, float width, float height);
std::string TrimAsciiWhitespace(std::string_view value);
std::string SanitizeDebugLogLabel(std::string value);
#include "debug_ui_overlay/public_memory_forwarders.inl"
