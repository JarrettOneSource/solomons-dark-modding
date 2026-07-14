#include "steam_bootstrap.h"

#include "steam_bootstrap_internal.h"

#include <algorithm>
#include <limits>
#include <mutex>
#include <string>
#include <vector>

namespace sdmod {
namespace {

constexpr std::size_t kMaxSteamMessageBytes = 512 * 1024;
constexpr std::int32_t kMaxReceiveBatch = 64;
constexpr std::int32_t kMaxLobbyMemberRead = 250;

bool IsReady(const detail::SteamBootstrapState& state) {
    return state.initialized && state.snapshot.transport_interfaces_ready;
}

void* Friends(detail::SteamBootstrapState& state) {
    return IsReady(state) ? state.steam_friends_v017() : nullptr;
}

void* Matchmaking(detail::SteamBootstrapState& state) {
    return IsReady(state) ? state.steam_matchmaking_v009() : nullptr;
}

void* NetworkingMessages(detail::SteamBootstrapState& state) {
    return IsReady(state) ? state.steam_networking_messages_v002() : nullptr;
}

bool BuildIdentity(
    detail::SteamBootstrapState& state,
    std::uint64_t steam_id,
    steamabi::NetworkingIdentity* identity) {
    if (!IsReady(state) || steam_id == 0 || identity == nullptr) {
        return false;
    }
    state.identity_clear(identity);
    state.identity_set_steam_id64(identity, steam_id);
    return state.identity_get_steam_id64(identity) == steam_id;
}

std::string CopySteamString(const char* text) {
    return text != nullptr ? std::string(text) : std::string{};
}

std::string CopyBoundedText(const char* text, std::size_t capacity) {
    if (text == nullptr || capacity == 0) {
        return {};
    }
    std::size_t length = 0;
    while (length < capacity && text[length] != '\0') {
        ++length;
    }
    return std::string(text, length);
}

}  // namespace

std::uint64_t SteamCreateFriendsOnlyLobby(std::int32_t max_members) {
    if (max_members < 2) {
        return 0;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr
        ? state.matchmaking_create_lobby(
              matchmaking,
              steamabi::kLobbyTypeFriendsOnly,
              max_members)
        : 0;
}

std::uint64_t SteamJoinLobby(std::uint64_t lobby_id) {
    if (lobby_id == 0) {
        return 0;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr
        ? state.matchmaking_join_lobby(matchmaking, lobby_id)
        : 0;
}

void SteamLeaveLobby(std::uint64_t lobby_id) {
    if (lobby_id == 0) {
        return;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    if (auto* matchmaking = Matchmaking(state); matchmaking != nullptr) {
        state.matchmaking_leave_lobby(matchmaking, lobby_id);
    }
}

bool SteamRequestLobbyData(std::uint64_t lobby_id) {
    if (lobby_id == 0) {
        return false;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr &&
           state.matchmaking_request_lobby_data(matchmaking, lobby_id);
}

bool SteamSetLobbyJoinable(std::uint64_t lobby_id, bool joinable) {
    if (lobby_id == 0) {
        return false;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr &&
           state.matchmaking_set_lobby_joinable(matchmaking, lobby_id, joinable);
}

bool SteamInviteUserToLobby(std::uint64_t lobby_id, std::uint64_t steam_id) {
    if (lobby_id == 0 || steam_id == 0) {
        return false;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr &&
           state.matchmaking_invite_user_to_lobby(matchmaking, lobby_id, steam_id);
}

bool SteamSetLobbyData(std::uint64_t lobby_id, const char* key, const char* value) {
    if (lobby_id == 0 || key == nullptr || *key == '\0' || value == nullptr) {
        return false;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr &&
           state.matchmaking_set_lobby_data(matchmaking, lobby_id, key, value);
}

std::string SteamGetLobbyData(std::uint64_t lobby_id, const char* key) {
    if (lobby_id == 0 || key == nullptr || *key == '\0') {
        return {};
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr
        ? CopySteamString(state.matchmaking_get_lobby_data(matchmaking, lobby_id, key))
        : std::string{};
}

void SteamSetLobbyMemberData(
    std::uint64_t lobby_id,
    const char* key,
    const char* value) {
    if (lobby_id == 0 || key == nullptr || *key == '\0' || value == nullptr) {
        return;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    if (auto* matchmaking = Matchmaking(state); matchmaking != nullptr) {
        state.matchmaking_set_lobby_member_data(matchmaking, lobby_id, key, value);
    }
}

std::string SteamGetLobbyMemberData(
    std::uint64_t lobby_id,
    std::uint64_t member_id,
    const char* key) {
    if (lobby_id == 0 || member_id == 0 || key == nullptr || *key == '\0') {
        return {};
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr
        ? CopySteamString(
              state.matchmaking_get_lobby_member_data(
                  matchmaking,
                  lobby_id,
                  member_id,
                  key))
        : std::string{};
}

std::uint64_t SteamGetLobbyOwner(std::uint64_t lobby_id) {
    if (lobby_id == 0) {
        return 0;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    return matchmaking != nullptr
        ? state.matchmaking_get_lobby_owner(matchmaking, lobby_id)
        : 0;
}

std::vector<std::uint64_t> SteamGetLobbyMembers(std::uint64_t lobby_id) {
    std::vector<std::uint64_t> members;
    if (lobby_id == 0) {
        return members;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* matchmaking = Matchmaking(state);
    if (matchmaking == nullptr) {
        return members;
    }
    const int count = (std::clamp)(
        state.matchmaking_get_num_lobby_members(matchmaking, lobby_id),
        0,
        kMaxLobbyMemberRead);
    members.reserve(static_cast<std::size_t>(count));
    for (int index = 0; index < count; ++index) {
        const auto member_id =
            state.matchmaking_get_lobby_member_by_index(matchmaking, lobby_id, index);
        if (member_id != 0 &&
            std::find(members.begin(), members.end(), member_id) == members.end()) {
            members.push_back(member_id);
        }
    }
    return members;
}

void SteamOpenLobbyInviteDialog(std::uint64_t lobby_id) {
    if (lobby_id == 0) {
        return;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    if (auto* friends = Friends(state); friends != nullptr) {
        state.friends_activate_game_overlay_invite_dialog(friends, lobby_id);
    }
}

bool SteamIsOverlayEnabled() {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* utils = state.initialized && state.steam_utils_v010 != nullptr
        ? state.steam_utils_v010()
        : nullptr;
    const bool enabled = utils != nullptr &&
        state.utils_is_overlay_enabled != nullptr &&
        state.utils_is_overlay_enabled(utils);
    state.snapshot.overlay_enabled = enabled;
    return enabled;
}

bool SteamSetRichPresence(const char* key, const char* value) {
    if (key == nullptr || *key == '\0') {
        return false;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* friends = Friends(state);
    return friends != nullptr && state.friends_set_rich_presence(friends, key, value);
}

std::string SteamGetFriendPersonaName(std::uint64_t steam_id) {
    if (steam_id == 0) {
        return {};
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* friends = Friends(state);
    return friends != nullptr
        ? CopySteamString(state.friends_get_friend_persona_name(friends, steam_id))
        : std::string{};
}

bool SteamSendNetworkMessage(
    std::uint64_t remote_steam_id,
    const void* data,
    std::size_t size,
    SteamNetworkSendMode mode,
    std::int32_t* result_code) {
    if (result_code != nullptr) {
        *result_code = 0;
    }
    if (data == nullptr || size == 0 || size > kMaxSteamMessageBytes ||
        size > (std::numeric_limits<std::uint32_t>::max)()) {
        return false;
    }
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* networking = NetworkingMessages(state);
    steamabi::NetworkingIdentity identity{};
    if (networking == nullptr || !BuildIdentity(state, remote_steam_id, &identity)) {
        return false;
    }
    int flags = steamabi::kNetworkingSendUnreliableNoNagle;
    if (mode == SteamNetworkSendMode::UnreliableNoDelay) {
        flags = steamabi::kNetworkingSendUnreliableNoDelay;
    } else if (mode == SteamNetworkSendMode::ReliableNoNagle) {
        flags = steamabi::kNetworkingSendReliableNoNagle;
    }
    const auto result = state.networking_messages_send(
        networking,
        &identity,
        data,
        static_cast<std::uint32_t>(size),
        flags,
        0);
    if (result_code != nullptr) {
        *result_code = result;
    }
    return result == steamabi::kResultOk;
}

std::vector<SteamNetworkMessage> SteamReceiveNetworkMessages(
    std::int32_t channel,
    std::int32_t max_messages) {
    std::vector<SteamNetworkMessage> messages;
    const int requested = (std::clamp)(max_messages, 1, kMaxReceiveBatch);
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* networking = NetworkingMessages(state);
    if (networking == nullptr) {
        return messages;
    }

    std::vector<steamabi::NetworkingMessage*> received(
        static_cast<std::size_t>(requested),
        nullptr);
    const int count = (std::clamp)(
        state.networking_messages_receive(
            networking,
            channel,
            received.data(),
            requested),
        0,
        requested);
    messages.reserve(static_cast<std::size_t>(count));
    for (int index = 0; index < count; ++index) {
        auto* source = received[static_cast<std::size_t>(index)];
        if (source == nullptr) {
            continue;
        }
        if (source->data != nullptr && source->size > 0 &&
            static_cast<std::size_t>(source->size) <= kMaxSteamMessageBytes) {
            SteamNetworkMessage message;
            message.sender_steam_id = state.identity_get_steam_id64(&source->peer_identity);
            message.reliable =
                (source->flags & steamabi::kNetworkingSendReliable) != 0;
            const auto* begin = static_cast<const std::uint8_t*>(source->data);
            message.payload.assign(begin, begin + source->size);
            if (message.sender_steam_id != 0) {
                messages.push_back(std::move(message));
            }
        }
        state.networking_message_release(source);
    }
    return messages;
}

bool SteamAcceptNetworkSession(std::uint64_t remote_steam_id) {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* networking = NetworkingMessages(state);
    steamabi::NetworkingIdentity identity{};
    return networking != nullptr && BuildIdentity(state, remote_steam_id, &identity) &&
           state.networking_messages_accept(networking, &identity);
}

bool SteamCloseNetworkSession(std::uint64_t remote_steam_id) {
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* networking = NetworkingMessages(state);
    steamabi::NetworkingIdentity identity{};
    return networking != nullptr && BuildIdentity(state, remote_steam_id, &identity) &&
           state.networking_messages_close(networking, &identity);
}

SteamPeerNetworkStatus SteamGetNetworkSessionStatus(std::uint64_t remote_steam_id) {
    SteamPeerNetworkStatus status;
    status.steam_id = remote_steam_id;
    std::scoped_lock lock(detail::SteamBootstrapMutex());
    auto& state = detail::MutableSteamBootstrapState();
    auto* networking = NetworkingMessages(state);
    steamabi::NetworkingIdentity identity{};
    if (networking == nullptr || !BuildIdentity(state, remote_steam_id, &identity)) {
        return status;
    }
    steamabi::NetworkConnectionInfo info{};
    steamabi::NetworkRealtimeStatus realtime{};
    status.connection_state = state.networking_messages_get_session_info(
        networking,
        &identity,
        &info,
        &realtime);
    status.end_reason = info.end_reason;
    status.ping_ms = realtime.ping_ms;
    status.pending_reliable_bytes = realtime.pending_reliable_bytes;
    status.using_relay = (info.flags & steamabi::kNetworkConnectionInfoRelayed) != 0;
    status.debug_text = CopyBoundedText(info.end_debug, sizeof(info.end_debug));
    status.connection_description =
        CopyBoundedText(info.connection_description, sizeof(info.connection_description));
    return status;
}

}  // namespace sdmod
