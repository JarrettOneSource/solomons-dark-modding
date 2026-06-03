bool IsStandaloneWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::StandaloneWizard;
}

bool IsGameplaySlotWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::GameplaySlotWizard;
}

bool IsWizardParticipantKind(ParticipantEntityBinding::Kind kind) {
    return IsStandaloneWizardKind(kind) || IsGameplaySlotWizardKind(kind);
}
