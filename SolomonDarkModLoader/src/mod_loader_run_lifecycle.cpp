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
#include <unordered_map>

namespace sdmod {
namespace {

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

int ReadResolvedGlobalIntOr(uintptr_t absolute_address, int fallback = 0) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return ProcessMemory::Instance().ReadValueOr<int>(resolved, fallback);
}

float BitsToFloat(std::uint32_t bits) {
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

bool IsReturnAddressNear(uintptr_t return_address, uintptr_t function_address, uintptr_t max_span) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(function_address);
    return resolved != 0 && return_address >= resolved && return_address < resolved + max_span;
}

const char* ClassifyGoldChangeSource(uintptr_t return_address, int delta) {
    if (IsReturnAddressNear(return_address, kGoldScriptCaller, 0x1800)) {
        return kGoldSourceScript;
    }
    if (IsReturnAddressNear(return_address, kGoldPickupCaller, 0x900)) {
        return kGoldSourcePickup;
    }
    if (IsReturnAddressNear(return_address, kGoldMirrorCaller, 0x500) ||
        IsReturnAddressNear(return_address, kGoldSpendCaller, 0x500) ||
        IsReturnAddressNear(return_address, kGoldShopCaller, 0x700)) {
        return kGoldSourceSpend;
    }
    if (delta > 0) {
        return kGoldSourcePickup;
    }
    if (delta < 0) {
        return kGoldSourceSpend;
    }
    return kGoldSourceUnknown;
}

float ReadFloatFieldOrZero(uintptr_t address, size_t offset) {
    return ProcessMemory::Instance().ReadFieldOr<float>(address, offset, 0.0f);
}

std::string DescribeSpellCastHookActorState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return "actor=0x0";
    }

    auto& memory = ProcessMemory::Instance();
    SDModPlayerState player_state{};
    const bool have_player_state = TryGetPlayerState(&player_state) && player_state.valid;
    const bool is_local_actor = have_player_state && player_state.actor_address == actor_address;

    return
        "actor=" + HexString(actor_address) +
        " local=" + std::to_string(is_local_actor ? 1 : 0) +
        " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " slot=" + std::to_string(memory.ReadFieldOr<int>(actor_address, kActorSlotOffset, -1)) +
        " world_slot=" + std::to_string(memory.ReadFieldOr<int>(actor_address, kActorWorldSlotOffset, -1)) +
        " skill=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0)) +
        " prev=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset + sizeof(std::int32_t), 0)) +
        " drive=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0)) +
        " no_int=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0)) +
        " group=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " cast_slot=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " heading=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)) +
        " aimx=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f)) +
        " aimy=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f)) +
        " aux0=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0)) +
        " aux1=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0)) +
        " f278=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x278, 0)) +
        " f29c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x29C, 0.0f)) +
        " f2a0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A0, 0.0f)) +
        " f2d0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D0, 0.0f)) +
        " f2d4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D4, 0.0f)) +
        " f2d8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D8, 0.0f)) +
        " selection_ptr=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)) +
        " progression_runtime=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
        " progression_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
}

int ReadRoundedXpOrUnknown(uintptr_t address) {
    if (address == 0) {
        return -1;
    }

    const auto xp = ProcessMemory::Instance().ReadFieldOr<float>(address, kProgressionXpOffset, -1.0f);
    if (xp < 0.0f) {
        return -1;
    }

    return static_cast<int>(std::lround(xp));
}

int ReadEnemyType(uintptr_t enemy_address, uintptr_t fallback_config_address = 0) {
    auto& memory = ProcessMemory::Instance();
    const auto config_address = memory.ReadFieldOr<uintptr_t>(enemy_address, kEnemyConfigOffset, fallback_config_address);
    return memory.ReadFieldOr<int>(config_address, kEnemyTypeOffset, -1);
}

void RememberEnemyType(uintptr_t enemy_address, int enemy_type) {
    if (enemy_address == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address[enemy_address] = enemy_type;
}

int LookupRememberedEnemyType(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return -1;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    const auto it = g_state.enemy_types_by_address.find(enemy_address);
    return it != g_state.enemy_types_by_address.end() ? it->second : -1;
}

void ForgetEnemyType(uintptr_t enemy_address) {
    if (enemy_address == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address.erase(enemy_address);
}

void ClearRememberedEnemyTypes() {
    std::lock_guard<std::mutex> lock(g_state.enemy_type_mutex);
    g_state.enemy_types_by_address.clear();
}

void DispatchSpellCastForSelf(uintptr_t self_address, int spell_id) {
    if (self_address == 0 || !IsRunActive()) {
        return;
    }

    const auto click_serial = GetGameplayMouseLeftEdgeSerial();
    const auto click_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    if (click_serial == 0 ||
        click_tick_ms == 0 ||
        now < click_tick_ms ||
        now - click_tick_ms > kSpellCastClickWindowMs) {
        return;
    }

    const auto last_consumed_click_serial =
        g_state.last_consumed_spell_click_serial.load(std::memory_order_acquire);
    if (last_consumed_click_serial == click_serial) {
        return;
    }
    g_state.last_consumed_spell_click_serial.store(click_serial, std::memory_order_release);

    const auto x = ReadFloatFieldOrZero(self_address, kActorPositionXOffset);
    const auto y = ReadFloatFieldOrZero(self_address, kActorPositionYOffset);
    const auto direction_x = ReadFloatFieldOrZero(self_address, kSpellDirectionXOffset);
    const auto direction_y = ReadFloatFieldOrZero(self_address, kSpellDirectionYOffset);

    Log(
        "spell.cast hook invoked. spell_id=" + std::to_string(spell_id) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0));
    DispatchLuaSpellCast(spell_id, x, y, direction_x, direction_y);
}

#define SDMOD_DEFINE_SPELL_CAST_HOOK(name, hook_index, spell_id_value)               \
    void __fastcall HookSpellCast_##name(void* self, void* unused_edx) {             \
        const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[hook_index]); \
        if (original == nullptr) {                                                   \
            return;                                                                  \
        }                                                                            \
        const auto self_address = reinterpret_cast<uintptr_t>(self);                 \
        original(self, unused_edx);                                                  \
        DispatchSpellCastForSelf(self_address, spell_id_value);                      \
    }

SDMOD_DEFINE_SPELL_CAST_HOOK(3EB, kHookSpellCast3EB, 0x3EB)
SDMOD_DEFINE_SPELL_CAST_HOOK(018, kHookSpellCast018, 0x18)
SDMOD_DEFINE_SPELL_CAST_HOOK(020, kHookSpellCast020, 0x20)
SDMOD_DEFINE_SPELL_CAST_HOOK(028, kHookSpellCast028, 0x28)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EC, kHookSpellCast3EC, 0x3EC)
SDMOD_DEFINE_SPELL_CAST_HOOK(3ED, kHookSpellCast3ED, 0x3ED)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EE, kHookSpellCast3EE, 0x3EE)
SDMOD_DEFINE_SPELL_CAST_HOOK(3F0, kHookSpellCast3F0, 0x3F0)

void __fastcall HookSpellCast_3EF(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[kHookSpellCast3EF]);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    Log("[bots] spell_3ef hook enter. " + DescribeSpellCastHookActorState(self_address));
    original(self, unused_edx);
    Log("[bots] spell_3ef hook exit. " + DescribeSpellCastHookActorState(self_address));
    DispatchSpellCastForSelf(self_address, 0x3EF);
}

#undef SDMOD_DEFINE_SPELL_CAST_HOOK

// ---- Detour functions ----

void __fastcall HookCreateArena(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<RunStartedFn>(g_state.hooks[kHookCreateArena]);
    if (original == nullptr) return;
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    ClearRememberedEnemyTypes();
    original(self, unused_edx);
    DispatchLuaRunStarted();
}

void __fastcall HookStartGame(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<RunStartedFn>(g_state.hooks[kHookStartGame]);
    if (original == nullptr) return;
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(true, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(static_cast<std::uint64_t>(GetTickCount64()), std::memory_order_release);
    ClearRememberedEnemyTypes();
    original(self, unused_edx);
    DispatchLuaRunStarted();
}

void __cdecl HookRunEnded() {
    const auto original = GetX86HookTrampoline<RunEndedFn>(g_state.hooks[kHookRunEnded]);
    if (original == nullptr) return;
    g_state.run_active.store(false, std::memory_order_release);
    original();
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(0, std::memory_order_release);
    ClearRememberedEnemyTypes();
    multiplayer::SetAllBotSceneIntentsToSharedHub();
    DispatchLuaRunEnded("death");
}

void __fastcall HookWaveSpawnerTick(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<WaveSpawnerTickFn>(g_state.hooks[kHookWaveSpawnerTick]);
    if (original == nullptr) return;

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    const auto previous_self = g_state.last_wave_spawner.exchange(self_address, std::memory_order_acq_rel);
    if (self_address != 0 && previous_self != self_address) {
        uintptr_t self_vtable = 0;
        if (ProcessMemory::Instance().TryReadValue(self_address, &self_vtable)) {
            Log(
                "WaveSpawner_Tick invoked. self=" + HexString(self_address) +
                " vtable=" + HexString(self_vtable));
        } else {
            Log("WaveSpawner_Tick invoked. self=" + HexString(self_address) + " vtable=unreadable");
        }
    }

    original(self, unused_edx);

    // Only dispatch wave events while a run is active.
    // The game calls WaveSpawner_Tick once more after Game_OnGameOver,
    // so we must check run_active to avoid a spurious wave.started.
    if (!g_state.run_active.load(std::memory_order_acquire)) return;

    const auto wave_before = g_state.current_wave.load(std::memory_order_acquire);
    if (wave_before == 0) {
        g_state.current_wave.store(1, std::memory_order_release);
        DispatchLuaWaveStarted(1);
    }
}

void* __fastcall HookEnemySpawned(
    void* self,
    void* unused_edx,
    void* param_2,
    int enemy_config,
    void* param_4,
    int param_5,
    int param_6,
    char param_7) {
    const auto original = GetX86HookTrampoline<EnemySpawnedFn>(g_state.hooks[kHookEnemySpawned]);
    if (original == nullptr) {
        return nullptr;
    }

    auto* enemy = original(self, unused_edx, param_2, enemy_config, param_4, param_5, param_6, param_7);
    if (enemy == nullptr || !IsRunActive()) {
        return enemy;
    }

    const auto enemy_address = reinterpret_cast<uintptr_t>(enemy);
    const auto enemy_type = ReadEnemyType(enemy_address, static_cast<uintptr_t>(enemy_config));
    const auto x = ReadFloatFieldOrZero(enemy_address, kActorPositionXOffset);
    const auto y = ReadFloatFieldOrZero(enemy_address, kActorPositionYOffset);
    RememberEnemyType(enemy_address, enemy_type);
    DispatchLuaEnemySpawned(enemy_type, x, y);
    return enemy;
}

int __fastcall HookEnemyDeath(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<EnemyDeathFn>(g_state.hooks[kHookEnemyDeath]);
    if (original == nullptr) {
        return 0;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    const bool already_handled = memory.ReadFieldOr<std::uint8_t>(self_address, kEnemyDeathHandledOffset, 0) != 0;
    auto enemy_type = LookupRememberedEnemyType(self_address);
    if (enemy_type < 0) {
        enemy_type = ReadEnemyType(self_address);
    }
    const auto x = ReadFloatFieldOrZero(self_address, kActorPositionXOffset);
    const auto y = ReadFloatFieldOrZero(self_address, kActorPositionYOffset);

    const auto result = original(self, unused_edx);
    Log(
        "enemy.death hook invoked. enemy_type=" + std::to_string(enemy_type) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " already_handled=" + std::to_string(already_handled ? 1 : 0) +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0) +
        " result=" + std::to_string(result));
    ForgetEnemyType(self_address);
    if (!already_handled && IsRunActive()) {
        DispatchLuaEnemyDeath(enemy_type, x, y, kUnknownKillMethod);
    }

    return result;
}

int __stdcall HookGoldChanged(int delta, char allow_negative) {
    const auto original = GetX86HookTrampoline<GoldChangedFn>(g_state.hooks[kHookGoldChanged]);
    if (original == nullptr) {
        return 0;
    }

    const auto return_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto* source = ClassifyGoldChangeSource(return_address, delta);
    const auto result = original(delta, allow_negative);
    if (result != 0) {
        DispatchLuaGoldChanged(ReadResolvedGlobalIntOr(kGoldGlobal), delta, source);
    }
    return result;
}

void __fastcall HookDropSpawned(
    void* self,
    void* unused_edx,
    std::uint32_t x_bits,
    std::uint32_t y_bits,
    int amount,
    int lifetime) {
    const auto original = GetX86HookTrampoline<DropSpawnedFn>(g_state.hooks[kHookDropSpawned]);
    if (original == nullptr) {
        return;
    }

    original(self, unused_edx, x_bits, y_bits, amount, lifetime);
    if (!IsRunActive()) {
        return;
    }

    DispatchLuaDropSpawned(kDropKindGold, BitsToFloat(x_bits), BitsToFloat(y_bits));
}

void __fastcall HookLevelUp(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<LevelUpFn>(g_state.hooks[kHookLevelUp]);
    if (original == nullptr) {
        return;
    }

    const auto progression_address = reinterpret_cast<uintptr_t>(self);
    const auto level_before =
        ProcessMemory::Instance().ReadFieldOr<int>(progression_address, kProgressionLevelOffset, 0);
    original(self, unused_edx);
    if (!IsRunActive()) {
        return;
    }

    const auto level_after =
        ProcessMemory::Instance().ReadFieldOr<int>(progression_address, kProgressionLevelOffset, level_before);
    if (level_after <= level_before) {
        return;
    }

    DispatchLuaLevelUp(level_after, ReadRoundedXpOrUnknown(progression_address));
}

}  // namespace

bool IsRunLifecycleActive() {
    return g_state.run_active.load(std::memory_order_acquire);
}

int GetRunLifecycleCurrentWave() {
    return g_state.current_wave.load(std::memory_order_acquire);
}

std::uint64_t GetRunLifecycleElapsedMilliseconds() {
    const auto started_at = g_state.run_start_tick_ms.load(std::memory_order_acquire);
    if (started_at == 0) {
        return 0;
    }

    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    return now >= started_at ? now - started_at : 0;
}

bool InitializeRunLifecycleHooks(std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    if (g_state.initialized) return true;

    if (!InitializeGameplaySeams(error_message)) {
        return false;
    }

    HookTarget targets[kHookCount] = {};
    BuildHookTargets(targets);

    uintptr_t resolved[kHookCount] = {};
    for (size_t i = 0; i < kHookCount; ++i) {
        resolved[i] = ProcessMemory::Instance().ResolveGameAddressOrZero(targets[i].address);
        if (resolved[i] == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve lifecycle hook target at " + HexString(targets[i].address);
            }
            return false;
        }
    }

    void* detours[] = {
        reinterpret_cast<void*>(&HookCreateArena),
        reinterpret_cast<void*>(&HookStartGame),
        reinterpret_cast<void*>(&HookRunEnded),
        reinterpret_cast<void*>(&HookWaveSpawnerTick),
        reinterpret_cast<void*>(&HookEnemySpawned),
        reinterpret_cast<void*>(&HookEnemyDeath),
        reinterpret_cast<void*>(&HookSpellCast_3EB),
        reinterpret_cast<void*>(&HookSpellCast_018),
        reinterpret_cast<void*>(&HookSpellCast_020),
        reinterpret_cast<void*>(&HookSpellCast_028),
        reinterpret_cast<void*>(&HookSpellCast_3EC),
        reinterpret_cast<void*>(&HookSpellCast_3ED),
        reinterpret_cast<void*>(&HookSpellCast_3EE),
        reinterpret_cast<void*>(&HookSpellCast_3EF),
        reinterpret_cast<void*>(&HookSpellCast_3F0),
        reinterpret_cast<void*>(&HookGoldChanged),
        reinterpret_cast<void*>(&HookDropSpawned),
        reinterpret_cast<void*>(&HookLevelUp),
    };
    const char* names[] = {
        "create_arena",
        "start_game",
        "run.ended",
        "wave.spawner_tick",
        "enemy.spawned",
        "enemy.death",
        "spell.cast.0x3eb",
        "spell.cast.0x18",
        "spell.cast.0x20",
        "spell.cast.0x28",
        "spell.cast.0x3ec",
        "spell.cast.0x3ed",
        "spell.cast.0x3ee",
        "spell.cast.0x3ef",
        "spell.cast.0x3f0",
        "gold.changed",
        "drop.spawned",
        "level.up",
    };

    HookSpec specs[kHookCount] = {};
    for (size_t i = 0; i < kHookCount; ++i) {
        specs[i] = {reinterpret_cast<void*>(resolved[i]), targets[i].patch_size, detours[i], names[i]};
    }

    if (!InstallHookSet(specs, kHookCount, g_state.hooks, error_message)) {
        return false;
    }

    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(false, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(0, std::memory_order_release);
    ClearRememberedEnemyTypes();
    g_state.initialized = true;

    std::string log_line = "Run lifecycle hooks installed.";
    for (size_t i = 0; i < kHookCount; ++i) {
        log_line += " " + std::string(names[i]) + "=" + HexString(resolved[i]);
    }
    Log(log_line);
    return true;
}

void ShutdownRunLifecycleHooks() {
    RemoveHookSet(g_state.hooks, kHookCount);
    g_state.current_wave.store(0, std::memory_order_release);
    g_state.run_active.store(false, std::memory_order_release);
    g_state.last_wave_spawner.store(0, std::memory_order_release);
    g_state.last_consumed_spell_click_serial.store(0, std::memory_order_release);
    g_state.run_start_tick_ms.store(0, std::memory_order_release);
    ClearRememberedEnemyTypes();
    g_state.initialized = false;
}

}  // namespace sdmod
