bool IsStandaloneWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::StandaloneWizard;
}

bool IsGameplaySlotWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::GameplaySlotWizard;
}

bool IsWizardParticipantKind(ParticipantEntityBinding::Kind kind) {
    return IsStandaloneWizardKind(kind) || IsGameplaySlotWizardKind(kind);
}

bool IsNativeRemoteParticipantBinding(
    const ParticipantEntityBinding* binding) {
    return binding != nullptr &&
           binding->controller_kind ==
               multiplayer::ParticipantControllerKind::Native;
}

bool IsPacketDrivenRemoteParticipantBinding(
    const ParticipantEntityBinding* binding) {
    return binding != nullptr &&
           (binding->controller_kind ==
                multiplayer::ParticipantControllerKind::Native ||
            (binding->controller_kind ==
                 multiplayer::ParticipantControllerKind::LuaBrain &&
             multiplayer::IsLocalTransportClient()));
}

bool IsRemoteInputControlledParticipantBinding(
    const ParticipantEntityBinding* binding) {
    return binding != nullptr &&
           (binding->controller_kind ==
                multiplayer::ParticipantControllerKind::Native ||
            binding->controller_kind ==
                multiplayer::ParticipantControllerKind::LuaBrain);
}

bool IsPacketDrivenRemoteParticipant(
    const multiplayer::ParticipantInfo& participant) {
    return multiplayer::IsRemoteParticipant(participant) &&
           (multiplayer::IsNativeControlledParticipant(participant) ||
            (multiplayer::IsLuaControlledParticipant(participant) &&
             multiplayer::IsLocalTransportClient()));
}
