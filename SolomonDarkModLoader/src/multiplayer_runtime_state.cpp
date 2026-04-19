#include "multiplayer_runtime_state.h"

#include <algorithm>
#include <mutex>

namespace sdmod::multiplayer {
namespace {

std::mutex g_runtime_state_mutex;
RuntimeState g_runtime_state;

void InitializeParticipantDefaults(
    ParticipantInfo* participant,
    ParticipantKind kind,
    ParticipantControllerKind controller_kind) {
    if (participant == nullptr) {
        return;
    }

    participant->kind = kind;
    participant->controller_kind = controller_kind;
}

void InitializeLocalParticipantLocked(RuntimeState& state) {
    if (FindLocalParticipant(state) != nullptr) {
        return;
    }

    ParticipantInfo participant;
    participant.participant_id = kLocalParticipantId;
    participant.kind = ParticipantKind::LocalHuman;
    participant.controller_kind = ParticipantControllerKind::Native;
    participant.name = "Wizard";
    participant.is_owner = true;
    participant.character_profile = DefaultCharacterProfile();
    state.participants.push_back(std::move(participant));
}

}  // namespace

namespace detail {

std::mutex& RuntimeStateMutex() {
    return g_runtime_state_mutex;
}

RuntimeState& MutableRuntimeState() {
    return g_runtime_state;
}

}  // namespace detail

MultiplayerCharacterProfile DefaultCharacterProfile() {
    return MultiplayerCharacterProfile{};
}

ParticipantSceneIntent DefaultParticipantSceneIntent() {
    return ParticipantSceneIntent{};
}

bool IsValidCharacterProfile(const MultiplayerCharacterProfile& profile) {
    if (profile.element_id < 0 || profile.element_id > 4) {
        return false;
    }

    const auto discipline_id = static_cast<std::int32_t>(profile.discipline_id);
    if (discipline_id < static_cast<std::int32_t>(CharacterDisciplineId::Mind) ||
        discipline_id > static_cast<std::int32_t>(CharacterDisciplineId::Arcane)) {
        return false;
    }

    return true;
}

bool IsValidParticipantSceneIntent(const ParticipantSceneIntent& scene_intent) {
    const auto kind = static_cast<std::int32_t>(scene_intent.kind);
    if (kind < static_cast<std::int32_t>(ParticipantSceneIntentKind::SharedHub) ||
        kind > static_cast<std::int32_t>(ParticipantSceneIntentKind::Run)) {
        return false;
    }

    if (scene_intent.kind == ParticipantSceneIntentKind::PrivateRegion) {
        return scene_intent.region_index >= 0 || scene_intent.region_type_id >= 0;
    }

    return true;
}

void InitializeRuntimeState() {
    std::scoped_lock lock(g_runtime_state_mutex);
    g_runtime_state = RuntimeState{};
    InitializeLocalParticipantLocked(g_runtime_state);
    g_runtime_state.status_text = "Multiplayer foundation initializing.";
}

void ShutdownRuntimeState() {
    std::scoped_lock lock(g_runtime_state_mutex);
    g_runtime_state = RuntimeState{};
}

void MarkRuntimeShuttingDown() {
    UpdateRuntimeState([](RuntimeState& state) {
        state.shutting_down = true;
        state.status_text = "Multiplayer foundation shutting down.";
    });
}

RuntimeState SnapshotRuntimeState() {
    std::scoped_lock lock(g_runtime_state_mutex);
    InitializeLocalParticipantLocked(g_runtime_state);
    return g_runtime_state;
}

void ApplySteamSnapshotToRuntime(std::uint64_t now_ms, const SteamBootstrapSnapshot& steam_snapshot) {
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = UpsertLocalParticipant(state);
        state.foundation_ready = true;
        state.service_loop_running = true;
        state.steam_requested = steam_snapshot.requested;
        state.steam_available = steam_snapshot.module_loaded;
        state.steam_transport_ready = steam_snapshot.transport_interfaces_ready;
        state.transport_ready = steam_snapshot.transport_interfaces_ready;
        state.local_steam_id = steam_snapshot.local_steam_id;
        state.service_tick_count += 1;
        state.last_service_tick_ms = now_ms;
        state.steam_callback_pump_count = steam_snapshot.callback_pump_count;
        state.last_steam_callback_pump_ms = steam_snapshot.last_callback_pump_ms;
        state.session_transport = steam_snapshot.transport_interfaces_ready ? SessionTransportKind::Steam
                                                                           : SessionTransportKind::None;
        state.session_status = !steam_snapshot.error_text.empty()
                                   ? SessionStatus::Error
                                   : (steam_snapshot.transport_interfaces_ready ? SessionStatus::Ready : SessionStatus::Idle);
        if (state.status_text != steam_snapshot.status_text) {
            state.status_text = steam_snapshot.status_text;
        }
        if (state.error_text != steam_snapshot.error_text) {
            state.error_text = steam_snapshot.error_text;
        }

        if (local == nullptr) {
            return;
        }

        local->steam_id = steam_snapshot.local_steam_id;
        local->is_owner = true;
        local->transport_connected = steam_snapshot.transport_interfaces_ready;
        if (!steam_snapshot.persona_name.empty() && local->name != steam_snapshot.persona_name) {
            local->name = steam_snapshot.persona_name;
        }
    });
}

ParticipantInfo* FindParticipant(RuntimeState& state, std::uint64_t participant_id) {
    const auto it = std::find_if(state.participants.begin(), state.participants.end(), [&](const ParticipantInfo& participant) {
        return participant.participant_id == participant_id;
    });
    return it == state.participants.end() ? nullptr : &(*it);
}

const ParticipantInfo* FindParticipant(const RuntimeState& state, std::uint64_t participant_id) {
    const auto it = std::find_if(state.participants.begin(), state.participants.end(), [&](const ParticipantInfo& participant) {
        return participant.participant_id == participant_id;
    });
    return it == state.participants.end() ? nullptr : &(*it);
}

ParticipantInfo* FindLocalParticipant(RuntimeState& state) {
    return FindParticipant(state, kLocalParticipantId);
}

const ParticipantInfo* FindLocalParticipant(const RuntimeState& state) {
    return FindParticipant(state, kLocalParticipantId);
}

ParticipantInfo* UpsertLocalParticipant(RuntimeState& state) {
    auto* participant = FindLocalParticipant(state);
    if (participant != nullptr) {
        InitializeParticipantDefaults(
            participant,
            ParticipantKind::LocalHuman,
            ParticipantControllerKind::Native);
        participant->is_owner = true;
        if (participant->name.empty()) {
            participant->name = "Wizard";
        }
        return participant;
    }

    InitializeLocalParticipantLocked(state);
    return FindLocalParticipant(state);
}

ParticipantInfo* UpsertRemoteParticipant(
    RuntimeState& state,
    std::uint64_t participant_id,
    ParticipantControllerKind controller_kind) {
    if (participant_id == 0) {
        return nullptr;
    }

    auto* participant = FindParticipant(state, participant_id);
    if (participant != nullptr) {
        InitializeParticipantDefaults(
            participant,
            ParticipantKind::RemoteParticipant,
            controller_kind);
        return participant;
    }

    ParticipantInfo created;
    created.participant_id = participant_id;
    created.kind = ParticipantKind::RemoteParticipant;
    created.controller_kind = controller_kind;
    created.name = controller_kind == ParticipantControllerKind::LuaBrain
                       ? "Lua Bot"
                       : "Remote Wizard";
    created.character_profile = DefaultCharacterProfile();
    state.participants.push_back(std::move(created));
    return &state.participants.back();
}

bool IsLocalHumanParticipant(const ParticipantInfo& participant) {
    return participant.kind == ParticipantKind::LocalHuman;
}

bool IsRemoteParticipant(const ParticipantInfo& participant) {
    return participant.kind == ParticipantKind::RemoteParticipant;
}

bool IsLuaControlledParticipant(const ParticipantInfo& participant) {
    return IsRemoteParticipant(participant) &&
           participant.controller_kind == ParticipantControllerKind::LuaBrain;
}

bool IsNativeControlledParticipant(const ParticipantInfo& participant) {
    return participant.controller_kind == ParticipantControllerKind::Native;
}

const char* SessionStatusLabel(SessionStatus status) {
    switch (status) {
    case SessionStatus::Idle:
        return "Idle";
    case SessionStatus::Ready:
        return "Ready";
    case SessionStatus::Error:
        return "Error";
    }

    return "Unknown";
}

const char* SessionTransportLabel(SessionTransportKind kind) {
    switch (kind) {
    case SessionTransportKind::None:
        return "None";
    case SessionTransportKind::Steam:
        return "Steam";
    }

    return "Unknown";
}

const char* ParticipantKindLabel(ParticipantKind kind) {
    switch (kind) {
    case ParticipantKind::LocalHuman:
        return "LocalHuman";
    case ParticipantKind::RemoteParticipant:
        return "RemoteParticipant";
    }

    return "Unknown";
}

const char* ParticipantControllerKindLabel(ParticipantControllerKind kind) {
    switch (kind) {
    case ParticipantControllerKind::Native:
        return "Native";
    case ParticipantControllerKind::LuaBrain:
        return "LuaBrain";
    }

    return "Unknown";
}

const char* ParticipantSceneIntentKindLabel(ParticipantSceneIntentKind kind) {
    switch (kind) {
    case ParticipantSceneIntentKind::SharedHub:
        return "SharedHub";
    case ParticipantSceneIntentKind::PrivateRegion:
        return "PrivateRegion";
    case ParticipantSceneIntentKind::Run:
        return "Run";
    }

    return "Unknown";
}

}  // namespace sdmod::multiplayer
