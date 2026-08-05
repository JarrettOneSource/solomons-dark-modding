void __fastcall HookRegionSlotDetach(
    void* self,
    void* /*unused_edx*/,
    int slot) {
    const auto transition_id = CurrentTransitionId();
    EventDetails details;
    details.native_argument = slot;
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "region.player_slot.detach.begin",
            reinterpret_cast<std::uintptr_t>(self),
            details);
    }
    const auto original = GetX86HookTrampoline<RegionSlotDetachFn>(
        g_capture.hooks[kHookRegionSlotDetach]);
    if (original != nullptr) {
        original(self, slot);
    }
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "region.player_slot.detach.end",
            reinterpret_cast<std::uintptr_t>(self),
            details);
    }
}

void __fastcall HookRegionSleep(void* self, void* /*unused_edx*/) {
    const auto transition_id = CurrentTransitionId();
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "region.cache.sleep.begin",
            reinterpret_cast<std::uintptr_t>(self));
    }
    const auto original = GetX86HookTrampoline<RegionNoArgFn>(
        g_capture.hooks[kHookRegionSleep]);
    if (original != nullptr) {
        original(self);
    }
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "region.cache.sleep.end",
            reinterpret_cast<std::uintptr_t>(self));
    }
}

void __fastcall HookRegionWake(void* self, void* /*unused_edx*/) {
    const auto transition_id = CurrentTransitionId();
    std::uint8_t initialized = 0;
    (void)ProcessMemory::Instance().TryReadField(
        reinterpret_cast<std::uintptr_t>(self),
        kRegionInitializedOffset,
        &initialized);
    EventDetails details;
    details.native_argument = initialized;
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "region.wake.begin",
            reinterpret_cast<std::uintptr_t>(self),
            details);
    }
    const auto original = GetX86HookTrampoline<RegionNoArgFn>(
        g_capture.hooks[kHookRegionWake]);
    if (original != nullptr) {
        original(self);
    }
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "region.wake.end",
            reinterpret_cast<std::uintptr_t>(self),
            details);
    }
}

void __fastcall HookGameplayAttachRegion(
    void* self,
    void* /*unused_edx*/,
    int target_region) {
    const auto transition_id = CurrentTransitionId();
    EventDetails details;
    details.native_argument = target_region;
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "gameplay.attach.begin",
            reinterpret_cast<std::uintptr_t>(self),
            details);
    }
    const auto original = GetX86HookTrampoline<GameplayAttachRegionFn>(
        g_capture.hooks[kHookGameplayAttachRegion]);
    if (original != nullptr) {
        original(self, target_region);
    }
    if (transition_id != 0) {
        AppendEvent(
            transition_id,
            "gameplay.attach.end",
            reinterpret_cast<std::uintptr_t>(self),
            details);
    }
}

void __cdecl ObserveSwitchAfterOutgoingUnregister() {
    const auto transition_id = CurrentTransitionId();
    if (transition_id == 0) {
        return;
    }
    CaptureSnapshot snapshot;
    (void)ReadCaptureSnapshot(&snapshot);
    if (snapshot.current_region < 0) {
        return;
    }
    AppendEvent(
        transition_id,
        "region.lifecycle.unregister",
        snapshot.active_region);
}

DEFINE_MID_FUNCTION_HOOK(
    SwitchAfterOutgoingUnregister,
    g_switch_after_outgoing_unregister_trampoline,
    ObserveSwitchAfterOutgoingUnregister)

void __fastcall HookRegionBaseTick(void* self, void* /*unused_edx*/) {
    const auto region = reinterpret_cast<std::uintptr_t>(self);
    float alpha_before = 0.0f;
    float rate_before = 0.0f;
    auto& memory = ProcessMemory::Instance();
    const bool readable_before =
        memory.TryReadField(
            region,
            kRegionFadeAlphaOffset,
            &alpha_before) &&
        memory.TryReadField(
            region,
            kRegionFadeRateOffset,
            &rate_before) &&
        std::isfinite(alpha_before) &&
        std::isfinite(rate_before);
    if (readable_before && rate_before != 0.0f &&
        g_thread_active_fades.insert(region).second) {
        EventDetails details;
        details.has_fade_values = true;
        details.alpha_before = alpha_before;
        details.alpha_after = alpha_before;
        details.rate_before = rate_before;
        details.rate_after = rate_before;
        AppendEvent(
            0,
            rate_before > 0.0f
                ? "presentation.fade_out.begin"
                : "presentation.fade_in.begin",
            region,
            details);
    }

    const auto original = GetX86HookTrampoline<RegionNoArgFn>(
        g_capture.hooks[kHookRegionBaseTick]);
    if (original != nullptr) {
        original(self);
    }

    float alpha_after = alpha_before;
    float rate_after = rate_before;
    const bool readable_after =
        memory.TryReadField(
            region,
            kRegionFadeAlphaOffset,
            &alpha_after) &&
        memory.TryReadField(
            region,
            kRegionFadeRateOffset,
            &rate_after) &&
        std::isfinite(alpha_after) &&
        std::isfinite(rate_after);
    if (readable_before && readable_after && rate_before != 0.0f &&
        rate_after == 0.0f) {
        g_thread_active_fades.erase(region);
        EventDetails details;
        details.has_fade_values = true;
        details.alpha_before = alpha_before;
        details.alpha_after = alpha_after;
        details.rate_before = rate_before;
        details.rate_after = rate_after;
        AppendEvent(
            0,
            rate_before > 0.0f
                ? "presentation.fade_out.endpoint"
                : "presentation.fade_in.endpoint",
            region,
            details);
    }
}

void __fastcall HookArenaStartWaves(void* self, void* /*unused_edx*/) {
    AppendEvent(
        0,
        "run.wave.start.begin",
        reinterpret_cast<std::uintptr_t>(self));
    const auto original = GetX86HookTrampoline<RegionNoArgFn>(
        g_capture.hooks[kHookArenaStartWaves]);
    if (original != nullptr) {
        original(self);
    }
    AppendEvent(
        0,
        "run.wave.start.end",
        reinterpret_cast<std::uintptr_t>(self));
}

bool InstallCaptureHooks(std::string* error_message) {
    struct HookDefinition {
        const char* key;
        void* detour;
        HookIndex index;
    };
    const std::array<HookDefinition, kHookCount> definitions = {{
        {"region_slot_detach", reinterpret_cast<void*>(&HookRegionSlotDetach), kHookRegionSlotDetach},
        {"region_sleep", reinterpret_cast<void*>(&HookRegionSleep), kHookRegionSleep},
        {"region_wake", reinterpret_cast<void*>(&HookRegionWake), kHookRegionWake},
        {"gameplay_attach_region", reinterpret_cast<void*>(&HookGameplayAttachRegion), kHookGameplayAttachRegion},
        {
            "switch_after_outgoing_unregister",
            reinterpret_cast<void*>(&MidFunctionDetour_SwitchAfterOutgoingUnregister),
            kHookSwitchAfterOutgoingUnregister,
        },
        {"region_base_tick", reinterpret_cast<void*>(&HookRegionBaseTick), kHookRegionBaseTick},
        {"arena_start_waves", reinterpret_cast<void*>(&HookArenaStartWaves), kHookArenaStartWaves},
    }};
    for (const auto& definition : definitions) {
        std::uintptr_t target = 0;
        if (!ResolveLayoutAddress(
                definition.key,
                &target,
                error_message) ||
            !ProcessMemory::Instance().IsExecutableRange(target, 1)) {
            if (error_message != nullptr && error_message->empty()) {
                *error_message = std::string(
                    "session-flow recorder target is not executable: ") +
                    definition.key;
            }
            RemoveCaptureHooks();
            return false;
        }
        std::string hook_error;
        if (!InstallSafeX86Hook(
                reinterpret_cast<void*>(target),
                definition.detour,
                5,
                &g_capture.hooks[definition.index],
                &hook_error)) {
            RemoveCaptureHooks();
            if (error_message != nullptr) {
                *error_message = std::string(
                    "session-flow recorder could not install ") +
                    definition.key + " hook: " + hook_error;
            }
            return false;
        }
        if (definition.index == kHookSwitchAfterOutgoingUnregister) {
            g_switch_after_outgoing_unregister_trampoline =
                g_capture.hooks[definition.index].trampoline;
        }
    }
    return true;
}
