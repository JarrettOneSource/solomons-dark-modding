bool TryParseConfigFloatArray(
    const std::string& text,
    std::string_view key,
    std::vector<float>* values) {
    if (values == nullptr) {
        return false;
    }

    values->clear();
    auto IsIdentifierCharacter = [](char ch) {
        return (ch >= 'a' && ch <= 'z') ||
               (ch >= 'A' && ch <= 'Z') ||
               (ch >= '0' && ch <= '9') ||
               ch == '_';
    };
    auto IsWhitespace = [](char ch) {
        return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n';
    };

    std::size_t open_brace = std::string::npos;
    std::size_t search_position = 0;
    while (search_position < text.size()) {
        const auto candidate = text.find(key, search_position);
        if (candidate == std::string::npos) {
            break;
        }

        const auto after_key = candidate + key.size();
        const bool identifier_boundary =
            (candidate == 0 || !IsIdentifierCharacter(text[candidate - 1])) &&
            (after_key >= text.size() || !IsIdentifierCharacter(text[after_key]));
        std::size_t cursor = after_key;
        while (cursor < text.size() && IsWhitespace(text[cursor])) {
            ++cursor;
        }
        if (identifier_boundary && cursor < text.size() && text[cursor] == '=') {
            ++cursor;
            while (cursor < text.size() && IsWhitespace(text[cursor])) {
                ++cursor;
            }
            if (cursor < text.size() && text[cursor] == '{') {
                open_brace = cursor;
                break;
            }
        }
        search_position = after_key;
    }
    if (open_brace == std::string::npos) {
        return false;
    }

    const auto close_brace =
        text.find('}', open_brace + 1);
    if (close_brace == std::string::npos || close_brace <= open_brace) {
        return false;
    }

    std::string token;
    bool parse_valid = true;
    const auto body = text.substr(open_brace + 1, close_brace - open_brace - 1);
    auto FlushToken = [&]() {
        if (token.empty()) {
            return;
        }
        char* end = nullptr;
        const float value = std::strtof(token.c_str(), &end);
        if (end == token.c_str() || *end != '\0' || !std::isfinite(value)) {
            parse_valid = false;
            values->clear();
            token.clear();
            return;
        }
        values->push_back(value);
        token.clear();
    };

    for (const char ch : body) {
        if ((ch >= '0' && ch <= '9') ||
            ch == '-' || ch == '+' || ch == '.' || ch == 'e' || ch == 'E') {
            token.push_back(ch);
        } else {
            FlushToken();
        }
    }
    FlushToken();
    return parse_valid && !values->empty();
}

const ParticipantProgressionBookEntryState* FindProgressionBookEntryById(
    const ParticipantOwnedProgressionState& progression,
    std::int32_t entry_id) {
    for (const auto& entry : progression.progression_book_entries) {
        if (entry.entry_index == entry_id) {
            return &entry;
        }
    }
    return nullptr;
}

bool EnsureFireballExplodeEffectConfigLoaded(std::string* error_message = nullptr) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_fireball_explode_effect_config.loaded) {
        return true;
    }
    if (g_fireball_explode_effect_config_attempted) {
        if (error_message != nullptr) {
            *error_message = "explode.cfg was already probed and is unavailable";
        }
        return false;
    }
    g_fireball_explode_effect_config_attempted = true;

    const auto path = ResolveRuntimeWizardSkillConfigPath(L"explode.cfg");
    if (path.empty()) {
        if (error_message != nullptr) {
            *error_message = "could not resolve runtime explode.cfg path";
        }
        return false;
    }

    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error_message != nullptr) {
            *error_message = "could not open " + path.string();
        }
        return false;
    }

    std::ostringstream buffer;
    buffer << input.rdbuf();
    const auto text = buffer.str();

    std::vector<float> damage_by_level;
    std::vector<float> radius_feet_by_level;
    if (!TryParseConfigFloatArray(text, "mDamage", &damage_by_level) ||
        !TryParseConfigFloatArray(text, "mRadius", &radius_feet_by_level)) {
        if (error_message != nullptr) {
            *error_message = "failed to parse explode.cfg damage/radius arrays";
        }
        return false;
    }

    g_fireball_explode_effect_config.loaded = true;
    g_fireball_explode_effect_config.damage_by_level = std::move(damage_by_level);
    g_fireball_explode_effect_config.radius_feet_by_level = std::move(radius_feet_by_level);
    return true;
}

bool TryResolveFireballExplodeSplashTuning(
    const ParticipantOwnedProgressionState& progression,
    float* splash_damage,
    float* splash_radius_world,
    std::string* error_message = nullptr) {
    if (splash_damage != nullptr) {
        *splash_damage = 0.0f;
    }
    if (splash_radius_world != nullptr) {
        *splash_radius_world = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    const auto* explode_entry =
        FindProgressionBookEntryById(progression, kFireballExplodeProgressionEntryId);
    if (explode_entry == nullptr || explode_entry->active <= 0) {
        if (error_message != nullptr) {
            *error_message = "explode upgrade is not active";
        }
        return false;
    }

    std::string config_error;
    if (!EnsureFireballExplodeEffectConfigLoaded(&config_error)) {
        if (error_message != nullptr) {
            *error_message = config_error;
        }
        return false;
    }

    const auto active_level =
        (std::max)(0, static_cast<int>(explode_entry->active));
    const auto level_index = static_cast<std::size_t>(active_level);
    const auto damage_index = (std::min)(
        level_index,
        g_fireball_explode_effect_config.damage_by_level.size() - 1);
    const auto radius_index = (std::min)(
        level_index,
        g_fireball_explode_effect_config.radius_feet_by_level.size() - 1);
    const float damage =
        g_fireball_explode_effect_config.damage_by_level[damage_index];
    const float radius_world =
        g_fireball_explode_effect_config.radius_feet_by_level[radius_index] *
        kFireballExplodeConfigFootToWorldUnits;
    if (!std::isfinite(damage) || damage <= 0.0f ||
        !std::isfinite(radius_world) || radius_world <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "explode tuning resolved non-positive damage/radius";
        }
        return false;
    }

    if (splash_damage != nullptr) {
        *splash_damage = damage;
    }
    if (splash_radius_world != nullptr) {
        *splash_radius_world = radius_world;
    }
    return true;
}

bool IsLocalUdpRequested() {
    const auto transport = ToLowerAscii(ReadEnvironmentVariable(kTransportEnvironmentVariable));
    return transport == "local_udp" || transport == "local-udp" || transport == "udp";
}

bool IsSteamTransportRequested() {
    return ToLowerAscii(ReadEnvironmentVariable(kTransportEnvironmentVariable)) == "steam";
}

bool ConfigureLocalTransport() {
    const bool local_udp_requested = IsLocalUdpRequested();
    const bool steam_requested = IsSteamTransportRequested();
    if (!local_udp_requested && !steam_requested) {
        g_local_transport = LocalTransportState{};
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        ClearLocalLootPickupRequestStateLocked();
        g_queued_local_level_up_choices.clear();
        g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
        g_have_queued_local_air_chain_frame = false;
        ResetAirChainRuntimeState();
        return false;
    }

    const auto role = ToLowerAscii(ReadEnvironmentVariable(kRoleEnvironmentVariable));
    const bool is_host = role.empty() || role == "host" || role == "server";
    const auto local_port = ReadPortEnvironmentVariable(
        kLocalPortEnvironmentVariable,
        is_host ? kDefaultHostPort : kDefaultClientPort);
    const auto remote_port = ReadPortEnvironmentVariable(
        kRemotePortEnvironmentVariable,
        is_host ? kDefaultClientPort : kDefaultHostPort);
    auto remote_host = ReadEnvironmentVariable(kRemoteHostEnvironmentVariable);
    if (remote_host.empty()) {
        remote_host = "127.0.0.1";
    }

    g_local_transport = LocalTransportState{};
    g_local_transport.configured = true;
    g_local_transport.is_host = is_host;
    g_local_transport.backend = steam_requested
        ? GameplayTransportBackend::Steam
        : GameplayTransportBackend::LocalUdp;
    if (steam_requested) {
        const auto steam = GetSteamBootstrapSnapshot();
        g_local_transport.local_peer_id = steam.transport_interfaces_ready
            ? steam.local_steam_id
            : 0;
    } else {
    g_local_transport.local_port = local_port;
    g_local_transport.remote_host = remote_host;
    g_local_transport.remote_port = remote_port;
    g_local_transport.local_peer_id = ReadParticipantId(local_port);
    g_local_transport.configured_remote.backend = GameplayTransportBackend::LocalUdp;
    g_local_transport.configured_remote_valid = ResolveIpv4Endpoint(
        remote_host,
        remote_port,
        &g_local_transport.configured_remote.udp_address);
    }
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        ClearLocalLootPickupRequestStateLocked();
        g_queued_local_level_up_choices.clear();
        g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
        g_have_queued_local_air_chain_frame = false;
    }
    ResetAirChainRuntimeState();
    return true;
}

void UpsertPeerEndpoint(
    const TransportPeerEndpoint& endpoint,
    std::uint64_t participant_id,
    std::uint64_t now_ms) {
    if (endpoint.backend == GameplayTransportBackend::Steam &&
        participant_id != endpoint.steam_id) {
        return;
    }
    for (auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.endpoint, endpoint)) {
            if (peer.participant_id != participant_id) {
                return;
            }
            peer.last_packet_ms = now_ms;
            return;
        }
    }

    LocalPeerEndpoint peer;
    peer.endpoint = endpoint;
    peer.participant_id = participant_id;
    peer.last_packet_ms = now_ms;
    g_local_transport.peers.push_back(peer);
    Log(
        "Multiplayer transport learned peer endpoint=" + EndpointToString(endpoint) +
        " participant_id=" + std::to_string(participant_id));
}

std::string ReadLocalDisplayName() {
    auto name = ReadEnvironmentVariable(kPlayerNameEnvironmentVariable);
    if (name.empty()) {
        return {};
    }
    if (name.size() >= kParticipantDisplayNameBytes) {
        name.resize(kParticipantDisplayNameBytes - 1);
    }
    return name;
}

void CopyPacketDisplayName(const std::string& name, StatePacket* packet) {
    if (packet == nullptr) {
        return;
    }
    std::memset(packet->display_name, 0, sizeof(packet->display_name));
    if (name.empty()) {
        return;
    }
    const auto count = (std::min)(name.size(), sizeof(packet->display_name) - 1);
    std::memcpy(packet->display_name, name.data(), count);
}

std::string PacketDisplayName(const StatePacket& packet) {
    std::size_t length = 0;
    while (length < sizeof(packet.display_name) && packet.display_name[length] != '\0') {
        ++length;
    }
    return std::string(packet.display_name, packet.display_name + length);
}

ParticipantSceneIntent SceneIntentFromPacket(const StatePacket& packet) {
    ParticipantSceneIntent intent;
    intent.kind = packet.in_run != 0 ? ParticipantSceneIntentKind::Run
                                     : ParticipantSceneIntentKind::SharedHub;
    return intent;
}

ParticipantSceneIntent SceneIntentFromPacket(
    const ParticipantFramePacket& packet) {
    ParticipantSceneIntent intent;
    switch (static_cast<WorldSceneKind>(packet.scene_kind)) {
    case WorldSceneKind::Run:
        intent.kind = ParticipantSceneIntentKind::Run;
        break;
    case WorldSceneKind::PrivateRegion:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        intent.region_index = packet.region_index;
        intent.region_type_id = packet.region_type_id;
        break;
    case WorldSceneKind::SharedHub:
    case WorldSceneKind::Unknown:
    default:
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        break;
    }
    return intent;
}

ParticipantSceneIntent SceneIntentFromLocalScene() {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return DefaultParticipantSceneIntent();
    }

    ParticipantSceneIntent intent;
    if (scene_state.kind == "arena") {
        intent.kind = ParticipantSceneIntentKind::Run;
        return intent;
    }
    if (scene_state.kind == "hub") {
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        return intent;
    }

    intent.kind = ParticipantSceneIntentKind::PrivateRegion;
    intent.region_index = scene_state.current_region_index;
    intent.region_type_id = scene_state.region_type_id;
    return intent;
}

WorldSceneKind WorldSceneKindFromSceneIntent(const ParticipantSceneIntent& intent) {
    switch (intent.kind) {
    case ParticipantSceneIntentKind::SharedHub:
        return WorldSceneKind::SharedHub;
    case ParticipantSceneIntentKind::PrivateRegion:
        return WorldSceneKind::PrivateRegion;
    case ParticipantSceneIntentKind::Run:
        return WorldSceneKind::Run;
    }

    return WorldSceneKind::Unknown;
}

ParticipantSceneIntent SceneIntentFromWorldSceneKind(WorldSceneKind kind) {
    ParticipantSceneIntent intent;
    switch (kind) {
    case WorldSceneKind::SharedHub:
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        break;
    case WorldSceneKind::PrivateRegion:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        break;
    case WorldSceneKind::Run:
        intent.kind = ParticipantSceneIntentKind::Run;
        break;
    case WorldSceneKind::Unknown:
    default:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        break;
    }
    return intent;
}

LootDropKind LootDropKindFromPacketValue(std::uint8_t kind) {
    switch (static_cast<LootDropKind>(kind)) {
    case LootDropKind::Gold:
        return LootDropKind::Gold;
    case LootDropKind::Item:
        return LootDropKind::Item;
    case LootDropKind::Potion:
        return LootDropKind::Potion;
    case LootDropKind::Orb:
        return LootDropKind::Orb;
    case LootDropKind::Powerup:
        return LootDropKind::Powerup;
    case LootDropKind::Unknown:
    default:
        return LootDropKind::Unknown;
    }
}

LootPickupResultCode LootPickupResultCodeFromPacketValue(std::uint8_t code) {
    switch (static_cast<LootPickupResultCode>(code)) {
    case LootPickupResultCode::Accepted:
        return LootPickupResultCode::Accepted;
    case LootPickupResultCode::AlreadyGone:
        return LootPickupResultCode::AlreadyGone;
    case LootPickupResultCode::OutOfRange:
        return LootPickupResultCode::OutOfRange;
    case LootPickupResultCode::WrongRun:
        return LootPickupResultCode::WrongRun;
    case LootPickupResultCode::Unsupported:
        return LootPickupResultCode::Unsupported;
    case LootPickupResultCode::Rejected:
    default:
        return LootPickupResultCode::Rejected;
    }
}

LevelUpChoiceResultCode LevelUpChoiceResultCodeFromPacketValue(std::uint8_t code) {
    switch (static_cast<LevelUpChoiceResultCode>(code)) {
    case LevelUpChoiceResultCode::Accepted:
        return LevelUpChoiceResultCode::Accepted;
    case LevelUpChoiceResultCode::StaleOffer:
        return LevelUpChoiceResultCode::StaleOffer;
    case LevelUpChoiceResultCode::InvalidOption:
        return LevelUpChoiceResultCode::InvalidOption;
    case LevelUpChoiceResultCode::ApplyFailed:
        return LevelUpChoiceResultCode::ApplyFailed;
    case LevelUpChoiceResultCode::Rejected:
    default:
        return LevelUpChoiceResultCode::Rejected;
    }
}

const char* LevelUpChoiceResultCodeLabel(LevelUpChoiceResultCode code) {
    switch (code) {
    case LevelUpChoiceResultCode::Accepted:
        return "Accepted";
    case LevelUpChoiceResultCode::Rejected:
        return "Rejected";
    case LevelUpChoiceResultCode::StaleOffer:
        return "StaleOffer";
    case LevelUpChoiceResultCode::InvalidOption:
        return "InvalidOption";
    case LevelUpChoiceResultCode::ApplyFailed:
        return "ApplyFailed";
    }

    return "Unknown";
}

std::string BuildWorldSceneKey(const SDModSceneState& scene_state) {
    std::ostringstream stream;
    stream << scene_state.kind
           << ":" << scene_state.name
           << ":" << scene_state.current_region_index
           << ":" << scene_state.region_type_id
           << ":" << scene_state.gameplay_scene_address;
    return stream.str();
}

std::uint64_t BuildRunWorldActorNetworkId(std::uint32_t spawn_serial) {
    if (spawn_serial == 0) {
        return 0;
    }
    return kRunWorldActorNetworkIdBase | static_cast<std::uint64_t>(spawn_serial);
}

std::uint64_t BuildRunLootDropNetworkId(std::uint32_t spawn_serial) {
    if (spawn_serial == 0) {
        return 0;
    }
    return kRunLootDropNetworkIdBase | static_cast<std::uint64_t>(spawn_serial);
}

std::uint64_t AllocateRunHostLocalWorldActorNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_run_host_local_world_actor_serial == 0) {
        g_local_transport.next_run_host_local_world_actor_serial = 1;
    }
    const auto serial = g_local_transport.next_run_host_local_world_actor_serial++;
    const auto network_actor_id =
        kRunHostLocalWorldActorNetworkIdBase | static_cast<std::uint64_t>(serial);
    g_local_transport.run_host_local_world_actor_ids_by_address.emplace(actor.actor_address, network_actor_id);
    Log(
        "world_snapshot: assigned host-local run actor network id. actor=" +
        HexString(actor.actor_address) +
        " type=" + HexString(static_cast<uintptr_t>(actor.object_type_id)) +
        " enemy_type=" + std::to_string(actor.enemy_type) +
        " network_actor_id=" + std::to_string(network_actor_id));
    return network_actor_id;
}

std::uint64_t AllocateRunLootDropNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.run_loot_drop_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.run_loot_drop_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_run_loot_drop_serial == 0) {
        g_local_transport.next_run_loot_drop_serial = 1;
    }
    const auto serial = g_local_transport.next_run_loot_drop_serial++;
    const auto network_drop_id = BuildRunLootDropNetworkId(serial);
    g_local_transport.run_loot_drop_ids_by_address.emplace(actor.actor_address, network_drop_id);
    return network_drop_id;
}

bool IsRunStaticLayoutActorType(std::uint32_t native_type_id) {
    return native_type_id == kSolomonDigNativeTypeId ||
           native_type_id == kSolomonRunStaticNativeTypeId;
}

bool IsRunStaticLayoutActor(const SDModSceneActorState& actor) {
    return !actor.tracked_enemy &&
           IsRunStaticLayoutActorType(actor.object_type_id);
}
