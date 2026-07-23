constexpr const char* kTransportEnvironmentVariable = "SDMOD_MULTIPLAYER_TRANSPORT";
constexpr const char* kRoleEnvironmentVariable = "SDMOD_MULTIPLAYER_ROLE";
constexpr const char* kSessionModeEnvironmentVariable = "SDMOD_STEAM_SESSION_MODE";
constexpr const char* kLobbyIdEnvironmentVariable = "SDMOD_STEAM_LOBBY_ID";
constexpr const char* kManifestEnvironmentVariable = "SDMOD_MULTIPLAYER_MANIFEST_SHA256";
constexpr const char* kMaxParticipantsEnvironmentVariable = "SDMOD_MULTIPLAYER_MAX_PARTICIPANTS";
constexpr const char* kOpenInviteEnvironmentVariable = "SDMOD_STEAM_OPEN_INVITE";
constexpr const char* kInviteSteamIdEnvironmentVariable = "SDMOD_STEAM_INVITE_STEAM_ID";
constexpr const char* kLobbyPrivacyEnvironmentVariable = "SDMOD_STEAM_LOBBY_PRIVACY";
constexpr const char* kLaunchTokenEnvironmentVariable = "SDMOD_LAUNCH_TOKEN";

constexpr const char* kLobbyProtocolKey = "sdmod_protocol";
constexpr const char* kLobbyManifestKey = "sdmod_manifest";
constexpr const char* kLobbyHostKey = "sdmod_host";
constexpr const char* kLobbyAppIdKey = "sdmod_app_id";
constexpr const char* kLobbyMaxParticipantsKey = "sdmod_max_players";
constexpr const char* kLobbyStateKey = "sdmod_state";
constexpr const char* kLobbyPrivacyKey = "sdmod_privacy";
constexpr const char* kLobbyStateOpen = "open";
constexpr const char* kLobbyStateClosed = "closed";
constexpr const char* kMemberProtocolKey = "sdmod_protocol";
constexpr const char* kMemberManifestKey = "sdmod_manifest";

constexpr std::uint32_t kDefaultMaxParticipants = 4;
constexpr std::uint32_t kMaximumSupportedParticipants = 4;
constexpr std::uint64_t kHelloRetryIntervalMs = 1000;
constexpr std::uint64_t kKeepaliveIntervalMs = 2000;
constexpr std::uint64_t kAuthenticatedPeerTimeoutMs = 30000;
constexpr std::uint64_t kLobbyReconcileIntervalMs = 500;
constexpr std::uint64_t kRouteStatusIntervalMs = 1000;
constexpr std::uint64_t kSessionStatusWriteIntervalMs = 1000;
constexpr std::uint64_t kFriendListRefreshIntervalMs = 5000;
constexpr std::uint64_t kClientLobbyRecoveryRetryMs = 3000;
constexpr std::uint64_t kClientLobbyRecoveryTimeoutMs = 120000;
constexpr std::int32_t kReceiveBatchSize = 64;

enum class SteamSessionPhase {
    Disabled,
    WaitingForInvite,
    CreatingLobby,
    JoiningLobby,
    Reconnecting,
    Handshaking,
    LobbyReady,
    Connected,
    Error,
};

const char* SteamSessionPhaseLabel(SteamSessionPhase phase) {
    switch (phase) {
    case SteamSessionPhase::WaitingForInvite:
        return "WaitingForInvite";
    case SteamSessionPhase::CreatingLobby:
        return "CreatingLobby";
    case SteamSessionPhase::JoiningLobby:
        return "JoiningLobby";
    case SteamSessionPhase::Reconnecting:
        return "Reconnecting";
    case SteamSessionPhase::Handshaking:
        return "Handshaking";
    case SteamSessionPhase::LobbyReady:
        return "LobbyReady";
    case SteamSessionPhase::Connected:
        return "Connected";
    case SteamSessionPhase::Error:
        return "Error";
    case SteamSessionPhase::Disabled:
    default:
        return "Disabled";
    }
}

struct SteamSessionPeer {
    std::uint64_t steam_id = 0;
    std::uint64_t session_nonce = 0;
    std::uint64_t last_packet_ms = 0;
    bool authenticated = false;
    bool rejected = false;
    std::string display_name;
    SteamPeerNetworkStatus network_status;
};

struct SteamSessionState {
    bool configured = false;
    bool initialized = false;
    bool is_host = false;
    bool open_invite_dialog = true;
    bool invite_fallback_logged = false;
    bool invite_dialog_opened = false;
    bool invite_sent = false;
    bool overlay_enabled = false;
    bool steam_servers_connected = true;
    bool client_lobby_recovery = false;
    SteamLobbyVisibility lobby_visibility = SteamLobbyVisibility::FriendsOnly;
    SteamSessionPhase phase = SteamSessionPhase::Disabled;
    std::uint32_t app_id = 0;
    std::uint32_t max_participants = kDefaultMaxParticipants;
    std::uint32_t next_sequence = 1;
    std::uint64_t local_steam_id = 0;
    std::uint64_t lobby_id = 0;
    std::uint64_t desired_lobby_id = 0;
    std::uint64_t host_steam_id = 0;
    std::uint64_t invite_steam_id = 0;
    std::uint64_t pending_api_call = 0;
    std::uint64_t recovery_lobby_id = 0;
    std::uint64_t recovery_started_ms = 0;
    std::uint64_t last_join_attempt_ms = 0;
    std::uint64_t local_session_nonce = 0;
    std::uint64_t last_hello_send_ms = 0;
    std::uint64_t last_keepalive_send_ms = 0;
    std::uint64_t last_keepalive_send_success_ms = 0;
    std::int32_t last_keepalive_send_result = 0;
    std::uint64_t last_lobby_reconcile_ms = 0;
    std::uint64_t last_route_status_ms = 0;
    std::uint64_t last_status_write_ms = 0;
    std::uint64_t last_friend_list_refresh_ms = 0;
    std::array<std::uint8_t, 32> manifest_sha256{};
    std::string manifest_sha256_text;
    std::string privacy = "friendsOnly";
    std::string launch_token;
    std::string last_status_signature;
    std::string error_text;
    std::unordered_set<std::uint64_t> lobby_members;
    std::unordered_map<std::uint64_t, SteamSessionPeer> peers;
    std::vector<std::uint64_t> immediate_friend_ids;
};

SteamSessionState g_session;

void RemoveAllPeers();

std::string ReadEnvironmentVariable(const char* name) {
    char* value = nullptr;
    std::size_t value_length = 0;
    if (_dupenv_s(&value, &value_length, name) != 0 || value == nullptr) {
        return {};
    }
    std::string result(value);
    std::free(value);
    return result;
}

std::string TrimAscii(std::string value) {
    const auto is_space = [](unsigned char ch) { return std::isspace(ch) != 0; };
    while (!value.empty() && is_space(static_cast<unsigned char>(value.front()))) {
        value.erase(value.begin());
    }
    while (!value.empty() && is_space(static_cast<unsigned char>(value.back()))) {
        value.pop_back();
    }
    return value;
}

std::string ToLowerAscii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool ReadBooleanEnvironmentVariable(const char* name, bool default_value) {
    const auto value = ToLowerAscii(TrimAscii(ReadEnvironmentVariable(name)));
    if (value.empty()) {
        return default_value;
    }
    if (value == "1" || value == "true" || value == "yes" || value == "on") {
        return true;
    }
    if (value == "0" || value == "false" || value == "no" || value == "off") {
        return false;
    }
    return default_value;
}

SteamLobbyVisibility ReadLobbyVisibility() {
    const auto value = ToLowerAscii(TrimAscii(
        ReadEnvironmentVariable(kLobbyPrivacyEnvironmentVariable)));
    return value == "public"
        ? SteamLobbyVisibility::Public
        : SteamLobbyVisibility::FriendsOnly;
}

const char* LobbyPrivacyToken(SteamLobbyVisibility visibility) {
    return visibility == SteamLobbyVisibility::Public
        ? "public"
        : "friendsOnly";
}

bool TryParseUnsigned64(const std::string& text, std::uint64_t* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }
    std::uint64_t parsed = 0;
    const auto result = std::from_chars(
        text.data(),
        text.data() + text.size(),
        parsed,
        10);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size()) {
        return false;
    }
    *value = parsed;
    return true;
}

bool TryParseLobbyIdFromConnectString(
    const std::string& connect_string,
    std::uint64_t* lobby_id) {
    std::istringstream stream(connect_string);
    std::string command;
    std::string lobby_text;
    std::string trailing;
    return (stream >> command >> lobby_text) &&
           !(stream >> trailing) &&
           command == "+connect_lobby" &&
           TryParseUnsigned64(lobby_text, lobby_id) &&
           *lobby_id != 0;
}

std::uint32_t ReadMaxParticipants() {
    std::uint64_t parsed = 0;
    if (!TryParseUnsigned64(
            TrimAscii(ReadEnvironmentVariable(kMaxParticipantsEnvironmentVariable)),
            &parsed)) {
        return kDefaultMaxParticipants;
    }
    return static_cast<std::uint32_t>((std::clamp<std::uint64_t>)(
        parsed,
        2,
        kMaximumSupportedParticipants));
}

int HexNibble(char ch) {
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'a' && ch <= 'f') {
        return 10 + ch - 'a';
    }
    if (ch >= 'A' && ch <= 'F') {
        return 10 + ch - 'A';
    }
    return -1;
}

bool ParseSha256(
    const std::string& text,
    std::array<std::uint8_t, 32>* digest) {
    if (digest == nullptr || text.size() != digest->size() * 2) {
        return false;
    }
    for (std::size_t index = 0; index < digest->size(); ++index) {
        const int high = HexNibble(text[index * 2]);
        const int low = HexNibble(text[index * 2 + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        (*digest)[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

std::uint64_t ParseCommandLineLobbyId() {
    int argument_count = 0;
    auto** arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    if (arguments == nullptr) {
        return 0;
    }
    std::uint64_t lobby_id = 0;
    for (int index = 0; index + 1 < argument_count; ++index) {
        if (_wcsicmp(arguments[index], L"+connect_lobby") != 0) {
            continue;
        }
        const auto* first = arguments[index + 1];
        const auto* last = first + wcslen(first);
        wchar_t* end = nullptr;
        lobby_id = _wcstoui64(first, &end, 10);
        if (lobby_id != 0 && end == last) {
            break;
        }
        lobby_id = 0;
    }
    LocalFree(arguments);
    return lobby_id;
}

std::uint64_t GenerateSessionNonce() {
    std::random_device random;
    std::uint64_t nonce =
        (static_cast<std::uint64_t>(random()) << 32) ^
        static_cast<std::uint64_t>(random()) ^
        GetTickCount64() ^
        (g_session.local_steam_id << 1);
    return nonce != 0 ? nonce : 1;
}

bool HasProtocolMagic(const PacketHeader& header) {
    return header.magic[0] == kProtocolMagic[0] &&
           header.magic[1] == kProtocolMagic[1] &&
           header.magic[2] == kProtocolMagic[2] &&
           header.magic[3] == kProtocolMagic[3];
}

template <typename Packet>
bool CopyNetworkPacket(const SteamNetworkMessage& message, Packet* packet) {
    if (packet == nullptr || message.payload.size() != sizeof(Packet)) {
        return false;
    }
    std::memcpy(packet, message.payload.data(), sizeof(Packet));
    return true;
}

std::string PacketDisplayName(const char* name, std::size_t capacity) {
    std::size_t length = 0;
    while (length < capacity && name[length] != '\0') {
        ++length;
    }
    return std::string(name, length);
}

void CopyDisplayName(const std::string& name, char* target, std::size_t capacity) {
    if (target == nullptr || capacity == 0) {
        return;
    }
    std::memset(target, 0, capacity);
    const auto count = (std::min)(name.size(), capacity - 1);
    std::memcpy(target, name.data(), count);
}

const char* HelloResultLabel(SessionHelloResultCode result) {
    switch (result) {
    case SessionHelloResultCode::Accepted:
        return "accepted";
    case SessionHelloResultCode::ProtocolMismatch:
        return "protocol_mismatch";
    case SessionHelloResultCode::ManifestMismatch:
        return "manifest_mismatch";
    case SessionHelloResultCode::LobbyMismatch:
        return "lobby_mismatch";
    case SessionHelloResultCode::IdentityMismatch:
        return "identity_mismatch";
    case SessionHelloResultCode::LobbyFull:
        return "lobby_full";
    case SessionHelloResultCode::HostMismatch:
        return "host_mismatch";
    case SessionHelloResultCode::CapabilityMismatch:
        return "capability_mismatch";
    }
    return "unknown";
}

std::string HelloResultUserMessage(SessionHelloResultCode result) {
    const char* text;
    switch (result) {
    case SessionHelloResultCode::Accepted:
        text = "The host accepted the connection";
        break;
    case SessionHelloResultCode::ProtocolMismatch:
        text =
            "The host is on a different Solomon Dark Revived version. "
            "Update both players to the same launcher version";
        break;
    case SessionHelloResultCode::ManifestMismatch:
        text =
            "Mod list mismatch. Your mods or game build do not match the host's. "
            "Join through the launcher or the website lobby browser and it "
            "downloads the host's mods for you";
        break;
    case SessionHelloResultCode::LobbyMismatch:
        text = "The lobby changed while joining. Try joining again";
        break;
    case SessionHelloResultCode::IdentityMismatch:
        text = "Steam identity validation failed. Restart the game and try again";
        break;
    case SessionHelloResultCode::LobbyFull:
        text = "The lobby is full";
        break;
    case SessionHelloResultCode::HostMismatch:
        text = "The lobby host changed while joining. Try joining again";
        break;
    case SessionHelloResultCode::CapabilityMismatch:
        text =
            "The host requires multiplayer features this build does not have. "
            "Update both players to the same launcher version";
        break;
    default:
        text = "The host rejected the connection";
        break;
    }
    return std::string(text) + " (" + HelloResultLabel(result) + ").";
}

void SetError(std::string message, bool leave_lobby) {
    Log("Steam multiplayer session error: " + message);
    g_session.error_text = std::move(message);
    g_session.phase = SteamSessionPhase::Error;
    RemoveAllPeers();
    SteamSetRichPresence("connect", nullptr);
    SteamSetRichPresence("status", nullptr);
    if (leave_lobby && g_session.lobby_id != 0) {
        SteamLeaveLobby(g_session.lobby_id);
        g_session.lobby_id = 0;
        g_session.lobby_members.clear();
    }
}

bool IsLobbyMember(std::uint64_t steam_id) {
    return steam_id != 0 &&
           g_session.lobby_members.find(steam_id) != g_session.lobby_members.end();
}

void SuspendPeerForReauthentication(std::uint64_t steam_id) {
    const auto peer_it = g_session.peers.find(steam_id);
    if (steam_id == 0 || peer_it == g_session.peers.end()) {
        return;
    }
    UnregisterSteamGameplayPeer(steam_id);
    auto& peer = peer_it->second;
    peer.authenticated = false;
    peer.last_packet_ms = 0;
}

void ResetPeerForReauthentication(std::uint64_t steam_id) {
    if (steam_id == 0) {
        return;
    }
    UnregisterSteamGameplayPeer(steam_id);
    g_session.peers.erase(steam_id);
}

void RemovePeer(std::uint64_t steam_id) {
    if (steam_id == 0) {
        return;
    }
    ResetPeerForReauthentication(steam_id);
    SteamCloseNetworkSession(steam_id);
}

void RestartClientHostHandshake(
    std::uint64_t host_steam_id,
    const char* reason,
    bool reset_failed_route) {
    if (g_session.is_host ||
        host_steam_id == 0 ||
        host_steam_id != g_session.host_steam_id ||
        !IsLobbyMember(host_steam_id)) {
        return;
    }
    ResetPeerForReauthentication(host_steam_id);
    if (reset_failed_route) {
        const bool route_reset = SteamCloseNetworkSession(host_steam_id);
        Log(
            "Steam multiplayer reset terminal host route. steam_id=" +
            std::to_string(host_steam_id) +
            " close_result=" + (route_reset ? "1" : "0"));
    }
    auto& peer = g_session.peers[host_steam_id];
    peer.steam_id = host_steam_id;
    peer.display_name = SteamGetFriendPersonaName(host_steam_id);
    g_session.local_session_nonce = GenerateSessionNonce();
    // A normal application heartbeat timeout deliberately reuses the live
    // message route. A terminal Steam failure must close that dead route, then
    // leave one retry interval for Steam's teardown before opening a new one.
    g_session.last_hello_send_ms = reset_failed_route ? GetTickCount64() : 0;
    g_session.phase = SteamSessionPhase::Handshaking;
    Log(
        "Steam multiplayer restarting host handshake. reason=" +
        std::string(reason != nullptr ? reason : "unknown"));
}

void RemoveAllPeers() {
    std::vector<std::uint64_t> peer_ids;
    peer_ids.reserve(g_session.peers.size());
    for (const auto& [steam_id, peer] : g_session.peers) {
        (void)peer;
        peer_ids.push_back(steam_id);
    }
    for (const auto steam_id : peer_ids) {
        RemovePeer(steam_id);
    }
}
