// Participant-owned Hagatha charm and curse state. The ordered selector list
// is durable owner state. Cheat Death and the two until-hurt bytes become
// host-authored while a remote participant is in a run.

struct HagathaRuntimeCorrectionState {
    bool valid = false;
    std::int32_t cheat_death_charges = 0;
    bool serendipity_active = false;
    bool reverie_active = false;
    bool cheat_death_consumed = false;
    bool native_life_valid = false;
    float life_current = 0.0f;
    float life_max = 0.0f;
};

using NativeActorProgressionApplyHagathaPerkFn =
    void(__thiscall*)(void* progression, std::int32_t selector);
using NativeActorProgressionRefreshHagathaFn =
    void(__thiscall*)(void* progression);

bool HagathaPerkSelectorsAreSane(
    std::uint8_t perk_count,
    const std::array<std::int8_t, kParticipantHagathaPerkMaxCount>& selectors) {
    if (perk_count > kParticipantHagathaPerkMaxCount) {
        return false;
    }

    std::array<bool, 27> seen = {};
    std::uint8_t tonic_count = 0;
    for (std::size_t index = 0; index < selectors.size(); ++index) {
        const auto selector = selectors[index];
        if (index >= perk_count) {
            if (selector != -1) {
                return false;
            }
            continue;
        }
        if (selector < 0 || selector > 27) {
            return false;
        }
        if (selector == 27) {
            if (++tonic_count > 2) {
                return false;
            }
            continue;
        }
        if (seen[static_cast<std::size_t>(selector)]) {
            return false;
        }
        seen[static_cast<std::size_t>(selector)] = true;
    }
    return true;
}

bool HagathaPerkStatesEqual(
    const ParticipantHagathaPerkState& left,
    const ParticipantHagathaPerkState& right) {
    return left.valid == right.valid &&
           left.perk_count == right.perk_count &&
           left.perk_capacity == right.perk_capacity &&
           left.cheat_death_charges == right.cheat_death_charges &&
           left.serendipity_active == right.serendipity_active &&
           left.reverie_active == right.reverie_active &&
           left.perk_selectors == right.perk_selectors;
}

bool HagathaPerkIdentityEqual(
    const ParticipantHagathaPerkState& left,
    const ParticipantHagathaPerkState& right) {
    return left.valid == right.valid &&
           left.perk_count == right.perk_count &&
           left.perk_capacity == right.perk_capacity &&
           left.perk_selectors == right.perk_selectors;
}

bool TryReadNativeHagathaPerkState(
    uintptr_t progression_address,
    ParticipantHagathaPerkState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = ParticipantHagathaPerkState{};
    if (progression_address == 0 ||
        kProgressionHagathaPerkListOffset == 0 ||
        kProgressionHagathaPerkCountOffset == 0 ||
        kProgressionHagathaPerkFlagBaseOffset == 0 ||
        kProgressionHagathaPerkCapacityOffset == 0 ||
        kProgressionCheatDeathEnabledOffset == 0 ||
        kProgressionCheatDeathChargesOffset == 0 ||
        kProgressionSerendipityActiveOffset == 0 ||
        kProgressionReverieActiveOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t selector_list = 0;
    std::int32_t perk_count = 0;
    std::int32_t perk_capacity = 0;
    std::int32_t cheat_death_charges = 0;
    std::uint8_t serendipity_active = 0;
    std::uint8_t reverie_active = 0;
    if (!memory.TryReadField(
            progression_address,
            kProgressionHagathaPerkListOffset,
            &selector_list) ||
        !memory.TryReadField(
            progression_address,
            kProgressionHagathaPerkCountOffset,
            &perk_count) ||
        !memory.TryReadField(
            progression_address,
            kProgressionHagathaPerkCapacityOffset,
            &perk_capacity) ||
        !memory.TryReadField(
            progression_address,
            kProgressionCheatDeathChargesOffset,
            &cheat_death_charges) ||
        !memory.TryReadField(
            progression_address,
            kProgressionSerendipityActiveOffset,
            &serendipity_active) ||
        !memory.TryReadField(
            progression_address,
            kProgressionReverieActiveOffset,
            &reverie_active) ||
        perk_count < 0 ||
        perk_count > static_cast<std::int32_t>(kParticipantHagathaPerkMaxCount) ||
        perk_capacity < 0 ||
        perk_capacity > static_cast<std::int32_t>(kParticipantHagathaPerkMaxCount) ||
        perk_count > perk_capacity ||
        cheat_death_charges < 0 ||
        cheat_death_charges > 1 ||
        serendipity_active > 1 ||
        reverie_active > 1 ||
        (perk_count > 0 && selector_list == 0)) {
        return false;
    }

    ParticipantHagathaPerkState next;
    next.valid = true;
    next.perk_count = static_cast<std::uint8_t>(perk_count);
    next.perk_capacity = static_cast<std::uint8_t>(perk_capacity);
    next.cheat_death_charges = cheat_death_charges;
    next.serendipity_active = serendipity_active != 0;
    next.reverie_active = reverie_active != 0;
    for (std::int32_t index = 0; index < perk_count; ++index) {
        std::int32_t selector = -1;
        if (!memory.TryReadField(
                selector_list,
                static_cast<std::size_t>(index) * sizeof(std::int32_t),
                &selector) ||
            selector < 0 || selector > 27) {
            return false;
        }
        next.perk_selectors[static_cast<std::size_t>(index)] =
            static_cast<std::int8_t>(selector);
    }
    if (!HagathaPerkSelectorsAreSane(next.perk_count, next.perk_selectors)) {
        return false;
    }
    *state = next;
    return true;
}

void RefreshOwnedHagathaPerks(
    uintptr_t progression_address,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr) {
        return;
    }
    ParticipantHagathaPerkState next;
    if (!TryReadNativeHagathaPerkState(progression_address, &next) ||
        HagathaPerkStatesEqual(owned_progression->hagatha_perks, next)) {
        return;
    }
    owned_progression->hagatha_perks = next;
    owned_progression->hagatha_perk_revision += 1;
}

void BuildHagathaPerkPacketState(
    const ParticipantOwnedProgressionState& owned_progression,
    std::uint32_t* revision,
    ParticipantHagathaPerkPacketState* packet) {
    if (revision == nullptr || packet == nullptr) {
        return;
    }
    *revision = owned_progression.hagatha_perk_revision;
    *packet = ParticipantHagathaPerkPacketState{};
    std::fill(
        std::begin(packet->perk_selectors),
        std::end(packet->perk_selectors),
        static_cast<std::int8_t>(-1));
    const auto& perks = owned_progression.hagatha_perks;
    packet->valid = perks.valid ? 1 : 0;
    packet->perk_count = perks.perk_count;
    packet->perk_capacity = perks.perk_capacity;
    packet->cheat_death_charges = perks.cheat_death_charges;
    packet->runtime_flags = static_cast<std::uint8_t>(
        (perks.serendipity_active
             ? ParticipantHagathaRuntimeFlagSerendipityActive
             : 0) |
        (perks.reverie_active
             ? ParticipantHagathaRuntimeFlagReverieActive
             : 0));
    std::copy(
        perks.perk_selectors.begin(),
        perks.perk_selectors.end(),
        packet->perk_selectors);
}

bool IsSaneHagathaPerkPacketState(
    const ParticipantHagathaPerkPacketState& packet) {
    if (packet.valid == 0 ||
        packet.perk_count > kParticipantHagathaPerkMaxCount ||
        packet.perk_capacity > kParticipantHagathaPerkMaxCount ||
        packet.perk_count > packet.perk_capacity ||
        packet.cheat_death_charges < 0 ||
        packet.cheat_death_charges > 1 ||
        (packet.runtime_flags & ~kParticipantHagathaRuntimeKnownFlags) != 0) {
        return false;
    }
    std::array<std::int8_t, kParticipantHagathaPerkMaxCount> selectors = {};
    std::copy(
        std::begin(packet.perk_selectors),
        std::end(packet.perk_selectors),
        selectors.begin());
    return HagathaPerkSelectorsAreSane(packet.perk_count, selectors);
}

void ApplyHagathaPerkPacketState(
    std::uint32_t revision,
    const ParticipantHagathaPerkPacketState& packet,
    bool preserve_host_runtime_state,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr ||
        !IsSaneHagathaPerkPacketState(packet) ||
        (owned_progression->hagatha_perks.valid &&
         revision <= owned_progression->hagatha_perk_revision)) {
        return;
    }

    ParticipantHagathaPerkState next;
    next.valid = true;
    next.perk_count = packet.perk_count;
    next.perk_capacity = packet.perk_capacity;
    next.cheat_death_charges = packet.cheat_death_charges;
    next.serendipity_active =
        (packet.runtime_flags &
         ParticipantHagathaRuntimeFlagSerendipityActive) != 0;
    next.reverie_active =
        (packet.runtime_flags &
         ParticipantHagathaRuntimeFlagReverieActive) != 0;
    std::copy(
        std::begin(packet.perk_selectors),
        std::end(packet.perk_selectors),
        next.perk_selectors.begin());
    if (preserve_host_runtime_state && owned_progression->hagatha_perks.valid) {
        next.cheat_death_charges =
            owned_progression->hagatha_perks.cheat_death_charges;
        next.serendipity_active =
            owned_progression->hagatha_perks.serendipity_active;
        next.reverie_active =
            owned_progression->hagatha_perks.reverie_active;
    }
    owned_progression->hagatha_perks = next;
    owned_progression->hagatha_perk_revision = revision;
}

bool CallNativeActorProgressionApplyHagathaPerk(
    uintptr_t progression_address,
    std::int32_t selector,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto apply_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kActorProgressionApplyHagathaPerk);
    auto* apply = reinterpret_cast<NativeActorProgressionApplyHagathaPerkFn>(
        apply_address);
    if (apply == nullptr || progression_address == 0 ||
        selector < 0 || selector > 27) {
        return false;
    }
    __try {
        apply(reinterpret_cast<void*>(progression_address), selector);
        return true;
    } __except (CaptureLocalTransportSehCode(
        GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallNativeActorProgressionRefreshForHagatha(
    uintptr_t progression_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto refresh_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kActorProgressionRefresh);
    auto* refresh = reinterpret_cast<NativeActorProgressionRefreshHagathaFn>(
        refresh_address);
    if (refresh == nullptr || progression_address == 0) {
        return false;
    }
    __try {
        refresh(reinterpret_cast<void*>(progression_address));
        return true;
    } __except (CaptureLocalTransportSehCode(
        GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ResetRemoteNativeHagathaPerks(uintptr_t progression_address) {
    auto& memory = ProcessMemory::Instance();
    const std::int32_t zero_count = 0;
    const std::int32_t zero_charges = 0;
    const std::uint8_t zero_byte = 0;
    if (!memory.TryWriteField(
            progression_address,
            kProgressionHagathaPerkCountOffset,
            zero_count) ||
        !memory.TryWrite(
            progression_address + kProgressionHagathaPerkFlagBaseOffset,
            std::array<std::uint8_t, 28>{}.data(),
            28) ||
        !memory.TryWriteField(
            progression_address,
            kProgressionCheatDeathEnabledOffset,
            zero_byte) ||
        !memory.TryWriteField(
            progression_address,
            kProgressionCheatDeathChargesOffset,
            zero_charges) ||
        !memory.TryWriteField(
            progression_address,
            kProgressionSerendipityActiveOffset,
            zero_byte) ||
        !memory.TryWriteField(
            progression_address,
            kProgressionReverieActiveOffset,
            zero_byte)) {
        return false;
    }
    DWORD exception_code = 0;
    return CallNativeActorProgressionRefreshForHagatha(
        progression_address,
        &exception_code);
}

bool ReconcileRemoteHagathaPerks(
    uintptr_t progression_address,
    const ParticipantHagathaPerkState& desired,
    bool apply_runtime_state,
    int* mutation_count) {
    if (mutation_count != nullptr) {
        *mutation_count = 0;
    }
    if (!desired.valid ||
        !HagathaPerkSelectorsAreSane(
            desired.perk_count,
            desired.perk_selectors)) {
        return false;
    }

    ParticipantHagathaPerkState native;
    if (!TryReadNativeHagathaPerkState(progression_address, &native)) {
        return false;
    }
    bool prefix_matches = native.perk_count <= desired.perk_count;
    for (std::size_t index = 0;
         prefix_matches && index < native.perk_count;
         ++index) {
        prefix_matches =
            native.perk_selectors[index] == desired.perk_selectors[index];
    }
    int mutations = 0;
    if (!prefix_matches || native.perk_count > desired.perk_count) {
        if (!ResetRemoteNativeHagathaPerks(progression_address) ||
            !TryReadNativeHagathaPerkState(progression_address, &native)) {
            return false;
        }
        ++mutations;
    }

    for (std::size_t index = native.perk_count;
         index < desired.perk_count;
         ++index) {
        DWORD exception_code = 0;
        if (!CallNativeActorProgressionApplyHagathaPerk(
                progression_address,
                desired.perk_selectors[index],
                &exception_code)) {
            return false;
        }
        ++mutations;
    }

    auto& memory = ProcessMemory::Instance();
    std::int32_t native_capacity = 0;
    if (!memory.TryReadField(
            progression_address,
            kProgressionHagathaPerkCapacityOffset,
            &native_capacity)) {
        return false;
    }
    if (native_capacity != desired.perk_capacity) {
        const auto capacity = static_cast<std::int32_t>(desired.perk_capacity);
        if (!memory.TryWriteField(
                progression_address,
                kProgressionHagathaPerkCapacityOffset,
                capacity)) {
            return false;
        }
        ++mutations;
    }

    if (apply_runtime_state) {
        std::int32_t native_charges = 0;
        std::uint8_t native_serendipity = 0;
        std::uint8_t native_reverie = 0;
        if (!memory.TryReadField(
                progression_address,
                kProgressionCheatDeathChargesOffset,
                &native_charges) ||
            !memory.TryReadField(
                progression_address,
                kProgressionSerendipityActiveOffset,
                &native_serendipity) ||
            !memory.TryReadField(
                progression_address,
                kProgressionReverieActiveOffset,
                &native_reverie)) {
            return false;
        }
        const auto desired_serendipity = static_cast<std::uint8_t>(
            desired.serendipity_active ? 1 : 0);
        const auto desired_reverie = static_cast<std::uint8_t>(
            desired.reverie_active ? 1 : 0);
        bool refresh_required = false;
        if (native_charges != desired.cheat_death_charges) {
            if (!memory.TryWriteField(
                    progression_address,
                    kProgressionCheatDeathChargesOffset,
                    desired.cheat_death_charges)) {
                return false;
            }
            ++mutations;
        }
        if (native_serendipity != desired_serendipity) {
            if (!memory.TryWriteField(
                    progression_address,
                    kProgressionSerendipityActiveOffset,
                    desired_serendipity)) {
                return false;
            }
            refresh_required = true;
            ++mutations;
        }
        if (native_reverie != desired_reverie) {
            if (!memory.TryWriteField(
                    progression_address,
                    kProgressionReverieActiveOffset,
                    desired_reverie)) {
                return false;
            }
            refresh_required = true;
            ++mutations;
        }
        if (refresh_required) {
            DWORD exception_code = 0;
            if (!CallNativeActorProgressionRefreshForHagatha(
                    progression_address,
                    &exception_code)) {
                return false;
            }
        }
    }

    ParticipantHagathaPerkState verified;
    if (!TryReadNativeHagathaPerkState(progression_address, &verified) ||
        !HagathaPerkIdentityEqual(verified, desired) ||
        (apply_runtime_state &&
         !HagathaPerkStatesEqual(verified, desired))) {
        return false;
    }
    if (mutation_count != nullptr) {
        *mutation_count = mutations;
    }
    return true;
}

bool CaptureAuthoritativeHagathaRuntimeState(
    std::uint64_t target_participant_id,
    HagathaRuntimeCorrectionState* correction) {
    if (correction == nullptr) {
        return false;
    }
    *correction = HagathaRuntimeCorrectionState{};
    if (!g_local_transport.is_host || target_participant_id == 0 ||
        target_participant_id == g_local_transport.local_peer_id) {
        return false;
    }

    const auto snapshot = SnapshotRuntimeState();
    const auto* participant = FindParticipant(snapshot, target_participant_id);
    SDModParticipantGameplayState gameplay_state;
    ParticipantHagathaPerkState native;
    if (participant == nullptr ||
        !participant->owned_progression.hagatha_perks.valid ||
        !TryGetParticipantGameplayState(
            target_participant_id,
            &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0 ||
        !TryReadNativeHagathaPerkState(
            gameplay_state.progression_runtime_state_address,
            &native) ||
        !HagathaPerkIdentityEqual(
            native,
            participant->owned_progression.hagatha_perks)) {
        return false;
    }

    correction->valid = true;
    correction->cheat_death_charges = native.cheat_death_charges;
    correction->serendipity_active = native.serendipity_active;
    correction->reverie_active = native.reverie_active;
    correction->cheat_death_consumed =
        native.cheat_death_charges <
        participant->owned_progression.hagatha_perks.cheat_death_charges;
    if (correction->cheat_death_consumed) {
        auto& memory = ProcessMemory::Instance();
        float life_current = 0.0f;
        float life_max = 0.0f;
        if (memory.TryReadField(
                gameplay_state.progression_runtime_state_address,
                kProgressionHpOffset,
                &life_current) &&
            memory.TryReadField(
                gameplay_state.progression_runtime_state_address,
                kProgressionMaxHpOffset,
                &life_max) &&
            std::isfinite(life_current) &&
            std::isfinite(life_max) &&
            life_max > 0.0f &&
            life_current >= 0.0f &&
            life_current <= life_max) {
            correction->native_life_valid = true;
            correction->life_current = life_current;
            correction->life_max = life_max;
        }
    }
    return true;
}

bool HasAuthoritativeHagathaRuntimeStateChangedInternal(
    std::uint64_t target_participant_id) {
    if (!g_local_transport.is_host || target_participant_id == 0 ||
        target_participant_id == g_local_transport.local_peer_id) {
        return false;
    }

    const auto snapshot = SnapshotRuntimeState();
    const auto* participant = FindParticipant(snapshot, target_participant_id);
    SDModParticipantGameplayState gameplay_state;
    ParticipantHagathaPerkState native;
    if (participant == nullptr ||
        !participant->owned_progression.hagatha_perks.valid ||
        !TryGetParticipantGameplayState(
            target_participant_id,
            &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0 ||
        !TryReadNativeHagathaPerkState(
            gameplay_state.progression_runtime_state_address,
            &native) ||
        !HagathaPerkIdentityEqual(
            native,
            participant->owned_progression.hagatha_perks)) {
        return false;
    }

    const auto& replicated = participant->owned_progression.hagatha_perks;
    return native.cheat_death_charges < replicated.cheat_death_charges ||
           (!native.serendipity_active && replicated.serendipity_active) ||
           (!native.reverie_active && replicated.reverie_active);
}

bool ApplyAuthoritativeHagathaRuntimeCorrection(
    uintptr_t progression_address,
    const ParticipantVitalsCorrectionPacket& packet) {
    if ((packet.correction_flags &
         ParticipantVitalsCorrectionFlagHagathaRuntimeState) == 0) {
        return true;
    }
    if (progression_address == 0 ||
        packet.hagatha_runtime_valid == 0 ||
        packet.hagatha_cheat_death_charges < 0 ||
        packet.hagatha_cheat_death_charges > 1 ||
        packet.hagatha_serendipity_active > 1 ||
        packet.hagatha_reverie_active > 1) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            progression_address,
            kProgressionCheatDeathChargesOffset,
            packet.hagatha_cheat_death_charges) ||
        !memory.TryWriteField(
            progression_address,
            kProgressionSerendipityActiveOffset,
            packet.hagatha_serendipity_active) ||
        !memory.TryWriteField(
            progression_address,
            kProgressionReverieActiveOffset,
            packet.hagatha_reverie_active)) {
        return false;
    }
    DWORD exception_code = 0;
    if (!CallNativeActorProgressionRefreshForHagatha(
            progression_address,
            &exception_code)) {
        return false;
    }

    ParticipantHagathaPerkState verified;
    if (!TryReadNativeHagathaPerkState(progression_address, &verified) ||
        verified.cheat_death_charges !=
            packet.hagatha_cheat_death_charges ||
        verified.serendipity_active !=
            (packet.hagatha_serendipity_active != 0) ||
        verified.reverie_active !=
            (packet.hagatha_reverie_active != 0)) {
        return false;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = FindLocalParticipant(state);
        if (local == nullptr ||
            !local->owned_progression.hagatha_perks.valid) {
            return;
        }
        auto& perks = local->owned_progression.hagatha_perks;
        const bool changed =
            perks.cheat_death_charges !=
                packet.hagatha_cheat_death_charges ||
            perks.serendipity_active !=
                (packet.hagatha_serendipity_active != 0) ||
            perks.reverie_active !=
                (packet.hagatha_reverie_active != 0);
        perks.cheat_death_charges =
            packet.hagatha_cheat_death_charges;
        perks.serendipity_active =
            packet.hagatha_serendipity_active != 0;
        perks.reverie_active = packet.hagatha_reverie_active != 0;
        if (changed) {
            local->owned_progression.hagatha_perk_revision += 1;
        }
    });
    return true;
}
