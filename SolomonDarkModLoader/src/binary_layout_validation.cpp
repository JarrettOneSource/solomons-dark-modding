#include "binary_layout_internal.h"

#include <set>

namespace sdmod {

namespace {

bool IsKnownDispatchTiming(std::string_view value) {
    return value.empty() || value == "overlay_frame";
}

bool IsKnownDispatchKind(std::string_view value) {
    return value.empty() ||
           value == "owner_control" ||
           value == "owner_noarg" ||
           value == "owner_point_click" ||
           value == "control_child" ||
           value == "control_child_callback_owner" ||
           value == "control_noarg" ||
           value == "direct_write";
}

}  // namespace

bool ValidateBinaryLayout(const BinaryLayout& layout, std::string* error_message) {
    if (layout.binary_name.empty()) {
        if (error_message != nullptr) {
            *error_message = "Binary layout is missing [binary].name.";
        }
        return false;
    }

    if (layout.image_base == 0) {
        if (error_message != nullptr) {
            *error_message = "Binary layout is missing a non-zero [binary].image_base.";
        }
        return false;
    }

    std::set<std::string> known_surface_ids;
    for (const auto& surface : layout.ui_surfaces) {
        if (surface.id.empty()) {
            if (error_message != nullptr) {
                *error_message = "Binary layout contains a surface section with an empty id.";
            }
            return false;
        }

        if (!IsKnownDispatchTiming(surface.dispatch_timing)) {
            if (error_message != nullptr) {
                *error_message =
                    "Binary layout surface '" + surface.id + "' has an unknown dispatch_timing value '" +
                    surface.dispatch_timing + "'.";
            }
            return false;
        }

        known_surface_ids.insert(surface.id);
    }

    std::set<std::string> known_action_ids;
    for (const auto& action : layout.ui_actions) {
        if (action.id.empty()) {
            if (error_message != nullptr) {
                *error_message = "Binary layout contains an action section with an empty id.";
            }
            return false;
        }

        if (!action.surface_id.empty() && known_surface_ids.find(action.surface_id) == known_surface_ids.end()) {
            if (error_message != nullptr) {
                *error_message = "Binary layout action '" + action.id + "' references unknown surface '" + action.surface_id + "'.";
            }
            return false;
        }

        if (!IsKnownDispatchTiming(action.dispatch_timing)) {
            if (error_message != nullptr) {
                *error_message =
                    "Binary layout action '" + action.id + "' has an unknown dispatch_timing value '" +
                    action.dispatch_timing + "'.";
            }
            return false;
        }

        if (!IsKnownDispatchKind(action.dispatch_kind)) {
            if (error_message != nullptr) {
                *error_message =
                    "Binary layout action '" + action.id + "' has an unknown dispatch_kind value '" +
                    action.dispatch_kind + "'.";
            }
            return false;
        }

        known_action_ids.insert(action.id);
    }

    for (const auto& surface : layout.ui_surfaces) {
        for (const auto& action_id : surface.action_ids) {
            if (known_action_ids.find(action_id) == known_action_ids.end()) {
                if (error_message != nullptr) {
                    *error_message = "Binary layout surface '" + surface.id + "' references unknown action '" + action_id + "'.";
                }
                return false;
            }
        }
    }

    return true;
}

}  // namespace sdmod
