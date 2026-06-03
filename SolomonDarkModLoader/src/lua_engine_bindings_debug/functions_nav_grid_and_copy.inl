template <typename T>
bool LuaSetFieldFromMemory(lua_State* state, uintptr_t base_address, size_t offset, const char* field_name) {
    T value{};
    if (!ProcessMemory::Instance().TryReadField(base_address, offset, &value)) {
        return false;
    }

    PushLuaScalarValue(state, value);
    lua_setfield(state, -2, field_name);
    return true;
}

template <typename T>
bool LuaSetValueFromMemory(lua_State* state, uintptr_t address, const char* field_name) {
    T value{};
    if (!ProcessMemory::Instance().TryReadValue(address, &value)) {
        return false;
    }

    PushLuaScalarValue(state, value);
    lua_setfield(state, -2, field_name);
    return true;
}

void LuaSetReadableFlag(lua_State* state, bool readable) {
    lua_pushboolean(state, readable ? 1 : 0);
    lua_setfield(state, -2, "readable");
}

bool TryReadLuaFiniteFloatField(uintptr_t base_address, size_t offset, float* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(base_address, offset, value)) {
        return false;
    }
    return std::isfinite(*value);
}

// sd.debug.get_nav_grid([subdivisions]) -> table|nil
// Returns the latest nav-grid snapshot produced on the gameplay thread, or nil
// if no snapshot has been built yet. Also submits a rebuild request so the next
// gameplay tick refreshes the snapshot. Callers should tolerate nil on the
// first call after scene load and retry.
int LuaDebugGetNavGrid(lua_State* state) {
    const auto subdivisions = lua_gettop(state) >= 1 ? static_cast<int>(luaL_checkinteger(state, 1)) : 1;
    RequestNavGridSnapshotRebuild(subdivisions);

    auto snapshot = GetLastNavGridSnapshotShared();
    if (snapshot == nullptr || !snapshot->valid) {
        lua_pushnil(state);
        return 1;
    }

    const SDModGameplayNavGridState& grid_state = *snapshot;

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
        lua_pushboolean(state, cell.path_traversable ? 1 : 0);
        lua_setfield(state, -2, "path_traversable");
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
    const auto actor_address = ResolveReadableLuaAddress(
        memory,
        requested_actor_address,
        kGameNpcLateTimerOffset + sizeof(std::uint32_t));
    if (actor_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    float actor_x = 0.0f;
    float actor_y = 0.0f;
    float goal_x = 0.0f;
    float goal_y = 0.0f;
    if (!TryReadLuaFiniteFloatField(actor_address, kActorPositionXOffset, &actor_x) ||
        !TryReadLuaFiniteFloatField(actor_address, kActorPositionYOffset, &actor_y) ||
        !TryReadLuaFiniteFloatField(actor_address, kGameNpcGoalXOffset, &goal_x) ||
        !TryReadLuaFiniteFloatField(actor_address, kGameNpcGoalYOffset, &goal_y)) {
        lua_pushnil(state);
        return 1;
    }
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
    (void)LuaSetFieldFromMemory<float>(state, actor_address, kActorHeadingOffset, "heading");
    (void)LuaSetFieldFromMemory<float>(state, actor_address, kGameNpcDesiredYawOffset, "desired_yaw");
    (void)LuaSetFieldFromMemory<std::uint8_t>(state, actor_address, kGameNpcMoveFlagOffset, "move_flag");
    lua_pushnumber(state, static_cast<lua_Number>(goal_x));
    lua_setfield(state, -2, "goal_x");
    lua_pushnumber(state, static_cast<lua_Number>(goal_y));
    lua_setfield(state, -2, "goal_y");
    (void)LuaSetFieldFromMemory<float>(state, actor_address, kGameNpcGoalStartXOffset, "goal_start_x");
    (void)LuaSetFieldFromMemory<float>(state, actor_address, kGameNpcGoalStartYOffset, "goal_start_y");
    lua_pushnumber(state, static_cast<lua_Number>(goal_dx));
    lua_setfield(state, -2, "goal_delta_x");
    lua_pushnumber(state, static_cast<lua_Number>(goal_dy));
    lua_setfield(state, -2, "goal_delta_y");
    lua_pushnumber(state, static_cast<lua_Number>((goal_dx * goal_dx) + (goal_dy * goal_dy)));
    lua_setfield(state, -2, "goal_distance_sq");
    (void)LuaSetFieldFromMemory<std::uint8_t>(state, actor_address, kGameNpcModeOffset, "mode");
    (void)LuaSetFieldFromMemory<std::int32_t>(state, actor_address, kGameNpcRepathTimerOffset, "repath_timer");
    (void)LuaSetFieldFromMemory<float>(state, actor_address, kGameNpcSpeedScalarOffset, "speed_scalar");
    (void)LuaSetFieldFromMemory<float>(state, actor_address, kGameNpcStartupCadenceOffset, "startup_cadence");
    (void)LuaSetFieldFromMemory<std::int8_t>(state, actor_address, kGameNpcTrackedSlotOffset, "tracked_slot");
    (void)LuaSetFieldFromMemory<std::uint8_t>(state, actor_address, kGameNpcTrackedSlotCallbackOffset, "callback");
    (void)LuaSetFieldFromMemory<std::int32_t>(state, actor_address, kGameNpcLateTimerOffset, "late_timer");
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

    if (world_address == 0) {
        lua_pushnil(state);
        return 1;
    }

    auto& memory = ProcessMemory::Instance();
    const auto controller_address = world_address + kActorOwnerMovementControllerOffset;
    const auto resolved_controller = ResolveReadableLuaAddress(
        memory,
        controller_address,
        kMovementControllerCellHeightOffset + sizeof(float));
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
            std::int32_t count = 0;
            uintptr_t list_address = 0;
            const bool readable =
                memory.TryReadField(resolved_controller, count_offset, &count) &&
                memory.TryReadField(resolved_controller, list_offset, &list_address);

            lua_createtable(state, 0, 3);
            LuaSetReadableFlag(state, readable);
            if (!readable) {
                lua_setfield(state, -2, field_name);
                return;
            }
            lua_pushinteger(state, static_cast<lua_Integer>(count));
            lua_setfield(state, -2, "count");
            lua_pushinteger(state, static_cast<lua_Integer>(list_address));
            lua_setfield(state, -2, "list_address");
            lua_createtable(state, entry_limit, 0);
            for (int index = 0; index < entry_limit && index < count; ++index) {
                uintptr_t entry_address = 0;
                const bool have_entry_address =
                    list_address != 0 &&
                    memory.TryReadValue(
                        list_address + static_cast<std::size_t>(index) * sizeof(uintptr_t),
                        &entry_address);
                lua_createtable(state, 0, include_type_mask ? 5 : 2);
                LuaSetReadableFlag(state, have_entry_address);
                lua_pushinteger(state, static_cast<lua_Integer>(index));
                lua_setfield(state, -2, "index");
                if (have_entry_address) {
                    lua_pushinteger(state, static_cast<lua_Integer>(entry_address));
                    lua_setfield(state, -2, "address");
                }
                if (include_type_mask && have_entry_address && entry_address != 0) {
                    (void)LuaSetFieldFromMemory<std::int32_t>(
                        state,
                        entry_address,
                        kMovementOverlapEntryTypeOffset,
                        "type");
                    (void)LuaSetFieldFromMemory<std::uint32_t>(
                        state,
                        entry_address,
                        kMovementOverlapEntryMaskOffset,
                        "mask");
                    (void)LuaSetFieldFromMemory<std::uint32_t>(
                        state,
                        entry_address,
                        kMovementOverlapEntryAuxOffset,
                        "aux");
                }
                lua_rawseti(state, -2, index + 1);
            }
            lua_setfield(state, -2, "entries");
            lua_setfield(state, -2, field_name);
        };

    push_entry_list("primary", kMovementControllerPrimaryCountOffset, kMovementControllerPrimaryListOffset, true);
    push_entry_list("secondary", kMovementControllerSecondaryCountOffset, kMovementControllerSecondaryListOffset, true);

    std::int32_t shape_count = 0;
    uintptr_t shape_list_address = 0;
    const bool have_shape_list =
        memory.TryReadField(resolved_controller, kMovementControllerShapeCountOffset, &shape_count) &&
        memory.TryReadField(resolved_controller, kMovementControllerShapeListOffset, &shape_list_address);
    lua_createtable(state, 0, 3);
    LuaSetReadableFlag(state, have_shape_list);
    if (have_shape_list) {
        lua_pushinteger(state, static_cast<lua_Integer>(shape_count));
        lua_setfield(state, -2, "count");
        lua_pushinteger(state, static_cast<lua_Integer>(shape_list_address));
        lua_setfield(state, -2, "list_address");
    }
    lua_createtable(state, entry_limit, 0);
    for (int index = 0; have_shape_list && index < entry_limit && index < shape_count; ++index) {
        uintptr_t shape_address = 0;
        const bool have_shape_address =
            shape_list_address != 0 &&
            memory.TryReadValue(
                shape_list_address + static_cast<std::size_t>(index) * sizeof(uintptr_t),
                &shape_address);
        lua_createtable(state, 0, 9);
        LuaSetReadableFlag(state, have_shape_address);
        lua_pushinteger(state, static_cast<lua_Integer>(index));
        lua_setfield(state, -2, "index");
        if (have_shape_address) {
            lua_pushinteger(state, static_cast<lua_Integer>(shape_address));
            lua_setfield(state, -2, "address");
        }
        if (have_shape_address && shape_address != 0) {
            uintptr_t points_address = 0;
            const bool have_points_address =
                memory.TryReadField(shape_address, kMovementShapePointsOffset, &points_address);
            uintptr_t cached_points_address = 0;
            const bool have_cached_points_address =
                memory.TryReadField(shape_address, kMovementShapeCachedPointsOffset, &cached_points_address);
            std::int32_t point_count = 0;
            const bool have_point_count =
                memory.TryReadField(shape_address, kMovementShapePointCountOffset, &point_count);
            if (have_points_address) {
                lua_pushinteger(state, static_cast<lua_Integer>(points_address));
                lua_setfield(state, -2, "points_address");
            }
            if (have_cached_points_address) {
                lua_pushinteger(state, static_cast<lua_Integer>(cached_points_address));
                lua_setfield(state, -2, "cached_points_address");
            }
            if (have_point_count) {
                lua_pushinteger(state, static_cast<lua_Integer>(point_count));
                lua_setfield(state, -2, "point_count");
            }
            (void)LuaSetFieldFromMemory<float>(state, shape_address, kMovementShapeBoundsXOffset, "bounds_x");
            (void)LuaSetFieldFromMemory<float>(state, shape_address, kMovementShapeBoundsYOffset, "bounds_y");
            (void)LuaSetFieldFromMemory<float>(state, shape_address, kMovementShapeBoundsWOffset, "bounds_w");
            (void)LuaSetFieldFromMemory<float>(state, shape_address, kMovementShapeBoundsHOffset, "bounds_h");
            const auto active_points_address = have_points_address && points_address != 0
                ? points_address
                : (have_cached_points_address ? cached_points_address : 0);
            lua_createtable(state, point_limit, 0);
            for (int point_index = 0;
                 active_points_address != 0 && have_point_count && point_index < point_limit && point_index < point_count;
                 ++point_index) {
                const auto point_address =
                    active_points_address + static_cast<std::size_t>(point_index) * (sizeof(float) * 2);
                lua_createtable(state, 0, 3);
                LuaSetReadableFlag(
                    state,
                    memory.IsReadableRange(point_address, sizeof(float) * 2));
                lua_pushinteger(state, static_cast<lua_Integer>(point_index));
                lua_setfield(state, -2, "index");
                (void)LuaSetValueFromMemory<float>(state, point_address, "x");
                (void)LuaSetValueFromMemory<float>(state, point_address + sizeof(float), "y");
                lua_rawseti(state, -2, point_index + 1);
            }
            lua_setfield(state, -2, "points");
        }
        lua_rawseti(state, -2, index + 1);
    }
    lua_setfield(state, -2, "entries");
    lua_setfield(state, -2, "shapes");

    std::int32_t circle_count = 0;
    uintptr_t circle_list_address = 0;
    const bool have_circle_list =
        memory.TryReadField(resolved_controller, kMovementControllerCircleCountOffset, &circle_count) &&
        memory.TryReadField(resolved_controller, kMovementControllerCircleListOffset, &circle_list_address);
    lua_createtable(state, 0, 3);
    LuaSetReadableFlag(state, have_circle_list);
    if (have_circle_list) {
        lua_pushinteger(state, static_cast<lua_Integer>(circle_count));
        lua_setfield(state, -2, "count");
        lua_pushinteger(state, static_cast<lua_Integer>(circle_list_address));
        lua_setfield(state, -2, "list_address");
    }
    lua_createtable(state, entry_limit, 0);
    for (int index = 0; have_circle_list && index < entry_limit && index < circle_count; ++index) {
        uintptr_t circle_address = 0;
        const bool have_circle_address =
            circle_list_address != 0 &&
            memory.TryReadValue(
                circle_list_address + static_cast<std::size_t>(index) * sizeof(uintptr_t),
                &circle_address);
        lua_createtable(state, 0, 6);
        LuaSetReadableFlag(state, have_circle_address);
        lua_pushinteger(state, static_cast<lua_Integer>(index));
        lua_setfield(state, -2, "index");
        if (have_circle_address) {
            lua_pushinteger(state, static_cast<lua_Integer>(circle_address));
            lua_setfield(state, -2, "address");
        }
        if (have_circle_address && circle_address != 0) {
            (void)LuaSetFieldFromMemory<std::uint32_t>(
                state,
                circle_address,
                kMovementCircleMaskOffset,
                "mask");
            (void)LuaSetFieldFromMemory<float>(state, circle_address, kMovementCircleXOffset, "x");
            (void)LuaSetFieldFromMemory<float>(state, circle_address, kMovementCircleYOffset, "y");
            (void)LuaSetFieldFromMemory<float>(state, circle_address, kMovementCircleRadiusOffset, "radius");
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
