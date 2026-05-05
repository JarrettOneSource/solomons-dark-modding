#include <cfloat>

struct GameplayPathCircleObstacle {
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
    std::uint32_t mask = 0;
};

struct GameplayPathGridSnapshot {
    uintptr_t controller_address = 0;
    uintptr_t cells_address = 0;
    int width = 0;
    int height = 0;
    float cell_width = 0.0f;
    float cell_height = 0.0f;
    std::vector<GameplayPathCircleObstacle> static_circle_obstacles;
    std::vector<GameplayPathCircleObstacle> ignored_circle_obstacles;
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

std::uint32_t GameplayPathPushThroughGateCircleObjectType() {
    return static_cast<std::uint32_t>(kGameplayPathPushThroughGateCircleObjectType);
}

float GameplayPathPushThroughGateCircleRadius() {
    return static_cast<float>(kGameplayPathPushThroughGateCircleRadius);
}

float GameplayPathPushThroughGateRadiusEpsilon() {
    return static_cast<float>(kGameplayPathPushThroughGateRadiusEpsilonMilliunits) / 1000.0f;
}

bool IsGameplayPathIgnoredStaticCircleObstacle(
    std::uint32_t mask,
    std::uint32_t object_type,
    float radius) {
    if ((mask & GameplayPathPushableCircleObstacleMask()) != 0) {
        return true;
    }

    const auto push_through_gate_radius = GameplayPathPushThroughGateCircleRadius();
    const auto radius_delta =
        radius > push_through_gate_radius
            ? radius - push_through_gate_radius
            : push_through_gate_radius - radius;
    return object_type == GameplayPathPushThroughGateCircleObjectType() &&
           radius_delta <= GameplayPathPushThroughGateRadiusEpsilon();
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
    const auto cells_address =
        memory.ReadFieldOr<uintptr_t>(controller_address, kMovementControllerCellsOffset, 0);
    const auto grid_height = static_cast<int>(
        memory.ReadFieldOr<std::uint32_t>(controller_address, kMovementControllerGridHeightOffset, 0));
    const auto grid_width = static_cast<int>(
        memory.ReadFieldOr<std::uint32_t>(controller_address, kMovementControllerGridWidthOffset, 0));
    const auto cell_width =
        memory.ReadFieldOr<float>(controller_address, kMovementControllerCellWidthOffset, 0.0f);
    const auto cell_height =
        memory.ReadFieldOr<float>(controller_address, kMovementControllerCellHeightOffset, 0.0f);
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

    const auto circle_count = memory.ReadFieldOr<std::int32_t>(
        controller_address,
        kMovementControllerCircleCountOffset,
        0);
    const auto circle_list_address = memory.ReadFieldOr<uintptr_t>(
        controller_address,
        kMovementControllerCircleListOffset,
        0);
    if (circle_count > 0 && circle_list_address != 0) {
        const auto clamped_count =
            static_cast<std::size_t>(circle_count) < kGameplayPathMaxStaticCircleObstacles
                ? static_cast<std::size_t>(circle_count)
                : kGameplayPathMaxStaticCircleObstacles;
        snapshot->static_circle_obstacles.reserve(clamped_count);
        snapshot->ignored_circle_obstacles.reserve(clamped_count);
        for (std::size_t index = 0; index < clamped_count; ++index) {
            const auto circle_address = memory.ReadValueOr<uintptr_t>(
                circle_list_address + index * sizeof(uintptr_t),
                0);
            if (circle_address == 0 ||
                !memory.IsReadableRange(circle_address + kMovementCircleRadiusOffset, sizeof(float))) {
                continue;
            }

            const auto mask = memory.ReadFieldOr<std::uint32_t>(
                circle_address,
                kMovementCircleMaskOffset,
                0);
            if ((mask & GameplayPathStaticCircleObstacleMask()) == 0) {
                continue;
            }

            const auto radius = memory.ReadFieldOr<float>(
                circle_address,
                kMovementCircleRadiusOffset,
                -1.0f);
            if (!std::isfinite(radius) || radius < 0.0f) {
                continue;
            }
            const auto object_type = memory.ReadFieldOr<std::uint32_t>(
                circle_address,
                kMovementCircleObjectTypeOffset,
                0);

            const auto x = memory.ReadFieldOr<float>(circle_address, kMovementCircleXOffset, 0.0f);
            const auto y = memory.ReadFieldOr<float>(circle_address, kMovementCircleYOffset, 0.0f);
            if (!std::isfinite(x) || !std::isfinite(y)) {
                continue;
            }

            if (IsGameplayPathIgnoredStaticCircleObstacle(mask, object_type, radius)) {
                snapshot->ignored_circle_obstacles.push_back(GameplayPathCircleObstacle{x, y, radius, mask});
                continue;
            }

            snapshot->static_circle_obstacles.push_back(GameplayPathCircleObstacle{x, y, radius, mask});
        }
    }
    return true;
}
