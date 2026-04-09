#pragma once

#include <stdint.h>

#ifdef _WIN32
#define SDMOD_PLUGIN_CALL __stdcall
#else
#define SDMOD_PLUGIN_CALL
#endif

#define SDMOD_RUNTIME_API_VERSION "0.2.0"
#define SDMOD_PLUGIN_HOST_ABI_VERSION 2u

#ifdef __cplusplus
extern "C" {
#endif

#pragma pack(push, 1)

typedef struct SDModRuntimeTickContext {
    uint32_t size;
    uint32_t tick_interval_ms;
    uint64_t tick_count;
    uint64_t monotonic_milliseconds;
} SDModRuntimeTickContext;

#pragma pack(pop)

typedef void(SDMOD_PLUGIN_CALL* SDModRuntimeTickCallback)(const SDModRuntimeTickContext* context);

typedef struct SDModHostApi {
    uint32_t size;
    uint32_t abi_version;
    const char* runtime_api_version;
    void(SDMOD_PLUGIN_CALL* log)(const char* mod_id, const char* message);
    int(SDMOD_PLUGIN_CALL* has_capability)(const char* capability);
    void*(SDMOD_PLUGIN_CALL* resolve_game_address)(uint64_t absolute_address);
    int(SDMOD_PLUGIN_CALL* register_runtime_tick_callback)(SDModRuntimeTickCallback callback);
    void(SDMOD_PLUGIN_CALL* unregister_runtime_tick_callback)(SDModRuntimeTickCallback callback);
} SDModHostApi;

typedef struct SDModPluginContext {
    uint32_t size;
    const char* mod_id;
    const char* mod_name;
    const char* mod_version;
    const char* mod_api_version;
    const char* mod_runtime_kind;
    const char* mod_root_path;
    const char* mod_manifest_path;
    const char* stage_root_path;
    const char* runtime_root_path;
    const char* sandbox_root_path;
    const char* data_root_path;
    const char* cache_root_path;
    const char* temp_root_path;
    const char* entry_script_path;
    const char* entry_dll_path;
    const char* const* required_capabilities;
    uint32_t required_capability_count;
    const char* const* optional_capabilities;
    uint32_t optional_capability_count;
} SDModPluginContext;

typedef int(SDMOD_PLUGIN_CALL* SDModPluginInitializeFn)(
    const SDModHostApi* host_api,
    const SDModPluginContext* plugin_context);

typedef void(SDMOD_PLUGIN_CALL* SDModPluginShutdownFn)();

#ifdef __cplusplus
}
#endif
