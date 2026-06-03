#include "lua_engine_bindings_internal.h"

#include "logger.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"

#include <Windows.h>

#include <algorithm>
#include <string>

namespace sdmod::detail {
namespace {

bool TryFindHostProcessWindow(HWND* window) {
    if (window == nullptr) {
        return false;
    }
    *window = nullptr;

    const auto foreground = GetForegroundWindow();
    if (foreground != nullptr) {
        DWORD process_id = 0;
        GetWindowThreadProcessId(foreground, &process_id);
        if (process_id == GetCurrentProcessId()) {
            *window = foreground;
            return true;
        }
    }

    struct SearchState {
        DWORD pid;
        HWND result;
    };
    SearchState state_s{GetCurrentProcessId(), nullptr};
    EnumWindows(
        [](HWND hwnd, LPARAM lp) -> BOOL {
            auto* s = reinterpret_cast<SearchState*>(lp);
            DWORD pid = 0;
            GetWindowThreadProcessId(hwnd, &pid);
            if (pid == s->pid && IsWindowVisible(hwnd) && GetWindow(hwnd, GW_OWNER) == nullptr) {
                s->result = hwnd;
                return FALSE;
            }
            return TRUE;
        },
        reinterpret_cast<LPARAM>(&state_s));

    *window = state_s.result;
    return state_s.result != nullptr;
}

bool TrySendHostProcessLeftClickNormalized(
    double normalized_x,
    double normalized_y,
    std::string* error_message) {
    constexpr DWORD kPreClickSettleDelayMs = 15;
    constexpr DWORD kHeldClickDurationMs = 35;
    normalized_x = (std::max)(0.0, (std::min)(1.0, normalized_x));
    normalized_y = (std::max)(0.0, (std::min)(1.0, normalized_y));

    if (IsRunLifecycleActive()) {
        std::string gameplay_click_error;
        if (QueueGameplayMouseLeftClick(&gameplay_click_error)) {
            return true;
        }

        Log("Gameplay click queue failed; falling back to windowed SendInput: " + gameplay_click_error);
    }

    HWND window = nullptr;
    bool have_window_click_point = false;
    if (TryFindHostProcessWindow(&window) && window != nullptr) {
        RECT client_rect{};
        if (GetClientRect(window, &client_rect)) {
            const auto width = client_rect.right - client_rect.left;
            const auto height = client_rect.bottom - client_rect.top;
            if (width > 0 && height > 0) {
                const auto client_x = static_cast<LONG>(normalized_x * static_cast<double>(width - 1));
                const auto client_y = static_cast<LONG>(normalized_y * static_cast<double>(height - 1));

                POINT point{client_x, client_y};
                if (ClientToScreen(window, &point)) {
                    SetForegroundWindow(window);
                    SetCursorPos(point.x, point.y);
                    Sleep(kPreClickSettleDelayMs);
                    have_window_click_point = true;
                }
            }
        }
    }

    if (!have_window_click_point) {
        if (error_message != nullptr) {
            *error_message = "Unable to position a host game window click point.";
        }
        return false;
    }

    INPUT input{};
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    if (SendInput(1, &input, sizeof(INPUT)) != 1) {
        if (error_message != nullptr) {
            *error_message = "SendInput left-button-down failed for the host game window.";
        }
        return false;
    }

    Sleep(kHeldClickDurationMs);

    input.mi.dwFlags = MOUSEEVENTF_LEFTUP;
    if (SendInput(1, &input, sizeof(INPUT)) != 1) {
        if (error_message != nullptr) {
            *error_message = "SendInput left-button-up failed for the host game window.";
        }
        return false;
    }

    return true;
}

int LuaInputClickNormalized(lua_State* state) {
    const auto normalized_x = luaL_checknumber(state, 1);
    const auto normalized_y = luaL_checknumber(state, 2);

    std::string error_message;
    if (!TrySendHostProcessLeftClickNormalized(normalized_x, normalized_y, &error_message)) {
        return luaL_error(state, "sd.input.click_normalized failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaHubStartTestrun(lua_State* state) {
    if (multiplayer::IsLocalTransportClient()) {
        return luaL_error(
            state,
            "sd.hub.start_testrun is host-only while connected to a multiplayer session.");
    }

    std::string error_message;
    if (!QueueHubStartTestrun(&error_message)) {
        return luaL_error(state, "sd.hub.start_testrun failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputPressKey(lua_State* state) {
    const auto* binding_name = luaL_checkstring(state, 1);
    std::string error_message;
    if (!QueueGameplayKeyPress(
            binding_name == nullptr ? std::string_view{} : std::string_view(binding_name),
            &error_message)) {
        return luaL_error(state, "sd.input.press_key failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputPressScancode(lua_State* state) {
    const auto raw = luaL_checkinteger(state, 1);
    std::string error_message;
    if (raw < 0 || !QueueGameplayScancodePress(static_cast<std::uint32_t>(raw), &error_message)) {
        return luaL_error(state, "sd.input.press_scancode failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputHoldMouseLeftFrames(lua_State* state) {
    const auto raw = luaL_checkinteger(state, 1);
    std::string error_message;
    if (raw <= 0 || raw > 3600 ||
        !QueueGameplayMouseLeftHoldFrames(static_cast<std::uint32_t>(raw), &error_message)) {
        return luaL_error(state, "sd.input.hold_mouse_left_frames failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputQueueLocalSpellCast(lua_State* state) {
    const auto raw_skill_id = luaL_checkinteger(state, 1);
    if (raw_skill_id < 0) {
        return luaL_error(state, "sd.input.queue_local_spell_cast skill_id must be non-negative");
    }

    const auto direction_x = static_cast<float>(luaL_optnumber(state, 2, 1.0));
    const auto direction_y = static_cast<float>(luaL_optnumber(state, 3, 0.0));
    const auto hold_frames = luaL_optinteger(state, 4, 0);
    if (hold_frames < 0 || hold_frames > 3600) {
        return luaL_error(state, "sd.input.queue_local_spell_cast hold_frames must be in the range 0..3600");
    }
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return luaL_error(state, "sd.input.queue_local_spell_cast requires a live player");
    }

    multiplayer::QueueLocalSpellCastEvent(
        static_cast<int>(raw_skill_id),
        player_state.x,
        player_state.y,
        direction_x,
        direction_y,
        0,
        0,
        static_cast<std::uint32_t>(hold_frames));
    lua_pushboolean(state, 1);
    return 1;
}

int LuaInputQueueLocalEnemyDamageClaim(lua_State* state) {
    const auto raw_network_actor_id = luaL_checkinteger(state, 1);
    const auto raw_skill_id = luaL_checkinteger(state, 2);
    const auto authoritative_hp = static_cast<float>(luaL_checknumber(state, 3));
    const auto local_hp = static_cast<float>(luaL_checknumber(state, 4));
    const auto max_hp = static_cast<float>(luaL_checknumber(state, 5));
    const auto target_position_x = static_cast<float>(luaL_checknumber(state, 6));
    const auto target_position_y = static_cast<float>(luaL_checknumber(state, 7));
    if (raw_network_actor_id <= 0) {
        return luaL_error(state, "sd.input.queue_local_enemy_damage_claim network_actor_id must be positive");
    }

    multiplayer::QueueLocalEnemyDamageClaim(
        static_cast<std::uint64_t>(raw_network_actor_id),
        static_cast<std::int32_t>(raw_skill_id),
        authoritative_hp,
        local_hp,
        max_hp,
        target_position_x,
        target_position_y);
    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaInputBindings(lua_State* state) {
    lua_createtable(state, 0, 6);
    RegisterFunction(state, &LuaInputPressKey, "press_key");
    RegisterFunction(state, &LuaInputPressScancode, "press_scancode");
    RegisterFunction(state, &LuaInputClickNormalized, "click_normalized");
    RegisterFunction(state, &LuaInputHoldMouseLeftFrames, "hold_mouse_left_frames");
    RegisterFunction(state, &LuaInputQueueLocalSpellCast, "queue_local_spell_cast");
    RegisterFunction(state, &LuaInputQueueLocalEnemyDamageClaim, "queue_local_enemy_damage_claim");
    lua_setfield(state, -2, "input");
}

void RegisterLuaHubBindings(lua_State* state) {
    lua_createtable(state, 0, 1);
    RegisterFunction(state, &LuaHubStartTestrun, "start_testrun");
    lua_setfield(state, -2, "hub");
}

}  // namespace sdmod::detail
