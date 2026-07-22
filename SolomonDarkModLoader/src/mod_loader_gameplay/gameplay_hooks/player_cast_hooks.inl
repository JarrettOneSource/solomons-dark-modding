bool IsActorCurrentLocalPlayerSlotZero(uintptr_t actor_address);
bool IsManualSpawnerPrimaryCastControlGraceActive();
bool IsManualSpawnerPrimaryTargetActor(uintptr_t actor_address);
bool ApplyManualSpawnerPrimaryTargetState(
    uintptr_t actor_address,
    uintptr_t selection_pointer,
    uintptr_t target_actor_address);

namespace {

constexpr std::size_t kSecondaryCastGameplayBeltArrayOffset = 0x5EC;
constexpr std::size_t kSecondaryCastBeltButtonStride = 0xEC;
constexpr std::size_t kSecondaryCastBeltButtonTypeOffset = 0xB4;
constexpr std::size_t kSecondaryCastBeltButtonSkillEntryOffset = 0xB8;
constexpr std::uint32_t kSecondaryCastBeltSkillTypeId = 0x1B67;

struct LocalSecondaryCastCapture {
    bool valid = false;
    std::int32_t belt_slot = -1;
    std::array<std::int32_t, multiplayer::kSecondaryLoadoutSlotCount>
        secondary_entry_indices = {-1, -1, -1, -1, -1, -1, -1, -1};
    float position_x = 0.0f;
    float position_y = 0.0f;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    uintptr_t target_actor_address = 0;
    bool has_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool has_cursor_world_placement = false;
    float cursor_world_x = 0.0f;
    float cursor_world_y = 0.0f;
};

struct LocalSecondaryCursorProjectionCaptureContext {
    LocalSecondaryCastCapture* capture = nullptr;
    uintptr_t actor_world_address = 0;
};

struct LocalPrimarySpellFilterState {
    uintptr_t actor_address = 0;
    std::int32_t skill_id = 0;
    std::uint64_t mouse_edge_serial = 0;
    std::uint64_t mouse_edge_tick_ms = 0;
    bool allowed = true;
};

LocalPrimarySpellFilterState g_local_primary_spell_filter_state;

bool TryResolveLocalPlayerPrimarySpellFilterSkillId(
    uintptr_t actor_address,
    std::int32_t* skill_id) {
    if (actor_address == 0 || skill_id == nullptr) {
        return false;
    }

    *skill_id = 0;
    if (ProcessMemory::Instance().TryReadField(
            actor_address,
            kActorPrimarySkillIdOffset,
            skill_id) &&
        *skill_id > 0) {
        return true;
    }

    int selection_state = -1;
    if (!TryReadGameplayIndexStateValue(
            static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex),
            &selection_state)) {
        return false;
    }

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(
            actor_address,
            &progression_address)) {
        return false;
    }

    NativePrimarySpellSelection selection{};
    if (!TryResolveNativePrimarySelectionFromLiveProgression(
            progression_address,
            selection_state,
            selection_state,
            &selection) ||
        selection.build_skill_id <= 0) {
        return false;
    }

    *skill_id = selection.build_skill_id;
    return true;
}

bool ApplyLocalPlayerPrimarySpellFilter(
    uintptr_t actor_address,
    std::int32_t skill_id) {
    if (!HasLuaSpellCastFilterHandlers()) {
        return true;
    }

    const auto edge_serial = GetGameplayMouseLeftEdgeSerial();
    const auto edge_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    const auto& previous = g_local_primary_spell_filter_state;
    if (edge_serial != 0 &&
        edge_tick_ms != 0 &&
        previous.actor_address == actor_address &&
        previous.skill_id == skill_id &&
        previous.mouse_edge_serial == edge_serial &&
        previous.mouse_edge_tick_ms == edge_tick_ms) {
        return previous.allowed;
    }

    constexpr std::uint64_t kPrimarySpellFilterEdgeWindowMs = 500;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (edge_serial == 0 ||
        edge_tick_ms == 0 ||
        now_ms < edge_tick_ms ||
        now_ms - edge_tick_ms > kPrimarySpellFilterEdgeWindowMs) {
        return true;
    }

    const auto context = CaptureLuaSpellCastFilterContext(
        actor_address,
        multiplayer::GetLocalTransportParticipantId(),
        LuaSpellCastKind::Primary,
        skill_id);
    const bool allowed = ApplyLuaSpellCastFilters(context);
    g_local_primary_spell_filter_state = {
        actor_address,
        skill_id,
        edge_serial,
        edge_tick_ms,
        allowed,
    };
    if (!allowed) {
        Log(
            "[lua] canceled owner-side local primary spell cast. actor=" +
            HexString(actor_address) +
            " skill_id=" + std::to_string(skill_id) +
            " mouse_edge=" + std::to_string(edge_serial));
    }
    return allowed;
}

thread_local LocalSecondaryCursorProjectionCaptureContext*
    g_local_secondary_cursor_projection_capture = nullptr;

class ScopedLocalSecondaryCursorProjectionCapture {
public:
    ScopedLocalSecondaryCursorProjectionCapture(
        uintptr_t actor_address,
        std::int32_t skill_entry_index,
        LocalSecondaryCastCapture* capture)
        : previous_(g_local_secondary_cursor_projection_capture) {
        g_local_secondary_cursor_projection_capture = nullptr;
        if (actor_address == 0 ||
            capture == nullptr ||
            !capture->valid ||
            !IsSecondaryCursorWorldPlacementSkill(skill_entry_index) ||
            !ProcessMemory::Instance().TryReadField(
                actor_address,
                kActorOwnerOffset,
                &context_.actor_world_address) ||
            context_.actor_world_address == 0) {
            return;
        }
        context_.capture = capture;
        g_local_secondary_cursor_projection_capture = &context_;
    }

    ScopedLocalSecondaryCursorProjectionCapture(
        const ScopedLocalSecondaryCursorProjectionCapture&) = delete;
    ScopedLocalSecondaryCursorProjectionCapture& operator=(
        const ScopedLocalSecondaryCursorProjectionCapture&) = delete;

    ~ScopedLocalSecondaryCursorProjectionCapture() {
        g_local_secondary_cursor_projection_capture = previous_;
    }

private:
    LocalSecondaryCursorProjectionCaptureContext context_{};
    LocalSecondaryCursorProjectionCaptureContext* previous_ = nullptr;
};

void* __fastcall HookSecondaryCursorWorldProjection(
    void* self,
    void* /*unused_edx*/,
    void* output_point,
    float screen_x,
    float screen_y) {
    const auto original =
        GetX86HookTrampoline<SecondaryCursorWorldProjectionFn>(
            g_gameplay_keyboard_injection
                .secondary_cursor_world_projection_hook);
    if (original == nullptr) {
        return nullptr;
    }

    void* result = original(self, output_point, screen_x, screen_y);
    auto* active = g_local_secondary_cursor_projection_capture;
    if (active == nullptr ||
        active->capture == nullptr ||
        active->actor_world_address != reinterpret_cast<uintptr_t>(self) ||
        active->capture->has_cursor_world_placement ||
        result == nullptr) {
        return result;
    }

    const auto* world_point = static_cast<const float*>(result);
    const auto world_x = world_point[0];
    const auto world_y = world_point[1];
    constexpr float kMaximumCursorWorldCoordinate = 100000.0f;
    if (std::isfinite(world_x) &&
        std::isfinite(world_y) &&
        std::abs(world_x) <= kMaximumCursorWorldCoordinate &&
        std::abs(world_y) <= kMaximumCursorWorldCoordinate) {
        active->capture->has_cursor_world_placement = true;
        active->capture->cursor_world_x = world_x;
        active->capture->cursor_world_y = world_y;
    }
    return result;
}

bool IsUsableSecondaryCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y) {
    return IsUsableSpellCastAimTarget(
        position_x,
        position_y,
        aim_target_x,
        aim_target_y);
}

bool TryCaptureLocalSecondaryCastOrigin(
    uintptr_t actor_address,
    LocalSecondaryCastCapture* capture) {
    if (actor_address == 0 || capture == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return
        memory.TryReadField(
            actor_address,
            kActorPositionXOffset,
            &capture->position_x) &&
        memory.TryReadField(
            actor_address,
            kActorPositionYOffset,
            &capture->position_y) &&
        std::isfinite(capture->position_x) &&
        std::isfinite(capture->position_y);
}

bool TryRefreshLocalSecondaryCastAim(
    uintptr_t actor_address,
    LocalSecondaryCastCapture* capture) {
    if (actor_address == 0 ||
        capture == nullptr ||
        !std::isfinite(capture->position_x) ||
        !std::isfinite(capture->position_y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float heading = 0.0f;
    if (!memory.TryReadField(
            actor_address,
            kActorHeadingOffset,
            &heading) ||
        !std::isfinite(heading)) {
        return false;
    }

    const auto radians =
        (NormalizeWizardActorHeadingForWrite(heading) - 90.0f) /
        kWizardHeadingRadiansToDegrees;
    capture->direction_x = static_cast<float>(std::cos(radians));
    capture->direction_y = static_cast<float>(std::sin(radians));
    if (!std::isfinite(capture->direction_x) ||
        !std::isfinite(capture->direction_y)) {
        return false;
    }

    capture->target_actor_address = 0;
    (void)memory.TryReadField(
        actor_address,
        kActorCurrentTargetActorOffset,
        &capture->target_actor_address);
    capture->has_aim_target =
        memory.TryReadField(
            actor_address,
            kActorAimTargetXOffset,
            &capture->aim_target_x) &&
        memory.TryReadField(
            actor_address,
            kActorAimTargetYOffset,
            &capture->aim_target_y) &&
        IsUsableSecondaryCastAimTarget(
            capture->position_x,
            capture->position_y,
            capture->aim_target_x,
            capture->aim_target_y);
    return true;
}

bool TryCaptureLocalSecondaryCast(
    uintptr_t actor_address,
    std::int32_t skill_entry_index,
    LocalSecondaryCastCapture* capture) {
    if (capture == nullptr ||
        actor_address == 0 ||
        skill_entry_index < 0 ||
        skill_entry_index >=
            static_cast<std::int32_t>(multiplayer::kParticipantProgressionBookSnapshotMaxEntries)) {
        return false;
    }
    *capture = LocalSecondaryCastCapture{};

    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    if (!TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, &gameplay_address) ||
        gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address) ||
        local_actor_address != actor_address) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    for (std::size_t slot = 0;
         slot < multiplayer::kSecondaryLoadoutSlotCount;
         ++slot) {
        const auto button_address =
            gameplay_address + kSecondaryCastGameplayBeltArrayOffset +
            slot * kSecondaryCastBeltButtonStride;
        std::uint32_t button_type = 0;
        std::int32_t button_skill_entry = -1;
        if (!memory.TryReadField(
                button_address,
                kSecondaryCastBeltButtonTypeOffset,
                &button_type) ||
            !memory.TryReadField(
                button_address,
                kSecondaryCastBeltButtonSkillEntryOffset,
                &button_skill_entry)) {
            return false;
        }
        if (button_type == kSecondaryCastBeltSkillTypeId) {
            capture->secondary_entry_indices[slot] = button_skill_entry;
        }
        if (button_type == kSecondaryCastBeltSkillTypeId &&
            button_skill_entry == skill_entry_index) {
            capture->belt_slot = static_cast<std::int32_t>(slot);
            break;
        }
    }
    if (capture->belt_slot < 0) {
        return false;
    }

    capture->valid =
        TryCaptureLocalSecondaryCastOrigin(actor_address, capture) &&
        TryRefreshLocalSecondaryCastAim(actor_address, capture);
    return capture->valid;
}

bool IsNativeSecondaryToggleSkill(std::int32_t skill_entry_index) {
    // Firewalker, Mindstar, and Regenerate use false to report the native
    // toggle-off transition even though the requested state change succeeded.
    return skill_entry_index == 0x17 ||
           skill_entry_index == 0x4E ||
           skill_entry_index == 0x4F;
}

}  // namespace

bool InvokeOriginalPlayerActorSecondarySpellCast(
    uintptr_t actor_address,
    int skill_entry_index,
    std::uint8_t* result) {
    if (result != nullptr) {
        *result = 0;
    }
    const auto original =
        GetX86HookTrampoline<PlayerActorSecondarySpellCastFn>(
            g_gameplay_keyboard_injection.player_actor_secondary_spell_cast_hook);
    if (actor_address == 0 || original == nullptr) {
        return false;
    }
    if (skill_entry_index == 0x17 && multiplayer::IsLocalTransportEnabled()) {
        uintptr_t profile_address = 0;
        std::uint8_t active_before = 0;
        auto& memory = ProcessMemory::Instance();
        const bool toggled =
            TryResolveWizardActorProfileAddress(
                actor_address,
                &profile_address) &&
            memory.TryReadField(
                profile_address,
                kWizardProfileFirewalkerActiveOffset,
                &active_before) &&
            memory.TryWriteField<std::uint8_t>(
                profile_address,
                kWizardProfileFirewalkerActiveOffset,
                active_before == 0 ? 1 : 0);
        if (result != nullptr) {
            *result = toggled ? 1 : 0;
        }
        Log(
            "Multiplayer remote Firewalker used owner-authored effect replay. "
            "actor=" + HexString(actor_address) +
            " active_before=" + std::to_string(active_before) +
            " toggled=" + std::to_string(toggled ? 1 : 0));
        return toggled;
    }
    ++g_remote_secondary_spell_dispatch_depth;
    std::uint8_t native_result = 0;
    const bool stock_context_ok =
        InvokeWithStockDampenEffectSuppressed(
            skill_entry_index,
            [&] {
                native_result = original(
                    reinterpret_cast<void*>(actor_address),
                    skill_entry_index);
            });
    --g_remote_secondary_spell_dispatch_depth;
    if (!stock_context_ok) {
        return false;
    }
    if (result != nullptr) {
        *result = native_result;
    }
    return true;
}

std::uint8_t __fastcall HookPlayerActorSecondarySpellCast(
    void* self,
    void* /*unused_edx*/,
    int skill_entry_index) {
    const auto original =
        GetX86HookTrampoline<PlayerActorSecondarySpellCastFn>(
            g_gameplay_keyboard_injection.player_actor_secondary_spell_cast_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    if (g_remote_secondary_spell_dispatch_depth == 0 &&
        IsActorCurrentLocalPlayerSlotZero(actor_address) &&
        HasLuaSpellCastFilterHandlers()) {
        const auto filter_context = CaptureLuaSpellCastFilterContext(
            actor_address,
            multiplayer::GetLocalTransportParticipantId(),
            LuaSpellCastKind::Secondary,
            skill_entry_index);
        if (!ApplyLuaSpellCastFilters(filter_context)) {
            Log(
                "[lua] canceled owner-side local secondary spell cast. actor=" +
                HexString(actor_address) +
                " skill_id=" + std::to_string(skill_entry_index));
            return 0;
        }
    }
    const auto turn_undead_precast_state =
        CaptureAuthoritativeTurnUndeadPrecastState(
            actor_address,
            skill_entry_index);
    LocalSecondaryCastCapture capture{};
    const bool should_capture =
        g_remote_secondary_spell_dispatch_depth == 0 &&
        multiplayer::IsLocalTransportEnabled() &&
        TryCaptureLocalSecondaryCast(
            actor_address,
            skill_entry_index,
            &capture);
    if (skill_entry_index == 0x33 &&
        multiplayer::IsLocalTransportEnabled() &&
        !should_capture) {
        Log(
            "Multiplayer local Dampen rejected because its authoritative "
            "cast context was unavailable. actor=" +
            HexString(actor_address));
        return 0;
    }
    std::uint8_t native_result = 0;
    bool stock_context_ok = true;
    {
        ScopedLocalSecondaryCursorProjectionCapture cursor_projection_capture(
            actor_address,
            skill_entry_index,
            should_capture ? &capture : nullptr);
        if (multiplayer::IsLocalTransportEnabled()) {
            stock_context_ok = InvokeWithStockDampenEffectSuppressed(
                skill_entry_index,
                [&] {
                    native_result = original(self, skill_entry_index);
                });
        } else {
            native_result = original(self, skill_entry_index);
        }
    }
    if (!stock_context_ok) {
        return 0;
    }
    RegisterAuthoritativeTurnUndeadCasterTargets(
        actor_address,
        multiplayer::GetLocalTransportParticipantId(),
        turn_undead_precast_state,
        native_result != 0);
    if (!should_capture) {
        return native_result;
    }
    if (native_result == 0 &&
        !IsNativeSecondaryToggleSkill(skill_entry_index)) {
        Log(
            "Multiplayer local secondary cast rejected by native dispatcher. actor=" +
            HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot));
        return native_result;
    }
    if (!TryRefreshLocalSecondaryCastAim(actor_address, &capture)) {
        Log(
            "Multiplayer local secondary cast accepted without a readable "
            "post-dispatch aim. actor=" + HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot));
        return native_result;
    }

    const auto native_queue_id =
        multiplayer::QueueLocalSecondarySpellCastEvent(
            skill_entry_index,
            capture.belt_slot,
            capture.position_x,
            capture.position_y,
            capture.direction_x,
            capture.direction_y,
            0,
            capture.target_actor_address,
            capture.has_aim_target,
            capture.aim_target_x,
            capture.aim_target_y,
            capture.secondary_entry_indices.data(),
            capture.secondary_entry_indices.size(),
            capture.has_cursor_world_placement,
            capture.cursor_world_x,
            capture.cursor_world_y);
    if (native_queue_id != 0) {
        Log(
            "Multiplayer local secondary cast queued from native dispatcher. actor=" +
            HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot) +
            " native_result=" + std::to_string(native_result) +
            " native_queue_id=" + std::to_string(native_queue_id) +
            " cursor_world_placement=" +
                std::to_string(capture.has_cursor_world_placement ? 1 : 0) +
            " cursor_world=(" + std::to_string(capture.cursor_world_x) + "," +
                std::to_string(capture.cursor_world_y) + ")");
    }
    return native_result;
}

bool IsTrackedWizardParticipantActorForHud(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    const auto* binding = FindParticipantEntityForActor(actor_address);
    return binding != nullptr && IsWizardParticipantKind(binding->kind);
}

bool IsIdleNativeRemoteParticipantActor(uintptr_t actor_address, std::uint64_t* out_bot_id = nullptr) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    const auto* binding = FindParticipantEntityForActor(actor_address);
    if (binding == nullptr ||
        !IsNativeRemoteParticipantBinding(binding) ||
        binding->ongoing_cast.active) {
        return false;
    }
    if (out_bot_id != nullptr) {
        *out_bot_id = binding->bot_id;
    }
    return true;
}

bool HasNativeRemotePerCastProjectileEmission(
    uintptr_t actor_address,
    std::uint64_t* out_bot_id = nullptr) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    const auto* binding = FindParticipantEntityForActor(actor_address);
    if (binding == nullptr ||
        !IsNativeRemoteParticipantBinding(binding) ||
        !binding->ongoing_cast.active ||
        binding->ongoing_cast.lane !=
            ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary ||
        binding->ongoing_cast.mana_charge_kind !=
            multiplayer::BotManaChargeKind::PerCast ||
        (!binding->ongoing_cast.remote_per_cast_projectile_emission_latched &&
         !binding->ongoing_cast.remote_per_cast_projectile_observed)) {
        return false;
    }
    if (out_bot_id != nullptr) {
        *out_bot_id = binding->bot_id;
    }
    return true;
}

void __fastcall HookPurePrimaryAttackDispatch(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<PlayerActorNoArgMethodFn>(
        g_gameplay_keyboard_injection.pure_primary_attack_dispatch_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    if (IsRunLifecycleManualEnemySpawnerTestModeEnabled() &&
        IsActorCurrentLocalPlayerSlotZero(actor_address) &&
        IsManualSpawnerPrimaryCastControlGraceActive()) {
        const auto manual_spawner_target_actor =
            g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.load(
                std::memory_order_acquire);
        if (IsManualSpawnerPrimaryTargetActor(manual_spawner_target_actor)) {
            (void)ApplyManualSpawnerPrimaryTargetState(
                actor_address,
                0,
                manual_spawner_target_actor);
        }
    }

    bool observe_emission = false;
    std::uint64_t bot_id = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t expected_projectile_type = 0;
    std::vector<uintptr_t> projectile_addresses_before;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        auto* binding = FindParticipantEntityForActor(actor_address);
        if (binding != nullptr &&
            IsNativeRemoteParticipantBinding(binding) &&
            binding->ongoing_cast.active &&
            binding->ongoing_cast.lane ==
                ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
            binding->ongoing_cast.mana_charge_kind ==
                multiplayer::BotManaChargeKind::PerCast &&
            binding->ongoing_cast.remote_per_cast_projectile_baseline_valid) {
            auto& ongoing = binding->ongoing_cast;
            if (ongoing.remote_per_cast_projectile_emission_latched) {
                ongoing.remote_per_cast_duplicate_dispatches_suppressed += 1;
                if (ongoing.remote_per_cast_duplicate_dispatches_suppressed == 1) {
                    Log(
                        "[bots] suppressed duplicate remote per-cast primary dispatch. bot_id=" +
                        std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " remote_cast_sequence=" +
                        std::to_string(ongoing.remote_input_cast_sequence) +
                        " projectile_type=" + HexString(static_cast<uintptr_t>(
                            ongoing.remote_per_cast_projectile_expected_type)));
                }
                return;
            }

            observe_emission = true;
            bot_id = binding->bot_id;
            cast_sequence = ongoing.remote_input_cast_sequence;
            expected_projectile_type = ongoing.remote_per_cast_projectile_expected_type;
            projectile_addresses_before = ongoing.remote_per_cast_projectile_addresses_before;
        }
    }

    original(self);
    if (!observe_emission) {
        return;
    }

    uintptr_t emitted_projectile_actor = 0;
    if (!TryFindNewPurePrimaryProjectileActorInScene(
            expected_projectile_type,
            projectile_addresses_before,
            &emitted_projectile_actor)) {
        return;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    auto* binding = FindParticipantEntityForActor(actor_address);
    if (binding == nullptr ||
        binding->bot_id != bot_id ||
        !IsNativeRemoteParticipantBinding(binding) ||
        !binding->ongoing_cast.active ||
        binding->ongoing_cast.remote_input_cast_sequence != cast_sequence ||
        binding->ongoing_cast.lane !=
            ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary ||
        binding->ongoing_cast.mana_charge_kind !=
            multiplayer::BotManaChargeKind::PerCast) {
        return;
    }

    auto& ongoing = binding->ongoing_cast;
    ongoing.remote_per_cast_projectile_emission_latched = true;
    ongoing.remote_per_cast_projectile_observed = true;
    ongoing.remote_per_cast_projectile_observed_actor = emitted_projectile_actor;
    Log(
        "[bots] latched first remote per-cast primary emission. bot_id=" +
        std::to_string(binding->bot_id) +
        " actor=" + HexString(actor_address) +
        " remote_cast_sequence=" + std::to_string(cast_sequence) +
        " projectile_type=" +
        HexString(static_cast<uintptr_t>(expected_projectile_type)) +
        " projectile_actor=" + HexString(emitted_projectile_actor));
}

#include "player_cast_hooks_effect_and_dispatch.inl"
