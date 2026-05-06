struct BotBoulderDamageProjectionSnapshot {
    bool readable = false;
    uintptr_t requested_target_actor = 0;
    uintptr_t requested_target_health_base = 0;
    const char* requested_target_health_kind = "unknown";
    bool requested_target_health_readable = false;
    float requested_target_hp = 0.0f;
    float requested_target_max_hp = 0.0f;
    uintptr_t target_actor = 0;
    uintptr_t target_health_base = 0;
    const char* target_health_kind = "unknown";
    int progression_level = 0;
    float target_hp = 0.0f;
    float target_max_hp = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float target_radius = 0.0f;
    float target_distance = 0.0f;
    float target_impact_radius = 0.0f;
    float charge = 0.0f;
    float base_damage = 0.0f;
    float projected_damage = 0.0f;
    float damage_output_scale = 0.0f;
    float release_damage_scale = 0.0f;
    float release_damage_floor = 0.0f;
    float release_damage_cap_scale = 0.0f;
    float projected_release_damage = 0.0f;
    float projected_hp_damage = 0.0f;
    bool target_position_readable = false;
    bool target_in_impact = false;
    bool native_radius_damage_eligible = false;
};

float ProjectEarthBoulderReleaseDamage(
    float native_base_damage,
    float release_charge,
    float release_damage_scale,
    float release_damage_floor,
    float release_damage_cap_scale) {
    if (!std::isfinite(native_base_damage) ||
        native_base_damage <= 0.0f ||
        !std::isfinite(release_charge) ||
        release_charge <= 0.0f ||
        !std::isfinite(release_damage_scale) ||
        release_damage_scale <= 0.0f ||
        !std::isfinite(release_damage_floor) ||
        release_damage_floor < 0.0f ||
        !std::isfinite(release_damage_cap_scale) ||
        release_damage_cap_scale <= 0.0f) {
        return 0.0f;
    }

    const auto scaled_base_damage = native_base_damage * release_damage_scale;
    const auto quadratic_damage =
        scaled_base_damage * release_charge * release_charge;
    const auto capped_damage =
        (std::min)(quadratic_damage, scaled_base_damage * release_damage_cap_scale);
    return release_damage_floor <= capped_damage
        ? capped_damage
        : release_damage_floor;
}

bool TryPopulateBoulderProjectionTarget(
    ProcessMemory& memory,
    const BotNativeActiveSpellObjectState& active_spell_state,
    BotBoulderDamageProjectionSnapshot* snapshot,
    uintptr_t target_actor) {
    (void)memory;
    if (snapshot == nullptr || target_actor == 0) {
        return false;
    }

    ActorHealthRuntime target_health{};
    if (!TryReadActorHealthRuntime(target_actor, &target_health) ||
        target_health.hp <= 0.0f) {
        return false;
    }

    auto candidate = *snapshot;
    candidate.target_actor = target_actor;
    candidate.target_health_base = target_health.base_address;
    candidate.target_health_kind = target_health.kind;
    candidate.target_hp = target_health.hp;
    candidate.target_max_hp = target_health.max_hp;
    candidate.target_position_readable = false;
    candidate.target_in_impact = false;
    candidate.native_radius_damage_eligible = false;
    if (kActorPositionXOffset == 0 ||
        kActorPositionYOffset == 0 ||
        !TryReadFiniteFloatField(target_actor, kActorPositionXOffset, &candidate.target_x) ||
        !TryReadFiniteFloatField(target_actor, kActorPositionYOffset, &candidate.target_y)) {
        return false;
    }
    candidate.target_position_readable = true;
    if (kActorCollisionRadiusOffset == 0 ||
        !TryReadFiniteFloatField(target_actor, kActorCollisionRadiusOffset, &candidate.target_radius) ||
        candidate.target_radius < 0.0f ||
        candidate.target_radius > 128.0f) {
        return false;
    }
    if (candidate.target_position_readable &&
        std::isfinite(active_spell_state.object_x) &&
        std::isfinite(active_spell_state.object_y)) {
        const auto target_dx = candidate.target_x - active_spell_state.object_x;
        const auto target_dy = candidate.target_y - active_spell_state.object_y;
        const auto target_distance_squared =
            (target_dx * target_dx) + (target_dy * target_dy);
        candidate.target_distance = std::sqrt(target_distance_squared);
        const float object_radius =
            std::isfinite(active_spell_state.object_radius) &&
                    active_spell_state.object_radius > 0.0f &&
                    active_spell_state.object_radius <= 128.0f
                ? active_spell_state.object_radius
                : 0.0f;
        const auto release_charge = candidate.charge;
        const auto native_secondary_reach_radius =
            object_radius * release_charge * 2.0f;
        const auto native_secondary_reach_radius_squared =
            (native_secondary_reach_radius * native_secondary_reach_radius) +
            (candidate.target_radius * candidate.target_radius);
        candidate.target_impact_radius =
            native_secondary_reach_radius_squared > 0.0f
                ? std::sqrt(native_secondary_reach_radius_squared)
                : 0.0f;
        if (!std::isfinite(candidate.target_impact_radius) ||
            candidate.target_impact_radius <= 0.0f ||
            candidate.target_impact_radius > 192.0f) {
            candidate.target_impact_radius = 0.0f;
        }
        // Native World_QueryRadius uses distance^2 <
        // query_radius^2 + actor_collision_radius^2.
        candidate.target_in_impact =
            candidate.target_impact_radius > 0.0f &&
            std::isfinite(target_distance_squared) &&
            target_distance_squared < native_secondary_reach_radius_squared;
        candidate.native_radius_damage_eligible = candidate.target_in_impact;
    }

    candidate.readable =
        std::isfinite(candidate.projected_damage) &&
        candidate.projected_damage > 0.0f &&
        std::isfinite(candidate.projected_release_damage) &&
        candidate.projected_release_damage > 0.0f &&
        std::isfinite(candidate.projected_hp_damage) &&
        candidate.projected_hp_damage > 0.0f;
    if (!candidate.readable) {
        return false;
    }

    *snapshot = candidate;
    return true;
}

bool IsBoulderProjectionTargetLethal(
    const BotBoulderDamageProjectionSnapshot& snapshot) {
    return snapshot.readable &&
           snapshot.target_actor != 0 &&
           std::isfinite(snapshot.target_hp) &&
           snapshot.target_hp > 0.0f &&
           std::isfinite(snapshot.projected_hp_damage) &&
           snapshot.projected_hp_damage + 0.001f >= snapshot.target_hp;
}

bool FindBestNativeBoulderImpactVictim(
    ProcessMemory& memory,
    const BotNativeActiveSpellObjectState& active_spell_state,
    const BotBoulderDamageProjectionSnapshot& base_snapshot,
    BotBoulderDamageProjectionSnapshot* snapshot) {
    if (snapshot == nullptr || !base_snapshot.readable) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    bool found = false;
    BotBoulderDamageProjectionSnapshot best{};
    for (const auto& actor : actors) {
        if (!actor.tracked_enemy ||
            actor.actor_address == 0 ||
            actor.dead ||
            actor.hp <= 0.0f) {
            continue;
        }

        auto candidate = base_snapshot;
        if (!TryPopulateBoulderProjectionTarget(
                memory,
                active_spell_state,
                &candidate,
                actor.actor_address) ||
            !candidate.native_radius_damage_eligible ||
            !IsBoulderProjectionTargetLethal(candidate)) {
            continue;
        }

        if (!found ||
            candidate.target_hp < best.target_hp ||
            (candidate.target_hp == best.target_hp &&
             candidate.target_distance < best.target_distance)) {
            best = candidate;
            found = true;
        }
    }

    if (!found) {
        return false;
    }

    // native_boulder_impact_victim_scan: release chooses a live enemy that is
    // inside the active Boulder object's recovered native secondary reach.
    *snapshot = best;
    return true;
}

BotBoulderDamageProjectionSnapshot ReadBotBoulderDamageProjectionSnapshot(
    const BotCastProcessingContext& context,
    const BotNativeActiveSpellObjectState& active_spell_state) {
    auto* binding = context.binding;
    auto& memory = *context.memory;

    BotBoulderDamageProjectionSnapshot snapshot{};
    if (!active_spell_state.readable || active_spell_state.object == 0) {
        return snapshot;
    }

    int progression_level = 0;
    if (!TryReadEarthBoulderProgressionLevel(
            binding->ongoing_cast.progression_runtime_address,
            &progression_level)) {
        return snapshot;
    }
    const auto resolved_native_damage = active_spell_state.release_base_damage;
    if (!std::isfinite(resolved_native_damage) ||
        resolved_native_damage <= 0.0f) {
        return snapshot;
    }
    const float release_charge =
        std::isfinite(active_spell_state.charge) &&
                active_spell_state.charge > 0.0f
            ? active_spell_state.charge
            : 0.0f;
    if (release_charge <= 0.0f) {
        return snapshot;
    }
    const auto damage_output_scale = ResolveEarthBoulderDamageOutputScale();
    const auto release_damage_scale = ResolveEarthBoulderReleaseDamageScale();
    const auto release_damage_floor = ResolveEarthBoulderReleaseDamageFloor();
    const auto release_damage_cap_scale = ResolveEarthBoulderReleaseDamageCapScale();
    if (!std::isfinite(damage_output_scale) ||
        damage_output_scale <= 0.0f ||
        !std::isfinite(release_damage_scale) ||
        release_damage_scale <= 0.0f ||
        !std::isfinite(release_damage_floor) ||
        release_damage_floor < 0.0f ||
        !std::isfinite(release_damage_cap_scale) ||
        release_damage_cap_scale <= 0.0f) {
        return snapshot;
    }

    snapshot.progression_level = progression_level;
    snapshot.charge = release_charge;
    snapshot.base_damage = resolved_native_damage;
    snapshot.damage_output_scale = damage_output_scale;
    snapshot.release_damage_scale = release_damage_scale;
    snapshot.release_damage_floor = release_damage_floor;
    snapshot.release_damage_cap_scale = release_damage_cap_scale;
    snapshot.projected_damage =
        snapshot.base_damage * snapshot.charge * snapshot.charge;
    snapshot.projected_release_damage =
        ProjectEarthBoulderReleaseDamage(
            snapshot.base_damage,
            snapshot.charge,
            snapshot.release_damage_scale,
            snapshot.release_damage_floor,
            snapshot.release_damage_cap_scale);
    snapshot.projected_hp_damage = snapshot.projected_release_damage;
    snapshot.readable =
        std::isfinite(snapshot.projected_damage) &&
        snapshot.projected_damage > 0.0f &&
        std::isfinite(snapshot.projected_release_damage) &&
        snapshot.projected_release_damage > 0.0f &&
        std::isfinite(snapshot.projected_hp_damage) &&
        snapshot.projected_hp_damage > 0.0f;
    if (!snapshot.readable) {
        return snapshot;
    }

    const auto current_target_actor = ResolveOngoingCastNativeTargetActor(
        binding,
        binding->ongoing_cast);
    snapshot.requested_target_actor = current_target_actor;
    ActorHealthRuntime requested_target_health{};
    if (TryReadActorHealthRuntime(current_target_actor, &requested_target_health)) {
        snapshot.requested_target_health_readable = true;
        snapshot.requested_target_health_base = requested_target_health.base_address;
        snapshot.requested_target_health_kind = requested_target_health.kind;
        snapshot.requested_target_hp = requested_target_health.hp;
        snapshot.requested_target_max_hp = requested_target_health.max_hp;
    }
    auto current_target_snapshot = snapshot;
    const bool current_target_readable =
        TryPopulateBoulderProjectionTarget(
            memory,
            active_spell_state,
            &current_target_snapshot,
            current_target_actor);
    if (current_target_readable && IsBoulderProjectionTargetLethal(current_target_snapshot)) {
        return current_target_snapshot;
    }

    auto impact_victim_snapshot = snapshot;
    if (FindBestNativeBoulderImpactVictim(
            memory,
            active_spell_state,
            snapshot,
            &impact_victim_snapshot)) {
        return impact_victim_snapshot;
    }

    // Read-only: callers may use the native release-damage projection to
    // release a held Boulder when it can kill the live target. The native
    // impact scan remains available for already-overlapped victims, but this
    // helper never writes guessed native query context.
    if (current_target_readable) {
        return current_target_snapshot;
    }
    return snapshot;
}
