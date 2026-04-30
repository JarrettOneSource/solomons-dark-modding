void ResetGameplaySeams() {
    std::size_t address_count = 0;
    const auto* address_bindings = GetAddressBindings(&address_count);
    for (std::size_t index = 0; index < address_count; ++index) {
        *address_bindings[index].target = 0;
    }

    std::size_t size_count = 0;
    const auto* size_bindings = GetSizeBindings(&size_count);
    for (std::size_t index = 0; index < size_count; ++index) {
        *size_bindings[index].target = 0;
    }
}

bool LoadAddressBinding(const AddressBinding& binding, std::string* error_message) {
    uintptr_t value = 0;
    if (!TryGetBinaryLayoutNumericValue(binding.section, binding.key, &value) || value == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Binary layout is missing [" + std::string(binding.section) + "]." + binding.key + ".";
        }
        return false;
    }

    *binding.target = value;
    return true;
}

bool LoadSizeBinding(const SizeBinding& binding, std::string* error_message) {
    uintptr_t value = 0;
    if (!TryGetBinaryLayoutNumericValue(binding.section, binding.key, &value)) {
        if (error_message != nullptr) {
            *error_message =
                "Binary layout is missing [" + std::string(binding.section) + "]." + binding.key + ".";
        }
        return false;
    }

    *binding.target = static_cast<std::size_t>(value);
    return true;
}

#undef SDMOD_ADDR
#undef SDMOD_SIZE

}  // namespace
