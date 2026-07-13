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
};

bool IsUsableSecondaryCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y) {
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y) ||
        (std::abs(aim_target_x) < 0.001f &&
         std::abs(aim_target_y) < 0.001f)) {
        return false;
    }
    const auto dx = aim_target_x - position_x;
    const auto dy = aim_target_y - position_y;
    const auto distance = std::sqrt(dx * dx + dy * dy);
    return std::isfinite(distance) &&
           distance >= 1.0f &&
           distance <= 4096.0f &&
           std::abs(aim_target_x) <= 20000.0f &&
           std::abs(aim_target_y) <= 20000.0f;
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

    float heading = 0.0f;
    if (!memory.TryReadField(actor_address, kActorPositionXOffset, &capture->position_x) ||
        !memory.TryReadField(actor_address, kActorPositionYOffset, &capture->position_y) ||
        !memory.TryReadField(actor_address, kActorHeadingOffset, &heading) ||
        !std::isfinite(capture->position_x) ||
        !std::isfinite(capture->position_y) ||
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

    (void)memory.TryReadField(
        actor_address,
        kActorCurrentTargetActorOffset,
        &capture->target_actor_address);
    if (memory.TryReadField(
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
            capture->aim_target_y)) {
        const auto aim_dx = capture->aim_target_x - capture->position_x;
        const auto aim_dy = capture->aim_target_y - capture->position_y;
        const auto aim_length = std::sqrt(aim_dx * aim_dx + aim_dy * aim_dy);
        capture->direction_x = aim_dx / aim_length;
        capture->direction_y = aim_dy / aim_length;
        capture->has_aim_target = true;
    }

    capture->valid = true;
    return true;
}

bool IsNativeSecondaryToggleSkill(std::int32_t skill_entry_index) {
    // Firewalker, Mindstar, and Regenerate use false to report the native
    // toggle-off transition even though the requested state change succeeded.
    return skill_entry_index == 0x17 ||
           skill_entry_index == 0x4E ||
           skill_entry_index == 0x4F;
}

bool TryConsumeLocalMultiplayerDampenMana(
    uintptr_t actor_address,
    std::int32_t belt_slot,
    float* mana_before,
    float* mana_after,
    float* mana_cost) {
    if (mana_before != nullptr) {
        *mana_before = 0.0f;
    }
    if (mana_after != nullptr) {
        *mana_after = 0.0f;
    }
    if (mana_cost != nullptr) {
        *mana_cost = 0.0f;
    }

    uintptr_t progression = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression) ||
        progression == 0) {
        return false;
    }
    NativeSecondarySpellManaStats resolved{};
    std::string resolve_error;
    if (!TryResolveNativeSecondarySpellManaStats(
        progression,
        0x33,
        &resolved,
        &resolve_error)) {
        Log(
            "Multiplayer local Dampen mana resolution failed. actor=" +
            HexString(actor_address) +
            " belt_slot=" + std::to_string(belt_slot) +
            " error=" + resolve_error);
        return false;
    }

    float current = 0.0f;
    float maximum = 0.0f;
    if (!TryReadProgressionMana(progression, &current, &maximum) ||
        current + 0.001f < resolved.spend_cost) {
        return false;
    }
    const auto resulting = (std::max)(0.0f, current - resolved.spend_cost);
    if (!ProcessMemory::Instance().TryWriteField(
            progression,
            kProgressionMpOffset,
            resulting)) {
        return false;
    }

    if (mana_before != nullptr) {
        *mana_before = current;
    }
    if (mana_after != nullptr) {
        *mana_after = resulting;
    }
    if (mana_cost != nullptr) {
        *mana_cost = resolved.spend_cost;
    }
    return true;
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
    if (skill_entry_index == 0x33 && multiplayer::IsLocalTransportEnabled()) {
        // Stock Dampen corrupts the engine's shared pointer-list heap even in
        // an otherwise empty two-player arena. Remote observers replay the
        // loader-owned authoritative effect instead of entering that branch.
        if (result != nullptr) {
            *result = 1;
        }
        Log(
            "Multiplayer remote Dampen used the safe replicated dispatcher. "
            "actor=" + HexString(actor_address));
        return true;
    }

    ++g_remote_secondary_spell_dispatch_depth;
    const auto native_result =
        original(reinterpret_cast<void*>(actor_address), skill_entry_index);
    --g_remote_secondary_spell_dispatch_depth;
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
    LocalSecondaryCastCapture capture{};
    const bool should_capture =
        g_remote_secondary_spell_dispatch_depth == 0 &&
        multiplayer::IsLocalTransportEnabled() &&
        TryCaptureLocalSecondaryCast(
            actor_address,
            skill_entry_index,
            &capture);
    std::uint8_t native_result = 0;
    if (skill_entry_index == 0x33 && multiplayer::IsLocalTransportEnabled()) {
        float mana_before = 0.0f;
        float mana_after = 0.0f;
        float mana_cost = 0.0f;
        if (should_capture &&
            TryConsumeLocalMultiplayerDampenMana(
                actor_address,
                capture.belt_slot,
                &mana_before,
                &mana_after,
                &mana_cost)) {
            native_result = 1;
            Log(
                "Multiplayer local Dampen used the safe replicated dispatcher. "
                "actor=" + HexString(actor_address) +
                " mana_before=" + std::to_string(mana_before) +
                " mana_after=" + std::to_string(mana_after) +
                " mana_cost=" + std::to_string(mana_cost));
        }
    } else {
        native_result = original(self, skill_entry_index);
    }
    if (!should_capture ||
        (native_result == 0 &&
         !IsNativeSecondaryToggleSkill(skill_entry_index))) {
        if (should_capture && native_result == 0) {
            Log(
                "Multiplayer local secondary cast rejected by native dispatcher. actor=" +
                HexString(actor_address) +
                " skill_entry=" + std::to_string(skill_entry_index) +
                " belt_slot=" + std::to_string(capture.belt_slot));
        }
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
            capture.secondary_entry_indices.size());
    if (native_queue_id != 0) {
        Log(
            "Multiplayer local secondary cast queued from native dispatcher. actor=" +
            HexString(actor_address) +
            " skill_entry=" + std::to_string(skill_entry_index) +
            " belt_slot=" + std::to_string(capture.belt_slot) +
            " native_result=" + std::to_string(native_result) +
            " native_queue_id=" + std::to_string(native_queue_id));
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
