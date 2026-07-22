#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sdmod {

inline constexpr std::size_t kLuaDamageFilterLaneCount = 9;

inline constexpr std::uint32_t kLuaDamageDealingFilterMask = 1u << 0;
inline constexpr std::uint32_t kLuaDamageTakenFilterMask = 1u << 1;
inline constexpr std::uint32_t kLuaEnemySpawningFilterMask = 1u << 2;

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

}  // namespace sdmod
