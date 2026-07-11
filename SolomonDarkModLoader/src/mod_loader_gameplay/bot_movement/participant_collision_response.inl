struct WizardParticipantCollisionSubject {
    ParticipantEntityBinding* binding = nullptr;
    uintptr_t actor_address = 0;
    uintptr_t world_address = 0;
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
    bool movable = false;
    bool local_player = false;
    bool native_remote = false;
    bool moved = false;
};

bool TryReadWizardParticipantCollisionSubject(
    uintptr_t actor_address,
    ParticipantEntityBinding* binding,
    bool movable,
    WizardParticipantCollisionSubject* subject) {
    if (subject == nullptr) {
        return false;
    }

    *subject = WizardParticipantCollisionSubject{};
    if (actor_address == 0 || kActorCollisionRadiusOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = 0;
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &world_address) ||
        world_address == 0 ||
        !TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorCollisionRadiusOffset, &radius) ||
        radius <= 0.0f) {
        return false;
    }

    subject->binding = binding;
    subject->actor_address = actor_address;
    subject->world_address = world_address;
    subject->x = x;
    subject->y = y;
    subject->radius = radius;
    subject->movable = movable;
    return true;
}

void ResolveWizardParticipantActorCollisions() {
    auto& memory = ProcessMemory::Instance();
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);

    std::vector<WizardParticipantCollisionSubject> subjects;
    uintptr_t gameplay_address = 0;
    uintptr_t local_player_actor = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address) &&
        gameplay_address != 0 &&
        TryResolvePlayerActorForSlot(gameplay_address, 0, &local_player_actor) &&
        local_player_actor != 0) {
        WizardParticipantCollisionSubject player_subject;
        if (TryReadWizardParticipantCollisionSubject(
                local_player_actor,
                nullptr,
                false,
                &player_subject)) {
            player_subject.local_player = true;
            subjects.push_back(player_subject);
        }
    }

    for (auto& binding : g_participant_entities) {
        if (!IsWizardParticipantKind(binding.kind) ||
            binding.actor_address == 0 ||
            binding.actor_address == local_player_actor ||
            IsActorRuntimeDead(binding.actor_address)) {
            continue;
        }

        WizardParticipantCollisionSubject subject;
        if (!TryReadWizardParticipantCollisionSubject(
                binding.actor_address,
                &binding,
                true,
                &subject)) {
            continue;
        }

        binding.materialized_world_address = subject.world_address;
        subject.native_remote = IsNativeRemoteParticipantBinding(&binding);
        subjects.push_back(subject);
    }

    if (subjects.size() < 2) {
        return;
    }

    constexpr float kParticipantCollisionPadding = 0.25f;
    constexpr float kParticipantCollisionEpsilon = 0.0001f;
    bool any_moved = false;
    for (int pass = 0; pass < 3; ++pass) {
        bool pass_moved = false;
        for (std::size_t left_index = 0; left_index < subjects.size(); ++left_index) {
            for (std::size_t right_index = left_index + 1; right_index < subjects.size(); ++right_index) {
                auto& left = subjects[left_index];
                auto& right = subjects[right_index];
                const bool native_player_pair =
                    (left.local_player && right.native_remote) ||
                    (right.local_player && left.native_remote);
                // Never run loader collision response for a local-player vs
                // native-remote-mirror pair. Pushing the local player creates a
                // cross-instance feedback loop (each instance displaces its own
                // player against the other's lagged mirror, which then replicates
                // back) -> endless oscillation that never converges when the two
                // players are near each other. Pushing the mirror instead leaves
                // it permanently offset from the peer's true replicated position
                // (by radius+radius+padding), breaking remote convergence. Real
                // player separation is governed by the authoritative simulation
                // and replication; the local mirror must faithfully reflect the
                // peer's transform, so we skip the pair entirely here.
                if (native_player_pair) {
                    continue;
                }
                const bool left_movable = left.movable;
                const bool right_movable = right.movable;
                if (left.world_address != right.world_address ||
                    (!left_movable && !right_movable)) {
                    continue;
                }

                const float minimum_separation =
                    left.radius + right.radius + kParticipantCollisionPadding;
                if (minimum_separation <= 0.0f) {
                    continue;
                }

                float direction_x = right.x - left.x;
                float direction_y = right.y - left.y;
                const float distance_sq =
                    direction_x * direction_x + direction_y * direction_y;
                float distance = 0.0f;
                if (distance_sq > kParticipantCollisionEpsilon) {
                    distance = std::sqrt(distance_sq);
                    direction_x /= distance;
                    direction_y /= distance;
                } else {
                    direction_x = left.actor_address < right.actor_address ? 1.0f : -1.0f;
                    direction_y = 0.0f;
                }

                const float overlap = minimum_separation - distance;
                if (overlap <= 0.0f) {
                    continue;
                }

                if (left_movable && right_movable) {
                    const float half_overlap = overlap * 0.5f;
                    left.x -= direction_x * half_overlap;
                    left.y -= direction_y * half_overlap;
                    right.x += direction_x * half_overlap;
                    right.y += direction_y * half_overlap;
                    left.moved = true;
                    right.moved = true;
                } else if (left_movable) {
                    left.x -= direction_x * overlap;
                    left.y -= direction_y * overlap;
                    left.moved = true;
                } else if (right_movable) {
                    right.x += direction_x * overlap;
                    right.y += direction_y * overlap;
                    right.moved = true;
                }
                any_moved = true;
                pass_moved = true;
            }
        }
        if (!pass_moved) {
            break;
        }
    }

    if (!any_moved) {
        return;
    }

    static std::uint64_t s_last_collision_response_failure_log_ms = 0;
    auto LogCollisionResponseFailure = [&](const std::string& message) {
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_collision_response_failure_log_ms < 1000) {
            return;
        }
        s_last_collision_response_failure_log_ms = now_ms;
        Log("[bots] participant collision response failed. " + message);
    };

    const auto rebind_actor_address = memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
    for (auto& subject : subjects) {
        if (!subject.moved ||
            (!subject.movable && !subject.local_player) ||
            (subject.binding == nullptr && !subject.local_player)) {
            continue;
        }

        if (!memory.TryWriteField(subject.actor_address, kActorPositionXOffset, subject.x) ||
            !memory.TryWriteField(subject.actor_address, kActorPositionYOffset, subject.y)) {
            LogCollisionResponseFailure(
                "position_write actor=" + HexString(subject.actor_address) +
                " bot_id=" + (subject.binding != nullptr
                                  ? std::to_string(subject.binding->bot_id)
                                  : std::string("local")));
            continue;
        }

        DWORD rebind_exception_code = 0;
        if (rebind_actor_address == 0 ||
            !CallWorldCellGridRebindActorSafe(
                rebind_actor_address,
                subject.world_address,
                subject.actor_address,
                &rebind_exception_code)) {
            LogCollisionResponseFailure(
                "rebind actor=" + HexString(subject.actor_address) +
                " bot_id=" + (subject.binding != nullptr
                                  ? std::to_string(subject.binding->bot_id)
                                  : std::string("local")) +
                " world=" + HexString(subject.world_address) +
                " exception=" + HexString(rebind_exception_code));
        }

        if (subject.binding != nullptr) {
            subject.binding->materialized_world_address = subject.world_address;
            PublishParticipantGameplaySnapshot(*subject.binding);
        }
    }
}
