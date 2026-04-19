#include "debug_ui_config.h"

#include "debug_ui_config_internal.h"

#include <mutex>

namespace sdmod {
namespace {

using sdmod::detail::debug_ui_config_internal::IniDocument;
using sdmod::detail::debug_ui_config_internal::IniSection;

std::mutex g_debug_ui_config_mutex;
DebugUiOverlayConfig g_debug_ui_config;
std::string g_debug_ui_config_error;
bool g_debug_ui_config_loaded = false;

struct AddressField {
    const char* key;
    uintptr_t DebugUiOverlayConfig::* member;
};

struct SizeField {
    const char* key;
    size_t DebugUiOverlayConfig::* member;
};

bool ParseDebugUiOverlayConfig(
    const std::filesystem::path& path,
    DebugUiOverlayConfig* config,
    std::string* error_message) {
    using namespace sdmod::detail::debug_ui_config_internal;

    if (config == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config destination is null.";
        }
        return false;
    }

    IniDocument document;
    if (!LoadIniDocument(path, &document, error_message)) {
        return false;
    }

    const auto overlay_it = document.find("overlay");
    if (overlay_it == document.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing the [overlay] section.";
        }
        return false;
    }

    DebugUiOverlayConfig parsed;
    parsed.source_path = path;

    const auto& overlay = overlay_it->second;

    if (!ReadRequiredBoolean(overlay, "enabled", &parsed.enabled, error_message)) {
        return false;
    }

    static constexpr AddressField kRequiredAddressFields[] = {
        {"text_draw_helper", &DebugUiOverlayConfig::text_draw_helper},
        {"string_assign_helper", &DebugUiOverlayConfig::string_assign_helper},
        {"dialog_add_line_helper", &DebugUiOverlayConfig::dialog_add_line_helper},
        {"dialog_primary_button_helper", &DebugUiOverlayConfig::dialog_primary_button_helper},
        {"dialog_secondary_button_helper", &DebugUiOverlayConfig::dialog_secondary_button_helper},
        {"dialog_finalize_helper", &DebugUiOverlayConfig::dialog_finalize_helper},
        {"exact_text_render_helper", &DebugUiOverlayConfig::exact_text_render_helper},
        {"dark_cloud_browser_exact_text_render_helper", &DebugUiOverlayConfig::dark_cloud_browser_exact_text_render_helper},
        {"ui_labeled_control_render_helper", &DebugUiOverlayConfig::ui_labeled_control_render_helper},
        {"ui_labeled_control_alt_render_helper", &DebugUiOverlayConfig::ui_labeled_control_alt_render_helper},
        {"ui_unlabeled_control_render_helper", &DebugUiOverlayConfig::ui_unlabeled_control_render_helper},
        {"ui_panel_render_helper", &DebugUiOverlayConfig::ui_panel_render_helper},
        {"ui_rect_dispatch_helper", &DebugUiOverlayConfig::ui_rect_dispatch_helper},
        {"glyph_draw_helper", &DebugUiOverlayConfig::glyph_draw_helper},
        {"text_quad_draw_helper", &DebugUiOverlayConfig::text_quad_draw_helper},
        {"device_pointer_global", &DebugUiOverlayConfig::device_pointer_global},
        {"ui_render_context_global", &DebugUiOverlayConfig::ui_render_context_global},
        {"title_main_menu_vftable", &DebugUiOverlayConfig::title_main_menu_vftable},
        {"myquick_panel_vftable", &DebugUiOverlayConfig::myquick_panel_vftable},
        {"dark_cloud_browser_render_helper", &DebugUiOverlayConfig::dark_cloud_browser_render_helper},
        {"dark_cloud_browser_vftable", &DebugUiOverlayConfig::dark_cloud_browser_vftable},
        {"dark_cloud_browser_modal_header_text_caller", &DebugUiOverlayConfig::dark_cloud_browser_modal_header_text_caller},
        {"settings_render_helper", &DebugUiOverlayConfig::settings_render_helper},
        {"myquick_panel_render_helper", &DebugUiOverlayConfig::myquick_panel_render_helper},
        {"myquick_panel_modal_loop_helper", &DebugUiOverlayConfig::myquick_panel_modal_loop_helper},
        {"settings_section_header_text_caller", &DebugUiOverlayConfig::settings_section_header_text_caller},
        {"settings_panel_title_text_caller", &DebugUiOverlayConfig::settings_panel_title_text_caller},
        {"settings_control_label_text_caller_primary", &DebugUiOverlayConfig::settings_control_label_text_caller_primary},
        {"settings_control_label_text_caller_secondary", &DebugUiOverlayConfig::settings_control_label_text_caller_secondary},
        {"simple_menu_modal_loop_helper", &DebugUiOverlayConfig::simple_menu_modal_loop_helper},
        {"simple_menu_vftable", &DebugUiOverlayConfig::simple_menu_vftable},
        {"msgbox_content_left_padding_global", &DebugUiOverlayConfig::msgbox_content_left_padding_global},
        {"msgbox_content_top_padding_global", &DebugUiOverlayConfig::msgbox_content_top_padding_global},
        {"msgbox_vftable", &DebugUiOverlayConfig::msgbox_vftable},
        {"settings_rollout_vftable", &DebugUiOverlayConfig::settings_rollout_vftable},
    };

    for (const auto& field : kRequiredAddressFields) {
        if (!ReadRequiredAddress(overlay, field.key, &(parsed.*(field.member)), error_message)) {
            return false;
        }
    }

    static constexpr AddressField kOptionalAddressFields[] = {
        {"main_menu_render_helper", &DebugUiOverlayConfig::main_menu_render_helper},
        {"hall_of_fame_render_helper", &DebugUiOverlayConfig::hall_of_fame_render_helper},
        {"hall_of_fame_vftable", &DebugUiOverlayConfig::hall_of_fame_vftable},
        {"spell_picker_render_helper", &DebugUiOverlayConfig::spell_picker_render_helper},
        {"spell_picker_vftable", &DebugUiOverlayConfig::spell_picker_vftable},
    };

    for (const auto& field : kOptionalAddressFields) {
        if (!ReadOptionalAddress(overlay, field.key, &(parsed.*(field.member)), error_message)) {
            return false;
        }
    }

    static constexpr SizeField kRequiredSizeFields[] = {
        {"string_object_text_pointer_offset", &DebugUiOverlayConfig::string_object_text_pointer_offset},
        {"string_object_length_offset", &DebugUiOverlayConfig::string_object_length_offset},
        {"ui_render_context_base_x_offset", &DebugUiOverlayConfig::ui_render_context_base_x_offset},
        {"ui_render_context_base_y_offset", &DebugUiOverlayConfig::ui_render_context_base_y_offset},
        {"title_main_menu_button_array_offset", &DebugUiOverlayConfig::title_main_menu_button_array_offset},
        {"title_main_menu_button_stride", &DebugUiOverlayConfig::title_main_menu_button_stride},
        {"title_main_menu_button_count", &DebugUiOverlayConfig::title_main_menu_button_count},
        {"title_main_menu_button_left_offset", &DebugUiOverlayConfig::title_main_menu_button_left_offset},
        {"title_main_menu_button_top_offset", &DebugUiOverlayConfig::title_main_menu_button_top_offset},
        {"title_main_menu_button_width_offset", &DebugUiOverlayConfig::title_main_menu_button_width_offset},
        {"title_main_menu_button_height_offset", &DebugUiOverlayConfig::title_main_menu_button_height_offset},
        {"title_main_menu_mode_offset", &DebugUiOverlayConfig::title_main_menu_mode_offset},
        {"myquick_panel_left_offset", &DebugUiOverlayConfig::myquick_panel_left_offset},
        {"myquick_panel_top_offset", &DebugUiOverlayConfig::myquick_panel_top_offset},
        {"myquick_panel_width_offset", &DebugUiOverlayConfig::myquick_panel_width_offset},
        {"myquick_panel_height_offset", &DebugUiOverlayConfig::myquick_panel_height_offset},
        {"myquick_panel_builder_owner_offset", &DebugUiOverlayConfig::myquick_panel_builder_owner_offset},
        {"myquick_panel_builder_offset", &DebugUiOverlayConfig::myquick_panel_builder_offset},
        {"myquick_panel_builder_root_control_offset", &DebugUiOverlayConfig::myquick_panel_builder_root_control_offset},
        {"myquick_panel_builder_widget_entries_begin_offset", &DebugUiOverlayConfig::myquick_panel_builder_widget_entries_begin_offset},
        {"myquick_panel_builder_widget_entries_end_offset", &DebugUiOverlayConfig::myquick_panel_builder_widget_entries_end_offset},
        {"myquick_panel_builder_widget_entry_stride", &DebugUiOverlayConfig::myquick_panel_builder_widget_entry_stride},
        {"myquick_panel_builder_widget_entry_primary_offset", &DebugUiOverlayConfig::myquick_panel_builder_widget_entry_primary_offset},
        {"myquick_panel_builder_widget_entry_secondary_offset", &DebugUiOverlayConfig::myquick_panel_builder_widget_entry_secondary_offset},
        {"myquick_panel_widget_parent_offset", &DebugUiOverlayConfig::myquick_panel_widget_parent_offset},
        {"ui_widget_parent_offset", &DebugUiOverlayConfig::ui_widget_parent_offset},
        {"ui_rollout_parent_offset", &DebugUiOverlayConfig::ui_rollout_parent_offset},
        {"ui_owner_control_action_vtable_byte_offset", &DebugUiOverlayConfig::ui_owner_control_action_vtable_byte_offset},
        {"dark_cloud_browser_control_left_offset", &DebugUiOverlayConfig::dark_cloud_browser_control_left_offset},
        {"dark_cloud_browser_control_top_offset", &DebugUiOverlayConfig::dark_cloud_browser_control_top_offset},
        {"dark_cloud_browser_control_width_offset", &DebugUiOverlayConfig::dark_cloud_browser_control_width_offset},
        {"dark_cloud_browser_control_height_offset", &DebugUiOverlayConfig::dark_cloud_browser_control_height_offset},
        {"dark_cloud_browser_text_owner_offset", &DebugUiOverlayConfig::dark_cloud_browser_text_owner_offset},
        {"dark_cloud_browser_primary_action_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_primary_action_control_offset},
        {"dark_cloud_browser_secondary_action_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_secondary_action_control_offset},
        {"dark_cloud_browser_aux_left_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_aux_left_control_offset},
        {"dark_cloud_browser_aux_right_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_aux_right_control_offset},
        {"dark_cloud_browser_recent_tab_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_recent_tab_control_offset},
        {"dark_cloud_browser_online_levels_tab_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_online_levels_tab_control_offset},
        {"dark_cloud_browser_my_levels_tab_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_my_levels_tab_control_offset},
        {"dark_cloud_browser_footer_action_control_offset", &DebugUiOverlayConfig::dark_cloud_browser_footer_action_control_offset},
        {"dark_cloud_browser_modal_button_rollout_offset", &DebugUiOverlayConfig::dark_cloud_browser_modal_button_rollout_offset},
        {"dark_cloud_browser_modal_header_group_left_offset", &DebugUiOverlayConfig::dark_cloud_browser_modal_header_group_left_offset},
        {"dark_cloud_browser_modal_header_group_top_offset", &DebugUiOverlayConfig::dark_cloud_browser_modal_header_group_top_offset},
        {"dark_cloud_browser_modal_header_group_width_offset", &DebugUiOverlayConfig::dark_cloud_browser_modal_header_group_width_offset},
        {"dark_cloud_browser_modal_header_group_height_offset", &DebugUiOverlayConfig::dark_cloud_browser_modal_header_group_height_offset},
        {"dark_cloud_browser_list_widget_offset", &DebugUiOverlayConfig::dark_cloud_browser_list_widget_offset},
        {"dark_cloud_browser_list_widget_entry_count_offset", &DebugUiOverlayConfig::dark_cloud_browser_list_widget_entry_count_offset},
        {"dark_cloud_browser_list_widget_max_visible_rows_offset", &DebugUiOverlayConfig::dark_cloud_browser_list_widget_max_visible_rows_offset},
        {"dark_cloud_browser_list_widget_row_height_offset", &DebugUiOverlayConfig::dark_cloud_browser_list_widget_row_height_offset},
        {"dark_cloud_browser_list_widget_row_data_base_offset", &DebugUiOverlayConfig::dark_cloud_browser_list_widget_row_data_base_offset},
        {"settings_control_list_count_offset", &DebugUiOverlayConfig::settings_control_list_count_offset},
        {"settings_control_list_entries_offset", &DebugUiOverlayConfig::settings_control_list_entries_offset},
        {"settings_control_child_count_offset", &DebugUiOverlayConfig::settings_control_child_count_offset},
        {"settings_control_child_list_offset", &DebugUiOverlayConfig::settings_control_child_list_offset},
        {"settings_control_left_offset", &DebugUiOverlayConfig::settings_control_left_offset},
        {"settings_control_top_offset", &DebugUiOverlayConfig::settings_control_top_offset},
        {"settings_control_width_offset", &DebugUiOverlayConfig::settings_control_width_offset},
        {"settings_control_height_offset", &DebugUiOverlayConfig::settings_control_height_offset},
        {"settings_control_label_pointer_offset", &DebugUiOverlayConfig::settings_control_label_pointer_offset},
        {"settings_control_label_enabled_offset", &DebugUiOverlayConfig::settings_control_label_enabled_offset},
        {"settings_control_enabled_byte_offset", &DebugUiOverlayConfig::settings_control_enabled_byte_offset},
        {"settings_control_dispatch_offset", &DebugUiOverlayConfig::settings_control_dispatch_offset},
        {"settings_control_callback_owner_offset", &DebugUiOverlayConfig::settings_control_callback_owner_offset},
        {"settings_done_button_control_offset", &DebugUiOverlayConfig::settings_done_button_control_offset},
        {"settings_rollout_dispatch_offset", &DebugUiOverlayConfig::settings_rollout_dispatch_offset},
        {"settings_controls_guard_pointer_offset", &DebugUiOverlayConfig::settings_controls_guard_pointer_offset},
        {"settings_controls_expected_guard_offset", &DebugUiOverlayConfig::settings_controls_expected_guard_offset},
        {"control_noarg_owner_offset", &DebugUiOverlayConfig::control_noarg_owner_offset},
        {"control_noarg_context_offset", &DebugUiOverlayConfig::control_noarg_context_offset},
        {"control_noarg_callback_offset", &DebugUiOverlayConfig::control_noarg_callback_offset},
        {"settings_section_widget_left_offset", &DebugUiOverlayConfig::settings_section_widget_left_offset},
        {"settings_section_widget_top_offset", &DebugUiOverlayConfig::settings_section_widget_top_offset},
        {"settings_section_widget_width_offset", &DebugUiOverlayConfig::settings_section_widget_width_offset},
        {"settings_section_widget_height_offset", &DebugUiOverlayConfig::settings_section_widget_height_offset},
        {"simple_menu_left_offset", &DebugUiOverlayConfig::simple_menu_left_offset},
        {"simple_menu_top_offset", &DebugUiOverlayConfig::simple_menu_top_offset},
        {"simple_menu_width_offset", &DebugUiOverlayConfig::simple_menu_width_offset},
        {"simple_menu_height_offset", &DebugUiOverlayConfig::simple_menu_height_offset},
        {"simple_menu_control_list_offset", &DebugUiOverlayConfig::simple_menu_control_list_offset},
        {"simple_menu_control_list_count_offset", &DebugUiOverlayConfig::simple_menu_control_list_count_offset},
        {"simple_menu_control_list_entries_offset", &DebugUiOverlayConfig::simple_menu_control_list_entries_offset},
        {"simple_menu_control_left_offset", &DebugUiOverlayConfig::simple_menu_control_left_offset},
        {"simple_menu_control_top_offset", &DebugUiOverlayConfig::simple_menu_control_top_offset},
        {"simple_menu_control_width_offset", &DebugUiOverlayConfig::simple_menu_control_width_offset},
        {"simple_menu_control_height_offset", &DebugUiOverlayConfig::simple_menu_control_height_offset},
        {"msgbox_panel_left_offset", &DebugUiOverlayConfig::msgbox_panel_left_offset},
        {"msgbox_panel_top_offset", &DebugUiOverlayConfig::msgbox_panel_top_offset},
        {"msgbox_panel_width_offset", &DebugUiOverlayConfig::msgbox_panel_width_offset},
        {"msgbox_panel_height_offset", &DebugUiOverlayConfig::msgbox_panel_height_offset},
        {"msgbox_primary_button_left_offset", &DebugUiOverlayConfig::msgbox_primary_button_left_offset},
        {"msgbox_primary_button_top_offset", &DebugUiOverlayConfig::msgbox_primary_button_top_offset},
        {"msgbox_primary_button_width_offset", &DebugUiOverlayConfig::msgbox_primary_button_width_offset},
        {"msgbox_primary_button_height_offset", &DebugUiOverlayConfig::msgbox_primary_button_height_offset},
        {"msgbox_primary_button_control_offset", &DebugUiOverlayConfig::msgbox_primary_button_control_offset},
        {"msgbox_secondary_button_left_offset", &DebugUiOverlayConfig::msgbox_secondary_button_left_offset},
        {"msgbox_secondary_button_top_offset", &DebugUiOverlayConfig::msgbox_secondary_button_top_offset},
        {"msgbox_secondary_button_half_width_offset", &DebugUiOverlayConfig::msgbox_secondary_button_half_width_offset},
        {"msgbox_secondary_button_half_height_offset", &DebugUiOverlayConfig::msgbox_secondary_button_half_height_offset},
        {"msgbox_secondary_button_control_offset", &DebugUiOverlayConfig::msgbox_secondary_button_control_offset},
        {"msgbox_primary_label_offset", &DebugUiOverlayConfig::msgbox_primary_label_offset},
        {"msgbox_secondary_label_offset", &DebugUiOverlayConfig::msgbox_secondary_label_offset},
        {"msgbox_line_list_offset", &DebugUiOverlayConfig::msgbox_line_list_offset},
        {"msgbox_line_list_count_offset", &DebugUiOverlayConfig::msgbox_line_list_count_offset},
        {"msgbox_line_list_entries_offset", &DebugUiOverlayConfig::msgbox_line_list_entries_offset},
        {"msgbox_line_wrapper_object_offset", &DebugUiOverlayConfig::msgbox_line_wrapper_object_offset},
        {"msgbox_line_height_offset", &DebugUiOverlayConfig::msgbox_line_height_offset},
    };

    for (const auto& field : kRequiredSizeFields) {
        if (!ReadRequiredSize(overlay, field.key, &(parsed.*(field.member)), error_message)) {
            return false;
        }
    }

    if (!ReadOptionalPositiveSize(overlay, "surface_range_slop", &parsed.surface_range_slop, error_message) ||
        !ReadOptionalPositiveSize(
            overlay,
            "max_tracked_elements_per_frame",
            &parsed.max_tracked_elements_per_frame,
            error_message) ||
        !ReadOptionalPositiveSize(overlay, "stack_scan_slots", &parsed.stack_scan_slots, error_message)) {
        return false;
    }

    *config = parsed;
    return true;
}

}  // namespace

bool InitializeDebugUiOverlayConfig(const std::filesystem::path& stage_runtime_directory) {
    std::scoped_lock lock(g_debug_ui_config_mutex);

    g_debug_ui_config = DebugUiOverlayConfig{};
    g_debug_ui_config_error.clear();
    g_debug_ui_config_loaded = false;

    if (!ParseDebugUiOverlayConfig(GetDebugUiOverlayConfigPath(stage_runtime_directory), &g_debug_ui_config, &g_debug_ui_config_error)) {
        return false;
    }

    g_debug_ui_config_loaded = true;
    return true;
}

void ShutdownDebugUiOverlayConfig() {
    std::scoped_lock lock(g_debug_ui_config_mutex);

    g_debug_ui_config = DebugUiOverlayConfig{};
    g_debug_ui_config_error.clear();
    g_debug_ui_config_loaded = false;
}

bool IsDebugUiOverlayConfigLoaded() {
    std::scoped_lock lock(g_debug_ui_config_mutex);
    return g_debug_ui_config_loaded;
}

const DebugUiOverlayConfig* TryGetDebugUiOverlayConfig() {
    std::scoped_lock lock(g_debug_ui_config_mutex);
    return g_debug_ui_config_loaded ? &g_debug_ui_config : nullptr;
}

std::string GetDebugUiOverlayConfigLoadError() {
    std::scoped_lock lock(g_debug_ui_config_mutex);
    return g_debug_ui_config_error;
}

std::filesystem::path GetDebugUiOverlayConfigPath(const std::filesystem::path& stage_runtime_directory) {
    return stage_runtime_directory / "config" / "debug-ui.ini";
}

}  // namespace sdmod
