std::uint8_t __fastcall HookPlayerActorSecondarySpellCast(
    void* self,
    void* /*unused_edx*/,
    int skill_entry_index) {
    const auto original =
        GetX86HookTrampoline<PlayerActorSecondarySpellCastFn>(
            g_gameplay_keyboard_injection.player_actor_secondary_spell_cast_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    const bool local_input_dispatch =
        g_remote_secondary_spell_dispatch_depth == 0 &&
        IsActorCurrentLocalPlayerSlotZero(actor_address);
    LocalSecondaryCastCapture capture{};
    const bool have_local_capture =
        local_input_dispatch &&
        TryCaptureLocalSecondaryCast(
            actor_address,
            skill_entry_index,
            &capture);
    if (have_local_capture) {
        const auto registered_result =
            TryDispatchSelectedLuaRegisteredSecondarySpell(
                actor_address,
                capture.belt_slot,
                &capture);
        if (registered_result ==
            LuaRegisteredSpellInputDispatchResult::Queued) {
            return 1;
        }
        if (registered_result ==
            LuaRegisteredSpellInputDispatchResult::Rejected) {
            return 0;
        }
    }
    if (local_input_dispatch &&
        HasLuaSpellCastFilterHandlers()) {
        const auto filter_context = CaptureLuaSpellCastFilterContext(
            actor_address,
            multiplayer::GetLocalTransportParticipantId(),
            LuaSpellCastKind::Secondary,
            skill_entry_index);
        if (!ApplyLuaSpellCastFilters(filter_context)) {
            Log(
                "[lua] canceled owner-side local secondary spell cast. actor=" +
                HexString(actor_address) +
                " skill_id=" + std::to_string(skill_entry_index));
            return 0;
        }
    }
    const auto turn_undead_precast_state =
        CaptureAuthoritativeTurnUndeadPrecastState(
            actor_address,
            skill_entry_index);
    const bool should_capture =
        multiplayer::IsLocalTransportEnabled() &&
        have_local_capture;
    if (skill_entry_index == 0x33 &&
        multiplayer::IsLocalTransportEnabled() &&
        !should_capture) {
        Log(
            "Multiplayer local Dampen rejected because its authoritative "
            "cast context was unavailable. actor=" +
            HexString(actor_address));
        return 0;
    }
    std::uint8_t native_result = 0;
    bool stock_context_ok = true;
    {
        ScopedLocalSecondaryCursorProjectionCapture cursor_projection_capture(
            actor_address,
            skill_entry_index,
            should_capture ? &capture : nullptr);
        if (multiplayer::IsLocalTransportEnabled()) {
            stock_context_ok = InvokeWithStockDampenEffectSuppressed(
                skill_entry_index,
                [&] {
                    native_result = original(self, skill_entry_index);
                });
        } else {
            native_result = original(self, skill_entry_index);
        }
    }
    if (!stock_context_ok) {
        return 0;
    }
    RegisterAuthoritativeTurnUndeadCasterTargets(
        actor_address,
        multiplayer::GetLocalTransportParticipantId(),
        turn_undead_precast_state,
        native_result != 0);
    if (!should_capture) {
        return native_result;
    }
    if (native_result == 0 &&
        !IsNativeSecondaryToggleSkill(skill_entry_index)) {
        Log(
            "Multiplayer local secondary cast rejected by native dispatcher. actor=" +
            HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot));
        return native_result;
    }
    if (!TryRefreshLocalSecondaryCastAim(actor_address, &capture)) {
        Log(
            "Multiplayer local secondary cast accepted without a readable "
            "post-dispatch aim. actor=" + HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot));
        return native_result;
    }

    const auto native_queue_id =
        multiplayer::QueueLocalSecondarySpellCastEvent(
            skill_entry_index,
            capture.belt_slot,
            capture.position_x,
            capture.position_y,
            capture.direction_x,
            capture.direction_y,
            0,
            capture.target_actor_address,
            capture.has_aim_target,
            capture.aim_target_x,
            capture.aim_target_y,
            capture.secondary_entry_indices.data(),
            capture.secondary_entry_indices.size(),
            capture.has_cursor_world_placement,
            capture.cursor_world_x,
            capture.cursor_world_y);
    if (native_queue_id != 0) {
        Log(
            "Multiplayer local secondary cast queued from native dispatcher. actor=" +
            HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot) +
            " native_result=" + std::to_string(native_result) +
            " native_queue_id=" + std::to_string(native_queue_id) +
            " cursor_world_placement=" +
                std::to_string(capture.has_cursor_world_placement ? 1 : 0) +
            " cursor_world=(" + std::to_string(capture.cursor_world_x) + "," +
                std::to_string(capture.cursor_world_y) + ")");
    }
    return native_result;
}
