#define NOMINMAX
#include <Windows.h>

#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <string>
#include <vector>

namespace {

[[noreturn]] void Fail(const char* message, int exit_code) {
    std::fprintf(stderr, "%s\n", message);
    std::exit(exit_code);
}

double ParseFraction(const char* text, const char* label) {
    char* end = nullptr;
    errno = 0;
    const double value = std::strtod(text, &end);
    if (errno != 0 || end == text || *end != '\0' ||
        !std::isfinite(value) || value < 0.0 || value > 1.0) {
        std::fprintf(stderr, "%s must be a finite 0..1 fraction\n", label);
        std::exit(3);
    }
    return value;
}

DWORD ParseHoldMilliseconds(const char* text) {
    char* end = nullptr;
    errno = 0;
    const unsigned long value = std::strtoul(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' ||
        value > 5000UL) {
        std::fprintf(
            stderr,
            "hold-milliseconds must be an integer from 0 through 5000\n");
        std::exit(4);
    }
    return static_cast<DWORD>(value);
}

DWORD ParseProcessId(const char* text) {
    char* end = nullptr;
    errno = 0;
    const unsigned long value = std::strtoul(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value == 0 ||
        value > MAXDWORD) {
        Fail("process-id must be a nonzero integer", 5);
    }
    return static_cast<DWORD>(value);
}

std::wstring Utf8ToWide(const char* text) {
    const int count = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        text,
        -1,
        nullptr,
        0);
    if (count <= 0) {
        Fail("expected-executable-path is not valid UTF-8", 6);
    }
    std::vector<wchar_t> value(static_cast<std::size_t>(count));
    if (MultiByteToWideChar(
            CP_UTF8,
            MB_ERR_INVALID_CHARS,
            text,
            -1,
            value.data(),
            count) != count) {
        Fail("expected-executable-path conversion failed", 6);
    }
    return std::wstring(value.data());
}

void RequireExpectedProcess(DWORD process_id, const wchar_t* expected_path) {
    HANDLE process = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        FALSE,
        process_id);
    if (process == nullptr) {
        std::fprintf(
            stderr,
            "OpenProcess failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(7);
    }
    std::vector<wchar_t> path(32768);
    DWORD path_length = static_cast<DWORD>(path.size());
    const BOOL queried = QueryFullProcessImageNameW(
        process,
        0,
        path.data(),
        &path_length);
    CloseHandle(process);
    if (!queried) {
        std::fprintf(
            stderr,
            "QueryFullProcessImageName failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(8);
    }
    const std::wstring actual(path.data(), path_length);
    if (_wcsicmp(actual.c_str(), expected_path) != 0) {
        Fail("process executable does not match the exact staged path", 9);
    }
}

struct WindowSearch {
    DWORD process_id = 0;
    HWND match = nullptr;
    unsigned int match_count = 0;
};

bool ProcessPathMatches(DWORD process_id, const wchar_t* expected_path) {
    HANDLE process = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        FALSE,
        process_id);
    if (process == nullptr) {
        return false;
    }
    std::vector<wchar_t> path(32768);
    DWORD path_length = static_cast<DWORD>(path.size());
    const BOOL queried = QueryFullProcessImageNameW(
        process,
        0,
        path.data(),
        &path_length);
    CloseHandle(process);
    if (!queried) {
        return false;
    }
    const std::wstring actual(path.data(), path_length);
    return _wcsicmp(actual.c_str(), expected_path) == 0;
}

BOOL CALLBACK VisitWindow(HWND window, LPARAM parameter) {
    auto* search = reinterpret_cast<WindowSearch*>(parameter);
    DWORD process_id = 0;
    GetWindowThreadProcessId(window, &process_id);
    if (process_id != search->process_id || !IsWindowVisible(window)) {
        return TRUE;
    }
    wchar_t title[64]{};
    GetWindowTextW(window, title, static_cast<int>(std::size(title)));
    if (std::wcscmp(title, L"SolomonDark") != 0) {
        return TRUE;
    }
    search->match = window;
    search->match_count += 1;
    return TRUE;
}

HWND FindGameWindow(DWORD process_id) {
    WindowSearch search{};
    search.process_id = process_id;
    if (!EnumWindows(VisitWindow, reinterpret_cast<LPARAM>(&search))) {
        std::fprintf(
            stderr,
            "EnumWindows failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(10);
    }
    if (search.match_count != 1 || search.match == nullptr) {
        std::fprintf(
            stderr,
            "expected one visible SolomonDark window for process %lu; "
            "found %u\n",
            static_cast<unsigned long>(process_id),
            search.match_count);
        std::exit(11);
    }
    return search.match;
}

struct ExactPathWindowSearch {
    const wchar_t* expected_path = nullptr;
    HWND match = nullptr;
    unsigned int match_count = 0;
};

BOOL CALLBACK VisitExactPathWindow(HWND window, LPARAM parameter) {
    auto* search =
        reinterpret_cast<ExactPathWindowSearch*>(parameter);
    if (!IsWindowVisible(window)) {
        return TRUE;
    }
    wchar_t title[64]{};
    GetWindowTextW(window, title, static_cast<int>(std::size(title)));
    if (std::wcscmp(title, L"SolomonDark") != 0) {
        return TRUE;
    }
    DWORD process_id = 0;
    GetWindowThreadProcessId(window, &process_id);
    if (!ProcessPathMatches(process_id, search->expected_path)) {
        return TRUE;
    }
    search->match = window;
    search->match_count += 1;
    return TRUE;
}

HWND FindGameWindowForExactPath(const wchar_t* expected_path) {
    ExactPathWindowSearch search{};
    search.expected_path = expected_path;
    if (!EnumWindows(
            VisitExactPathWindow,
            reinterpret_cast<LPARAM>(&search))) {
        std::fprintf(
            stderr,
            "EnumWindows failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(10);
    }
    if (search.match_count != 1 || search.match == nullptr) {
        std::fprintf(
            stderr,
            "expected one visible SolomonDark window for the exact staged "
            "path; found %u\n",
            search.match_count);
        std::exit(11);
    }
    return search.match;
}

void FocusWindow(HWND window) {
    DWORD target_process_id = 0;
    const DWORD target_thread_id =
        GetWindowThreadProcessId(window, &target_process_id);
    const DWORD current_thread_id = GetCurrentThreadId();
    const BOOL attached =
        target_thread_id != 0 &&
        target_thread_id != current_thread_id &&
        AttachThreadInput(
            current_thread_id,
            target_thread_id,
            TRUE);
    for (int attempt = 0; attempt < 3; ++attempt) {
        ShowWindow(window, SW_RESTORE);
        BringWindowToTop(window);
        SetActiveWindow(window);
        SetFocus(window);
        INPUT alt_down{};
        alt_down.type = INPUT_KEYBOARD;
        alt_down.ki.wVk = VK_MENU;
        INPUT alt_up = alt_down;
        alt_up.ki.dwFlags = KEYEVENTF_KEYUP;
        INPUT alt_events[] = {alt_down, alt_up};
        SendInput(
            static_cast<UINT>(std::size(alt_events)),
            alt_events,
            sizeof(INPUT));
        SetForegroundWindow(window);
        if (GetForegroundWindow() == window) {
            break;
        }
        Sleep(100);
    }
    if (attached) {
        AttachThreadInput(
            current_thread_id,
            target_thread_id,
            FALSE);
    }
    if (GetForegroundWindow() != window) {
        Fail("Windows refused to focus the exact game window", 12);
    }
}

void Click(HWND window, double x_fraction, double y_fraction, DWORD hold_ms) {
    DWORD target_process_id = 0;
    GetWindowThreadProcessId(window, &target_process_id);
    RECT client{};
    if (!GetClientRect(window, &client)) {
        std::fprintf(
            stderr,
            "GetClientRect failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(6);
    }
    POINT point{
        static_cast<LONG>(
            std::lround(
                x_fraction * static_cast<double>(client.right - 1))),
        static_cast<LONG>(
            std::lround(
                y_fraction * static_cast<double>(client.bottom - 1))),
    };
    if (!ClientToScreen(window, &point) ||
        !SetCursorPos(point.x, point.y)) {
        std::fprintf(
            stderr,
            "cursor positioning failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(7);
    }
    INPUT down{};
    down.type = INPUT_MOUSE;
    down.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    INPUT up{};
    up.type = INPUT_MOUSE;
    up.mi.dwFlags = MOUSEEVENTF_LEFTUP;
    if (SendInput(1, &down, sizeof(INPUT)) != 1) {
        std::fprintf(
            stderr,
            "mouse down failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(8);
    }
    Sleep(hold_ms);
    if (SendInput(1, &up, sizeof(INPUT)) != 1) {
        std::fprintf(
            stderr,
            "mouse up failed with Win32 error %lu\n",
            static_cast<unsigned long>(GetLastError()));
        std::exit(9);
    }
    std::printf(
        "{\"x\":%.8f,\"y\":%.8f,\"holdMilliseconds\":%lu,"
        "\"screenX\":%ld,\"screenY\":%ld,"
        "\"targetProcessId\":%lu}\n",
        x_fraction,
        y_fraction,
        static_cast<unsigned long>(hold_ms),
        static_cast<long>(point.x),
        static_cast<long>(point.y),
        static_cast<unsigned long>(target_process_id));
}

void MessageClick(
    HWND window,
    double x_fraction,
    double y_fraction,
    DWORD hold_ms) {
    DWORD target_process_id = 0;
    GetWindowThreadProcessId(window, &target_process_id);
    RECT client{};
    if (!GetClientRect(window, &client)) {
        Fail("GetClientRect failed for message click", 16);
    }
    const POINT client_point{
        static_cast<LONG>(
            std::lround(
                x_fraction * static_cast<double>(client.right - 1))),
        static_cast<LONG>(
            std::lround(
                y_fraction * static_cast<double>(client.bottom - 1))),
    };
    POINT screen_point = client_point;
    if (!ClientToScreen(window, &screen_point) ||
        !SetCursorPos(screen_point.x, screen_point.y)) {
        Fail("cursor positioning failed for message click", 17);
    }

    const LPARAM position = MAKELPARAM(client_point.x, client_point.y);
    const auto send = [window, position](
                          UINT message,
                          WPARAM buttons,
                          const char* name) {
        DWORD_PTR ignored = 0;
        SetLastError(ERROR_SUCCESS);
        if (!SendMessageTimeoutW(
                window,
                message,
                buttons,
                position,
                SMTO_ABORTIFHUNG | SMTO_BLOCK,
                5000,
                &ignored)) {
            std::fprintf(
                stderr,
                "%s failed with Win32 error %lu\n",
                name,
                static_cast<unsigned long>(GetLastError()));
            std::exit(18);
        }
    };

    send(WM_MOUSEMOVE, 0, "WM_MOUSEMOVE");
    send(WM_LBUTTONDOWN, MK_LBUTTON, "WM_LBUTTONDOWN");
    Sleep(hold_ms);
    send(WM_LBUTTONUP, 0, "WM_LBUTTONUP");
    std::printf(
        "{\"delivery\":\"SendMessageTimeoutW\",\"x\":%.8f,"
        "\"y\":%.8f,\"holdMilliseconds\":%lu,"
        "\"clientX\":%ld,\"clientY\":%ld,"
        "\"screenX\":%ld,\"screenY\":%ld,"
        "\"targetProcessId\":%lu}\n",
        x_fraction,
        y_fraction,
        static_cast<unsigned long>(hold_ms),
        static_cast<long>(client_point.x),
        static_cast<long>(client_point.y),
        static_cast<long>(screen_point.x),
        static_cast<long>(screen_point.y),
        static_cast<unsigned long>(target_process_id));
}

WORD VirtualKey(const char* key) {
    if (std::strcmp(key, "enter") == 0) return VK_RETURN;
    if (std::strcmp(key, "escape") == 0) return VK_ESCAPE;
    if (std::strcmp(key, "space") == 0) return VK_SPACE;
    if (std::strcmp(key, "tab") == 0) return VK_TAB;
    if (std::strcmp(key, "up") == 0) return VK_UP;
    if (std::strcmp(key, "down") == 0) return VK_DOWN;
    if (std::strcmp(key, "left") == 0) return VK_LEFT;
    if (std::strcmp(key, "right") == 0) return VK_RIGHT;
    if (std::strcmp(key, "f9") == 0) return VK_F9;
    if (std::strlen(key) == 1 && key[0] >= 'a' && key[0] <= 'z') {
        return static_cast<WORD>('A' + key[0] - 'a');
    }
    Fail("key is unsupported", 13);
}

void Key(const char* key, DWORD hold_ms, DWORD process_id) {
    INPUT down{};
    down.type = INPUT_KEYBOARD;
    down.ki.wVk = VirtualKey(key);
    INPUT up = down;
    up.ki.dwFlags = KEYEVENTF_KEYUP;
    if (SendInput(1, &down, sizeof(INPUT)) != 1) {
        Fail("key down failed", 14);
    }
    Sleep(hold_ms);
    if (SendInput(1, &up, sizeof(INPUT)) != 1) {
        Fail("key up failed", 15);
    }
    std::printf(
        "{\"key\":\"%s\",\"holdMilliseconds\":%lu,"
        "\"targetProcessId\":%lu}\n",
        key,
        static_cast<unsigned long>(hold_ms),
        static_cast<unsigned long>(process_id));
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(
            stderr,
            "usage: win32_real_input click <process-id> "
            "<expected-executable-path> <x-fraction> <y-fraction> "
            "<hold-milliseconds>\n"
            "       win32_real_input click-path "
            "<expected-executable-path> <x-fraction> <y-fraction> "
            "<hold-milliseconds>\n"
            "       win32_real_input message-click <process-id> "
            "<expected-executable-path> <x-fraction> <y-fraction> "
            "<hold-milliseconds>\n"
            "       win32_real_input key <process-id> "
            "<expected-executable-path> <key> <hold-milliseconds>\n");
        return 2;
    }
    const bool is_click = std::strcmp(argv[1], "click") == 0;
    const bool is_click_path =
        std::strcmp(argv[1], "click-path") == 0;
    const bool is_message_click =
        std::strcmp(argv[1], "message-click") == 0;
    const bool is_key = std::strcmp(argv[1], "key") == 0;
    if ((!is_click && !is_click_path && !is_message_click && !is_key) ||
        (is_click && argc != 7) ||
        (is_click_path && argc != 6) ||
        (is_message_click && argc != 7) ||
        (is_key && argc != 6)) {
        Fail("invalid real-input command line", 2);
    }
    if (is_click_path) {
        const std::wstring expected_path = Utf8ToWide(argv[2]);
        const HWND window =
            FindGameWindowForExactPath(expected_path.c_str());
        FocusWindow(window);
        Click(
            window,
            ParseFraction(argv[3], "x-fraction"),
            ParseFraction(argv[4], "y-fraction"),
            ParseHoldMilliseconds(argv[5]));
        return 0;
    }
    const DWORD process_id = ParseProcessId(argv[2]);
    const std::wstring expected_path = Utf8ToWide(argv[3]);
    RequireExpectedProcess(process_id, expected_path.c_str());
    const HWND window = FindGameWindow(process_id);
    FocusWindow(window);
    if (is_click) {
        Click(
            window,
            ParseFraction(argv[4], "x-fraction"),
            ParseFraction(argv[5], "y-fraction"),
            ParseHoldMilliseconds(argv[6]));
    } else if (is_message_click) {
        MessageClick(
            window,
            ParseFraction(argv[4], "x-fraction"),
            ParseFraction(argv[5], "y-fraction"),
            ParseHoldMilliseconds(argv[6]));
    } else {
        Key(argv[4], ParseHoldMilliseconds(argv[5]), process_id);
    }
    return 0;
}
