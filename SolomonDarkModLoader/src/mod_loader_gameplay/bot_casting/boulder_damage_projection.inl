struct BotBoulderDamageProjectionSnapshot {
    bool readable = false;
    uintptr_t target_actor = 0;
    uintptr_t target_health_base = 0;
    uintptr_t stat_source = 0;
    uintptr_t stat_vtable = 0;
    uintptr_t damage_getter = 0;
    const char* target_health_kind = "unknown";
    int statbook_level = 1;
    float target_hp = 0.0f;
    float target_max_hp = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float target_radius = 0.0f;
    float target_distance = 0.0f;
    float target_impact_radius = 0.0f;
    float target_damage_scale = 0.0f;
    float charge = 0.0f;
    float base_damage = 0.0f;
    float statbook_damage = 0.0f;
    float projected_damage = 0.0f;
    DWORD damage_getter_seh = 0;
    bool damage_getter_attempted = false;
    bool native_damage_scale_available = false;
    bool target_position_readable = false;
    bool target_in_impact = false;
    bool impact_context_write_attempted = false;
    bool impact_context_write_ok = false;
    float impact_context_x = 0.0f;
    float impact_context_y = 0.0f;
    float impact_context_radius = 0.0f;
};

BotBoulderDamageProjectionSnapshot ReadBotBoulderDamageProjectionSnapshot(
    const BotCastProcessingContext& context,
    const BotActiveSpellObjectSnapshot& active_spell_snapshot) {
    auto* binding = context.binding;
    auto& memory = *context.memory;

    BotBoulderDamageProjectionSnapshot snapshot{};
    if (!active_spell_snapshot.readable || active_spell_snapshot.object == 0) {
        return snapshot;
    }

    snapshot.target_actor = ResolveOngoingCastNativeTargetActor(
        binding,
        binding->ongoing_cast);
    ActorHealthRuntime target_health{};
    if (!TryReadActorHealthRuntime(snapshot.target_actor, &target_health) ||
        target_health.hp <= 0.0f) {
        return snapshot;
    }

    int statbook_level = 1;
    const auto resolved_statbook_damage = ResolveEarthBoulderBaseDamage(
        binding,
        binding->ongoing_cast.progression_runtime_address,
        &statbook_level);
    if (!std::isfinite(resolved_statbook_damage) ||
        resolved_statbook_damage <= 0.0f) {
        return snapshot;
    }
    const float release_charge =
        std::isfinite(active_spell_snapshot.object_f74) &&
                active_spell_snapshot.object_f74 > 0.0f
            ? active_spell_snapshot.object_f74
            : 0.0f;
    if (release_charge <= 0.0f) {
        return snapshot;
    }

    snapshot.target_health_base = target_health.base_address;
    snapshot.target_health_kind = target_health.kind;
    snapshot.statbook_level = statbook_level;
    snapshot.target_hp = target_health.hp;
    snapshot.target_max_hp = target_health.max_hp;
    if (kActorPositionXOffset != 0 &&
        kActorPositionYOffset != 0 &&
        memory.IsReadableRange(
            snapshot.target_actor + kActorPositionXOffset,
            sizeof(float)) &&
        memory.IsReadableRange(
            snapshot.target_actor + kActorPositionYOffset,
            sizeof(float))) {
        snapshot.target_x =
            memory.ReadFieldOr<float>(
                snapshot.target_actor,
                kActorPositionXOffset,
                0.0f);
        snapshot.target_y =
            memory.ReadFieldOr<float>(
                snapshot.target_actor,
                kActorPositionYOffset,
                0.0f);
        snapshot.target_position_readable =
            std::isfinite(snapshot.target_x) &&
            std::isfinite(snapshot.target_y);
    }
    if (kActorCollisionRadiusOffset != 0 &&
        memory.IsReadableRange(
            snapshot.target_actor + kActorCollisionRadiusOffset,
            sizeof(float))) {
        snapshot.target_radius =
            memory.ReadFieldOr<float>(
                snapshot.target_actor,
                kActorCollisionRadiusOffset,
                0.0f);
        if (!std::isfinite(snapshot.target_radius) ||
            snapshot.target_radius < 0.0f ||
            snapshot.target_radius > 128.0f) {
            snapshot.target_radius = 0.0f;
        }
    }
    if (snapshot.target_position_readable &&
        std::isfinite(active_spell_snapshot.object_x) &&
        std::isfinite(active_spell_snapshot.object_y)) {
        const auto target_dx = snapshot.target_x - active_spell_snapshot.object_x;
        const auto target_dy = snapshot.target_y - active_spell_snapshot.object_y;
        snapshot.target_distance =
            std::sqrt((target_dx * target_dx) + (target_dy * target_dy));
        const float object_radius =
            std::isfinite(active_spell_snapshot.object_radius) &&
                    active_spell_snapshot.object_radius > 0.0f &&
                    active_spell_snapshot.object_radius <= 128.0f
                ? active_spell_snapshot.object_radius
                : 0.0f;
        snapshot.target_impact_radius = object_radius + snapshot.target_radius;
        if (object_radius <= 0.0f ||
            !std::isfinite(snapshot.target_impact_radius) ||
            snapshot.target_impact_radius <= 0.0f ||
            snapshot.target_impact_radius > 256.0f) {
            snapshot.target_impact_radius = 0.0f;
        }
        snapshot.target_in_impact =
            snapshot.target_impact_radius > 0.0f &&
            std::isfinite(snapshot.target_distance) &&
            snapshot.target_distance <= snapshot.target_impact_radius + 0.001f;
    }
    snapshot.charge = release_charge;
    snapshot.statbook_damage = resolved_statbook_damage;
    snapshot.base_damage = resolved_statbook_damage;
    snapshot.projected_damage =
        snapshot.base_damage * snapshot.charge * snapshot.charge;
    snapshot.readable =
        std::isfinite(snapshot.projected_damage) &&
        snapshot.projected_damage > 0.0f;
    if (!snapshot.readable) {
        return snapshot;
    }

    DWORD damage_getter_exception_code = 0;
    snapshot.stat_source =
        memory.ReadFieldOr<std::uintptr_t>(active_spell_snapshot.object, 0x58, 0);
    if (snapshot.stat_source != 0 &&
        memory.IsReadableRange(snapshot.stat_source, sizeof(std::uintptr_t))) {
        snapshot.stat_vtable =
            memory.ReadValueOr<std::uintptr_t>(snapshot.stat_source, 0);
        if (snapshot.stat_vtable != 0 &&
            memory.IsReadableRange(snapshot.stat_vtable + 0x100, sizeof(std::uintptr_t))) {
            snapshot.damage_getter =
                memory.ReadValueOr<std::uintptr_t>(snapshot.stat_vtable + 0x100, 0);
        }
    }
    if (snapshot.stat_source != 0 &&
        snapshot.target_in_impact &&
        snapshot.target_position_readable &&
        std::isfinite(active_spell_snapshot.object_x) &&
        std::isfinite(active_spell_snapshot.object_y) &&
        std::isfinite(snapshot.target_impact_radius) &&
        snapshot.target_impact_radius > 0.0f) {
        const float object_radius =
            std::isfinite(active_spell_snapshot.object_radius) &&
                    active_spell_snapshot.object_radius > 0.0f
                ? active_spell_snapshot.object_radius
                : 0.0f;
        const float context_radius =
            object_radius > snapshot.target_impact_radius
                ? object_radius
                : snapshot.target_impact_radius;
        if (std::isfinite(context_radius) && context_radius > 0.0f) {
            snapshot.impact_context_write_attempted = true;
            snapshot.impact_context_x = active_spell_snapshot.object_x - context_radius;
            snapshot.impact_context_y = active_spell_snapshot.object_y;
            snapshot.impact_context_radius = context_radius;
            const bool write_x =
                memory.TryWriteField<float>(
                    snapshot.stat_source,
                    0x8BCC,
                    snapshot.impact_context_x);
            const bool write_y =
                memory.TryWriteField<float>(
                    snapshot.stat_source,
                    0x8BD0,
                    snapshot.impact_context_y);
            const bool write_radius =
                memory.TryWriteField<float>(
                    snapshot.stat_source,
                    0x8BD4,
                    snapshot.impact_context_radius);
            const bool write_y_extent =
                memory.TryWriteField<float>(
                    snapshot.stat_source,
                    0x8BD8,
                    0.0f);
            snapshot.impact_context_write_ok =
                write_x && write_y && write_radius && write_y_extent;
        }
    }
    if (snapshot.damage_getter != 0 &&
        memory.IsExecutableRange(snapshot.damage_getter, 1)) {
        snapshot.damage_getter_attempted = true;
        snapshot.native_damage_scale_available =
            CallNativeTwoFloatGetterSafe(
                snapshot.damage_getter,
                snapshot.stat_source,
                snapshot.target_x,
                snapshot.target_y,
                &snapshot.target_damage_scale,
                &damage_getter_exception_code) &&
            snapshot.target_position_readable &&
            std::isfinite(snapshot.target_damage_scale) &&
            snapshot.target_damage_scale > 0.0f;
        snapshot.damage_getter_seh = damage_getter_exception_code;
    }

    // The vtable getter is useful as a native reachability diagnostic,
    // but damage magnitude follows the statbook "damage x size^2"
    // formula recovered from the Earth release path and confirmed
    // against live HP deltas.
    return snapshot;
}
