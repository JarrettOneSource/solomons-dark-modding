#pragma once

#include <cstdint>
#include <string>

namespace sdmod::multiplayer {

bool ValidatePasswordLobbyJoinTicket(
    const std::string& secret_hex,
    const std::string& ticket,
    std::uint64_t lobby_id,
    std::uint64_t steam_id,
    std::uint64_t now_unix_seconds);

}  // namespace sdmod::multiplayer
