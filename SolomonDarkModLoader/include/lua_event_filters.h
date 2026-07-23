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
inline constexpr std::uint32_t kLuaSpellCastingFilterMask = 1u << 5;
inline constexpr std::uint32_t kLuaXpGainingFilterMask = 1u << 6;
inline constexpr std::uint32_t kLuaGoldChangingFilterMask = 1u << 7;
inline constexpr std::uint32_t kLuaManaChangingFilterMask = 1u << 8;

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
    None,
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
    bool is_boss = false;
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

enum class LuaSpellCastKind : std::uint8_t {
    Primary = 0,
    Secondary,
};

struct LuaSpellCastFilterContext {
    std::uintptr_t caster_actor_address = 0;
    std::uint64_t caster_participant_id = 0;
    LuaSpellCastKind kind = LuaSpellCastKind::Primary;
    std::int32_t skill_id = 0;
    std::int32_t secondary_slot = -1;
    bool has_position = false;
    float position_x = 0.0f;
    float position_y = 0.0f;
    bool has_direction = false;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    std::uintptr_t target_actor_address = 0;
    bool has_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
};

bool HasLuaSpellCastFilterHandlers();
bool ApplyLuaSpellCastFilters(const LuaSpellCastFilterContext& context);

struct LuaXpGainFilterContext {
    std::uintptr_t progression_address = 0;
    std::uint64_t participant_id = 0;
    float current_xp = 0.0f;
    float amount = 0.0f;
    bool apply_native_scaling = false;
    const char* source = "unknown";
};

bool HasLuaXpGainFilterHandlers();
bool ApplyLuaXpGainFilters(LuaXpGainFilterContext* context);

struct LuaGoldChangeFilterContext {
    std::uint64_t participant_id = 0;
    std::int32_t current_gold = 0;
    std::int32_t delta = 0;
    bool allow_negative = false;
    const char* source = "unknown";
};

bool HasLuaGoldChangeFilterHandlers();
bool ApplyLuaGoldChangeFilters(LuaGoldChangeFilterContext* context);

struct LuaManaChangeFilterContext {
    std::uintptr_t actor_address = 0;
    std::uintptr_t progression_address = 0;
    std::uint64_t participant_id = 0;
    float current_mana = 0.0f;
    float maximum_mana = 0.0f;
    float delta = 0.0f;
    bool allow_prompt = false;
    const char* source = "native";
};

bool HasLuaManaChangeFilterHandlers();
bool ApplyLuaManaChangeFilters(LuaManaChangeFilterContext* context);

}  // namespace sdmod
