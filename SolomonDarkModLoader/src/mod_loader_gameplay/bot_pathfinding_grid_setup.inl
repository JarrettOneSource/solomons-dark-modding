#include <cfloat>

struct GameplayPathGridSnapshot {
    uintptr_t controller_address = 0;
    uintptr_t cells_address = 0;
    int width = 0;
    int height = 0;
    float cell_width = 0.0f;
    float cell_height = 0.0f;
};

constexpr int kGameplayPathCellPlacementSampleResolution = 5;

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
    std::uint32_t cell_mask,
    std::uint32_t object_mask,
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
            cell_mask,
            object_mask);
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
    const auto cells_address = memory.ReadFieldOr<uintptr_t>(controller_address, 0xB4, 0);
    const auto grid_height = static_cast<int>(memory.ReadFieldOr<std::uint32_t>(controller_address, 0xD8, 0));
    const auto grid_width = static_cast<int>(memory.ReadFieldOr<std::uint32_t>(controller_address, 0xDC, 0));
    const auto cell_width = memory.ReadFieldOr<float>(controller_address, 0xE0, 0.0f);
    const auto cell_height = memory.ReadFieldOr<float>(controller_address, 0xE4, 0.0f);
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
    return true;
}
