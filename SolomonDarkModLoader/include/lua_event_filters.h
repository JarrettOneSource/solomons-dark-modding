#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sdmod {

inline constexpr std::size_t kLuaDamageFilterLaneCount = 9;

inline constexpr std::uint32_t kLuaDamageDealingFilterMask = 1u << 0;
inline constexpr std::uint32_t kLuaDamageTakenFilterMask = 1u << 1;
inline constexpr std::uint32_t kLuaEnemySpawningFilterMask = 1u << 2;
inline constexpr std::uint32_t kLuaDropRollingFilterMask = 1u << 3;
inline constexpr std::uint32_t kLuaWaveSpawningFilterMask = 1u << 4;

struct LuaDamageFilterContext {
    std::uintptr_t source_actor_address = 0;
    std::uintptr_t target_actor_address = 0;
    std::uint64_t source_participant_id = 0;
    std::uint64_t target_participant_id = 0;
    std::uint32_t flags = 0;
    std::array<float, kLuaDamageFilterLaneCount> lanes{};
};

bool HasLuaDamageFilterHandlers();
bool ApplyLuaDamageFilters(LuaDamageFilterContext* context);

inline constexpr std::size_t kLuaEnemySpawnFamilyValueCount = 4;

struct LuaEnemySpawnFilterContext {
    std::uintptr_t arena_address = 0;
    std::uintptr_t config_address = 0;
    std::uintptr_t wave_spawner_address = 0;
    std::int32_t native_type_id = -1;
    float hp = 0.0f;
    std::array<float, kLuaEnemySpawnFamilyValueCount> family_values{};
    float chase_speed = 0.0f;
    float attack_speed = 0.0f;
    float scale = 0.0f;
};

bool HasLuaEnemySpawnFilterHandlers();
bool ApplyLuaEnemySpawnFilters(LuaEnemySpawnFilterContext* context);

inline constexpr std::size_t kLuaDropSelectorCount = 6;

enum class LuaDropForcedKind : std::uint8_t {
    Stock = 0,
    Orb,
    Gold,
    Item,
    Powerup,
    Potion,
};

struct LuaDropRollFilterContext {
    std::uintptr_t enemy_address = 0;
    std::uintptr_t arena_address = 0;
    std::uintptr_t config_address = 0;
    std::int32_t native_type_id = -1;
    float x = 0.0f;
    float y = 0.0f;
    std::array<std::uint8_t, kLuaDropSelectorCount> selectors{};
    std::uint32_t arena_disable_mask = 0;
    LuaDropForcedKind forced_kind = LuaDropForcedKind::Stock;
};

bool HasLuaDropRollFilterHandlers();
bool ApplyLuaDropRollFilters(LuaDropRollFilterContext* context);

struct LuaWaveSpawnFilterContext {
    std::uintptr_t spawner_address = 0;
    std::uintptr_t action_record_address = 0;
    std::int32_t wave_index = 0;
    std::int32_t count = 0;
    std::int32_t spawn_delay_remaining = 0;
    std::int32_t spawn_delay = 0;
    std::int32_t wave_delay = 0;
    bool randomize_spawn_delay = false;
    bool sequential_groups = false;
};

bool HasLuaWaveSpawnFilterHandlers();
bool ApplyLuaWaveSpawnFilters(LuaWaveSpawnFilterContext* context);

}  // namespace sdmod
