bool TrySpawnStandaloneRemoteWizardParticipantEntitySafe(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnStandaloneRemoteWizardParticipantEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TrySpawnRegisteredGameNpcParticipantEntitySafe(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnRegisteredGameNpcParticipantEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TrySpawnGameplaySlotBotParticipantEntitySafe(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnGameplaySlotBotParticipantEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
