#include "lua_content_registry.h"

#include <array>
#include <map>
#include <mutex>
#include <string>
#include <utility>

namespace sdmod {
namespace {

constexpr std::uint64_t kFnv1aOffsetBasis = 14695981039346656037ull;
constexpr std::uint64_t kFnv1aPrime = 1099511628211ull;
constexpr std::uint64_t kLuaContentNamespaceBit = 0x4000000000000000ull;
constexpr std::uint64_t kLuaContentHashMask = 0x3FFFFFFFFFFFFFFFull;
constexpr std::array<std::uint8_t, 13> kLuaContentHashDomain = {
    's', 'd', '.', 'c', 'o', 'n', 't', 'e', 'n', 't', '.', 'v', '1',
};

std::mutex& RegistryMutex() {
    static std::mutex mutex;
    return mutex;
}

std::map<std::uint64_t, LuaContentIdentity>& Registry() {
    static std::map<std::uint64_t, LuaContentIdentity> registry;
    return registry;
}

void HashByte(std::uint8_t value, std::uint64_t* hash) {
    *hash ^= value;
    *hash *= kFnv1aPrime;
}

void HashLength(std::size_t value, std::uint64_t* hash) {
    const auto length = static_cast<std::uint32_t>(value);
    for (unsigned int shift = 0; shift < 32; shift += 8) {
        HashByte(static_cast<std::uint8_t>((length >> shift) & 0xFFu), hash);
    }
}

void HashText(std::string_view value, std::uint64_t* hash) {
    HashLength(value.size(), hash);
    for (const auto character : value) {
        HashByte(static_cast<std::uint8_t>(character), hash);
    }
}

void SetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

}  // namespace

const char* GetLuaContentKindName(LuaContentKind kind) {
    switch (kind) {
        case LuaContentKind::Spell:
            return "spell";
        case LuaContentKind::Enemy:
            return "enemy";
        case LuaContentKind::Item:
            return "item";
    }
    return "unknown";
}

bool IsValidLuaContentIdentifier(std::string_view value) {
    if (value.empty() || value.size() > kLuaContentMaximumIdentifierLength) {
        return false;
    }
    for (const auto character : value) {
        const bool lowercase = character >= 'a' && character <= 'z';
        const bool digit = character >= '0' && character <= '9';
        const bool separator =
            character == '.' || character == '_' || character == '-';
        if (!lowercase && !digit && !separator) {
            return false;
        }
    }
    return value.front() != '.' && value.front() != '_' && value.front() != '-' &&
           value.back() != '.' && value.back() != '_' && value.back() != '-';
}

std::uint64_t ComputeLuaContentNetworkId(
    std::string_view mod_id,
    std::string_view content_key) {
    if (!IsValidLuaContentIdentifier(mod_id) ||
        !IsValidLuaContentIdentifier(content_key)) {
        return 0;
    }

    std::uint64_t hash = kFnv1aOffsetBasis;
    for (const auto byte : kLuaContentHashDomain) {
        HashByte(byte, &hash);
    }
    HashText(mod_id, &hash);
    HashText(content_key, &hash);
    return (hash & kLuaContentHashMask) | kLuaContentNamespaceBit;
}

bool RegisterLuaContentIdentity(
    LuaContentKind kind,
    std::string_view mod_id,
    std::string_view content_key,
    LuaContentIdentity* identity,
    std::string* error_message) {
    if (identity == nullptr || error_message == nullptr) {
        return false;
    }
    *identity = LuaContentIdentity{};
    error_message->clear();

    if (!IsValidLuaContentIdentifier(mod_id)) {
        SetError(
            error_message,
            "invalid mod id for Lua content registration: " + std::string(mod_id));
        return false;
    }
    if (!IsValidLuaContentIdentifier(content_key)) {
        SetError(
            error_message,
            "invalid lowercase Lua content key: " + std::string(content_key));
        return false;
    }

    LuaContentIdentity candidate;
    candidate.network_id = ComputeLuaContentNetworkId(mod_id, content_key);
    candidate.kind = kind;
    candidate.mod_id = mod_id;
    candidate.key = content_key;

    std::scoped_lock lock(RegistryMutex());
    auto& registry = Registry();
    const auto existing = registry.find(candidate.network_id);
    if (existing != registry.end()) {
        if (existing->second.mod_id == candidate.mod_id &&
            existing->second.key == candidate.key) {
            if (existing->second.kind == candidate.kind) {
                SetError(
                    error_message,
                    "duplicate Lua " + std::string(GetLuaContentKindName(kind)) +
                        " content key: " + candidate.mod_id + ":" + candidate.key);
            } else {
                SetError(
                    error_message,
                    "Lua content key is already registered as " +
                        std::string(GetLuaContentKindName(existing->second.kind)) + ": " +
                        candidate.mod_id + ":" + candidate.key);
            }
        } else {
            SetError(
                error_message,
                "Lua content network ID collision between " + existing->second.mod_id + ":" +
                    existing->second.key + " and " + candidate.mod_id + ":" + candidate.key);
        }
        return false;
    }

    const auto inserted = registry.emplace(candidate.network_id, std::move(candidate));
    *identity = inserted.first->second;
    return true;
}

std::optional<LuaContentIdentity> FindLuaContentIdentity(std::uint64_t network_id) {
    std::scoped_lock lock(RegistryMutex());
    const auto& registry = Registry();
    const auto found = registry.find(network_id);
    if (found == registry.end()) {
        return std::nullopt;
    }
    return found->second;
}

std::size_t GetLuaContentIdentityCount() {
    std::scoped_lock lock(RegistryMutex());
    return Registry().size();
}

void UnregisterLuaContentIdentitiesForMod(std::string_view mod_id) {
    std::scoped_lock lock(RegistryMutex());
    auto& registry = Registry();
    for (auto iterator = registry.begin(); iterator != registry.end();) {
        if (iterator->second.mod_id == mod_id) {
            iterator = registry.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void ResetLuaContentRegistry() {
    std::scoped_lock lock(RegistryMutex());
    Registry().clear();
}

}  // namespace sdmod
