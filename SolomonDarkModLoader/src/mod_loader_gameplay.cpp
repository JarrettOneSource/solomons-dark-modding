#include "bot_runtime.h"
#include "d3d9_end_scene_hook.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "lua_engine.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "runtime_debug.h"
#include "runtime_tick_service.h"
#include "sdmod_plugin_api.h"
#include "x86_hook.h"

#include <Windows.h>
#include <d3d9.h>
#include <intrin.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <cwctype>
#include <deque>
#include <filesystem>
#include <fstream>
#include <limits>
#include <malloc.h>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

#include "mod_loader_gameplay/core/native_function_types.inl"
#include "mod_loader_gameplay/core/seh_safe_call_declarations.inl"
#include "mod_loader_gameplay/core/gameplay_constants.inl"
#include "mod_loader_gameplay/core/synthetic_wizard_source_profiles.inl"
#include "mod_loader_gameplay/core/runtime_request_state.inl"
#include "mod_loader_gameplay/core/participant_entity_state.inl"
#include "mod_loader_gameplay/core/participant_kind_helpers.inl"
#include "mod_loader_gameplay/core/participant_snapshot_types.inl"
#include "mod_loader_gameplay/core/gameplay_state_globals.inl"
#include "mod_loader_gameplay/core/crash_summary_builders.inl"
#include "mod_loader_gameplay/core/internal_forward_declarations.inl"
#include "mod_loader_gameplay/core/standalone_owner_repair.inl"

#include "mod_loader_gameplay/scene_and_animation.inl"
#include "mod_loader_gameplay/standalone_materialization.inl"
#include "mod_loader_gameplay/bot_pathfinding.inl"
#include "mod_loader_gameplay/bot_registry_and_movement.inl"
#include "mod_loader_gameplay/dispatch_and_hooks.inl"

}  // namespace

#include "mod_loader_gameplay/public_api.inl"

}  // namespace sdmod
