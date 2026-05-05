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
void InvokeBotCastWithNativeActorSlot(
    const BotCastProcessingContext& context,
    InvokeFn&& invoke) {
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;
    invoke();
    Log(
        std::string("[bots] native cast slot diag. actor=") + HexString(actor_address) +
        " slot_offset=" + HexString(static_cast<std::uint32_t>(kActorSlotOffset)) +
        " slot=" + HexString(
            memory.ReadFieldOr<std::uint8_t>(
                actor_address,
                kActorSlotOffset,
                static_cast<std::uint8_t>(0xFE))) +
        " progression_runtime=" +
            HexString(memory.ReadFieldOr<uintptr_t>(
                actor_address,
                kActorProgressionRuntimeStateOffset,
                0)) +
        " actor_progression_handle=" +
            HexString(memory.ReadFieldOr<uintptr_t>(
                actor_address,
                kActorProgressionHandleOffset,
                0)));
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
