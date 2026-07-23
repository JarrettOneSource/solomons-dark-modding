#include "lua_engine_internal.h"

#include "lua_engine.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>

namespace sdmod {
namespace {

struct RegisteredSpellInputSelectionRecord {
    LuaRegisteredSpellInputSelection selection;
    std::string mod_id;
};

struct RegisteredSpellInputSelectionState {
    std::optional<RegisteredSpellInputSelectionRecord> primary;
    std::array<
        std::optional<RegisteredSpellInputSelectionRecord>,
        kLuaRegisteredSpellSecondaryInputSlotCount>
        secondary;
    std::unordered_map<std::uint64_t, std::uint64_t> last_cast_ms;
};

std::mutex& RegisteredSpellInputSelectionMutex() {
    static std::mutex mutex;
    return mutex;
}

RegisteredSpellInputSelectionState& RegisteredSpellInputSelections() {
    static RegisteredSpellInputSelectionState state;
    return state;
}

double ReadConfigNumber(
    const LuaModValue& config,
    std::string_view field,
    double default_value) {
    if (config.type != LuaModValueType::Object) {
        return default_value;
    }
    const auto found = config.object_value.find(field);
    if (found == config.object_value.end()) {
        return default_value;
    }
    if (found->second.type == LuaModValueType::Integer) {
        return static_cast<double>(found->second.integer_value);
    }
    if (found->second.type == LuaModValueType::Number) {
        return found->second.number_value;
    }
    return default_value;
}

RegisteredSpellInputSelectionRecord BuildSelectionRecord(
    const detail::LuaSpellDefinition& definition,
    std::int32_t secondary_slot) {
    RegisteredSpellInputSelectionRecord record;
    record.mod_id = definition.identity.mod_id;
    record.selection.content_id = definition.identity.network_id;
    record.selection.primary =
        definition.slot == detail::LuaSpellSlot::Primary;
    record.selection.secondary_slot = secondary_slot;
    record.selection.mana_cost = static_cast<float>(
        ReadConfigNumber(definition.config, "mana_cost", 0.0));
    record.selection.cooldown_ms = static_cast<std::uint32_t>(
        ReadConfigNumber(definition.config, "cooldown_ms", 0.0));
    record.selection.cast_range = static_cast<float>((std::max)(
        1.0,
        ReadConfigNumber(definition.config, "range", 100.0)));
    return record;
}

const RegisteredSpellInputSelectionRecord* FindSelectedContent(
    const RegisteredSpellInputSelectionState& state,
    std::uint64_t content_id) {
    if (state.primary.has_value() &&
        state.primary->selection.content_id == content_id) {
        return &*state.primary;
    }
    for (const auto& selection : state.secondary) {
        if (selection.has_value() &&
            selection->selection.content_id == content_id) {
            return &*selection;
        }
    }
    return nullptr;
}

}  // namespace

namespace detail {

void ResetLuaRegisteredSpellInputSelections() {
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    RegisteredSpellInputSelections() = {};
}

bool SelectLuaRegisteredSpellForInput(
    const LuaSpellDefinition& definition,
    std::int32_t secondary_slot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const bool primary = definition.slot == LuaSpellSlot::Primary;
    if (primary && secondary_slot != -1) {
        if (error_message != nullptr) {
            *error_message =
                "Primary registered spells do not accept a belt slot.";
        }
        return false;
    }
    if (!primary &&
        (secondary_slot < 0 ||
         secondary_slot >= static_cast<std::int32_t>(
             kLuaRegisteredSpellSecondaryInputSlotCount))) {
        if (error_message != nullptr) {
            *error_message =
                "Secondary registered spells require belt slot 1 through 8.";
        }
        return false;
    }

    auto record = BuildSelectionRecord(definition, secondary_slot);
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    auto& state = RegisteredSpellInputSelections();
    if (primary) {
        state.primary = std::move(record);
    } else {
        state.secondary[static_cast<std::size_t>(secondary_slot)] =
            std::move(record);
    }
    return true;
}

bool ClearLuaRegisteredSpellInputSelection(
    LuaSpellSlot slot,
    std::int32_t secondary_slot) {
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    auto& state = RegisteredSpellInputSelections();
    if (slot == LuaSpellSlot::Primary) {
        const bool cleared = state.primary.has_value();
        state.primary.reset();
        return cleared;
    }
    if (secondary_slot < 0 ||
        secondary_slot >= static_cast<std::int32_t>(state.secondary.size())) {
        return false;
    }
    auto& selection =
        state.secondary[static_cast<std::size_t>(secondary_slot)];
    const bool cleared = selection.has_value();
    selection.reset();
    return cleared;
}

void ClearLuaRegisteredSpellInputSelectionsForMod(std::string_view mod_id) {
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    auto& state = RegisteredSpellInputSelections();
    if (state.primary.has_value() && state.primary->mod_id == mod_id) {
        state.last_cast_ms.erase(state.primary->selection.content_id);
        state.primary.reset();
    }
    for (auto& selection : state.secondary) {
        if (selection.has_value() && selection->mod_id == mod_id) {
            state.last_cast_ms.erase(selection->selection.content_id);
            selection.reset();
        }
    }
}

}  // namespace detail

bool TryGetSelectedLuaRegisteredPrimarySpell(
    LuaRegisteredSpellInputSelection* selection) {
    if (selection == nullptr) {
        return false;
    }
    *selection = {};
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    const auto& selected = RegisteredSpellInputSelections().primary;
    if (!selected.has_value()) {
        return false;
    }
    *selection = selected->selection;
    return true;
}

bool TryGetSelectedLuaRegisteredSecondarySpell(
    std::size_t secondary_slot,
    LuaRegisteredSpellInputSelection* selection) {
    if (selection == nullptr ||
        secondary_slot >= kLuaRegisteredSpellSecondaryInputSlotCount) {
        return false;
    }
    *selection = {};
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    const auto& selected =
        RegisteredSpellInputSelections().secondary[secondary_slot];
    if (!selected.has_value()) {
        return false;
    }
    *selection = selected->selection;
    return true;
}

bool TryGetLuaRegisteredSpellInputCooldownRemaining(
    std::uint64_t content_id,
    std::uint64_t now_ms,
    std::uint32_t* remaining_ms) {
    if (remaining_ms == nullptr || content_id == 0) {
        return false;
    }
    *remaining_ms = 0;
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    const auto& state = RegisteredSpellInputSelections();
    const auto* selected = FindSelectedContent(state, content_id);
    if (selected == nullptr) {
        return false;
    }
    const auto last_cast = state.last_cast_ms.find(content_id);
    if (last_cast == state.last_cast_ms.end() ||
        now_ms < last_cast->second) {
        return true;
    }
    const auto elapsed = now_ms - last_cast->second;
    if (elapsed >= selected->selection.cooldown_ms) {
        return true;
    }
    const auto remaining =
        static_cast<std::uint64_t>(selected->selection.cooldown_ms) - elapsed;
    *remaining_ms = static_cast<std::uint32_t>((std::min)(
        remaining,
        static_cast<std::uint64_t>(
            (std::numeric_limits<std::uint32_t>::max)())));
    return true;
}

void CommitLuaRegisteredSpellInputCast(
    std::uint64_t content_id,
    std::uint64_t now_ms) {
    if (content_id == 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(RegisteredSpellInputSelectionMutex());
    auto& state = RegisteredSpellInputSelections();
    if (FindSelectedContent(state, content_id) != nullptr) {
        state.last_cast_ms[content_id] = now_ms;
    }
}

}  // namespace sdmod
