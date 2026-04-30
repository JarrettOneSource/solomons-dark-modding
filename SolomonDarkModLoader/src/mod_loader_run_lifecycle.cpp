#include "lua_engine_events.h"
#include "bot_runtime.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "mod_loader_internal.h"
#include "x86_hook.h"

#include <intrin.h>

#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>

namespace sdmod {
namespace {

#include "run_lifecycle/state_and_targets.inl"
#include "run_lifecycle/combat_prelude_and_sources.inl"
#include "run_lifecycle/enemy_tracking_and_reset.inl"
#include "run_lifecycle/spell_cast_hooks.inl"
#include "run_lifecycle/run_and_enemy_hooks.inl"

}  // namespace

#include "run_lifecycle/public_api_and_install.inl"

}  // namespace sdmod
