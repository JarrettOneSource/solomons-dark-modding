using CreateTickFn = void(__thiscall*)(void* owner);
using CreateClickFn =
    void(__thiscall*)(void* owner, std::int32_t x, std::int32_t y);

bool IsCreateOwner(std::uintptr_t owner_address) {
    if (owner_address == 0 ||
        g_join_flow.create_vftable_address == 0) {
        return false;
    }
    std::uintptr_t vftable = 0;
    return ProcessMemory::Instance().TryReadField(
               owner_address,
               0,
               &vftable) &&
           vftable == g_join_flow.create_vftable_address;
}

bool TryReadCreateSelections(
    std::uintptr_t owner_address,
    std::uint32_t* element_selected,
    std::uint32_t* discipline_selected) {
    if (element_selected == nullptr ||
        discipline_selected == nullptr ||
        !IsCreateOwner(owner_address)) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               owner_address,
               kCreateElementSelectedOffset,
               element_selected) &&
           memory.TryReadField(
               owner_address,
               kCreateDisciplineSelectedOffset,
               discipline_selected);
}

bool IsCompletedCreateSelection(std::uint32_t selection, std::uint32_t count) {
    return selection < count;
}

void SetLocalLoadoutPickStateUnlocked(
    multiplayer::LoadoutPickState pick_state) {
    const auto generation = g_join_flow.loadout_pick_generation;
    multiplayer::UpdateRuntimeState(
        [&](multiplayer::RuntimeState& runtime) {
            auto* local =
                multiplayer::UpsertLocalParticipant(runtime);
            if (local == nullptr) {
                return;
            }
            local->loadout_pick_generation = generation;
            local->loadout_pick_state = pick_state;
        });
}

void BeginNextLoadoutGenerationUnlocked(std::string_view source) {
    if (g_join_flow.loadout_pick_generation ==
        (std::numeric_limits<std::uint32_t>::max)()) {
        g_join_flow.loadout_pick_generation = 1;
    } else {
        ++g_join_flow.loadout_pick_generation;
    }
    g_join_flow.create_pick_committed = false;
    g_join_flow.retained_preselection_active = false;
    g_join_flow.active_create_owner_address = 0;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_automation_enabled = false;
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);
    Log(
        "Multiplayer loadout generation advanced. generation=" +
        std::to_string(g_join_flow.loadout_pick_generation) +
        " source=" + std::string(source));
}

const multiplayer::ParticipantInfo* FindAuthorityLoadoutParticipant(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host ||
        multiplayer::IsLocalTransportHost()) {
        return multiplayer::FindLocalParticipant(runtime);
    }
    const auto authority_id =
        runtime.steam_host_id != 0
        ? runtime.steam_host_id
        : multiplayer::GetLocalTransportAuthorityParticipantId();
    if (authority_id == 0) {
        return nullptr;
    }
    const auto authority = std::find_if(
        runtime.participants.begin(),
        runtime.participants.end(),
        [&](const multiplayer::ParticipantInfo& participant) {
            return participant.participant_id == authority_id ||
                   participant.steam_id == authority_id;
        });
    return authority == runtime.participants.end()
        ? nullptr
        : &*authority;
}

bool IsAuthorityWorldReadyForCurrentLoadout(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host ||
        multiplayer::IsLocalTransportHost()) {
        return true;
    }
    const auto* authority =
        FindAuthorityLoadoutParticipant(runtime);
    return authority != nullptr &&
           authority->loadout_pick_generation ==
               g_join_flow.loadout_pick_generation &&
           authority->loadout_pick_state ==
               multiplayer::LoadoutPickState::WorldReady;
}

void ReconcileAuthorityLoadoutGenerationUnlocked(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host ||
        multiplayer::IsLocalTransportHost()) {
        return;
    }
    const auto* authority =
        FindAuthorityLoadoutParticipant(runtime);
    if (authority == nullptr ||
        authority->loadout_pick_generation == 0) {
        return;
    }
    const auto authority_generation =
        authority->loadout_pick_generation;
    if (g_join_flow.observed_authority_loadout_generation == 0) {
        g_join_flow.observed_authority_loadout_generation =
            authority_generation;
        if (authority_generation !=
            g_join_flow.loadout_pick_generation) {
            g_join_flow.loadout_pick_generation =
                authority_generation;
            SetLocalLoadoutPickStateUnlocked(
                g_join_flow.create_pick_committed
                    ? multiplayer::LoadoutPickState::Picked
                    : multiplayer::LoadoutPickState::Picking);
        }
        return;
    }
    if (authority_generation ==
        g_join_flow.observed_authority_loadout_generation) {
        return;
    }

    g_join_flow.observed_authority_loadout_generation =
        authority_generation;
    g_join_flow.loadout_pick_generation = authority_generation;
    g_join_flow.create_pick_committed = false;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_automation_enabled = false;
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);
    CancelLoadingScreen();
    Log(
        "Multiplayer client adopted the host's next loadout generation. "
        "generation=" +
        std::to_string(authority_generation));
}

void MarkLocalLoadoutWorldReadyUnlocked() {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local =
        multiplayer::FindLocalParticipant(runtime);
    if (local != nullptr &&
        local->loadout_pick_generation ==
            g_join_flow.loadout_pick_generation &&
        local->loadout_pick_state ==
            multiplayer::LoadoutPickState::WorldReady) {
        return;
    }
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::WorldReady);
    Log(
        "Multiplayer loadout world is ready. generation=" +
        std::to_string(g_join_flow.loadout_pick_generation));
}

void ObserveCreateOwnerUnlocked(std::uintptr_t owner_address) {
    if (!IsCreateOwner(owner_address) ||
        owner_address ==
            g_join_flow.active_create_owner_address) {
        return;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local =
        multiplayer::FindLocalParticipant(runtime);
    if (local != nullptr &&
        local->loadout_pick_generation ==
            g_join_flow.loadout_pick_generation &&
        local->loadout_pick_state ==
            multiplayer::LoadoutPickState::WorldReady) {
        BeginNextLoadoutGenerationUnlocked(
            "fresh_create_surface");
    }

    g_join_flow.active_create_owner_address = owner_address;
    g_join_flow.create_pick_committed = false;
    g_join_flow.retained_preselection_active = false;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_automation_enabled =
        !g_join_flow.quick_start_loadout_automation_consumed &&
        g_join_flow.loadout_pick_generation == 1 &&
        !g_join_flow.quick_start_element_action_id.empty() &&
        !g_join_flow.quick_start_discipline_action_id.empty();
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);

    std::uint32_t element_selected = kCreateSelectionUnset;
    std::uint32_t discipline_selected = kCreateSelectionUnset;
    if (TryReadCreateSelections(
            owner_address,
            &element_selected,
            &discipline_selected)) {
        if (element_selected == kCreateSelectionUnset &&
            discipline_selected == kCreateSelectionUnset &&
            IsCompletedCreateSelection(
                g_join_flow.last_committed_element,
                kCreateElementPointCount) &&
            IsCompletedCreateSelection(
                g_join_flow.last_committed_discipline,
                kCreateDisciplinePointCount)) {
            auto& memory = ProcessMemory::Instance();
            const bool element_written = memory.TryWriteField(
                owner_address,
                kCreateElementSelectedOffset,
                g_join_flow.last_committed_element);
            const bool discipline_written = memory.TryWriteField(
                owner_address,
                kCreateDisciplineSelectedOffset,
                g_join_flow.last_committed_discipline);
            if (element_written && discipline_written) {
                element_selected = g_join_flow.last_committed_element;
                discipline_selected =
                    g_join_flow.last_committed_discipline;
                g_join_flow.retained_preselection_active = true;
            } else {
                (void)memory.TryWriteField(
                    owner_address,
                    kCreateElementSelectedOffset,
                    kCreateSelectionUnset);
                (void)memory.TryWriteField(
                    owner_address,
                    kCreateDisciplineSelectedOffset,
                    kCreateSelectionUnset);
            }
        }
        Log(
            "Multiplayer loadout picker entered. generation=" +
            std::to_string(g_join_flow.loadout_pick_generation) +
            " preselected_element=" +
            std::to_string(element_selected) +
            " preselected_discipline=" +
            std::to_string(discipline_selected));
    }
}

template <std::size_t PointCount>
bool IsCreatePointHit(
    std::uintptr_t owner_address,
    std::size_t point_list_offset,
    std::int32_t x,
    std::int32_t y) {
    auto& memory = ProcessMemory::Instance();
    for (std::size_t index = 0; index < PointCount; ++index) {
        const auto point_address =
            owner_address + point_list_offset +
            index * kCreatePointStride;
        float point_x = 0.0f;
        float point_y = 0.0f;
        if (!memory.TryReadValue(point_address, &point_x) ||
            !memory.TryReadValue(
                point_address + sizeof(float),
                &point_y) ||
            !std::isfinite(point_x) ||
            !std::isfinite(point_y)) {
            continue;
        }
        const auto delta_x =
            static_cast<float>(x) - point_x;
        const auto delta_y =
            static_cast<float>(y) - point_y;
        if (delta_x * delta_x + delta_y * delta_y <=
            kCreateSelectionRadius * kCreateSelectionRadius) {
            return true;
        }
    }
    return false;
}

bool TryReadCreatePoint(
    std::uintptr_t owner_address,
    std::size_t point_list_offset,
    std::size_t point_index,
    std::int32_t* x,
    std::int32_t* y) {
    if (x == nullptr || y == nullptr) {
        return false;
    }
    const auto point_address =
        owner_address + point_list_offset +
        point_index * kCreatePointStride;
    float point_x = 0.0f;
    float point_y = 0.0f;
    if (!ProcessMemory::Instance().TryReadValue(
            point_address,
            &point_x) ||
        !ProcessMemory::Instance().TryReadValue(
            point_address + sizeof(float),
            &point_y) ||
        !std::isfinite(point_x) ||
        !std::isfinite(point_y)) {
        return false;
    }
    *x = static_cast<std::int32_t>(point_x);
    *y = static_cast<std::int32_t>(point_y);
    return true;
}

void __fastcall HookCreateTick(
    void* owner,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<CreateTickFn>(
        g_join_flow.create_tick_hook);
    if (original == nullptr) {
        return;
    }

    const auto owner_address =
        reinterpret_cast<std::uintptr_t>(owner);
    bool discipline_masked = false;
    bool expose_retained_choices = false;
    std::uint32_t retained_discipline =
        kCreateSelectionUnset;
    {
        std::scoped_lock lock(g_join_flow.mutex);
        if (g_join_flow.enabled &&
            IsCreateOwner(owner_address)) {
            ObserveCreateOwnerUnlocked(owner_address);
            const auto runtime =
                multiplayer::SnapshotRuntimeState();
            ReconcileAuthorityLoadoutGenerationUnlocked(runtime);
            const bool gate_world_creation =
                !g_join_flow.create_pick_committed ||
                !IsAuthorityWorldReadyForCurrentLoadout(runtime);
            expose_retained_choices =
                g_join_flow.retained_preselection_active &&
                !g_join_flow.create_pick_committed;
            if (gate_world_creation &&
                ProcessMemory::Instance().TryReadField(
                    owner_address,
                    kCreateDisciplineSelectedOffset,
                    &retained_discipline) &&
                retained_discipline != kCreateSelectionUnset) {
                discipline_masked =
                    ProcessMemory::Instance().TryWriteField(
                        owner_address,
                        kCreateDisciplineSelectedOffset,
                        kCreateSelectionUnset);
            }
        }
    }

    original(owner);

    if (discipline_masked) {
        (void)ProcessMemory::Instance().TryWriteField(
            owner_address,
            kCreateDisciplineSelectedOffset,
            retained_discipline);
    }
    if (expose_retained_choices) {
        (void)ProcessMemory::Instance().TryWriteField(
            owner_address,
            kCreateElementEnabledOffset,
            std::uint32_t{1});
        (void)ProcessMemory::Instance().TryWriteField(
            owner_address,
            kCreateDisciplineEnabledOffset,
            std::uint32_t{1});
    }
}

void __fastcall HookCreateClick(
    void* owner,
    void* /*unused_edx*/,
    std::int32_t x,
    std::int32_t y) {
    const auto original = GetX86HookTrampoline<CreateClickFn>(
        g_join_flow.create_click_hook);
    if (original == nullptr) {
        return;
    }

    const auto owner_address =
        reinterpret_cast<std::uintptr_t>(owner);
    bool valid_selection_attempt = false;
    bool retained_element_change = false;
    bool replay_retained_element = false;
    std::int32_t retained_element_x = 0;
    std::int32_t retained_element_y = 0;
    {
        std::scoped_lock lock(g_join_flow.mutex);
        if (g_join_flow.enabled &&
            IsCreateOwner(owner_address)) {
            ObserveCreateOwnerUnlocked(owner_address);
            std::uint32_t element_selected =
                kCreateSelectionUnset;
            std::uint32_t discipline_selected =
                kCreateSelectionUnset;
            if (TryReadCreateSelections(
                    owner_address,
                    &element_selected,
                    &discipline_selected) &&
                IsCompletedCreateSelection(
                    element_selected,
                    kCreateElementPointCount) &&
                IsCompletedCreateSelection(
                    discipline_selected,
                    kCreateDisciplinePointCount)) {
                if (IsCreatePointHit<kCreateElementPointCount>(
                        owner_address,
                        kCreateElementPointListOffset,
                        x,
                        y)) {
                    retained_element_change =
                        g_join_flow.retained_preselection_active;
                    valid_selection_attempt =
                        ProcessMemory::Instance().TryWriteField(
                            owner_address,
                            kCreateElementSelectedOffset,
                            kCreateSelectionUnset);
                } else if (
                    IsCreatePointHit<kCreateDisciplinePointCount>(
                        owner_address,
                        kCreateDisciplinePointListOffset,
                        x,
                        y)) {
                    if (g_join_flow.retained_preselection_active) {
                        valid_selection_attempt =
                            TryReadCreatePoint(
                                owner_address,
                                kCreateElementPointListOffset,
                                element_selected,
                                &retained_element_x,
                                &retained_element_y) &&
                            ProcessMemory::Instance().TryWriteField(
                                owner_address,
                                kCreateElementEnabledOffset,
                                std::uint32_t{1}) &&
                            ProcessMemory::Instance().TryWriteField(
                                owner_address,
                                kCreateElementSelectedOffset,
                                kCreateSelectionUnset) &&
                            ProcessMemory::Instance().TryWriteField(
                                owner_address,
                                kCreateDisciplineEnabledOffset,
                                std::uint32_t{0}) &&
                            ProcessMemory::Instance().TryWriteField(
                                owner_address,
                                kCreateDisciplineSelectedOffset,
                                kCreateSelectionUnset);
                        replay_retained_element =
                            valid_selection_attempt;
                    } else {
                        valid_selection_attempt =
                            ProcessMemory::Instance().TryWriteField(
                                owner_address,
                                kCreateDisciplineSelectedOffset,
                                kCreateSelectionUnset);
                    }
                }
            } else {
                valid_selection_attempt = true;
            }
        }
    }

    if (replay_retained_element) {
        original(
            owner,
            retained_element_x,
            retained_element_y);
        if (!ProcessMemory::Instance().TryWriteField(
                owner_address,
                kCreateDisciplineEnabledOffset,
                std::uint32_t{1})) {
            return;
        }
    }
    original(owner, x, y);

    std::scoped_lock lock(g_join_flow.mutex);
    if (!g_join_flow.enabled ||
        !valid_selection_attempt ||
        !IsCreateOwner(owner_address)) {
        return;
    }
    if (retained_element_change) {
        (void)ProcessMemory::Instance().TryWriteField(
            owner_address,
            kCreateDisciplineSelectedOffset,
            kCreateSelectionUnset);
        g_join_flow.retained_preselection_active = false;
    }
    std::uint32_t element_selected = kCreateSelectionUnset;
    std::uint32_t discipline_selected = kCreateSelectionUnset;
    if (!TryReadCreateSelections(
            owner_address,
            &element_selected,
            &discipline_selected) ||
        !IsCompletedCreateSelection(
            element_selected,
            kCreateElementPointCount) ||
        !IsCompletedCreateSelection(
            discipline_selected,
            kCreateDisciplinePointCount)) {
        return;
    }

    g_join_flow.create_pick_committed = true;
    g_join_flow.retained_preselection_active = false;
    g_join_flow.last_committed_element = element_selected;
    g_join_flow.last_committed_discipline = discipline_selected;
    g_join_flow.quick_start_loadout_automation_consumed = true;
    g_join_flow.quick_start_loadout_automation_enabled = false;
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picked);
    const auto runtime = multiplayer::SnapshotRuntimeState();
    Log(
        "Multiplayer loadout pick committed. generation=" +
        std::to_string(g_join_flow.loadout_pick_generation) +
        " element=" + std::to_string(element_selected) +
        " discipline=" +
        std::to_string(discipline_selected));
    if (!IsAuthorityWorldReadyForCurrentLoadout(runtime)) {
        SetPhaseUnlocked(
            JoinFlowPhase::WaitingForHostLoadout);
    }
}
