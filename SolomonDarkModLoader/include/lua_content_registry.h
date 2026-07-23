#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace sdmod {

inline constexpr std::size_t kLuaContentMaximumIdentifierLength = 128;

enum class LuaContentKind : std::uint8_t {
    Spell,
    Enemy,
    Item,
};

struct LuaContentIdentity {
    std::uint64_t network_id = 0;
    LuaContentKind kind = LuaContentKind::Spell;
    std::string mod_id;
    std::string key;
};

const char* GetLuaContentKindName(LuaContentKind kind);
bool IsValidLuaContentIdentifier(std::string_view value);
std::uint64_t ComputeLuaContentNetworkId(
    std::string_view mod_id,
    std::string_view content_key);

bool RegisterLuaContentIdentity(
    LuaContentKind kind,
    std::string_view mod_id,
    std::string_view content_key,
    LuaContentIdentity* identity,
    std::string* error_message);
std::optional<LuaContentIdentity> FindLuaContentIdentity(std::uint64_t network_id);
std::size_t GetLuaContentIdentityCount();
void UnregisterLuaContentIdentitiesForMod(std::string_view mod_id);
void ResetLuaContentRegistry();

}  // namespace sdmod
