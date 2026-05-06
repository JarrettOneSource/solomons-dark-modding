// The game's scene dispatcher only ticks the player's Skills_Wizard (via a
// global slot at DAT_0081c264+0x1654 in the shipping binary). Bots allocate
// their own Skills_Wizard instance during WizardCloneFromSourceActor but are
// never reached by that dispatcher, so HP/MP regen never fires for them.
// Drive each bot's own Skills_Wizard::Tick (vtable slot 2) from our per-actor
// tick hook so every entity maintains its own stat pool.
void TickBotOwnedSkillsWizard(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_address = 0;
    if (!memory.TryReadField(actor_address, kActorProgressionRuntimeStateOffset, &progression_address)) {
        return;
    }
    if (progression_address == 0) {
        uintptr_t progression_handle = 0;
        if (!memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle)) {
            return;
        }
        progression_address = ReadSmartPointerInnerObject(progression_handle);
    }
    if (progression_address == 0) {
        return;
    }
    uintptr_t vtable_address = 0;
    if (!memory.TryReadField(progression_address, kObjectVtableOffset, &vtable_address)) {
        return;
    }
    if (vtable_address == 0) {
        return;
    }
    uintptr_t tick_fn_address = 0;
    if (!memory.TryReadField(vtable_address, kSkillsWizardTickVfuncOffset, &tick_fn_address)) {
        return;
    }
    if (tick_fn_address == 0) {
        return;
    }
    using SkillsWizardTickFn = void(__thiscall*)(void*);
    auto* tick_fn = reinterpret_cast<SkillsWizardTickFn>(tick_fn_address);
    __try {
        tick_fn(reinterpret_cast<void*>(progression_address));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}
