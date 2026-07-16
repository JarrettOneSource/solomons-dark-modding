struct LocalPlayerNativePrimaryRuntimeSignature {
    uintptr_t actor_address = 0;
    uintptr_t progression_inner = 0;
    std::uint64_t participant_id = 0;
    std::int32_t element_id = -1;
    std::int32_t primary_entry_index = -2;
    std::int32_t primary_combo_entry_index = -2;
    std::int32_t level = -1;
    std::uint32_t spellbook_revision = 0;
    std::uint32_t statbook_revision = 0;
    std::uint32_t loadout_revision = 0;
    std::uint32_t concentration_revision = 0;
    std::uint32_t derived_stat_revision = 0;
};

bool LocalPlayerNativePrimaryRuntimeSignaturesEqual(
    const LocalPlayerNativePrimaryRuntimeSignature& left,
    const LocalPlayerNativePrimaryRuntimeSignature& right) {
    return
        left.actor_address == right.actor_address &&
        left.progression_inner == right.progression_inner &&
        left.participant_id == right.participant_id &&
        left.element_id == right.element_id &&
        left.primary_entry_index == right.primary_entry_index &&
        left.primary_combo_entry_index == right.primary_combo_entry_index &&
        left.level == right.level &&
        left.spellbook_revision == right.spellbook_revision &&
        left.statbook_revision == right.statbook_revision &&
        left.loadout_revision == right.loadout_revision &&
        left.concentration_revision == right.concentration_revision &&
        left.derived_stat_revision == right.derived_stat_revision;
}

multiplayer::MultiplayerCharacterProfile BuildLocalPlayerNativePrimaryProfile(
    const multiplayer::ParticipantInfo& local_participant) {
    auto profile = local_participant.character_profile;
    if (local_participant.owned_progression.ability_loadout_valid) {
        profile.loadout = local_participant.owned_progression.ability_loadout;
    } else {
        if (local_participant.runtime.primary_entry_index >= 0) {
            profile.loadout.primary_entry_index =
                local_participant.runtime.primary_entry_index;
        }
        if (local_participant.runtime.primary_combo_entry_index >= 0) {
            profile.loadout.primary_combo_entry_index =
                local_participant.runtime.primary_combo_entry_index;
        }
    }
    if (local_participant.runtime.level > 0) {
        profile.level = local_participant.runtime.level;
    }
    if (local_participant.runtime.experience_current >= 0) {
        profile.experience = local_participant.runtime.experience_current;
    }
    return profile;
}

bool MaybeInitializeLocalPlayerNativePrimaryRuntime(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    if (gameplay_address == 0 ||
        actor_address == 0 ||
        !multiplayer::IsLocalTransportEnabled() ||
        !IsRunLifecycleActive()) {
        return false;
    }

    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address) ||
        local_actor_address != actor_address) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local_participant =
        multiplayer::FindLocalParticipant(runtime_state);
    if (local_participant == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_handle = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorProgressionHandleOffset,
            &progression_handle) ||
        progression_handle == 0) {
        return false;
    }
    const auto progression_inner =
        ReadSmartPointerInnerObject(progression_handle);
    if (progression_inner == 0) {
        return false;
    }

    const auto profile =
        BuildLocalPlayerNativePrimaryProfile(*local_participant);
    const LocalPlayerNativePrimaryRuntimeSignature signature = {
        actor_address,
        progression_inner,
        local_participant->participant_id,
        profile.element_id,
        profile.loadout.primary_entry_index,
        profile.loadout.primary_combo_entry_index,
        profile.level,
        local_participant->owned_progression.spellbook_revision,
        local_participant->owned_progression.statbook_revision,
        local_participant->owned_progression.loadout_revision,
        local_participant->owned_progression.concentration_revision,
        local_participant->owned_progression.derived_stat_revision,
    };

    static LocalPlayerNativePrimaryRuntimeSignature s_last_successful_signature{};
    static bool s_have_successful_signature = false;
    static std::uint64_t s_last_failure_log_ms = 0;

    uintptr_t progression_runtime = 0;
    std::int32_t current_spell_id = 0;
    const bool runtime_ready =
        memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &progression_runtime) &&
        progression_runtime == progression_inner;
    const bool spell_ready =
        memory.TryReadField(
            progression_inner,
            kProgressionCurrentSpellIdOffset,
            &current_spell_id) &&
        current_spell_id > 0;
    if (runtime_ready &&
        spell_ready &&
        s_have_successful_signature &&
        LocalPlayerNativePrimaryRuntimeSignaturesEqual(
            signature,
            s_last_successful_signature)) {
        return false;
    }

    if (!EnsureActorProgressionRuntimeFieldFromHandle(
            actor_address,
            "local_player_native_primary")) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[multiplayer] Local native primary runtime cache initialization failed. actor=" +
                HexString(actor_address) +
                " handle=" + HexString(progression_handle) +
                " inner=" + HexString(progression_inner));
        }
        return false;
    }

    int resolved_primary_skill_id = -1;
    std::string error_message;
    if (!ApplyProfilePrimaryLoadoutToSkillsWizard(
            progression_inner,
            profile,
            &resolved_primary_skill_id,
            &error_message)) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[multiplayer] Local native primary spell initialization failed. actor=" +
                HexString(actor_address) +
                " progression=" + HexString(progression_inner) +
                " error=" + error_message);
        }
        return false;
    }

    progression_runtime = 0;
    current_spell_id = 0;
    const bool initialized =
        memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &progression_runtime) &&
        progression_runtime == progression_inner &&
        memory.TryReadField(
            progression_inner,
            kProgressionCurrentSpellIdOffset,
            &current_spell_id) &&
        current_spell_id > 0;
    if (!initialized) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[multiplayer] Local native primary runtime remained incomplete. actor=" +
                HexString(actor_address) +
                " progression=" + HexString(progression_runtime) +
                " expected_progression=" + HexString(progression_inner) +
                " spell=" + std::to_string(current_spell_id));
        }
        return false;
    }

    s_last_successful_signature = signature;
    s_have_successful_signature = true;
    Log(
        "[multiplayer] Local native primary runtime initialized. actor=" +
        HexString(actor_address) +
        " progression=" + HexString(progression_inner) +
        " primary_entry=" +
            std::to_string(profile.loadout.primary_entry_index) +
        " combo_entry=" +
            std::to_string(profile.loadout.primary_combo_entry_index) +
        " resolved_spell=" + std::to_string(resolved_primary_skill_id) +
        " current_spell=" + std::to_string(current_spell_id) +
        " spellbook_revision=" +
            std::to_string(
                local_participant->owned_progression.spellbook_revision) +
        " statbook_revision=" +
            std::to_string(
                local_participant->owned_progression.statbook_revision) +
        " loadout_revision=" +
            std::to_string(
                local_participant->owned_progression.loadout_revision));
    return true;
}
