#pragma once

#include <cstdint>

namespace sdmod {

inline constexpr std::int32_t kDemonSkullNativeTypeId = 0x3F0;
inline constexpr std::int32_t kDemonNativeTypeId = 0x3F1;
inline constexpr std::int32_t kDireFacultyNativeTypeId = 0x3F2;
inline constexpr std::int32_t kHeartmongerNativeTypeId = 0x3F3;

inline bool IsStockBossEnemyNativeType(std::int32_t native_type_id) {
    return native_type_id == kDemonSkullNativeTypeId ||
        native_type_id == kDemonNativeTypeId ||
        native_type_id == kDireFacultyNativeTypeId ||
        native_type_id == kHeartmongerNativeTypeId;
}

}  // namespace sdmod
