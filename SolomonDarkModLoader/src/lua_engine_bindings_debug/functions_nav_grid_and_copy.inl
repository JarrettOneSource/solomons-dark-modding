// sd.debug.get_nav_grid([subdivisions]) -> table|nil
int LuaDebugGetNavGrid(lua_State* state) {
    const auto subdivisions = lua_gettop(state) >= 1 ? static_cast<int>(luaL_checkinteger(state, 1)) : 1;
    SDModGameplayNavGridState grid_state;
    if (!TryGetGameplayNavGridState(&grid_state, subdivisions) || !grid_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 10);
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.width));
    lua_setfield(state, -2, "width");
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.height));
    lua_setfield(state, -2, "height");
    lua_pushnumber(state, static_cast<lua_Number>(grid_state.cell_width));
    lua_setfield(state, -2, "cell_width");
    lua_pushnumber(state, static_cast<lua_Number>(grid_state.cell_height));
    lua_setfield(state, -2, "cell_height");
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.world_address));
    lua_setfield(state, -2, "world_address");
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.controller_address));
    lua_setfield(state, -2, "controller_address");
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.cells_address));
    lua_setfield(state, -2, "cells_address");
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.probe_actor_address));
    lua_setfield(state, -2, "probe_actor_address");
    lua_pushnumber(state, static_cast<lua_Number>(grid_state.probe_x));
    lua_setfield(state, -2, "probe_x");
    lua_pushnumber(state, static_cast<lua_Number>(grid_state.probe_y));
    lua_setfield(state, -2, "probe_y");
    lua_pushinteger(state, static_cast<lua_Integer>(grid_state.subdivisions));
    lua_setfield(state, -2, "subdivisions");

    lua_createtable(state, static_cast<int>(grid_state.cells.size()), 0);
    int cell_index = 1;
    for (const auto& cell : grid_state.cells) {
        lua_createtable(state, 0, 5);
        lua_pushinteger(state, static_cast<lua_Integer>(cell.grid_x));
        lua_setfield(state, -2, "grid_x");
        lua_pushinteger(state, static_cast<lua_Integer>(cell.grid_y));
        lua_setfield(state, -2, "grid_y");
        lua_pushnumber(state, static_cast<lua_Number>(cell.center_x));
        lua_setfield(state, -2, "center_x");
        lua_pushnumber(state, static_cast<lua_Number>(cell.center_y));
        lua_setfield(state, -2, "center_y");
        lua_pushboolean(state, cell.traversable ? 1 : 0);
        lua_setfield(state, -2, "traversable");
        lua_createtable(state, static_cast<int>(cell.samples.size()), 0);
        int sample_index = 1;
        for (const auto& sample : cell.samples) {
            lua_createtable(state, 0, 5);
            lua_pushinteger(state, static_cast<lua_Integer>(sample.sample_x));
            lua_setfield(state, -2, "sample_x");
            lua_pushinteger(state, static_cast<lua_Integer>(sample.sample_y));
            lua_setfield(state, -2, "sample_y");
            lua_pushnumber(state, static_cast<lua_Number>(sample.world_x));
            lua_setfield(state, -2, "world_x");
            lua_pushnumber(state, static_cast<lua_Number>(sample.world_y));
            lua_setfield(state, -2, "world_y");
            lua_pushboolean(state, sample.traversable ? 1 : 0);
            lua_setfield(state, -2, "traversable");
            lua_rawseti(state, -2, sample_index++);
        }
        lua_setfield(state, -2, "samples");
        lua_rawseti(state, -2, cell_index++);
    }
    lua_setfield(state, -2, "cells");
    return 1;
}

// sd.debug.get_gamenpc_motion(actor_address) -> table|nil
int LuaDebugGetGameNpcMotion(lua_State* state) {
    const auto requested_actor_address = CheckLuaAddress(state, 1, "actor_address");

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = ResolveReadableLuaAddress(memory, requested_actor_address, 0x1C4 + sizeof(std::uint32_t));
    if (actor_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    constexpr std::size_t kActorXOffset = 0x18;
    constexpr std::size_t kActorYOffset = 0x1C;
    constexpr std::size_t kActorHeadingOffset = 0x6C;
    constexpr std::size_t kGameNpcDesiredYawOffset = 0x188;
    constexpr std::size_t kGameNpcMoveFlagOffset = 0x198;
    constexpr std::size_t kGameNpcGoalXOffset = 0x19C;
    constexpr std::size_t kGameNpcGoalYOffset = 0x1A0;
    constexpr std::size_t kGameNpcGoalStartXOffset = 0x1A4;
    constexpr std::size_t kGameNpcGoalStartYOffset = 0x1A8;
    constexpr std::size_t kGameNpcModeOffset = 0x1AC;
    constexpr std::size_t kGameNpcRepathTimerOffset = 0x1B0;
    constexpr std::size_t kGameNpcSpeedScalarOffset = 0x1B4;
    constexpr std::size_t kGameNpcStartupCadenceOffset = 0x1B8;
    constexpr std::size_t kGameNpcTrackedSlotOffset = 0x1C2;
    constexpr std::size_t kGameNpcCallbackOffset = 0x1C3;
    constexpr std::size_t kGameNpcLateTimerOffset = 0x1C4;

    const auto actor_x = memory.ReadFieldOr<float>(actor_address, kActorXOffset, 0.0f);
    const auto actor_y = memory.ReadFieldOr<float>(actor_address, kActorYOffset, 0.0f);
    const auto goal_x = memory.ReadFieldOr<float>(actor_address, kGameNpcGoalXOffset, 0.0f);
    const auto goal_y = memory.ReadFieldOr<float>(actor_address, kGameNpcGoalYOffset, 0.0f);
    const auto goal_dx = goal_x - actor_x;
    const auto goal_dy = goal_y - actor_y;

    lua_createtable(state, 0, 18);
    lua_pushinteger(state, static_cast<lua_Integer>(requested_actor_address));
    lua_setfield(state, -2, "requested_actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushnumber(state, static_cast<lua_Number>(actor_x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(actor_y));
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)));
    lua_setfield(state, -2, "heading");
    lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(actor_address, kGameNpcDesiredYawOffset, 0.0f)));
    lua_setfield(state, -2, "desired_yaw");
    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::uint8_t>(actor_address, kGameNpcMoveFlagOffset, 0)));
    lua_setfield(state, -2, "move_flag");
    lua_pushnumber(state, static_cast<lua_Number>(goal_x));
    lua_setfield(state, -2, "goal_x");
    lua_pushnumber(state, static_cast<lua_Number>(goal_y));
    lua_setfield(state, -2, "goal_y");
    lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(actor_address, kGameNpcGoalStartXOffset, 0.0f)));
    lua_setfield(state, -2, "goal_start_x");
    lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(actor_address, kGameNpcGoalStartYOffset, 0.0f)));
    lua_setfield(state, -2, "goal_start_y");
    lua_pushnumber(state, static_cast<lua_Number>(goal_dx));
    lua_setfield(state, -2, "goal_delta_x");
    lua_pushnumber(state, static_cast<lua_Number>(goal_dy));
    lua_setfield(state, -2, "goal_delta_y");
    lua_pushnumber(state, static_cast<lua_Number>((goal_dx * goal_dx) + (goal_dy * goal_dy)));
    lua_setfield(state, -2, "goal_distance_sq");
    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::uint8_t>(actor_address, kGameNpcModeOffset, 0)));
    lua_setfield(state, -2, "mode");
    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::int32_t>(actor_address, kGameNpcRepathTimerOffset, 0)));
    lua_setfield(state, -2, "repath_timer");
    lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(actor_address, kGameNpcSpeedScalarOffset, 0.0f)));
    lua_setfield(state, -2, "speed_scalar");
    lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(actor_address, kGameNpcStartupCadenceOffset, 0.0f)));
    lua_setfield(state, -2, "startup_cadence");
    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::int8_t>(actor_address, kGameNpcTrackedSlotOffset, -1)));
    lua_setfield(state, -2, "tracked_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::uint8_t>(actor_address, kGameNpcCallbackOffset, 0)));
    lua_setfield(state, -2, "callback");
    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::int32_t>(actor_address, kGameNpcLateTimerOffset, 0)));
    lua_setfield(state, -2, "late_timer");
    return 1;
}

// sd.debug.get_world_movement_geometry(world_address[, max_entries[, max_points]]) -> table|nil
int LuaDebugGetWorldMovementGeometry(lua_State* state) {
    const auto world_address = CheckLuaAddress(state, 1, "world_address");
    const auto max_entries =
        lua_gettop(state) >= 2 && !lua_isnil(state, 2)
            ? static_cast<int>(CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "max_entries"))
            : 8;
    const auto max_points =
        lua_gettop(state) >= 3 && !lua_isnil(state, 3)
            ? static_cast<int>(CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "max_points"))
            : 16;

    constexpr std::size_t kWorldMovementControllerOffset = 0x378;
    if (world_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    constexpr std::size_t kMovementPrimaryCountOffset = 0x40;
    constexpr std::size_t kMovementPrimaryListOffset = 0x4C;
    constexpr std::size_t kMovementSecondaryCountOffset = 0x70;
    constexpr std::size_t kMovementSecondaryListOffset = 0x7C;
    constexpr std::size_t kMovementShapeCountOffset = 0x28;
    constexpr std::size_t kMovementShapeListOffset = 0x34;
    constexpr std::size_t kMovementCircleCountOffset = 0xA0;
    constexpr std::size_t kMovementCircleListOffset = 0xAC;
    constexpr std::size_t kShapePointsOffset = 0x00;
    constexpr std::size_t kShapeCachedPointsOffset = 0x04;
    constexpr std::size_t kShapeBoundsXOffset = 0x08;
    constexpr std::size_t kShapeBoundsYOffset = 0x0C;
    constexpr std::size_t kShapeBoundsWOffset = 0x10;
    constexpr std::size_t kShapeBoundsHOffset = 0x14;
    constexpr std::size_t kShapePointCountOffset = 0x38;
    constexpr std::size_t kCircleMaskOffset = 0x14;
    constexpr std::size_t kCircleXOffset = 0x18;
    constexpr std::size_t kCircleYOffset = 0x1C;
    constexpr std::size_t kCircleRadiusOffset = 0x30;

    auto& memory = ProcessMemory::Instance();
    const auto controller_address = world_address + kWorldMovementControllerOffset;
    const auto resolved_controller = ResolveReadableLuaAddress(memory, controller_address, 0xB4);
    if (resolved_controller == 0) {
        lua_pushnil(state);
        return 1;
    }

    const auto clamp_limit = [](int value) {
        if (value < 0) {
            return 0;
        }
        return value > 64 ? 64 : value;
    };
    const auto entry_limit = clamp_limit(max_entries);
    const auto point_limit = clamp_limit(max_points);

    lua_createtable(state, 0, 10);
    lua_pushinteger(state, static_cast<lua_Integer>(world_address));
    lua_setfield(state, -2, "world_address");
    lua_pushinteger(state, static_cast<lua_Integer>(controller_address));
    lua_setfield(state, -2, "controller_address");

    const auto push_entry_list =
        [&](const char* field_name,
            std::size_t count_offset,
            std::size_t list_offset,
            bool include_type_mask) {
            const auto count = memory.ReadFieldOr<std::int32_t>(resolved_controller, count_offset, 0);
            const auto list_address = memory.ReadFieldOr<uintptr_t>(resolved_controller, list_offset, 0);

            lua_createtable(state, 0, 3);
            lua_pushinteger(state, static_cast<lua_Integer>(count));
            lua_setfield(state, -2, "count");
            lua_pushinteger(state, static_cast<lua_Integer>(list_address));
            lua_setfield(state, -2, "list_address");
            lua_createtable(state, entry_limit, 0);
            for (int index = 0; index < entry_limit && index < count; ++index) {
                const auto entry_address = memory.ReadValueOr<uintptr_t>(
                    list_address + static_cast<std::size_t>(index) * sizeof(uintptr_t),
                    0);
                lua_createtable(state, 0, include_type_mask ? 5 : 2);
                lua_pushinteger(state, static_cast<lua_Integer>(index));
                lua_setfield(state, -2, "index");
                lua_pushinteger(state, static_cast<lua_Integer>(entry_address));
                lua_setfield(state, -2, "address");
                if (include_type_mask && entry_address != 0) {
                    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::int32_t>(entry_address, 0x0C, 0)));
                    lua_setfield(state, -2, "type");
                    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::uint32_t>(entry_address, 0x10, 0)));
                    lua_setfield(state, -2, "mask");
                    lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::uint32_t>(entry_address, 0x14, 0)));
                    lua_setfield(state, -2, "aux");
                }
                lua_rawseti(state, -2, index + 1);
            }
            lua_setfield(state, -2, "entries");
            lua_setfield(state, -2, field_name);
        };

    push_entry_list("primary", kMovementPrimaryCountOffset, kMovementPrimaryListOffset, true);
    push_entry_list("secondary", kMovementSecondaryCountOffset, kMovementSecondaryListOffset, true);

    const auto shape_count = memory.ReadFieldOr<std::int32_t>(resolved_controller, kMovementShapeCountOffset, 0);
    const auto shape_list_address = memory.ReadFieldOr<uintptr_t>(resolved_controller, kMovementShapeListOffset, 0);
    lua_createtable(state, 0, 3);
    lua_pushinteger(state, static_cast<lua_Integer>(shape_count));
    lua_setfield(state, -2, "count");
    lua_pushinteger(state, static_cast<lua_Integer>(shape_list_address));
    lua_setfield(state, -2, "list_address");
    lua_createtable(state, entry_limit, 0);
    for (int index = 0; index < entry_limit && index < shape_count; ++index) {
        const auto shape_address = memory.ReadValueOr<uintptr_t>(
            shape_list_address + static_cast<std::size_t>(index) * sizeof(uintptr_t),
            0);
        lua_createtable(state, 0, 9);
        lua_pushinteger(state, static_cast<lua_Integer>(index));
        lua_setfield(state, -2, "index");
        lua_pushinteger(state, static_cast<lua_Integer>(shape_address));
        lua_setfield(state, -2, "address");
        if (shape_address != 0) {
            const auto points_address = memory.ReadFieldOr<uintptr_t>(shape_address, kShapePointsOffset, 0);
            const auto cached_points_address = memory.ReadFieldOr<uintptr_t>(shape_address, kShapeCachedPointsOffset, 0);
            const auto point_count = memory.ReadFieldOr<std::int32_t>(shape_address, kShapePointCountOffset, 0);
            lua_pushinteger(state, static_cast<lua_Integer>(points_address));
            lua_setfield(state, -2, "points_address");
            lua_pushinteger(state, static_cast<lua_Integer>(cached_points_address));
            lua_setfield(state, -2, "cached_points_address");
            lua_pushinteger(state, static_cast<lua_Integer>(point_count));
            lua_setfield(state, -2, "point_count");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(shape_address, kShapeBoundsXOffset, 0.0f)));
            lua_setfield(state, -2, "bounds_x");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(shape_address, kShapeBoundsYOffset, 0.0f)));
            lua_setfield(state, -2, "bounds_y");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(shape_address, kShapeBoundsWOffset, 0.0f)));
            lua_setfield(state, -2, "bounds_w");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(shape_address, kShapeBoundsHOffset, 0.0f)));
            lua_setfield(state, -2, "bounds_h");
            const auto active_points_address = points_address != 0 ? points_address : cached_points_address;
            lua_createtable(state, point_limit, 0);
            for (int point_index = 0; point_index < point_limit && point_index < point_count; ++point_index) {
                const auto point_address =
                    active_points_address + static_cast<std::size_t>(point_index) * (sizeof(float) * 2);
                lua_createtable(state, 0, 3);
                lua_pushinteger(state, static_cast<lua_Integer>(point_index));
                lua_setfield(state, -2, "index");
                lua_pushnumber(state, static_cast<lua_Number>(memory.ReadValueOr<float>(point_address, 0.0f)));
                lua_setfield(state, -2, "x");
                lua_pushnumber(state, static_cast<lua_Number>(memory.ReadValueOr<float>(point_address + sizeof(float), 0.0f)));
                lua_setfield(state, -2, "y");
                lua_rawseti(state, -2, point_index + 1);
            }
            lua_setfield(state, -2, "points");
        }
        lua_rawseti(state, -2, index + 1);
    }
    lua_setfield(state, -2, "entries");
    lua_setfield(state, -2, "shapes");

    const auto circle_count = memory.ReadFieldOr<std::int32_t>(resolved_controller, kMovementCircleCountOffset, 0);
    const auto circle_list_address = memory.ReadFieldOr<uintptr_t>(resolved_controller, kMovementCircleListOffset, 0);
    lua_createtable(state, 0, 3);
    lua_pushinteger(state, static_cast<lua_Integer>(circle_count));
    lua_setfield(state, -2, "count");
    lua_pushinteger(state, static_cast<lua_Integer>(circle_list_address));
    lua_setfield(state, -2, "list_address");
    lua_createtable(state, entry_limit, 0);
    for (int index = 0; index < entry_limit && index < circle_count; ++index) {
        const auto circle_address = memory.ReadValueOr<uintptr_t>(
            circle_list_address + static_cast<std::size_t>(index) * sizeof(uintptr_t),
            0);
        lua_createtable(state, 0, 6);
        lua_pushinteger(state, static_cast<lua_Integer>(index));
        lua_setfield(state, -2, "index");
        lua_pushinteger(state, static_cast<lua_Integer>(circle_address));
        lua_setfield(state, -2, "address");
        if (circle_address != 0) {
            lua_pushinteger(state, static_cast<lua_Integer>(memory.ReadFieldOr<std::uint32_t>(circle_address, kCircleMaskOffset, 0)));
            lua_setfield(state, -2, "mask");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(circle_address, kCircleXOffset, 0.0f)));
            lua_setfield(state, -2, "x");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(circle_address, kCircleYOffset, 0.0f)));
            lua_setfield(state, -2, "y");
            lua_pushnumber(state, static_cast<lua_Number>(memory.ReadFieldOr<float>(circle_address, kCircleRadiusOffset, 0.0f)));
            lua_setfield(state, -2, "radius");
        }
        lua_rawseti(state, -2, index + 1);
    }
    lua_setfield(state, -2, "entries");
    lua_setfield(state, -2, "circles");

    return 1;
}

// sd.debug.call_cdecl_u32_u32(function_address, arg0, arg1) -> boolean
int LuaDebugCallCdeclU32U32(lua_State* state) {
    const auto requested_function_address = CheckLuaAddress(state, 1, "function_address");
    const auto arg0 = CheckLuaUnsignedInteger<std::uint32_t>(state, 2, "arg0");
    const auto arg1 = CheckLuaUnsignedInteger<std::uint32_t>(state, 3, "arg1");

    auto& memory = ProcessMemory::Instance();
    const auto function_address = ResolveExecutableLuaAddress(memory, requested_function_address);
    if (function_address == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    using CdeclU32U32Fn = void(__cdecl*)(std::uint32_t, std::uint32_t);
    auto* fn = reinterpret_cast<CdeclU32U32Fn>(function_address);
    bool ok = false;
    __try {
        fn(arg0, arg1);
        ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = false;
    }

    lua_pushboolean(state, ok ? 1 : 0);
    return 1;
}

// sd.debug.copy_bytes(src_addr, dst_addr, count) -> boolean
int LuaDebugCopyBytes(lua_State* state) {
    const auto source_address = CheckLuaAddress(state, 1, "src_addr");
    const auto destination_address = CheckLuaAddress(state, 2, "dst_addr");
    const auto count = CheckLuaTransferSize(state, 3, "count");

    std::vector<std::uint8_t> bytes;
    if (!TryReadLuaBytes(source_address, count, &bytes)) {
        lua_pushboolean(state, 0);
        return 1;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_destination = ResolveWritableLuaAddress(memory, destination_address, count);
    if (resolved_destination == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    lua_pushboolean(state, memory.TryWrite(resolved_destination, bytes.data(), bytes.size()) ? 1 : 0);
    return 1;
}
