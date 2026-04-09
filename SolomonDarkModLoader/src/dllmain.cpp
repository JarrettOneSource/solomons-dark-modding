#include "mod_loader.h"

#include <Windows.h>

namespace {

DWORD WINAPI InitializeLoaderThread(LPVOID parameter) {
    sdmod::Initialize(static_cast<HMODULE>(parameter));
    return 0;
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE module_handle, DWORD reason, LPVOID reserved) {
    (void)reserved;

    switch (reason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(module_handle);
        if (const auto init_thread = CreateThread(nullptr, 0, &InitializeLoaderThread, module_handle, 0, nullptr);
            init_thread != nullptr) {
            CloseHandle(init_thread);
        }
        break;
    case DLL_PROCESS_DETACH:
        sdmod::Shutdown();
        break;
    default:
        break;
    }

    return TRUE;
}
