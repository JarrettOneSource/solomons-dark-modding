#pragma once

#include <Windows.h>

namespace sdmod {

void InitializeLuaDeveloperConsole();
void ShutdownLuaDeveloperConsole();
bool IsLuaDeveloperConsoleOpen();
bool HandleLuaDeveloperConsoleWindowMessage(
    HWND hwnd,
    UINT message,
    WPARAM wparam,
    LPARAM lparam);

}  // namespace sdmod
