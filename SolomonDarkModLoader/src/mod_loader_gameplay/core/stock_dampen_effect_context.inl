constexpr std::array<std::uint8_t, 10> kStockDampenEffectBlockBytes = {
    0x53, 0x83, 0xEC, 0x08, 0x8D,
    0x46, 0x18, 0x8B, 0xCC, 0x89,
};
constexpr std::array<std::uint8_t, 10> kStockDampenEffectBlockSkipBytes = {
    // Preserve the case's native success result, then jump to its shared
    // dispatcher-finalization path without touching the argument stack.
    0xC6, 0x44, 0x24, 0x1F, 0x01,
    0xE9, 0x3B, 0x00, 0x00, 0x00,
};

// The multiplayer-only transaction begins after FUN_0052B150 has accepted
// and spent the native mana.  It skips both FUN_00648DF0 and the following
// type-0x15 presentation object factory.  Two Windows dumps proved that each
// path poisons the shared pointer-list heap and later fails in
// HookPointerListDeleteBatch.  The synchronized Dampen request owns behavior
// and DX9 presentation; the dispatcher still owns admission, mana, success,
// and its normal common finalization.

struct ScopedStockDampenEffectSuppression {
    uintptr_t resolved_address = 0;
    bool ready = false;
    bool active = false;
    bool restore_attempted = false;
    bool restored = false;
    std::string status = "not_applied";

    ScopedStockDampenEffectSuppression() {
        Apply();
    }

    ScopedStockDampenEffectSuppression(
        const ScopedStockDampenEffectSuppression&) = delete;
    ScopedStockDampenEffectSuppression& operator=(
        const ScopedStockDampenEffectSuppression&) = delete;

    ~ScopedStockDampenEffectSuppression() {
        Restore();
    }

    void Apply() {
        auto& memory = ProcessMemory::Instance();
        resolved_address = memory.ResolveGameAddressOrZero(
            kDampenStockEffectBlock);
        if (resolved_address == 0) {
            status = "address_unresolved";
            return;
        }

        std::array<std::uint8_t, 10> current{};
        if (!memory.TryRead(
                resolved_address,
                current.data(),
                current.size())) {
            status = "block_unreadable";
            return;
        }
        if (current != kStockDampenEffectBlockBytes) {
            status = "block_mismatch";
            return;
        }
        if (!memory.TryWrite(
                resolved_address,
                kStockDampenEffectBlockSkipBytes.data(),
                kStockDampenEffectBlockSkipBytes.size())) {
            status = "block_write_failed";
            return;
        }

        active = true;
        std::array<std::uint8_t, 10> applied{};
        if (!memory.TryRead(
                resolved_address,
                applied.data(),
                applied.size()) ||
            applied != kStockDampenEffectBlockSkipBytes) {
            status = "block_verify_failed";
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
        std::array<std::uint8_t, 10> restored_bytes{};
        restored =
            memory.TryWrite(
                resolved_address,
                kStockDampenEffectBlockBytes.data(),
                kStockDampenEffectBlockBytes.size()) &&
            memory.TryRead(
                resolved_address,
                restored_bytes.data(),
                restored_bytes.size()) &&
            restored_bytes == kStockDampenEffectBlockBytes;
        status = restored ? "restored" : "restore_failed";
        if (!restored) {
            Log(
                "Stock Dampen effect suppression restore failed. block=" +
                HexString(kDampenStockEffectBlock));
        }
    }

    std::string Describe() const {
        return
            "ready=" + std::to_string(ready ? 1 : 0) +
            " status=" + status +
            " restore_attempted=" +
                std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
bool InvokeWithStockDampenEffectSuppressed(
    std::int32_t skill_entry_index,
    InvokeFn&& invoke) {
    if (skill_entry_index != 0x33) {
        invoke();
        return true;
    }

    ScopedStockDampenEffectSuppression context;
    if (context.ready) {
        invoke();
    }
    context.Restore();
    const bool succeeded = context.ready && context.restored;
    Log(
        "Multiplayer stock Dampen effect block suppressed; native "
        "dispatcher completed. success=" +
        std::to_string(succeeded ? 1 : 0) +
        " context={" + context.Describe() + "}");
    return succeeded;
}
