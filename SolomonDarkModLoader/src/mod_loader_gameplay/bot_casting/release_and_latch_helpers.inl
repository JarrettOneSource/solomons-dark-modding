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

    const auto release_object_state =
        known_release_object_state != nullptr
            ? *known_release_object_state
            : ReadBotNativeActiveSpellObjectState(context, false);
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
        InvokeBotCastWithNativeActorSlot(context, [&] {
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
    }
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    const bool should_clear_cast_latch =
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

    const auto group_after =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0);
    const auto settled_heading =
        memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
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
