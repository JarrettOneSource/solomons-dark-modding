#include "lua_item_runtime.h"

#include "gameplay_seams.h"
#include "lua_camera_runtime.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"

#include <Windows.h>

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
    struct ActiveNativeVfxPulse {
        LuaConsumableNativeVfxRequest request;
        std::uint64_t next_spawn_ms = 0;
        std::uint64_t expires_at_ms = 0;
    };

    std::map<std::uint64_t, LuaConsumableDefinition> consumables;
    std::unordered_map<std::int32_t, std::uint64_t> content_by_subtype;
    std::unordered_map<std::uint64_t, std::int32_t> reserved_subtype_by_content;
    std::vector<LuaLootPoolEntry> loot_pool;
    std::vector<LuaConsumableRenderQuad> render_quads;
    std::vector<LuaConsumableNativeVfxRequest> native_vfx_requests;
    std::vector<ActiveNativeVfxPulse> active_native_vfx_pulses;
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

int CaptureNativeVfxSehCode(
    EXCEPTION_POINTERS* exception_pointers,
    DWORD* exception_code) {
    if (exception_code != nullptr && exception_pointers != nullptr &&
        exception_pointers->ExceptionRecord != nullptr) {
        *exception_code =
            exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

using ObjectAllocateFn = void*(__cdecl*)(std::size_t);
using SpellGlowCtorFn = void*(__thiscall*)(void*);
using RegisterAnimationFn =
    void(__thiscall*)(void* world, void* animation, float layer);

constexpr float kSpellGlowAnimationLayer = 75.0f;
constexpr std::uint64_t kSpellGlowPulseIntervalMs = 16;
constexpr std::uint64_t kSpellGlowPulseDurationMs = 4000;
constexpr std::size_t kMaximumRenderQuads = 512;
constexpr std::size_t kActivationBurstParticleCount = 4;
constexpr float kActivationBurstOrbitRadius = 42.0f;
constexpr float kActivationBurstIconHalfSize = 16.0f;
constexpr float kPi = 3.14159265358979323846f;

struct ConsumableVfxTarget {
    uintptr_t actor_address = 0;
    uintptr_t world_address = 0;
    float x = 0.0f;
    float y = 0.0f;
};

bool TryResolveConsumableVfxTarget(
    std::uint64_t participant_id,
    ConsumableVfxTarget* target) {
    if (target == nullptr || participant_id == 0) {
        return false;
    }
    *target = ConsumableVfxTarget{};

    const auto transport_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    const auto local_participant_id = transport_participant_id != 0
        ? transport_participant_id
        : multiplayer::kLocalParticipantId;
    if (participant_id == local_participant_id) {
        SDModPlayerState player;
        if (!TryGetPlayerState(&player) ||
            !player.valid ||
            player.actor_address == 0 ||
            player.world_address == 0) {
            return false;
        }
        target->actor_address = player.actor_address;
        target->world_address = player.world_address;
        target->x = player.x;
        target->y = player.y;
        return true;
    }

    SDModParticipantGameplayState participant;
    if (!TryGetParticipantGameplayState(participant_id, &participant) ||
        !participant.available ||
        !participant.entity_materialized ||
        participant.actor_address == 0) {
        return false;
    }
    target->actor_address = participant.actor_address;
    target->world_address = participant.world_address;
    target->x = participant.x;
    target->y = participant.y;
    return true;
}

void AppendConsumableActivationBurstQuads(
    const LuaConsumableDefinition& definition,
    const LuaConsumableNativeVfxRequest& request,
    std::uint64_t now_ms,
    std::vector<LuaConsumableRenderQuad>* quads) {
    if (quads == nullptr) {
        return;
    }

    ConsumableVfxTarget target;
    LuaCameraSnapshot camera;
    if (!TryResolveConsumableVfxTarget(
            request.participant_id,
            &target) ||
        !TryGetLuaCameraSnapshot(definition.mod_id, &camera) ||
        !camera.scene_available ||
        !std::isfinite(camera.origin_x) ||
        !std::isfinite(camera.origin_y) ||
        !std::isfinite(camera.scale) ||
        camera.scale <= 0.0f) {
        return;
    }

    const float center_x =
        (target.x - camera.origin_x) * camera.scale;
    const float center_y =
        (target.y - camera.origin_y) * camera.scale -
        14.0f * camera.scale;
    const float phase =
        static_cast<float>(now_ms % 1600) / 1600.0f * 2.0f * kPi +
        static_cast<float>(request.use_id & 0xFFu) /
            255.0f * 2.0f * kPi;

    for (std::size_t index = 0;
         index < kActivationBurstParticleCount &&
             quads->size() < kMaximumRenderQuads;
         ++index) {
        const float angle = phase +
            static_cast<float>(index) *
                (2.0f * kPi /
                 static_cast<float>(kActivationBurstParticleCount));
        const float particle_x = center_x +
            std::cos(angle) * kActivationBurstOrbitRadius;
        const float particle_y = center_y +
            std::sin(angle) * kActivationBurstOrbitRadius * 0.65f;
        const float half_size = kActivationBurstIconHalfSize +
            std::sin(angle * 2.0f) * 2.0f;

        LuaConsumableRenderQuad quad;
        quad.content_id = definition.content_id;
        quad.icon_atlas = definition.icon_atlas;
        quad.icon_frame = definition.icon_frame;
        quad.vertices = {
            particle_x - half_size,
            particle_y - half_size,
            particle_x + half_size,
            particle_y - half_size,
            particle_x - half_size,
            particle_y + half_size,
            particle_x + half_size,
            particle_y + half_size,
        };
        quads->push_back(std::move(quad));
    }
}

bool ConstructSpellGlowSafe(
    uintptr_t allocate_address,
    uintptr_t constructor_address,
    void** allocation,
    void** glow,
    DWORD* exception_code) {
    if (allocation != nullptr) {
        *allocation = nullptr;
    }
    if (glow != nullptr) {
        *glow = nullptr;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (allocation == nullptr || glow == nullptr ||
        allocate_address == 0 || constructor_address == 0) {
        return false;
    }
    auto* allocate =
        reinterpret_cast<ObjectAllocateFn>(allocate_address);
    auto* constructor =
        reinterpret_cast<SpellGlowCtorFn>(constructor_address);
    __try {
        *allocation = allocate(0x38);
        if (*allocation != nullptr) {
            *glow = constructor(*allocation);
        }
        return *glow != nullptr;
    } __except (
        CaptureNativeVfxSehCode(
            GetExceptionInformation(),
            exception_code)) {
        return false;
    }
}

bool RegisterSpellGlowSafe(
    uintptr_t register_address,
    uintptr_t world_address,
    void* glow,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (register_address == 0 ||
        world_address == 0 ||
        glow == nullptr) {
        return false;
    }
    auto* register_animation =
        reinterpret_cast<RegisterAnimationFn>(register_address);
    __try {
        register_animation(
            reinterpret_cast<void*>(world_address),
            glow,
            kSpellGlowAnimationLayer);
        return true;
    } __except (
        CaptureNativeVfxSehCode(
            GetExceptionInformation(),
            exception_code)) {
        return false;
    }
}

bool SpawnSpellGlowForParticipant(
    const LuaConsumableDefinition& definition,
    std::uint64_t participant_id,
    std::uint64_t use_id,
    std::string* error_message) {
    ConsumableVfxTarget target;
    if (!TryResolveConsumableVfxTarget(participant_id, &target)) {
        SetError(
            error_message,
            "participant actor is not materialized");
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = target.world_address;
    if (world_address == 0 &&
        (kActorOwnerOffset == 0 ||
         !memory.TryReadField(
             target.actor_address,
             kActorOwnerOffset,
             &world_address))) {
        SetError(error_message, "participant world is unavailable");
        return false;
    }

    const auto allocate_address =
        memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto free_address =
        memory.ResolveGameAddressOrZero(kObjectFree);
    const auto constructor_address =
        memory.ResolveGameAddressOrZero(kSpellGlowCtor);
    const auto register_address =
        memory.ResolveGameAddressOrZero(kActorWorldRegisterAnimation);
    if (allocate_address == 0 || constructor_address == 0 ||
        register_address == 0 || world_address == 0) {
        SetError(error_message, "SpellGlow native seams are unavailable");
        return false;
    }

    using ObjectFreeFn = void(__cdecl*)(void*);
    auto* object_free = reinterpret_cast<ObjectFreeFn>(free_address);

    void* allocation = nullptr;
    void* glow = nullptr;
    DWORD exception_code = 0;
    if (!ConstructSpellGlowSafe(
            allocate_address,
            constructor_address,
            &allocation,
            &glow,
            &exception_code)) {
        if (allocation != nullptr && object_free != nullptr) {
            object_free(allocation);
        }
        SetError(
            error_message,
            "SpellGlow allocation or construction failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)));
        return false;
    }

    const uintptr_t glow_address = reinterpret_cast<uintptr_t>(glow);
    const float phase =
        0.8f +
        static_cast<float>((use_id ^ (use_id >> 32)) & 0xFFu) /
            255.0f * 0.4f;
    const std::uint32_t selector = 0x18;
    if (!memory.TryWriteField(
            glow_address,
            0x14,
            target.x) ||
        !memory.TryWriteField(
            glow_address,
            0x18,
            target.y) ||
        !memory.TryWriteField(glow_address, 0x1C, phase) ||
        !memory.TryWriteField(glow_address, 0x20, phase) ||
        !memory.TryWriteField(glow_address, 0x24, selector) ||
        !memory.TryWriteField(
            glow_address,
            0x28,
            definition.consume_vfx_color[0]) ||
        !memory.TryWriteField(
            glow_address,
            0x2C,
            definition.consume_vfx_color[1]) ||
        !memory.TryWriteField(
            glow_address,
            0x30,
            definition.consume_vfx_color[2]) ||
        !memory.TryWriteField(
            glow_address,
            0x34,
            definition.consume_vfx_color[3])) {
        if (object_free != nullptr) {
            object_free(glow);
        }
        SetError(error_message, "SpellGlow state write failed");
        return false;
    }

    exception_code = 0;
    if (!RegisterSpellGlowSafe(
            register_address,
            world_address,
            glow,
            &exception_code)) {
        if (object_free != nullptr) {
            object_free(glow);
        }
        SetError(
            error_message,
            "SpellGlow registration failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)));
        return false;
    }
    return true;
}

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

bool QueueLuaConsumableRenderQuad(LuaConsumableRenderQuad quad) {
    if (quad.content_id == 0 || quad.icon_atlas.empty()) {
        return false;
    }
    for (const auto coordinate : quad.vertices) {
        if (!std::isfinite(coordinate)) {
            return false;
        }
    }

    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    if (runtime.render_quads.size() >= kMaximumRenderQuads) {
        return false;
    }
    runtime.render_quads.push_back(std::move(quad));
    return true;
}

std::vector<LuaConsumableRenderQuad> TakeLuaConsumableRenderQuads() {
    using ActivePresentation = std::pair<
        LuaConsumableDefinition,
        LuaConsumableNativeVfxRequest>;

    auto& runtime = ItemRuntime();
    std::vector<LuaConsumableRenderQuad> quads;
    std::vector<ActivePresentation> presentations;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    {
        std::scoped_lock lock(runtime.mutex);
        quads.swap(runtime.render_quads);
        presentations.reserve(runtime.active_native_vfx_pulses.size());
        for (const auto& pulse : runtime.active_native_vfx_pulses) {
            if (now_ms > pulse.expires_at_ms) {
                continue;
            }
            const auto definition =
                runtime.consumables.find(pulse.request.content_id);
            if (definition == runtime.consumables.end() ||
                definition->second.consume_vfx_kind ==
                    LuaConsumableVfxKind::None) {
                continue;
            }
            presentations.emplace_back(
                definition->second,
                pulse.request);
        }
    }
    for (const auto& [definition, request] : presentations) {
        AppendConsumableActivationBurstQuads(
            definition,
            request,
            now_ms,
            &quads);
    }
    return quads;
}

bool QueueLuaConsumableNativeVfx(
    LuaConsumableNativeVfxRequest request) {
    if (request.content_id == 0 ||
        request.participant_id == 0 ||
        request.use_id == 0) {
        return false;
    }
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    if (runtime.native_vfx_requests.size() +
            runtime.active_native_vfx_pulses.size() >=
        256) {
        return false;
    }
    runtime.native_vfx_requests.push_back(request);
    return true;
}

void PumpLuaConsumableNativeVfx() {
    std::vector<LuaConsumableNativeVfxRequest> requests_to_spawn;
    {
        auto& runtime = ItemRuntime();
        std::scoped_lock lock(runtime.mutex);
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        for (const auto& request : runtime.native_vfx_requests) {
            runtime.active_native_vfx_pulses.push_back({
                request,
                now_ms,
                now_ms + kSpellGlowPulseDurationMs,
            });
        }
        runtime.native_vfx_requests.clear();

        for (auto iterator = runtime.active_native_vfx_pulses.begin();
             iterator != runtime.active_native_vfx_pulses.end();) {
            if (now_ms > iterator->expires_at_ms) {
                iterator = runtime.active_native_vfx_pulses.erase(iterator);
                continue;
            }
            if (now_ms >= iterator->next_spawn_ms) {
                requests_to_spawn.push_back(iterator->request);
                iterator->next_spawn_ms =
                    now_ms + kSpellGlowPulseIntervalMs;
            }
            ++iterator;
        }
    }
    for (const auto& request : requests_to_spawn) {
        const auto definition =
            FindLuaConsumableDefinition(request.content_id);
        if (!definition.has_value() ||
            definition->consume_vfx_kind ==
                LuaConsumableVfxKind::None) {
            continue;
        }
        std::string error_message;
        if (!SpawnSpellGlowForParticipant(
                *definition,
                request.participant_id,
                request.use_id,
                &error_message)) {
            Log(
                "lua_items: consumable VFX skipped. content_id=" +
                std::to_string(request.content_id) +
                " participant_id=" +
                std::to_string(request.participant_id) +
                " use_id=" + std::to_string(request.use_id) +
                " error=" + error_message);
        }
    }
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
    runtime.render_quads.erase(
        std::remove_if(
            runtime.render_quads.begin(),
            runtime.render_quads.end(),
            [&](const LuaConsumableRenderQuad& quad) {
                return runtime.consumables.find(quad.content_id) ==
                    runtime.consumables.end();
            }),
        runtime.render_quads.end());
    runtime.native_vfx_requests.erase(
        std::remove_if(
            runtime.native_vfx_requests.begin(),
            runtime.native_vfx_requests.end(),
            [&](const LuaConsumableNativeVfxRequest& request) {
                return runtime.consumables.find(request.content_id) ==
                    runtime.consumables.end();
            }),
        runtime.native_vfx_requests.end());
    runtime.active_native_vfx_pulses.erase(
        std::remove_if(
            runtime.active_native_vfx_pulses.begin(),
            runtime.active_native_vfx_pulses.end(),
            [&](const LuaItemRuntimeState::ActiveNativeVfxPulse& pulse) {
                return runtime.consumables.find(pulse.request.content_id) ==
                    runtime.consumables.end();
            }),
        runtime.active_native_vfx_pulses.end());
}

void ResetLuaItemRuntime() {
    auto& runtime = ItemRuntime();
    std::scoped_lock lock(runtime.mutex);
    runtime.consumables.clear();
    runtime.content_by_subtype.clear();
    runtime.reserved_subtype_by_content.clear();
    runtime.loot_pool.clear();
    runtime.render_quads.clear();
    runtime.native_vfx_requests.clear();
    runtime.active_native_vfx_pulses.clear();
    runtime.loot_rng_state =
        static_cast<std::uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count()) ^
        0xA0761D6478BD642Full;
    runtime.next_native_subtype = kLuaFirstConsumablePotionSubtype;
}

}  // namespace sdmod
