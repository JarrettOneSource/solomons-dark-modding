#include "lobby_access.h"

#include <Windows.h>
#include <bcrypt.h>

#include <array>
#include <charconv>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#pragma comment(lib, "bcrypt.lib")

namespace sdmod::multiplayer {
namespace {

constexpr std::uint64_t kClockSkewSeconds = 30;
constexpr std::uint64_t kMaximumFutureLifetimeSeconds = 5 * 60;

int HexNibble(char character) {
    if (character >= '0' && character <= '9') {
        return character - '0';
    }
    if (character >= 'a' && character <= 'f') {
        return 10 + character - 'a';
    }
    return -1;
}

bool DecodeHex(std::string_view text, std::vector<std::uint8_t>* bytes) {
    if (bytes == nullptr || text.empty() || text.size() % 2 != 0) {
        return false;
    }
    bytes->resize(text.size() / 2);
    for (std::size_t index = 0; index < bytes->size(); ++index) {
        const int high = HexNibble(text[index * 2]);
        const int low = HexNibble(text[index * 2 + 1]);
        if (high < 0 || low < 0) {
            bytes->clear();
            return false;
        }
        (*bytes)[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

bool ParseUnsigned64(std::string_view text, std::uint64_t* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }
    const auto result = std::from_chars(
        text.data(),
        text.data() + text.size(),
        *value,
        10);
    return result.ec == std::errc{} && result.ptr == text.data() + text.size();
}

bool SplitTicket(
    const std::string& ticket,
    std::array<std::string_view, 5>* parts) {
    if (parts == nullptr) {
        return false;
    }
    std::size_t start = 0;
    for (std::size_t index = 0; index < parts->size(); ++index) {
        const auto separator = ticket.find('.', start);
        if (index + 1 == parts->size()) {
            if (separator != std::string::npos) {
                return false;
            }
            (*parts)[index] = std::string_view(ticket).substr(start);
            return !(*parts)[index].empty();
        }
        if (separator == std::string::npos || separator == start) {
            return false;
        }
        (*parts)[index] = std::string_view(ticket).substr(start, separator - start);
        start = separator + 1;
    }
    return false;
}

bool ComputeHmacSha256(
    const std::vector<std::uint8_t>& key,
    std::string_view payload,
    std::array<std::uint8_t, 32>* digest) {
    if (key.empty() || digest == nullptr) {
        return false;
    }
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    std::vector<std::uint8_t> hash_object;
    bool success = false;
    do {
        if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(
                &algorithm,
                BCRYPT_SHA256_ALGORITHM,
                nullptr,
                BCRYPT_ALG_HANDLE_HMAC_FLAG))) {
            break;
        }
        ULONG object_size = 0;
        ULONG copied = 0;
        if (!BCRYPT_SUCCESS(BCryptGetProperty(
                algorithm,
                BCRYPT_OBJECT_LENGTH,
                reinterpret_cast<PUCHAR>(&object_size),
                sizeof(object_size),
                &copied,
                0))) {
            break;
        }
        hash_object.resize(object_size);
        if (!BCRYPT_SUCCESS(BCryptCreateHash(
                algorithm,
                &hash,
                hash_object.data(),
                static_cast<ULONG>(hash_object.size()),
                const_cast<PUCHAR>(key.data()),
                static_cast<ULONG>(key.size()),
                0))) {
            break;
        }
        if (!BCRYPT_SUCCESS(BCryptHashData(
                hash,
                reinterpret_cast<PUCHAR>(const_cast<char*>(payload.data())),
                static_cast<ULONG>(payload.size()),
                0))) {
            break;
        }
        success = BCRYPT_SUCCESS(BCryptFinishHash(
            hash,
            digest->data(),
            static_cast<ULONG>(digest->size()),
            0));
    } while (false);

    if (hash != nullptr) {
        BCryptDestroyHash(hash);
    }
    if (algorithm != nullptr) {
        BCryptCloseAlgorithmProvider(algorithm, 0);
    }
    return success;
}

bool FixedTimeEquals(
    const std::array<std::uint8_t, 32>& expected,
    const std::vector<std::uint8_t>& actual) {
    if (actual.size() != expected.size()) {
        return false;
    }
    std::uint8_t difference = 0;
    for (std::size_t index = 0; index < expected.size(); ++index) {
        difference |= expected[index] ^ actual[index];
    }
    return difference == 0;
}

}  // namespace

bool ValidatePasswordLobbyJoinTicket(
    const std::string& secret_hex,
    const std::string& ticket,
    std::uint64_t lobby_id,
    std::uint64_t steam_id,
    std::uint64_t now_unix_seconds) {
    if (lobby_id == 0 || steam_id == 0 || ticket.size() > 159) {
        return false;
    }
    std::array<std::string_view, 5> parts{};
    if (!SplitTicket(ticket, &parts) || parts[0] != "v1") {
        return false;
    }
    std::uint64_t expires_at = 0;
    std::uint64_t ticket_steam_id = 0;
    if (!ParseUnsigned64(parts[1], &expires_at) ||
        !ParseUnsigned64(parts[2], &ticket_steam_id) ||
        ticket_steam_id != steam_id ||
        parts[3].size() != 32 ||
        parts[4].size() != 64 ||
        expires_at + kClockSkewSeconds < now_unix_seconds ||
        expires_at > now_unix_seconds + kMaximumFutureLifetimeSeconds) {
        return false;
    }

    std::vector<std::uint8_t> key;
    std::vector<std::uint8_t> provided_digest;
    if (secret_hex.size() != 64 ||
        !DecodeHex(secret_hex, &key) ||
        !DecodeHex(parts[4], &provided_digest)) {
        return false;
    }
    const auto payload =
        std::string(parts[0]) + '\n' +
        std::to_string(lobby_id) + '\n' +
        std::string(parts[2]) + '\n' +
        std::string(parts[1]) + '\n' +
        std::string(parts[3]);
    std::array<std::uint8_t, 32> expected_digest{};
    return ComputeHmacSha256(key, payload, &expected_digest) &&
           FixedTimeEquals(expected_digest, provided_digest);
}

}  // namespace sdmod::multiplayer
