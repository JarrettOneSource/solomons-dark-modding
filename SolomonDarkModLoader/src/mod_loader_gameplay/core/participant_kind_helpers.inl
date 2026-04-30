bool IsStandaloneWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::StandaloneWizard;
}

bool IsGameplaySlotWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::GameplaySlotWizard;
}

bool IsRegisteredGameNpcKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::RegisteredGameNpc;
}

bool IsWizardParticipantKind(ParticipantEntityBinding::Kind kind) {
    return IsStandaloneWizardKind(kind) || IsGameplaySlotWizardKind(kind) ||
           IsRegisteredGameNpcKind(kind);
}
