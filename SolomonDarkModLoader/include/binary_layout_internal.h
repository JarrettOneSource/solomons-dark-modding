#pragma once

#include "binary_layout.h"

#include <map>
#include <mutex>
#include <string>

namespace sdmod {

using BinaryLayoutProperties = std::map<std::string, std::string>;
using BinaryLayoutSectionMap = std::map<std::string, BinaryLayoutProperties>;

struct BinaryLayoutState {
    std::mutex mutex;
    bool loaded = false;
    BinaryLayout layout;
    std::string last_error;
};

BinaryLayoutState& GetBinaryLayoutState();

bool LoadBinaryLayoutFromDisk(
    const std::filesystem::path& path,
    BinaryLayout* layout,
    std::string* error_message);

bool ValidateBinaryLayout(const BinaryLayout& layout, std::string* error_message);

}  // namespace sdmod
