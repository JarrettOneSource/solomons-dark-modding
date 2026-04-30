struct UiOwnerControlActionException {
    DWORD code = 0;
    uintptr_t address = 0;
    uintptr_t access_type = 0;
    uintptr_t access_address = 0;
};

int CaptureUiOwnerControlActionException(
    EXCEPTION_POINTERS* exception_pointers,
    UiOwnerControlActionException* exception) {
    if (exception == nullptr || exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_EXECUTE_HANDLER;
    }

    const auto* record = exception_pointers->ExceptionRecord;
    exception->code = record->ExceptionCode;
    exception->address = reinterpret_cast<uintptr_t>(record->ExceptionAddress);
    if (record->NumberParameters >= 1) {
        exception->access_type = static_cast<uintptr_t>(record->ExceptionInformation[0]);
    }
    if (record->NumberParameters >= 2) {
        exception->access_address = static_cast<uintptr_t>(record->ExceptionInformation[1]);
    }

    return EXCEPTION_EXECUTE_HANDLER;
}

bool TryCallUiOwnerControlAction(
    UiOwnerControlActionFn action_method,
    uintptr_t owner_address,
    uintptr_t control_address,
    UiOwnerControlActionException* exception) {
    if (action_method == nullptr || owner_address == 0 || control_address == 0) {
        return false;
    }

    if (exception != nullptr) {
        *exception = UiOwnerControlActionException{};
    }

    __try {
        action_method(reinterpret_cast<void*>(owner_address), reinterpret_cast<void*>(control_address));
        return true;
    } __except (CaptureUiOwnerControlActionException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryCallUiOwnerNoArgAction(
    UiOwnerNoArgActionFn action_method,
    uintptr_t owner_address,
    UiOwnerControlActionException* exception) {
    if (action_method == nullptr || owner_address == 0) {
        return false;
    }

    if (exception != nullptr) {
        *exception = UiOwnerControlActionException{};
    }

    __try {
        action_method(reinterpret_cast<void*>(owner_address));
        return true;
    } __except (CaptureUiOwnerControlActionException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryCallUiOwnerPointClickAction(
    UiOwnerPointClickActionFn action_method,
    uintptr_t owner_address,
    std::int32_t x,
    std::int32_t y,
    UiOwnerControlActionException* exception) {
    if (action_method == nullptr || owner_address == 0) {
        return false;
    }

    if (exception != nullptr) {
        *exception = UiOwnerControlActionException{};
    }

    __try {
        action_method(reinterpret_cast<void*>(owner_address), x, y);
        return true;
    } __except (CaptureUiOwnerControlActionException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryResolveOwnerControlActionMethod(
    const void* object,
    uintptr_t expected_vftable_address,
    uintptr_t expected_handler_address,
    UiOwnerControlActionFn* action_method,
    std::string* error_message) {
    if (object == nullptr || action_method == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Control activation requires a live owner object and a destination method.";
        }
        return false;
    }

    uintptr_t object_vftable = 0;
    if (!TryReadPointerFieldDirect(object, 0, &object_vftable) || object_vftable == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the owner object vftable for UI control activation.";
        }
        return false;
    }

    if (expected_vftable_address != 0) {
        const auto resolved_vftable = ProcessMemory::Instance().ResolveGameAddressOrZero(expected_vftable_address);
        if (resolved_vftable == 0 || object_vftable != resolved_vftable) {
            if (error_message != nullptr) {
                *error_message = "Owner object no longer matches the expected UI class vftable.";
            }
            return false;
        }
    }

    if (expected_handler_address != 0) {
        const auto resolved_handler = ProcessMemory::Instance().ResolveGameAddressOrZero(expected_handler_address);
        if (resolved_handler == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve the configured UI control action handler.";
            }
            return false;
        }

        *action_method = reinterpret_cast<UiOwnerControlActionFn>(resolved_handler);
        return true;
    }

    uintptr_t method_address = 0;
    if (!TryReadPointerValueDirect(
            object_vftable + kUiOwnerControlActionVtableSlotIndex * sizeof(uintptr_t),
            &method_address) ||
        method_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the UI control action dispatch method from the owner vftable.";
        }
        return false;
    }

    *action_method = reinterpret_cast<UiOwnerControlActionFn>(method_address);
    return true;
}
