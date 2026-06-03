void __fastcall HookActorAnimationAdvance(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);

    struct AnimationAdvanceContextScope {
        int previous_depth = 0;
        uintptr_t previous_actor = 0;
        uintptr_t previous_caller = 0;
        int previous_participant_depth = 0;
        uintptr_t previous_participant_actor = 0;
        uintptr_t previous_participant_caller = 0;

        AnimationAdvanceContextScope(uintptr_t actor, uintptr_t caller)
            : previous_depth(g_player_actor_vslot1c_depth),
              previous_actor(g_player_actor_vslot1c_actor),
              previous_caller(g_player_actor_vslot1c_caller),
              previous_participant_depth(g_gameplay_hud_participant_actor_depth),
              previous_participant_actor(g_gameplay_hud_participant_actor),
              previous_participant_caller(g_gameplay_hud_participant_actor_caller) {
            ++g_player_actor_vslot1c_depth;
            g_player_actor_vslot1c_actor = actor;
            g_player_actor_vslot1c_caller = caller;

            ++g_gameplay_hud_participant_actor_depth;
            g_gameplay_hud_participant_actor = actor;
            g_gameplay_hud_participant_actor_caller = caller;
        }

        ~AnimationAdvanceContextScope() {
            g_gameplay_hud_participant_actor_depth = previous_participant_depth;
            g_gameplay_hud_participant_actor = previous_participant_actor;
            g_gameplay_hud_participant_actor_caller = previous_participant_caller;
            g_player_actor_vslot1c_depth = previous_depth;
            g_player_actor_vslot1c_actor = previous_actor;
            g_player_actor_vslot1c_caller = previous_caller;
        }
    } context_scope(actor_address, reinterpret_cast<uintptr_t>(_ReturnAddress()));

    original(self);
}
