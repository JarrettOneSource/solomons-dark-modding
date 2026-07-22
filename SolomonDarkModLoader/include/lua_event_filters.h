#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sdmod {

inline constexpr std::size_t kLuaDamageFilterLaneCount = 9;

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

}  // namespace sdmod
