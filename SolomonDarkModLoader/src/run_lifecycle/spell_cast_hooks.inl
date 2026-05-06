void DispatchSpellCastForSelf(uintptr_t self_address, int spell_id) {
    if (self_address == 0 || spell_id <= 0 || !IsRunActive()) {
        return;
    }

    const auto click_serial = GetGameplayMouseLeftEdgeSerial();
    const auto click_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    const auto now = static_cast<std::uint64_t>(GetTickCount64());
    if (click_serial == 0 ||
        click_tick_ms == 0 ||
        now < click_tick_ms ||
        now - click_tick_ms > kSpellCastClickWindowMs) {
        return;
    }

    const auto last_consumed_click_serial =
        g_state.last_consumed_spell_click_serial.load(std::memory_order_acquire);
    if (last_consumed_click_serial == click_serial) {
        return;
    }
    g_state.last_consumed_spell_click_serial.store(click_serial, std::memory_order_release);

    float x = 0.0f;
    float y = 0.0f;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    if (!TryReadActorPosition(self_address, &x, &y) ||
        !TryReadFloatField(self_address, kSpellDirectionXOffset, &direction_x) ||
        !TryReadFloatField(self_address, kSpellDirectionYOffset, &direction_y)) {
        Log(
            "spell.cast native event fields unavailable. spell_id=" + std::to_string(spell_id) +
            " actor=" + HexString(self_address));
        return;
    }

    Log(
        "spell.cast hook invoked. spell_id=" + std::to_string(spell_id) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0));
    DispatchLuaSpellCast(spell_id, x, y, direction_x, direction_y);
}

bool TryReadSpellCastHookSkillId(uintptr_t self_address, int* spell_id) {
    if (spell_id == nullptr) {
        return false;
    }

    *spell_id = 0;
    if (self_address == 0 || kActorPrimarySkillIdOffset == 0) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(self_address + kActorPrimarySkillIdOffset, sizeof(std::int32_t))) {
        return false;
    }
    return memory.TryReadField(self_address, kActorPrimarySkillIdOffset, spell_id);
}

#define SDMOD_DEFINE_SPELL_CAST_HOOK(name, hook_index)                              \
    void __fastcall HookSpellCast_##name(void* self, void* unused_edx) {             \
        const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[hook_index]); \
        if (original == nullptr) {                                                   \
            return;                                                                  \
        }                                                                            \
        const auto self_address = reinterpret_cast<uintptr_t>(self);                 \
        int spell_id = 0;                                                           \
        const bool have_spell_id = TryReadSpellCastHookSkillId(self_address, &spell_id); \
        original(self, unused_edx);                                                  \
        if (have_spell_id) {                                                         \
            DispatchSpellCastForSelf(self_address, spell_id);                        \
        } else {                                                                     \
            Log("spell.cast native skill id unavailable. actor=" + HexString(self_address)); \
        }                                                                            \
    }

SDMOD_DEFINE_SPELL_CAST_HOOK(3EB, kHookSpellCast3EB)
SDMOD_DEFINE_SPELL_CAST_HOOK(018, kHookSpellCast018)
SDMOD_DEFINE_SPELL_CAST_HOOK(020, kHookSpellCast020)
SDMOD_DEFINE_SPELL_CAST_HOOK(028, kHookSpellCast028)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EC, kHookSpellCast3EC)
SDMOD_DEFINE_SPELL_CAST_HOOK(3ED, kHookSpellCast3ED)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EE, kHookSpellCast3EE)
SDMOD_DEFINE_SPELL_CAST_HOOK(3F0, kHookSpellCast3F0)

void __fastcall HookSpellCast_3EF(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[kHookSpellCast3EF]);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    int spell_id = 0;
    const bool have_spell_id = TryReadSpellCastHookSkillId(self_address, &spell_id);
    Log("[bots] spell_3ef hook enter. " + DescribeSpellCastHookActorState(self_address));
    original(self, unused_edx);
    Log("[bots] spell_3ef hook exit. " + DescribeSpellCastHookActorState(self_address));
    if (have_spell_id) {
        DispatchSpellCastForSelf(self_address, spell_id);
    } else {
        Log("spell.cast native skill id unavailable. actor=" + HexString(self_address));
    }
}

#undef SDMOD_DEFINE_SPELL_CAST_HOOK

// ---- Detour functions ----
