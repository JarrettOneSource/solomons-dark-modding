constexpr std::uint64_t kSharedGameplayPauseTimeoutMs = 60'000;
constexpr std::uint64_t kSharedGameplayPauseRequestFreshnessMs = 2'000;
constexpr std::uint64_t kSharedGameplayPauseAuthorityFreshnessMs = 2'000;

bool IsLocalSynchronizedPauseSurfaceActive(std::string* surface_id) {
    if (surface_id != nullptr) {
        surface_id->clear();
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr || !local->runtime.in_run ||
        local->runtime.run_nonce == 0) {
        return false;
    }

    DebugUiSurfaceSnapshot snapshot;
    if (!TryGetLatestDebugUiSurfaceSnapshot(&snapshot)) {
        return false;
    }

    const auto& observed_surface_id = snapshot.surface_id;
    const bool synchronized_surface =
        observed_surface_id == "pause_menu" ||
        observed_surface_id == "simple_menu" ||
        observed_surface_id == "quick_panel" ||
        observed_surface_id == "settings";
    if (synchronized_surface && surface_id != nullptr) {
        *surface_id = observed_surface_id;
    }
    return synchronized_surface;
}

void PublishLocalMenuPauseRequestRuntimeState() {
    UpdateRuntimeState([&](RuntimeState& state) {
        state.shared_gameplay_pause.local_request_active =
            g_local_transport.local_menu_pause_requested;
        state.shared_gameplay_pause.local_request_epoch =
            g_local_transport.local_menu_pause_request_epoch;
    });
}

void RefreshLocalMenuPauseRequest(std::uint64_t now_ms) {
    (void)now_ms;
    std::string surface_id;
    const bool requested =
        IsLocalSynchronizedPauseSurfaceActive(&surface_id);
    if (requested && !g_local_transport.local_menu_pause_requested) {
        ++g_local_transport.local_menu_pause_request_epoch;
        if (g_local_transport.local_menu_pause_request_epoch == 0) {
            g_local_transport.local_menu_pause_request_epoch = 1;
        }
    }

    g_local_transport.local_menu_pause_requested = requested;
    g_local_transport.local_menu_pause_surface_id =
        requested ? std::move(surface_id) : std::string{};
    PublishLocalMenuPauseRequestRuntimeState();
}

const ParticipantInfo* FindHostPauseRequestParticipant(
    const RuntimeState& runtime_state,
    std::uint64_t participant_id) {
    if (participant_id == g_local_transport.local_peer_id) {
        return FindLocalParticipant(runtime_state);
    }
    return FindParticipant(runtime_state, participant_id);
}

bool IsHostPauseRequestParticipantCurrent(
    const RuntimeState& runtime_state,
    std::uint64_t participant_id,
    std::uint32_t run_nonce) {
    const auto* participant =
        FindHostPauseRequestParticipant(runtime_state, participant_id);
    return participant != nullptr && participant->runtime.in_run &&
           participant->runtime.run_nonce == run_nonce;
}

void ApplyHostMenuPauseRequest(
    std::uint64_t participant_id,
    std::uint32_t run_nonce,
    std::uint32_t request_epoch,
    bool requested,
    std::uint64_t now_ms) {
    if (!IsLocalTransportHost() || participant_id == 0) {
        return;
    }

    auto& request =
        g_local_transport.host_menu_pause_requests_by_participant[
            participant_id];
    request.last_update_ms = now_ms;
    if (!requested) {
        request.requested = false;
        request.timed_out_until_release = false;
        request.deadline_ms = 0;
        request.run_nonce = run_nonce;
        request.request_epoch = request_epoch;
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    if (request_epoch == 0 || run_nonce == 0 ||
        !IsHostPauseRequestParticipantCurrent(
            runtime_state,
            participant_id,
            run_nonce)) {
        request = HostMenuPauseRequestState{};
        return;
    }

    // A new epoch cannot extend an active request. A participant must first
    // publish a release, including after the authority times the request out.
    if (request.requested) {
        return;
    }

    request.request_epoch = request_epoch;
    request.run_nonce = run_nonce;
    request.requested = true;
    request.timed_out_until_release = false;
    request.deadline_ms = now_ms + kSharedGameplayPauseTimeoutMs;
}

void PublishHostSharedGameplayPauseRuntimeState(
    const RuntimeState& runtime_state,
    bool pause_active,
    bool timed_out,
    std::uint64_t origin_participant_id,
    std::uint64_t aggregate_deadline_ms,
    std::uint64_t now_ms) {
    const auto* local = FindLocalParticipant(runtime_state);
    SharedGameplayPauseRuntimeInfo next;
    next.valid = local != nullptr && local->runtime.in_run &&
                 local->runtime.run_nonce != 0;
    next.pause_active = next.valid && pause_active;
    next.timed_out = next.valid && timed_out;
    next.local_request_active =
        g_local_transport.local_menu_pause_requested;
    next.local_request_epoch =
        g_local_transport.local_menu_pause_request_epoch;
    next.run_nonce = next.valid ? local->runtime.run_nonce : 0;
    next.authority_participant_id =
        next.valid ? g_local_transport.local_peer_id : 0;
    next.origin_participant_id = next.valid ? origin_participant_id : 0;
    next.received_ms = now_ms;
    if (next.pause_active && aggregate_deadline_ms > now_ms) {
        next.deadline_remaining_ms = static_cast<std::uint32_t>(
            (std::min<std::uint64_t>)(
                aggregate_deadline_ms - now_ms,
                (std::numeric_limits<std::uint32_t>::max)()));
    }

    const auto& previous = runtime_state.shared_gameplay_pause;
    const bool status_changed =
        previous.valid != next.valid ||
        previous.pause_active != next.pause_active ||
        previous.timed_out != next.timed_out ||
        previous.origin_participant_id != next.origin_participant_id ||
        previous.run_nonce != next.run_nonce;
    UpdateRuntimeState([&](RuntimeState& state) {
        state.shared_gameplay_pause = next;
    });
    if (status_changed) {
        Log(
            "Shared gameplay pause state changed. active=" +
            std::to_string(next.pause_active ? 1 : 0) +
            " timed_out=" + std::to_string(next.timed_out ? 1 : 0) +
            " origin_participant_id=" +
            std::to_string(next.origin_participant_id) +
            " run_nonce=" + std::to_string(next.run_nonce));
    }
}

void RefreshHostSharedGameplayPause(std::uint64_t now_ms) {
    if (!IsLocalTransportHost()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr || !local->runtime.in_run ||
        local->runtime.run_nonce == 0) {
        g_local_transport.host_menu_pause_requests_by_participant.clear();
        PublishHostSharedGameplayPauseRuntimeState(
            runtime_state,
            false,
            false,
            0,
            0,
            now_ms);
        return;
    }

    ApplyHostMenuPauseRequest(
        g_local_transport.local_peer_id,
        local->runtime.run_nonce,
        g_local_transport.local_menu_pause_request_epoch,
        g_local_transport.local_menu_pause_requested,
        now_ms);

    bool pause_active = false;
    bool timed_out = false;
    std::uint64_t origin_participant_id = 0;
    std::uint64_t aggregate_deadline_ms = 0;
    for (auto request_it =
             g_local_transport.host_menu_pause_requests_by_participant.begin();
         request_it !=
             g_local_transport.host_menu_pause_requests_by_participant.end();) {
        const auto participant_id = request_it->first;
        auto& request = request_it->second;
        const bool local_request =
            participant_id == g_local_transport.local_peer_id;
        const bool stale =
            !local_request &&
            (now_ms < request.last_update_ms ||
             now_ms - request.last_update_ms >
                 kSharedGameplayPauseRequestFreshnessMs);
        const bool current_participant =
            IsHostPauseRequestParticipantCurrent(
                runtime_state,
                participant_id,
                request.run_nonce);
        if (!request.requested || stale || !current_participant) {
            request_it =
                g_local_transport.host_menu_pause_requests_by_participant.erase(
                    request_it);
            continue;
        }

        if (!request.timed_out_until_release &&
            now_ms >= request.deadline_ms) {
            request.timed_out_until_release = true;
        }
        if (request.timed_out_until_release) {
            timed_out = true;
            if (origin_participant_id == 0) {
                origin_participant_id = participant_id;
            }
            ++request_it;
            continue;
        }

        pause_active = true;
        if (request.deadline_ms > aggregate_deadline_ms ||
            (request.deadline_ms == aggregate_deadline_ms &&
             (origin_participant_id == 0 ||
              participant_id < origin_participant_id))) {
            aggregate_deadline_ms = request.deadline_ms;
            origin_participant_id = participant_id;
        }
        ++request_it;
    }

    PublishHostSharedGameplayPauseRuntimeState(
        runtime_state,
        pause_active,
        timed_out,
        origin_participant_id,
        aggregate_deadline_ms,
        now_ms);
}

void ApplyAuthoritativeSharedGameplayPause(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t origin_participant_id,
    std::uint32_t deadline_remaining_ms,
    bool pause_active,
    bool timed_out,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() || authority_participant_id == 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const bool valid =
        local != nullptr && local->runtime.in_run && run_nonce != 0 &&
        local->runtime.run_nonce == run_nonce;
    SharedGameplayPauseRuntimeInfo next;
    next.valid = valid;
    next.pause_active =
        valid && pause_active && deadline_remaining_ms != 0;
    next.timed_out = valid && timed_out;
    next.local_request_active =
        runtime_state.shared_gameplay_pause.local_request_active;
    next.local_request_epoch =
        runtime_state.shared_gameplay_pause.local_request_epoch;
    next.run_nonce = valid ? run_nonce : 0;
    next.deadline_remaining_ms =
        next.pause_active ? deadline_remaining_ms : 0;
    next.authority_participant_id =
        valid ? authority_participant_id : 0;
    next.origin_participant_id = valid ? origin_participant_id : 0;
    next.received_ms = now_ms;
    UpdateRuntimeState([&](RuntimeState& state) {
        state.shared_gameplay_pause = next;
    });
}

template <typename Packet>
void PopulateSharedGameplayPausePacketFieldsImpl(
    const RuntimeState& runtime_state,
    Packet* packet) {
    if (packet == nullptr) {
        return;
    }

    packet->local_menu_pause_request_epoch =
        runtime_state.shared_gameplay_pause.local_request_epoch;
    packet->local_menu_pause_requested =
        runtime_state.shared_gameplay_pause.local_request_active ? 1 : 0;
    if (!g_local_transport.is_host ||
        !runtime_state.shared_gameplay_pause.valid) {
        return;
    }

    const auto& pause = runtime_state.shared_gameplay_pause;
    packet->shared_gameplay_pause_active = pause.pause_active ? 1 : 0;
    packet->shared_gameplay_pause_timed_out = pause.timed_out ? 1 : 0;
    packet->shared_gameplay_pause_deadline_remaining_ms =
        pause.deadline_remaining_ms;
    packet->shared_gameplay_pause_origin_participant_id =
        pause.origin_participant_id;
}

void PopulateSharedGameplayPausePacketFields(
    const RuntimeState& runtime_state,
    StatePacket* packet) {
    PopulateSharedGameplayPausePacketFieldsImpl(runtime_state, packet);
}

void PopulateSharedGameplayPausePacketFields(
    const RuntimeState& runtime_state,
    ParticipantFramePacket* packet) {
    PopulateSharedGameplayPausePacketFieldsImpl(runtime_state, packet);
}

bool ShouldPauseForSharedGameplayMenu() {
    if (!g_local_transport.initialized) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto& pause = runtime_state.shared_gameplay_pause;
    if (!pause.valid || !pause.pause_active ||
        pause.deadline_remaining_ms == 0) {
        return false;
    }
    if (g_local_transport.is_host) {
        return true;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (pause.received_ms == 0 || now_ms < pause.received_ms) {
        return false;
    }
    const auto age_ms = now_ms - pause.received_ms;
    return age_ms <= kSharedGameplayPauseAuthorityFreshnessMs &&
           age_ms < pause.deadline_remaining_ms;
}
