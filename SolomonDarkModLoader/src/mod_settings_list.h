#pragma once

#include "mod_settings.h"
#include "mod_settings_json.h"

#include <string>
#include <string_view>

namespace sdmod::detail {

bool ParseListModSettingEntry(
    const settings_json::Value& object,
    std::string_view label,
    ModSettingEntry* entry,
    std::string* error);

bool ConvertJsonModSettingValue(
    const ModSettingEntry& entry,
    const settings_json::Value& source,
    ModSettingValue* value,
    std::string* error);

}  // namespace sdmod::detail
