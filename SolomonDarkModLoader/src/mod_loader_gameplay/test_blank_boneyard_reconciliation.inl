constexpr char kTestBlankBoneyardEnvironmentVariable[] =
    "SDMOD_TEST_BLANK_BONEYARD";
constexpr std::int32_t kTestBlankBoneyardMaximumListEntries = 4096;
constexpr std::uint64_t kTestBlankBoneyardRetryDelayMs = 250;
constexpr std::uint32_t kTestBlankBoneyardSolomonDigTypeId = 0x1391;
constexpr std::uint32_t kTestBlankBoneyardLanternTypeId = 0x1392;

struct NativePointerListView {
    uintptr_t address = 0;
    uintptr_t items_address = 0;
    uintptr_t remove_address = 0;
    std::int32_t count = 0;
};

struct TestBlankBoneyardState {
    uintptr_t applied_world_address = 0;
    std::uint64_t retry_not_before_ms = 0;
    std::uint64_t last_failure_log_ms = 0;
};

TestBlankBoneyardState g_test_blank_boneyard_state;

bool IsExplicitTestBlankBoneyardEnabled() {
    static const bool enabled = [] {
        char value[2] = {};
        const auto length = GetEnvironmentVariableA(
            kTestBlankBoneyardEnvironmentVariable,
            value,
            static_cast<DWORD>(std::size(value)));
        return length == 1 && value[0] == '1';
    }();
    return enabled;
}

bool IsExpectedBlankBoneyardSceneryType(std::uint32_t object_type_id) {
    // Stock BoneyardGenerator output observed in both play.boneyard and direct
    // testrun loads: Tree, Gravestone, Building, Goodie, Fencepost,
    // FenceGrate, and Gate. Refuse to destroy an unknown native class even in
    // the explicitly enabled test mode.
    constexpr std::array<std::uint32_t, 7> kExpectedTypes = {
        2001,
        2029,
        2040,
        2061,
        3006,
        3007,
        3012,
    };
    return std::find(
               kExpectedTypes.begin(),
               kExpectedTypes.end(),
               object_type_id) != kExpectedTypes.end();
}

bool IsExpectedBlankBoneyardScriptedSetpieceType(
    std::uint32_t object_type_id) {
    // The stock arena generator adds the Solomon_Dig intro controller and its
    // Lantern even when the custom Boneyard source contains no placed props.
    // Solomon_Dig owns the pre-wave intro rail and asserts the stock input
    // gates until that rail completes, so neither object belongs in the
    // explicitly blank multiplayer test arena.
    return object_type_id == kTestBlankBoneyardSolomonDigTypeId ||
           object_type_id == kTestBlankBoneyardLanternTypeId;
}

bool TryRequestBlankBoneyardScriptedSetpieceRetirement(
    uintptr_t world_address,
    std::int32_t* active_count,
    std::int32_t* requested_count,
    std::string* error_message) {
    if (active_count != nullptr) {
        *active_count = 0;
    }
    if (requested_count != nullptr) {
        *requested_count = 0;
    }

    std::vector<SDModSceneActorState> actors;
    if (world_address == 0 || !TryListSceneActors(&actors)) {
        if (error_message != nullptr) {
            *error_message =
                "could not enumerate scripted actors in the blank-test Boneyard";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::int32_t observed = 0;
    std::int32_t requested = 0;
    for (const auto& actor : actors) {
        if (actor.owner_address != world_address ||
            !IsExpectedBlankBoneyardScriptedSetpieceType(
                actor.object_type_id)) {
            continue;
        }

        ++observed;
        std::uint8_t pending_remove = 0;
        if (!memory.TryReadField(
                actor.actor_address,
                kActorPendingRemoveOffset,
                &pending_remove)) {
            if (error_message != nullptr) {
                *error_message =
                    "could not read blank-test scripted actor retirement state. type=" +
                    std::to_string(actor.object_type_id) +
                    " address=" + HexString(actor.actor_address);
            }
            return false;
        }
        if (pending_remove != 0) {
            continue;
        }

        DWORD exception_code = 0;
        if (!CallActorRequestRetirementSafe(
                actor.actor_address,
                &exception_code) ||
            !memory.TryReadField(
                actor.actor_address,
                kActorPendingRemoveOffset,
                &pending_remove) ||
            pending_remove == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "blank-test scripted actor retirement failed. type=" +
                    std::to_string(actor.object_type_id) +
                    " address=" + HexString(actor.actor_address) +
                    " seh=0x" + HexString(exception_code);
            }
            return false;
        }
        ++requested;
    }

    if (active_count != nullptr) {
        *active_count = observed;
    }
    if (requested_count != nullptr) {
        *requested_count = requested;
    }
    return true;
}

bool TryReadNativePointerList(
    uintptr_t list_address,
    NativePointerListView* view,
    std::string* error_message) {
    if (view == nullptr || list_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native pointer-list address is unavailable";
        }
        return false;
    }

    *view = NativePointerListView{};
    view->address = list_address;
    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable = 0;
    if (!memory.TryReadValue(list_address, &vtable) || vtable == 0 ||
        !memory.TryReadField(list_address, kPointerListCountOffset, &view->count) ||
        view->count < 0 ||
        view->count > kTestBlankBoneyardMaximumListEntries ||
        !memory.TryReadField(
            list_address,
            kPointerListItemsOffset,
            &view->items_address) ||
        (view->count > 0 && view->items_address == 0) ||
        !memory.TryReadValue(
            vtable + kPointerListRemoveValueVtableOffset,
            &view->remove_address) ||
        view->remove_address == 0 ||
        !memory.IsExecutableRange(view->remove_address, 1)) {
        if (error_message != nullptr) {
            *error_message =
                "native pointer-list layout or remove method is invalid at " +
                HexString(list_address);
        }
        return false;
    }
    return true;
}

bool TryReadPointerListValue(
    const NativePointerListView& list,
    std::int32_t index,
    uintptr_t* value) {
    if (value == nullptr || index < 0 || index >= list.count ||
        list.items_address == 0) {
        return false;
    }
    return ProcessMemory::Instance().TryReadValue(
        list.items_address +
            static_cast<std::size_t>(index) * sizeof(uintptr_t),
        value);
}

bool TryValidateOwnedPointerListTypes(
    const NativePointerListView& list,
    const std::function<bool(std::uint32_t)>& accepts_type,
    std::string_view label,
    std::string* error_message) {
    auto& memory = ProcessMemory::Instance();
    for (std::int32_t index = 0; index < list.count; ++index) {
        uintptr_t object_address = 0;
        std::uint32_t object_type_id = 0;
        if (!TryReadPointerListValue(list, index, &object_address) ||
            object_address == 0 ||
            !memory.TryReadField(
                object_address,
                kGameObjectTypeIdOffset,
                &object_type_id) ||
            !accepts_type(object_type_id)) {
            if (error_message != nullptr) {
                *error_message =
                    std::string(label) +
                    " contains an unexpected native object at index " +
                    std::to_string(index) +
                    " type=" + std::to_string(object_type_id) +
                    " address=" + HexString(object_address);
            }
            return false;
        }
    }
    return true;
}

bool TryRemovePointerListValueIfPresent(
    uintptr_t list_address,
    uintptr_t value,
    std::string_view label,
    std::string* error_message) {
    for (;;) {
        NativePointerListView list;
        if (!TryReadNativePointerList(list_address, &list, error_message)) {
            return false;
        }

        bool found = false;
        for (std::int32_t index = 0; index < list.count; ++index) {
            uintptr_t current = 0;
            if (!TryReadPointerListValue(list, index, &current)) {
                if (error_message != nullptr) {
                    *error_message =
                        std::string(label) +
                        " could not read native pointer-list index " +
                        std::to_string(index);
                }
                return false;
            }
            if (current == value) {
                found = true;
                break;
            }
        }
        if (!found) {
            return true;
        }

        DWORD exception_code = 0;
        if (!CallPointerListRemoveValueSafe(
                list.remove_address,
                list.address,
                value,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    std::string(label) +
                    " native remove raised seh=0x" +
                    HexString(exception_code);
            }
            return false;
        }

        std::int32_t count_after = 0;
        if (!ProcessMemory::Instance().TryReadField(
                list.address,
                kPointerListCountOffset,
                &count_after) ||
            count_after != list.count - 1) {
            if (error_message != nullptr) {
                *error_message =
                    std::string(label) +
                    " native remove did not reduce the pointer-list count";
            }
            return false;
        }
    }
}

bool TryDetachMovementCircleFromGridCell(
    uintptr_t object_address,
    std::string* error_message) {
    if (kActorGridCellPtrOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "movement-circle grid-cell layout is unavailable";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t cell_address = 0;
    if (!memory.TryReadField(
            object_address,
            kActorGridCellPtrOffset,
            &cell_address)) {
        if (error_message != nullptr) {
            *error_message =
                "could not read movement-circle grid-cell membership at " +
                HexString(object_address);
        }
        return false;
    }
    if (cell_address == 0) {
        return true;
    }

    if (!TryRemovePointerListValueIfPresent(
            cell_address,
            object_address,
            "movement-grid cell",
            error_message)) {
        return false;
    }

    uintptr_t current_cell_address = 0;
    if (!memory.TryReadField(
            object_address,
            kActorGridCellPtrOffset,
            &current_cell_address) ||
        (current_cell_address == cell_address &&
         !memory.TryWriteField(
             object_address,
             kActorGridCellPtrOffset,
             static_cast<uintptr_t>(0)))) {
        if (error_message != nullptr) {
            *error_message =
                "could not clear movement-circle grid-cell membership at " +
                HexString(object_address);
        }
        return false;
    }
    return true;
}

bool TryDestroyOwnedPointerList(
    uintptr_t list_address,
    uintptr_t movement_circle_list_address,
    uintptr_t static_circle_list_address,
    std::string_view label,
    std::int32_t* removed_count,
    std::string* error_message) {
    if (removed_count != nullptr) {
        *removed_count = 0;
    }

    for (std::int32_t removed = 0;
         removed < kTestBlankBoneyardMaximumListEntries;
         ++removed) {
        NativePointerListView owner_list;
        if (!TryReadNativePointerList(
                list_address,
                &owner_list,
                error_message)) {
            return false;
        }
        if (owner_list.count == 0) {
            if (removed_count != nullptr) {
                *removed_count = removed;
            }
            return true;
        }

        uintptr_t object_address = 0;
        if (!TryReadPointerListValue(owner_list, 0, &object_address) ||
            object_address == 0) {
            if (error_message != nullptr) {
                *error_message =
                    std::string(label) +
                    " could not read its first owned object";
            }
            return false;
        }

        if (static_circle_list_address != 0 &&
            !TryRemovePointerListValueIfPresent(
                static_circle_list_address,
                object_address,
                "static movement-circle cache",
                error_message)) {
            return false;
        }
        if (movement_circle_list_address != 0 &&
            !TryDetachMovementCircleFromGridCell(
                object_address,
                error_message)) {
            return false;
        }
        if (movement_circle_list_address != 0 &&
            !TryRemovePointerListValueIfPresent(
                movement_circle_list_address,
                object_address,
                "movement-circle list",
                error_message)) {
            return false;
        }
        if (!TryRemovePointerListValueIfPresent(
                owner_list.address,
                object_address,
                label,
                error_message)) {
            return false;
        }

        DWORD exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(
                object_address,
                1,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    std::string(label) +
                    " object destructor raised seh=0x" +
                    HexString(exception_code) +
                    " address=" + HexString(object_address);
            }
            return false;
        }
    }

    if (error_message != nullptr) {
        *error_message =
            std::string(label) +
            " exceeded the explicit blank-test removal limit";
    }
    return false;
}

bool TryApplyExplicitTestBlankBoneyard(
    uintptr_t world_address,
    std::int32_t* scripted_setpieces_active,
    std::int32_t* scripted_setpieces_retired,
    std::int32_t* scenery_removed,
    std::int32_t* roads_removed,
    std::int32_t* fences_removed,
    std::int32_t* remaining_movement_circles,
    std::int32_t* remaining_static_circles,
    std::string* error_message) {
    if (world_address == 0 ||
        kActorWorldSceneryObjectListOffset == 0 ||
        kActorWorldRoadListOffset == 0 ||
        kActorWorldFenceListOffset == 0 ||
        kActorOwnerMovementControllerOffset == 0 ||
        kPointerListCountOffset == 0 ||
        kPointerListItemsOffset == 0 ||
        kMovementControllerCircleCountOffset < kPointerListCountOffset ||
        kMovementControllerStaticCircleCountOffset < kPointerListCountOffset) {
        if (error_message != nullptr) {
            *error_message = "explicit blank-test Boneyard layout is unavailable";
        }
        return false;
    }

    if (!TryRequestBlankBoneyardScriptedSetpieceRetirement(
            world_address,
            scripted_setpieces_active,
            scripted_setpieces_retired,
            error_message)) {
        return false;
    }

    const auto scenery_list_address =
        world_address + kActorWorldSceneryObjectListOffset;
    const auto road_list_address =
        world_address + kActorWorldRoadListOffset;
    const auto fence_list_address =
        world_address + kActorWorldFenceListOffset;
    const auto movement_controller_address =
        world_address + kActorOwnerMovementControllerOffset;
    const auto movement_circle_list_address =
        movement_controller_address +
        kMovementControllerCircleCountOffset -
        kPointerListCountOffset;
    const auto static_circle_list_address =
        movement_controller_address +
        kMovementControllerStaticCircleCountOffset -
        kPointerListCountOffset;

    NativePointerListView scenery_list;
    NativePointerListView road_list;
    NativePointerListView fence_list;
    NativePointerListView movement_circle_list;
    NativePointerListView static_circle_list;
    if (!TryReadNativePointerList(
            scenery_list_address,
            &scenery_list,
            error_message) ||
        !TryReadNativePointerList(
            road_list_address,
            &road_list,
            error_message) ||
        !TryReadNativePointerList(
            fence_list_address,
            &fence_list,
            error_message) ||
        !TryReadNativePointerList(
            movement_circle_list_address,
            &movement_circle_list,
            error_message) ||
        !TryReadNativePointerList(
            static_circle_list_address,
            &static_circle_list,
            error_message)) {
        return false;
    }

    if (!TryValidateOwnedPointerListTypes(
            scenery_list,
            &IsExpectedBlankBoneyardSceneryType,
            "Boneyard scenery list",
            error_message) ||
        !TryValidateOwnedPointerListTypes(
            road_list,
            [](std::uint32_t type) { return type == 3004; },
            "Boneyard road list",
            error_message) ||
        !TryValidateOwnedPointerListTypes(
            fence_list,
            [](std::uint32_t type) { return type == 3005; },
            "Boneyard fence list",
            error_message)) {
        return false;
    }

    if (!TryDestroyOwnedPointerList(
            scenery_list_address,
            movement_circle_list_address,
            static_circle_list_address,
            "Boneyard scenery list",
            scenery_removed,
            error_message) ||
        !TryDestroyOwnedPointerList(
            road_list_address,
            0,
            0,
            "Boneyard road list",
            roads_removed,
            error_message) ||
        !TryDestroyOwnedPointerList(
            fence_list_address,
            0,
            0,
            "Boneyard fence list",
            fences_removed,
            error_message)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               movement_circle_list_address,
               kPointerListCountOffset,
               remaining_movement_circles) &&
           memory.TryReadField(
               static_circle_list_address,
               kPointerListCountOffset,
               remaining_static_circles);
}

void ReconcileExplicitTestBlankBoneyard(
    uintptr_t gameplay_address,
    std::uint64_t now_ms) {
    if (!IsExplicitTestBlankBoneyardEnabled()) {
        return;
    }

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(gameplay_address, &scene_context) ||
        !IsArenaSceneContext(scene_context) ||
        scene_context.world_address == 0) {
        g_test_blank_boneyard_state.applied_world_address = 0;
        g_test_blank_boneyard_state.retry_not_before_ms = 0;
        return;
    }
    if (g_test_blank_boneyard_state.applied_world_address ==
            scene_context.world_address ||
        now_ms < g_test_blank_boneyard_state.retry_not_before_ms) {
        return;
    }

    std::int32_t scripted_setpieces_active = 0;
    std::int32_t scripted_setpieces_retired = 0;
    std::int32_t scenery_removed = 0;
    std::int32_t roads_removed = 0;
    std::int32_t fences_removed = 0;
    std::int32_t remaining_movement_circles = 0;
    std::int32_t remaining_static_circles = 0;
    std::string error_message;
    if (TryApplyExplicitTestBlankBoneyard(
            scene_context.world_address,
            &scripted_setpieces_active,
            &scripted_setpieces_retired,
            &scenery_removed,
            &roads_removed,
            &fences_removed,
            &remaining_movement_circles,
            &remaining_static_circles,
            &error_message)) {
        if (scripted_setpieces_active != 0) {
            g_test_blank_boneyard_state.retry_not_before_ms =
                now_ms + kTestBlankBoneyardRetryDelayMs;
            if (scripted_setpieces_retired != 0) {
                Log(
                    "Explicit multiplayer blank-test Boneyard retired stock "
                    "scripted setpieces. world=" +
                    HexString(scene_context.world_address) +
                    " active=" +
                    std::to_string(scripted_setpieces_active) +
                    " requested=" +
                    std::to_string(scripted_setpieces_retired));
            }
            return;
        }

        g_test_blank_boneyard_state.applied_world_address =
            scene_context.world_address;
        g_test_blank_boneyard_state.retry_not_before_ms = 0;
        Log(
            "Explicit multiplayer blank-test Boneyard applied. world=" +
            HexString(scene_context.world_address) +
            " scripted_setpieces=0" +
            " scenery_removed=" + std::to_string(scenery_removed) +
            " roads_removed=" + std::to_string(roads_removed) +
            " fences_removed=" + std::to_string(fences_removed) +
            " remaining_movement_circles=" +
            std::to_string(remaining_movement_circles) +
            " remaining_static_circles=" +
            std::to_string(remaining_static_circles));
        return;
    }

    g_test_blank_boneyard_state.retry_not_before_ms =
        now_ms + kTestBlankBoneyardRetryDelayMs;
    if (now_ms - g_test_blank_boneyard_state.last_failure_log_ms >= 1000) {
        g_test_blank_boneyard_state.last_failure_log_ms = now_ms;
        Log(
            "Explicit multiplayer blank-test Boneyard deferred. world=" +
            HexString(scene_context.world_address) +
            " error=" + error_message);
    }
}
