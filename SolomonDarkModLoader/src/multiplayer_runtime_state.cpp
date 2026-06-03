#include "multiplayer_runtime_state.h"

#include <algorithm>
#include <cmath>
#include <mutex>
#include <unordered_map>

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
    participant->owned_progression.initialized = true;
}

void InitializeLocalParticipantLocked(RuntimeState& state) {
    if (FindLocalParticipant(state) != nullptr) {
        return;
    }

    ParticipantInfo participant;
    participant.participant_id = kLocalParticipantId;
    InitializeParticipantDefaults(
        &participant,
        ParticipantKind::LocalHuman,
        ParticipantControllerKind::Native);
    participant.name = "Wizard";
    participant.is_owner = true;
    participant.character_profile = DefaultCharacterProfile();
    state.participants.push_back(std::move(participant));
}

bool IsFiniteTransform(float x, float y, float heading) {
    return std::isfinite(x) && std::isfinite(y) && std::isfinite(heading);
}

bool IsOlderSequence(std::uint32_t candidate, std::uint32_t latest) {
    if (candidate == 0 || latest == 0 || candidate == latest) {
        return false;
    }
    return static_cast<std::int32_t>(candidate - latest) < 0;
}

float NormalizeHeadingDegrees(float degrees) {
    if (!std::isfinite(degrees)) {
        return 0.0f;
    }
    while (degrees < 0.0f) {
        degrees += 360.0f;
    }
    while (degrees >= 360.0f) {
        degrees -= 360.0f;
    }
    return degrees;
}

bool SameWorldSnapshotTimeline(
    const WorldSnapshotRuntimeInfo& left,
    const WorldSnapshotRuntimeInfo& right) {
    return left.valid &&
           right.valid &&
           left.authority_participant_id == right.authority_participant_id &&
           left.scene_epoch == right.scene_epoch &&
           left.run_nonce == right.run_nonce &&
           SameParticipantSceneIntent(left.scene_intent, right.scene_intent);
}

WorldActorSnapshot InterpolateWorldActorSnapshot(
    const WorldActorSnapshot& before,
    const WorldActorSnapshot& after,
    float alpha) {
    WorldActorSnapshot result = after;
    result.position_x = before.position_x + (after.position_x - before.position_x) * alpha;
    result.position_y = before.position_y + (after.position_y - before.position_y) * alpha;
    result.heading = InterpolateHeadingDegrees(before.heading, after.heading, alpha);
    if ((before.presentation_flags & WorldActorPresentationFlagLocomotionFloats) != 0 &&
        (after.presentation_flags & WorldActorPresentationFlagLocomotionFloats) != 0) {
        result.walk_cycle_primary =
            before.walk_cycle_primary + (after.walk_cycle_primary - before.walk_cycle_primary) * alpha;
        result.walk_cycle_secondary =
            before.walk_cycle_secondary + (after.walk_cycle_secondary - before.walk_cycle_secondary) * alpha;
    }
    return result;
}

WorldSnapshotRuntimeInfo InterpolateWorldSnapshot(
    const WorldSnapshotRuntimeInfo& before,
    const WorldSnapshotRuntimeInfo& after,
    std::uint64_t sample_ms) {
    if (after.received_ms <= before.received_ms ||
        !SameWorldSnapshotTimeline(before, after)) {
        return after;
    }

    const float alpha = (std::clamp)(
        static_cast<float>(sample_ms - before.received_ms) /
            static_cast<float>(after.received_ms - before.received_ms),
        0.0f,
        1.0f);

    std::unordered_map<std::uint64_t, const WorldActorSnapshot*> before_by_id;
    before_by_id.reserve(before.actors.size());
    for (const auto& actor : before.actors) {
        if (actor.network_actor_id != 0) {
            before_by_id.emplace(actor.network_actor_id, &actor);
        }
    }

    WorldSnapshotRuntimeInfo result = after;
    result.received_ms = sample_ms;
    for (auto& actor : result.actors) {
        const auto it = before_by_id.find(actor.network_actor_id);
        if (it == before_by_id.end() || it->second == nullptr) {
            continue;
        }
        const auto& previous = *it->second;
        if (previous.native_type_id != actor.native_type_id ||
            !IsFiniteTransform(previous.position_x, previous.position_y, previous.heading) ||
            !IsFiniteTransform(actor.position_x, actor.position_y, actor.heading)) {
            continue;
        }
        actor = InterpolateWorldActorSnapshot(previous, actor, alpha);
    }
    return result;
}

void PruneRemovedRunActorsFromSample(
    const WorldSnapshotRuntimeInfo& latest,
    WorldSnapshotRuntimeInfo* sample) {
    if (sample == nullptr ||
        !sample->valid ||
        !latest.valid ||
        sample->scene_intent.kind != ParticipantSceneIntentKind::Run ||
        latest.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        !SameWorldSnapshotTimeline(*sample, latest)) {
        return;
    }

    std::unordered_map<std::uint64_t, bool> latest_actor_ids;
    latest_actor_ids.reserve(latest.actors.size());
    for (const auto& actor : latest.actors) {
        if (actor.network_actor_id != 0) {
            latest_actor_ids.emplace(actor.network_actor_id, true);
        }
    }

    sample->actors.erase(
        std::remove_if(
            sample->actors.begin(),
            sample->actors.end(),
            [&](const WorldActorSnapshot& actor) {
                return actor.lifecycle_owned &&
                       actor.tracked_enemy &&
                       actor.network_actor_id != 0 &&
                       latest_actor_ids.find(actor.network_actor_id) == latest_actor_ids.end();
            }),
        sample->actors.end());
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

bool SameParticipantSceneIntent(const ParticipantSceneIntent& left, const ParticipantSceneIntent& right) {
    return left.kind == right.kind &&
           left.region_index == right.region_index &&
           left.region_type_id == right.region_type_id;
}

float InterpolateHeadingDegrees(float from_degrees, float to_degrees, float alpha) {
    const float from = NormalizeHeadingDegrees(from_degrees);
    const float to = NormalizeHeadingDegrees(to_degrees);
    float delta = to - from;
    while (delta > 180.0f) {
        delta -= 360.0f;
    }
    while (delta < -180.0f) {
        delta += 360.0f;
    }
    return NormalizeHeadingDegrees(from + delta * (std::clamp)(alpha, 0.0f, 1.0f));
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
    InitializeParticipantDefaults(
        &created,
        ParticipantKind::RemoteParticipant,
        controller_kind);
    created.name = controller_kind == ParticipantControllerKind::LuaBrain
                       ? "Lua Bot"
                       : "Remote Wizard";
    created.character_profile = DefaultCharacterProfile();
    state.participants.push_back(std::move(created));
    return &state.participants.back();
}

void AppendParticipantTransformSample(ParticipantInfo* participant, const ParticipantTransformSample& sample) {
    if (participant == nullptr ||
        !sample.valid ||
        !IsFiniteTransform(sample.position_x, sample.position_y, sample.heading)) {
        return;
    }

    auto& history = participant->transform_history;
    if (!history.empty()) {
        const auto& latest = history.back();
        if (latest.run_nonce != sample.run_nonce ||
            !SameParticipantSceneIntent(latest.scene_intent, sample.scene_intent)) {
            history.clear();
        } else if (sample.sequence == latest.sequence) {
            history.back() = sample;
            return;
        } else if (IsOlderSequence(sample.sequence, latest.sequence)) {
            return;
        }
    }

    history.push_back(sample);
    if (history.size() > kParticipantTransformHistoryCapacity) {
        history.erase(history.begin(), history.begin() + (history.size() - kParticipantTransformHistoryCapacity));
    }
}

bool TrySampleParticipantTransform(
    const ParticipantInfo& participant,
    std::uint64_t now_ms,
    std::uint64_t interpolation_delay_ms,
    ParticipantTransformSample* sample) {
    if (sample == nullptr || participant.transform_history.empty()) {
        return false;
    }

    const std::uint64_t sample_ms = now_ms > interpolation_delay_ms ? now_ms - interpolation_delay_ms : 0;
    const ParticipantTransformSample* before = nullptr;
    const ParticipantTransformSample* after = nullptr;
    for (const auto& candidate : participant.transform_history) {
        if (!candidate.valid) {
            continue;
        }
        if (candidate.received_ms <= sample_ms) {
            before = &candidate;
        }
        if (candidate.received_ms >= sample_ms) {
            after = &candidate;
            break;
        }
    }

    if (before == nullptr && after == nullptr) {
        return false;
    }
    if (before == nullptr) {
        *sample = *after;
        return true;
    }
    if (after == nullptr || after == before || after->received_ms <= before->received_ms) {
        *sample = *before;
        return true;
    }
    if (before->run_nonce != after->run_nonce ||
        !SameParticipantSceneIntent(before->scene_intent, after->scene_intent)) {
        *sample = *after;
        return true;
    }

    const float alpha = (std::clamp)(
        static_cast<float>(sample_ms - before->received_ms) /
            static_cast<float>(after->received_ms - before->received_ms),
        0.0f,
        1.0f);
    *sample = *after;
    sample->received_ms = sample_ms;
    sample->position_x = before->position_x + (after->position_x - before->position_x) * alpha;
    sample->position_y = before->position_y + (after->position_y - before->position_y) * alpha;
    sample->heading = InterpolateHeadingDegrees(before->heading, after->heading, alpha);
    if ((before->presentation_flags & ParticipantPresentationFlagRenderDriveFloats) != 0 &&
        (after->presentation_flags & ParticipantPresentationFlagRenderDriveFloats) != 0) {
        sample->walk_cycle_primary =
            before->walk_cycle_primary + (after->walk_cycle_primary - before->walk_cycle_primary) * alpha;
        sample->walk_cycle_secondary =
            before->walk_cycle_secondary + (after->walk_cycle_secondary - before->walk_cycle_secondary) * alpha;
        sample->render_drive_stride =
            before->render_drive_stride + (after->render_drive_stride - before->render_drive_stride) * alpha;
        sample->render_advance_rate =
            before->render_advance_rate + (after->render_advance_rate - before->render_advance_rate) * alpha;
        sample->render_advance_phase =
            before->render_advance_phase + (after->render_advance_phase - before->render_advance_phase) * alpha;
        sample->render_drive_effect_timer =
            before->render_drive_effect_timer +
            (after->render_drive_effect_timer - before->render_drive_effect_timer) * alpha;
        sample->render_drive_effect_progress =
            before->render_drive_effect_progress +
            (after->render_drive_effect_progress - before->render_drive_effect_progress) * alpha;
        sample->render_drive_overlay_alpha =
            before->render_drive_overlay_alpha +
            (after->render_drive_overlay_alpha - before->render_drive_overlay_alpha) * alpha;
        sample->render_drive_move_blend =
            before->render_drive_move_blend +
            (after->render_drive_move_blend - before->render_drive_move_blend) * alpha;
    }
    if ((after->presentation_flags & ParticipantPresentationFlagStaffVisualState) != 0) {
        sample->attachment_staff_visual_state = after->attachment_staff_visual_state;
    }
    return true;
}

void AppendWorldSnapshot(RuntimeState* state, WorldSnapshotRuntimeInfo snapshot) {
    if (state == nullptr || !snapshot.valid) {
        return;
    }

    auto& history = state->world_snapshot_history;
    if (!history.empty()) {
        const auto& latest = history.back();
        if (!SameWorldSnapshotTimeline(latest, snapshot)) {
            history.clear();
        } else if (snapshot.sequence == latest.sequence) {
            state->world_snapshot = snapshot;
            history.back() = std::move(snapshot);
            return;
        } else if (IsOlderSequence(snapshot.sequence, latest.sequence)) {
            return;
        }
    }

    state->world_snapshot = snapshot;
    history.push_back(std::move(snapshot));
    if (history.size() > kWorldSnapshotHistoryCapacity) {
        history.erase(history.begin(), history.begin() + (history.size() - kWorldSnapshotHistoryCapacity));
    }
}

bool TrySampleWorldSnapshot(
    const RuntimeState& state,
    std::uint64_t now_ms,
    std::uint64_t interpolation_delay_ms,
    WorldSnapshotRuntimeInfo* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }
    if (state.world_snapshot_history.empty()) {
        if (!state.world_snapshot.valid) {
            return false;
        }
        *snapshot = state.world_snapshot;
        return true;
    }

    const std::uint64_t sample_ms = now_ms > interpolation_delay_ms ? now_ms - interpolation_delay_ms : 0;
    const WorldSnapshotRuntimeInfo* before = nullptr;
    const WorldSnapshotRuntimeInfo* after = nullptr;
    for (const auto& candidate : state.world_snapshot_history) {
        if (!candidate.valid) {
            continue;
        }
        if (candidate.received_ms <= sample_ms) {
            before = &candidate;
        }
        if (candidate.received_ms >= sample_ms) {
            after = &candidate;
            break;
        }
    }

    if (before == nullptr && after == nullptr) {
        return false;
    }
    if (before == nullptr) {
        *snapshot = *after;
        PruneRemovedRunActorsFromSample(state.world_snapshot, snapshot);
        return true;
    }
    if (after == nullptr || after == before) {
        *snapshot = *before;
        PruneRemovedRunActorsFromSample(state.world_snapshot, snapshot);
        return true;
    }

    *snapshot = InterpolateWorldSnapshot(*before, *after, sample_ms);
    PruneRemovedRunActorsFromSample(state.world_snapshot, snapshot);
    return true;
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
    case SessionTransportKind::LocalUdp:
        return "LocalUdp";
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

const char* LootDropKindLabel(LootDropKind kind) {
    switch (kind) {
    case LootDropKind::Unknown:
        return "Unknown";
    case LootDropKind::Gold:
        return "Gold";
    case LootDropKind::Item:
        return "Item";
    case LootDropKind::Potion:
        return "Potion";
    case LootDropKind::Orb:
        return "Orb";
    case LootDropKind::Powerup:
        return "Powerup";
    }

    return "Unknown";
}

}  // namespace sdmod::multiplayer
