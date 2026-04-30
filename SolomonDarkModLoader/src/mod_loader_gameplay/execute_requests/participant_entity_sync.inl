bool ExecuteParticipantEntitySyncNow(
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    multiplayer::BotSnapshot bot_snapshot;
    if (!multiplayer::ReadBotSnapshot(request.bot_id, &bot_snapshot) || !bot_snapshot.available) {
        Log(
            "[bots] sync skipped stale request. bot_id=" + std::to_string(request.bot_id) +
            " element_id=" + std::to_string(request.character_profile.element_id));
        return true;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    SceneContextSnapshot scene_context;
    std::string readiness_error;
    if (!TryValidateRemoteParticipantSpawnReadiness(
            gameplay_address,
            &scene_context,
            &readiness_error)) {
        if (error_message != nullptr) {
            *error_message = readiness_error;
        }
        return false;
    }

    if (TryUpdateParticipantEntity(gameplay_address, request, error_message)) {
        Log(
            "[bots] sync updated existing entity. bot_id=" + std::to_string(request.bot_id) +
            " element_id=" + std::to_string(request.character_profile.element_id));
        return true;
    }

    const bool use_slot_bot_rail =
        ShouldUseGameplaySlotBotParticipantRail(gameplay_address, scene_context);
    const bool use_registered_gamenpc_rail =
        !use_slot_bot_rail && ShouldUseRegisteredGameNpcParticipantRail(scene_context);
    const char* rail_name =
        use_slot_bot_rail ? "gameplay_slot_bot"
                          : (use_registered_gamenpc_rail ? "registered_gamenpc" : "standalone_clone");
    Log(
        "[bots] sync spawning actor. bot_id=" + std::to_string(request.bot_id) +
        " element_id=" + std::to_string(request.character_profile.element_id) +
        " rail=" + std::string(rail_name) +
        " gameplay=" + HexString(gameplay_address));
    DWORD exception_code = 0;
    const bool spawned =
        use_slot_bot_rail
            ? TrySpawnGameplaySlotBotParticipantEntitySafe(
                  gameplay_address,
                  request,
                  error_message,
                  &exception_code)
            : (use_registered_gamenpc_rail
                   ? TrySpawnRegisteredGameNpcParticipantEntitySafe(
                         gameplay_address,
                         request,
                         error_message,
                         &exception_code)
                   : TrySpawnStandaloneRemoteWizardParticipantEntitySafe(
                         gameplay_address,
                         request,
                         error_message,
                         &exception_code));
    if (spawned) {
        return true;
    }
    if (error_message != nullptr && error_message->empty()) {
        const char* rail_fn_name =
            use_slot_bot_rail ? "TrySpawnGameplaySlotBotParticipantEntity"
                              : (use_registered_gamenpc_rail
                                     ? "TrySpawnRegisteredGameNpcParticipantEntity"
                                     : "TrySpawnStandaloneRemoteWizardParticipantEntity");
        if (exception_code != 0) {
            *error_message =
                std::string(rail_fn_name) + " threw 0x" + HexString(exception_code) + ".";
        } else {
            *error_message =
                std::string(rail_fn_name) + " returned false without an error message.";
        }
    }
    return false;
}

void DestroyParticipantEntityNow(std::uint64_t bot_id) {
    RemovePendingParticipantSyncRequest(bot_id);
    RemovePendingParticipantDestroyRequest(bot_id);
    DematerializeParticipantEntityNow(bot_id, true, "destroy");
}
