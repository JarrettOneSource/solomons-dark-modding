std::vector<ParticipantEntityBinding> g_participant_entities;
std::recursive_mutex g_participant_entities_mutex;
std::mutex g_wizard_bot_snapshot_mutex;
std::vector<ParticipantGameplaySnapshot> g_participant_gameplay_snapshots;
std::recursive_mutex g_gameplay_action_pump_mutex;
std::uint64_t g_last_wizard_bot_crash_summary_refresh_ms = 0;
std::uint64_t g_last_gameplay_hud_case100_log_ms = 0;
std::uint64_t g_gameplay_slot_hud_probe_until_ms = 0;
uintptr_t g_gameplay_slot_hud_probe_actor = 0;

ObservedActorAnimationDriveProfile g_observed_idle_animation_profile;
ObservedActorAnimationDriveProfile g_observed_moving_animation_profile;
bool g_local_player_animation_probe_has_last_position = false;
float g_local_player_animation_probe_last_x = 0.0f;
float g_local_player_animation_probe_last_y = 0.0f;
