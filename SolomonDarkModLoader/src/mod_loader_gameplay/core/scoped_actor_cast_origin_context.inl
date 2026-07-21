struct ScopedActorCastOriginContext {
    uintptr_t actor_address = 0;
    float authored_x = 0.0f;
    float authored_y = 0.0f;
    float original_x = 0.0f;
    float original_y = 0.0f;
    bool ready = false;
    bool active = false;
    bool restore_attempted = false;
    bool restored = true;
    std::string status = "not_applied";

    ScopedActorCastOriginContext(
        uintptr_t actor_address_in,
        float authored_x_in,
        float authored_y_in)
        : actor_address(actor_address_in),
          authored_x(authored_x_in),
          authored_y(authored_y_in) {
        Apply();
    }

    ScopedActorCastOriginContext(const ScopedActorCastOriginContext&) = delete;
    ScopedActorCastOriginContext& operator=(
        const ScopedActorCastOriginContext&) = delete;

    ~ScopedActorCastOriginContext() {
        Restore();
    }

    void Apply() {
        if (actor_address == 0 ||
            !std::isfinite(authored_x) ||
            !std::isfinite(authored_y)) {
            status = "invalid_request";
            return;
        }

        auto& memory = ProcessMemory::Instance();
        if (!memory.TryReadField(
                actor_address,
                kActorPositionXOffset,
                &original_x) ||
            !memory.TryReadField(
                actor_address,
                kActorPositionYOffset,
                &original_y) ||
            !std::isfinite(original_x) ||
            !std::isfinite(original_y)) {
            status = "original_unreadable";
            return;
        }
        if (original_x == authored_x && original_y == authored_y) {
            ready = true;
            status = "already_authored";
            return;
        }

        active = true;
        restored = false;
        if (!memory.TryWriteField(
                actor_address,
                kActorPositionXOffset,
                authored_x) ||
            !memory.TryWriteField(
                actor_address,
                kActorPositionYOffset,
                authored_y)) {
            status = "origin_write_failed";
            RestoreAfterApplyFailure();
            return;
        }

        float applied_x = 0.0f;
        float applied_y = 0.0f;
        if (!memory.TryReadField(
                actor_address,
                kActorPositionXOffset,
                &applied_x) ||
            !memory.TryReadField(
                actor_address,
                kActorPositionYOffset,
                &applied_y) ||
            applied_x != authored_x ||
            applied_y != authored_y) {
            status = "origin_verify_failed";
            RestoreAfterApplyFailure();
            return;
        }

        // The stock secondary dispatcher reads actor+0x18/0x1C synchronously.
        // Do not move the actor between spatial cells for this temporary read.
        ready = true;
        status = "active";
    }

    void RestoreAfterApplyFailure() {
        const auto apply_failure = status;
        Restore();
        if (restored) {
            status = apply_failure + "_restored";
        }
    }

    void Restore() {
        if (!active || restore_attempted) {
            return;
        }
        restore_attempted = true;
        active = false;

        auto& memory = ProcessMemory::Instance();
        float restored_x = 0.0f;
        float restored_y = 0.0f;
        restored =
            memory.TryWriteField(
                actor_address,
                kActorPositionXOffset,
                original_x) &&
            memory.TryWriteField(
                actor_address,
                kActorPositionYOffset,
                original_y) &&
            memory.TryReadField(
                actor_address,
                kActorPositionXOffset,
                &restored_x) &&
            memory.TryReadField(
                actor_address,
                kActorPositionYOffset,
                &restored_y) &&
            restored_x == original_x &&
            restored_y == original_y;
        if (restored && ready) {
            status = "restored";
        }
        if (!restored) {
            status = "restore_failed";
            Log(
                "[gameplay] actor cast-origin restore failed. actor=" +
                HexString(actor_address) +
                " original=(" + std::to_string(original_x) + "," +
                std::to_string(original_y) + ")" +
                " restored=(" + std::to_string(restored_x) + "," +
                std::to_string(restored_y) + ")");
        }
    }

    std::string Describe() const {
        return
            "ready=" + std::to_string(ready ? 1 : 0) +
            " status=" + status +
            " authored=(" + std::to_string(authored_x) + "," +
                std::to_string(authored_y) + ")" +
            " original=(" + std::to_string(original_x) + "," +
                std::to_string(original_y) + ")" +
            " restore_attempted=" +
                std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
bool InvokeWithActorCastOriginContext(
    uintptr_t actor_address,
    float authored_x,
    float authored_y,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedActorCastOriginContext cast_origin_context(
        actor_address,
        authored_x,
        authored_y);
    if (cast_origin_context.ready) {
        invoke();
    }
    cast_origin_context.Restore();
    if (context_description != nullptr) {
        *context_description = cast_origin_context.Describe();
    }
    return cast_origin_context.ready && cast_origin_context.restored;
}
