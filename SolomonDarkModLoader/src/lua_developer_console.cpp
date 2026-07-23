#include "lua_developer_console.h"

#include "logger.h"
#include "lua_draw_runtime.h"
#include "lua_engine.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

constexpr char kLuaDeveloperConsoleOwner[] = "__loader.lua_console";
constexpr std::size_t kLuaDeveloperConsoleMaximumInputBytes = 4096;
constexpr std::size_t kLuaDeveloperConsoleMaximumOutputLines = 128;
constexpr std::size_t kLuaDeveloperConsoleMaximumHistoryEntries = 64;
constexpr std::size_t kLuaDeveloperConsoleMaximumDisplayColumns = 156;

struct LuaDeveloperConsoleState {
    bool initialized = false;
    bool open = false;
    bool suppress_next_toggle_character = false;
    std::string target_mod_id;
    std::string input;
    std::string history_draft;
    std::vector<std::string> history;
    std::size_t history_cursor = 0;
    std::deque<std::string> output;
    std::size_t pending_requests = 0;
    std::mutex mutex;
};

struct LuaDeveloperConsoleRenderSnapshot {
    bool open = false;
    std::string target_mod_id;
    std::string input;
    std::vector<std::string> output;
    std::size_t pending_requests = 0;
};

LuaDeveloperConsoleState g_lua_developer_console;

bool IsControlDown() {
    return (GetKeyState(VK_CONTROL) & 0x8000) != 0;
}

std::string SanitizeDisplayText(std::string_view text) {
    std::string sanitized;
    sanitized.reserve((std::min)(text.size(), kLuaDeveloperConsoleMaximumDisplayColumns));
    for (const unsigned char character : text) {
        if (sanitized.size() >= kLuaDeveloperConsoleMaximumDisplayColumns) {
            break;
        }
        if (character == '\t') {
            const auto spaces = (std::min)(
                std::size_t{4},
                kLuaDeveloperConsoleMaximumDisplayColumns - sanitized.size());
            sanitized.append(spaces, ' ');
        } else if (character >= 32 && character <= 126) {
            sanitized.push_back(static_cast<char>(character));
        } else {
            sanitized.push_back('?');
        }
    }
    if (text.size() > kLuaDeveloperConsoleMaximumDisplayColumns &&
        sanitized.size() >= 3) {
        sanitized.resize(kLuaDeveloperConsoleMaximumDisplayColumns - 3);
        sanitized.append("...");
    }
    return sanitized;
}

void AppendOutputLineLocked(std::string line) {
    g_lua_developer_console.output.push_back(std::move(line));
    while (g_lua_developer_console.output.size() >
        kLuaDeveloperConsoleMaximumOutputLines) {
        g_lua_developer_console.output.pop_front();
    }
}

void AppendOutputTextLocked(std::string_view text, std::string_view first_prefix) {
    std::size_t offset = 0;
    bool first = true;
    while (offset <= text.size()) {
        const auto newline = text.find('\n', offset);
        const auto length = newline == std::string_view::npos
            ? text.size() - offset
            : newline - offset;
        std::string line(first ? first_prefix : "  ");
        line.append(SanitizeDisplayText(text.substr(offset, length)));
        AppendOutputLineLocked(std::move(line));
        first = false;
        if (newline == std::string_view::npos) {
            break;
        }
        offset = newline + 1;
    }
}

LuaDrawCommand MakeRectangleCommand(
    LuaDrawCommandKind kind,
    float x,
    float y,
    float width,
    float height,
    LuaDrawColor color,
    float thickness = 1.0f) {
    LuaDrawCommand command;
    command.kind = kind;
    command.x = x;
    command.y = y;
    command.width = width;
    command.height = height;
    command.color = color;
    command.thickness = thickness;
    return command;
}

LuaDrawCommand MakeTextCommand(
    float x,
    float y,
    std::string text,
    LuaDrawColor color,
    float scale = 0.8f) {
    LuaDrawCommand command;
    command.kind = LuaDrawCommandKind::Text;
    command.x = x;
    command.y = y;
    command.text = std::move(text);
    command.color = color;
    command.scale = scale;
    return command;
}

void SubmitConsoleDrawCommand(LuaDrawCommand command) {
    std::string error_message;
    if (!SubmitLuaDrawCommand(
            kLuaDeveloperConsoleOwner,
            std::move(command),
            &error_message)) {
        Log("[lua-console] draw command rejected: " + error_message);
    }
}

LuaDeveloperConsoleRenderSnapshot SnapshotConsoleForRendering() {
    std::scoped_lock lock(g_lua_developer_console.mutex);
    LuaDeveloperConsoleRenderSnapshot snapshot;
    snapshot.open =
        g_lua_developer_console.initialized && g_lua_developer_console.open;
    if (!snapshot.open) {
        return snapshot;
    }
    snapshot.target_mod_id = g_lua_developer_console.target_mod_id;
    snapshot.input = g_lua_developer_console.input;
    snapshot.pending_requests = g_lua_developer_console.pending_requests;
    snapshot.output.assign(
        g_lua_developer_console.output.begin(),
        g_lua_developer_console.output.end());
    return snapshot;
}

void RefreshLuaDeveloperConsoleFrame() {
    const auto snapshot = SnapshotConsoleForRendering();
    if (!snapshot.open) {
        ClearLuaDrawFrameForMod(kLuaDeveloperConsoleOwner);
        return;
    }

    std::uint32_t viewport_width = 1280;
    std::uint32_t viewport_height = 720;
    std::string viewport_error;
    TryGetLuaDrawViewport(&viewport_width, &viewport_height, &viewport_error);

    const float panel_margin = 24.0f;
    const float panel_width = (std::max)(
        600.0f,
        (std::min)(1100.0f, static_cast<float>(viewport_width) - panel_margin * 2.0f));
    const float panel_height = (std::max)(
        280.0f,
        (std::min)(600.0f, static_cast<float>(viewport_height) * 0.68f));
    const float panel_x =
        (std::max)(panel_margin, (static_cast<float>(viewport_width) - panel_width) * 0.5f);
    const float panel_y = panel_margin;
    constexpr float text_x_padding = 14.0f;
    constexpr float line_height = 16.0f;

    BeginLuaDrawFrame(kLuaDeveloperConsoleOwner);
    SubmitConsoleDrawCommand(MakeRectangleCommand(
        LuaDrawCommandKind::FilledRect,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        LuaDrawColor{8, 10, 16, 232}));
    SubmitConsoleDrawCommand(MakeRectangleCommand(
        LuaDrawCommandKind::OutlinedRect,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        LuaDrawColor{235, 184, 72, 255},
        2.0f));

    const std::string target = snapshot.target_mod_id.empty()
        ? std::string("<no loaded Lua mod>")
        : snapshot.target_mod_id;
    SubmitConsoleDrawCommand(MakeTextCommand(
        panel_x + text_x_padding,
        panel_y + 12.0f,
        "Lua Console  |  target: " + target +
            "  |  pending: " + std::to_string(snapshot.pending_requests) +
            "  |  Ctrl+` close",
        LuaDrawColor{248, 211, 121, 255},
        0.85f));

    const float output_top = panel_y + 42.0f;
    const float prompt_y = panel_y + panel_height - 30.0f;
    const auto visible_line_count = static_cast<std::size_t>((std::max)(
        1.0f,
        (prompt_y - output_top - 8.0f) / line_height));
    const std::size_t first_line = snapshot.output.size() > visible_line_count
        ? snapshot.output.size() - visible_line_count
        : 0;
    float text_y = output_top;
    for (std::size_t index = first_line; index < snapshot.output.size(); ++index) {
        SubmitConsoleDrawCommand(MakeTextCommand(
            panel_x + text_x_padding,
            text_y,
            snapshot.output[index],
            LuaDrawColor{218, 224, 235, 255}));
        text_y += line_height;
    }

    std::string prompt = "> ";
    prompt.append(SanitizeDisplayText(snapshot.input));
    prompt.push_back('_');
    SubmitConsoleDrawCommand(MakeTextCommand(
        panel_x + text_x_padding,
        prompt_y,
        std::move(prompt),
        LuaDrawColor{150, 232, 176, 255},
        0.85f));
    CommitLuaDrawFrame(kLuaDeveloperConsoleOwner);
}

void CompleteConsoleRequest(LuaExecResult result) {
    bool refresh = false;
    {
        std::scoped_lock lock(g_lua_developer_console.mutex);
        if (!g_lua_developer_console.initialized) {
            return;
        }
        if (g_lua_developer_console.pending_requests != 0) {
            --g_lua_developer_console.pending_requests;
        }
        if (!result.print_output.empty()) {
            AppendOutputTextLocked(result.print_output, "  ");
        }
        for (const auto& value : result.results) {
            AppendOutputTextLocked(value, "= ");
        }
        if (!result.error.empty()) {
            AppendOutputTextLocked(result.error, "! ");
        } else if (result.ok && result.print_output.empty() && result.results.empty()) {
            AppendOutputLineLocked("= ok");
        }
        refresh = g_lua_developer_console.open;
    }
    if (refresh) {
        RefreshLuaDeveloperConsoleFrame();
    }
}

void ExecuteConsoleInput() {
    std::string code;
    {
        std::scoped_lock lock(g_lua_developer_console.mutex);
        if (!g_lua_developer_console.initialized ||
            !g_lua_developer_console.open ||
            g_lua_developer_console.input.empty()) {
            return;
        }
        code = std::move(g_lua_developer_console.input);
        g_lua_developer_console.input.clear();
        if (g_lua_developer_console.history.empty() ||
            g_lua_developer_console.history.back() != code) {
            g_lua_developer_console.history.push_back(code);
            if (g_lua_developer_console.history.size() >
                kLuaDeveloperConsoleMaximumHistoryEntries) {
                g_lua_developer_console.history.erase(
                    g_lua_developer_console.history.begin());
            }
        }
        g_lua_developer_console.history_cursor =
            g_lua_developer_console.history.size();
        g_lua_developer_console.history_draft.clear();
        AppendOutputTextLocked(code, "> ");
        ++g_lua_developer_console.pending_requests;
    }

    RefreshLuaDeveloperConsoleFrame();
    QueueLuaExecRequestAsync(code, &CompleteConsoleRequest);
}

void NavigateConsoleHistory(bool older) {
    {
        std::scoped_lock lock(g_lua_developer_console.mutex);
        if (g_lua_developer_console.history.empty()) {
            return;
        }
        if (older) {
            if (g_lua_developer_console.history_cursor ==
                g_lua_developer_console.history.size()) {
                g_lua_developer_console.history_draft =
                    g_lua_developer_console.input;
            }
            if (g_lua_developer_console.history_cursor != 0) {
                --g_lua_developer_console.history_cursor;
            }
        } else if (g_lua_developer_console.history_cursor <
            g_lua_developer_console.history.size()) {
            ++g_lua_developer_console.history_cursor;
        }

        g_lua_developer_console.input =
            g_lua_developer_console.history_cursor <
                g_lua_developer_console.history.size()
            ? g_lua_developer_console.history[
                  g_lua_developer_console.history_cursor]
            : g_lua_developer_console.history_draft;
    }
    RefreshLuaDeveloperConsoleFrame();
}

std::string ReadClipboardUtf8(HWND hwnd) {
    std::string text;
    if (!OpenClipboard(hwnd)) {
        return text;
    }
    const auto clipboard = GetClipboardData(CF_UNICODETEXT);
    if (clipboard != nullptr) {
        const auto* wide_text = static_cast<const wchar_t*>(GlobalLock(clipboard));
        if (wide_text != nullptr) {
            const int required_bytes = WideCharToMultiByte(
                CP_UTF8,
                0,
                wide_text,
                -1,
                nullptr,
                0,
                nullptr,
                nullptr);
            if (required_bytes > 1) {
                std::vector<char> utf8(static_cast<std::size_t>(required_bytes));
                WideCharToMultiByte(
                    CP_UTF8,
                    0,
                    wide_text,
                    -1,
                    utf8.data(),
                    required_bytes,
                    nullptr,
                    nullptr);
                text.assign(utf8.data(), static_cast<std::size_t>(required_bytes - 1));
            }
            GlobalUnlock(clipboard);
        }
    }
    CloseClipboard();

    text.erase(
        std::remove(text.begin(), text.end(), '\r'),
        text.end());
    return text;
}

void PasteConsoleClipboard(HWND hwnd) {
    const auto pasted = ReadClipboardUtf8(hwnd);
    if (pasted.empty()) {
        return;
    }
    {
        std::scoped_lock lock(g_lua_developer_console.mutex);
        const auto remaining =
            kLuaDeveloperConsoleMaximumInputBytes -
            g_lua_developer_console.input.size();
        g_lua_developer_console.input.append(pasted.substr(0, remaining));
    }
    RefreshLuaDeveloperConsoleFrame();
}

void ToggleLuaDeveloperConsole() {
    const auto target_mod_id = GetLuaExecTargetModId();
    bool opened = false;
    {
        std::scoped_lock lock(g_lua_developer_console.mutex);
        if (!g_lua_developer_console.initialized) {
            return;
        }
        g_lua_developer_console.open = !g_lua_developer_console.open;
        g_lua_developer_console.suppress_next_toggle_character = true;
        g_lua_developer_console.target_mod_id = target_mod_id;
        g_lua_developer_console.history_cursor =
            g_lua_developer_console.history.size();
        opened = g_lua_developer_console.open;
    }
    if (opened) {
        RefreshLuaDeveloperConsoleFrame();
    } else {
        ClearLuaDrawFrameForMod(kLuaDeveloperConsoleOwner);
    }
}

bool IsInitialKeyPress(LPARAM lparam) {
    return (static_cast<std::uint32_t>(lparam) & (1u << 30)) == 0;
}

}  // namespace

void InitializeLuaDeveloperConsole() {
    std::scoped_lock lock(g_lua_developer_console.mutex);
    g_lua_developer_console.initialized = true;
    g_lua_developer_console.open = false;
    g_lua_developer_console.suppress_next_toggle_character = false;
    g_lua_developer_console.target_mod_id.clear();
    g_lua_developer_console.input.clear();
    g_lua_developer_console.history_draft.clear();
    g_lua_developer_console.history.clear();
    g_lua_developer_console.history_cursor = 0;
    g_lua_developer_console.output.clear();
    g_lua_developer_console.pending_requests = 0;
    Log("Lua developer console initialized (Ctrl+`).");
}

void ShutdownLuaDeveloperConsole() {
    {
        std::scoped_lock lock(g_lua_developer_console.mutex);
        g_lua_developer_console.initialized = false;
        g_lua_developer_console.open = false;
        g_lua_developer_console.suppress_next_toggle_character = false;
        g_lua_developer_console.target_mod_id.clear();
        g_lua_developer_console.input.clear();
        g_lua_developer_console.history_draft.clear();
        g_lua_developer_console.history.clear();
        g_lua_developer_console.history_cursor = 0;
        g_lua_developer_console.output.clear();
        g_lua_developer_console.pending_requests = 0;
    }
    ClearLuaDrawFrameForMod(kLuaDeveloperConsoleOwner);
}

bool IsLuaDeveloperConsoleOpen() {
    std::scoped_lock lock(g_lua_developer_console.mutex);
    return g_lua_developer_console.initialized && g_lua_developer_console.open;
}

bool HandleLuaDeveloperConsoleWindowMessage(
    HWND hwnd,
    UINT message,
    WPARAM wparam,
    LPARAM lparam) {
    if (message == WM_KEYDOWN &&
        wparam == VK_OEM_3 &&
        IsControlDown() &&
        IsInitialKeyPress(lparam)) {
        ToggleLuaDeveloperConsole();
        return true;
    }

    if (message == WM_CHAR) {
        bool suppress_toggle_character = false;
        {
            std::scoped_lock lock(g_lua_developer_console.mutex);
            suppress_toggle_character =
                g_lua_developer_console.suppress_next_toggle_character;
            if (suppress_toggle_character) {
                g_lua_developer_console.suppress_next_toggle_character = false;
            }
        }
        if (suppress_toggle_character && (wparam == '`' || wparam == '~')) {
            return true;
        }
    }

    if (!IsLuaDeveloperConsoleOpen()) {
        return false;
    }

    if (message == WM_PASTE ||
        (message == WM_KEYDOWN && wparam == 'V' && IsControlDown())) {
        PasteConsoleClipboard(hwnd);
        return true;
    }
    if (message == WM_KEYUP || message == WM_SYSKEYUP) {
        return false;
    }
    if (message == WM_KEYDOWN) {
        if (wparam == VK_ESCAPE) {
            ToggleLuaDeveloperConsole();
        } else if (wparam == VK_UP && IsInitialKeyPress(lparam)) {
            NavigateConsoleHistory(true);
        } else if (wparam == VK_DOWN && IsInitialKeyPress(lparam)) {
            NavigateConsoleHistory(false);
        } else if (wparam == 'L' && IsControlDown() && IsInitialKeyPress(lparam)) {
            {
                std::scoped_lock lock(g_lua_developer_console.mutex);
                g_lua_developer_console.output.clear();
            }
            RefreshLuaDeveloperConsoleFrame();
        }
        return true;
    }
    if (message == WM_SYSKEYDOWN) {
        return true;
    }
    if (message != WM_CHAR) {
        return false;
    }

    if (wparam == '\r') {
        ExecuteConsoleInput();
        return true;
    }
    if (wparam == '\b') {
        {
            std::scoped_lock lock(g_lua_developer_console.mutex);
            if (!g_lua_developer_console.input.empty()) {
                auto character_start = g_lua_developer_console.input.size() - 1;
                while (character_start != 0 &&
                    (static_cast<unsigned char>(
                         g_lua_developer_console.input[character_start]) & 0xC0u) == 0x80u) {
                    --character_start;
                }
                g_lua_developer_console.input.erase(character_start);
            }
        }
        RefreshLuaDeveloperConsoleFrame();
        return true;
    }
    if (wparam >= 32 && wparam <= 126) {
        {
            std::scoped_lock lock(g_lua_developer_console.mutex);
            if (g_lua_developer_console.input.size() <
                kLuaDeveloperConsoleMaximumInputBytes) {
                g_lua_developer_console.input.push_back(
                    static_cast<char>(wparam));
            }
        }
        RefreshLuaDeveloperConsoleFrame();
    }
    return true;
}

}  // namespace sdmod
