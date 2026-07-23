#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

inline constexpr std::int32_t kLuaFirstConsumablePotionSubtype = 6;
inline constexpr std::size_t kLuaMaximumRegisteredConsumables = 256;
inline constexpr std::uint32_t kLuaMaximumConsumableDurationMs =
    24U * 60U * 60U * 1000U;

enum class LuaConsumableVfxKind : std::uint8_t {
    None = 0,
    SpellGlow = 1,
};

struct LuaConsumableDefinition {
    std::uint64_t content_id = 0;
    std::string mod_id;
    std::string key;
    std::string name;
    std::string description;
    std::string icon_atlas;
    std::uint32_t icon_frame = 0;
    std::uint32_t duration_ms = 0;
    std::int32_t native_subtype = -1;
    LuaConsumableVfxKind consume_vfx_kind = LuaConsumableVfxKind::None;
    std::array<float, 4> consume_vfx_color = {0.25f, 1.0f, 0.35f, 1.0f};
};

struct LuaLootPoolEntry {
    std::string mod_id;
    std::uint64_t item_content_id = 0;
    double normal_chance = 0.0;
    double boss_chance = 0.0;
};

struct LuaConsumableRenderQuad {
    std::uint64_t content_id = 0;
    std::string icon_atlas;
    std::uint32_t icon_frame = 0;
    std::array<float, 8> vertices{};
};

struct LuaConsumableNativeVfxRequest {
    std::uint64_t content_id = 0;
    std::uint64_t participant_id = 0;
    std::uint64_t use_id = 0;
};

bool RegisterLuaConsumableDefinition(
    LuaConsumableDefinition definition,
    LuaConsumableDefinition* registered,
    std::string* error_message);
std::optional<LuaConsumableDefinition> FindLuaConsumableDefinition(
    std::uint64_t content_id);
std::optional<LuaConsumableDefinition> FindLuaConsumableDefinitionByNativeSubtype(
    std::int32_t native_subtype);
std::vector<LuaConsumableDefinition> ListLuaConsumableDefinitions();

bool RegisterLuaLootPoolEntry(
    LuaLootPoolEntry entry,
    std::string* error_message);
std::vector<LuaLootPoolEntry> SnapshotLuaLootPool();
std::vector<LuaLootPoolEntry> RollLuaLootPool(bool boss);
bool LuaLootRollSucceeds(
    const LuaLootPoolEntry& entry,
    bool boss,
    double unit_roll);

bool QueueLuaConsumableRenderQuad(LuaConsumableRenderQuad quad);
std::vector<LuaConsumableRenderQuad> TakeLuaConsumableRenderQuads();
bool QueueLuaConsumableNativeVfx(LuaConsumableNativeVfxRequest request);
void PumpLuaConsumableNativeVfx();

bool InitializeLuaItemNativeHooks(std::string* error_message);
void ShutdownLuaItemNativeHooks();

void ClearLuaItemRuntimeForMod(std::string_view mod_id);
void ResetLuaItemRuntime();

}  // namespace sdmod
