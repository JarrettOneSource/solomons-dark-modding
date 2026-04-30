bool InitializeGameplaySeams(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    if (state.loaded) {
        return true;
    }

    if (!IsBinaryLayoutLoaded()) {
        state.last_error = "Binary layout is not loaded.";
        if (error_message != nullptr) {
            *error_message = state.last_error;
        }
        return false;
    }

    ResetGameplaySeams();

    std::size_t address_count = 0;
    const auto* address_bindings = GetAddressBindings(&address_count);
    for (std::size_t index = 0; index < address_count; ++index) {
        if (!LoadAddressBinding(address_bindings[index], &state.last_error)) {
            ResetGameplaySeams();
            if (error_message != nullptr) {
                *error_message = state.last_error;
            }
            return false;
        }
    }

    std::size_t size_count = 0;
    const auto* size_bindings = GetSizeBindings(&size_count);
    for (std::size_t index = 0; index < size_count; ++index) {
        if (!LoadSizeBinding(size_bindings[index], &state.last_error)) {
            ResetGameplaySeams();
            if (error_message != nullptr) {
                *error_message = state.last_error;
            }
            return false;
        }
    }

    state.loaded = true;
    state.last_error.clear();
    return true;
}

void ShutdownGameplaySeams() {
    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    ResetGameplaySeams();
    state.loaded = false;
    state.last_error.clear();
}

bool AreGameplaySeamsLoaded() {
    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    return state.loaded;
}

std::string GetGameplaySeamsLoadError() {
    auto& state = GetGameplaySeamState();
    std::scoped_lock lock(state.mutex);
    return state.last_error;
}
