struct GameplayPlayerProgressionSlotOwnerSnapshot {
    uintptr_t gameplay_address = 0;
    uintptr_t player_actor = 0;
    uintptr_t slot_wrapper_entry = 0;
    uintptr_t slot_wrapper = 0;
    uintptr_t slot_inner = 0;
    uintptr_t player_wrapper = 0;
    uintptr_t player_inner = 0;
};

struct GameplayPlayerActorSlotOwnerSnapshot {
    uintptr_t gameplay_address = 0;
    uintptr_t player_actor_entry = 0;
    uintptr_t player_actor = 0;
};

thread_local int g_bot_progression_slot_context_depth = 0;

bool EnsureActorProgressionRuntimeFieldFromHandle(
    uintptr_t actor_address,
    std::string_view reason) {
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_handle = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorProgressionHandleOffset,
            &progression_handle) ||
        progression_handle == 0) {
        return false;
    }

    const auto progression_runtime = ReadSmartPointerInnerObject(progression_handle);
    if (progression_runtime == 0) {
        return false;
    }

    uintptr_t current_runtime = 0;
    if (memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &current_runtime) &&
        current_runtime == progression_runtime) {
        return true;
    }

    const bool wrote =
        memory.TryWriteField<uintptr_t>(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            progression_runtime);
    static std::uint64_t s_last_actor_progression_runtime_repair_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!wrote || now_ms - s_last_actor_progression_runtime_repair_log_ms >= 500) {
        s_last_actor_progression_runtime_repair_log_ms = now_ms;
        uintptr_t repaired_runtime = 0;
        (void)memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &repaired_runtime);
        Log(
            std::string("[bots] actor progression runtime cache ") +
            (wrote ? "updated" : "update_failed") +
            ". reason=" + std::string(reason) +
            " actor=" + HexString(actor_address) +
            " handle=" + HexString(progression_handle) +
            " inner=" + HexString(progression_runtime) +
            " previous_runtime=" + HexString(current_runtime) +
            " repaired_runtime=" + HexString(repaired_runtime));
    }
    return wrote;
}

bool CaptureGameplayPlayerProgressionSlotOwner(
    uintptr_t gameplay_address,
    GameplayPlayerProgressionSlotOwnerSnapshot* snapshot) {
    if (snapshot == nullptr || gameplay_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    GameplayPlayerProgressionSlotOwnerSnapshot captured{};
    captured.gameplay_address = gameplay_address;
    captured.slot_wrapper_entry = gameplay_address + kGameplayPlayerProgressionHandleOffset;
    if (!memory.TryReadField(
            gameplay_address,
            kGameplayPlayerActorOffset,
            &captured.player_actor) ||
        captured.player_actor == 0) {
        return false;
    }
    if (!memory.TryReadField(
            captured.player_actor,
            kActorProgressionHandleOffset,
            &captured.player_wrapper) ||
        captured.player_wrapper == 0) {
        return false;
    }
    captured.player_inner = ReadSmartPointerInnerObject(captured.player_wrapper);
    if (captured.player_inner == 0) {
        return false;
    }
    if (!memory.TryReadValue(captured.slot_wrapper_entry, &captured.slot_wrapper)) {
        return false;
    }
    captured.slot_inner = ReadSmartPointerInnerObject(captured.slot_wrapper);

    *snapshot = captured;
    return true;
}

bool CaptureGameplayPlayerActorSlotOwner(
    uintptr_t gameplay_address,
    GameplayPlayerActorSlotOwnerSnapshot* snapshot) {
    if (snapshot == nullptr || gameplay_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    GameplayPlayerActorSlotOwnerSnapshot captured{};
    captured.gameplay_address = gameplay_address;
    captured.player_actor_entry = gameplay_address + kGameplayPlayerActorOffset;
    if (!memory.TryReadValue(captured.player_actor_entry, &captured.player_actor) ||
        captured.player_actor == 0) {
        return false;
    }

    *snapshot = captured;
    return true;
}

bool RepairGameplayPlayerProgressionSlotOwner(
    std::string_view reason,
    uintptr_t actor_address = 0) {
    if (g_bot_progression_slot_context_depth > 0) {
        return true;
    }

    uintptr_t gameplay_address = 0;
    if (!TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, &gameplay_address) ||
        gameplay_address == 0) {
        return false;
    }

    GameplayPlayerProgressionSlotOwnerSnapshot owner{};
    if (!CaptureGameplayPlayerProgressionSlotOwner(gameplay_address, &owner)) {
        return false;
    }
    if (owner.slot_wrapper == owner.player_wrapper) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const bool write_ok =
        memory.TryWriteValue<uintptr_t>(owner.slot_wrapper_entry, owner.player_wrapper);
    uintptr_t repaired_wrapper = 0;
    const bool read_ok =
        memory.TryReadValue(owner.slot_wrapper_entry, &repaired_wrapper);
    const bool repaired =
        write_ok && read_ok && repaired_wrapper == owner.player_wrapper;
    Log(
        std::string("[bots] gameplay player progression slot owner repair ") +
        (repaired ? "succeeded" : "failed") +
        ". reason=" + std::string(reason) +
        " actor=" + HexString(actor_address) +
        " gameplay=" + HexString(owner.gameplay_address) +
        " player_actor=" + HexString(owner.player_actor) +
        " slot_wrapper_entry=" + HexString(owner.slot_wrapper_entry) +
        " previous_wrapper=" + HexString(owner.slot_wrapper) +
        " previous_inner=" + HexString(owner.slot_inner) +
        " player_wrapper=" + HexString(owner.player_wrapper) +
        " player_inner=" + HexString(owner.player_inner) +
        " repaired_wrapper=" + HexString(repaired_wrapper));
    return repaired;
}

struct ScopedStandaloneBotProgressionSlotContext {
    uintptr_t actor_address = 0;
    bool requested = false;
    bool require_standalone_slot = true;
    bool active = false;
    bool depth_entered = false;
    bool restore_attempted = false;
    bool restored = true;
    std::string status = "not_requested";
    std::uint8_t actor_slot = 0xFF;
    uintptr_t gameplay_address = 0;
    uintptr_t slot_wrapper_entry = 0;
    uintptr_t original_wrapper = 0;
    uintptr_t original_inner = 0;
    uintptr_t player_actor = 0;
    uintptr_t player_wrapper = 0;
    uintptr_t player_inner = 0;
    uintptr_t bot_wrapper = 0;
    uintptr_t bot_inner = 0;

    ScopedStandaloneBotProgressionSlotContext(
        uintptr_t actor_address_in,
        bool standalone_actor,
        bool require_standalone_slot_in = true)
        : actor_address(actor_address_in),
          requested(standalone_actor),
          require_standalone_slot(require_standalone_slot_in) {
        if (!requested) {
            return;
        }
        Apply();
    }

    ScopedStandaloneBotProgressionSlotContext(const ScopedStandaloneBotProgressionSlotContext&) = delete;
    ScopedStandaloneBotProgressionSlotContext& operator=(
        const ScopedStandaloneBotProgressionSlotContext&) = delete;

    ~ScopedStandaloneBotProgressionSlotContext() {
        Restore();
    }

    void Apply() {
        auto& memory = ProcessMemory::Instance();
        if (actor_address == 0) {
            status = "no_actor";
            return;
        }
        if (!memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot)) {
            status = "slot_unreadable";
            return;
        }
        if (require_standalone_slot && actor_slot != 0) {
            status = "nonzero_actor_slot";
            return;
        }
        if (!TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, &gameplay_address) ||
            gameplay_address == 0) {
            status = "gameplay_unreadable";
            return;
        }
        if (!memory.TryReadField(actor_address, kActorProgressionHandleOffset, &bot_wrapper)) {
            status = "bot_progression_wrapper_unreadable";
            return;
        }
        if (bot_wrapper == 0) {
            status = "bot_progression_wrapper_null";
            return;
        }
        bot_inner = ReadSmartPointerInnerObject(bot_wrapper);
        if (bot_inner == 0) {
            status = "bot_progression_inner_null";
            return;
        }

        GameplayPlayerProgressionSlotOwnerSnapshot player_owner{};
        if (!CaptureGameplayPlayerProgressionSlotOwner(gameplay_address, &player_owner)) {
            status = "player_slot_owner_unreadable";
            return;
        }
        player_actor = player_owner.player_actor;
        player_wrapper = player_owner.player_wrapper;
        player_inner = player_owner.player_inner;
        slot_wrapper_entry = player_owner.slot_wrapper_entry;
        original_wrapper = player_owner.slot_wrapper;
        original_inner = player_owner.slot_inner;
        if (actor_address == player_actor) {
            status = "local_player_actor";
            return;
        }
        if (original_wrapper == bot_wrapper) {
            if (g_bot_progression_slot_context_depth > 0) {
                status = "nested_bot_owned";
                return;
            }
            original_wrapper = player_wrapper;
            original_inner = player_inner;
            active = true;
            depth_entered = true;
            ++g_bot_progression_slot_context_depth;
            restored = false;
            status = "active_preowned_by_bot";
            return;
        }
        if (!memory.TryWriteValue<uintptr_t>(slot_wrapper_entry, bot_wrapper)) {
            status = "slot_wrapper_write_failed";
            return;
        }

        active = true;
        depth_entered = true;
        ++g_bot_progression_slot_context_depth;
        restored = false;
        status = "active";
    }

    void Restore() {
        if (!active || restore_attempted) {
            return;
        }
        restore_attempted = true;
        active = false;
        auto& memory = ProcessMemory::Instance();
        restored = memory.TryWriteValue<uintptr_t>(slot_wrapper_entry, original_wrapper);
        if (depth_entered && g_bot_progression_slot_context_depth > 0) {
            --g_bot_progression_slot_context_depth;
            depth_entered = false;
        }
        status = restored ? "restored" : "restore_failed";
        if (!restored) {
            Log(
                "[bots] standalone slot owner context restore failed. actor=" +
                HexString(actor_address) +
                " slot=" + HexString(actor_slot) +
                " slot_wrapper_entry=" + HexString(slot_wrapper_entry) +
                " original_wrapper=" + HexString(original_wrapper) +
                " bot_wrapper=" + HexString(bot_wrapper));
        }
        if (g_bot_progression_slot_context_depth == 0) {
            (void)RepairGameplayPlayerProgressionSlotOwner(
                "standalone_slot_context_restore",
                actor_address);
        }
    }

    std::string Describe() const {
        return
            "requested=" + std::to_string(requested ? 1 : 0) +
            " require_standalone_slot=" + std::to_string(require_standalone_slot ? 1 : 0) +
            " status=" + status +
            " slot=" + HexString(actor_slot) +
            " gameplay=" + HexString(gameplay_address) +
            " slot_wrapper_entry=" + HexString(slot_wrapper_entry) +
            " original_wrapper=" + HexString(original_wrapper) +
            " original_inner=" + HexString(original_inner) +
            " player_actor=" + HexString(player_actor) +
            " player_wrapper=" + HexString(player_wrapper) +
            " player_inner=" + HexString(player_inner) +
            " bot_wrapper=" + HexString(bot_wrapper) +
            " bot_inner=" + HexString(bot_inner) +
            " depth=" + std::to_string(g_bot_progression_slot_context_depth) +
            " restore_attempted=" + std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
void InvokeWithStandaloneBotProgressionSlotContext(
    uintptr_t actor_address,
    bool standalone_actor,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedStandaloneBotProgressionSlotContext slot_context(actor_address, standalone_actor);
    invoke();
    slot_context.Restore();
    if (context_description != nullptr) {
        *context_description = slot_context.Describe();
    }
}

struct ScopedGameplayPlayerActorSlotContext {
    uintptr_t actor_address = 0;
    bool requested = false;
    bool ready = false;
    bool active = false;
    bool restore_attempted = false;
    bool restored = true;
    std::string status = "not_requested";
    uintptr_t gameplay_address = 0;
    uintptr_t player_actor_entry = 0;
    uintptr_t original_player_actor = 0;

    ScopedGameplayPlayerActorSlotContext(uintptr_t actor_address_in, bool requested_in)
        : actor_address(actor_address_in), requested(requested_in) {
        if (!requested) {
            ready = true;
            return;
        }
        Apply();
    }

    ScopedGameplayPlayerActorSlotContext(const ScopedGameplayPlayerActorSlotContext&) = delete;
    ScopedGameplayPlayerActorSlotContext& operator=(
        const ScopedGameplayPlayerActorSlotContext&) = delete;

    ~ScopedGameplayPlayerActorSlotContext() {
        Restore();
    }

    void Apply() {
        if (actor_address == 0) {
            status = "no_actor";
            return;
        }

        GameplayPlayerActorSlotOwnerSnapshot owner{};
        if (!TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, &gameplay_address) ||
            gameplay_address == 0 ||
            !CaptureGameplayPlayerActorSlotOwner(gameplay_address, &owner)) {
            status = "player_actor_slot_unreadable";
            return;
        }

        player_actor_entry = owner.player_actor_entry;
        original_player_actor = owner.player_actor;
        if (original_player_actor == actor_address) {
            ready = true;
            status = "already_owned";
            return;
        }

        if (!ProcessMemory::Instance().TryWriteValue<uintptr_t>(player_actor_entry, actor_address)) {
            status = "player_actor_slot_write_failed";
            return;
        }

        active = true;
        restored = false;
        ready = true;
        status = "active";
    }

    void Restore() {
        if (!active || restore_attempted) {
            return;
        }
        restore_attempted = true;
        active = false;
        restored =
            ProcessMemory::Instance().TryWriteValue<uintptr_t>(
                player_actor_entry,
                original_player_actor);
        status = restored ? "restored" : "restore_failed";
        if (!restored) {
            Log(
                "[bots] gameplay player actor slot context restore failed. actor=" +
                HexString(actor_address) +
                " player_actor_entry=" + HexString(player_actor_entry) +
                " original_player_actor=" + HexString(original_player_actor));
        }
    }

    std::string Describe() const {
        return
            "requested=" + std::to_string(requested ? 1 : 0) +
            " ready=" + std::to_string(ready ? 1 : 0) +
            " status=" + status +
            " gameplay=" + HexString(gameplay_address) +
            " player_actor_entry=" + HexString(player_actor_entry) +
            " original_player_actor=" + HexString(original_player_actor) +
            " restore_attempted=" + std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
void InvokeWithGameplayPlayerActorSlotContext(
    uintptr_t actor_address,
    bool swap_player_actor_slot,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedGameplayPlayerActorSlotContext slot_context(actor_address, swap_player_actor_slot);
    invoke();
    slot_context.Restore();
    if (context_description != nullptr) {
        *context_description = slot_context.Describe();
    }
}

template <typename InvokeFn>
void InvokeWithBotProgressionSlotOwnerContext(
    uintptr_t actor_address,
    bool bot_actor,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedStandaloneBotProgressionSlotContext slot_context(
        actor_address,
        bot_actor,
        false);
    invoke();
    slot_context.Restore();
    if (context_description != nullptr) {
        *context_description = slot_context.Describe();
    }
}
