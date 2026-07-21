struct ScopedActorSlotZeroContext {
    uintptr_t actor_address = 0;
    bool requested = false;
    bool ready = false;
    bool active = false;
    bool restore_attempted = false;
    bool restored = true;
    std::string status = "not_requested";
    std::int8_t original_slot = -1;

    ScopedActorSlotZeroContext(
        uintptr_t actor_address_in,
        bool requested_in)
        : actor_address(actor_address_in), requested(requested_in) {
        if (!requested) {
            ready = true;
            return;
        }
        Apply();
    }

    ScopedActorSlotZeroContext(const ScopedActorSlotZeroContext&) = delete;
    ScopedActorSlotZeroContext& operator=(
        const ScopedActorSlotZeroContext&) = delete;

    ~ScopedActorSlotZeroContext() {
        Restore();
    }

    void Apply() {
        auto& memory = ProcessMemory::Instance();
        if (actor_address == 0) {
            status = "no_actor";
            return;
        }
        if (!memory.TryReadField(
                actor_address,
                kActorSlotOffset,
                &original_slot)) {
            status = "slot_unreadable";
            return;
        }
        if (original_slot == 0) {
            ready = true;
            status = "already_zero";
            return;
        }
        if (!memory.TryWriteField<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                0)) {
            status = "slot_write_failed";
            return;
        }

        active = true;
        restored = false;
        std::int8_t applied_slot = -1;
        if (!memory.TryReadField(
                actor_address,
                kActorSlotOffset,
                &applied_slot) ||
            applied_slot != 0) {
            status = "slot_verify_failed";
            return;
        }
        ready = true;
        status = "active";
    }

    void Restore() {
        if (!active || restore_attempted) {
            return;
        }
        restore_attempted = true;
        active = false;
        auto& memory = ProcessMemory::Instance();
        std::int8_t restored_slot = -1;
        restored =
            memory.TryWriteField<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                original_slot) &&
            memory.TryReadField(
                actor_address,
                kActorSlotOffset,
                &restored_slot) &&
            restored_slot == original_slot;
        status = restored ? "restored" : "restore_failed";
        if (!restored) {
            Log(
                "[gameplay] actor slot context restore failed. actor=" +
                HexString(actor_address) +
                " original_slot=" +
                std::to_string(static_cast<int>(original_slot)) +
                " restored_slot=" +
                std::to_string(static_cast<int>(restored_slot)));
        }
    }

    std::string Describe() const {
        return
            "requested=" + std::to_string(requested ? 1 : 0) +
            " ready=" + std::to_string(ready ? 1 : 0) +
            " status=" + status +
            " original_slot=" +
                std::to_string(static_cast<int>(original_slot)) +
            " restore_attempted=" +
                std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
bool InvokeWithActorSlotZeroContext(
    uintptr_t actor_address,
    bool requested,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedActorSlotZeroContext slot_context(actor_address, requested);
    if (slot_context.ready) {
        invoke();
    }
    slot_context.Restore();
    if (context_description != nullptr) {
        *context_description = slot_context.Describe();
    }
    return slot_context.ready && slot_context.restored;
}
