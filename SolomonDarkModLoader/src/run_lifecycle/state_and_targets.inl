using RunStartedFn = void(__fastcall*)(void* self, void* unused_edx);
using MainMenuControlActionFn = void(__thiscall*)(void* self, void* control);
using RunEndedFn = void(__cdecl*)();
using ActorWorldTickFn = void(__fastcall*)(void* self, void* unused_edx);
using ActorWorldEntryFn = void(__thiscall*)(void* self);
using WaveSpawnerTickFn = void(__fastcall*)(void* self, void* unused_edx);
using SpawnExactEnemyGroupFn = void(__thiscall*)(
    void* arena,
    int count,
    std::uint32_t native_type_id,
    int variant,
    void* modifiers,
    int placement_mode,
    int placement_argument,
    int random_placement);
using GameFreeFn = void(__cdecl*)(void* memory);
using EnemySpawnedFn =
    void* (__fastcall*)(void* self, void* unused_edx, void* param_2, int enemy_config, void* param_4, int param_5, int param_6, char param_7);
using EnemyDeathFn = int(__fastcall*)(void* self, void* unused_edx);
using DropSelectorFn = void(__fastcall*)(void* self, void* unused_edx);
using SpellCastFn = void(__fastcall*)(void* self, void* unused_edx);
using AirLightningChainTargetFn =
    void* (__thiscall*)(
        void* self,
        float source_x,
        float source_y,
        float radius,
        std::uint32_t mask,
        void* exclusions);
using GoldChangedFn = int(__stdcall*)(int delta, char allow_negative);
using DropSpawnedFn =
    void(__fastcall*)(void* self, void* unused_edx, std::uint32_t x_bits, std::uint32_t y_bits, int amount, int lifetime);
using LevelUpFn = void(__fastcall*)(void* self, void* unused_edx);

struct HookTarget {
    uintptr_t address;
    size_t patch_size;
};

enum HookIndex : size_t {
    kHookCreateArena = 0,
    kHookMainMenuControlAction,
    kHookStartGame,
    kHookRunEnded,
    kHookActorWorldTick,
    kHookWaveSpawnerTick,
    kHookEnemySpawned,
    kHookEnemyDeath,
    kHookDropSelector,
    kHookSpellCast3EB,
    kHookSpellCast018,
    kHookAirLightningChainTarget,
    kHookSpellCast020,
    kHookSpellCast028,
    kHookSpellCast3EC,
    kHookSpellCast3ED,
    kHookSpellCast3EE,
    kHookSpellCast3EF,
    kHookSpellCast3F0,
    kHookGoldChanged,
    kHookDropSpawned,
    kHookLevelUp,
    kHookCount,
};

struct RunLifecycleState {
    X86Hook hooks[kHookCount] = {};
    std::atomic<int> current_wave{0};
    std::atomic<bool> run_active{false};
    std::atomic<uintptr_t> last_wave_spawner{0};
    std::atomic<uintptr_t> last_wave_spawner_vtable{0};
    std::atomic<std::uint64_t> last_wave_spawner_tick_ms{0};
    std::atomic<uintptr_t> last_arena_enemy_wave_spawner{0};
    std::atomic<uintptr_t> last_arena_enemy_wave_spawner_vtable{0};
    std::atomic<std::uint64_t> last_arena_enemy_wave_spawner_tick_ms{0};
    std::atomic<std::uint64_t> last_dispatched_lua_spell_click_serial{0};
    std::atomic<std::uint64_t> run_start_tick_ms{0};
    std::atomic<bool> combat_prelude_only_suppression{false};
    std::atomic<bool> wave_start_enemy_tracking{false};
    std::atomic<bool> manual_enemy_spawner_test_mode{false};
    std::mutex enemy_type_mutex;
    std::unordered_map<uintptr_t, int> enemy_types_by_address;
    std::unordered_map<uintptr_t, std::uint32_t> enemy_spawn_serials_by_address;
    std::uint32_t next_enemy_spawn_serial = 1;
    std::mutex wave_spawner_log_mutex;
    std::unordered_set<uintptr_t> logged_wave_spawners;
    bool initialized = false;
} g_state;

struct ManualRunEnemySpawnRequest {
    std::uint64_t request_id = 0;
    std::uint64_t network_actor_id = 0;
    int type_id = 0;
    float x = 0.0f;
    float y = 0.0f;
    bool allow_active_waves = false;
    bool freeze_on_spawn = true;
};

struct FrozenManualRunEnemy {
    float x = 0.0f;
    float y = 0.0f;
};

std::mutex g_manual_run_enemy_spawn_mutex;
ManualRunEnemySpawnRequest g_pending_manual_run_enemy_spawn;
ManualRunEnemySpawnRequest g_active_manual_run_enemy_spawn;
SDModManualRunEnemySpawnResult g_last_manual_run_enemy_spawn_result;
bool g_have_pending_manual_run_enemy_spawn = false;
bool g_have_active_manual_run_enemy_spawn = false;
std::uint64_t g_next_manual_run_enemy_spawn_request_id = 1;
std::deque<ManualRunEnemySpawnRequest> g_queued_replicated_run_enemy_spawns;
std::unordered_map<uintptr_t, FrozenManualRunEnemy> g_frozen_manual_run_enemies;

thread_local bool g_manual_run_enemy_spawner_tick_active = false;
thread_local uintptr_t g_current_wave_spawner_tick_address = 0;

constexpr std::uint64_t kSpellCastClickWindowMs = 400;
constexpr char kUnknownKillMethod[] = "unknown";
constexpr char kGoldSourcePickup[] = "pickup";
constexpr char kGoldSourceSpend[] = "spend";
constexpr char kGoldSourceScript[] = "script";
constexpr char kGoldSourceUnknown[] = "unknown";
constexpr char kDropKindGold[] = "gold";
constexpr std::size_t kWaveSpawnerRemainingBudgetOffset = 0x20;
constexpr std::size_t kWaveSpawnerSpawnDelayCountdownOffset = 0x24;
constexpr std::size_t kWaveSpawnerLongDelayCountdownOffset = 0x2C;
constexpr std::uint64_t kManualRunEnemySpawnerFreshnessWindowMs = 5000;
constexpr std::size_t kQueuedReplicatedRunEnemySpawnLimit = 16;
constexpr std::size_t kReplicatedCatchupSpawnBurstPerSpawnerTick = 8;
constexpr std::size_t kEnemySpawnConfigHpOffset = 0x58;
constexpr std::size_t kEnemySpawnConfigFamilyValuesOffset = 0x5C;
constexpr std::size_t kEnemySpawnConfigChaseSpeedOffset = 0x6C;
constexpr std::size_t kEnemySpawnConfigAttackSpeedOffset = 0x70;
constexpr std::size_t kEnemySpawnConfigScaleOffset = 0x74;
constexpr std::size_t kCanceledEnemySpawnResultSize = 0x400;
constexpr std::uint32_t kMaximumLuaEnemySpawnFilterHookLogCount = 4;
constexpr std::uint32_t kMaximumLuaDropRollFilterHookLogCount = 4;

alignas(std::uintptr_t)
std::array<std::uint8_t, kCanceledEnemySpawnResultSize>
    g_canceled_enemy_spawn_result{};
std::atomic<std::uint32_t> g_lua_enemy_spawn_filter_capture_log_count{0};
std::atomic<std::uint32_t> g_lua_enemy_spawn_filter_write_log_count{0};
std::atomic<std::uint32_t> g_lua_drop_roll_filter_capture_log_count{0};
std::atomic<std::uint32_t> g_lua_drop_roll_filter_write_log_count{0};

void BuildHookTargets(HookTarget* targets) {
    if (targets == nullptr) {
        return;
    }

    targets[kHookCreateArena] = {kArenaCreate, 6};      // "Create New ARENA" virtual method
    // MainMenu control action: PUSH -1 (2) + PUSH exception handler (5).
    targets[kHookMainMenuControlAction] = {kMainMenuControlAction, 7};
    targets[kHookStartGame] = {kStartGame, 7};          // "on START GAME" menu-initiated
    targets[kHookRunEnded] = {kRunEnded, 7};            // GameOver trigger (__cdecl)
    // Whole instructions: PUSH ESI, PUSH EDI, XOR EDI,EDI, MOV ESI,ECX.
    targets[kHookActorWorldTick] = {kActorWorldTick, 6};
    targets[kHookWaveSpawnerTick] = {kWaveSpawnerTick, 6};
    targets[kHookEnemySpawned] = {kSpawnEnemy, 7};
    targets[kHookEnemyDeath] = {kEnemyDeath, 10};
    // Whole instructions: PUSH -1 (2) + PUSH exception handler (5).
    targets[kHookDropSelector] = {kEnemyDropSelector, 7};
    targets[kHookSpellCast3EB] = {kSpellCast3EB, 8};
    targets[kHookSpellCast018] = {kSpellCast018, 8};
    // Whole instructions: sub esp,18h (3) + fld [esp+24h] (4).
    targets[kHookAirLightningChainTarget] = {kAirLightningChainTarget, 7};
    targets[kHookSpellCast020] = {kSpellCast020, 8};
    targets[kHookSpellCast028] = {kSpellCast028, 7};
    targets[kHookSpellCast3EC] = {kSpellCast3EC, 8};
    targets[kHookSpellCast3ED] = {kSpellCast3ED, 8};
    targets[kHookSpellCast3EE] = {kSpellCast3EE, 8};
    targets[kHookSpellCast3EF] = {kSpellCast3EF, 7};
    targets[kHookSpellCast3F0] = {kSpellCast3F0, 7};
    targets[kHookGoldChanged] = {kGoldChanged, 9};
    targets[kHookDropSpawned] = {kSpawnRewardGold, 7};
    targets[kHookLevelUp] = {kLevelUp, 6};
}

bool IsRunActive() {
    return g_state.run_active.load(std::memory_order_acquire);
}

bool IsCombatArenaActiveForEnemyTracking() {
    if (IsRunActive()) {
        return true;
    }
    if (g_state.wave_start_enemy_tracking.load(std::memory_order_acquire)) {
        return true;
    }

    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid) {
        return false;
    }

    return combat_state.combat_active != 0 ||
        combat_state.combat_started_music != 0 ||
        combat_state.combat_wave_index > 0;
}

bool TryReadResolvedGlobalInt(uintptr_t absolute_address, int* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0;
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved != 0 && ProcessMemory::Instance().TryReadValue(resolved, value);
}

bool TryReadSmartPointerInnerObjectForRunLifecycle(uintptr_t wrapper_address, uintptr_t* inner_object) {
    if (inner_object == nullptr) {
        return false;
    }

    *inner_object = 0;
    if (wrapper_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t direct_inner = 0;
    if (!memory.TryReadValue(wrapper_address, &direct_inner)) {
        return false;
    }
    if (direct_inner != 0 && memory.IsReadableRange(direct_inner, 1)) {
        *inner_object = direct_inner;
        return true;
    }

    uintptr_t gameplay_inner = 0;
    if (!memory.TryReadValue(wrapper_address + 0x0C, &gameplay_inner)) {
        return false;
    }
    if (gameplay_inner != 0 && memory.IsReadableRange(gameplay_inner, 1)) {
        *inner_object = gameplay_inner;
        return true;
    }

    return false;
}

uintptr_t ResolveActorProgressionRuntimeForRunLifecycle(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t direct_progression = 0;
    if (!memory.TryReadField(actor_address, kActorProgressionRuntimeStateOffset, &direct_progression)) {
        return 0;
    }
    if (direct_progression != 0 && memory.IsReadableRange(direct_progression, 1)) {
        return direct_progression;
    }

    uintptr_t progression_handle = 0;
    if (!memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle)) {
        return 0;
    }
    uintptr_t progression_runtime = 0;
    return TryReadSmartPointerInnerObjectForRunLifecycle(progression_handle, &progression_runtime)
        ? progression_runtime
        : 0;
}

uintptr_t ResolveLocalPlayerActorForRunLifecycle() {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid || scene_state.gameplay_scene_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t slot_actor = 0;
    if (!memory.TryReadField(scene_state.gameplay_scene_address, kGameplayPlayerActorOffset, &slot_actor)) {
        return 0;
    }
    if (slot_actor != 0 && memory.IsReadableRange(slot_actor, 1)) {
        return slot_actor;
    }

    return 0;
}

uintptr_t ResolveLocalPlayerProgressionForRunLifecycle() {
    return ResolveActorProgressionRuntimeForRunLifecycle(ResolveLocalPlayerActorForRunLifecycle());
}

bool IsLocalPlayerProgressionForRunLifecycle(uintptr_t progression_address) {
    if (progression_address == 0) {
        return false;
    }

    const auto local_progression = ResolveLocalPlayerProgressionForRunLifecycle();
    return local_progression != 0 && local_progression == progression_address;
}

bool TryReadPendingLevelKind(int* pending_level_kind) {
    return TryReadResolvedGlobalInt(kPendingLevelKindGlobal, pending_level_kind);
}

bool TryWritePendingLevelKind(int pending_level_kind) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(kPendingLevelKindGlobal);
    return resolved != 0 && ProcessMemory::Instance().TryWriteValue<int>(resolved, pending_level_kind);
}

void RestoreNonLocalPendingLevelKind(
    uintptr_t progression_address,
    int pending_before,
    int level_after,
    int xp_after) {
    int pending_after = 0;
    if (!TryReadPendingLevelKind(&pending_after)) {
        Log(
            "level.up pending-level-kind global unavailable after native level-up. progression=" +
            HexString(progression_address) +
            " level=" + std::to_string(level_after) +
            " xp=" + std::to_string(xp_after));
        return;
    }
    if (pending_after == pending_before) {
        return;
    }

    if (TryWritePendingLevelKind(pending_before)) {
        Log(
            "level.up restored non-local picker delta. progression=" + HexString(progression_address) +
            " level=" + std::to_string(level_after) +
            " xp=" + std::to_string(xp_after) +
            " pending_before=" + std::to_string(pending_before) +
            " pending_after=" + std::to_string(pending_after));
    } else {
        Log(
            "level.up failed to restore non-local picker delta. progression=" + HexString(progression_address) +
            " level=" + std::to_string(level_after) +
            " xp=" + std::to_string(xp_after) +
            " pending_before=" + std::to_string(pending_before) +
            " pending_after=" + std::to_string(pending_after));
    }
}
