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
std::mutex g_local_mana_delta_observation_mutex;
SDModLocalManaDeltaObservation g_local_mana_delta_observation;

ObservedActorAnimationDriveProfile g_observed_idle_animation_profile;
ObservedActorAnimationDriveProfile g_observed_moving_animation_profile;
bool g_local_player_animation_probe_has_last_position = false;
float g_local_player_animation_probe_last_x = 0.0f;
float g_local_player_animation_probe_last_y = 0.0f;
