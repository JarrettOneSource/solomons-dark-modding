#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace sdmod {

inline constexpr std::size_t kLuaModMaxIdentifierBytes = 128;
inline constexpr std::size_t kLuaModMaxKeyBytes = 128;
inline constexpr std::size_t kLuaModMaxStringBytes = 16 * 1024;
inline constexpr std::size_t kLuaModMaxValueBytes = 32 * 1024;
inline constexpr std::size_t kLuaModMaxEventPayloadBytes = 32 * 1024;
inline constexpr std::size_t kLuaModMaxStateSnapshotBytes = 64 * 1024;
inline constexpr std::size_t kLuaModMaxValueDepth = 16;
inline constexpr std::size_t kLuaModMaxValueNodes = 2048;

enum class LuaModValueType : std::uint8_t {
    Nil = 0,
    Boolean = 1,
    Integer = 2,
    Number = 3,
    String = 4,
    Array = 5,
    Object = 6,
};

struct LuaModValue {
    LuaModValueType type = LuaModValueType::Nil;
    bool boolean_value = false;
    std::int64_t integer_value = 0;
    double number_value = 0.0;
    std::string string_value;
    std::vector<LuaModValue> array_value;
    std::map<std::string, LuaModValue, std::less<>> object_value;
};

using LuaModStateValues =
    std::map<std::string, LuaModValue, std::less<>>;
using LuaModStateSnapshot =
    std::map<std::string, LuaModStateValues, std::less<>>;

bool IsValidLuaModIdentifier(const std::string& value);
bool IsValidLuaModStateKey(const std::string& value);

bool EncodeLuaModValue(
    const LuaModValue& value,
    std::vector<std::uint8_t>* encoded,
    std::string* error_message);
bool DecodeLuaModValue(
    const std::uint8_t* encoded,
    std::size_t encoded_size,
    LuaModValue* value,
    std::string* error_message);

bool EncodeLuaModStateSnapshot(
    const LuaModStateSnapshot& snapshot,
    std::vector<std::uint8_t>* encoded,
    std::string* error_message);
bool DecodeLuaModStateSnapshot(
    const std::uint8_t* encoded,
    std::size_t encoded_size,
    LuaModStateSnapshot* snapshot,
    std::string* error_message);

void ResetLuaModStateStore();
std::uint64_t GetLuaModStateRevision();
LuaModStateSnapshot SnapshotLuaModState();
LuaModStateSnapshot SnapshotLuaModState(std::uint64_t* revision);
bool TryGetLuaModStateValue(
    const std::string& mod_id,
    const std::string& key,
    LuaModValue* value);
bool SetLuaModStateValue(
    const std::string& mod_id,
    const std::string& key,
    LuaModValue value,
    std::uint64_t* revision,
    std::string* error_message);
bool DeleteLuaModStateValue(
    const std::string& mod_id,
    const std::string& key,
    bool* deleted,
    std::uint64_t* revision,
    std::string* error_message);
bool ClearLuaModStateValues(
    const std::string& mod_id,
    bool* cleared,
    std::uint64_t* revision,
    std::string* error_message);

bool ApplyReplicatedLuaModStateSet(
    const std::string& mod_id,
    const std::string& key,
    LuaModValue value,
    std::uint64_t revision,
    std::string* error_message);
bool ApplyReplicatedLuaModStateDelete(
    const std::string& mod_id,
    const std::string& key,
    std::uint64_t revision,
    std::string* error_message);
bool ApplyReplicatedLuaModStateClear(
    const std::string& mod_id,
    std::uint64_t revision,
    std::string* error_message);
bool ApplyReplicatedLuaModStateSnapshot(
    LuaModStateSnapshot snapshot,
    std::uint64_t revision,
    std::string* error_message);

}  // namespace sdmod
