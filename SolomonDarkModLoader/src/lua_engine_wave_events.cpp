#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
}

#include <cstddef>
#include <cstdint>

namespace sdmod::detail {

void PushWaveStartedPayload(lua_State* state, const WaveSummary& summary) {
    lua_createtable(state, 0, 4);
    lua_pushstring(state, kWaveStartedEventName);
    lua_setfield(state, -2, "event");
    lua_pushinteger(state, static_cast<lua_Integer>(summary.wave));
    lua_setfield(state, -2, "wave");
    std::int32_t planned = 0;
    lua_createtable(state, static_cast<int>(summary.composition.size()), 0);
    for (std::size_t index = 0; index < summary.composition.size(); ++index) {
        const auto& row = summary.composition[index];
        planned += row.planned;
        lua_createtable(state, 0, 2);
        lua_pushinteger(state, static_cast<lua_Integer>(row.enemy_type));
        lua_setfield(state, -2, "enemy_type");
        lua_pushinteger(state, static_cast<lua_Integer>(row.planned));
        lua_setfield(state, -2, "planned");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "composition");
    lua_pushinteger(state, static_cast<lua_Integer>(planned));
    lua_setfield(state, -2, "planned");
}

}  // namespace sdmod::detail
