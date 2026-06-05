constexpr std::uint32_t kReplicatedLootOrbNativeTypeId = 0x07DB;
constexpr std::uint32_t kReplicatedLootGoldNativeTypeId = 0x07DC;
constexpr std::uint32_t kReplicatedLootItemDropNativeTypeId = 0x07DD;
constexpr std::size_t kReplicatedGoldAmountTierOffset = 0x13C;
constexpr std::size_t kReplicatedGoldAmountOffset = 0x140;
constexpr std::size_t kReplicatedGoldLifetimeOffset = 0x144;
constexpr std::size_t kReplicatedGoldActiveOffset = 0x148;
constexpr std::size_t kReplicatedOrbResourceKindOffset = 0x13C;
constexpr std::size_t kReplicatedOrbValueOffset = 0x140;
constexpr std::size_t kReplicatedOrbLifetimeOffset = 0x144;
constexpr std::size_t kReplicatedOrbMotionOffset = 0x148;
constexpr std::size_t kReplicatedOrbProgressOffset = 0x14C;
constexpr std::uint32_t kReplicatedLootDefaultLifetime = 900;
constexpr float kReplicatedLootSpawnMatchMaxDistance = 192.0f;
constexpr float kReplicatedLootParkBase = 900000.0f;

struct ReplicatedLootPresentationBinding {
    std::uint64_t network_drop_id = 0;
    std::uint64_t authority_participant_id = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t native_type_id = 0;
    multiplayer::LootDropKind drop_kind = multiplayer::LootDropKind::Unknown;
    uintptr_t actor_address = 0;
    bool active = false;
    std::int32_t amount = 0;
    std::int32_t amount_tier = 0;
    float value = 0.0f;
    float x = 0.0f;
    float y = 0.0f;
    std::uint64_t last_seen_ms = 0;
};

std::mutex g_replicated_loot_presentation_mutex;
std::vector<ReplicatedLootPresentationBinding> g_replicated_loot_presentations;
std::unordered_set<uintptr_t> g_client_non_authoritative_loot_suppressed_actors;

bool IsReplicatedLootPresentationActorInternal(uintptr_t actor_address);

bool IsSupportedReplicatedLootPresentationKind(const multiplayer::LootDropSnapshot& drop) {
    if (!drop.active || drop.network_drop_id == 0) {
        return false;
    }
    if (drop.drop_kind == multiplayer::LootDropKind::Gold) {
        return drop.native_type_id == kReplicatedLootGoldNativeTypeId && drop.amount > 0;
    }
    if (drop.drop_kind == multiplayer::LootDropKind::Orb) {
        return drop.native_type_id == kReplicatedLootOrbNativeTypeId &&
               std::isfinite(drop.value) &&
               drop.value > 0.0f &&
               (drop.amount_tier == 0 || drop.amount_tier == 1);
    }
    return false;
}

bool IsLootDropNativeTypeId(std::uint32_t native_type_id) {
    return native_type_id == kReplicatedLootGoldNativeTypeId ||
           native_type_id == kReplicatedLootOrbNativeTypeId ||
           native_type_id == kReplicatedLootItemDropNativeTypeId;
}

multiplayer::LootDropKind LootDropKindFromNativeTypeId(std::uint32_t native_type_id) {
    if (native_type_id == kReplicatedLootGoldNativeTypeId) {
        return multiplayer::LootDropKind::Gold;
    }
    if (native_type_id == kReplicatedLootOrbNativeTypeId) {
        return multiplayer::LootDropKind::Orb;
    }
    if (native_type_id == kReplicatedLootItemDropNativeTypeId) {
        return multiplayer::LootDropKind::Item;
    }
    return multiplayer::LootDropKind::Unknown;
}

ReplicatedLootPresentationBinding ToReplicatedLootPresentationBinding(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    const multiplayer::LootDropSnapshot& drop,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    ReplicatedLootPresentationBinding binding;
    binding.network_drop_id = drop.network_drop_id;
    binding.authority_participant_id = snapshot.authority_participant_id;
    binding.scene_epoch = snapshot.scene_epoch;
    binding.run_nonce = snapshot.run_nonce;
    binding.native_type_id = drop.native_type_id;
    binding.drop_kind = drop.drop_kind;
    binding.actor_address = actor_address;
    binding.active = drop.active;
    binding.amount = drop.amount;
    binding.amount_tier = drop.amount_tier;
    binding.value = drop.value;
    binding.x = drop.position_x;
    binding.y = drop.position_y;
    binding.last_seen_ms = now_ms;
    return binding;
}

SDModReplicatedLootPresentationState ToPublicReplicatedLootPresentationState(
    const ReplicatedLootPresentationBinding& binding) {
    SDModReplicatedLootPresentationState state;
    state.valid = binding.network_drop_id != 0 && binding.actor_address != 0;
    state.network_drop_id = binding.network_drop_id;
    state.authority_participant_id = binding.authority_participant_id;
    state.scene_epoch = binding.scene_epoch;
    state.run_nonce = binding.run_nonce;
    state.native_type_id = binding.native_type_id;
    state.drop_kind = binding.drop_kind;
    state.actor_address = binding.actor_address;
    state.active = binding.active;
    state.amount = binding.amount;
    state.amount_tier = binding.amount_tier;
    state.value = binding.value;
    state.x = binding.x;
    state.y = binding.y;
    state.last_seen_ms = binding.last_seen_ms;
    return state;
}

ReplicatedLootPresentationBinding* FindReplicatedLootPresentationBindingLocked(
    std::uint64_t network_drop_id) {
    const auto it = std::find_if(
        g_replicated_loot_presentations.begin(),
        g_replicated_loot_presentations.end(),
        [&](const ReplicatedLootPresentationBinding& binding) {
            return binding.network_drop_id == network_drop_id;
        });
    return it == g_replicated_loot_presentations.end() ? nullptr : &*it;
}

bool TryListSceneActorsByType(
    std::uint32_t native_type_id,
    std::vector<SDModSceneActorState>* actors) {
    if (actors == nullptr) {
        return false;
    }
    actors->clear();
    std::vector<SDModSceneActorState> all_actors;
    if (!TryListSceneActors(&all_actors)) {
        return false;
    }
    for (const auto& actor : all_actors) {
        if (actor.valid && actor.actor_address != 0 && actor.object_type_id == native_type_id) {
            actors->push_back(actor);
        }
    }
    return true;
}

bool IsSceneActorAddressPresent(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }
    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }
    return std::find_if(
               actors.begin(),
               actors.end(),
               [&](const SDModSceneActorState& actor) {
                   return actor.valid && actor.actor_address == actor_address;
               }) != actors.end();
}

bool WriteReplicatedLootDropFields(
    uintptr_t actor_address,
    const multiplayer::LootDropSnapshot& drop,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || !std::isfinite(drop.position_x) || !std::isfinite(drop.position_y)) {
        if (error_message != nullptr) {
            *error_message = "replicated loot field write received an invalid actor or position";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote =
        memory.TryWriteField(actor_address, kActorPositionXOffset, drop.position_x) &&
        memory.TryWriteField(actor_address, kActorPositionYOffset, drop.position_y);

    const auto lifetime =
        drop.lifetime != 0 ? drop.lifetime : kReplicatedLootDefaultLifetime;
    if (drop.drop_kind == multiplayer::LootDropKind::Gold) {
        const auto tier = static_cast<std::uint8_t>((std::max)(0, drop.amount_tier));
        const auto amount = static_cast<std::uint32_t>((std::max)(1, drop.amount));
        const auto presentation_state = drop.presentation_state;
        wrote = memory.TryWriteField(actor_address, kReplicatedGoldAmountTierOffset, tier) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedGoldAmountOffset, amount) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedGoldLifetimeOffset, lifetime) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedGoldActiveOffset, presentation_state) && wrote;
    } else if (drop.drop_kind == multiplayer::LootDropKind::Orb) {
        const auto resource_kind = static_cast<std::uint8_t>(drop.amount_tier == 1 ? 1 : 0);
        const float raw_value = (std::max)(drop.value, 1.0f);
        const float motion = std::isfinite(drop.motion) ? drop.motion : 0.0f;
        const float progress = std::isfinite(drop.progress) ? drop.progress : 0.0f;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbResourceKindOffset, resource_kind) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbValueOffset, raw_value) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbLifetimeOffset, lifetime) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbMotionOffset, motion) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbProgressOffset, progress) && wrote;
    }

    if (!wrote && error_message != nullptr) {
        *error_message = "failed to seed replicated loot native fields";
    }
    return wrote;
}

bool TryFindSpawnedReplicatedLootActor(
    std::uint32_t native_type_id,
    const std::unordered_set<uintptr_t>& previous_actor_addresses,
    float x,
    float y,
    uintptr_t* actor_address) {
    if (actor_address == nullptr) {
        return false;
    }
    *actor_address = 0;

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActorsByType(native_type_id, &actors)) {
        return false;
    }

    float best_distance2 = kReplicatedLootSpawnMatchMaxDistance * kReplicatedLootSpawnMatchMaxDistance;
    bool found = false;
    for (const auto& actor : actors) {
        if (previous_actor_addresses.find(actor.actor_address) != previous_actor_addresses.end()) {
            continue;
        }
        const float dx = actor.x - x;
        const float dy = actor.y - y;
        const float distance2 = dx * dx + dy * dy;
        if (distance2 <= best_distance2) {
            best_distance2 = distance2;
            *actor_address = actor.actor_address;
            found = true;
        }
    }
    if (found) {
        return true;
    }

    for (const auto& actor : actors) {
        bool already_bound = false;
        {
            std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
            already_bound = std::find_if(
                g_replicated_loot_presentations.begin(),
                g_replicated_loot_presentations.end(),
                [&](const ReplicatedLootPresentationBinding& binding) {
                    return binding.actor_address == actor.actor_address;
                }) != g_replicated_loot_presentations.end();
        }
        if (already_bound) {
            continue;
        }
        const float dx = actor.x - x;
        const float dy = actor.y - y;
        const float distance2 = dx * dx + dy * dy;
        if (distance2 <= best_distance2) {
            best_distance2 = distance2;
            *actor_address = actor.actor_address;
            found = true;
        }
    }
    return found;
}

bool SpawnReplicatedLootPresentationActor(
    const multiplayer::LootDropSnapshot& drop,
    uintptr_t* actor_address,
    std::string* error_message) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == nullptr || !IsSupportedReplicatedLootPresentationKind(drop)) {
        if (error_message != nullptr) {
            *error_message = "unsupported replicated loot drop";
        }
        return false;
    }

    std::vector<SDModSceneActorState> before_actors;
    std::unordered_set<uintptr_t> before_addresses;
    if (TryListSceneActorsByType(drop.native_type_id, &before_actors)) {
        for (const auto& actor : before_actors) {
            before_addresses.insert(actor.actor_address);
        }
    }

    std::string spawn_kind;
    int spawn_amount = 1;
    if (drop.drop_kind == multiplayer::LootDropKind::Gold) {
        spawn_kind = "gold";
        spawn_amount = (std::max)(1, drop.amount);
    } else {
        spawn_kind = drop.amount_tier == 1 ? "mana_orb" : "health_orb";
        spawn_amount = static_cast<int>((std::max)(1.0f, std::round(drop.value)));
    }

    std::string spawn_error;
    if (!ExecuteSpawnRewardNow(
            spawn_kind,
            spawn_amount,
            drop.position_x,
            drop.position_y,
            &spawn_error)) {
        if (error_message != nullptr) {
            *error_message = "native reward spawn failed: " + spawn_error;
        }
        return false;
    }

    uintptr_t spawned_actor = 0;
    if (!TryFindSpawnedReplicatedLootActor(
            drop.native_type_id,
            before_addresses,
            drop.position_x,
            drop.position_y,
            &spawned_actor) ||
        spawned_actor == 0) {
        if (error_message != nullptr) {
            *error_message = "native reward spawn did not expose a matching scene actor";
        }
        return false;
    }

    if (!WriteReplicatedLootDropFields(spawned_actor, drop, error_message)) {
        return false;
    }
    *actor_address = spawned_actor;
    return true;
}

bool RemoveReplicatedLootPresentationActor(
    const ReplicatedLootPresentationBinding& binding,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (binding.actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = 0;
    if (memory.TryReadField(binding.actor_address, kActorOwnerOffset, &world_address) &&
        world_address != 0) {
        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        if (unregister_address != 0 &&
            CallActorWorldUnregisterSafe(
                unregister_address,
                world_address,
                binding.actor_address,
                1,
                exception_code)) {
            return true;
        }
    }

    const float address_jitter_x = static_cast<float>((binding.actor_address >> 4) & 0x3FFu);
    const float address_jitter_y = static_cast<float>((binding.actor_address >> 14) & 0x3FFu);
    const float park_x = kReplicatedLootParkBase + address_jitter_x * 8.0f;
    const float park_y = kReplicatedLootParkBase + address_jitter_y * 8.0f;
    bool wrote =
        memory.TryWriteField(binding.actor_address, kActorPositionXOffset, park_x) &&
        memory.TryWriteField(binding.actor_address, kActorPositionYOffset, park_y);
    const std::uint32_t zero = 0;
    if (binding.drop_kind == multiplayer::LootDropKind::Gold) {
        const std::uint8_t inactive = 0;
        wrote = memory.TryWriteField(binding.actor_address, kReplicatedGoldLifetimeOffset, zero) && wrote;
        wrote = memory.TryWriteField(binding.actor_address, kReplicatedGoldActiveOffset, inactive) && wrote;
    } else if (binding.drop_kind == multiplayer::LootDropKind::Orb) {
        wrote = memory.TryWriteField(binding.actor_address, kReplicatedOrbLifetimeOffset, zero) && wrote;
    }
    DWORD rebind_exception_code = 0;
    (void)TryRebindActorToOwnerWorld(binding.actor_address, &rebind_exception_code);
    return wrote;
}

void ClearReplicatedLootPresentationBindingsForSceneSwitch(const char* reason) {
    std::uint32_t count = 0;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        count = static_cast<std::uint32_t>(g_replicated_loot_presentations.size());
        g_replicated_loot_presentations.clear();
        g_client_non_authoritative_loot_suppressed_actors.clear();
    }
    if (count != 0) {
        Log(
            "replicated_loot: abandoned presentation bindings for scene switch. reason=" +
            std::string(reason != nullptr ? reason : "unknown") +
            " count=" + std::to_string(count));
    }
}

void RemoveAllReplicatedLootPresentationActors(const char* reason) {
    std::vector<ReplicatedLootPresentationBinding> bindings;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        bindings = g_replicated_loot_presentations;
        g_replicated_loot_presentations.clear();
        g_client_non_authoritative_loot_suppressed_actors.clear();
    }

    std::uint32_t removed = 0;
    std::uint32_t failed = 0;
    for (const auto& binding : bindings) {
        DWORD exception_code = 0;
        if (RemoveReplicatedLootPresentationActor(binding, &exception_code)) {
            ++removed;
        } else {
            ++failed;
            Log(
                "replicated_loot: failed to remove presentation actor. reason=" +
                std::string(reason != nullptr ? reason : "unknown") +
                " network_drop_id=" + std::to_string(binding.network_drop_id) +
                " actor=" + HexString(binding.actor_address) +
                " seh=" + HexString(static_cast<uintptr_t>(exception_code)));
        }
    }
    if (removed != 0 || failed != 0) {
        Log(
            "replicated_loot: removed presentation actors. reason=" +
            std::string(reason != nullptr ? reason : "unknown") +
            " removed=" + std::to_string(removed) +
            " failed=" + std::to_string(failed));
    }
}

void RemoveUnboundClientLootActors(const char* reason) {
    if (!multiplayer::IsLocalTransportClient()) {
        return;
    }

    std::unordered_set<uintptr_t> bound_actor_addresses;
    std::unordered_set<uintptr_t> suppressed_actor_addresses;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        for (const auto& binding : g_replicated_loot_presentations) {
            if (binding.actor_address != 0) {
                bound_actor_addresses.insert(binding.actor_address);
            }
        }
        suppressed_actor_addresses = g_client_non_authoritative_loot_suppressed_actors;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return;
    }

    std::uint32_t removed = 0;
    std::uint32_t failed = 0;
    for (const auto& actor : actors) {
        if (!actor.valid ||
            actor.actor_address == 0 ||
            !IsLootDropNativeTypeId(actor.object_type_id) ||
            bound_actor_addresses.find(actor.actor_address) != bound_actor_addresses.end()) {
            continue;
        }

        ReplicatedLootPresentationBinding binding;
        binding.actor_address = actor.actor_address;
        binding.native_type_id = actor.object_type_id;
        binding.drop_kind = LootDropKindFromNativeTypeId(actor.object_type_id);
        DWORD exception_code = 0;
        if (suppressed_actor_addresses.find(actor.actor_address) != suppressed_actor_addresses.end()) {
            (void)RemoveReplicatedLootPresentationActor(binding, &exception_code);
            continue;
        }
        if (RemoveReplicatedLootPresentationActor(binding, &exception_code)) {
            ++removed;
            std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
            g_client_non_authoritative_loot_suppressed_actors.insert(actor.actor_address);
        } else {
            ++failed;
            Log(
                "replicated_loot: failed to remove unbound client loot actor. reason=" +
                std::string(reason != nullptr ? reason : "unknown") +
                " actor=" + HexString(actor.actor_address) +
                " type=" + HexString(static_cast<uintptr_t>(actor.object_type_id)) +
                " seh=" + HexString(static_cast<uintptr_t>(exception_code)));
        }
    }

    if (removed != 0 || failed != 0) {
        Log(
            "replicated_loot: removed unbound client loot actors. reason=" +
            std::string(reason != nullptr ? reason : "unknown") +
            " removed=" + std::to_string(removed) +
            " failed=" + std::to_string(failed));
    }
}

bool RemoveUnboundClientLootActorNow(
    uintptr_t actor_address,
    multiplayer::LootDropKind drop_kind,
    const char* reason) {
    if (!multiplayer::IsLocalTransportClient() ||
        actor_address == 0 ||
        IsReplicatedLootPresentationActorInternal(actor_address)) {
        return false;
    }

    ReplicatedLootPresentationBinding binding;
    binding.actor_address = actor_address;
    binding.drop_kind = drop_kind;
    DWORD exception_code = 0;
    bool already_suppressed = false;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        already_suppressed =
            g_client_non_authoritative_loot_suppressed_actors.find(actor_address) !=
            g_client_non_authoritative_loot_suppressed_actors.end();
    }
    if (already_suppressed) {
        return RemoveReplicatedLootPresentationActor(binding, &exception_code);
    }
    if (RemoveReplicatedLootPresentationActor(binding, &exception_code)) {
        {
            std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
            g_client_non_authoritative_loot_suppressed_actors.insert(actor_address);
        }
        Log(
            "replicated_loot: removed client-local non-authoritative loot actor. reason=" +
            std::string(reason != nullptr ? reason : "unknown") +
            " actor=" + HexString(actor_address) +
            " kind=" + std::string(multiplayer::LootDropKindLabel(drop_kind)));
        return true;
    }

    Log(
        "replicated_loot: failed to remove client-local non-authoritative loot actor. reason=" +
        std::string(reason != nullptr ? reason : "unknown") +
        " actor=" + HexString(actor_address) +
        " kind=" + std::string(multiplayer::LootDropKindLabel(drop_kind)) +
        " seh=" + HexString(static_cast<uintptr_t>(exception_code)));
    return false;
}

void ReconcileReplicatedLootSnapshotNow(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient() ||
        !snapshot.valid ||
        snapshot.authority_participant_id == 0 ||
        snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        RemoveAllReplicatedLootPresentationActors("snapshot_not_run");
        return;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        (scene_state.kind != "arena" && scene_state.name != "testrun")) {
        return;
    }

    std::unordered_set<std::uint64_t> active_drop_ids;
    for (const auto& drop : snapshot.drops) {
        if (IsSupportedReplicatedLootPresentationKind(drop)) {
            active_drop_ids.insert(drop.network_drop_id);
        }
    }

    std::vector<ReplicatedLootPresentationBinding> stale_bindings;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        auto it = g_replicated_loot_presentations.begin();
        while (it != g_replicated_loot_presentations.end()) {
            const bool wrong_authority = it->authority_participant_id != snapshot.authority_participant_id;
            const bool wrong_run = it->run_nonce != snapshot.run_nonce || it->scene_epoch != snapshot.scene_epoch;
            const bool missing_from_complete_snapshot =
                !snapshot.truncated && active_drop_ids.find(it->network_drop_id) == active_drop_ids.end();
            const bool native_actor_gone = !IsSceneActorAddressPresent(it->actor_address);
            if (wrong_authority || wrong_run || missing_from_complete_snapshot || native_actor_gone) {
                if (!native_actor_gone) {
                    stale_bindings.push_back(*it);
                }
                it = g_replicated_loot_presentations.erase(it);
                continue;
            }
            ++it;
        }
    }
    for (const auto& binding : stale_bindings) {
        DWORD exception_code = 0;
        if (!RemoveReplicatedLootPresentationActor(binding, &exception_code)) {
            Log(
                "replicated_loot: failed stale presentation removal. network_drop_id=" +
                std::to_string(binding.network_drop_id) +
                " actor=" + HexString(binding.actor_address) +
                " seh=" + HexString(static_cast<uintptr_t>(exception_code)));
        }
    }

    RemoveUnboundClientLootActors("pre_reconcile");

    for (const auto& drop : snapshot.drops) {
        if (!IsSupportedReplicatedLootPresentationKind(drop)) {
            continue;
        }

        ReplicatedLootPresentationBinding* existing = nullptr;
        {
            std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
            existing = FindReplicatedLootPresentationBindingLocked(drop.network_drop_id);
            if (existing != nullptr) {
                *existing = ToReplicatedLootPresentationBinding(
                    snapshot,
                    drop,
                    existing->actor_address,
                    now_ms);
                g_client_non_authoritative_loot_suppressed_actors.erase(existing->actor_address);
            }
        }
        if (existing != nullptr) {
            std::string write_error;
            if (!WriteReplicatedLootDropFields(existing->actor_address, drop, &write_error)) {
                Log(
                    "replicated_loot: failed to update presentation actor. network_drop_id=" +
                    std::to_string(drop.network_drop_id) +
                    " actor=" + HexString(existing->actor_address) +
                    " error=" + write_error);
            }
            continue;
        }

        uintptr_t actor_address = 0;
        std::string spawn_error;
        if (!SpawnReplicatedLootPresentationActor(drop, &actor_address, &spawn_error)) {
            Log(
                "replicated_loot: failed to materialize host drop. network_drop_id=" +
                std::to_string(drop.network_drop_id) +
                " kind=" + std::string(multiplayer::LootDropKindLabel(drop.drop_kind)) +
                " error=" + spawn_error);
            continue;
        }

        {
            std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
            g_client_non_authoritative_loot_suppressed_actors.erase(actor_address);
            g_replicated_loot_presentations.push_back(
                ToReplicatedLootPresentationBinding(snapshot, drop, actor_address, now_ms));
        }
        Log(
            "replicated_loot: materialized host drop. network_drop_id=" +
            std::to_string(drop.network_drop_id) +
            " kind=" + std::string(multiplayer::LootDropKindLabel(drop.drop_kind)) +
            " actor=" + HexString(actor_address) +
            " x=" + std::to_string(drop.position_x) +
            " y=" + std::to_string(drop.position_y));
    }

    RemoveUnboundClientLootActors("post_reconcile");
}

bool QueueReplicatedLootSnapshotInternal(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    if (!multiplayer::IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message = "Replicated loot materialization is client-only.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.clear();
    g_gameplay_keyboard_injection.pending_replicated_loot_snapshots.push_back(snapshot);
    return true;
}

bool IsReplicatedLootPresentationActorInternal(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    return std::find_if(
               g_replicated_loot_presentations.begin(),
               g_replicated_loot_presentations.end(),
               [&](const ReplicatedLootPresentationBinding& binding) {
                   return binding.actor_address == actor_address;
               }) != g_replicated_loot_presentations.end();
}

bool TryGetReplicatedLootPresentationStateInternal(
    std::uint64_t network_drop_id,
    SDModReplicatedLootPresentationState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = SDModReplicatedLootPresentationState{};
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    const auto* binding = FindReplicatedLootPresentationBindingLocked(network_drop_id);
    if (binding == nullptr) {
        return false;
    }
    *state = ToPublicReplicatedLootPresentationState(*binding);
    return true;
}

void GetReplicatedLootPresentationStatesInternal(std::vector<SDModReplicatedLootPresentationState>* states) {
    if (states == nullptr) {
        return;
    }
    states->clear();
    std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
    states->reserve(g_replicated_loot_presentations.size());
    for (const auto& binding : g_replicated_loot_presentations) {
        states->push_back(ToPublicReplicatedLootPresentationState(binding));
    }
}
