#include "lua_ui_runtime.h"

#include "logger.h"

#include <Windowsx.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <deque>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

constexpr std::size_t kMaximumPendingActions = 128;

struct LuaUiElementState {
    std::uint64_t handle = 0;
    std::uint64_t parent_handle = 0;
    LuaUiElementDefinition definition;
};

struct LuaUiSurfaceState {
    std::uint64_t handle = 0;
    std::string mod_id;
    LuaUiSurfaceDefinition definition;
    bool visible = false;
    std::uint64_t focused_button_handle = 0;
    std::vector<LuaUiElementState> elements;
};

struct LuaUiRuntimeState {
    bool initialized = false;
    std::uint64_t next_handle = 1;
    std::uint64_t next_action_request_id = 1;
    std::uint32_t viewport_width = 0;
    std::uint32_t viewport_height = 0;
    std::vector<std::uint64_t> surface_order;
    std::unordered_map<std::uint64_t, LuaUiSurfaceState> surfaces;
    std::deque<LuaUiPendingAction> pending_actions;
    std::mutex mutex;
};

LuaUiRuntimeState g_lua_ui_runtime;

void SetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

bool IsValidIdentifier(std::string_view value) {
    if (value.empty() || value.size() > kLuaUiMaximumIdentifierBytes) {
        return false;
    }
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return std::islower(character) != 0 || std::isdigit(character) != 0 ||
            character == '_' || character == '-' || character == '.';
    });
}

bool IsValidRect(const LuaUiRect& rect) {
    return std::isfinite(rect.x) && std::isfinite(rect.y) &&
        std::isfinite(rect.width) && std::isfinite(rect.height) &&
        rect.x >= 0.0f && rect.y >= 0.0f && rect.width > 0.0f &&
        rect.height > 0.0f && rect.x + rect.width <= 1.0f &&
        rect.y + rect.height <= 1.0f;
}

LuaUiSurfaceState* FindOwnedSurfaceLocked(
    std::string_view mod_id,
    std::uint64_t handle) {
    const auto found = g_lua_ui_runtime.surfaces.find(handle);
    if (found == g_lua_ui_runtime.surfaces.end() ||
        found->second.mod_id != mod_id) {
        return nullptr;
    }
    return &found->second;
}

LuaUiElementState* FindOwnedElementLocked(
    std::string_view mod_id,
    std::uint64_t handle,
    LuaUiSurfaceState** surface_out) {
    for (auto order = g_lua_ui_runtime.surface_order.rbegin();
         order != g_lua_ui_runtime.surface_order.rend(); ++order) {
        const auto entry = g_lua_ui_runtime.surfaces.find(*order);
        if (entry == g_lua_ui_runtime.surfaces.end()) {
            continue;
        }
        auto& surface = entry->second;
        if (surface.mod_id != mod_id) {
            continue;
        }
        const auto found = std::find_if(
            surface.elements.begin(),
            surface.elements.end(),
            [handle](const LuaUiElementState& element) {
                return element.handle == handle;
            });
        if (found != surface.elements.end()) {
            if (surface_out != nullptr) {
                *surface_out = &surface;
            }
            return &*found;
        }
    }
    return nullptr;
}

std::size_t CountElements(
    const LuaUiSurfaceState& surface,
    LuaUiElementKind kind) {
    return static_cast<std::size_t>(std::count_if(
        surface.elements.begin(),
        surface.elements.end(),
        [kind](const LuaUiElementState& element) {
            return element.definition.kind == kind;
        }));
}

std::size_t CountTextBytes(const LuaUiSurfaceState& surface) {
    std::size_t bytes = surface.definition.title.size();
    for (const auto& element : surface.elements) {
        bytes += element.definition.text.size();
    }
    return bytes;
}

#include "lua_ui_runtime/input_helpers.inl"

LuaUiSurfaceSnapshot CopySurface(const LuaUiSurfaceState& source) {
    LuaUiSurfaceSnapshot snapshot;
    snapshot.handle = source.handle;
    snapshot.mod_id = source.mod_id;
    snapshot.id = source.definition.id;
    snapshot.title = source.definition.title;
    snapshot.rect = source.definition.rect;
    snapshot.modal = source.definition.modal;
    snapshot.close_on_escape = source.definition.close_on_escape;
    snapshot.visible = source.visible;
    snapshot.focused_button_handle = source.focused_button_handle;
    snapshot.elements.reserve(source.elements.size());
    for (const auto& element : source.elements) {
        LuaUiElementSnapshot copy;
        copy.handle = element.handle;
        copy.parent_handle = element.parent_handle;
        copy.kind = element.definition.kind;
        copy.id = element.definition.id;
        copy.text = element.definition.text;
        copy.rect = element.definition.rect;
        copy.action_class = element.definition.action_class;
        copy.enabled = element.definition.enabled;
        copy.selected = element.handle == source.focused_button_handle;
        snapshot.elements.push_back(std::move(copy));
    }
    return snapshot;
}

}  // namespace

bool InitializeLuaUiRuntime(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    g_lua_ui_runtime.initialized = true;
    g_lua_ui_runtime.next_handle = 1;
    g_lua_ui_runtime.next_action_request_id = 1;
    g_lua_ui_runtime.viewport_width = 0;
    g_lua_ui_runtime.viewport_height = 0;
    g_lua_ui_runtime.surface_order.clear();
    g_lua_ui_runtime.surfaces.clear();
    g_lua_ui_runtime.pending_actions.clear();
    return true;
}

bool CreateLuaUiSurface(
    std::string_view mod_id,
    LuaUiSurfaceDefinition definition,
    std::uint64_t* handle,
    std::string* error_message) {
    if (handle != nullptr) {
        *handle = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (handle == nullptr || mod_id.empty()) {
        SetError(error_message, "Lua UI surface owner was invalid.");
        return false;
    }
    if (!IsValidIdentifier(definition.id)) {
        SetError(error_message, "Lua UI surface id must contain 1 through 64 lowercase identifier bytes.");
        return false;
    }
    if (definition.title.size() > kLuaUiMaximumTitleBytes ||
        !IsValidRect(definition.rect)) {
        SetError(error_message, "Lua UI surface title or normalized rectangle was invalid.");
        return false;
    }

    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    if (!g_lua_ui_runtime.initialized) {
        SetError(error_message, "Lua UI runtime is not initialized.");
        return false;
    }
    const auto owned_count = std::count_if(
        g_lua_ui_runtime.surfaces.begin(),
        g_lua_ui_runtime.surfaces.end(),
        [&](const auto& entry) { return entry.second.mod_id == mod_id; });
    if (owned_count >= kLuaUiMaximumSurfacesPerMod ||
        g_lua_ui_runtime.surfaces.size() >= kLuaUiMaximumSurfaces) {
        SetError(error_message, "Lua UI surface capacity was exhausted.");
        return false;
    }
    const bool duplicate = std::any_of(
        g_lua_ui_runtime.surfaces.begin(),
        g_lua_ui_runtime.surfaces.end(),
        [&](const auto& entry) {
            return entry.second.mod_id == mod_id &&
                entry.second.definition.id == definition.id;
        });
    if (duplicate) {
        SetError(error_message, "Lua UI surface id is already registered by this mod.");
        return false;
    }
    const auto new_handle = g_lua_ui_runtime.next_handle++;
    LuaUiSurfaceState surface;
    surface.handle = new_handle;
    surface.mod_id.assign(mod_id.data(), mod_id.size());
    surface.definition = std::move(definition);
    g_lua_ui_runtime.surfaces.emplace(new_handle, std::move(surface));
    g_lua_ui_runtime.surface_order.push_back(new_handle);
    *handle = new_handle;
    return true;
}

bool CreateLuaUiElement(
    std::string_view mod_id,
    std::uint64_t parent_handle,
    LuaUiElementDefinition definition,
    std::uint64_t* handle,
    std::uint64_t* surface_handle,
    std::string* error_message) {
    if (handle != nullptr) *handle = 0;
    if (surface_handle != nullptr) *surface_handle = 0;
    if (error_message != nullptr) error_message->clear();
    if (handle == nullptr || surface_handle == nullptr ||
        !IsValidIdentifier(definition.id) || !IsValidRect(definition.rect) ||
        definition.text.size() > kLuaUiMaximumTextBytes) {
        SetError(error_message, "Lua UI element id, text, or normalized rectangle was invalid.");
        return false;
    }

    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    LuaUiSurfaceState* surface = FindOwnedSurfaceLocked(mod_id, parent_handle);
    if (surface == nullptr) {
        LuaUiSurfaceState* parent_surface = nullptr;
        auto* parent = FindOwnedElementLocked(mod_id, parent_handle, &parent_surface);
        if (parent == nullptr || parent->definition.kind != LuaUiElementKind::Panel) {
            SetError(error_message, "Lua UI element parent must be an owned surface or panel.");
            return false;
        }
        surface = parent_surface;
    }
    const bool duplicate = std::any_of(
        surface->elements.begin(), surface->elements.end(),
        [&](const LuaUiElementState& element) {
            return element.definition.id == definition.id;
        });
    if (duplicate) {
        SetError(error_message, "Lua UI element id is already registered on this surface.");
        return false;
    }
    const auto kind_count = CountElements(*surface, definition.kind);
    const auto kind_limit = definition.kind == LuaUiElementKind::Panel
        ? kLuaUiMaximumPanelsPerSurface
        : definition.kind == LuaUiElementKind::Label
            ? kLuaUiMaximumLabelsPerSurface
            : kLuaUiMaximumButtonsPerSurface;
    if (kind_count >= kind_limit ||
        CountTextBytes(*surface) + definition.text.size() >
            kLuaUiMaximumTextBytesPerSurface) {
        SetError(error_message, "Lua UI element capacity was exhausted.");
        return false;
    }
    const auto new_handle = g_lua_ui_runtime.next_handle++;
    surface->elements.push_back(
        LuaUiElementState{new_handle, parent_handle, std::move(definition)});
    EnsureFocusLocked(surface);
    *handle = new_handle;
    *surface_handle = surface->handle;
    return true;
}

bool SetLuaUiSurfaceVisible(
    std::string_view mod_id,
    std::uint64_t surface_handle,
    bool visible,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    auto* surface = FindOwnedSurfaceLocked(mod_id, surface_handle);
    if (surface == nullptr) {
        SetError(error_message, "Lua UI surface handle is not owned by this mod.");
        return false;
    }
    surface->visible = visible;
    if (visible) {
        EnsureFocusLocked(surface);
        const auto order = std::find(
            g_lua_ui_runtime.surface_order.begin(),
            g_lua_ui_runtime.surface_order.end(), surface_handle);
        if (order != g_lua_ui_runtime.surface_order.end()) {
            g_lua_ui_runtime.surface_order.erase(order);
            g_lua_ui_runtime.surface_order.push_back(surface_handle);
        }
    }
    return true;
}

bool DestroyLuaUiSurface(
    std::string_view mod_id,
    std::uint64_t surface_handle,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    const auto* surface = FindOwnedSurfaceLocked(mod_id, surface_handle);
    if (surface == nullptr) {
        SetError(error_message, "Lua UI surface handle is not owned by this mod.");
        return false;
    }
    const auto surface_id = surface->definition.id;
    g_lua_ui_runtime.surfaces.erase(surface_handle);
    g_lua_ui_runtime.surface_order.erase(
        std::remove(
            g_lua_ui_runtime.surface_order.begin(),
            g_lua_ui_runtime.surface_order.end(), surface_handle),
        g_lua_ui_runtime.surface_order.end());
    g_lua_ui_runtime.pending_actions.erase(
        std::remove_if(
            g_lua_ui_runtime.pending_actions.begin(),
            g_lua_ui_runtime.pending_actions.end(),
            [&](const LuaUiPendingAction& action) {
                return action.mod_id == mod_id &&
                    action.surface_id == surface_id;
            }),
        g_lua_ui_runtime.pending_actions.end());
    return true;
}

bool SetLuaUiElementText(
    std::string_view mod_id,
    std::uint64_t element_handle,
    std::string text,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    if (text.size() > kLuaUiMaximumTextBytes) {
        SetError(error_message, "Lua UI text exceeds 1024 bytes.");
        return false;
    }
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    LuaUiSurfaceState* surface = nullptr;
    auto* element = FindOwnedElementLocked(mod_id, element_handle, &surface);
    if (element == nullptr || surface == nullptr) {
        SetError(error_message, "Lua UI element handle is not owned by this mod.");
        return false;
    }
    const auto old_size = element->definition.text.size();
    if (CountTextBytes(*surface) - old_size + text.size() >
        kLuaUiMaximumTextBytesPerSurface) {
        SetError(error_message, "Lua UI surface text budget was exhausted.");
        return false;
    }
    element->definition.text = std::move(text);
    return true;
}

bool SetLuaUiButtonEnabled(
    std::string_view mod_id,
    std::uint64_t button_handle,
    bool enabled,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    LuaUiSurfaceState* surface = nullptr;
    auto* element = FindOwnedElementLocked(mod_id, button_handle, &surface);
    if (element == nullptr || element->definition.kind != LuaUiElementKind::Button) {
        SetError(error_message, "Lua UI button handle is not owned by this mod.");
        return false;
    }
    element->definition.enabled = enabled;
    EnsureFocusLocked(surface);
    return true;
}

bool FocusLuaUiButton(
    std::string_view mod_id,
    std::uint64_t button_handle,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    LuaUiSurfaceState* surface = nullptr;
    auto* element = FindOwnedElementLocked(mod_id, button_handle, &surface);
    if (element == nullptr || element->definition.kind != LuaUiElementKind::Button ||
        !element->definition.enabled) {
        SetError(error_message, "Lua UI focus target must be an enabled owned button.");
        return false;
    }
    surface->focused_button_handle = button_handle;
    return true;
}

bool TryQueueLuaUiAction(
    std::string_view mod_id,
    std::string_view surface_id,
    std::string_view action_id,
    std::uint64_t* request_id,
    std::string* error_message) {
    if (request_id != nullptr) *request_id = 0;
    if (error_message != nullptr) error_message->clear();
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    for (auto order = g_lua_ui_runtime.surface_order.rbegin();
         order != g_lua_ui_runtime.surface_order.rend(); ++order) {
        const auto entry = g_lua_ui_runtime.surfaces.find(*order);
        if (entry == g_lua_ui_runtime.surfaces.end()) {
            continue;
        }
        auto& surface = entry->second;
        if (surface.mod_id != mod_id ||
            (!surface_id.empty() && surface.definition.id != surface_id) ||
            !surface.visible) {
            continue;
        }
        const auto button = std::find_if(
            surface.elements.begin(), surface.elements.end(),
            [&](const LuaUiElementState& element) {
                return element.definition.kind == LuaUiElementKind::Button &&
                    element.definition.id == action_id;
            });
        if (button == surface.elements.end() || !button->definition.enabled) {
            break;
        }
        const auto id = g_lua_ui_runtime.next_action_request_id++;
        QueueButtonActionLocked(&surface, &*button, 0, id, false);
        if (request_id != nullptr) *request_id = id;
        return true;
    }
    SetError(error_message, "Visible authored UI action was not found or is disabled.");
    return false;
}

bool QueueRemoteLuaUiSimulationAction(
    std::string_view mod_id,
    std::string_view surface_id,
    std::string_view action_id,
    std::uint64_t participant_id,
    std::uint64_t request_id,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    if (participant_id == 0 || request_id == 0) {
        SetError(error_message, "Routed Lua UI action identity was invalid.");
        return false;
    }
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    for (auto& entry : g_lua_ui_runtime.surfaces) {
        auto& surface = entry.second;
        if (surface.mod_id != mod_id || surface.definition.id != surface_id) {
            continue;
        }
        const auto button = std::find_if(
            surface.elements.begin(), surface.elements.end(),
            [&](const LuaUiElementState& element) {
                return element.definition.kind == LuaUiElementKind::Button &&
                    element.definition.id == action_id &&
                    element.definition.action_class == LuaUiActionClass::Simulation;
            });
        if (button != surface.elements.end() && button->definition.enabled) {
            QueueButtonActionLocked(
                &surface, &*button, participant_id, request_id, true);
            return true;
        }
        break;
    }
    SetError(error_message, "Routed Lua UI simulation action is not registered or is disabled.");
    return false;
}

std::vector<LuaUiSurfaceSnapshot> SnapshotLuaUiSurfaces() {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    std::vector<LuaUiSurfaceSnapshot> snapshots;
    snapshots.reserve(g_lua_ui_runtime.surface_order.size());
    for (const auto handle : g_lua_ui_runtime.surface_order) {
        const auto found = g_lua_ui_runtime.surfaces.find(handle);
        if (found != g_lua_ui_runtime.surfaces.end() && found->second.visible) {
            snapshots.push_back(CopySurface(found->second));
        }
    }
    return snapshots;
}

bool TryGetLuaUiSurfaceSnapshot(
    std::string_view mod_id,
    std::uint64_t surface_handle,
    LuaUiSurfaceSnapshot* snapshot) {
    if (snapshot == nullptr) return false;
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    const auto* surface = FindOwnedSurfaceLocked(mod_id, surface_handle);
    if (surface == nullptr) return false;
    *snapshot = CopySurface(*surface);
    return true;
}

std::vector<LuaUiPendingAction> TakePendingLuaUiActions() {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    std::vector<LuaUiPendingAction> actions;
    actions.reserve(g_lua_ui_runtime.pending_actions.size());
    while (!g_lua_ui_runtime.pending_actions.empty()) {
        actions.push_back(std::move(g_lua_ui_runtime.pending_actions.front()));
        g_lua_ui_runtime.pending_actions.pop_front();
    }
    return actions;
}

bool HasLuaUiRegistrations() {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    return !g_lua_ui_runtime.surfaces.empty();
}

bool HasLuaUiRegistrationsForMod(std::string_view mod_id) {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    return std::any_of(
        g_lua_ui_runtime.surfaces.begin(),
        g_lua_ui_runtime.surfaces.end(),
        [&](const auto& entry) { return entry.second.mod_id == mod_id; });
}

void ClearLuaUiForMod(std::string_view mod_id) {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    for (auto it = g_lua_ui_runtime.surfaces.begin();
         it != g_lua_ui_runtime.surfaces.end();) {
        if (it->second.mod_id == mod_id) {
            const auto handle = it->first;
            g_lua_ui_runtime.surface_order.erase(
                std::remove(
                    g_lua_ui_runtime.surface_order.begin(),
                    g_lua_ui_runtime.surface_order.end(), handle),
                g_lua_ui_runtime.surface_order.end());
            it = g_lua_ui_runtime.surfaces.erase(it);
        } else {
            ++it;
        }
    }
    g_lua_ui_runtime.pending_actions.erase(
        std::remove_if(
            g_lua_ui_runtime.pending_actions.begin(),
            g_lua_ui_runtime.pending_actions.end(),
            [&](const LuaUiPendingAction& action) {
                return action.mod_id == mod_id;
            }),
        g_lua_ui_runtime.pending_actions.end());
}

bool HandleLuaAuthoredUiWindowMessage(
    HWND,
    UINT message,
    WPARAM wparam,
    LPARAM lparam) {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    auto* surface = TopVisibleSurfaceLocked();
    if (surface == nullptr) {
        return false;
    }
    EnsureFocusLocked(surface);

    bool handled = false;
    if (message == WM_KEYDOWN && (lparam & (1LL << 30)) == 0) {
        switch (wparam) {
        case VK_UP:
            CycleFocusLocked(surface, -1);
            handled = true;
            break;
        case VK_DOWN:
        case VK_TAB:
            CycleFocusLocked(surface, 1);
            handled = true;
            break;
        case VK_RETURN:
        case VK_SPACE: {
            const auto button = std::find_if(
                surface->elements.begin(), surface->elements.end(),
                [&](const LuaUiElementState& element) {
                    return element.handle == surface->focused_button_handle;
                });
            if (button != surface->elements.end()) {
                QueueButtonActionLocked(surface, &*button, 0, 0, false);
            }
            handled = true;
            break;
        }
        case VK_ESCAPE:
            if (surface->definition.close_on_escape) {
                surface->visible = false;
            }
            handled = true;
            break;
        default:
            break;
        }
    } else if (message == WM_MOUSEMOVE || message == WM_LBUTTONUP) {
        if (g_lua_ui_runtime.viewport_width != 0 &&
            g_lua_ui_runtime.viewport_height != 0) {
            const auto mouse_x = static_cast<float>(GET_X_LPARAM(lparam));
            const auto mouse_y = static_cast<float>(GET_Y_LPARAM(lparam));
            for (auto& element : surface->elements) {
                if (element.definition.kind != LuaUiElementKind::Button ||
                    !element.definition.enabled) {
                    continue;
                }
                LuaUiRect rect;
                if (!ResolveElementRectLocked(*surface, element, &rect)) {
                    continue;
                }
                const float left = rect.x * g_lua_ui_runtime.viewport_width;
                const float top = rect.y * g_lua_ui_runtime.viewport_height;
                const float right = (rect.x + rect.width) * g_lua_ui_runtime.viewport_width;
                const float bottom = (rect.y + rect.height) * g_lua_ui_runtime.viewport_height;
                if (mouse_x >= left && mouse_x <= right &&
                    mouse_y >= top && mouse_y <= bottom) {
                    surface->focused_button_handle = element.handle;
                    if (message == WM_LBUTTONUP) {
                        QueueButtonActionLocked(surface, &element, 0, 0, false);
                    }
                    handled = true;
                    break;
                }
            }
        }
    }

    return handled ||
        (surface->definition.modal &&
         (IsUiKeyboardMessage(message) || IsUiMouseMessage(message)));
}

void UpdateLuaUiViewport(std::uint32_t width, std::uint32_t height) {
    std::scoped_lock lock(g_lua_ui_runtime.mutex);
    g_lua_ui_runtime.viewport_width = width;
    g_lua_ui_runtime.viewport_height = height;
}

}  // namespace sdmod
