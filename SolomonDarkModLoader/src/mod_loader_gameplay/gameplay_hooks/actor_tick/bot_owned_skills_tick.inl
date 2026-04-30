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
    uintptr_t progression_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (progression_address == 0) {
        progression_address = ReadSmartPointerInnerObject(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
    }
    if (progression_address == 0) {
        return;
    }
    const auto vtable_address =
        memory.ReadFieldOr<uintptr_t>(progression_address, 0, 0);
    if (vtable_address == 0) {
        return;
    }
    const auto tick_fn_address =
        memory.ReadFieldOr<uintptr_t>(vtable_address, 0x8, 0);
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
