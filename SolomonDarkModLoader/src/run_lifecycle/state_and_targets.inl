using RunStartedFn = void(__fastcall*)(void* self, void* unused_edx);
using RunEndedFn = void(__cdecl*)();
using WaveSpawnerTickFn = void(__fastcall*)(void* self, void* unused_edx);
using EnemySpawnedFn =
    void* (__fastcall*)(void* self, void* unused_edx, void* param_2, int enemy_config, void* param_4, int param_5, int param_6, char param_7);
using EnemyDeathFn = int(__fastcall*)(void* self, void* unused_edx);
using SpellCastFn = void(__fastcall*)(void* self, void* unused_edx);
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
    kHookStartGame,
    kHookRunEnded,
    kHookWaveSpawnerTick,
    kHookEnemySpawned,
    kHookEnemyDeath,
    kHookSpellCast3EB,
    kHookSpellCast018,
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
    std::atomic<std::uint64_t> last_consumed_spell_click_serial{0};
    std::atomic<std::uint64_t> run_start_tick_ms{0};
    std::atomic<bool> combat_prelude_only_suppression{false};
    std::atomic<bool> wave_start_enemy_tracking{false};
    std::mutex enemy_type_mutex;
    std::unordered_map<uintptr_t, int> enemy_types_by_address;
    bool initialized = false;
} g_state;
constexpr std::uint64_t kSpellCastClickWindowMs = 400;
constexpr char kUnknownKillMethod[] = "unknown";
constexpr char kGoldSourcePickup[] = "pickup";
constexpr char kGoldSourceSpend[] = "spend";
constexpr char kGoldSourceScript[] = "script";
constexpr char kGoldSourceUnknown[] = "unknown";
constexpr char kDropKindGold[] = "gold";

void BuildHookTargets(HookTarget* targets) {
    if (targets == nullptr) {
        return;
    }

    targets[kHookCreateArena] = {kArenaCreate, 6};      // "Create New ARENA" virtual method
    targets[kHookStartGame] = {kStartGame, 7};          // "on START GAME" menu-initiated
    targets[kHookRunEnded] = {kRunEnded, 7};            // GameOver trigger (__cdecl)
    targets[kHookWaveSpawnerTick] = {kWaveSpawnerTick, 6};
    targets[kHookEnemySpawned] = {kSpawnEnemy, 7};
    targets[kHookEnemyDeath] = {kEnemyDeath, 10};
    targets[kHookSpellCast3EB] = {kSpellCast3EB, 8};
    targets[kHookSpellCast018] = {kSpellCast018, 8};
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

int ReadResolvedGlobalIntOr(uintptr_t absolute_address, int fallback = 0) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return ProcessMemory::Instance().ReadValueOr<int>(resolved, fallback);
}
