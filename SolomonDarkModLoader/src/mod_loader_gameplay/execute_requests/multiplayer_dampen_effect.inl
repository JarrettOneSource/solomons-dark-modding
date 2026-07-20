namespace {

constexpr float kMultiplayerDampenRadius = 800.0f;
constexpr float kMultiplayerDampenMinimumRepelSpeed = 8.0f;
constexpr float kMultiplayerDampenMaximumRepelSpeed = 64.0f;
constexpr int kMultiplayerDampenMageTypeADisruptTicks = 600;
constexpr int kMultiplayerDampenMageTypeBDisruptTicks = 500;
constexpr std::uint32_t kMultiplayerDampenDisruptableFlag = 0x2u;
constexpr std::uint32_t kMultiplayerDampenProjectileFlag = 0x100u;
constexpr std::uint32_t kMultiplayerDampenMageTypeA = 0x03EBu;
constexpr std::uint32_t kMultiplayerDampenMageTypeB = 0x03F2u;

std::uint64_t BuildDampenActorChanceHash(
    const PendingMultiplayerDampenEffectRequest& request,
    const SDModSceneActorState& actor) {
    auto value = request.owner_participant_id;
    value ^= static_cast<std::uint64_t>(request.cast_sequence) *
             0x9E3779B185EBCA87ull;
    value ^= static_cast<std::uint64_t>(actor.object_type_id) *
             0xC2B2AE3D27D4EB4Full;
    const auto network_actor_id =
        multiplayer::GetLocalRunEnemyNetworkActorId(actor.actor_address);
    if (network_actor_id != 0) {
        value ^= network_actor_id * 0x165667B19E3779F9ull;
    }
    value ^= value >> 33;
    value *= 0xFF51AFD7ED558CCDull;
    value ^= value >> 33;
    return value;
}

bool IsPlayerOwnedDampenProjectile(const SDModSceneActorState& actor) {
    return actor.actor_slot >= 0 &&
           actor.actor_slot < static_cast<int>(kGameplayPlayerSlotCount);
}

bool TryRepelDampenProjectile(
    const PendingMultiplayerDampenEffectRequest& request,
    const SDModSceneActorState& actor) {
    auto dx = actor.x - request.position_x;
    auto dy = actor.y - request.position_y;
    auto length = std::sqrt(dx * dx + dy * dy);
    if (!std::isfinite(length)) {
        return false;
    }
    if (length <= 0.001f) {
        const auto hash = BuildDampenActorChanceHash(request, actor);
        constexpr float kRadiansPerByte =
            6.28318530717958647692f / 256.0f;
        const auto radians =
            static_cast<float>(hash & 0xFFu) * kRadiansPerByte;
        dx = std::cos(radians);
        dy = std::sin(radians);
    } else {
        dx /= length;
        dy /= length;
    }

    auto& memory = ProcessMemory::Instance();
    float motion_x = 0.0f;
    float motion_y = 0.0f;
    float repel_speed = kMultiplayerDampenMinimumRepelSpeed;
    if (memory.TryReadField(
            actor.actor_address,
            kSpellEffectMotionXOffset,
            &motion_x) &&
        memory.TryReadField(
            actor.actor_address,
            kSpellEffectMotionYOffset,
            &motion_y) &&
        std::isfinite(motion_x) &&
        std::isfinite(motion_y)) {
        const auto current_speed =
            std::sqrt(motion_x * motion_x + motion_y * motion_y);
        if (std::isfinite(current_speed)) {
            repel_speed = (std::clamp)(
                current_speed,
                kMultiplayerDampenMinimumRepelSpeed,
                kMultiplayerDampenMaximumRepelSpeed);
        }
    }

    const auto wrote_direction =
        memory.TryWriteField(
            actor.actor_address,
            kProjectileDirectionXOffset,
            dx) &&
        memory.TryWriteField(
            actor.actor_address,
            kProjectileDirectionYOffset,
            dy);
    const auto wrote_motion =
        memory.TryWriteField(
            actor.actor_address,
            kSpellEffectMotionXOffset,
            dx * repel_speed) &&
        memory.TryWriteField(
            actor.actor_address,
            kSpellEffectMotionYOffset,
            dy * repel_speed);
    const auto cleared_target =
        kActorCurrentTargetActorOffset != 0 &&
        memory.TryWriteField<uintptr_t>(
            actor.actor_address,
            kActorCurrentTargetActorOffset,
            0);
    (void)cleared_target;
    return wrote_direction || wrote_motion;
}

bool TryDisruptDampenMage(const SDModSceneActorState& actor) {
    auto& memory = ProcessMemory::Instance();
    if (actor.object_type_id == kMultiplayerDampenMageTypeA) {
        return memory.TryWriteField<std::int32_t>(
            actor.actor_address,
            kMage3EbDampenDisruptTicksOffset,
            kMultiplayerDampenMageTypeADisruptTicks);
    }
    if (actor.object_type_id == kMultiplayerDampenMageTypeB) {
        const bool cleared_a = memory.TryWriteField<std::int32_t>(
            actor.actor_address,
            kMage3F2DampenInterruptStateAOffset,
            0);
        const bool cleared_b = memory.TryWriteField<std::int32_t>(
            actor.actor_address,
            kMage3F2DampenInterruptStateBOffset,
            0);
        const bool wrote_ticks = memory.TryWriteField<std::int32_t>(
            actor.actor_address,
            kMage3F2DampenDisruptTicksOffset,
            kMultiplayerDampenMageTypeBDisruptTicks);
        return cleared_a && cleared_b && wrote_ticks;
    }
    return false;
}

bool TryDispelDampenShield(
    const PendingMultiplayerDampenEffectRequest& request,
    const SDModSceneActorState& actor) {
    if ((BuildDampenActorChanceHash(request, actor) & 1ull) != 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float shield_strength = 0.0f;
    if (!memory.TryReadField(
            actor.actor_address,
            kActorDampenShieldStrengthOffset,
            &shield_strength) ||
        !std::isfinite(shield_strength) ||
        shield_strength <= 0.001f ||
        shield_strength > 1000000.0f) {
        return false;
    }
    return memory.TryWriteField<float>(
        actor.actor_address,
        kActorDampenShieldStrengthOffset,
        0.0f);
}

}  // namespace

bool ExecuteMultiplayerDampenEffectNow(
    const PendingMultiplayerDampenEffectRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    SDModSceneState scene{};
    if (!TryGetSceneState(&scene) ||
        !scene.valid ||
        scene.kind != "arena") {
        if (error_message != nullptr) {
            *error_message = "Dampen requires an active arena scene.";
        }
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        if (error_message != nullptr) {
            *error_message = "Dampen could not enumerate arena actors.";
        }
        return false;
    }

    const auto radius_sq =
        kMultiplayerDampenRadius * kMultiplayerDampenRadius;
    std::size_t actors_in_radius = 0;
    std::size_t projectiles_repelled = 0;
    std::size_t mages_disrupted = 0;
    std::size_t shields_dispelled = 0;
    std::vector<uintptr_t> repelled_projectile_samples;
    std::vector<uintptr_t> disrupted_mage_samples;
    for (const auto& actor : actors) {
        if (!actor.valid ||
            actor.actor_address == 0 ||
            !std::isfinite(actor.x) ||
            !std::isfinite(actor.y)) {
            continue;
        }
        const auto dx = actor.x - request.position_x;
        const auto dy = actor.y - request.position_y;
        const auto distance_sq = dx * dx + dy * dy;
        if (!std::isfinite(distance_sq) || distance_sq > radius_sq) {
            continue;
        }
        actors_in_radius += 1;

        if ((actor.object_header_word &
             kMultiplayerDampenProjectileFlag) != 0 &&
            !IsPlayerOwnedDampenProjectile(actor) &&
            TryRepelDampenProjectile(request, actor)) {
            projectiles_repelled += 1;
            if (repelled_projectile_samples.size() < 8) {
                repelled_projectile_samples.push_back(actor.actor_address);
            }
        }

        // The stock Dampen dispatcher gates shields and the two mage families
        // on object-header bit 0x2. That capability is not equivalent to
        // arena-enemy membership, so tracked_enemy is not a valid behavior
        // gate for this spell.
        if ((actor.object_header_word &
             kMultiplayerDampenDisruptableFlag) == 0) {
            continue;
        }
        if (TryDisruptDampenMage(actor)) {
            mages_disrupted += 1;
            if (disrupted_mage_samples.size() < 8) {
                disrupted_mage_samples.push_back(actor.actor_address);
            }
        }
        if (TryDispelDampenShield(request, actor)) {
            shields_dispelled += 1;
        }
    }

    auto describe_samples = [](const std::vector<uintptr_t>& samples) {
        std::ostringstream stream;
        for (std::size_t index = 0; index < samples.size(); ++index) {
            if (index != 0) {
                stream << ',';
            }
            stream << HexString(samples[index]);
        }
        return stream.str();
    };
    QueueDebugUiMultiplayerDampenPresentation(
        request.owner_participant_id,
        request.cast_sequence);
    Log(
        "Multiplayer Dampen behavior applied. owner_participant_id=" +
        std::to_string(request.owner_participant_id) +
        " cast_sequence=" + std::to_string(request.cast_sequence) +
        " position=(" + std::to_string(request.position_x) + "," +
        std::to_string(request.position_y) + ")" +
        " radius=" + std::to_string(kMultiplayerDampenRadius) +
        " mage_type_a_ticks=" +
        std::to_string(kMultiplayerDampenMageTypeADisruptTicks) +
        " mage_type_b_ticks=" +
        std::to_string(kMultiplayerDampenMageTypeBDisruptTicks) +
        " authority_instance=" +
        std::to_string(multiplayer::IsLocalTransportHost() ? 1 : 0) +
        " scene_actor_count=" + std::to_string(actors.size()) +
        " actors_in_radius=" + std::to_string(actors_in_radius) +
        " projectiles_repelled=" +
        std::to_string(projectiles_repelled) +
        " mages_disrupted=" + std::to_string(mages_disrupted) +
        " shields_dispelled=" + std::to_string(shields_dispelled) +
        " projectile_samples=" +
        describe_samples(repelled_projectile_samples) +
        " mage_samples=" + describe_samples(disrupted_mage_samples));
    return true;
}
