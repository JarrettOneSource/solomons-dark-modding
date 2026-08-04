#include "lua_item_runtime.h"

#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "native_world_render.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <mutex>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

struct LuaItemRuntimeState {
    std::map<std::uint64_t, LuaConsumableDefinition> consumables;
    std::unordered_map<std::int32_t, std::uint64_t> content_by_subtype;
    std::unordered_map<std::uint64_t, std::int32_t> reserved_subtype_by_content;
    std::vector<LuaLootPoolEntry> loot_pool;
    std::uint64_t loot_rng_state = 0xA0761D6478BD642Full;
    std::int32_t next_native_subtype = kLuaFirstConsumablePotionSubtype;
    std::mutex mutex;
};

LuaItemRuntimeState& ItemRuntime() {
    static LuaItemRuntimeState runtime;
    return runtime;
}

void SetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

bool IsValidChance(double chance) {
    return std::isfinite(chance) && chance >= 0.0 && chance <= 1.0;
}

bool IsValidVfxColor(const std::array<float, 4>& color) {
    return std::all_of(
        color.begin(),
        color.end(),
        [](float component) {
            return std::isfinite(component) &&
                component >= 0.0f &&
                component <= 1.0f;
        });
}

#include "lua_item_runtime/consumable_vfx_helpers.inl"

double NextLootUnitRoll(std::uint64_t* state) {
    *state += 0x9E3779B97F4A7C15ull;
    auto mixed = *state;
    mixed = (mixed ^ (mixed >> 30)) * 0xBF58476D1CE4E5B9ull;
    mixed = (mixed ^ (mixed >> 27)) * 0x94D049BB133111EBull;
    mixed ^= mixed >> 31;
    return static_cast<double>(mixed >> 11) * 0x1.0p-53;
}

}  // namespace

bool RegisterLuaConsumableDefinition(
    LuaConsumableDefinition definition,
    LuaConsumableDefinition* registered,
    std::string* error_message) {
    if (registered != nullptr) {
        *registered = {};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (registered == nullptr || error_message == nullptr) {
        return false;
    }
    if (definition.content_id == 0 || definition.mod_id.empty() ||
        definition.key.empty() || definition.name.empty() ||
        definition.description.empty() || definition.icon_atlas.empty()) {
        SetError(
            error_message,
            "Consumable registration requires identity, text, and icon metadata.");
        return false;
    }
    if (definition.duration_ms > kLuaMaximumConsumableDurationMs) {
        SetError(
            error_message,
            "Consumable duration exceeds the 24-hour runtime bound.");
        return false;
    }
    if ((definition.consume_vfx_kind != LuaConsumableVfxKind::None &&
         definition.consume_vfx_kind !=
             LuaConsumableVfxKind::SpellGlow) ||
        !IsValidVfxColor(definition.consume_vfx_color)) {
        SetError(
            error_message,
            "Consumable VFX metadata is invalid.");
        return false;
    }

    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    if (runtime.consumables.find(definition.content_id) !=
        runtime.consumables.end()) {
        SetError(error_message, "Consumable content identity is already registered.");
        return false;
    }
    if (runtime.consumables.size() >= kLuaMaximumRegisteredConsumables) {
        SetError(error_message, "Global registered consumable limit exceeded.");
        return false;
    }

    const auto reservation =
        runtime.reserved_subtype_by_content.find(definition.content_id);
    if (reservation != runtime.reserved_subtype_by_content.end()) {
        definition.native_subtype = reservation->second;
    } else {
        if (runtime.reserved_subtype_by_content.size() >=
            kLuaMaximumRegisteredConsumables) {
            SetError(
                error_message,
                "Global consumable native subtype reservation limit exceeded.");
            return false;
        }
        definition.native_subtype = runtime.next_native_subtype++;
        runtime.reserved_subtype_by_content.emplace(
            definition.content_id,
            definition.native_subtype);
    }
    if (runtime.content_by_subtype.find(definition.native_subtype) !=
        runtime.content_by_subtype.end()) {
        SetError(error_message, "Consumable native subtype is already active.");
        return false;
    }

    runtime.content_by_subtype.emplace(
        definition.native_subtype,
        definition.content_id);
    runtime.consumables.emplace(definition.content_id, definition);
    *registered = std::move(definition);
    return true;
}

std::optional<LuaConsumableDefinition> FindLuaConsumableDefinition(
    std::uint64_t content_id) {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    const auto found = runtime.consumables.find(content_id);
    if (found == runtime.consumables.end()) {
        return std::nullopt;
    }
    return found->second;
}

std::optional<LuaConsumableDefinition>
FindLuaConsumableDefinitionByNativeSubtype(std::int32_t native_subtype) {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    const auto content = runtime.content_by_subtype.find(native_subtype);
    if (content == runtime.content_by_subtype.end()) {
        return std::nullopt;
    }
    const auto definition = runtime.consumables.find(content->second);
    if (definition == runtime.consumables.end()) {
        return std::nullopt;
    }
    return definition->second;
}

std::vector<LuaConsumableDefinition> ListLuaConsumableDefinitions() {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    std::vector<LuaConsumableDefinition> definitions;
    definitions.reserve(runtime.consumables.size());
    for (const auto& [content_id, definition] : runtime.consumables) {
        (void)content_id;
        definitions.push_back(definition);
    }
    return definitions;
}

bool RegisterLuaLootPoolEntry(
    LuaLootPoolEntry entry,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (error_message == nullptr) {
        return false;
    }
    if (entry.mod_id.empty() || entry.item_content_id == 0) {
        SetError(error_message, "Loot registration requires a mod and item identity.");
        return false;
    }
    if (!IsValidChance(entry.normal_chance) ||
        !IsValidChance(entry.boss_chance)) {
        SetError(error_message, "Loot chances must be finite values in 0 through 1.");
        return false;
    }

    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    if (runtime.consumables.find(entry.item_content_id) ==
        runtime.consumables.end()) {
        SetError(
            error_message,
            "Loot registration requires an active registered consumable.");
        return false;
    }
    const auto duplicate = std::find_if(
        runtime.loot_pool.begin(),
        runtime.loot_pool.end(),
        [&](const LuaLootPoolEntry& existing) {
            return existing.mod_id == entry.mod_id &&
                existing.item_content_id == entry.item_content_id;
        });
    if (duplicate != runtime.loot_pool.end()) {
        SetError(error_message, "Loot item is already registered by this mod.");
        return false;
    }
    runtime.loot_pool.push_back(std::move(entry));
    return true;
}

std::vector<LuaLootPoolEntry> SnapshotLuaLootPool() {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    return runtime.loot_pool;
}

std::vector<LuaLootPoolEntry> RollLuaLootPool(bool boss) {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    std::vector<LuaLootPoolEntry> drops;
    drops.reserve(runtime.loot_pool.size());
    for (const auto& entry : runtime.loot_pool) {
        if (LuaLootRollSucceeds(
                entry,
                boss,
                NextLootUnitRoll(&runtime.loot_rng_state))) {
            drops.push_back(entry);
        }
    }
    return drops;
}

bool LuaLootRollSucceeds(
    const LuaLootPoolEntry& entry,
    bool boss,
    double unit_roll) {
    if (!std::isfinite(unit_roll) || unit_roll < 0.0 || unit_roll >= 1.0) {
        return false;
    }
    const double chance = boss ? entry.boss_chance : entry.normal_chance;
    return IsValidChance(chance) && unit_roll < chance;
}

bool QueueLuaConsumableNativeVfx(
    LuaConsumableNativeVfxRequest request) {
    if (request.content_id == 0 ||
        request.participant_id == 0 ||
        request.use_id == 0) {
        return false;
    }
    const auto definition =
        FindLuaConsumableDefinition(request.content_id);
    if (!definition.has_value() ||
        definition->duration_ms != request.duration_ms) {
        return false;
    }
    if (definition->consume_vfx_kind == LuaConsumableVfxKind::None) {
        return true;
    }

    const bool carrier_queued = request.duration_ms == 0 ||
        QueueNativeWorldConsumableVfxPresentation(
            definition->mod_id,
            request.content_id,
            request.participant_id,
            request.use_id,
            request.duration_ms,
            definition->consume_vfx_color);
    if (!carrier_queued) {
        Log(
            "lua_items: consumable VFX native carrier could not be queued. "
            "content_id=" + std::to_string(request.content_id) +
            " participant_id=" +
            std::to_string(request.participant_id) +
            " use_id=" + std::to_string(request.use_id));
    }

    std::string flash_error;
    const bool flash_spawned = SpawnSpellGlowForParticipant(
        *definition,
        request.participant_id,
        request.use_id,
        &flash_error);
    if (!flash_spawned) {
        Log(
            "lua_items: consumable VFX activation flash skipped. content_id=" +
            std::to_string(request.content_id) +
            " participant_id=" +
            std::to_string(request.participant_id) +
            " use_id=" + std::to_string(request.use_id) +
            " error=" + flash_error);
    }
    return request.duration_ms == 0 ? flash_spawned : carrier_queued;
}

void ClearLuaItemRuntimeForMod(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    for (auto iterator = runtime.consumables.begin();
         iterator != runtime.consumables.end();) {
        if (iterator->second.mod_id != mod_id) {
            ++iterator;
            continue;
        }
        runtime.content_by_subtype.erase(iterator->second.native_subtype);
        iterator = runtime.consumables.erase(iterator);
    }
    runtime.loot_pool.erase(
        std::remove_if(
            runtime.loot_pool.begin(),
            runtime.loot_pool.end(),
            [&](const LuaLootPoolEntry& entry) {
                return entry.mod_id == mod_id;
            }),
        runtime.loot_pool.end());
    ClearNativeWorldConsumableVfxPresentationsForMod(mod_id);
}

void ResetLuaItemRuntime() {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    runtime.consumables.clear();
    runtime.content_by_subtype.clear();
    runtime.reserved_subtype_by_content.clear();
    runtime.loot_pool.clear();
    ClearNativeWorldConsumableVfxPresentations();
    runtime.loot_rng_state =
        static_cast<std::uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count()) ^
        0xA0761D6478BD642Full;
    runtime.next_native_subtype = kLuaFirstConsumablePotionSubtype;
}

}  // namespace sdmod
