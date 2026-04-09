#include "debug_ui_config.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <map>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>

namespace sdmod {
namespace {

using IniSection = std::map<std::string, std::string>;
using IniDocument = std::map<std::string, IniSection>;

std::mutex g_debug_ui_config_mutex;
DebugUiOverlayConfig g_debug_ui_config;
std::string g_debug_ui_config_error;
bool g_debug_ui_config_loaded = false;

std::string Trim(std::string value) {
    const auto is_space = [](unsigned char ch) { return std::isspace(ch) != 0; };

    value.erase(
        value.begin(),
        std::find_if(value.begin(), value.end(), [&](char ch) { return !is_space(static_cast<unsigned char>(ch)); }));
    value.erase(
        std::find_if(value.rbegin(), value.rend(), [&](char ch) { return !is_space(static_cast<unsigned char>(ch)); }).base(),
        value.end());
    return value;
}

std::string ToLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool TryParseBoolean(std::string value, bool* parsed) {
    if (parsed == nullptr) {
        return false;
    }

    value = ToLower(Trim(std::move(value)));
    if (value == "1" || value == "true" || value == "yes" || value == "on") {
        *parsed = true;
        return true;
    }

    if (value == "0" || value == "false" || value == "no" || value == "off") {
        *parsed = false;
        return true;
    }

    return false;
}

std::optional<uintptr_t> TryParseAddress(std::string value) {
    value = Trim(std::move(value));
    if (value.empty()) {
        return std::nullopt;
    }

    const auto base = value.size() > 2 && value[0] == '0' && (value[1] == 'x' || value[1] == 'X') ? 16 : 10;
    char* end = nullptr;
    const auto parsed = std::strtoull(value.c_str(), &end, base);
    if (end == value.c_str() || *end != '\0') {
        return std::nullopt;
    }

    return static_cast<uintptr_t>(parsed);
}

std::optional<size_t> TryParseSize(std::string value) {
    auto parsed = TryParseAddress(std::move(value));
    if (!parsed.has_value()) {
        return std::nullopt;
    }

    return static_cast<size_t>(*parsed);
}

bool LoadIniDocument(const std::filesystem::path& path, IniDocument* document, std::string* error_message) {
    if (document == nullptr) {
        if (error_message != nullptr) {
            *error_message = "INI destination is null.";
        }
        return false;
    }

    std::ifstream stream(path, std::ios::in | std::ios::binary);
    if (!stream.is_open()) {
        if (error_message != nullptr) {
            *error_message = "Unable to open " + path.string();
        }
        return false;
    }

    document->clear();

    std::string current_section;
    std::string line;
    size_t line_number = 0;
    while (std::getline(stream, line)) {
        ++line_number;

        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }

        line = Trim(std::move(line));
        if (line.empty() || line[0] == ';' || line[0] == '#') {
            continue;
        }

        if (line.front() == '[') {
            if (line.back() != ']') {
                if (error_message != nullptr) {
                    *error_message = "Invalid section header at line " + std::to_string(line_number);
                }
                return false;
            }

            current_section = Trim(line.substr(1, line.size() - 2));
            if (current_section.empty()) {
                if (error_message != nullptr) {
                    *error_message = "Empty section header at line " + std::to_string(line_number);
                }
                return false;
            }

            (*document)[current_section];
            continue;
        }

        const auto separator = line.find('=');
        if (separator == std::string::npos) {
            if (error_message != nullptr) {
                *error_message = "Invalid key/value entry at line " + std::to_string(line_number);
            }
            return false;
        }

        if (current_section.empty()) {
            if (error_message != nullptr) {
                *error_message = "Key/value entry before any section at line " + std::to_string(line_number);
            }
            return false;
        }

        auto key = Trim(line.substr(0, separator));
        auto value = Trim(line.substr(separator + 1));
        if (key.empty()) {
            if (error_message != nullptr) {
                *error_message = "Empty key at line " + std::to_string(line_number);
            }
            return false;
        }

        (*document)[current_section][key] = value;
    }

    return true;
}

bool ParseDebugUiOverlayConfig(
    const std::filesystem::path& path,
    DebugUiOverlayConfig* config,
    std::string* error_message) {
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

    const auto enabled_it = overlay.find("enabled");
    if (enabled_it == overlay.end() || !TryParseBoolean(enabled_it->second, &parsed.enabled)) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].enabled value.";
        }
        return false;
    }

    const auto helper_it = overlay.find("text_draw_helper");
    if (helper_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].text_draw_helper.";
        }
        return false;
    }

    const auto parsed_helper = TryParseAddress(helper_it->second);
    if (!parsed_helper.has_value() || *parsed_helper == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].text_draw_helper value.";
        }
        return false;
    }
    parsed.text_draw_helper = *parsed_helper;

    const auto string_assign_it = overlay.find("string_assign_helper");
    if (string_assign_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].string_assign_helper.";
        }
        return false;
    }

    const auto parsed_string_assign = TryParseAddress(string_assign_it->second);
    if (!parsed_string_assign.has_value() || *parsed_string_assign == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].string_assign_helper value.";
        }
        return false;
    }
    parsed.string_assign_helper = *parsed_string_assign;

    const auto dialog_add_line_it = overlay.find("dialog_add_line_helper");
    if (dialog_add_line_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].dialog_add_line_helper.";
        }
        return false;
    }

    const auto parsed_dialog_add_line = TryParseAddress(dialog_add_line_it->second);
    if (!parsed_dialog_add_line.has_value() || *parsed_dialog_add_line == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].dialog_add_line_helper value.";
        }
        return false;
    }
    parsed.dialog_add_line_helper = *parsed_dialog_add_line;

    const auto dialog_primary_button_it = overlay.find("dialog_primary_button_helper");
    if (dialog_primary_button_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].dialog_primary_button_helper.";
        }
        return false;
    }

    const auto parsed_dialog_primary_button = TryParseAddress(dialog_primary_button_it->second);
    if (!parsed_dialog_primary_button.has_value() || *parsed_dialog_primary_button == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].dialog_primary_button_helper value.";
        }
        return false;
    }
    parsed.dialog_primary_button_helper = *parsed_dialog_primary_button;

    const auto dialog_secondary_button_it = overlay.find("dialog_secondary_button_helper");
    if (dialog_secondary_button_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].dialog_secondary_button_helper.";
        }
        return false;
    }

    const auto parsed_dialog_secondary_button = TryParseAddress(dialog_secondary_button_it->second);
    if (!parsed_dialog_secondary_button.has_value() || *parsed_dialog_secondary_button == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].dialog_secondary_button_helper value.";
        }
        return false;
    }
    parsed.dialog_secondary_button_helper = *parsed_dialog_secondary_button;

    const auto dialog_finalize_it = overlay.find("dialog_finalize_helper");
    if (dialog_finalize_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].dialog_finalize_helper.";
        }
        return false;
    }

    const auto parsed_dialog_finalize = TryParseAddress(dialog_finalize_it->second);
    if (!parsed_dialog_finalize.has_value() || *parsed_dialog_finalize == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].dialog_finalize_helper value.";
        }
        return false;
    }
    parsed.dialog_finalize_helper = *parsed_dialog_finalize;

    const auto exact_text_render_it = overlay.find("exact_text_render_helper");
    if (exact_text_render_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].exact_text_render_helper.";
        }
        return false;
    }

    const auto parsed_exact_text_render = TryParseAddress(exact_text_render_it->second);
    if (!parsed_exact_text_render.has_value() || *parsed_exact_text_render == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].exact_text_render_helper value.";
        }
        return false;
    }
    parsed.exact_text_render_helper = *parsed_exact_text_render;

    const auto browser_exact_text_render_it = overlay.find("dark_cloud_browser_exact_text_render_helper");
    if (browser_exact_text_render_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].dark_cloud_browser_exact_text_render_helper.";
        }
        return false;
    }

    const auto parsed_browser_exact_text_render = TryParseAddress(browser_exact_text_render_it->second);
    if (!parsed_browser_exact_text_render.has_value() || *parsed_browser_exact_text_render == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Debug UI config contains an invalid [overlay].dark_cloud_browser_exact_text_render_helper value.";
        }
        return false;
    }
    parsed.dark_cloud_browser_exact_text_render_helper = *parsed_browser_exact_text_render;

    const auto ui_labeled_control_render_it = overlay.find("ui_labeled_control_render_helper");
    if (ui_labeled_control_render_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].ui_labeled_control_render_helper.";
        }
        return false;
    }

    const auto parsed_ui_labeled_control_render = TryParseAddress(ui_labeled_control_render_it->second);
    if (!parsed_ui_labeled_control_render.has_value() || *parsed_ui_labeled_control_render == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].ui_labeled_control_render_helper value.";
        }
        return false;
    }
    parsed.ui_labeled_control_render_helper = *parsed_ui_labeled_control_render;

    const auto ui_labeled_control_alt_render_it = overlay.find("ui_labeled_control_alt_render_helper");
    if (ui_labeled_control_alt_render_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].ui_labeled_control_alt_render_helper.";
        }
        return false;
    }

    const auto parsed_ui_labeled_control_alt_render = TryParseAddress(ui_labeled_control_alt_render_it->second);
    if (!parsed_ui_labeled_control_alt_render.has_value() || *parsed_ui_labeled_control_alt_render == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Debug UI config contains an invalid [overlay].ui_labeled_control_alt_render_helper value.";
        }
        return false;
    }
    parsed.ui_labeled_control_alt_render_helper = *parsed_ui_labeled_control_alt_render;

    const auto ui_unlabeled_control_render_it = overlay.find("ui_unlabeled_control_render_helper");
    if (ui_unlabeled_control_render_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].ui_unlabeled_control_render_helper.";
        }
        return false;
    }

    const auto parsed_ui_unlabeled_control_render = TryParseAddress(ui_unlabeled_control_render_it->second);
    if (!parsed_ui_unlabeled_control_render.has_value() || *parsed_ui_unlabeled_control_render == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Debug UI config contains an invalid [overlay].ui_unlabeled_control_render_helper value.";
        }
        return false;
    }
    parsed.ui_unlabeled_control_render_helper = *parsed_ui_unlabeled_control_render;

    const auto ui_panel_render_it = overlay.find("ui_panel_render_helper");
    if (ui_panel_render_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].ui_panel_render_helper.";
        }
        return false;
    }

    const auto parsed_ui_panel_render = TryParseAddress(ui_panel_render_it->second);
    if (!parsed_ui_panel_render.has_value() || *parsed_ui_panel_render == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].ui_panel_render_helper value.";
        }
        return false;
    }
    parsed.ui_panel_render_helper = *parsed_ui_panel_render;

    const auto ui_rect_dispatch_it = overlay.find("ui_rect_dispatch_helper");
    if (ui_rect_dispatch_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].ui_rect_dispatch_helper.";
        }
        return false;
    }

    const auto parsed_ui_rect_dispatch = TryParseAddress(ui_rect_dispatch_it->second);
    if (!parsed_ui_rect_dispatch.has_value() || *parsed_ui_rect_dispatch == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].ui_rect_dispatch_helper value.";
        }
        return false;
    }
    parsed.ui_rect_dispatch_helper = *parsed_ui_rect_dispatch;

    const auto glyph_draw_it = overlay.find("glyph_draw_helper");
    if (glyph_draw_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].glyph_draw_helper.";
        }
        return false;
    }

    const auto parsed_glyph_draw = TryParseAddress(glyph_draw_it->second);
    if (!parsed_glyph_draw.has_value() || *parsed_glyph_draw == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].glyph_draw_helper value.";
        }
        return false;
    }
    parsed.glyph_draw_helper = *parsed_glyph_draw;

    const auto text_quad_draw_it = overlay.find("text_quad_draw_helper");
    if (text_quad_draw_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].text_quad_draw_helper.";
        }
        return false;
    }

    const auto parsed_text_quad_draw = TryParseAddress(text_quad_draw_it->second);
    if (!parsed_text_quad_draw.has_value() || *parsed_text_quad_draw == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].text_quad_draw_helper value.";
        }
        return false;
    }
    parsed.text_quad_draw_helper = *parsed_text_quad_draw;

    const auto device_global_it = overlay.find("device_pointer_global");
    if (device_global_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].device_pointer_global.";
        }
        return false;
    }

    const auto parsed_device_global = TryParseAddress(device_global_it->second);
    if (!parsed_device_global.has_value() || *parsed_device_global == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].device_pointer_global value.";
        }
        return false;
    }
    parsed.device_pointer_global = *parsed_device_global;

    const auto parse_required_address = [&](const char* key, uintptr_t* destination) {
        const auto value_it = overlay.find(key);
        if (value_it == overlay.end()) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config is missing [overlay]." + std::string(key) + ".";
            }
            return false;
        }

        const auto parsed_value = TryParseAddress(value_it->second);
        if (!parsed_value.has_value() || *parsed_value == 0) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
            }
            return false;
        }

        *destination = *parsed_value;
        return true;
    };

    if (!parse_required_address("ui_render_context_global", &parsed.ui_render_context_global) ||
        !parse_required_address("title_main_menu_vftable", &parsed.title_main_menu_vftable) ||
        !parse_required_address("myquick_panel_vftable", &parsed.myquick_panel_vftable) ||
        !parse_required_address("dark_cloud_browser_render_helper", &parsed.dark_cloud_browser_render_helper) ||
        !parse_required_address("dark_cloud_browser_vftable", &parsed.dark_cloud_browser_vftable) ||
        !parse_required_address(
            "dark_cloud_browser_modal_header_text_caller",
            &parsed.dark_cloud_browser_modal_header_text_caller) ||
        !parse_required_address("settings_render_helper", &parsed.settings_render_helper) ||
        !parse_required_address("myquick_panel_render_helper", &parsed.myquick_panel_render_helper) ||
        !parse_required_address("myquick_panel_modal_loop_helper", &parsed.myquick_panel_modal_loop_helper) ||
        !parse_required_address("settings_section_header_text_caller", &parsed.settings_section_header_text_caller) ||
        !parse_required_address("settings_panel_title_text_caller", &parsed.settings_panel_title_text_caller) ||
        !parse_required_address(
            "settings_control_label_text_caller_primary",
            &parsed.settings_control_label_text_caller_primary) ||
        !parse_required_address(
            "settings_control_label_text_caller_secondary",
            &parsed.settings_control_label_text_caller_secondary) ||
        !parse_required_address("simple_menu_modal_loop_helper", &parsed.simple_menu_modal_loop_helper) ||
        !parse_required_address("simple_menu_vftable", &parsed.simple_menu_vftable) ||
        !parse_required_address("msgbox_content_left_padding_global", &parsed.msgbox_content_left_padding_global) ||
        !parse_required_address("msgbox_content_top_padding_global", &parsed.msgbox_content_top_padding_global)) {
        return false;
    }

    const auto parse_optional_address = [&](const char* key, uintptr_t* destination) {
        const auto value_it = overlay.find(key);
        if (value_it == overlay.end()) {
            return;
        }
        const auto parsed_value = TryParseAddress(value_it->second);
        if (parsed_value.has_value()) {
            *destination = *parsed_value;
        }
    };

    parse_optional_address("main_menu_render_helper", &parsed.main_menu_render_helper);
    parse_optional_address("hall_of_fame_render_helper", &parsed.hall_of_fame_render_helper);
    parse_optional_address("hall_of_fame_vftable", &parsed.hall_of_fame_vftable);
    parse_optional_address("spell_picker_render_helper", &parsed.spell_picker_render_helper);
    parse_optional_address("spell_picker_vftable", &parsed.spell_picker_vftable);


    const auto msgbox_vftable_it = overlay.find("msgbox_vftable");
    if (msgbox_vftable_it == overlay.end()) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config is missing [overlay].msgbox_vftable.";
        }
        return false;
    }

    const auto parsed_msgbox_vftable = TryParseAddress(msgbox_vftable_it->second);
    if (!parsed_msgbox_vftable.has_value() || *parsed_msgbox_vftable == 0) {
        if (error_message != nullptr) {
            *error_message = "Debug UI config contains an invalid [overlay].msgbox_vftable value.";
        }
        return false;
    }
    parsed.msgbox_vftable = *parsed_msgbox_vftable;

    const auto parse_required_size = [&](const char* key, size_t* destination) {
        const auto value_it = overlay.find(key);
        if (value_it == overlay.end()) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config is missing [overlay]." + std::string(key) + ".";
            }
            return false;
        }

        const auto parsed_value = TryParseSize(value_it->second);
        if (!parsed_value.has_value()) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config contains an invalid [overlay]." + std::string(key) + " value.";
            }
            return false;
        }

        *destination = *parsed_value;
        return true;
    };

    if (!parse_required_size("title_main_menu_button_array_offset", &parsed.title_main_menu_button_array_offset) ||
        !parse_required_size("title_main_menu_button_stride", &parsed.title_main_menu_button_stride) ||
        !parse_required_size("title_main_menu_button_count", &parsed.title_main_menu_button_count) ||
        !parse_required_size("title_main_menu_button_left_offset", &parsed.title_main_menu_button_left_offset) ||
        !parse_required_size("title_main_menu_button_top_offset", &parsed.title_main_menu_button_top_offset) ||
        !parse_required_size("title_main_menu_button_width_offset", &parsed.title_main_menu_button_width_offset) ||
        !parse_required_size("title_main_menu_button_height_offset", &parsed.title_main_menu_button_height_offset) ||
        !parse_required_size("title_main_menu_mode_offset", &parsed.title_main_menu_mode_offset) ||
        !parse_required_size("myquick_panel_left_offset", &parsed.myquick_panel_left_offset) ||
        !parse_required_size("myquick_panel_top_offset", &parsed.myquick_panel_top_offset) ||
        !parse_required_size("myquick_panel_width_offset", &parsed.myquick_panel_width_offset) ||
        !parse_required_size("myquick_panel_height_offset", &parsed.myquick_panel_height_offset) ||
        !parse_required_size("myquick_panel_builder_owner_offset", &parsed.myquick_panel_builder_owner_offset) ||
        !parse_required_size("myquick_panel_builder_offset", &parsed.myquick_panel_builder_offset) ||
        !parse_required_size(
            "myquick_panel_builder_root_control_offset",
            &parsed.myquick_panel_builder_root_control_offset) ||
        !parse_required_size(
            "myquick_panel_builder_widget_entries_begin_offset",
            &parsed.myquick_panel_builder_widget_entries_begin_offset) ||
        !parse_required_size(
            "myquick_panel_builder_widget_entries_end_offset",
            &parsed.myquick_panel_builder_widget_entries_end_offset) ||
        !parse_required_size(
            "myquick_panel_builder_widget_entry_stride",
            &parsed.myquick_panel_builder_widget_entry_stride) ||
        !parse_required_size(
            "myquick_panel_builder_widget_entry_primary_offset",
            &parsed.myquick_panel_builder_widget_entry_primary_offset) ||
        !parse_required_size(
            "myquick_panel_builder_widget_entry_secondary_offset",
            &parsed.myquick_panel_builder_widget_entry_secondary_offset) ||
        !parse_required_size("myquick_panel_widget_parent_offset", &parsed.myquick_panel_widget_parent_offset) ||
        !parse_required_size("ui_widget_parent_offset", &parsed.ui_widget_parent_offset) ||
        !parse_required_size("dark_cloud_browser_control_left_offset", &parsed.dark_cloud_browser_control_left_offset) ||
        !parse_required_size("dark_cloud_browser_control_top_offset", &parsed.dark_cloud_browser_control_top_offset) ||
        !parse_required_size("dark_cloud_browser_control_width_offset", &parsed.dark_cloud_browser_control_width_offset) ||
        !parse_required_size("dark_cloud_browser_control_height_offset", &parsed.dark_cloud_browser_control_height_offset) ||
        !parse_required_size("dark_cloud_browser_text_owner_offset", &parsed.dark_cloud_browser_text_owner_offset) ||
        !parse_required_size(
            "dark_cloud_browser_primary_action_control_offset",
            &parsed.dark_cloud_browser_primary_action_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_secondary_action_control_offset",
            &parsed.dark_cloud_browser_secondary_action_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_aux_left_control_offset",
            &parsed.dark_cloud_browser_aux_left_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_aux_right_control_offset",
            &parsed.dark_cloud_browser_aux_right_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_recent_tab_control_offset",
            &parsed.dark_cloud_browser_recent_tab_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_online_levels_tab_control_offset",
            &parsed.dark_cloud_browser_online_levels_tab_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_my_levels_tab_control_offset",
            &parsed.dark_cloud_browser_my_levels_tab_control_offset) ||
        !parse_required_size(
            "dark_cloud_browser_footer_action_control_offset",
            &parsed.dark_cloud_browser_footer_action_control_offset) ||
        !parse_required_size("settings_control_list_count_offset", &parsed.settings_control_list_count_offset) ||
        !parse_required_size("settings_control_list_entries_offset", &parsed.settings_control_list_entries_offset) ||
        !parse_required_size("settings_control_child_count_offset", &parsed.settings_control_child_count_offset) ||
        !parse_required_size("settings_control_child_list_offset", &parsed.settings_control_child_list_offset) ||
        !parse_required_size("settings_control_left_offset", &parsed.settings_control_left_offset) ||
        !parse_required_size("settings_control_top_offset", &parsed.settings_control_top_offset) ||
        !parse_required_size("settings_control_width_offset", &parsed.settings_control_width_offset) ||
        !parse_required_size("settings_control_height_offset", &parsed.settings_control_height_offset) ||
        !parse_required_size("settings_control_label_pointer_offset", &parsed.settings_control_label_pointer_offset) ||
        !parse_required_size("settings_control_label_enabled_offset", &parsed.settings_control_label_enabled_offset) ||
        !parse_required_size("settings_control_dispatch_offset", &parsed.settings_control_dispatch_offset) ||
        !parse_required_size("settings_done_button_control_offset", &parsed.settings_done_button_control_offset) ||
        !parse_required_address("settings_rollout_vftable", &parsed.settings_rollout_vftable) ||
        !parse_required_size("settings_rollout_dispatch_offset", &parsed.settings_rollout_dispatch_offset) ||
        !parse_required_size("settings_section_widget_left_offset", &parsed.settings_section_widget_left_offset) ||
        !parse_required_size("settings_section_widget_top_offset", &parsed.settings_section_widget_top_offset) ||
        !parse_required_size("settings_section_widget_width_offset", &parsed.settings_section_widget_width_offset) ||
        !parse_required_size("settings_section_widget_height_offset", &parsed.settings_section_widget_height_offset) ||
        !parse_required_size("simple_menu_left_offset", &parsed.simple_menu_left_offset) ||
        !parse_required_size("simple_menu_top_offset", &parsed.simple_menu_top_offset) ||
        !parse_required_size("simple_menu_width_offset", &parsed.simple_menu_width_offset) ||
        !parse_required_size("simple_menu_height_offset", &parsed.simple_menu_height_offset) ||
        !parse_required_size("simple_menu_control_list_offset", &parsed.simple_menu_control_list_offset) ||
        !parse_required_size("simple_menu_control_list_count_offset", &parsed.simple_menu_control_list_count_offset) ||
        !parse_required_size(
            "simple_menu_control_list_entries_offset",
            &parsed.simple_menu_control_list_entries_offset) ||
        !parse_required_size("simple_menu_control_left_offset", &parsed.simple_menu_control_left_offset) ||
        !parse_required_size("simple_menu_control_top_offset", &parsed.simple_menu_control_top_offset) ||
        !parse_required_size("simple_menu_control_width_offset", &parsed.simple_menu_control_width_offset) ||
        !parse_required_size("simple_menu_control_height_offset", &parsed.simple_menu_control_height_offset) ||
        !parse_required_size("msgbox_panel_left_offset", &parsed.msgbox_panel_left_offset) ||
        !parse_required_size("msgbox_panel_top_offset", &parsed.msgbox_panel_top_offset) ||
        !parse_required_size("msgbox_panel_width_offset", &parsed.msgbox_panel_width_offset) ||
        !parse_required_size("msgbox_panel_height_offset", &parsed.msgbox_panel_height_offset) ||
        !parse_required_size("msgbox_primary_button_left_offset", &parsed.msgbox_primary_button_left_offset) ||
        !parse_required_size("msgbox_primary_button_top_offset", &parsed.msgbox_primary_button_top_offset) ||
        !parse_required_size("msgbox_primary_button_width_offset", &parsed.msgbox_primary_button_width_offset) ||
        !parse_required_size("msgbox_primary_button_height_offset", &parsed.msgbox_primary_button_height_offset) ||
        !parse_required_size("msgbox_primary_button_control_offset", &parsed.msgbox_primary_button_control_offset) ||
        !parse_required_size("msgbox_secondary_button_left_offset", &parsed.msgbox_secondary_button_left_offset) ||
        !parse_required_size("msgbox_secondary_button_top_offset", &parsed.msgbox_secondary_button_top_offset) ||
        !parse_required_size(
            "msgbox_secondary_button_half_width_offset",
            &parsed.msgbox_secondary_button_half_width_offset) ||
        !parse_required_size(
            "msgbox_secondary_button_half_height_offset",
            &parsed.msgbox_secondary_button_half_height_offset) ||
        !parse_required_size("msgbox_secondary_button_control_offset", &parsed.msgbox_secondary_button_control_offset) ||
        !parse_required_size("msgbox_primary_label_offset", &parsed.msgbox_primary_label_offset) ||
        !parse_required_size("msgbox_secondary_label_offset", &parsed.msgbox_secondary_label_offset) ||
        !parse_required_size("msgbox_line_list_offset", &parsed.msgbox_line_list_offset) ||
        !parse_required_size("msgbox_line_list_count_offset", &parsed.msgbox_line_list_count_offset) ||
        !parse_required_size("msgbox_line_list_entries_offset", &parsed.msgbox_line_list_entries_offset) ||
        !parse_required_size("msgbox_line_wrapper_object_offset", &parsed.msgbox_line_wrapper_object_offset) ||
        !parse_required_size("msgbox_line_height_offset", &parsed.msgbox_line_height_offset)) {
        return false;
    }

    const auto slop_it = overlay.find("surface_range_slop");
    if (slop_it != overlay.end()) {
        const auto parsed_slop = TryParseSize(slop_it->second);
        if (!parsed_slop.has_value() || *parsed_slop == 0) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config contains an invalid [overlay].surface_range_slop value.";
            }
            return false;
        }
        parsed.surface_range_slop = *parsed_slop;
    }

    const auto max_it = overlay.find("max_tracked_elements_per_frame");
    if (max_it != overlay.end()) {
        const auto parsed_max = TryParseSize(max_it->second);
        if (!parsed_max.has_value() || *parsed_max == 0) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config contains an invalid [overlay].max_tracked_elements_per_frame value.";
            }
            return false;
        }
        parsed.max_tracked_elements_per_frame = *parsed_max;
    }

    const auto stack_scan_it = overlay.find("stack_scan_slots");
    if (stack_scan_it != overlay.end()) {
        const auto parsed_stack_scan_slots = TryParseSize(stack_scan_it->second);
        if (!parsed_stack_scan_slots.has_value() || *parsed_stack_scan_slots == 0) {
            if (error_message != nullptr) {
                *error_message = "Debug UI config contains an invalid [overlay].stack_scan_slots value.";
            }
            return false;
        }
        parsed.stack_scan_slots = *parsed_stack_scan_slots;
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
