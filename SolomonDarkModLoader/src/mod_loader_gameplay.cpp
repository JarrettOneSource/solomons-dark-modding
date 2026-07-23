#include "bot_runtime.h"
#include "d3d9_end_scene_hook.h"
#include "debug_ui_overlay.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "lua_draw_runtime.h"
#include "lua_engine.h"
#include "lua_event_filters.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "native_enemy_lifecycle.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"
#include "multiplayer_service_loop.h"
#include "native_spell_stats.h"
#include "runtime_debug.h"
#include "runtime_tick_service.h"
#include "x86_hook.h"

#include <Windows.h>
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
#include <functional>
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
#include "mod_loader_gameplay/core/actor_world_target_slot_state.inl"
#include "mod_loader_gameplay/core/runtime_request_state.inl"
#include "mod_loader_gameplay/core/participant_entity_state.inl"
#include "mod_loader_gameplay/core/participant_kind_helpers.inl"
#include "mod_loader_gameplay/core/participant_snapshot_types.inl"
#include "mod_loader_gameplay/core/gameplay_state_globals.inl"
#include "mod_loader_gameplay/core/crash_summary_builders.inl"
#include "mod_loader_gameplay/core/internal_forward_declarations.inl"
#include "mod_loader_gameplay/core/standalone_owner_repair.inl"
#include "mod_loader_gameplay/core/standalone_progression_slot_context.inl"
#include "mod_loader_gameplay/core/scoped_actor_cast_origin_context.inl"
#include "mod_loader_gameplay/core/scoped_secondary_cursor_world_placement_context.inl"
#include "mod_loader_gameplay/core/scoped_actor_slot_context.inl"
#include "mod_loader_gameplay/core/stock_dampen_effect_context.inl"
#include "mod_loader_gameplay/core/run_generation_seed_helpers.inl"
#include "mod_loader_gameplay/core/boneyard_generator_patch.inl"

#include "mod_loader_gameplay/scene_and_animation.inl"
#include "mod_loader_gameplay/lua_spell_cast_filter.inl"
#include "mod_loader_gameplay/standalone_materialization.inl"
#include "mod_loader_gameplay/bot_pathfinding.inl"
#include "mod_loader_gameplay/bot_registry_and_movement.inl"
#include "mod_loader_gameplay/lua_enemy_ai_runtime.inl"
#include "mod_loader_gameplay/dispatch_and_hooks.inl"

}  // namespace

#include "mod_loader_gameplay/public_api.inl"

}  // namespace sdmod
