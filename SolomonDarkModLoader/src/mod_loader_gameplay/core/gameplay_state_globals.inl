std::vector<ParticipantEntityBinding> g_participant_entities;
std::recursive_mutex g_participant_entities_mutex;
std::mutex g_wizard_bot_snapshot_mutex;
std::vector<ParticipantGameplaySnapshot> g_participant_gameplay_snapshots;
std::recursive_mutex g_gameplay_action_pump_mutex;
// Native remote-participant refresh/cast paths briefly install that
// participant's Concentrate choices in the game's process-global lanes.  A
// local progression snapshot must never publish those temporary values as the
// local player's owned state.  The recursive mutex also covers re-entrant
// native callbacks; the depth lets the snapshot getter reject those callbacks
// instead of observing the temporary context.
std::recursive_mutex g_participant_concentration_context_mutex;
std::atomic<std::uint32_t> g_participant_concentration_context_depth{0};
std::uint64_t g_last_wizard_bot_crash_summary_refresh_ms = 0;
std::uint64_t g_last_gameplay_hud_case100_log_ms = 0;
std::uint64_t g_gameplay_slot_hud_probe_until_ms = 0;
uintptr_t g_gameplay_slot_hud_probe_actor = 0;
std::mutex g_native_spell_effect_actor_mutex;
std::vector<SDModNativeSpellEffectActorState> g_recent_native_spell_effect_actors;
std::mutex g_synthetic_damage_source_mutex;
std::unordered_map<uintptr_t, std::uint64_t>
    g_authority_synthetic_damage_source_participants;
std::mutex g_local_mana_delta_observation_mutex;
SDModLocalManaDeltaObservation g_local_mana_delta_observation;
constexpr std::size_t kMaximumEarthBoulderDamageObservations = 32;
std::mutex g_earth_boulder_damage_observation_mutex;
bool g_earth_boulder_damage_observation_armed = false;
std::uint64_t g_next_earth_boulder_damage_observation_sequence = 1;
std::vector<SDModEarthBoulderDamageObservation>
    g_earth_boulder_damage_observations;
constexpr std::size_t kMaximumMatchDamageObservations = 4096;
std::mutex g_enemy_damage_observation_mutex;
bool g_enemy_damage_observation_armed = false;
std::uint64_t g_next_enemy_damage_observation_sequence = 1;
std::vector<SDModEnemyDamageObservation>
    g_enemy_damage_observations;
std::mutex g_player_damage_observation_mutex;
bool g_player_damage_observation_armed = false;
std::uint64_t g_next_player_damage_observation_sequence = 1;
std::vector<SDModPlayerDamageObservation>
    g_player_damage_observations;

ObservedActorAnimationDriveProfile g_observed_idle_animation_profile;
ObservedActorAnimationDriveProfile g_observed_moving_animation_profile;
bool g_local_player_animation_probe_has_last_position = false;
float g_local_player_animation_probe_last_x = 0.0f;
float g_local_player_animation_probe_last_y = 0.0f;

void RememberAuthoritySyntheticDamageSource(
    uintptr_t source_actor_address,
    std::uint64_t participant_id) {
    if (source_actor_address == 0 || participant_id == 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_synthetic_damage_source_mutex);
    g_authority_synthetic_damage_source_participants[source_actor_address] =
        participant_id;
}

std::uint64_t FindAuthoritySyntheticDamageSourceParticipant(
    uintptr_t source_actor_address) {
    if (source_actor_address == 0) {
        return 0;
    }
    std::lock_guard<std::mutex> lock(g_synthetic_damage_source_mutex);
    const auto it = g_authority_synthetic_damage_source_participants.find(
        source_actor_address);
    return it == g_authority_synthetic_damage_source_participants.end()
               ? 0
               : it->second;
}

void ForgetAuthoritySyntheticDamageSource(uintptr_t source_actor_address) {
    if (source_actor_address == 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_synthetic_damage_source_mutex);
    g_authority_synthetic_damage_source_participants.erase(
        source_actor_address);
}

void ClearAuthoritySyntheticDamageSources() {
    std::lock_guard<std::mutex> lock(g_synthetic_damage_source_mutex);
    g_authority_synthetic_damage_source_participants.clear();
}
