void ReleaseBotSpellHandle(
    const BotCastProcessingContext& context,
    const ParticipantEntityBinding::OngoingCastState& state,
    const char* exit_label,
    bool clear_facing_target,
    bool run_active_handle_cleanup = true,
    const BotActiveSpellObjectSnapshot* known_release_object_snapshot = nullptr) {
    auto* binding = context.binding;
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;
    const auto cleanup_address = context.cleanup_address;

    const auto release_object_snapshot =
        known_release_object_snapshot != nullptr
            ? *known_release_object_snapshot
            : ReadBotActiveSpellObjectSnapshot(context, false);
    const auto actor_group_before =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    const auto actor_slot_before =
        memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0);
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
    cleanup_actor_handle_live =
        actor_group_before != kBotCastActorActiveCastGroupSentinel &&
        actor_slot_before != kBotCastActorActiveCastSlotSentinel;
    if (!run_active_handle_cleanup) {
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address, kActorActiveCastGroupByteOffset, kBotCastActorActiveCastGroupSentinel);
        (void)memory.TryWriteField<std::uint16_t>(
            actor_address, kActorActiveCastSlotShortOffset, kBotCastActorActiveCastSlotSentinel);
    } else if (cleanup_actor_handle_live) {
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
        InvokeBotCastWithLocalPlayerSlot(context, [&] {
            cleanup_ok = CallCastActiveHandleCleanupSafe(
                cleanup_address, actor_address, &cleanup_exception_code);
        });
        if (cleanup_state_write_ok) {
            cleanup_state_restore_ok =
                memory.TryWriteValue<int>(
                    cleanup_state_entry_address,
                    cleanup_state_before);
        }
        if (cleanup_state_available && cleanup_state_entry_address != 0) {
            cleanup_state_after =
                memory.ReadValueOr<int>(cleanup_state_entry_address, -1);
        }
        if (!cleanup_ok) {
            // Native cleanup raised SEH. Fall back to writing the sentinels
            // directly so the next cast's init gate passes; vtable-side
            // effects get skipped, but the handle is released and future
            // casts are safe.
            (void)memory.TryWriteField<std::uint8_t>(
                actor_address, kActorActiveCastGroupByteOffset, kBotCastActorActiveCastGroupSentinel);
            (void)memory.TryWriteField<std::uint16_t>(
                actor_address, kActorActiveCastSlotShortOffset, kBotCastActorActiveCastSlotSentinel);
        }
    }
    const bool defer_bounded_latch_clear =
        state.bounded_release_requested &&
        state.bounded_release_at_damage_threshold &&
        !state.bounded_release_at_max_size;
    if (!defer_bounded_latch_clear) {
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
    }
    const bool should_clear_cast_latch =
        !defer_bounded_latch_clear &&
        state.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
        (actor_group_before == kBotCastActorActiveCastGroupSentinel ||
         state.bounded_release_requested);
    if (should_clear_cast_latch) {
        (void)memory.TryWriteField<std::uint32_t>(actor_address, 0xE4, 0);
        (void)memory.TryWriteField<std::uint32_t>(actor_address, 0xE8, 0);
    }
    RestoreBotCastAim(context, state);
    if (state.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
        state.pure_primary_item_sink_fallback != 0) {
        std::string lane_error;
        if (!SetEquipVisualLaneObject(
                actor_address,
                kActorEquipRuntimeVisualLinkAttachmentOffset,
                state.pure_primary_item_sink_fallback,
                "attachment",
                &lane_error) &&
            !lane_error.empty()) {
            Log(
                "[bots] pure-primary attachment restore failed. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(actor_address) +
                " error=" + lane_error);
        }
    }
    RestoreSelectionStateObjectAfterCast(state);
    RestoreSelectionBrainAfterCast(state);
    ClearSelectionBrainTarget(state.selection_state_pointer);
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
            0x750,
            state.progression_spell_id_before);
    }

    const auto group_after =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    const auto settled_heading =
        memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
    const bool completed_boulder_at_max =
        release_object_snapshot.boulder_max_size_reached ||
        state.bounded_release_at_max_size ||
        (SkillRequiresBoundedHeldCastInputDuringNativeTick(ResolveOngoingNativeTickSkillId(state)) &&
         std::strcmp(exit_label, "max_size_released") == 0);
    const std::string bounded_release_summary =
        state.bounded_release_requested
            ? std::string(" release_reason=") +
                  (state.bounded_release_at_damage_threshold
                       ? std::string("damage_threshold")
                       : (state.bounded_release_at_max_size ? std::string("max_size") : std::string("unknown"))) +
                  " release_charge=" + std::to_string(state.bounded_release_charge) +
                  " release_base_damage=" + std::to_string(state.bounded_release_base_damage) +
                  " release_statbook_damage=" +
                      std::to_string(state.bounded_release_statbook_damage) +
                  " release_projected_damage=" +
                      std::to_string(state.bounded_release_projected_damage) +
                  " release_target_hp=" + std::to_string(state.bounded_release_target_hp) +
                  " release_target_actor=" + HexString(state.bounded_release_target_actor) +
                  " release_damage_native=" +
                      (state.bounded_release_damage_native ? std::string("1") : std::string("0"))
            : std::string("");
    (void)multiplayer::FinishBotAttack(
        binding->bot_id,
        true,
        settled_heading,
        clear_facing_target);
    Log(
        std::string("[bots] cast complete (") + exit_label + "). bot_id=" +
        std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(state.skill_id) +
        " ticks=" + std::to_string(state.ticks_waiting) +
        " post_release_ticks=" + std::to_string(state.bounded_post_release_ticks_waiting) +
        " saw_latch=" + (state.saw_latch ? std::string("1") : std::string("0")) +
        " group_before=" + HexString(actor_group_before) +
        " slot_before=" + HexString(actor_slot_before) +
        " group_after=" + HexString(group_after) +
        " cleanup_requested=" + (run_active_handle_cleanup ? std::string("1") : std::string("0")) +
        " cleanup_actor_handle_live=" + (cleanup_actor_handle_live ? std::string("1") : std::string("0")) +
        " cleanup_state=" + HexString(cleanup_state_entry_address) +
        " cleanup_state_before=" + std::to_string(cleanup_state_before) +
        " cleanup_state_for_call=" + std::to_string(cleanup_state_for_call) +
        " cleanup_state_after=" + std::to_string(cleanup_state_after) +
        " cleanup_state_write=" + (cleanup_state_write_ok ? std::string("1") : std::string("0")) +
        " cleanup_state_restore=" + (cleanup_state_restore_ok ? std::string("1") : std::string("0")) +
        " handle_source=" +
            (release_object_snapshot.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
        " selection_state=" + HexString(release_object_snapshot.selection_state) +
        " obj_ptr=" + HexString(release_object_snapshot.object) +
        " obj_vt=" + HexString(release_object_snapshot.vtable) +
        " obj_vt_1c=" + HexString(release_object_snapshot.update_fn) +
        " obj_vt_6c=" + HexString(release_object_snapshot.release_secondary_fn) +
        " obj_vt_70=" + HexString(release_object_snapshot.release_finalize_fn) +
        " obj_type=" + HexString(release_object_snapshot.object_type) +
        " obj_x=" + std::to_string(release_object_snapshot.object_x) +
        " obj_y=" + std::to_string(release_object_snapshot.object_y) +
        " obj_heading=" + std::to_string(release_object_snapshot.object_heading) +
        " obj_radius=" + std::to_string(release_object_snapshot.object_radius) +
        " obj_74=" + std::to_string(release_object_snapshot.object_f74) +
        " obj_1f0=" + std::to_string(release_object_snapshot.object_f1f0) +
        " obj_1fc=" + std::to_string(release_object_snapshot.object_f1fc) +
        " obj_22c=" + HexString(release_object_snapshot.object_f22c) +
        " obj_230=" + HexString(release_object_snapshot.object_f230) +
        " obj_74_raw=" + HexString(release_object_snapshot.object_f74_raw) +
        " obj_1f0_raw=" + HexString(release_object_snapshot.object_f1f0_raw) +
        " obj_1fc_raw=" + HexString(release_object_snapshot.object_f1fc_raw) +
        " boulder_max_size=" +
            (completed_boulder_at_max ? std::string("1") : std::string("0")) +
        bounded_release_summary +
        (cleanup_ok ? std::string("") :
                      std::string(" cleanup_seh=") + HexString(cleanup_exception_code)));
}

void ScheduleBotBoundedReleaseLatchClear(
    ParticipantEntityBinding::OngoingCastState& state) {
    constexpr std::uint64_t kBoundedCleanupLatchClearDelayMs = 100;
    state.bounded_cleanup_completed = true;
    state.bounded_cleanup_clear_after_ms =
        static_cast<std::uint64_t>(GetTickCount64()) +
        kBoundedCleanupLatchClearDelayMs;
}

void ClearBotBoundedReleaseCastLatch(
    const BotCastProcessingContext& context,
    ParticipantEntityBinding::OngoingCastState& state,
    const char* reason) {
    auto* binding = context.binding;
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;

    const auto actor_e4_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE4, 0);
    const auto actor_e8_before =
        memory.ReadFieldOr<std::uint32_t>(actor_address, 0xE8, 0);
    const bool primary_clear_ok =
        memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
    const bool e4_clear_ok =
        memory.TryWriteField<std::uint32_t>(actor_address, 0xE4, 0);
    const bool e8_clear_ok =
        memory.TryWriteField<std::uint32_t>(actor_address, 0xE8, 0);
    Log(
        "[bots] bounded release latch cleared. bot_id=" +
        std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(state.skill_id) +
        " reason=" + (reason != nullptr ? std::string(reason) : std::string("unknown")) +
        " ticks=" + std::to_string(state.ticks_waiting) +
        " clear_after_ms=" + std::to_string(state.bounded_cleanup_clear_after_ms) +
        " e4_before=" + HexString(actor_e4_before) +
        " e8_before=" + HexString(actor_e8_before) +
        " primary_clear=" + (primary_clear_ok ? std::string("1") : std::string("0")) +
        " e4_clear=" + (e4_clear_ok ? std::string("1") : std::string("0")) +
        " e8_clear=" + (e8_clear_ok ? std::string("1") : std::string("0")));
    state = ParticipantEntityBinding::OngoingCastState{};
}

void LogBotSpellObjectDiag(
    const BotCastProcessingContext& context,
    std::uint8_t active_group_post) {
    auto* binding = context.binding;
    const auto actor_address = context.actor_address;

    auto snapshot = ReadBotActiveSpellObjectSnapshot(context);
    snapshot.group = active_group_post;
    Log(
        std::string("[bots] spell_obj diag. bot_id=") + std::to_string(binding->bot_id) +
        " group=" + HexString(snapshot.group) +
        " slot=" + HexString(snapshot.slot) +
        " handle_source=" + (snapshot.handle_from_selection_state ? std::string("selection") : std::string("actor")) +
        " selection_state=" + HexString(snapshot.selection_state) +
        " world=" + HexString(snapshot.world) +
        " obj_ptr=" + HexString(snapshot.object) +
        " obj_vt=" + HexString(snapshot.vtable) +
        " obj_vt_1c=" + HexString(snapshot.update_fn) +
        " obj_vt_6c=" + HexString(snapshot.release_secondary_fn) +
        " obj_vt_70=" + HexString(snapshot.release_finalize_fn) +
        " obj_type=" + HexString(snapshot.object_type) +
        " obj_x=" + std::to_string(snapshot.object_x) +
        " obj_y=" + std::to_string(snapshot.object_y) +
        " obj_heading=" + std::to_string(snapshot.object_heading) +
        " obj_radius=" + std::to_string(snapshot.object_radius) +
        " obj_74=" + std::to_string(snapshot.object_f74) +
        " obj_1f0=" + std::to_string(snapshot.object_f1f0) +
        " obj_1fc=" + std::to_string(snapshot.object_f1fc) +
        " obj_74_raw=" + HexString(snapshot.object_f74_raw) +
        " obj_1f0_raw=" + HexString(snapshot.object_f1f0_raw) +
        " obj_1fc_raw=" + HexString(snapshot.object_f1fc_raw) +
        " obj_22c=" + std::to_string(snapshot.object_f22c) +
        " obj_230=" + std::to_string(snapshot.object_f230) +
        " boulder_max_size=" + (snapshot.boulder_max_size_reached ? std::string("1") : std::string("0")) +
        " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
}
