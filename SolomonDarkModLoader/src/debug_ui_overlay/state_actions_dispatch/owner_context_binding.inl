bool TryReadPointerValueDirect(uintptr_t address, uintptr_t* value) {
    if (address == 0 || value == nullptr) {
        return false;
    }

    __try {
        *value = *reinterpret_cast<const uintptr_t*>(address);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryReadPointerFieldDirect(const void* object, size_t offset, uintptr_t* value) {
    if (object == nullptr || value == nullptr) {
        return false;
    }

    const auto field_address = reinterpret_cast<uintptr_t>(object) + offset;
    return TryReadPointerValueDirect(field_address, value);
}

struct UiOwnerContextGlobalBinding {
    uintptr_t resolved_address = 0;
    uintptr_t previous_value = 0;
    uintptr_t bound_value = 0;
    bool changed = false;
};

bool TryResolveUiOwnerContextBindingValue(
    const UiActionDispatchExpectation& expectation,
    uintptr_t owner_address,
    uintptr_t* binding_value,
    std::string* error_message) {
    if (binding_value == nullptr) {
        return false;
    }

    *binding_value = owner_address;
    if (owner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "UI owner context binding requires a live owner object.";
        }
        return false;
    }

    const uintptr_t context_source_globals[] = {
        expectation.owner_context_source_global_address,
        expectation.owner_context_source_alt_global_address_1,
        expectation.owner_context_source_alt_global_address_2,
    };

    auto has_explicit_source = false;
    for (const auto source_global_address : context_source_globals) {
        if (source_global_address == 0) {
            continue;
        }

        has_explicit_source = true;
        uintptr_t source_value = 0;
        if (TryReadResolvedGamePointer(source_global_address, &source_value) && source_value != 0) {
            *binding_value = source_value;
            return true;
        }
    }

    if (has_explicit_source) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a non-zero UI owner context source pointer.";
        }
        return false;
    }

    return true;
}

bool TryValidateUiActionOwnerReadiness(
    const UiActionDispatchExpectation& expectation,
    uintptr_t owner_address,
    std::string_view action_name,
    std::string* error_message) {
    if (owner_address == 0) {
        return true;
    }

    if (expectation.owner_optional_enabled_byte_pointer_offset != 0) {
        uintptr_t enabled_byte_pointer = 0;
        if (!TryReadPointerValueDirect(
                owner_address + expectation.owner_optional_enabled_byte_pointer_offset,
                &enabled_byte_pointer)) {
            if (error_message != nullptr) {
                *error_message =
                    "UI action '" + std::string(action_name) + "' owner readiness probe could not read " +
                    HexString(owner_address + expectation.owner_optional_enabled_byte_pointer_offset) +
                    " from owner=" + HexString(owner_address) + ".";
            }
            return false;
        }

        if (enabled_byte_pointer != 0) {
            std::uint8_t enabled_byte = 0;
            if (!TryReadByteValueDirect(enabled_byte_pointer, &enabled_byte)) {
                if (error_message != nullptr) {
                    *error_message =
                        "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                        HexString(expectation.owner_optional_enabled_byte_pointer_offset) + " = " +
                        HexString(enabled_byte_pointer) + " owner=" + HexString(owner_address) + ".";
                }
                return false;
            }

            if (enabled_byte == 0) {
                if (error_message != nullptr) {
                    *error_message =
                        "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                        HexString(expectation.owner_optional_enabled_byte_pointer_offset) + " = " +
                        HexString(enabled_byte_pointer) + " byte=0 owner=" + HexString(owner_address) + ".";
                }
                return false;
            }
        }
    }

    if (expectation.owner_ready_pointer_offset == 0) {
        return true;
    }

    uintptr_t owner_ready_value = 0;
    if (!TryReadPointerValueDirect(owner_address + expectation.owner_ready_pointer_offset, &owner_ready_value)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner readiness probe could not read " +
                HexString(owner_address + expectation.owner_ready_pointer_offset) +
                " from owner=" + HexString(owner_address) + ".";
        }
        return false;
    }

    if (owner_ready_value < 0x10000) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                HexString(expectation.owner_ready_pointer_offset) + " = " + HexString(owner_ready_value) +
                " owner=" + HexString(owner_address) + ".";
        }
        return false;
    }

    if (owner_ready_value >= 0x80000000u) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner is not ready yet: field +" +
                HexString(expectation.owner_ready_pointer_offset) + " = " + HexString(owner_ready_value) +
                " owner=" + HexString(owner_address) + ".";
        }
        return false;
    }

    std::uint32_t owner_ready_probe = 0;
    if (!TryReadUInt32ValueDirect(owner_ready_value + sizeof(std::uint32_t), &owner_ready_probe)) {
        if (error_message != nullptr) {
            *error_message =
                "UI action '" + std::string(action_name) + "' owner readiness probe could not read pointee " +
                HexString(owner_ready_value + sizeof(std::uint32_t)) +
                " from owner=" + HexString(owner_address) +
                " field=" + HexString(owner_ready_value) + ".";
        }
        return false;
    }

    return true;
}

bool TryBindUiOwnerContextGlobal(
    uintptr_t absolute_global_address,
    uintptr_t binding_value,
    UiOwnerContextGlobalBinding* binding,
    std::string* error_message) {
    if (binding == nullptr) {
        return absolute_global_address == 0;
    }

    *binding = UiOwnerContextGlobalBinding{};
    if (absolute_global_address == 0 || binding_value == 0) {
        return true;
    }

    const auto resolved_address = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_global_address);
    if (resolved_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured UI owner context global.";
        }
        return false;
    }

    uintptr_t previous_value = 0;
    if (!TryReadPointerValueDirect(resolved_address, &previous_value)) {
        if (error_message != nullptr) {
            *error_message = "Unable to read the configured UI owner context global.";
        }
        return false;
    }

    binding->resolved_address = resolved_address;
    binding->previous_value = previous_value;
    binding->bound_value = binding_value;
    if (previous_value == binding_value) {
        return true;
    }

    if (!ProcessMemory::Instance().TryWriteValue(resolved_address, binding_value)) {
        if (error_message != nullptr) {
            *error_message = "Unable to bind the configured UI owner context global.";
        }
        return false;
    }

    binding->changed = true;
    return true;
}

void RestoreUiOwnerContextGlobal(const UiOwnerContextGlobalBinding& binding) {
    if (!binding.changed || binding.resolved_address == 0) {
        return;
    }

    (void)ProcessMemory::Instance().TryWriteValue(binding.resolved_address, binding.previous_value);
}
