constexpr std::uint64_t kReplicatedEmberNaturalReplayGraceMs = 16;

std::unordered_map<std::uint64_t, std::unordered_map<std::uint32_t, std::uint64_t>>
    g_pending_replicated_spell_effect_materialization;

bool HasPendingReplicatedSpellEffectMaterialization() {
    return !g_pending_replicated_spell_effect_materialization.empty();
}

bool IsPendingReplicatedSpellEffectMaterialization(
    std::uint64_t owner_participant_id,
    std::uint32_t effect_serial) {
    const auto owner_it =
        g_pending_replicated_spell_effect_materialization.find(
            owner_participant_id);
    return owner_it != g_pending_replicated_spell_effect_materialization.end() &&
           owner_it->second.find(effect_serial) != owner_it->second.end();
}

void ClearPendingReplicatedSpellEffectMaterialization() {
    g_pending_replicated_spell_effect_materialization.clear();
}

void ForgetPendingReplicatedSpellEffectMaterialization(
    std::uint64_t owner_participant_id,
    std::uint32_t effect_serial) {
    const auto owner_it =
        g_pending_replicated_spell_effect_materialization.find(
            owner_participant_id);
    if (owner_it == g_pending_replicated_spell_effect_materialization.end()) {
        return;
    }
    owner_it->second.erase(effect_serial);
    if (owner_it->second.empty()) {
        g_pending_replicated_spell_effect_materialization.erase(owner_it);
    }
}

bool IsValidReplicatedEmberRuntime(
    const multiplayer::SpellEffectSnapshot& effect) {
    return effect.native_type_id == kReplicatedFireEmberNativeTypeId &&
           effect.ember_runtime_valid &&
           std::isfinite(effect.ember_vertical_position) &&
           std::isfinite(effect.ember_vertical_velocity) &&
           std::isfinite(effect.ember_damage) &&
           std::isfinite(effect.ember_lifetime) &&
           std::isfinite(effect.ember_initial_lifetime) &&
           std::isfinite(effect.ember_animation_progress) &&
           effect.ember_lifetime > 0.0f &&
           effect.ember_initial_lifetime > 0.0f;
}

bool IsValidReplicatedFirewalkerRuntime(
    const multiplayer::SpellEffectSnapshot& effect) {
    return effect.native_type_id == kReplicatedFirewalkerTrailNativeTypeId &&
           effect.firewalker_runtime_valid &&
           std::isfinite(effect.firewalker_collision_scale) &&
           std::isfinite(effect.firewalker_phase) &&
           std::isfinite(effect.firewalker_phase_step) &&
           std::isfinite(effect.firewalker_lifetime) &&
           std::isfinite(effect.firewalker_fade) &&
           std::isfinite(effect.firewalker_direction) &&
           std::isfinite(effect.firewalker_visual_scale) &&
           std::isfinite(effect.firewalker_damage) &&
           effect.firewalker_lifetime > 0.0f;
}

bool ShouldMaterializeMissingReplicatedSpellEffect(
    std::uint64_t owner_participant_id,
    const multiplayer::SpellEffectSnapshot& effect,
    std::uint64_t now_ms) {
    if (owner_participant_id == 0 ||
        !effect.transform_valid ||
        !std::isfinite(effect.position_x) ||
        !std::isfinite(effect.position_y) ||
        !std::isfinite(effect.radius) ||
        !std::isfinite(effect.heading) ||
        effect.radius < 0.0f) {
        return false;
    }

    if (IsValidReplicatedFirewalkerRuntime(effect)) {
        return effect.active && !effect.terminal;
    }
    if (!effect.motion_valid ||
        !std::isfinite(effect.motion_x) ||
        !std::isfinite(effect.motion_y) ||
        !IsValidReplicatedEmberRuntime(effect)) {
        return false;
    }
    if (effect.terminal) {
        return IsPendingReplicatedSpellEffectMaterialization(
            owner_participant_id,
            effect.effect_serial);
    }
    if (!effect.active) {
        return false;
    }

    auto& first_seen_by_serial =
        g_pending_replicated_spell_effect_materialization[
            owner_participant_id];
    const auto [it, inserted] =
        first_seen_by_serial.try_emplace(effect.effect_serial, now_ms);
    if (inserted) {
        return false;
    }
    if (now_ms < it->second) {
        it->second = now_ms;
        return false;
    }
    return now_ms - it->second >= kReplicatedEmberNaturalReplayGraceMs;
}

bool TryWriteReplicatedEmberRuntime(
    uintptr_t actor_address,
    const multiplayer::SpellEffectSnapshot& effect) {
    if (actor_address == 0 ||
        !IsValidReplicatedEmberRuntime(effect) ||
        kEmberVerticalPositionOffset == 0 ||
        kEmberVerticalVelocityOffset == 0 ||
        kEmberDamageOffset == 0 ||
        kEmberLifetimeOffset == 0 ||
        kEmberInitialLifetimeOffset == 0 ||
        kEmberAnimationProgressOffset == 0 ||
        kEmberVariantOffset == 0 ||
        kEmberFrameIntervalOffset == 0 ||
        kEmberConfigPrimaryOffset == 0 ||
        kEmberConfigSecondaryOffset == 0 ||
        kEmberConfigTertiaryOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryWriteField(
               actor_address,
               kEmberVerticalPositionOffset,
               effect.ember_vertical_position) &&
           memory.TryWriteField(
               actor_address,
               kEmberVerticalVelocityOffset,
               effect.ember_vertical_velocity) &&
           memory.TryWriteField(actor_address, kEmberDamageOffset, effect.ember_damage) &&
           memory.TryWriteField(actor_address, kEmberLifetimeOffset, effect.ember_lifetime) &&
           memory.TryWriteField(
               actor_address,
               kEmberInitialLifetimeOffset,
               effect.ember_initial_lifetime) &&
           memory.TryWriteField(
               actor_address,
               kEmberAnimationProgressOffset,
               effect.ember_animation_progress) &&
           memory.TryWriteField(actor_address, kEmberVariantOffset, effect.ember_variant) &&
           memory.TryWriteField(
               actor_address,
               kEmberFrameIntervalOffset,
               effect.ember_frame_interval) &&
           memory.TryWriteField(
               actor_address,
               kEmberConfigPrimaryOffset,
               effect.ember_config_primary) &&
           memory.TryWriteField(
               actor_address,
               kEmberConfigSecondaryOffset,
               effect.ember_config_secondary) &&
           memory.TryWriteField(
               actor_address,
               kEmberConfigTertiaryOffset,
               effect.ember_config_tertiary);
}

bool TryWriteReplicatedFirewalkerRuntime(
    uintptr_t actor_address,
    int owner_gameplay_slot,
    const multiplayer::SpellEffectSnapshot& effect) {
    if (actor_address == 0 ||
        owner_gameplay_slot < 0 ||
        !IsValidReplicatedFirewalkerRuntime(effect) ||
        kFirewalkerSourceSlotOffset == 0 ||
        kFirewalkerCollisionScaleOffset == 0 ||
        kFirewalkerPhaseOffset == 0 ||
        kFirewalkerPhaseStepOffset == 0 ||
        kFirewalkerLifetimeOffset == 0 ||
        kFirewalkerFadeOffset == 0 ||
        kFirewalkerDirectionOffset == 0 ||
        kFirewalkerVisualScaleOffset == 0 ||
        kFirewalkerActiveOffset == 0 ||
        kFirewalkerDamageOffset == 0 ||
        kFirewalkerAuxOffset == 0 ||
        kFirewalkerVariantOffset == 0 ||
        kFirewalkerDamageMaskOffset == 0) {
        return false;
    }

    const auto source_slot = static_cast<std::int8_t>(owner_gameplay_slot);
    auto& memory = ProcessMemory::Instance();
    return memory.TryWriteField(actor_address, kFirewalkerSourceSlotOffset, source_slot) &&
           memory.TryWriteField(
               actor_address,
               kFirewalkerCollisionScaleOffset,
               effect.firewalker_collision_scale) &&
           memory.TryWriteField(actor_address, kFirewalkerPhaseOffset, effect.firewalker_phase) &&
           memory.TryWriteField(
               actor_address,
               kFirewalkerPhaseStepOffset,
               effect.firewalker_phase_step) &&
           memory.TryWriteField(
               actor_address,
               kFirewalkerLifetimeOffset,
               effect.firewalker_lifetime) &&
           memory.TryWriteField(actor_address, kFirewalkerFadeOffset, effect.firewalker_fade) &&
           memory.TryWriteField(
               actor_address,
               kFirewalkerDirectionOffset,
               effect.firewalker_direction) &&
           memory.TryWriteField(
               actor_address,
               kFirewalkerVisualScaleOffset,
               effect.firewalker_visual_scale) &&
           memory.TryWriteField(actor_address, kFirewalkerActiveOffset, effect.firewalker_active) &&
           memory.TryWriteField(actor_address, kFirewalkerDamageOffset, effect.firewalker_damage) &&
           memory.TryWriteField(actor_address, kFirewalkerAuxOffset, effect.firewalker_aux) &&
           memory.TryWriteField(actor_address, kFirewalkerVariantOffset, effect.firewalker_variant) &&
           memory.TryWriteField(
               actor_address,
               kFirewalkerDamageMaskOffset,
               effect.firewalker_damage_mask);
}

bool TrySeedReplicatedSpellEffectState(
    uintptr_t actor_address,
    int owner_gameplay_slot,
    const multiplayer::SpellEffectSnapshot& effect) {
    if (actor_address == 0 ||
        !effect.transform_valid ||
        !std::isfinite(effect.position_x) ||
        !std::isfinite(effect.position_y) ||
        !std::isfinite(effect.radius) ||
        !std::isfinite(effect.heading) ||
        effect.radius < 0.0f) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote_transform =
        memory.TryWriteField(actor_address, kActorPositionXOffset, effect.position_x) &&
        memory.TryWriteField(actor_address, kActorPositionYOffset, effect.position_y) &&
        memory.TryWriteField(actor_address, kActorCollisionRadiusOffset, effect.radius) &&
        memory.TryWriteField(actor_address, kActorHeadingOffset, effect.heading);
    if (!wrote_transform) {
        return false;
    }

    if (effect.native_type_id == kReplicatedFireEmberNativeTypeId) {
        return effect.motion_valid &&
               std::isfinite(effect.motion_x) &&
               std::isfinite(effect.motion_y) &&
               memory.TryWriteField(
                   actor_address,
                   kSpellEffectMotionXOffset,
                   effect.motion_x) &&
               memory.TryWriteField(
                   actor_address,
                   kSpellEffectMotionYOffset,
                   effect.motion_y) &&
               TryWriteReplicatedEmberRuntime(actor_address, effect);
    }
    if (effect.native_type_id == kReplicatedFirewalkerTrailNativeTypeId) {
        return TryWriteReplicatedFirewalkerRuntime(
            actor_address,
            owner_gameplay_slot,
            effect);
    }
    return false;
}

void DeleteUnregisteredReplicatedSpellEffect(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    const auto object_delete_address =
        memory.ResolveGameAddressOrZero(kObjectDelete);
    DWORD exception_code = 0;
    if (object_delete_address != 0) {
        (void)CallObjectDeleteSafe(
            object_delete_address,
            actor_address,
            &exception_code);
    }
}

bool TryCreateReplicatedSpellEffect(
    uintptr_t world_address,
    int owner_gameplay_slot,
    const multiplayer::SpellEffectSnapshot& effect,
    uintptr_t* actor_address_out) {
    if (actor_address_out != nullptr) {
        *actor_address_out = 0;
    }
    if (world_address == 0 ||
        owner_gameplay_slot < kFirstWizardBotSlot ||
        owner_gameplay_slot >= static_cast<int>(kGameplayPlayerSlotCount) ||
        (effect.native_type_id != kReplicatedFireEmberNativeTypeId &&
         effect.native_type_id != kReplicatedFirewalkerTrailNativeTypeId)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto register_address = memory.ResolveGameAddressOrZero(kActorWorldRegister);
    if (factory_address == 0 ||
        factory_context_address == 0 ||
        register_address == 0) {
        return false;
    }

    uintptr_t actor_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(effect.native_type_id),
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        Log(
            "spell_effect: factory create failed. type=" +
            HexString(static_cast<uintptr_t>(effect.native_type_id)) +
            " slot=" + std::to_string(owner_gameplay_slot) +
            " seh=" + HexString(exception_code));
        return false;
    }

    if (!TrySeedReplicatedSpellEffectState(
            actor_address,
            owner_gameplay_slot,
            effect)) {
        DeleteUnregisteredReplicatedSpellEffect(actor_address);
        Log(
            "spell_effect: state seed failed. type=" +
            HexString(static_cast<uintptr_t>(effect.native_type_id)) +
            " slot=" + std::to_string(owner_gameplay_slot));
        return false;
    }

    exception_code = 0;
    if (!CallActorWorldRegisterSafe(
            register_address,
            world_address,
            owner_gameplay_slot,
            actor_address,
            -1,
            0,
            &exception_code)) {
        DeleteUnregisteredReplicatedSpellEffect(actor_address);
        Log(
            "spell_effect: actor register failed. type=" +
            HexString(static_cast<uintptr_t>(effect.native_type_id)) +
            " slot=" + std::to_string(owner_gameplay_slot) +
            " seh=" + HexString(exception_code));
        return false;
    }

    if (actor_address_out != nullptr) {
        *actor_address_out = actor_address;
    }
    Log(
        "spell_effect: materialized replicated effect. type=" +
        HexString(static_cast<uintptr_t>(effect.native_type_id)) +
        " actor=" + HexString(actor_address) +
        " slot=" + std::to_string(owner_gameplay_slot) +
        " serial=" + std::to_string(effect.effect_serial));
    return true;
}
