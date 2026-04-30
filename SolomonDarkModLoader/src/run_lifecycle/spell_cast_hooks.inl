void DispatchSpellCastForSelf(uintptr_t self_address, int spell_id) {
    if (self_address == 0 || !IsRunActive()) {
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

    const auto x = ReadFloatFieldOrZero(self_address, kActorPositionXOffset);
    const auto y = ReadFloatFieldOrZero(self_address, kActorPositionYOffset);
    const auto direction_x = ReadFloatFieldOrZero(self_address, kSpellDirectionXOffset);
    const auto direction_y = ReadFloatFieldOrZero(self_address, kSpellDirectionYOffset);

    Log(
        "spell.cast hook invoked. spell_id=" + std::to_string(spell_id) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " dir=(" + std::to_string(direction_x) + "," + std::to_string(direction_y) + ")" +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0));
    DispatchLuaSpellCast(spell_id, x, y, direction_x, direction_y);
}

#define SDMOD_DEFINE_SPELL_CAST_HOOK(name, hook_index, spell_id_value)               \
    void __fastcall HookSpellCast_##name(void* self, void* unused_edx) {             \
        const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[hook_index]); \
        if (original == nullptr) {                                                   \
            return;                                                                  \
        }                                                                            \
        const auto self_address = reinterpret_cast<uintptr_t>(self);                 \
        original(self, unused_edx);                                                  \
        DispatchSpellCastForSelf(self_address, spell_id_value);                      \
    }

SDMOD_DEFINE_SPELL_CAST_HOOK(3EB, kHookSpellCast3EB, 0x3EB)
SDMOD_DEFINE_SPELL_CAST_HOOK(018, kHookSpellCast018, 0x18)
SDMOD_DEFINE_SPELL_CAST_HOOK(020, kHookSpellCast020, 0x20)
SDMOD_DEFINE_SPELL_CAST_HOOK(028, kHookSpellCast028, 0x28)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EC, kHookSpellCast3EC, 0x3EC)
SDMOD_DEFINE_SPELL_CAST_HOOK(3ED, kHookSpellCast3ED, 0x3ED)
SDMOD_DEFINE_SPELL_CAST_HOOK(3EE, kHookSpellCast3EE, 0x3EE)
SDMOD_DEFINE_SPELL_CAST_HOOK(3F0, kHookSpellCast3F0, 0x3F0)

void __fastcall HookSpellCast_3EF(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<SpellCastFn>(g_state.hooks[kHookSpellCast3EF]);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    Log("[bots] spell_3ef hook enter. " + DescribeSpellCastHookActorState(self_address));
    original(self, unused_edx);
    Log("[bots] spell_3ef hook exit. " + DescribeSpellCastHookActorState(self_address));
    DispatchSpellCastForSelf(self_address, 0x3EF);
}

#undef SDMOD_DEFINE_SPELL_CAST_HOOK

// ---- Detour functions ----
