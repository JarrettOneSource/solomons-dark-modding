void FinishBotCastNativeLifecycle(
    const BotCastProcessingContext& context,
    const ParticipantEntityBinding::OngoingCastState& state,
    const char* exit_label,
    bool clear_facing_target,
    bool run_active_handle_cleanup = true,
    const BotNativeActiveSpellObjectState* known_release_object_state = nullptr) {
    auto* binding = context.binding;
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;
    const auto cleanup_address = context.cleanup_address;
    const bool native_remote_participant = IsNativeRemoteParticipantBinding(binding);

    const auto release_object_state =
        known_release_object_state != nullptr
            ? *known_release_object_state
            : ReadBotNativeActiveSpellObjectState(context, false);
    auto apply_native_action_rearm = [&]() {
        if (native_remote_participant) {
            return false;
        }
        if (!state.saw_activity || state.selection_state_pointer == 0) {
            return false;
        }
        if (state.selection_target_seed_active) {
            (void)memory.TryWriteField<std::uint8_t>(
                state.selection_state_pointer,
                kActorControlBrainTargetSlotOffset,
                state.selection_target_group_seed);
            (void)memory.TryWriteField<std::uint16_t>(
                state.selection_state_pointer,
                kActorControlBrainTargetHandleOffset,
                state.selection_target_slot_seed);
            (void)memory.TryWriteField<std::int32_t>(
                state.selection_state_pointer,
                kActorControlBrainRetargetTicksOffset,
                kBotNativeActionRearmTicks);
            (void)memory.TryWriteField<std::int32_t>(
                state.selection_state_pointer,
                kActorControlBrainTargetCooldownTicksOffset,
                0);
        }
        const bool cooldown_written = memory.TryWriteField<std::int32_t>(
            state.selection_state_pointer,
            kActorControlBrainActionCooldownTicksOffset,
            kBotNativeActionRearmTicks);
        (void)memory.TryWriteField<std::int32_t>(
            state.selection_state_pointer,
            kActorControlBrainActionBurstTicksOffset,
            0);
        return cooldown_written;
    };
    std::uint8_t actor_group_before = kBotCastActorActiveCastGroupSentinel;
    std::uint16_t actor_slot_before = kBotCastActorActiveCastSlotSentinel;
    const bool actor_handle_before_readable =
        memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &actor_group_before) &&
        memory.TryReadField(actor_address, kActorActiveCastSlotShortOffset, &actor_slot_before);
    DWORD cleanup_exception_code = 0;
    bool cleanup_ok = true;
    bool cleanup_actor_handle_live = false;
    uintptr_t cleanup_state_entry_address = 0;
    int cleanup_state_before = -1;
    int cleanup_state_for_call = -1;
    int cleanup_state_after = -1;
    bool cleanup_state_available = false;
    bool cleanup_state_write_ok = false;
    bool cleanup_state_restore_ok = true;
    bool cleanup_invoked = false;
    std::string cleanup_owner_context;
    cleanup_actor_handle_live =
        actor_handle_before_readable &&
        actor_group_before != kBotCastActorActiveCastGroupSentinel &&
        actor_slot_before != kBotCastActorActiveCastSlotSentinel;
    if (run_active_handle_cleanup && cleanup_actor_handle_live) {
        uintptr_t cleanup_state_table_address = 0;
        int cleanup_state_entry_count = 0;
        if (TryResolveGameplayIndexState(
                &cleanup_state_table_address,
                &cleanup_state_entry_count) &&
            cleanup_state_table_address != 0 &&
            cleanup_state_entry_count > 0 &&
            memory.TryReadValue<int>(cleanup_state_table_address, &cleanup_state_before)) {
            constexpr int kNativeCleanupRequiredGameplayState = 5;
            cleanup_state_entry_address = cleanup_state_table_address;
            cleanup_state_available = true;
            cleanup_state_for_call = cleanup_state_before;
            if (cleanup_state_before != kNativeCleanupRequiredGameplayState) {
                cleanup_state_write_ok =
                    memory.TryWriteValue<int>(
                        cleanup_state_entry_address,
                        kNativeCleanupRequiredGameplayState);
                if (cleanup_state_write_ok) {
                    cleanup_state_for_call = kNativeCleanupRequiredGameplayState;
                }
            }
        }
        InvokeBotCastCleanupWithNativeOwnerContext(
            context,
            [&] {
                cleanup_invoked = true;
                cleanup_ok = CallCastActiveHandleCleanupSafe(
                    cleanup_address, actor_address, &cleanup_exception_code);
            },
            &cleanup_owner_context);
        if (cleanup_state_write_ok) {
            cleanup_state_restore_ok =
                memory.TryWriteValue<int>(
                    cleanup_state_entry_address,
                    cleanup_state_before);
        }
        if (cleanup_state_available && cleanup_state_entry_address != 0) {
            cleanup_state_available =
                memory.TryReadValue<int>(cleanup_state_entry_address, &cleanup_state_after);
        }
    }
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    const bool mana_stop =
        std::strcmp(exit_label, "mana_reserve") == 0 ||
        std::strcmp(exit_label, "mana_depleted") == 0;
    const bool should_clear_cast_latch =
        mana_stop ||
        state.bounded_release_requested ||
        (state.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
         actor_group_before == kBotCastActorActiveCastGroupSentinel);
    if (should_clear_cast_latch) {
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE4Offset, 0);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE8Offset, 0);
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorPostGateActiveByteOffset, 0);
    }
    RestoreBotCastAim(context, state);
    RestoreSelectionStateObjectAfterCast(state);
    RestoreSelectionBrainAfterCast(state);
    ClearSelectionBrainTarget(state.selection_state_pointer);
    const bool native_action_rearm_write = apply_native_action_rearm();
    RestoreOngoingCastNativeTargetActor(actor_address, state);
    if (clear_facing_target) {
        binding->facing_target_actor_address = 0;
    } else {
        (void)RefreshWizardBindingTargetFacing(binding);
    }
    if (state.gameplay_selection_state_override_active &&
        binding->gameplay_slot >= 0 &&
        state.gameplay_selection_state_before != kUnknownAnimationStateId) {
        std::string selection_error;
        (void)TryWriteActorAnimationStateIdDirect(actor_address, state.gameplay_selection_state_before);
        (void)TryWriteGameplaySelectionStateForSlot(
            binding->gameplay_slot,
            state.gameplay_selection_state_before,
            &selection_error);
    }
    if (state.progression_spell_id_override_active && state.progression_runtime_address != 0) {
        (void)memory.TryWriteField<std::int32_t>(
            state.progression_runtime_address,
            kProgressionCurrentSpellIdOffset,
            state.progression_spell_id_before);
    }

    uintptr_t remote_visual_staging_before = 0;
    bool remote_visual_staging_readable = false;
    bool remote_visual_staging_clear_requested = false;
    bool remote_visual_staging_clear_ok = true;
    float remote_overlay_alpha_before = 0.0f;
    float remote_overlay_phase_before = 0.0f;
    bool remote_overlay_alpha_readable = false;
    bool remote_overlay_phase_readable = false;
    bool remote_overlay_alpha_clear_requested = false;
    bool remote_overlay_phase_clear_requested = false;
    bool remote_overlay_alpha_clear_ok = true;
    bool remote_overlay_phase_clear_ok = true;
    if (native_remote_participant) {
        // The continuous-primary active field aliases the hub staff/orb staging
        // pointer at +0x264. Leave it alone while a cast is active, but settle it
        // when the native remote cast lifecycle finishes so idle rendering returns
        // to the target-owned equip-lane staff only.
        remote_visual_staging_readable =
            memory.TryReadField(
                actor_address,
                kActorContinuousPrimaryActiveOffset,
                &remote_visual_staging_before);
        remote_visual_staging_clear_requested =
            remote_visual_staging_readable && remote_visual_staging_before != 0;
        if (remote_visual_staging_clear_requested) {
            remote_visual_staging_clear_ok =
                memory.TryWriteField<uintptr_t>(
                    actor_address,
                    kActorContinuousPrimaryActiveOffset,
                    0);
        }
        // Remote casts run through stock spell handlers without the local player
        // input lifecycle that normally drains the render overlay phase/cache.
        // Leaving +0x248/+0x268 nonzero was proven to create persistent oversized
        // staff/orb helper draws after held casts. These fields are native-owned
        // diagnostics during playback, so clear only at remote cast completion.
        if (kActorRenderDriveOverlayAlphaOffset != 0) {
            remote_overlay_alpha_readable =
                TryReadFiniteFloatField(
                    actor_address,
                    kActorRenderDriveOverlayAlphaOffset,
                    &remote_overlay_alpha_before);
            remote_overlay_alpha_clear_requested =
                remote_overlay_alpha_readable &&
                std::fabs(remote_overlay_alpha_before) > 0.001f;
            if (remote_overlay_alpha_clear_requested) {
                remote_overlay_alpha_clear_ok =
                    memory.TryWriteField<float>(
                        actor_address,
                        kActorRenderDriveOverlayAlphaOffset,
                        0.0f);
            }
        }
        if (kActorRenderDriveMoveBlendOffset != 0) {
            remote_overlay_phase_readable =
                TryReadFiniteFloatField(
                    actor_address,
                    kActorRenderDriveMoveBlendOffset,
                    &remote_overlay_phase_before);
            remote_overlay_phase_clear_requested =
                remote_overlay_phase_readable &&
                std::fabs(remote_overlay_phase_before) > 0.001f;
            if (remote_overlay_phase_clear_requested) {
                remote_overlay_phase_clear_ok =
                    memory.TryWriteField<float>(
                        actor_address,
                        kActorRenderDriveMoveBlendOffset,
                        0.0f);
            }
        }
    }

    std::uint8_t group_after = kBotCastActorActiveCastGroupSentinel;
    const bool group_after_readable =
        memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &group_after);
    float settled_heading = 0.0f;
    const bool settled_heading_readable =
        TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &settled_heading);
    const bool completed_boulder_at_max =
        release_object_state.boulder_max_size_reached ||
        state.bounded_release_at_max_size ||
        (OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(state) &&
         std::strcmp(exit_label, "max_size_released") == 0);
    const std::string bounded_release_summary =
        state.bounded_release_requested
            ? std::string(" release_reason=") +
                  (state.bounded_release_at_max_size
                       ? std::string("max_size")
                       : state.bounded_release_target_lethal
                           ? std::string("target_lethal")
                           : std::string("native")) +
                  " release_charge=" + std::to_string(state.bounded_release_charge) +
                  " release_base_damage=" + std::to_string(state.bounded_release_base_damage) +
                  " release_projected_damage=" +
                      std::to_string(state.bounded_release_projected_damage) +
                  " release_damage_output_scale=" +
                      std::to_string(state.bounded_release_damage_output_scale) +
                  " release_damage_scale=" +
                      std::to_string(state.bounded_release_damage_scale) +
                  " release_damage_floor=" +
                      std::to_string(state.bounded_release_damage_floor) +
                  " release_damage_cap_scale=" +
                      std::to_string(state.bounded_release_damage_cap_scale) +
                  " release_projected_release_damage=" +
                      std::to_string(state.bounded_release_projected_release_damage) +
                  " release_projected_hp_damage=" +
                      std::to_string(state.bounded_release_projected_hp_damage) +
                  " release_target_hp=" + std::to_string(state.bounded_release_target_hp) +
                  " release_target_actor=" + HexString(state.bounded_release_target_actor)
            : std::string("");
    (void)multiplayer::FinishBotAttack(
        binding->bot_id,
        settled_heading_readable,
        settled_heading,
        clear_facing_target);
    if (state.remote_input_controlled) {
        (void)multiplayer::ClearBotCastInput(
            binding->bot_id,
            state.remote_input_cast_sequence);
    }
    const auto group_before_text =
        actor_handle_before_readable ? HexString(actor_group_before) : std::string("unreadable");
    const auto slot_before_text =
        actor_handle_before_readable ? HexString(actor_slot_before) : std::string("unreadable");
    const auto group_after_text =
        group_after_readable ? HexString(group_after) : std::string("unreadable");
    Log(
        std::string("[bots] cast complete (") + exit_label + "). bot_id=" +
        std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(state.skill_id) +
        " remote_input_controlled=" +
            (state.remote_input_controlled ? std::string("1") : std::string("0")) +
        " remote_cast_sequence=" + std::to_string(state.remote_input_cast_sequence) +
        " ticks=" + std::to_string(state.ticks_waiting) +
        " post_release_ticks=" + std::to_string(state.bounded_post_release_ticks_waiting) +
        " saw_latch=" + (state.saw_latch ? std::string("1") : std::string("0")) +
        " remote_projectile_baseline=" +
            (state.remote_per_cast_projectile_baseline_valid ? std::string("1") : std::string("0")) +
        " remote_projectile_expected_type=" +
            HexString(static_cast<uintptr_t>(state.remote_per_cast_projectile_expected_type)) +
        " remote_projectile_before=" +
            std::to_string(state.remote_per_cast_projectile_count_before) +
        " remote_projectile_observed=" +
            (state.remote_per_cast_projectile_observed ? std::string("1") : std::string("0")) +
        " remote_projectile_observed_actor=" +
            HexString(state.remote_per_cast_projectile_observed_actor) +
        " remote_projectile_observed_ticks=" +
            std::to_string(state.remote_per_cast_projectile_observed_ticks_waiting) +
        " remote_projectile_missing_ticks=" +
            std::to_string(state.remote_per_cast_projectile_missing_ticks_waiting) +
        " remote_projectile_reached_target=" +
            (state.remote_per_cast_projectile_reached_target ? std::string("1") : std::string("0")) +
        " remote_projectile_target_ticks=" +
            std::to_string(state.remote_per_cast_projectile_target_ticks_waiting) +
        " group_before=" + group_before_text +
        " slot_before=" + slot_before_text +
        " group_after=" + group_after_text +
        " cleanup_requested=" + (run_active_handle_cleanup ? std::string("1") : std::string("0")) +
        " cleanup_actor_handle_live=" + (cleanup_actor_handle_live ? std::string("1") : std::string("0")) +
        " cleanup_invoked=" + (cleanup_invoked ? std::string("1") : std::string("0")) +
        " cleanup_state=" + HexString(cleanup_state_entry_address) +
        " cleanup_state_before=" + std::to_string(cleanup_state_before) +
        " cleanup_state_for_call=" + std::to_string(cleanup_state_for_call) +
        " cleanup_state_after=" + std::to_string(cleanup_state_after) +
        " cleanup_state_write=" + (cleanup_state_write_ok ? std::string("1") : std::string("0")) +
        " cleanup_state_restore=" + (cleanup_state_restore_ok ? std::string("1") : std::string("0")) +
        " cleanup_owner_context={" + cleanup_owner_context + "}" +
        " native_action_rearm=" + (native_action_rearm_write ? std::string("1") : std::string("0")) +
        " native_action_rearm_ticks=" + std::to_string(kBotNativeActionRearmTicks) +
        " remote_visual_staging_before=" +
            (remote_visual_staging_readable ? HexString(remote_visual_staging_before) : std::string("unreadable")) +
        " remote_visual_staging_clear=" +
            (remote_visual_staging_clear_requested ? std::string("1") : std::string("0")) +
        " remote_visual_staging_clear_ok=" +
            (remote_visual_staging_clear_ok ? std::string("1") : std::string("0")) +
        " remote_overlay_alpha_before=" +
            (remote_overlay_alpha_readable
                 ? std::to_string(remote_overlay_alpha_before)
                 : std::string("unreadable")) +
        " remote_overlay_alpha_clear=" +
            (remote_overlay_alpha_clear_requested ? std::string("1") : std::string("0")) +
        " remote_overlay_alpha_clear_ok=" +
            (remote_overlay_alpha_clear_ok ? std::string("1") : std::string("0")) +
        " remote_overlay_phase_before=" +
            (remote_overlay_phase_readable
                 ? std::to_string(remote_overlay_phase_before)
                 : std::string("unreadable")) +
        " remote_overlay_phase_clear=" +
            (remote_overlay_phase_clear_requested ? std::string("1") : std::string("0")) +
        " remote_overlay_phase_clear_ok=" +
            (remote_overlay_phase_clear_ok ? std::string("1") : std::string("0")) +
        " handle_source=" +
            (release_object_state.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
        " selection_state=" + HexString(release_object_state.selection_state) +
        " native_lookup=" + (release_object_state.lookup_attempted ? std::string("1") : std::string("0")) +
        " native_lookup_ok=" + (release_object_state.lookup_succeeded ? std::string("1") : std::string("0")) +
        " native_lookup_seh=" + HexString(release_object_state.lookup_exception) +
        " obj_ptr=" + HexString(release_object_state.object) +
        " obj_type=" + HexString(release_object_state.object_type) +
        " obj_x=" + std::to_string(release_object_state.object_x) +
        " obj_y=" + std::to_string(release_object_state.object_y) +
        " obj_heading=" + std::to_string(release_object_state.object_heading) +
        " obj_radius=" + std::to_string(release_object_state.object_radius) +
        " obj_charge=" + std::to_string(release_object_state.charge) +
        " obj_growth_rate=" + std::to_string(release_object_state.growth_rate) +
        " obj_release_charge=" + std::to_string(release_object_state.release_charge) +
        " obj_release_damage=" + std::to_string(release_object_state.release_damage) +
        " obj_release_base_damage=" + std::to_string(release_object_state.release_base_damage) +
        " obj_max_charge=" + std::to_string(release_object_state.max_charge) +
        " obj_phase=" + HexString(release_object_state.phase) +
        " obj_release_timer=" + HexString(release_object_state.release_timer) +
        " boulder_max_size=" +
            (completed_boulder_at_max ? std::string("1") : std::string("0")) +
        bounded_release_summary +
        (cleanup_ok ? std::string("") :
                      std::string(" cleanup_seh=") + HexString(cleanup_exception_code)));
}

void LogBotSpellObjectDiag(
    const BotCastProcessingContext& context,
    std::uint8_t active_group_post) {
    auto* binding = context.binding;
    const auto actor_address = context.actor_address;

    auto state = ReadBotNativeActiveSpellObjectState(context);
    state.group = active_group_post;
    Log(
        std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
        " group=" + HexString(state.group) +
        " slot=" + HexString(state.slot) +
        " handle_source=" + (state.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
        " selection_state=" + HexString(state.selection_state) +
        " world=" + HexString(state.world) +
        " native_lookup=" + (state.lookup_attempted ? std::string("1") : std::string("0")) +
        " native_lookup_ok=" + (state.lookup_succeeded ? std::string("1") : std::string("0")) +
        " native_lookup_seh=" + HexString(state.lookup_exception) +
        " obj_ptr=" + HexString(state.object) +
        " obj_type=" + HexString(state.object_type) +
        " obj_x=" + std::to_string(state.object_x) +
        " obj_y=" + std::to_string(state.object_y) +
        " obj_heading=" + std::to_string(state.object_heading) +
        " obj_radius=" + std::to_string(state.object_radius) +
        " obj_charge=" + std::to_string(state.charge) +
        " obj_growth_rate=" + std::to_string(state.growth_rate) +
        " obj_release_charge=" + std::to_string(state.release_charge) +
        " obj_max_charge=" + std::to_string(state.max_charge) +
        " obj_phase=" + std::to_string(state.phase) +
        " obj_release_timer=" + std::to_string(state.release_timer) +
        " boulder_max_size=" + (state.boulder_max_size_reached ? std::string("1") : std::string("0")) +
        " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
}
