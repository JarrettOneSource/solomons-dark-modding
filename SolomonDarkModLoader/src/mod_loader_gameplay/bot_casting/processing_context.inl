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
    std::uint8_t actor_slot = 0xFE;
    uintptr_t progression_runtime = 0;
    uintptr_t actor_progression_handle = 0;
    const auto actor_slot_text =
        memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot)
            ? HexString(actor_slot)
            : std::string("unreadable");
    const auto progression_runtime_text =
        memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &progression_runtime)
            ? HexString(progression_runtime)
            : std::string("unreadable");
    const auto actor_progression_handle_text =
        memory.TryReadField(
            actor_address,
            kActorProgressionHandleOffset,
            &actor_progression_handle)
            ? HexString(actor_progression_handle)
            : std::string("unreadable");
    Log(
        std::string("[bots] native cast slot diag. actor=") + HexString(actor_address) +
        " slot_offset=" + HexString(static_cast<std::uint32_t>(kActorSlotOffset)) +
        " slot=" + actor_slot_text +
        " progression_runtime=" + progression_runtime_text +
        " actor_progression_handle=" + actor_progression_handle_text);
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
