enum class NativeMinionTerminalReason : std::uint8_t {
    NativeDeath =
        multiplayer::NativeMinionTerminalReasonNativeDeath,
    Expired =
        multiplayer::NativeMinionTerminalReasonExpired,
    Replaced =
        multiplayer::NativeMinionTerminalReasonReplaced,
    OwnerDeath =
        multiplayer::NativeMinionTerminalReasonOwnerDeath,
    OwnerDisconnected =
        multiplayer::NativeMinionTerminalReasonOwnerDisconnected,
    ExplicitRetirement =
        multiplayer::NativeMinionTerminalReasonExplicitRetirement,
    SceneTeardown =
        multiplayer::NativeMinionTerminalReasonSceneTeardown,
};

enum class NativeMinionStateShape : std::uint8_t {
    GoodImp,
    Leviathan,
    Golem,
};

struct NativeMinionDescriptor {
    std::uint32_t native_type_id;
    SDModNativeMinionKind kind;
    NativeMinionStateShape state_shape;
    uintptr_t* tick_address;
    bool damageable;
};

constexpr std::uint32_t kGoodImpNativeTypeId = 0x03ED;
constexpr std::uint32_t kLeviathanNativeTypeId = 0x07F2;
constexpr std::uint32_t kGolemNativeTypeId = 0x07F4;
constexpr std::uint32_t kGolemKnockbackNativeTypeId = 0x07E9;
constexpr std::size_t kNativeMinionHookMinimumPatchSize = 5;
constexpr std::uint64_t
    kNativeMinionObserverBindingGraceMs = 1500;

const std::array<NativeMinionDescriptor, 3> kNativeMinionDescriptors = {{
    {
        kGoodImpNativeTypeId,
        SDModNativeMinionKind::GoodImp,
        NativeMinionStateShape::GoodImp,
        &kGoodImpTick,
        false,
    },
    {
        kLeviathanNativeTypeId,
        SDModNativeMinionKind::Leviathan,
        NativeMinionStateShape::Leviathan,
        &kLeviathanTick,
        false,
    },
    {
        kGolemNativeTypeId,
        SDModNativeMinionKind::Golem,
        NativeMinionStateShape::Golem,
        &kGolemTick,
        true,
    },
}};

std::recursive_mutex g_native_minion_state_mutex;
std::unordered_map<uintptr_t, std::uint64_t>
    g_native_minion_owner_by_actor;
std::unordered_map<uintptr_t, std::uint64_t>
    g_native_minion_first_observed_ms_by_actor;
std::unordered_map<uintptr_t, std::uint64_t>
    g_native_minion_knockback_owner_by_actor;
thread_local std::uint64_t g_authoritative_native_minion_tick_owner = 0;
thread_local std::uint64_t
    g_native_minion_creation_owner_participant_id = 0;
thread_local std::uint32_t
    g_native_minion_replacement_dispatch_depth = 0;

std::uint64_t ResolveNativeMinionCreationOwnerForCaster(
    uintptr_t caster_actor_address) {
    if (caster_actor_address == 0) {
        return 0;
    }

    {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        const auto* binding =
            FindParticipantEntityForActor(caster_actor_address);
        if (binding != nullptr &&
            IsWizardParticipantKind(binding->kind)) {
            return binding->bot_id;
        }
    }

    SDModPlayerState local_player;
    const auto local_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    if (local_participant_id != 0 &&
        TryGetPlayerState(&local_player) &&
        local_player.valid &&
        local_player.actor_address == caster_actor_address) {
        return local_participant_id;
    }
    return 0;
}

struct ScopedNativeMinionSummonDispatch {
    std::uint64_t previous_creation_owner_participant_id = 0;
    bool summon_dispatch = false;
    bool replacement_dispatch = false;

    ScopedNativeMinionSummonDispatch(
        std::int32_t skill_entry_index,
        uintptr_t caster_actor_address)
        : previous_creation_owner_participant_id(
              g_native_minion_creation_owner_participant_id),
          summon_dispatch(skill_entry_index == 0x2D),
          replacement_dispatch(
              summon_dispatch &&
              multiplayer::IsLocalTransportHost()) {
        if (summon_dispatch) {
            g_native_minion_creation_owner_participant_id =
                ResolveNativeMinionCreationOwnerForCaster(
                    caster_actor_address);
        }
        if (replacement_dispatch) {
            ++g_native_minion_replacement_dispatch_depth;
        }
    }

    ScopedNativeMinionSummonDispatch(
        const ScopedNativeMinionSummonDispatch&) = delete;
    ScopedNativeMinionSummonDispatch& operator=(
        const ScopedNativeMinionSummonDispatch&) = delete;

    ~ScopedNativeMinionSummonDispatch() {
        if (replacement_dispatch) {
            --g_native_minion_replacement_dispatch_depth;
        }
        if (summon_dispatch) {
            g_native_minion_creation_owner_participant_id =
                previous_creation_owner_participant_id;
        }
    }
};

multiplayer::NativeMinionTerminalReason
CurrentGolemTerminalReason() {
    return g_native_minion_replacement_dispatch_depth != 0
        ? multiplayer::NativeMinionTerminalReasonReplaced
        : multiplayer::NativeMinionTerminalReasonNativeDeath;
}

const NativeMinionDescriptor* FindNativeMinionDescriptor(
    std::uint32_t native_type_id) {
    const auto found = std::find_if(
        kNativeMinionDescriptors.begin(),
        kNativeMinionDescriptors.end(),
        [&](const NativeMinionDescriptor& descriptor) {
            return descriptor.native_type_id == native_type_id;
        });
    return found == kNativeMinionDescriptors.end()
        ? nullptr
        : &*found;
}

bool TryReadNativeMinionType(
    uintptr_t actor_address,
    std::uint32_t* native_type_id) {
    if (native_type_id != nullptr) {
        *native_type_id = 0;
    }
    return actor_address != 0 &&
        native_type_id != nullptr &&
        kGameObjectTypeIdOffset != 0 &&
        ProcessMemory::Instance().TryReadField(
            actor_address,
            kGameObjectTypeIdOffset,
            native_type_id) &&
        FindNativeMinionDescriptor(*native_type_id) != nullptr;
}

void RememberNativeMinionOwner(
    uintptr_t actor_address,
    std::uint64_t owner_participant_id) {
    if (actor_address == 0 || owner_participant_id == 0) {
        return;
    }
    std::lock_guard<std::recursive_mutex> lock(
        g_native_minion_state_mutex);
    g_native_minion_owner_by_actor[actor_address] =
        owner_participant_id;
    g_native_minion_first_observed_ms_by_actor
        .try_emplace(
            actor_address,
            static_cast<std::uint64_t>(
                GetTickCount64()));
}

void ForgetNativeMinionActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }
    std::lock_guard<std::recursive_mutex> lock(
        g_native_minion_state_mutex);
    g_native_minion_owner_by_actor.erase(actor_address);
    g_native_minion_first_observed_ms_by_actor.erase(
        actor_address);
    g_native_minion_knockback_owner_by_actor.erase(actor_address);
}
