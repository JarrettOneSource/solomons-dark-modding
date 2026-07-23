#include "lua_engine_internal.h"

#include "lua_engine.h"
#include "lua_engine_values.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr std::size_t kMaximumEffectsPerCast = 16;
constexpr std::size_t kMaximumEffectsPerMod = 128;
constexpr std::size_t kMaximumEffectKeyBytes = 64;
constexpr std::size_t kMaximumReplicatedEffectDataBytes = 128;
constexpr std::size_t kMaximumRememberedHitActors = 512;
constexpr float kMaximumCoordinateMagnitude = 10'000'000.0f;
constexpr float kMaximumEffectScalar = 1'000'000.0f;
constexpr std::uint32_t kDefaultEffectLifetimeMs = 1'000;
constexpr std::uint32_t kDefaultTickIntervalMs = 16;
constexpr std::uint32_t kMaximumEffectLifetimeMs = 600'000;

const LuaModValue* FindField(
    const LuaModValue& object,
    std::string_view field_name) {
    const auto found = object.object_value.find(field_name);
    return found == object.object_value.end() ? nullptr : &found->second;
}

bool IsNumeric(const LuaModValue& value) {
    return value.type == LuaModValueType::Integer ||
        value.type == LuaModValueType::Number;
}

double AsNumber(const LuaModValue& value) {
    return value.type == LuaModValueType::Integer
        ? static_cast<double>(value.integer_value)
        : value.number_value;
}

bool ReadBoundedFloat(
    const LuaModValue& object,
    std::string_view field_name,
    float default_value,
    float minimum,
    float maximum,
    float* value,
    std::string* error_message) {
    const auto* field = FindField(object, field_name);
    if (field == nullptr) {
        *value = default_value;
        return true;
    }
    if (!IsNumeric(*field)) {
        *error_message = std::string(field_name) + " must be numeric";
        return false;
    }
    const auto parsed = AsNumber(*field);
    if (!std::isfinite(parsed) || parsed < minimum || parsed > maximum) {
        *error_message = std::string(field_name) + " is outside its supported range";
        return false;
    }
    *value = static_cast<float>(parsed);
    return true;
}

std::uint32_t ReadConfigInteger(
    const LuaSpellDefinition& definition,
    std::string_view field_name,
    std::uint32_t default_value) {
    if (definition.config.type != LuaModValueType::Object) {
        return default_value;
    }
    const auto* value = FindField(definition.config, field_name);
    if (value == nullptr || value->type != LuaModValueType::Integer ||
        value->integer_value <= 0 ||
        value->integer_value >
            (std::numeric_limits<std::uint32_t>::max)()) {
        return default_value;
    }
    return static_cast<std::uint32_t>(value->integer_value);
}

float ReadConfigNumber(
    const LuaSpellDefinition& definition,
    std::string_view field_name,
    float default_value) {
    if (definition.config.type != LuaModValueType::Object) {
        return default_value;
    }
    const auto* value = FindField(definition.config, field_name);
    if (value == nullptr || !IsNumeric(*value)) {
        return default_value;
    }
    const auto parsed = AsNumber(*value);
    return std::isfinite(parsed)
        ? static_cast<float>(parsed)
        : default_value;
}

bool IsKnownDescriptorField(std::string_view field_name) {
    return field_name == "key" || field_name == "x" ||
        field_name == "y" || field_name == "velocity_x" ||
        field_name == "velocity_y" || field_name == "radius" ||
        field_name == "lifetime_ms" || field_name == "data";
}

bool IsKnownPatchField(std::string_view field_name) {
    return field_name == "x" || field_name == "y" ||
        field_name == "velocity_x" || field_name == "velocity_y" ||
        field_name == "radius" || field_name == "data" ||
        field_name == "done";
}

bool ValidateReplicatedData(
    const LuaModValue& data,
    std::string* error_message) {
    std::vector<std::uint8_t> encoded;
    if (!EncodeLuaModValue(data, &encoded, error_message)) {
        return false;
    }
    if (encoded.size() > kMaximumReplicatedEffectDataBytes) {
        *error_message = "effect data exceeds the 128-byte replication limit";
        return false;
    }
    return true;
}

bool ParseEffectDescriptor(
    const LuaModValue& descriptor,
    const LuaSpellDefinition& definition,
    const LuaRegisteredSpellCastRequest& request,
    LuaSpellEffectInstance* effect,
    std::string* error_message) {
    if (descriptor.type != LuaModValueType::Object) {
        *error_message = "each effect must be an object";
        return false;
    }
    for (const auto& [field_name, unused] : descriptor.object_value) {
        (void)unused;
        if (!IsKnownDescriptorField(field_name)) {
            *error_message = "effect contains unknown field '" + field_name + "'";
            return false;
        }
    }

    const auto* key = FindField(descriptor, "key");
    if (key == nullptr || key->type != LuaModValueType::String ||
        key->string_value.empty() ||
        key->string_value.size() > kMaximumEffectKeyBytes ||
        key->string_value.find('\0') != std::string::npos) {
        *error_message = "effect key must contain 1..64 text bytes";
        return false;
    }

    LuaSpellEffectInstance parsed;
    parsed.cast_request_id = request.request_id;
    parsed.content_id = request.content_id;
    parsed.owner_participant_id = request.owner_participant_id;
    parsed.key = key->string_value;
    if (!ReadBoundedFloat(
            descriptor,
            "x",
            request.aim_x,
            -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude,
            &parsed.x,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "y",
            request.aim_y,
            -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude,
            &parsed.y,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "velocity_x",
            0.0f,
            -kMaximumEffectScalar,
            kMaximumEffectScalar,
            &parsed.velocity_x,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "velocity_y",
            0.0f,
            -kMaximumEffectScalar,
            kMaximumEffectScalar,
            &parsed.velocity_y,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "radius",
            ReadConfigNumber(definition, "radius", 0.0f),
            0.0f,
            kMaximumEffectScalar,
            &parsed.radius,
            error_message)) {
        return false;
    }

    const auto default_lifetime = (std::min)(
        ReadConfigInteger(
            definition,
            "duration_ms",
            kDefaultEffectLifetimeMs),
        kMaximumEffectLifetimeMs);
    const auto* lifetime = FindField(descriptor, "lifetime_ms");
    std::uint32_t lifetime_ms = default_lifetime;
    if (lifetime != nullptr) {
        if (lifetime->type != LuaModValueType::Integer ||
            lifetime->integer_value < 1 ||
            lifetime->integer_value > kMaximumEffectLifetimeMs) {
            *error_message = "lifetime_ms must be an integer from 1 through 600000";
            return false;
        }
        lifetime_ms = static_cast<std::uint32_t>(lifetime->integer_value);
    }
    parsed.expires_ms = lifetime_ms;
    parsed.tick_interval_ms = (std::max)(
        1u,
        ReadConfigInteger(
            definition,
            "tick_interval_ms",
            kDefaultTickIntervalMs));
    if (const auto* data = FindField(descriptor, "data"); data != nullptr) {
        if (!ValidateReplicatedData(*data, error_message)) {
            return false;
        }
        parsed.data = *data;
    }
    *effect = std::move(parsed);
    return true;
}

const LuaSpellDefinition* FindDefinition(
    const LoadedLuaMod& mod,
    std::uint64_t content_id) {
    const auto found = std::find_if(
        mod.spell_definitions.begin(),
        mod.spell_definitions.end(),
        [content_id](const LuaSpellDefinition& definition) {
            return definition.identity.network_id == content_id;
        });
    return found == mod.spell_definitions.end() ? nullptr : &*found;
}

void PushEffectContext(
    lua_State* state,
    const LuaSpellEffectInstance& effect,
    std::uint64_t now_ms,
    std::uint32_t delta_ms) {
    const auto age = now_ms > effect.created_ms
        ? now_ms - effect.created_ms
        : 0;
    const auto remaining = effect.expires_ms > now_ms
        ? effect.expires_ms - now_ms
        : 0;
    lua_createtable(state, 0, 16);
    lua_pushinteger(state, static_cast<lua_Integer>(effect.effect_id));
    lua_setfield(state, -2, "effect_id");
    lua_pushinteger(state, static_cast<lua_Integer>(effect.cast_request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(state, static_cast<lua_Integer>(effect.content_id));
    lua_setfield(state, -2, "content_id");
    lua_pushinteger(state, static_cast<lua_Integer>(effect.owner_participant_id));
    lua_setfield(state, -2, "owner_participant_id");
    lua_pushlstring(state, effect.key.data(), effect.key.size());
    lua_setfield(state, -2, "key");
    lua_pushnumber(state, effect.x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, effect.y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, effect.velocity_x);
    lua_setfield(state, -2, "velocity_x");
    lua_pushnumber(state, effect.velocity_y);
    lua_setfield(state, -2, "velocity_y");
    lua_pushnumber(state, effect.radius);
    lua_setfield(state, -2, "radius");
    lua_pushinteger(state, static_cast<lua_Integer>(age));
    lua_setfield(state, -2, "age_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(remaining));
    lua_setfield(state, -2, "remaining_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(delta_ms));
    lua_setfield(state, -2, "delta_ms");
    PushLuaModValue(state, effect.data);
    lua_setfield(state, -2, "data");
}

bool ApplyEffectPatch(
    const LuaModValue& patch,
    LuaSpellEffectInstance* effect,
    bool* retire,
    std::string* error_message) {
    *retire = false;
    if (patch.type == LuaModValueType::Nil) {
        return true;
    }
    if (patch.type == LuaModValueType::Boolean) {
        *retire = !patch.boolean_value;
        return true;
    }
    if (patch.type != LuaModValueType::Object) {
        *error_message = "callback must return nil, a boolean, or an effect patch object";
        return false;
    }
    for (const auto& [field_name, unused] : patch.object_value) {
        (void)unused;
        if (!IsKnownPatchField(field_name)) {
            *error_message = "effect patch contains unknown field '" + field_name + "'";
            return false;
        }
    }

    LuaSpellEffectInstance updated = *effect;
    if (!ReadBoundedFloat(
            patch,
            "x",
            updated.x,
            -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude,
            &updated.x,
            error_message) ||
        !ReadBoundedFloat(
            patch,
            "y",
            updated.y,
            -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude,
            &updated.y,
            error_message) ||
        !ReadBoundedFloat(
            patch,
            "velocity_x",
            updated.velocity_x,
            -kMaximumEffectScalar,
            kMaximumEffectScalar,
            &updated.velocity_x,
            error_message) ||
        !ReadBoundedFloat(
            patch,
            "velocity_y",
            updated.velocity_y,
            -kMaximumEffectScalar,
            kMaximumEffectScalar,
            &updated.velocity_y,
            error_message) ||
        !ReadBoundedFloat(
            patch,
            "radius",
            updated.radius,
            0.0f,
            kMaximumEffectScalar,
            &updated.radius,
            error_message)) {
        return false;
    }
    if (const auto* data = FindField(patch, "data"); data != nullptr) {
        if (!ValidateReplicatedData(*data, error_message)) {
            return false;
        }
        updated.data = *data;
    }
    if (const auto* done = FindField(patch, "done"); done != nullptr) {
        if (done->type != LuaModValueType::Boolean) {
            *error_message = "effect patch done must be boolean";
            return false;
        }
        *retire = done->boolean_value;
    }
    *effect = std::move(updated);
    return true;
}

bool InvokeEffectCallback(
    LoadedLuaMod* mod,
    int callback_reference,
    LuaSpellEffectInstance* effect,
    std::uint64_t now_ms,
    std::uint32_t delta_ms,
    const SDModSceneActorState* target,
    bool* retire) {
    auto* state = mod->state;
    const int stack_top = lua_gettop(state);
    lua_rawgeti(state, LUA_REGISTRYINDEX, callback_reference);
    if (!lua_isfunction(state, -1)) {
        lua_settop(state, stack_top);
        LogLuaMessage(*mod, "registered spell effect callback reference is invalid");
        return false;
    }
    PushEffectContext(state, *effect, now_ms, delta_ms);
    int argument_count = 1;
    if (target != nullptr) {
        lua_createtable(state, 0, 12);
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(
                multiplayer::GetLocalRunEnemyNetworkActorId(
                    target->actor_address)));
        lua_setfield(state, -2, "network_actor_id");
        std::uint32_t spawn_serial = 0;
        TryGetRunLifecycleEnemySpawnSerial(
            target->actor_address,
            &spawn_serial);
        lua_pushinteger(state, static_cast<lua_Integer>(spawn_serial));
        lua_setfield(state, -2, "spawn_serial");
        lua_pushinteger(state, target->enemy_type);
        lua_setfield(state, -2, "enemy_type");
        lua_pushinteger(state, target->object_type_id);
        lua_setfield(state, -2, "object_type_id");
        lua_pushnumber(state, target->x);
        lua_setfield(state, -2, "x");
        lua_pushnumber(state, target->y);
        lua_setfield(state, -2, "y");
        lua_pushnumber(state, target->radius);
        lua_setfield(state, -2, "radius");
        lua_pushnumber(state, target->hp);
        lua_setfield(state, -2, "hp");
        lua_pushnumber(state, target->max_hp);
        lua_setfield(state, -2, "max_hp");
        SDModLuaEnemySpawnConfig config;
        if (TryGetRunLifecycleLuaEnemySpawnConfig(
                target->actor_address,
                &config) &&
            config.content_id != 0) {
            lua_pushinteger(
                state,
                static_cast<lua_Integer>(config.content_id));
            lua_setfield(state, -2, "content_id");
        }
        argument_count = 2;
    }
    if (lua_pcall(state, argument_count, 1, 0) != LUA_OK) {
        const auto* message = lua_tostring(state, -1);
        LogLuaMessage(
            *mod,
            std::string("registered spell effect callback failed: ") +
                (message == nullptr ? "unknown" : message));
        lua_settop(state, stack_top);
        return false;
    }

    LuaModValue patch;
    std::string patch_error;
    const bool converted = ReadLuaModValue(
        state,
        -1,
        &patch,
        &patch_error);
    lua_settop(state, stack_top);
    if (!converted ||
        !ApplyEffectPatch(patch, effect, retire, &patch_error)) {
        LogLuaMessage(
            *mod,
            "registered spell effect callback returned an invalid patch: " +
                patch_error);
        return false;
    }
    return true;
}

bool Overlaps(
    const LuaSpellEffectInstance& effect,
    const SDModSceneActorState& actor) {
    if (!actor.valid || !actor.tracked_enemy || actor.dead ||
        actor.actor_address == 0 || !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) || !std::isfinite(actor.radius)) {
        return false;
    }
    const auto delta_x = actor.x - effect.x;
    const auto delta_y = actor.y - effect.y;
    const auto combined_radius = effect.radius + (std::max)(actor.radius, 0.0f);
    return delta_x * delta_x + delta_y * delta_y <=
        combined_radius * combined_radius;
}

}  // namespace

bool CreateLuaSpellEffectsFromCallbackResult(
    LoadedLuaMod* mod,
    const LuaSpellDefinition& definition,
    const LuaRegisteredSpellCastRequest& request,
    std::uint64_t now_ms,
    int result_index,
    std::string* error_message) {
    if (mod == nullptr || mod->state == nullptr || error_message == nullptr) {
        return false;
    }
    error_message->clear();
    LuaModValue callback_result;
    if (!ReadLuaModValue(
            mod->state,
            result_index,
            &callback_result,
            error_message)) {
        return false;
    }
    if (callback_result.type == LuaModValueType::Nil) {
        return true;
    }

    std::vector<LuaModValue> descriptors;
    if (callback_result.type == LuaModValueType::Array) {
        if (callback_result.array_value.size() > kMaximumEffectsPerCast) {
            *error_message = "on_cast returned more than 16 effects";
            return false;
        }
        descriptors = std::move(callback_result.array_value);
    } else if (callback_result.type == LuaModValueType::Object) {
        descriptors.push_back(std::move(callback_result));
    } else {
        *error_message = "on_cast must return nil, an effect object, or an effect array";
        return false;
    }
    if (mod->spell_effects.size() + descriptors.size() >
        kMaximumEffectsPerMod) {
        *error_message = "registered spell effect limit for this mod was reached";
        return false;
    }

    std::vector<LuaSpellEffectInstance> parsed;
    parsed.reserve(descriptors.size());
    for (const auto& descriptor : descriptors) {
        LuaSpellEffectInstance effect;
        if (!ParseEffectDescriptor(
                descriptor,
                definition,
                request,
                &effect,
                error_message)) {
            return false;
        }
        effect.created_ms = now_ms;
        effect.updated_ms = now_ms;
        effect.expires_ms = now_ms + effect.expires_ms;
        effect.next_tick_ms = now_ms + effect.tick_interval_ms;
        parsed.push_back(std::move(effect));
    }
    for (auto& effect : parsed) {
        if (mod->next_spell_effect_id == 0 ||
            mod->next_spell_effect_id >
                static_cast<std::uint64_t>(INT64_MAX)) {
            mod->next_spell_effect_id = 1;
        }
        effect.effect_id = mod->next_spell_effect_id++;
        mod->spell_effects.push_back(std::move(effect));
    }
    return true;
}

void TickLuaRegisteredSpellEffects(
    const SDModRuntimeTickContext& context) {
    const bool have_effects = std::any_of(
        LoadedLuaModsStorage().begin(),
        LoadedLuaModsStorage().end(),
        [](const std::unique_ptr<LoadedLuaMod>& mod) {
            return mod != nullptr && !mod->spell_effects.empty();
        });
    if (!have_effects) {
        return;
    }
    std::vector<SDModSceneActorState> actors;
    const bool have_actors = TryListSceneActors(&actors);
    const auto now_ms = context.monotonic_milliseconds;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        if (loaded_mod == nullptr || loaded_mod->state == nullptr) {
            continue;
        }
        auto* mod = loaded_mod.get();
        for (std::size_t index = 0; index < mod->spell_effects.size();) {
            auto& effect = mod->spell_effects[index];
            const auto elapsed_ms = now_ms > effect.updated_ms
                ? now_ms - effect.updated_ms
                : 0;
            const auto delta_ms = static_cast<std::uint32_t>((std::min)(
                elapsed_ms,
                static_cast<std::uint64_t>(
                    (std::numeric_limits<std::uint32_t>::max)())));
            const auto delta_seconds = static_cast<float>(elapsed_ms) / 1000.0f;
            effect.x += effect.velocity_x * delta_seconds;
            effect.y += effect.velocity_y * delta_seconds;
            effect.updated_ms = now_ms;
            bool retire = now_ms >= effect.expires_ms ||
                !std::isfinite(effect.x) || !std::isfinite(effect.y) ||
                std::fabs(effect.x) > kMaximumCoordinateMagnitude ||
                std::fabs(effect.y) > kMaximumCoordinateMagnitude;

            const auto* definition = FindDefinition(*mod, effect.content_id);
            if (!retire && definition == nullptr) {
                retire = true;
            }
            if (!retire && definition->on_tick_reference != LUA_NOREF &&
                now_ms >= effect.next_tick_ms) {
                effect.next_tick_ms = now_ms + effect.tick_interval_ms;
                InvokeEffectCallback(
                    mod,
                    definition->on_tick_reference,
                    &effect,
                    now_ms,
                    delta_ms,
                    nullptr,
                    &retire);
            }
            if (!retire && have_actors && effect.radius > 0.0f &&
                definition->on_hit_reference != LUA_NOREF) {
                for (const auto& actor : actors) {
                    if (!Overlaps(effect, actor) ||
                        effect.hit_actor_addresses.find(actor.actor_address) !=
                            effect.hit_actor_addresses.end()) {
                        continue;
                    }
                    if (effect.hit_actor_addresses.size() >=
                        kMaximumRememberedHitActors) {
                        retire = true;
                        break;
                    }
                    effect.hit_actor_addresses.insert(actor.actor_address);
                    InvokeEffectCallback(
                        mod,
                        definition->on_hit_reference,
                        &effect,
                        now_ms,
                        delta_ms,
                        &actor,
                        &retire);
                    if (retire) {
                        break;
                    }
                }
            }
            if (retire) {
                mod->spell_effects.erase(mod->spell_effects.begin() + index);
            } else {
                ++index;
            }
        }
    }
}

}  // namespace sdmod::detail

namespace sdmod {

std::vector<LuaRegisteredSpellEffectState>
SnapshotLocalLuaRegisteredSpellEffects() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    std::vector<LuaRegisteredSpellEffectState> states;
    if (!detail::LuaEngineInitializedFlag()) {
        return states;
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    for (const auto& loaded_mod : detail::LoadedLuaModsStorage()) {
        if (loaded_mod == nullptr || loaded_mod->state == nullptr) {
            continue;
        }
        states.reserve(states.size() + loaded_mod->spell_effects.size());
        for (const auto& effect : loaded_mod->spell_effects) {
            LuaRegisteredSpellEffectState state;
            state.owner_participant_id = effect.owner_participant_id;
            state.cast_request_id = effect.cast_request_id;
            state.content_id = effect.content_id;
            state.effect_id = effect.effect_id;
            state.key = effect.key;
            state.x = effect.x;
            state.y = effect.y;
            state.velocity_x = effect.velocity_x;
            state.velocity_y = effect.velocity_y;
            state.radius = effect.radius;
            state.age_ms = static_cast<std::uint32_t>((std::min)(
                now_ms > effect.created_ms ? now_ms - effect.created_ms : 0,
                static_cast<std::uint64_t>(
                    (std::numeric_limits<std::uint32_t>::max)())));
            state.remaining_ms = static_cast<std::uint32_t>((std::min)(
                effect.expires_ms > now_ms ? effect.expires_ms - now_ms : 0,
                static_cast<std::uint64_t>(
                    (std::numeric_limits<std::uint32_t>::max)())));
            state.data = effect.data;
            states.push_back(std::move(state));
        }
    }
    return states;
}

}  // namespace sdmod
