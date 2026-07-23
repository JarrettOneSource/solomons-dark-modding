constexpr std::size_t kMaximumLuaEnemyAiCommands = 512;
constexpr float kMaximumLuaEnemyAiCoordinateMagnitude = 20000.0f;
constexpr float kMaximumLuaEnemyAiStopDistance = 4096.0f;

struct LuaEnemyAiCommandRuntime {
    SDModLuaEnemyAiCommandState state;
    uintptr_t actor_address = 0;
};

std::mutex g_lua_enemy_ai_command_mutex;
std::unordered_map<uintptr_t, LuaEnemyAiCommandRuntime>
    g_lua_enemy_ai_commands_by_actor;

void SetLuaEnemyAiError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

bool ValidateLuaEnemyAiActorIdentity(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    std::string* error_message) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        SetLuaEnemyAiError(
            error_message,
            "Lua enemy AI commands require simulation authority");
        return false;
    }
    if (owner_mod_id.empty() || owner_mod_id.size() > kLuaModMaxIdentifierBytes ||
        network_actor_id == 0 || content_id == 0 || spawn_serial == 0 ||
        actor_address == 0) {
        SetLuaEnemyAiError(error_message, "Lua enemy AI identity is invalid");
        return false;
    }

    std::uint32_t current_spawn_serial = 0;
    SDModLuaEnemySpawnConfig spawn_config;
    if (!TryGetRunLifecycleEnemySpawnSerial(
            actor_address,
            &current_spawn_serial) ||
        current_spawn_serial != spawn_serial ||
        !TryGetRunLifecycleLuaEnemySpawnConfig(actor_address, &spawn_config) ||
        spawn_config.content_id != content_id ||
        multiplayer::GetLocalRunEnemyNetworkActorId(actor_address) !=
            network_actor_id) {
        SetLuaEnemyAiError(
            error_message,
            "Lua enemy AI target is not the requested live registered enemy");
        return false;
    }
    return true;
}

LuaEnemyAiCommandRuntime* FindOwnedLuaEnemyAiCommandLocked(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id) {
    const auto found = std::find_if(
        g_lua_enemy_ai_commands_by_actor.begin(),
        g_lua_enemy_ai_commands_by_actor.end(),
        [&](auto& entry) {
            return entry.second.state.owner_mod_id == owner_mod_id &&
                entry.second.state.network_actor_id == network_actor_id;
        });
    return found == g_lua_enemy_ai_commands_by_actor.end()
        ? nullptr
        : &found->second;
}

LuaEnemyAiCommandRuntime* UpsertLuaEnemyAiCommandLocked(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    std::string* error_message) {
    for (auto it = g_lua_enemy_ai_commands_by_actor.begin();
         it != g_lua_enemy_ai_commands_by_actor.end();) {
        if (it->second.state.network_actor_id == network_actor_id &&
            it->first != actor_address) {
            it = g_lua_enemy_ai_commands_by_actor.erase(it);
        } else {
            ++it;
        }
    }

    const auto existing = g_lua_enemy_ai_commands_by_actor.find(actor_address);
    if (existing != g_lua_enemy_ai_commands_by_actor.end()) {
        if (existing->second.state.owner_mod_id != owner_mod_id ||
            existing->second.state.network_actor_id != network_actor_id ||
            existing->second.state.content_id != content_id ||
            existing->second.state.spawn_serial != spawn_serial) {
            SetLuaEnemyAiError(
                error_message,
                "Lua enemy AI target is already controlled by another registration");
            return nullptr;
        }
        return &existing->second;
    }

    if (g_lua_enemy_ai_commands_by_actor.size() >=
        kMaximumLuaEnemyAiCommands) {
        SetLuaEnemyAiError(
            error_message,
            "Lua enemy AI command limit reached");
        return nullptr;
    }

    LuaEnemyAiCommandRuntime command;
    command.state.available = true;
    command.state.owner_mod_id.assign(owner_mod_id);
    command.state.network_actor_id = network_actor_id;
    command.state.content_id = content_id;
    command.state.spawn_serial = spawn_serial;
    command.actor_address = actor_address;
    const auto [inserted, unused] =
        g_lua_enemy_ai_commands_by_actor.emplace(
            actor_address,
            std::move(command));
    (void)unused;
    return &inserted->second;
}

bool SetLuaEnemyAiTargetOverrideInternal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    SDModLuaEnemyAiTargetMode target_mode,
    std::uint64_t target_participant_id,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!ValidateLuaEnemyAiActorIdentity(
            owner_mod_id,
            network_actor_id,
            content_id,
            spawn_serial,
            actor_address,
            error_message)) {
        return false;
    }
    if (target_mode == SDModLuaEnemyAiTargetMode::Participant &&
        target_participant_id == 0) {
        SetLuaEnemyAiError(
            error_message,
            "Lua enemy AI participant target must be nonzero");
        return false;
    }
    if (target_mode != SDModLuaEnemyAiTargetMode::Participant) {
        target_participant_id = 0;
    }

    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    auto* command = UpsertLuaEnemyAiCommandLocked(
        owner_mod_id,
        network_actor_id,
        content_id,
        spawn_serial,
        actor_address,
        error_message);
    if (command == nullptr) {
        return false;
    }
    command->state.target_mode = target_mode;
    command->state.target_participant_id = target_participant_id;
    if (target_mode == SDModLuaEnemyAiTargetMode::Stock &&
        !command->state.move_goal_active) {
        g_lua_enemy_ai_commands_by_actor.erase(actor_address);
    }
    return true;
}

bool SetLuaEnemyAiMoveGoalInternal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    float x,
    float y,
    float stop_distance,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!ValidateLuaEnemyAiActorIdentity(
            owner_mod_id,
            network_actor_id,
            content_id,
            spawn_serial,
            actor_address,
            error_message)) {
        return false;
    }
    if (!std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(stop_distance) || stop_distance < 0.0f ||
        stop_distance > kMaximumLuaEnemyAiStopDistance ||
        std::abs(x) > kMaximumLuaEnemyAiCoordinateMagnitude ||
        std::abs(y) > kMaximumLuaEnemyAiCoordinateMagnitude) {
        SetLuaEnemyAiError(
            error_message,
            "Lua enemy AI move goal is outside the supported world range");
        return false;
    }

    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    auto* command = UpsertLuaEnemyAiCommandLocked(
        owner_mod_id,
        network_actor_id,
        content_id,
        spawn_serial,
        actor_address,
        error_message);
    if (command == nullptr) {
        return false;
    }
    command->state.move_goal_active = true;
    command->state.move_goal_x = x;
    command->state.move_goal_y = y;
    command->state.move_goal_stop_distance = stop_distance;
    return true;
}

bool StopLuaEnemyAiMoveGoalInternal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id) {
    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    auto* command = FindOwnedLuaEnemyAiCommandLocked(
        owner_mod_id,
        network_actor_id);
    if (command == nullptr || !command->state.move_goal_active) {
        return false;
    }
    const auto actor_address = command->actor_address;
    command->state.move_goal_active = false;
    command->state.move_goal_x = 0.0f;
    command->state.move_goal_y = 0.0f;
    command->state.move_goal_stop_distance = 0.0f;
    if (command->state.target_mode == SDModLuaEnemyAiTargetMode::Stock) {
        g_lua_enemy_ai_commands_by_actor.erase(actor_address);
    }
    return true;
}

bool ClearLuaEnemyAiOverridesInternal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id) {
    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    for (auto it = g_lua_enemy_ai_commands_by_actor.begin();
         it != g_lua_enemy_ai_commands_by_actor.end();
         ++it) {
        if (it->second.state.owner_mod_id == owner_mod_id &&
            it->second.state.network_actor_id == network_actor_id) {
            g_lua_enemy_ai_commands_by_actor.erase(it);
            return true;
        }
    }
    return false;
}

bool TryGetLuaEnemyAiCommandStateInternal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    SDModLuaEnemyAiCommandState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = {};
    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    const auto* command = FindOwnedLuaEnemyAiCommandLocked(
        owner_mod_id,
        network_actor_id);
    if (command == nullptr) {
        return false;
    }
    *state = command->state;
    return true;
}

bool TryGetLuaEnemyAiCommandForActor(
    uintptr_t actor_address,
    LuaEnemyAiCommandRuntime* command) {
    if (actor_address == 0 || command == nullptr ||
        !multiplayer::IsLuaModSimulationAuthority()) {
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
        const auto existing =
            g_lua_enemy_ai_commands_by_actor.find(actor_address);
        if (existing == g_lua_enemy_ai_commands_by_actor.end()) {
            return false;
        }
        *command = existing->second;
    }

    std::uint32_t current_spawn_serial = 0;
    if (!TryGetRunLifecycleEnemySpawnSerial(
            actor_address,
            &current_spawn_serial) ||
        current_spawn_serial != command->state.spawn_serial) {
        std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
        g_lua_enemy_ai_commands_by_actor.erase(actor_address);
        return false;
    }
    return true;
}

void ClearLuaEnemyAiOverridesForModInternal(std::string_view owner_mod_id) {
    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    for (auto it = g_lua_enemy_ai_commands_by_actor.begin();
         it != g_lua_enemy_ai_commands_by_actor.end();) {
        if (it->second.state.owner_mod_id == owner_mod_id) {
            it = g_lua_enemy_ai_commands_by_actor.erase(it);
        } else {
            ++it;
        }
    }
}

void ResetLuaEnemyAiOverridesInternal() {
    std::lock_guard<std::mutex> lock(g_lua_enemy_ai_command_mutex);
    g_lua_enemy_ai_commands_by_actor.clear();
}
