#include <cfloat>

struct GameplayPathCircleObstacle {
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
    std::uint32_t mask = 0;
};

struct GameplayPathSegmentObstacle {
    uintptr_t record_address = 0;
    float start_x = 0.0f;
    float start_y = 0.0f;
    float end_x = 0.0f;
    float end_y = 0.0f;
};

struct GameplayPathGridSnapshot {
    uintptr_t controller_address = 0;
    uintptr_t cells_address = 0;
    int width = 0;
    int height = 0;
    float cell_width = 0.0f;
    float cell_height = 0.0f;
    std::vector<GameplayPathCircleObstacle> static_circle_obstacles;
    std::vector<GameplayPathSegmentObstacle> openable_segment_obstacles;
};

int GameplayPathCellPlacementSampleResolution() {
    const auto value = static_cast<int>(kGameplayPathCellPlacementSampleResolution);
    return value > 0 ? value : 1;
}

int GameplayPathCellLineSampleResolution() {
    const auto value = static_cast<int>(kGameplayPathCellLineSampleResolution);
    return value > 0 ? value : 1;
}

std::uint32_t GameplayPathStaticCircleObstacleMask() {
    return static_cast<std::uint32_t>(kGameplayPathStaticCircleObstacleMask);
}

std::uint32_t GameplayPathPushableCircleObstacleMask() {
    return static_cast<std::uint32_t>(kGameplayPathPushableCircleObstacleMask);
}

std::uint32_t GameplayPathOpenableSegmentObstacleMask() {
    return static_cast<std::uint32_t>(kGameplayPathOpenableSegmentObstacleMask);
}

bool TryReadGameplayPathSegmentObstacle(
    uintptr_t record_address,
    GameplayPathSegmentObstacle* obstacle) {
    if (record_address == 0 || obstacle == nullptr) {
        return false;
    }

    GameplayPathSegmentObstacle read;
    read.record_address = record_address;
    if (!TryReadFiniteFloatField(
            record_address,
            kGameplayPathSegmentStartXOffset,
            &read.start_x) ||
        !TryReadFiniteFloatField(
            record_address,
            kGameplayPathSegmentStartYOffset,
            &read.start_y) ||
        !TryReadFiniteFloatField(
            record_address,
            kGameplayPathSegmentEndXOffset,
            &read.end_x) ||
        !TryReadFiniteFloatField(
            record_address,
            kGameplayPathSegmentEndYOffset,
            &read.end_y)) {
        return false;
    }
    *obstacle = read;
    return true;
}

void CaptureGameplayPathSegmentObstaclePolicy(
    uintptr_t world_address,
    GameplayPathGridSnapshot* snapshot) {
    if (world_address == 0 ||
        snapshot == nullptr ||
        snapshot->controller_address == 0 ||
        kActorWorldSceneryObjectListOffset == 0 ||
        kPointerListCountOffset == 0 ||
        kPointerListItemsOffset == 0 ||
        kGameplayPathOpenableSegmentBuilder == 0 ||
        kGameplayPathOpenableSegmentBuilderVtableSlotOffset == 0 ||
        kGameplayPathOpenableSegmentRecordOffset == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto openable_builder_address =
        memory.ResolveGameAddressOrZero(
            kGameplayPathOpenableSegmentBuilder);
    if (openable_builder_address == 0) {
        return;
    }

    const auto scenery_list_address =
        world_address + kActorWorldSceneryObjectListOffset;
    std::int32_t scenery_count = 0;
    uintptr_t scenery_items_address = 0;
    if (memory.TryReadField(
            scenery_list_address,
            kPointerListCountOffset,
            &scenery_count) &&
        scenery_count > 0 &&
        static_cast<std::size_t>(scenery_count) <=
            kGameplayPathMaxStaticCircleObstacles &&
        memory.TryReadField(
            scenery_list_address,
            kPointerListItemsOffset,
            &scenery_items_address) &&
        scenery_items_address != 0) {
        snapshot->openable_segment_obstacles.reserve(
            static_cast<std::size_t>(scenery_count));
        for (std::int32_t index = 0; index < scenery_count; ++index) {
            uintptr_t object_address = 0;
            uintptr_t vtable_address = 0;
            uintptr_t collision_builder_address = 0;
            uintptr_t segment_record_address = 0;
            if (!memory.TryReadValue(
                    scenery_items_address +
                        static_cast<std::size_t>(index) *
                            sizeof(uintptr_t),
                    &object_address) ||
                object_address == 0 ||
                !memory.TryReadValue(
                    object_address,
                    &vtable_address) ||
                vtable_address == 0 ||
                !memory.TryReadValue(
                    vtable_address +
                        kGameplayPathOpenableSegmentBuilderVtableSlotOffset,
                    &collision_builder_address) ||
                collision_builder_address != openable_builder_address ||
                !memory.TryReadField(
                    object_address,
                    kGameplayPathOpenableSegmentRecordOffset,
                    &segment_record_address) ||
                segment_record_address == 0) {
                continue;
            }
            GameplayPathSegmentObstacle obstacle;
            if (TryReadGameplayPathSegmentObstacle(
                    segment_record_address,
                    &obstacle)) {
                snapshot->openable_segment_obstacles.push_back(
                    obstacle);
            }
        }
    }
}

float NormalizeGameplayHeadingDegrees(float heading_degrees) {
    if (!std::isfinite(heading_degrees)) {
        return 0.0f;
    }

    while (heading_degrees < 0.0f) {
        heading_degrees += 360.0f;
    }
    while (heading_degrees >= 360.0f) {
        heading_degrees -= 360.0f;
    }
    return heading_degrees;
}

bool CallMovementCollisionTestCirclePlacementSafe(
    uintptr_t placement_test_address,
    uintptr_t movement_controller_address,
    float x,
    float y,
    float radius,
    std::uint32_t mask,
    std::uint32_t* blocked_result,
    DWORD* exception_code) {
    if (blocked_result != nullptr) {
        *blocked_result = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (placement_test_address == 0 || movement_controller_address == 0) {
        return false;
    }

    auto* placement_test = reinterpret_cast<MovementCollisionTestCirclePlacementFn>(placement_test_address);
    __try {
        const auto blocked = placement_test(
            reinterpret_cast<void*>(movement_controller_address),
            x,
            y,
            radius,
            mask);
        if (blocked_result != nullptr) {
            *blocked_result = blocked;
        }
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool CallMovementCollisionTestCirclePlacementExtendedSafe(
    uintptr_t placement_test_address,
    uintptr_t movement_controller_address,
    float x,
    float y,
    float radius,
    std::uint32_t circle_block_mask,
    std::uint32_t overlap_allow_mask,
    std::uint32_t* blocked_result,
    DWORD* exception_code) {
    if (blocked_result != nullptr) {
        *blocked_result = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (placement_test_address == 0 || movement_controller_address == 0) {
        return false;
    }

    auto* placement_test =
        reinterpret_cast<MovementCollisionTestCirclePlacementExtendedFn>(placement_test_address);
    __try {
        const auto blocked = placement_test(
            reinterpret_cast<void*>(movement_controller_address),
            x,
            y,
            radius,
            circle_block_mask,
            overlap_allow_mask);
        if (blocked_result != nullptr) {
            *blocked_result = blocked;
        }
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryBuildGameplayPathGridSnapshot(
    uintptr_t world_address,
    GameplayPathGridSnapshot* snapshot,
    std::string* error_message) {
    if (snapshot == nullptr || world_address == 0 || kActorOwnerMovementControllerOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "Path grid snapshot requires a live world address and movement-controller offset.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto controller_address = world_address + kActorOwnerMovementControllerOffset;
    uintptr_t cells_address = 0;
    std::uint32_t grid_height_u32 = 0;
    std::uint32_t grid_width_u32 = 0;
    float cell_width = 0.0f;
    float cell_height = 0.0f;
    if (!memory.TryReadField(controller_address, kMovementControllerCellsOffset, &cells_address) ||
        !memory.TryReadField(controller_address, kMovementControllerGridHeightOffset, &grid_height_u32) ||
        !memory.TryReadField(controller_address, kMovementControllerGridWidthOffset, &grid_width_u32) ||
        !TryReadFiniteFloatField(controller_address, kMovementControllerCellWidthOffset, &cell_width) ||
        !TryReadFiniteFloatField(controller_address, kMovementControllerCellHeightOffset, &cell_height)) {
        if (error_message != nullptr) {
            *error_message = "Movement controller grid snapshot fields were unreadable.";
        }
        return false;
    }
    const auto grid_height = static_cast<int>(grid_height_u32);
    const auto grid_width = static_cast<int>(grid_width_u32);
    if (cells_address == 0 || grid_width <= 0 || grid_height <= 0 || cell_width <= 0.0f || cell_height <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "Movement controller grid snapshot was incomplete. controller=" + HexString(controller_address) +
                " cells=" + HexString(cells_address) +
                " width=" + std::to_string(grid_width) +
                " height=" + std::to_string(grid_height) +
                " cell=(" + std::to_string(cell_width) + ", " + std::to_string(cell_height) + ")";
        }
        return false;
    }

    snapshot->controller_address = controller_address;
    snapshot->cells_address = cells_address;
    snapshot->width = grid_width;
    snapshot->height = grid_height;
    snapshot->cell_width = cell_width;
    snapshot->cell_height = cell_height;
    snapshot->static_circle_obstacles.clear();
    snapshot->openable_segment_obstacles.clear();

    std::int32_t circle_count = 0;
    uintptr_t circle_list_address = 0;
    if (!memory.TryReadField(controller_address, kMovementControllerCircleCountOffset, &circle_count) ||
        !memory.TryReadField(controller_address, kMovementControllerCircleListOffset, &circle_list_address)) {
        return true;
    }
    if (circle_count > 0 && circle_list_address != 0) {
        const auto clamped_count =
            static_cast<std::size_t>(circle_count) < kGameplayPathMaxStaticCircleObstacles
                ? static_cast<std::size_t>(circle_count)
                : kGameplayPathMaxStaticCircleObstacles;
        snapshot->static_circle_obstacles.reserve(clamped_count);
        for (std::size_t index = 0; index < clamped_count; ++index) {
            uintptr_t circle_address = 0;
            if (!memory.TryReadValue(
                    circle_list_address + index * sizeof(uintptr_t),
                    &circle_address)) {
                continue;
            }
            if (circle_address == 0 ||
                !memory.IsReadableRange(circle_address + kMovementCircleRadiusOffset, sizeof(float))) {
                continue;
            }

            std::uint32_t mask = 0;
            if (!memory.TryReadField(circle_address, kMovementCircleMaskOffset, &mask)) {
                continue;
            }
            if ((mask & GameplayPathStaticCircleObstacleMask()) == 0) {
                continue;
            }
            if ((mask & GameplayPathPushableCircleObstacleMask()) != 0) {
                continue;
            }

            float radius = -1.0f;
            if (!TryReadFiniteFloatField(circle_address, kMovementCircleRadiusOffset, &radius)) {
                continue;
            }
            if (!std::isfinite(radius) || radius < 0.0f) {
                continue;
            }

            float x = 0.0f;
            float y = 0.0f;
            if (!TryReadFiniteFloatField(circle_address, kMovementCircleXOffset, &x) ||
                !TryReadFiniteFloatField(circle_address, kMovementCircleYOffset, &y)) {
                continue;
            }
            if (!std::isfinite(x) || !std::isfinite(y)) {
                continue;
            }

            snapshot->static_circle_obstacles.push_back(GameplayPathCircleObstacle{x, y, radius, mask});
        }
    }
    CaptureGameplayPathSegmentObstaclePolicy(
        world_address,
        snapshot);
    return true;
}
