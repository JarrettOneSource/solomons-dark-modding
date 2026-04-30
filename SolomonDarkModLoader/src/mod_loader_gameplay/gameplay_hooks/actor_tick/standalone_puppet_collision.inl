// The loader-owned standalone puppet bot is not registered in the world
// movement controller's primary collider list, so the stock tick never applies
// collision response to it. Replicate a simple circle-vs-circle push here:
// after `pusher_actor_address` ticks, compare its radius-inflated position
// against each tracked standalone puppet and nudge the puppet along the
// separating axis until the radii no longer overlap.
void ApplyStandalonePuppetCollisionPushFromActor(uintptr_t pusher_actor_address) {
    if (pusher_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto pusher_x =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorPositionXOffset, 0.0f);
    const auto pusher_y =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorPositionYOffset, 0.0f);
    const auto pusher_radius =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorCollisionRadiusOffset, 0.0f);
    if (!std::isfinite(pusher_x) || !std::isfinite(pusher_y) ||
        !std::isfinite(pusher_radius) || pusher_radius <= 0.0f) {
        return;
    }
    const auto pusher_world =
        memory.ReadFieldOr<uintptr_t>(pusher_actor_address, kActorOwnerOffset, 0);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    for (auto& binding : g_participant_entities) {
        if (binding.actor_address == 0 ||
            binding.actor_address == pusher_actor_address) {
            continue;
        }
        if (!IsStandaloneWizardKind(binding.kind)) {
            continue;
        }
        const auto bot_world =
            memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
        if (pusher_world != 0 && bot_world != 0 && pusher_world != bot_world) {
            continue;
        }
        const auto bot_x =
            memory.ReadFieldOr<float>(binding.actor_address, kActorPositionXOffset, 0.0f);
        const auto bot_y =
            memory.ReadFieldOr<float>(binding.actor_address, kActorPositionYOffset, 0.0f);
        const auto bot_radius =
            memory.ReadFieldOr<float>(binding.actor_address, kActorCollisionRadiusOffset, 0.0f);
        if (!std::isfinite(bot_x) || !std::isfinite(bot_y) ||
            !std::isfinite(bot_radius) || bot_radius <= 0.0f) {
            continue;
        }
        const auto dx = bot_x - pusher_x;
        const auto dy = bot_y - pusher_y;
        const auto min_sep = pusher_radius + bot_radius;
        const auto dist2 = dx * dx + dy * dy;
        if (dist2 >= min_sep * min_sep) {
            continue;
        }
        const auto dist = std::sqrt(dist2);
        float direction_x = 1.0f;
        float direction_y = 0.0f;
        if (dist > 0.0001f) {
            direction_x = dx / dist;
            direction_y = dy / dist;
        }
        const auto pushed_x = pusher_x + direction_x * min_sep;
        const auto pushed_y = pusher_y + direction_y * min_sep;
        (void)memory.TryWriteField(binding.actor_address, kActorPositionXOffset, pushed_x);
        (void)memory.TryWriteField(binding.actor_address, kActorPositionYOffset, pushed_y);

        static std::uint64_t s_last_puppet_push_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_puppet_push_log_ms >= 1000) {
            s_last_puppet_push_log_ms = now_ms;
            Log(
                "[bots] pushed standalone puppet. bot_id=" + std::to_string(binding.bot_id) +
                " actor=" + HexString(binding.actor_address) +
                " pusher=" + HexString(pusher_actor_address) +
                " before=(" + std::to_string(bot_x) + "," + std::to_string(bot_y) + ")" +
                " after=(" + std::to_string(pushed_x) + "," + std::to_string(pushed_y) + ")" +
                " overlap=" + std::to_string(min_sep - dist));
        }
    }
}
