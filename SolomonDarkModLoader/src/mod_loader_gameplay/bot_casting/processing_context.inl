constexpr float kBotCastRadiansToDegrees = 57.2957795130823208767981548141051703f;
constexpr std::uint8_t kBotCastActorActiveCastGroupSentinel = 0xFF;
constexpr std::uint16_t kBotCastActorActiveCastSlotSentinel = 0xFFFF;

struct BotCastProcessingContext {
    ParticipantEntityBinding* binding = nullptr;
    uintptr_t actor_address = 0;
    uintptr_t cleanup_address = 0;
    ProcessMemory* memory = nullptr;
};

template <typename InvokeFn>
void InvokeBotCastWithLocalPlayerSlot(
    const BotCastProcessingContext& context,
    InvokeFn&& invoke) {
    auto* binding = context.binding;
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;

    LocalPlayerCastShimState shim_state;
    const auto shim_active = EnterLocalPlayerCastShim(binding, &shim_state);
    invoke();
    LeaveLocalPlayerCastShim(shim_state);
    Log(
        std::string("[bots] slot_flip diag. actor=") + HexString(actor_address) +
        " slot_offset=" + HexString(static_cast<std::uint32_t>(kActorSlotOffset)) +
        " saved=" + HexString(shim_state.saved_actor_slot) +
        " during=" + HexString(
            memory.ReadFieldOr<std::uint8_t>(
                actor_address,
                kActorSlotOffset,
                static_cast<std::uint8_t>(0xFE))) +
        " flip_needed=" + (shim_active ? "1" : "0") +
        " flip_wr=" + (shim_active ? "1" : "0") +
        " restore_wr=" + (shim_active ? "1" : "0") +
        " shim_slot=" + std::to_string(binding->gameplay_slot) +
        " prog_redirect=" + (shim_state.progression_slot_redirected ? "1" : "0") +
        " prog_restore=" + (shim_state.progression_slot_restore_needed ? "1" : "0") +
        " prog_saved=" + HexString(shim_state.saved_local_progression_handle) +
        " prog_bot=" + HexString(shim_state.redirected_progression_handle));
}

void RestoreBotCastAim(
    const BotCastProcessingContext& context,
    const ParticipantEntityBinding::OngoingCastState& state) {
    auto* binding = context.binding;
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;

    if (state.have_aim_heading) {
        (void)RefreshWizardBindingTargetFacing(binding);
        if (!ApplyWizardBindingFacingState(binding, actor_address)) {
            ApplyWizardActorFacingState(actor_address, state.heading_before);
        }
    }
    if (state.have_aim_target) {
        (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, state.aim_x_before);
        (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, state.aim_y_before);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address, kActorAimTargetAux0Offset, state.aim_aux0_before);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address, kActorAimTargetAux1Offset, state.aim_aux1_before);
    }
    (void)memory.TryWriteField<std::uint8_t>(
        actor_address, kActorCastSpreadModeByteOffset, state.spread_before);
}
