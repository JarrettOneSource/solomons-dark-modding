constexpr std::uint32_t kReplicatedLootOrbNativeTypeId = 0x07DB;
constexpr std::uint32_t kReplicatedLootGoldNativeTypeId = 0x07DC;
constexpr std::uint32_t kReplicatedLootItemDropNativeTypeId = 0x07DD;
constexpr std::uint32_t kReplicatedLootPowerupNativeTypeId = 0x07F6;
constexpr std::uint32_t kReplicatedLootPotionItemTypeId = 0x1B59;
constexpr std::uint32_t kReplicatedLootMiscItemTypeId = 0x1B64;
constexpr std::int32_t kStockPotionSubtypeMin = 0;
constexpr std::int32_t kStockPotionSubtypeMax = 5;
constexpr std::int32_t kReplicatedLootMiscItemSubtypeMin = 0;
constexpr std::int32_t kReplicatedLootMiscItemSubtypeMax = 3;
constexpr std::size_t kArenaSpawnPotionDropVfuncOffset = 0x148;
constexpr std::size_t kReplicatedGoldAmountTierOffset = 0x13C;
constexpr std::size_t kReplicatedGoldAmountOffset = 0x140;
constexpr std::size_t kReplicatedGoldLifetimeOffset = 0x144;
constexpr std::size_t kReplicatedGoldActiveOffset = 0x148;
constexpr std::size_t kReplicatedOrbResourceKindOffset = 0x13C;
constexpr std::size_t kReplicatedOrbValueOffset = 0x140;
constexpr std::size_t kReplicatedOrbLifetimeOffset = 0x144;
constexpr std::size_t kReplicatedOrbMotionOffset = 0x148;
constexpr std::size_t kReplicatedOrbProgressOffset = 0x14C;
constexpr std::size_t kReplicatedPowerupKindOffset = 0x13C;
constexpr std::size_t kReplicatedPowerupMotionOffset = 0x150;
constexpr std::size_t kReplicatedPowerupLifetimeOffset = 0x154;
constexpr std::size_t kReplicatedPowerupProgressOffset = 0x158;
constexpr std::size_t kReplicatedPowerupValueOffset = 0x15C;
constexpr std::size_t kReplicatedPowerupAuxiliaryOffset = 0x160;
constexpr std::uint32_t kReplicatedLootDefaultLifetime = 900;
constexpr float kReplicatedLootSpawnMatchMaxDistance = 192.0f;
constexpr std::uint64_t kClientLocalLootSuppressionSettleDelayMs = 150;
constexpr int kReplicatedOrbPresentationSpawnAmount = 1;

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
    float radius = 0.0f;
    std::uint32_t lifetime = 0;
    float motion = 0.0f;
    float progress = 0.0f;
    float auxiliary = 0.0f;
    std::uint32_t item_type_id = 0;
    std::uint32_t item_recipe_uid = 0;
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    std::uint8_t presentation_state = 0;
    std::uint64_t last_seen_ms = 0;
};

std::mutex g_replicated_loot_presentation_mutex;
std::vector<ReplicatedLootPresentationBinding> g_replicated_loot_presentations;

void ClearNativeInventoryCreditState();
bool IsNativeInventoryCreditCompleted(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id);

bool IsReplicatedLootPresentationActorInternal(uintptr_t actor_address);

bool IsSupportedReplicatedNonRecipeItem(
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    std::int32_t item_slot) {
    return item_type_id == kReplicatedLootMiscItemTypeId &&
           item_recipe_uid == 0 &&
           item_slot >= kReplicatedLootMiscItemSubtypeMin &&
           item_slot <= kReplicatedLootMiscItemSubtypeMax;
}

bool IsSupportedReplicatedPotionSubtype(std::int32_t item_slot) {
    if (item_slot >= kStockPotionSubtypeMin &&
        item_slot <= kStockPotionSubtypeMax) {
        return true;
    }
    return item_slot >= kLuaFirstConsumablePotionSubtype &&
        FindLuaConsumableDefinitionByNativeSubtype(item_slot).has_value();
}

void QueueClientLocalLootSuppressionInternal(const char* reason, std::uint64_t delay_ms) {
    if (!multiplayer::IsLocalTransportClient()) {
        return;
    }
    const std::string reason_text = reason != nullptr ? reason : "unknown";
    const auto due_ms = static_cast<std::uint64_t>(GetTickCount64()) + delay_ms;

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending = g_gameplay_keyboard_injection.pending_client_local_loot_suppression_requests;
    for (auto& request : pending) {
        if (request.reason == reason_text) {
            request.not_before_ms = (std::min)(request.not_before_ms, due_ms);
            return;
        }
    }
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        Log(
            "replicated_loot: dropped deferred client-local suppression; queue full. reason=" +
            reason_text);
        return;
    }

    PendingClientLocalLootSuppressionRequest request;
    request.reason = reason_text;
    request.not_before_ms = due_ms;
    pending.push_back(std::move(request));
}

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
    if (drop.drop_kind == multiplayer::LootDropKind::Potion) {
        return drop.native_type_id == kReplicatedLootItemDropNativeTypeId &&
               drop.item_type_id == kReplicatedLootPotionItemTypeId &&
               IsSupportedReplicatedPotionSubtype(drop.item_slot) &&
               drop.stack_count > 0;
    }
    if (drop.drop_kind == multiplayer::LootDropKind::Item) {
        return drop.native_type_id == kReplicatedLootItemDropNativeTypeId &&
               drop.item_type_id != 0 &&
               drop.item_type_id != kReplicatedLootPotionItemTypeId &&
               (drop.item_recipe_uid != 0 ||
                IsSupportedReplicatedNonRecipeItem(
                    drop.item_type_id,
                    drop.item_recipe_uid,
                    drop.item_slot));
    }
    if (drop.drop_kind == multiplayer::LootDropKind::Powerup) {
        return drop.native_type_id == kReplicatedLootPowerupNativeTypeId &&
               drop.amount_tier >=
                   static_cast<std::int32_t>(
                       multiplayer::PowerupRewardKind::BonusSkillPoint) &&
               drop.amount_tier <=
                   static_cast<std::int32_t>(
                       multiplayer::PowerupRewardKind::DamageX4) &&
               drop.lifetime > 0 &&
               std::isfinite(drop.value) &&
               std::isfinite(drop.motion) &&
               std::isfinite(drop.progress) &&
               std::isfinite(drop.auxiliary);
    }
    return false;
}

bool TryReadObjectVfunc(uintptr_t object_address, std::size_t vfunc_offset, uintptr_t* function_address) {
    if (function_address != nullptr) {
        *function_address = 0;
    }
    if (function_address == nullptr || object_address == 0) {
        return false;
    }

    uintptr_t vtable_address = 0;
    if (!ProcessMemory::Instance().TryReadValue(object_address, &vtable_address) ||
        vtable_address == 0) {
        return false;
    }

    return ProcessMemory::Instance().TryReadField(vtable_address, vfunc_offset, function_address) &&
           *function_address != 0;
}

bool CallSpawnPotionDropSafe(
    uintptr_t function_address,
    uintptr_t arena_address,
    float x,
    float y,
    int potion_slot,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* spawn_potion = reinterpret_cast<SpawnPotionDropFn>(function_address);
    if (spawn_potion == nullptr || arena_address == 0) {
        return false;
    }

    __try {
        spawn_potion(
            reinterpret_cast<void*>(arena_address),
            FloatToBits(x),
            FloatToBits(y),
            potion_slot);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}


bool IsLootDropNativeTypeId(std::uint32_t native_type_id) {
    return native_type_id == kReplicatedLootGoldNativeTypeId ||
           native_type_id == kReplicatedLootOrbNativeTypeId ||
           native_type_id == kReplicatedLootItemDropNativeTypeId ||
           native_type_id == kReplicatedLootPowerupNativeTypeId;
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
    if (native_type_id == kReplicatedLootPowerupNativeTypeId) {
        return multiplayer::LootDropKind::Powerup;
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
    binding.radius = drop.radius;
    binding.lifetime = drop.lifetime;
    binding.motion = drop.motion;
    binding.progress = drop.progress;
    binding.auxiliary = drop.auxiliary;
    binding.item_type_id = drop.item_type_id;
    binding.item_recipe_uid = drop.item_recipe_uid;
    binding.item_slot = drop.item_slot;
    binding.stack_count = drop.stack_count;
    binding.presentation_state = drop.presentation_state;
    binding.last_seen_ms = now_ms;
    return binding;
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

#include "replicated_loot_pickup_feedback.inl"
#include "replicated_gold_pickup_feedback.inl"

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
        const float raw_value = drop.value;
        const float motion = std::isfinite(drop.motion) ? drop.motion : 0.0f;
        const float progress = std::isfinite(drop.progress) ? drop.progress : 0.0f;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbResourceKindOffset, resource_kind) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbValueOffset, raw_value) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbLifetimeOffset, lifetime) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbMotionOffset, motion) && wrote;
        wrote = memory.TryWriteField(actor_address, kReplicatedOrbProgressOffset, progress) && wrote;
    } else if (drop.drop_kind == multiplayer::LootDropKind::Item ||
               drop.drop_kind == multiplayer::LootDropKind::Potion) {
        uintptr_t held_item_address = 0;
        std::uint32_t held_item_type_id = 0;
        if (kItemDropHeldItemOffset == 0 ||
            !memory.TryReadField(actor_address, kItemDropHeldItemOffset, &held_item_address) ||
            held_item_address == 0 ||
            !memory.TryReadField(held_item_address, kGameObjectTypeIdOffset, &held_item_type_id) ||
            held_item_type_id != drop.item_type_id) {
            if (error_message != nullptr) {
                *error_message = "replicated item drop did not expose the expected native held item";
            }
            return false;
        }

        if (drop.drop_kind == multiplayer::LootDropKind::Potion) {
            const auto stack_count = static_cast<std::int32_t>((std::max)(1, drop.stack_count));
            wrote = memory.TryWriteField(
                held_item_address,
                kItemSlotOffset,
                drop.item_slot) && wrote;
            if (kPotionStackCountOffset != 0) {
                wrote = memory.TryWriteField(
                    held_item_address,
                    kPotionStackCountOffset,
                    stack_count) && wrote;
            }
        } else if (drop.item_recipe_uid != 0) {
            std::uint32_t held_item_recipe_uid = 0;
            if (kItemInstanceRecipeUidOffset == 0 ||
                !memory.TryReadField(
                    held_item_address,
                    kItemInstanceRecipeUidOffset,
                    &held_item_recipe_uid) ||
                held_item_recipe_uid != drop.item_recipe_uid) {
                if (error_message != nullptr) {
                    *error_message = "replicated native item recipe identity diverged";
                }
                return false;
            }
            if (drop.item_color_state_valid &&
                (drop.item_type_id == kStandaloneWizardHatVisualTypeId ||
                 drop.item_type_id == kStandaloneWizardRobeVisualTypeId)) {
                wrote = memory.TryWrite(
                    held_item_address + kItemWearableColorStateOffset,
                    drop.item_color_state.data(),
                    drop.item_color_state.size()) && wrote;
            }
        } else if (IsSupportedReplicatedNonRecipeItem(
                       drop.item_type_id,
                       drop.item_recipe_uid,
                       drop.item_slot)) {
            wrote = memory.TryWriteField(
                held_item_address,
                kItemSlotOffset,
                drop.item_slot) && wrote;
        } else {
            if (error_message != nullptr) {
                *error_message = "replicated non-recipe item identity is unsupported";
            }
            return false;
        }
    } else if (drop.drop_kind == multiplayer::LootDropKind::Powerup) {
        const auto powerup_kind = static_cast<std::uint8_t>(drop.amount_tier);
        const float motion = drop.motion;
        const float progress = drop.progress;
        const float value = drop.value;
        const float auxiliary = drop.auxiliary;
        wrote =
            memory.TryWriteField(
                actor_address,
                kReplicatedPowerupKindOffset,
                powerup_kind) && wrote;
        wrote =
            memory.TryWriteField(
                actor_address,
                kReplicatedPowerupMotionOffset,
                motion) && wrote;
        wrote =
            memory.TryWriteField(
                actor_address,
                kReplicatedPowerupLifetimeOffset,
                lifetime) && wrote;
        wrote =
            memory.TryWriteField(
                actor_address,
                kReplicatedPowerupProgressOffset,
                progress) && wrote;
        wrote =
            memory.TryWriteField(
                actor_address,
                kReplicatedPowerupValueOffset,
                value) && wrote;
        wrote =
            memory.TryWriteField(
                actor_address,
                kReplicatedPowerupAuxiliaryOffset,
                auxiliary) && wrote;
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

bool ExecuteSpawnReplicatedPotionDropNow(
    const multiplayer::LootDropSnapshot& drop,
    std::string* error_message) {
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    uintptr_t spawn_function_address = 0;
    if (!TryReadObjectVfunc(
            arena_address,
            kArenaSpawnPotionDropVfuncOffset,
            &spawn_function_address)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the arena potion drop vfunc.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallSpawnPotionDropSafe(
            spawn_function_address,
            arena_address,
            drop.position_x,
            drop.position_y,
            drop.item_slot,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "native potion drop spawn failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) +
                " arena=" + HexString(arena_address) +
                " vfunc=" + HexString(spawn_function_address);
        }
        return false;
    }

    return true;
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

    if (drop.drop_kind == multiplayer::LootDropKind::Item) {
        uintptr_t held_item_address = 0;
        if (!SpawnNativeItemDropFromRecipe(
                drop,
                actor_address,
                &held_item_address,
                error_message)) {
            return false;
        }
        return WriteReplicatedLootDropFields(*actor_address, drop, error_message);
    }

    std::vector<SDModSceneActorState> before_actors;
    std::unordered_set<uintptr_t> before_addresses;
    if (TryListSceneActorsByType(drop.native_type_id, &before_actors)) {
        for (const auto& actor : before_actors) {
            before_addresses.insert(actor.actor_address);
        }
    }

    std::string spawn_error;
    if (drop.drop_kind == multiplayer::LootDropKind::Gold) {
        if (!ExecuteSpawnRewardNow(
                "gold",
                (std::max)(1, drop.amount),
                drop.position_x,
                drop.position_y,
                &spawn_error)) {
            if (error_message != nullptr) {
                *error_message = "native reward spawn failed: " + spawn_error;
            }
            return false;
        }
    } else if (drop.drop_kind == multiplayer::LootDropKind::Orb) {
        const auto spawn_kind = drop.amount_tier == 1 ? "mana_orb" : "health_orb";
        if (!ExecuteSpawnRewardNow(
                spawn_kind,
                kReplicatedOrbPresentationSpawnAmount,
                drop.position_x,
                drop.position_y,
                &spawn_error)) {
            if (error_message != nullptr) {
                *error_message = "native reward spawn failed: " + spawn_error;
            }
            return false;
        }
    } else if (drop.drop_kind == multiplayer::LootDropKind::Potion) {
        if (!ExecuteSpawnReplicatedPotionDropNow(drop, &spawn_error)) {
            if (error_message != nullptr) {
                *error_message = "native potion drop spawn failed: " + spawn_error;
            }
            return false;
        }
    } else if (drop.drop_kind == multiplayer::LootDropKind::Powerup) {
        const char* spawn_kind = nullptr;
        switch (static_cast<multiplayer::PowerupRewardKind>(drop.amount_tier)) {
        case multiplayer::PowerupRewardKind::BonusSkillPoint:
            spawn_kind = "bonus_skill";
            break;
        case multiplayer::PowerupRewardKind::RandomSkillRank:
            spawn_kind = "random_skill";
            break;
        case multiplayer::PowerupRewardKind::DamageX4:
            spawn_kind = "damage_x4";
            break;
        }
        if (spawn_kind == nullptr ||
            !ExecuteSpawnRewardNow(
                spawn_kind,
                1,
                drop.position_x,
                drop.position_y,
                &spawn_error)) {
            if (error_message != nullptr) {
                *error_message = "native powerup spawn failed: " + spawn_error;
            }
            return false;
        }
    } else {
        if (error_message != nullptr) {
            *error_message = "unsupported replicated loot presentation kind";
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

    return CallActorRequestRetirementSafe(
        binding.actor_address,
        exception_code);
}

void ClearReplicatedLootPresentationBindingsForSceneSwitch(const char* reason) {
    std::uint32_t count = 0;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        count = static_cast<std::uint32_t>(g_replicated_loot_presentations.size());
        g_replicated_loot_presentations.clear();
        ClearReplicatedGoldPickupFeedbackStateLocked();
    }
    if (count != 0) {
        Log(
            "replicated_loot: abandoned presentation bindings for scene switch. reason=" +
            std::string(reason != nullptr ? reason : "unknown") +
            " count=" + std::to_string(count));
    }
    ClearNativeInventoryCreditState();
}

void RemoveAllReplicatedLootPresentationActors(const char* reason) {
    std::vector<ReplicatedLootPresentationBinding> bindings;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        bindings = g_replicated_loot_presentations;
        g_replicated_loot_presentations.clear();
        ClearReplicatedGoldPickupFeedbackStateLocked();
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
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        for (const auto& binding : g_replicated_loot_presentations) {
            if (binding.actor_address != 0) {
                bound_actor_addresses.insert(binding.actor_address);
            }
        }
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
        if (RemoveReplicatedLootPresentationActor(binding, &exception_code)) {
            ++removed;
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


void ReconcileReplicatedLootSnapshotNow(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient() ||
        !snapshot.valid ||
        snapshot.authority_participant_id == 0 ||
        snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        RemoveAllReplicatedLootPresentationActors("snapshot_not_run");
        ClearNativeInventoryCreditState();
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
        if (IsSupportedReplicatedLootPresentationKind(drop) &&
            !IsNativeInventoryCreditCompleted(snapshot.run_nonce, drop.network_drop_id)) {
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
            const bool hold_for_pickup_feedback =
                missing_from_complete_snapshot &&
                ShouldHoldReplicatedLootPickupForFeedbackLocked(*it, now_ms);
            if (wrong_authority ||
                wrong_run ||
                (missing_from_complete_snapshot && !hold_for_pickup_feedback) ||
                native_actor_gone) {
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
        if (!IsSupportedReplicatedLootPresentationKind(drop) ||
            IsNativeInventoryCreditCompleted(snapshot.run_nonce, drop.network_drop_id)) {
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

#include "replicated_loot_public_api.inl"
