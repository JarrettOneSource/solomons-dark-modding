void ApplyTransform(
    ParticipantInfo* participant,
    float position_x,
    float position_y,
    bool has_heading,
    float heading) {
    if (participant == nullptr) {
        return;
    }

    participant->runtime.valid = true;
    participant->runtime.transform_valid = true;
    participant->runtime.position_x = position_x;
    participant->runtime.position_y = position_y;
    if (has_heading) {
        participant->runtime.heading = heading;
    }
}

void ApplyLoadout(ParticipantInfo* participant, const BotLoadoutInfo& loadout) {
    if (participant == nullptr) {
        return;
    }

    participant->runtime.primary_entry_index = loadout.primary_entry_index;
    participant->runtime.primary_combo_entry_index = loadout.primary_combo_entry_index;
    participant->runtime.queued_secondary_entry_indices = loadout.secondary_entry_indices;
}

void ApplySceneIntent(ParticipantInfo* participant, const ParticipantSceneIntent& scene_intent) {
    if (participant == nullptr) {
        return;
    }

    participant->runtime.scene_intent = scene_intent;
    participant->runtime.in_run = scene_intent.kind == ParticipantSceneIntentKind::Run;
}

void ApplyCharacterProfile(ParticipantInfo* participant, const MultiplayerCharacterProfile& profile) {
    if (participant == nullptr) {
        return;
    }

    participant->character_profile = profile;
    participant->runtime.level = profile.level;
    participant->runtime.experience_current = profile.experience;
    ApplyLoadout(participant, profile.loadout);
}

void ResetPendingState() {
    g_pending_casts.clear();
    g_pending_entity_syncs.clear();
    g_bot_movement_intents.clear();
    g_pending_destroys.clear();
    g_pending_skill_choices.clear();
    g_next_cast_sequence = 1;
    g_next_entity_sync_generation = 1;
    g_next_movement_intent_revision = 1;
    g_next_destroy_generation = 1;
    g_next_skill_choice_generation = 1;
}

void DestroyAllBotsLocked() {
    UpdateRuntimeState([](RuntimeState& state) {
        state.participants.erase(
            std::remove_if(state.participants.begin(), state.participants.end(), [](const ParticipantInfo& participant) {
                return IsLuaControlledParticipant(participant);
            }),
            state.participants.end());
    });

    ResetPendingState();
}
