constexpr std::uint64_t kDeathPresentationDurationMs = 3000;
constexpr std::uint64_t kSpectatorClickReleaseDebounceMs = 150;
constexpr std::string_view kDeathSpectatorCameraOwner =
    "multiplayer.death_spectator";

struct LocalDeathSpectatorState {
    DeathSpectatorPhase phase = DeathSpectatorPhase::Inactive;
    std::uint64_t death_started_ms = 0;
    std::uint64_t target_participant_id = 0;
    bool click_armed = true;
    std::uint64_t click_consumed_ms = 0;
    std::uint64_t observed_mouse_left_edge_serial = 0;
    std::uint64_t observed_mouse_right_edge_serial = 0;
};

LocalDeathSpectatorState g_local_death_spectator;

struct WaveRespawnCommand {
    std::uint32_t epoch = 0;
    std::int32_t wave = 0;
    std::uint32_t run_nonce = 0;
    float world_x = 0.0f;
    float world_y = 0.0f;
};

struct HostWaveRespawnState {
    bool spawn_anchor_valid = false;
    float spawn_x = 0.0f;
    float spawn_y = 0.0f;
    std::uint32_t run_nonce = 0;
    std::int32_t last_completed_wave = 0;
    std::uint32_t next_epoch = 1;
    WaveRespawnCommand command;
};

HostWaveRespawnState g_host_wave_respawn;
std::uint32_t g_last_applied_wave_respawn_epoch = 0;
std::uint64_t g_last_wave_respawn_failure_log_ms = 0;

void ResetLocalDeathSpectatorState(std::string_view reason);

void ResetWaveRespawnState() {
    g_host_wave_respawn = HostWaveRespawnState{};
    g_last_applied_wave_respawn_epoch = 0;
    g_last_wave_respawn_failure_log_ms = 0;
    UpdateRuntimeState([](RuntimeState& state) {
        state.death_spectator.last_applied_respawn_epoch = 0;
        state.death_spectator.last_applied_respawn_wave = 0;
        state.death_spectator.last_respawn_x = 0.0f;
        state.death_spectator.last_respawn_y = 0.0f;
    });
}

void PublishLocalDeathSpectatorRuntime(std::uint64_t now_ms) {
    const auto local = g_local_death_spectator;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto& runtime = state.death_spectator;
        runtime.active = local.phase != DeathSpectatorPhase::Inactive;
        runtime.phase = local.phase;
        runtime.death_started_ms = local.death_started_ms;
        runtime.target_participant_id = local.target_participant_id;
        if (local.phase == DeathSpectatorPhase::DeathPresentation &&
            now_ms >= local.death_started_ms) {
            const auto elapsed_ms = now_ms - local.death_started_ms;
            runtime.presentation_remaining_ms = static_cast<std::uint32_t>(
                elapsed_ms < kDeathPresentationDurationMs
                    ? kDeathPresentationDurationMs - elapsed_ms
                    : 0);
        } else {
            runtime.presentation_remaining_ms = 0;
        }
        if (local.phase == DeathSpectatorPhase::Inactive) {
            runtime.target_name.clear();
            runtime.waiting_for_alive_target = false;
        }
    });
}

bool IsValidWaveRespawnCommand(
    const WaveRespawnCommand& command) {
    constexpr std::int32_t kMaximumRespawnWave = 4096;
    constexpr float kMaximumRespawnCoordinateMagnitude = 1000000.0f;
    return command.epoch != 0 &&
           command.wave > 0 &&
           command.wave <= kMaximumRespawnWave &&
           command.run_nonce != 0 &&
           std::isfinite(command.world_x) &&
           std::isfinite(command.world_y) &&
           std::abs(command.world_x) <=
               kMaximumRespawnCoordinateMagnitude &&
           std::abs(command.world_y) <=
               kMaximumRespawnCoordinateMagnitude;
}

bool TryApplyWaveRespawnCommand(
    const WaveRespawnCommand& command,
    std::uint64_t now_ms,
    std::string_view source) {
    if (!IsValidWaveRespawnCommand(command) ||
        (g_last_applied_wave_respawn_epoch != 0 &&
         !IsPacketSequenceNewer(
             command.epoch,
             g_last_applied_wave_respawn_epoch))) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce != command.run_nonce) {
        return false;
    }

    std::string respawn_error;
    if (!TryRespawnLocalPlayerAt(
            command.world_x,
            command.world_y,
            &respawn_error)) {
        if (g_last_wave_respawn_failure_log_ms == 0 ||
            now_ms >=
                g_last_wave_respawn_failure_log_ms + 1000) {
            g_last_wave_respawn_failure_log_ms = now_ms;
            Log(
                "Multiplayer wave respawn is pending native convergence. "
                "source=" +
                std::string(source) +
                " epoch=" + std::to_string(command.epoch) +
                " wave=" + std::to_string(command.wave) +
                " error=" + respawn_error);
        }
        return false;
    }

    g_last_applied_wave_respawn_epoch = command.epoch;
    g_last_wave_respawn_failure_log_ms = 0;
    ResetLocalDeathSpectatorState("wave_respawn");
    SDModPlayerState player;
    const bool have_player =
        TryGetPlayerState(&player) && player.valid;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* mutable_local = FindLocalParticipant(state);
        if (mutable_local != nullptr && have_player) {
            mutable_local->runtime.life_current = player.hp;
            mutable_local->runtime.life_max = player.max_hp;
            mutable_local->runtime.mana_current = player.mp;
            mutable_local->runtime.mana_max = player.max_mp;
            mutable_local->runtime.position_x = player.x;
            mutable_local->runtime.position_y = player.y;
            mutable_local->runtime.anim_drive_state =
                player.anim_drive_state;
            mutable_local->runtime.movement_intent_x = 0.0f;
            mutable_local->runtime.movement_intent_y = 0.0f;
        }
        state.death_spectator.last_applied_respawn_epoch =
            command.epoch;
        state.death_spectator.last_applied_respawn_wave =
            command.wave;
        state.death_spectator.last_respawn_x = command.world_x;
        state.death_spectator.last_respawn_y = command.world_y;
    });
    Log(
        "Multiplayer wave respawn applied. source=" +
        std::string(source) +
        " epoch=" + std::to_string(command.epoch) +
        " wave=" + std::to_string(command.wave) +
        " position=(" + std::to_string(command.world_x) + "," +
        std::to_string(command.world_y) + ")");
    return true;
}

void CaptureHostWaveRespawnAnchorIfNeeded() {
    if (!g_local_transport.is_host ||
        g_host_wave_respawn.spawn_anchor_valid) {
        return;
    }
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    SDModPlayerState player;
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce == 0 ||
        !TryGetPlayerState(&player) ||
        !player.valid ||
        !std::isfinite(player.x) ||
        !std::isfinite(player.y)) {
        return;
    }
    g_host_wave_respawn.spawn_anchor_valid = true;
    g_host_wave_respawn.spawn_x = player.x;
    g_host_wave_respawn.spawn_y = player.y;
    g_host_wave_respawn.run_nonce = local->runtime.run_nonce;
    Log(
        "Multiplayer captured run respawn anchor. run_nonce=" +
        std::to_string(g_host_wave_respawn.run_nonce) +
        " position=(" + std::to_string(player.x) + "," +
        std::to_string(player.y) + ")");
}

void RefreshHostWaveRespawnCommand(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        return;
    }
    CaptureHostWaveRespawnAnchorIfNeeded();
    if (!g_host_wave_respawn.spawn_anchor_valid) {
        return;
    }

    const auto summary = SnapshotWaveSummary();
    if (!summary.valid ||
        summary.phase != WavePhase::Completed ||
        summary.wave <= 0 ||
        summary.wave == g_host_wave_respawn.last_completed_wave) {
        return;
    }

    auto epoch = g_host_wave_respawn.next_epoch++;
    if (epoch == 0) {
        epoch = g_host_wave_respawn.next_epoch++;
    }
    g_host_wave_respawn.last_completed_wave = summary.wave;
    g_host_wave_respawn.command = WaveRespawnCommand{
        epoch,
        summary.wave,
        g_host_wave_respawn.run_nonce,
        g_host_wave_respawn.spawn_x,
        g_host_wave_respawn.spawn_y,
    };
    Log(
        "Multiplayer host published wave respawn. epoch=" +
        std::to_string(epoch) +
        " wave=" + std::to_string(summary.wave));
    (void)TryApplyWaveRespawnCommand(
        g_host_wave_respawn.command,
        now_ms,
        "host_wave_completion");
}

void RetryHostWaveRespawnCommand(std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        !IsValidWaveRespawnCommand(g_host_wave_respawn.command) ||
        g_last_applied_wave_respawn_epoch ==
            g_host_wave_respawn.command.epoch) {
        return;
    }
    (void)TryApplyWaveRespawnCommand(
        g_host_wave_respawn.command,
        now_ms,
        "host_retry");
}

template <typename Packet>
void PopulateAuthorityWaveRespawn(Packet* packet) {
    if (packet == nullptr ||
        !g_local_transport.is_host ||
        !IsValidWaveRespawnCommand(g_host_wave_respawn.command)) {
        return;
    }
    packet->wave_respawn_epoch =
        g_host_wave_respawn.command.epoch;
    packet->wave_respawn_wave =
        g_host_wave_respawn.command.wave;
    packet->wave_respawn_x =
        g_host_wave_respawn.command.world_x;
    packet->wave_respawn_y =
        g_host_wave_respawn.command.world_y;
}

template <typename Packet>
void ApplyAuthoritativeWaveRespawn(
    const Packet& packet,
    bool packet_from_configured_authority,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        !packet_from_configured_authority) {
        return;
    }
    const WaveRespawnCommand command{
        packet.wave_respawn_epoch,
        packet.wave_respawn_wave,
        packet.run_nonce,
        packet.wave_respawn_x,
        packet.wave_respawn_y,
    };
    (void)TryApplyWaveRespawnCommand(
        command,
        now_ms,
        "authenticated_host_packet");
}

void ResetLocalDeathSpectatorState(std::string_view reason) {
    const bool was_active =
        g_local_death_spectator.phase != DeathSpectatorPhase::Inactive;
    (void)ClearLocalCameraFocus(kDeathSpectatorCameraOwner);
    g_local_death_spectator = LocalDeathSpectatorState{};
    PublishLocalDeathSpectatorRuntime(
        static_cast<std::uint64_t>(GetTickCount64()));
    if (was_active) {
        Log(
            "Multiplayer death spectator retired. reason=" +
            std::string(reason));
    }
}

bool HoldLocalSpectatorDeathVitals() {
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        !std::isfinite(player.hp) ||
        !std::isfinite(player.max_hp) ||
        !std::isfinite(player.mp) ||
        !std::isfinite(player.max_mp) ||
        player.max_hp <= 0.0f ||
        player.max_mp <= 0.0f) {
        return false;
    }
    if (player.hp > 0.0f &&
        !TryWriteLocalPlayerOrbResource(
            static_cast<std::int32_t>(
                LootOrbResourceKind::Health),
            0.0f,
            player.max_hp,
            player.mp,
            player.max_mp)) {
        return false;
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = FindLocalParticipant(state);
        if (local == nullptr) {
            return;
        }
        local->runtime.life_current = 0.0f;
        local->runtime.life_max = player.max_hp;
    });
    return true;
}

std::vector<std::uint64_t> CollectAliveSpectatorTargetIds(
    const RuntimeState& runtime_state,
    std::uint32_t run_nonce) {
    std::vector<std::uint64_t> participant_ids;
    for (const auto& participant : runtime_state.participants) {
        if (participant.participant_id == 0 ||
            participant.participant_id == g_local_transport.local_peer_id ||
            !participant.ready ||
            !participant.transport_connected ||
            !participant.runtime.valid ||
            !participant.runtime.in_run ||
            !participant.runtime.transform_valid ||
            participant.runtime.run_nonce != run_nonce ||
            !std::isfinite(participant.runtime.life_current) ||
            !std::isfinite(participant.runtime.life_max) ||
            participant.runtime.life_max <= 0.0f ||
            !(participant.runtime.life_current > 0.0f)) {
            continue;
        }
        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(
                participant.participant_id,
                &gameplay_state) ||
            !gameplay_state.available ||
            !gameplay_state.entity_materialized ||
            gameplay_state.actor_address == 0 ||
            !std::isfinite(gameplay_state.x) ||
            !std::isfinite(gameplay_state.y) ||
            !std::isfinite(gameplay_state.hp) ||
            gameplay_state.hp <= 0.0f) {
            continue;
        }
        participant_ids.push_back(participant.participant_id);
    }
    std::sort(participant_ids.begin(), participant_ids.end());
    return participant_ids;
}

std::uint64_t SelectNextAliveSpectatorTarget(
    const std::vector<std::uint64_t>& participant_ids,
    std::uint64_t current_participant_id,
    bool advance) {
    if (participant_ids.empty()) {
        return 0;
    }
    const auto current = std::find(
        participant_ids.begin(),
        participant_ids.end(),
        current_participant_id);
    if (current == participant_ids.end()) {
        return participant_ids.front();
    }
    if (!advance) {
        return *current;
    }
    const auto next = std::next(current);
    return next != participant_ids.end()
        ? *next
        : participant_ids.front();
}

void PublishSpectatorTarget(
    const RuntimeState& runtime_state,
    std::uint64_t target_participant_id,
    bool waiting_for_alive_target) {
    std::string target_name;
    if (target_participant_id != 0) {
        const auto* target =
            FindParticipant(runtime_state, target_participant_id);
        if (target != nullptr) {
            target_name = target->name;
        }
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        state.death_spectator.target_participant_id =
            target_participant_id;
        state.death_spectator.target_name = target_name;
        state.death_spectator.waiting_for_alive_target =
            waiting_for_alive_target;
    });
}

void TickLocalSpectatorTarget(std::uint64_t now_ms) {
    auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce == 0) {
        ResetLocalDeathSpectatorState("local_run_unavailable");
        return;
    }

    const bool mouse_left_down = IsGameplayMouseLeftDown();
    const bool mouse_right_down = IsGameplayMouseRightDown();
    const auto mouse_left_edge_serial =
        GetGameplayMouseLeftEdgeSerial();
    const auto mouse_right_edge_serial =
        GetGameplayMouseRightEdgeSerial();
    const bool mouse_left_edge =
        mouse_left_edge_serial !=
        g_local_death_spectator.observed_mouse_left_edge_serial;
    const bool mouse_right_edge =
        mouse_right_edge_serial !=
        g_local_death_spectator.observed_mouse_right_edge_serial;
    bool advance = false;
    if (g_local_death_spectator.click_armed &&
        (mouse_left_edge ||
         mouse_right_edge ||
         mouse_left_down ||
         mouse_right_down)) {
        advance = true;
        g_local_death_spectator.click_armed = false;
        g_local_death_spectator.click_consumed_ms = now_ms;
        g_local_death_spectator.observed_mouse_left_edge_serial =
            mouse_left_edge_serial;
        g_local_death_spectator.observed_mouse_right_edge_serial =
            mouse_right_edge_serial;
        if (mouse_left_edge || mouse_left_down) {
            ClearQueuedGameplayMouseLeft();
        }
        if (mouse_right_edge || mouse_right_down) {
            ClearQueuedGameplayMouseRight();
        }
    } else if (!g_local_death_spectator.click_armed &&
               !mouse_left_down &&
               !mouse_right_down &&
               now_ms >=
                   g_local_death_spectator.click_consumed_ms +
                       kSpectatorClickReleaseDebounceMs) {
        g_local_death_spectator.click_armed = true;
    }
    const auto alive_target_ids = CollectAliveSpectatorTargetIds(
        runtime_state,
        local->runtime.run_nonce);
    const auto target_participant_id = SelectNextAliveSpectatorTarget(
        alive_target_ids,
        g_local_death_spectator.target_participant_id,
        advance);
    g_local_death_spectator.target_participant_id =
        target_participant_id;
    if (target_participant_id == 0) {
        (void)ClearLocalCameraFocus(kDeathSpectatorCameraOwner);
        PublishSpectatorTarget(runtime_state, 0, true);
        return;
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(
            target_participant_id,
            &gameplay_state) ||
        !gameplay_state.entity_materialized ||
        !SetLocalCameraFocus(
            kDeathSpectatorCameraOwner,
            gameplay_state.x,
            gameplay_state.y,
            nullptr)) {
        (void)ClearLocalCameraFocus(kDeathSpectatorCameraOwner);
        g_local_death_spectator.target_participant_id = 0;
        PublishSpectatorTarget(runtime_state, 0, true);
        return;
    }
    PublishSpectatorTarget(
        runtime_state,
        target_participant_id,
        false);
}

void TickLocalDeathSpectator(std::uint64_t now_ms) {
    if (g_local_death_spectator.phase !=
        DeathSpectatorPhase::Inactive) {
        (void)HoldLocalSpectatorDeathVitals();
    }
    if (g_local_death_spectator.phase ==
            DeathSpectatorPhase::DeathPresentation &&
        now_ms >= g_local_death_spectator.death_started_ms &&
        now_ms - g_local_death_spectator.death_started_ms >=
            kDeathPresentationDurationMs) {
        g_local_death_spectator.phase = DeathSpectatorPhase::Spectating;
        g_local_death_spectator.observed_mouse_left_edge_serial =
            GetGameplayMouseLeftEdgeSerial();
        g_local_death_spectator.observed_mouse_right_edge_serial =
            GetGameplayMouseRightEdgeSerial();
        Log(
            "Multiplayer death presentation completed; spectator mode active.");
    }
    PublishLocalDeathSpectatorRuntime(now_ms);
    if (g_local_death_spectator.phase ==
        DeathSpectatorPhase::Spectating) {
        TickLocalSpectatorTarget(now_ms);
    }
}
