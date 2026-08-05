#define NOMINMAX
#include "native_input_trace.h"

#include "gameplay_seams.h"
#include "memory_access.h"

#include <Windowsx.h>

#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

constexpr std::size_t kNativeInputTraceCapacity = 768;
constexpr std::uint64_t kUnchangedInputSampleIntervalTicks = 10;
constexpr std::size_t kGameplayInputBufferStride = 0x203;
constexpr std::size_t kGameplayInputBufferCount = 2;

// Recovered from Joypad output consumption in PlayerActorTick (0x00548B00).
constexpr std::size_t kGameplayAimInputXOffset = 0x1D4;
constexpr std::size_t kGameplayAimInputYOffset = 0x1D8;
constexpr std::size_t kGameplayAlternateCastIntentOffset = 0x1E5;
constexpr std::size_t kGameplayMovementBlockedOffset = 0x1ABD;
constexpr std::size_t kGameplayCastBlockedOffset = 0x1ABE;

enum class TraceEventKind {
    WindowMessage,
    InputSample,
    ActorTick,
};

struct TraceEvent {
    TraceEventKind kind = TraceEventKind::WindowMessage;
    std::uint64_t sequence = 0;
    std::uint64_t monotonic_ms = 0;
    std::uint64_t simulation_tick = 0;
    std::string stage;

    std::uint32_t message = 0;
    std::uint64_t wparam = 0;
    std::uint64_t lparam = 0;
    bool forwarded_to_stock = false;
    std::int32_t raw_x = 0;
    std::int32_t raw_y = 0;
    std::int32_t native_x = 0;
    std::int32_t native_y = 0;
    std::int32_t client_width = 0;
    std::int32_t client_height = 0;
    float input_scale_x = 1.0f;
    float input_scale_y = 1.0f;
    std::uint32_t key_repeat = 0;
    std::uint32_t key_scancode = 0;
    bool key_extended = false;
    bool key_previous_down = false;
    bool key_transition_up = false;

    bool state_readable = false;
    std::int32_t input_buffer_index = -1;
    std::uint8_t raw_mouse_mask = 0;
    bool mouse_left = false;
    bool mouse_right = false;
    bool mouse_middle = false;
    float movement_x = 0.0f;
    float movement_y = 0.0f;
    float aim_x = 0.0f;
    float aim_y = 0.0f;
    bool cast_active = false;
    bool alternate_cast_active = false;
    bool movement_blocked = false;
    bool cast_blocked = false;
    bool gameplay_input_blocked = false;
    std::int32_t cursor_screen_x = 0;
    std::int32_t cursor_screen_y = 0;
    bool cursor_world_readable = false;
    float cursor_world_x = 0.0f;
    float cursor_world_y = 0.0f;
    float view_scale = 0.0f;
    float view_origin_x = 0.0f;
    float view_origin_y = 0.0f;

    bool actor_readable = false;
    float player_x = 0.0f;
    float player_y = 0.0f;
    std::int32_t primary_skill_id = 0;
    std::int32_t previous_skill_id = 0;
    NativeInputActiveSpellObservation active_spell;
};

struct NativeInputTraceState {
    std::atomic<bool> active{false};
    std::mutex mutex;
    std::string label;
    std::vector<TraceEvent> events;
    std::uint64_t next_sequence = 1;
    std::atomic<std::uint64_t> simulation_tick{0};
    std::size_t dropped_events = 0;
    bool have_last_input_sample = false;
    std::uint64_t last_input_sample_tick = 0;
    TraceEvent last_input_sample;
};

NativeInputTraceState g_native_input_trace;

bool InputSampleStateChanged(
    const TraceEvent& previous,
    const TraceEvent& current) {
    return previous.state_readable != current.state_readable ||
           previous.raw_mouse_mask != current.raw_mouse_mask ||
           previous.mouse_left != current.mouse_left ||
           previous.mouse_right != current.mouse_right ||
           previous.mouse_middle != current.mouse_middle ||
           previous.movement_x != current.movement_x ||
           previous.movement_y != current.movement_y ||
           previous.aim_x != current.aim_x ||
           previous.aim_y != current.aim_y ||
           previous.cast_active != current.cast_active ||
           previous.alternate_cast_active != current.alternate_cast_active ||
           previous.movement_blocked != current.movement_blocked ||
           previous.cast_blocked != current.cast_blocked ||
           previous.gameplay_input_blocked != current.gameplay_input_blocked;
}

bool IsObservedWindowMessage(UINT message) {
    switch (message) {
    case WM_KEYDOWN:
    case WM_KEYUP:
    case WM_CHAR:
    case WM_SYSKEYDOWN:
    case WM_SYSKEYUP:
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN:
    case WM_LBUTTONUP:
    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN:
    case WM_MBUTTONUP:
    case WM_MBUTTONDBLCLK:
    case WM_MOUSEWHEEL:
    case WM_MOUSELEAVE:
        return true;
    default:
        return false;
    }
}

bool HasMouseCoordinates(UINT message) {
    switch (message) {
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN:
    case WM_LBUTTONUP:
    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN:
    case WM_MBUTTONUP:
    case WM_MBUTTONDBLCLK:
        return true;
    default:
        return false;
    }
}

const char* WindowMessageName(std::uint32_t message) {
    switch (message) {
    case WM_KEYDOWN: return "WM_KEYDOWN";
    case WM_KEYUP: return "WM_KEYUP";
    case WM_CHAR: return "WM_CHAR";
    case WM_SYSKEYDOWN: return "WM_SYSKEYDOWN";
    case WM_SYSKEYUP: return "WM_SYSKEYUP";
    case WM_MOUSEMOVE: return "WM_MOUSEMOVE";
    case WM_LBUTTONDOWN: return "WM_LBUTTONDOWN";
    case WM_LBUTTONUP: return "WM_LBUTTONUP";
    case WM_LBUTTONDBLCLK: return "WM_LBUTTONDBLCLK";
    case WM_RBUTTONDOWN: return "WM_RBUTTONDOWN";
    case WM_RBUTTONUP: return "WM_RBUTTONUP";
    case WM_RBUTTONDBLCLK: return "WM_RBUTTONDBLCLK";
    case WM_MBUTTONDOWN: return "WM_MBUTTONDOWN";
    case WM_MBUTTONUP: return "WM_MBUTTONUP";
    case WM_MBUTTONDBLCLK: return "WM_MBUTTONDBLCLK";
    case WM_MOUSEWHEEL: return "WM_MOUSEWHEEL";
    case WM_MOUSELEAVE: return "WM_MOUSELEAVE";
    default: return "UNKNOWN";
    }
}

void AppendEvent(TraceEvent event) {
    auto& state = g_native_input_trace;
    if (!state.active.load(std::memory_order_acquire)) {
        return;
    }
    event.monotonic_ms = static_cast<std::uint64_t>(GetTickCount64());
    event.simulation_tick = state.simulation_tick.load(std::memory_order_acquire);

    std::lock_guard<std::mutex> lock(state.mutex);
    if (!state.active.load(std::memory_order_relaxed)) {
        return;
    }
    if (event.kind == TraceEventKind::InputSample) {
        const bool changed =
            !state.have_last_input_sample ||
            InputSampleStateChanged(state.last_input_sample, event);
        const bool periodic =
            !state.have_last_input_sample ||
            event.simulation_tick >=
                state.last_input_sample_tick +
                    kUnchangedInputSampleIntervalTicks;
        state.last_input_sample = event;
        state.have_last_input_sample = true;
        if (!changed && !periodic) {
            return;
        }
        state.last_input_sample_tick = event.simulation_tick;
    }
    event.sequence = state.next_sequence++;
    if (state.events.size() >= kNativeInputTraceCapacity) {
        ++state.dropped_events;
        return;
    }
    state.events.push_back(std::move(event));
}

bool TryResolveGameplay(std::uintptr_t* gameplay_address) {
    if (gameplay_address == nullptr) {
        return false;
    }
    *gameplay_address = 0;
    auto& memory = ProcessMemory::Instance();
    const auto global_address =
        memory.ResolveGameAddressOrZero(kGameObjectGlobal);
    return global_address != 0 &&
           memory.TryReadValue(global_address, gameplay_address) &&
           *gameplay_address != 0;
}

void ReadGameplayState(
    std::uintptr_t gameplay_address,
    TraceEvent* event) {
    if (gameplay_address == 0 || event == nullptr) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    std::uint8_t cast_active = 0;
    std::uint8_t alternate_cast_active = 0;
    std::uint8_t movement_blocked = 0;
    std::uint8_t cast_blocked = 0;
    std::uint8_t gameplay_input_blocked = 0;
    const bool readable =
        memory.TryReadField(
            gameplay_address,
            kGameplayLocalMovementInputXOffset,
            &event->movement_x) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayLocalMovementInputYOffset,
            &event->movement_y) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayAimInputXOffset,
            &event->aim_x) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayAimInputYOffset,
            &event->aim_y) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayCastIntentOffset,
            &cast_active) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayAlternateCastIntentOffset,
            &alternate_cast_active) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayMovementBlockedOffset,
            &movement_blocked) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayCastBlockedOffset,
            &cast_blocked) &&
        memory.TryReadField(
            gameplay_address,
            kGameplayInputGateFlagOffset,
            &gameplay_input_blocked);
    event->state_readable = event->state_readable || readable;
    event->cast_active = cast_active != 0;
    event->alternate_cast_active = alternate_cast_active != 0;
    event->movement_blocked = movement_blocked != 0;
    event->cast_blocked = cast_blocked != 0;
    event->gameplay_input_blocked = gameplay_input_blocked != 0;
}

void ReadCursorAndPlayerState(
    std::uintptr_t gameplay_address,
    std::uintptr_t actor_address,
    TraceEvent* event) {
    if (gameplay_address == 0 || event == nullptr) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    if (actor_address == 0) {
        (void)memory.TryReadField(
            gameplay_address,
            kGameplayPlayerActorOffset,
            &actor_address);
    }
    const auto cursor_address =
        memory.ResolveGameAddressOrZero(kCursorScreenPositionGlobal);
    std::uintptr_t actor_world_address = 0;
    if (actor_address == 0 || cursor_address == 0 ||
        !memory.TryReadValue(
            cursor_address,
            &event->cursor_screen_x) ||
        !memory.TryReadValue(
            cursor_address + sizeof(event->cursor_screen_x),
            &event->cursor_screen_y) ||
        !memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &actor_world_address) ||
        actor_world_address == 0 ||
        !memory.TryReadField(
            actor_world_address,
            kActorWorldViewScaleOffset,
            &event->view_scale) ||
        !memory.TryReadField(
            actor_world_address,
            kActorWorldViewOriginXOffset,
            &event->view_origin_x) ||
        !memory.TryReadField(
            actor_world_address,
            kActorWorldViewOriginYOffset,
            &event->view_origin_y) ||
        !std::isfinite(event->view_scale) ||
        std::abs(event->view_scale) <= 0.0001f ||
        !std::isfinite(event->view_origin_x) ||
        !std::isfinite(event->view_origin_y)) {
        return;
    }
    event->cursor_world_x =
        event->view_origin_x +
        static_cast<float>(event->cursor_screen_x) / event->view_scale;
    event->cursor_world_y =
        event->view_origin_y +
        static_cast<float>(event->cursor_screen_y) / event->view_scale;
    event->cursor_world_readable =
        std::isfinite(event->cursor_world_x) &&
        std::isfinite(event->cursor_world_y);
}

void AppendJsonString(std::ostringstream& output, std::string_view value) {
    output << '"';
    for (const auto character : value) {
        switch (character) {
        case '"': output << "\\\""; break;
        case '\\': output << "\\\\"; break;
        case '\b': output << "\\b"; break;
        case '\f': output << "\\f"; break;
        case '\n': output << "\\n"; break;
        case '\r': output << "\\r"; break;
        case '\t': output << "\\t"; break;
        default:
            if (static_cast<unsigned char>(character) < 0x20) {
                output << "\\u"
                       << std::hex << std::setw(4) << std::setfill('0')
                       << static_cast<unsigned int>(
                              static_cast<unsigned char>(character))
                       << std::dec << std::setfill(' ');
            } else {
                output << character;
            }
            break;
        }
    }
    output << '"';
}

void AppendBool(std::ostringstream& output, bool value) {
    output << (value ? "true" : "false");
}

void AppendVector(
    std::ostringstream& output,
    std::string_view name,
    float x,
    float y) {
    AppendJsonString(output, name);
    output << ":{";
    output << "\"x\":" << x << ",\"y\":" << y << '}';
}

void AppendCursorWorld(std::ostringstream& output, const TraceEvent& event) {
    output << "\"cursor_screen\":{";
    output << "\"x\":" << event.cursor_screen_x
           << ",\"y\":" << event.cursor_screen_y << "},";
    output << "\"cursor_world\":{";
    output << "\"readable\":";
    AppendBool(output, event.cursor_world_readable);
    output << ",\"x\":" << event.cursor_world_x
           << ",\"y\":" << event.cursor_world_y << "},";
    output << "\"view\":{";
    output << "\"scale\":" << event.view_scale
           << ",\"origin_x\":" << event.view_origin_x
           << ",\"origin_y\":" << event.view_origin_y << '}';
}

void AppendGameplayState(std::ostringstream& output, const TraceEvent& event) {
    output << "\"state_readable\":";
    AppendBool(output, event.state_readable);
    output << ',';
    AppendVector(
        output,
        "movement",
        event.movement_x,
        event.movement_y);
    output << ',';
    AppendVector(output, "aim_unit", event.aim_x, event.aim_y);
    output << ",\"cast_active\":";
    AppendBool(output, event.cast_active);
    output << ",\"alternate_cast_active\":";
    AppendBool(output, event.alternate_cast_active);
    output << ",\"gates\":{";
    output << "\"movement_blocked\":";
    AppendBool(output, event.movement_blocked);
    output << ",\"cast_blocked\":";
    AppendBool(output, event.cast_blocked);
    output << ",\"gameplay_input_blocked\":";
    AppendBool(output, event.gameplay_input_blocked);
    output << "},";
    AppendCursorWorld(output, event);
}

std::string SerializeTraceLocked(
    const NativeInputTraceState& state,
    bool active) {
    std::ostringstream output;
    output << std::setprecision(std::numeric_limits<float>::max_digits10);
    output << "{\"format\":\"sd-native-input-trace-v1\",\"label\":";
    AppendJsonString(output, state.label);
    output << ",\"active\":";
    AppendBool(output, active);
    output << ",\"capacity\":" << kNativeInputTraceCapacity
           << ",\"unchanged_input_sample_interval_ticks\":"
           << kUnchangedInputSampleIntervalTicks
           << ",\"dropped_events\":" << state.dropped_events
           << ",\"event_count\":" << state.events.size()
           << ",\"events\":[";
    for (std::size_t index = 0; index < state.events.size(); ++index) {
        if (index != 0) {
            output << ',';
        }
        const auto& event = state.events[index];
        output << '{';
        output << "\"kind\":";
        switch (event.kind) {
        case TraceEventKind::WindowMessage:
            AppendJsonString(output, "win32");
            break;
        case TraceEventKind::InputSample:
            AppendJsonString(output, "input_sample");
            break;
        case TraceEventKind::ActorTick:
            AppendJsonString(output, "actor_tick");
            break;
        }
        output << ",\"sequence\":" << event.sequence
               << ",\"monotonic_ms\":" << event.monotonic_ms
               << ",\"simulation_tick\":" << event.simulation_tick;
        if (event.kind == TraceEventKind::WindowMessage) {
            output << ",\"message\":" << event.message
                   << ",\"message_name\":";
            AppendJsonString(output, WindowMessageName(event.message));
            output << ",\"wparam\":" << event.wparam
                   << ",\"lparam\":" << event.lparam
                   << ",\"route_owner\":";
            AppendJsonString(output, event.stage);
            output << ",\"forwarded_to_stock\":";
            AppendBool(output, event.forwarded_to_stock);
            output << ",\"raw_client\":{";
            output << "\"x\":" << event.raw_x
                   << ",\"y\":" << event.raw_y << "},";
            output << "\"native_point\":{";
            output << "\"x\":" << event.native_x
                   << ",\"y\":" << event.native_y << "},";
            output << "\"client_size\":{";
            output << "\"width\":" << event.client_width
                   << ",\"height\":" << event.client_height << "},";
            output << "\"input_scale\":{";
            output << "\"x\":" << event.input_scale_x
                   << ",\"y\":" << event.input_scale_y << "},";
            output << "\"key\":{";
            output << "\"repeat\":" << event.key_repeat
                   << ",\"scancode\":" << event.key_scancode
                   << ",\"extended\":";
            AppendBool(output, event.key_extended);
            output << ",\"previous_down\":";
            AppendBool(output, event.key_previous_down);
            output << ",\"transition_up\":";
            AppendBool(output, event.key_transition_up);
            output << '}';
        } else if (event.kind == TraceEventKind::InputSample) {
            output << ",\"stage\":";
            AppendJsonString(output, event.stage);
            output << ",\"buffer_index\":" << event.input_buffer_index
                   << ",\"raw_mouse_mask\":"
                   << static_cast<unsigned int>(event.raw_mouse_mask)
                   << ",\"mouse\":{";
            output << "\"left\":";
            AppendBool(output, event.mouse_left);
            output << ",\"right\":";
            AppendBool(output, event.mouse_right);
            output << ",\"middle\":";
            AppendBool(output, event.mouse_middle);
            output << "},";
            AppendGameplayState(output, event);
        } else {
            output << ",\"actor_readable\":";
            AppendBool(output, event.actor_readable);
            output << ",\"player\":{";
            output << "\"x\":" << event.player_x
                   << ",\"y\":" << event.player_y << "},";
            output << "\"primary_skill_id\":" << event.primary_skill_id
                   << ",\"previous_skill_id\":"
                   << event.previous_skill_id << ',';
            AppendGameplayState(output, event);
            output << ",\"active_spell\":{";
            output << "\"readable\":";
            AppendBool(output, event.active_spell.readable);
            output << ",\"object_address\":"
                   << event.active_spell.object_address
                   << ",\"object_type\":"
                   << event.active_spell.object_type
                   << ",\"phase\":" << event.active_spell.phase
                   << ",\"release_timer\":"
                   << event.active_spell.release_timer
                   << ",\"charge\":" << event.active_spell.charge
                   << ",\"growth_rate\":"
                   << event.active_spell.growth_rate
                   << ",\"max_charge\":"
                   << event.active_spell.max_charge << '}';
        }
        output << '}';
    }
    output << "]}";
    return output.str();
}

}  // namespace

void ObserveNativeInputWindowMessage(
    HWND window,
    UINT message,
    WPARAM wparam,
    LPARAM lparam,
    bool forwarded_to_stock,
    std::string_view route_owner) {
    if (!g_native_input_trace.active.load(std::memory_order_acquire) ||
        !IsObservedWindowMessage(message)) {
        return;
    }

    TraceEvent event;
    event.kind = TraceEventKind::WindowMessage;
    event.message = message;
    event.wparam = static_cast<std::uint64_t>(wparam);
    event.lparam = static_cast<std::uint64_t>(
        static_cast<std::uintptr_t>(lparam));
    event.forwarded_to_stock = forwarded_to_stock;
    event.stage.assign(route_owner.begin(), route_owner.end());

    RECT client_rect{};
    if (window != nullptr && GetClientRect(window, &client_rect)) {
        event.client_width = client_rect.right - client_rect.left;
        event.client_height = client_rect.bottom - client_rect.top;
    }
    auto& memory = ProcessMemory::Instance();
    const auto scale_x_address =
        memory.ResolveGameAddressOrZero(kWindowInputScaleXGlobal);
    const auto scale_y_address =
        memory.ResolveGameAddressOrZero(kWindowInputScaleYGlobal);
    if (scale_x_address != 0) {
        (void)memory.TryReadValue(scale_x_address, &event.input_scale_x);
    }
    if (scale_y_address != 0) {
        (void)memory.TryReadValue(scale_y_address, &event.input_scale_y);
    }
    if (!std::isfinite(event.input_scale_x) ||
        std::abs(event.input_scale_x) <= 0.0001f) {
        event.input_scale_x = 1.0f;
    }
    if (!std::isfinite(event.input_scale_y) ||
        std::abs(event.input_scale_y) <= 0.0001f) {
        event.input_scale_y = 1.0f;
    }
    if (HasMouseCoordinates(message)) {
        event.raw_x = GET_X_LPARAM(lparam);
        event.raw_y = GET_Y_LPARAM(lparam);
        event.native_x = static_cast<std::int32_t>(std::lround(
            static_cast<double>(event.raw_x) / event.input_scale_x));
        event.native_y = static_cast<std::int32_t>(std::lround(
            static_cast<double>(event.raw_y) / event.input_scale_y));
    }
    event.key_repeat = static_cast<std::uint32_t>(lparam) & 0xFFFFu;
    event.key_scancode =
        (static_cast<std::uint32_t>(lparam) >> 16u) & 0xFFu;
    event.key_extended =
        ((static_cast<std::uint32_t>(lparam) >> 24u) & 1u) != 0;
    event.key_previous_down =
        ((static_cast<std::uint32_t>(lparam) >> 30u) & 1u) != 0;
    event.key_transition_up =
        ((static_cast<std::uint32_t>(lparam) >> 31u) & 1u) != 0;
    AppendEvent(std::move(event));
}

void ObserveNativeInputRefresh(
    std::uintptr_t input_state_address,
    std::string_view stage) {
    if (!g_native_input_trace.active.load(std::memory_order_acquire) ||
        input_state_address == 0) {
        return;
    }

    TraceEvent event;
    event.kind = TraceEventKind::InputSample;
    event.stage.assign(stage.begin(), stage.end());
    auto& memory = ProcessMemory::Instance();
    const bool have_buffer_index = memory.TryReadField(
        input_state_address,
        kGameplayInputBufferIndexOffset,
        &event.input_buffer_index);
    bool have_buttons = false;
    if (have_buffer_index && event.input_buffer_index >= 0 &&
        event.input_buffer_index <
            static_cast<std::int32_t>(kGameplayInputBufferCount)) {
        const auto buffer_offset = static_cast<std::size_t>(
            event.input_buffer_index * kGameplayInputBufferStride);
        std::uint8_t left = 0;
        std::uint8_t right = 0;
        std::uint8_t middle = 0;
        have_buttons =
            memory.TryReadField(
                input_state_address,
                buffer_offset + kGameplayMouseLeftButtonOffset,
                &left) &&
            memory.TryReadField(
                input_state_address,
                buffer_offset + kGameplayMouseRightButtonOffset,
                &right) &&
            memory.TryReadField(
                input_state_address,
                buffer_offset + kGameplayMouseRightButtonOffset + 1,
                &middle);
        event.mouse_left = left != 0;
        event.mouse_right = right != 0;
        event.mouse_middle = middle != 0;
    }
    const bool have_raw_mask = memory.TryReadField(
        input_state_address,
        kGameplayInputMouseButtonMaskOffset,
        &event.raw_mouse_mask);
    event.state_readable =
        have_buffer_index && have_buttons && have_raw_mask;

    std::uintptr_t gameplay_address = 0;
    if (TryResolveGameplay(&gameplay_address)) {
        ReadGameplayState(gameplay_address, &event);
        ReadCursorAndPlayerState(gameplay_address, 0, &event);
    }
    AppendEvent(std::move(event));
}

void ObserveNativeInputActorPostTick(
    std::uintptr_t gameplay_address,
    std::uintptr_t actor_address,
    const NativeInputActiveSpellObservation& active_spell) {
    auto& trace = g_native_input_trace;
    if (!trace.active.load(std::memory_order_acquire) ||
        gameplay_address == 0 || actor_address == 0) {
        return;
    }
    trace.simulation_tick.fetch_add(1, std::memory_order_acq_rel);

    TraceEvent event;
    event.kind = TraceEventKind::ActorTick;
    event.active_spell = active_spell;
    auto& memory = ProcessMemory::Instance();
    event.actor_readable =
        memory.TryReadField(
            actor_address,
            kActorPositionXOffset,
            &event.player_x) &&
        memory.TryReadField(
            actor_address,
            kActorPositionYOffset,
            &event.player_y) &&
        memory.TryReadField(
            actor_address,
            kActorPrimarySkillIdOffset,
            &event.primary_skill_id) &&
        memory.TryReadField(
            actor_address,
            kActorPreviousSkillIdOffset,
            &event.previous_skill_id);
    ReadGameplayState(gameplay_address, &event);
    ReadCursorAndPlayerState(gameplay_address, actor_address, &event);
    AppendEvent(std::move(event));
}

bool StartNativeInputTrace(
    std::string_view label,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (label.empty() || label.size() > 96) {
        if (error_message != nullptr) {
            *error_message = "trace label must contain 1 through 96 bytes";
        }
        return false;
    }
    auto& state = g_native_input_trace;
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active.load(std::memory_order_relaxed)) {
        if (error_message != nullptr) {
            *error_message = "a native input trace is already active";
        }
        return false;
    }
    state.label.assign(label.begin(), label.end());
    state.events.clear();
    state.events.reserve(kNativeInputTraceCapacity);
    state.next_sequence = 1;
    state.dropped_events = 0;
    state.have_last_input_sample = false;
    state.last_input_sample_tick = 0;
    state.simulation_tick.store(0, std::memory_order_release);
    state.active.store(true, std::memory_order_release);
    return true;
}

std::string SnapshotNativeInputTraceJson() {
    auto& state = g_native_input_trace;
    std::lock_guard<std::mutex> lock(state.mutex);
    return SerializeTraceLocked(
        state,
        state.active.load(std::memory_order_relaxed));
}

std::string StopNativeInputTraceJson() {
    auto& state = g_native_input_trace;
    state.active.store(false, std::memory_order_release);
    std::lock_guard<std::mutex> lock(state.mutex);
    return SerializeTraceLocked(state, false);
}

bool IsNativeInputTraceActive() {
    return g_native_input_trace.active.load(std::memory_order_acquire);
}

}  // namespace sdmod
