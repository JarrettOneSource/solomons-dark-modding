bool TryReadItemDropHeldItemMetadata(
    uintptr_t drop_actor_address,
    std::uint32_t* item_type_id,
    std::uint32_t* item_recipe_uid,
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>* item_color_state,
    bool* item_color_state_valid,
    std::int32_t* item_slot,
    std::int32_t* stack_count) {
    if (drop_actor_address == 0 ||
        item_type_id == nullptr ||
        item_recipe_uid == nullptr ||
        item_color_state == nullptr ||
        item_color_state_valid == nullptr ||
        item_slot == nullptr ||
        stack_count == nullptr ||
        kItemDropHeldItemOffset == 0 ||
        kGameObjectTypeIdOffset == 0 ||
        kItemSlotOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t held_item_address = 0;
    if (!memory.TryReadField(drop_actor_address, kItemDropHeldItemOffset, &held_item_address) ||
        held_item_address == 0 ||
        !memory.IsReadableRange(held_item_address + kGameObjectTypeIdOffset, sizeof(std::uint32_t)) ||
        !memory.IsReadableRange(held_item_address + kItemSlotOffset, sizeof(std::int32_t))) {
        return false;
    }

    std::uint32_t read_item_type_id = 0;
    std::uint32_t read_item_recipe_uid = 0;
    std::int32_t read_item_slot = -1;
    if (!memory.TryReadField(held_item_address, kGameObjectTypeIdOffset, &read_item_type_id) ||
        read_item_type_id == 0 ||
        !memory.TryReadField(held_item_address, kItemSlotOffset, &read_item_slot)) {
        return false;
    }
    if (kItemInstanceRecipeUidOffset != 0) {
        (void)memory.TryReadField(
            held_item_address,
            kItemInstanceRecipeUidOffset,
            &read_item_recipe_uid);
    }

    std::int32_t read_stack_count = 0;
    if (read_item_type_id == kPotionItemTypeId &&
        kPotionStackCountOffset != 0 &&
        memory.IsReadableRange(held_item_address + kPotionStackCountOffset, sizeof(std::int32_t))) {
        (void)memory.TryReadField(held_item_address, kPotionStackCountOffset, &read_stack_count);
    }

    *item_color_state = {};
    *item_color_state_valid = false;
    if ((read_item_type_id == kHatItemTypeId || read_item_type_id == kRobeItemTypeId) &&
        memory.TryRead(
            static_cast<uintptr_t>(held_item_address) + kItemWearableColorStateOffset,
            item_color_state->data(),
            item_color_state->size())) {
        *item_color_state_valid = true;
    }

    *item_type_id = read_item_type_id;
    *item_recipe_uid = read_item_recipe_uid;
    *item_slot = read_item_slot;
    *stack_count = NormalizeInventoryLootStackCount(read_item_type_id, read_stack_count);
    return true;
}
bool TryPopulateGoldLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kGoldRewardNativeTypeId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t amount_tier = 0;
    std::uint8_t presentation_state = 0;
    std::uint32_t amount_raw = 0;
    std::uint32_t lifetime = 0;
    if (!memory.TryReadField(actor.actor_address, kGoldRewardAmountTierOffset, &amount_tier) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardAmountOffset, &amount_raw) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardLifetimeOffset, &lifetime) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardActiveOffset, &presentation_state)) {
        return false;
    }

    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(LootDropKind::Gold);
    built.amount = amount_raw <= static_cast<std::uint32_t>((std::numeric_limits<std::int32_t>::max)())
                       ? static_cast<std::int32_t>(amount_raw)
                       : (std::numeric_limits<std::int32_t>::max)();
    built.flags = built.amount > 0 && lifetime != 0 ? LootDropSnapshotFlagActive : 0;
    built.presentation_state = presentation_state;
    built.amount_tier = amount_tier;
    built.value = static_cast<float>(built.amount);
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = lifetime;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulateOrbLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kOrbRewardNativeTypeId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t resource_kind = 0;
    float raw_value = 0.0f;
    std::uint32_t lifetime = 0;
    float motion = 0.0f;
    float progress = 0.0f;
    if (!memory.TryReadField(actor.actor_address, kOrbRewardResourceKindOffset, &resource_kind) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardValueOffset, &raw_value) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardLifetimeOffset, &lifetime) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardMotionOffset, &motion) ||
        !memory.TryReadField(actor.actor_address, kOrbRewardProgressOffset, &progress)) {
        return false;
    }

    LootOrbResourceKind resolved_kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind, &resolved_kind) ||
        !std::isfinite(raw_value) ||
        !std::isfinite(motion) ||
        !std::isfinite(progress)) {
        return false;
    }

    const float resource_delta = ComputeLootOrbResourceDelta(resource_kind, raw_value);
    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(LootDropKind::Orb);
    built.flags = lifetime != 0 && resource_delta > kLootPickupResourceEpsilon
                      ? LootDropSnapshotFlagActive
                      : 0;
    built.amount = RoundRewardAmountToInt(resource_delta);
    built.amount_tier = resource_kind;
    built.value = raw_value;
    built.motion = motion;
    built.progress = progress;
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = lifetime;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulateItemLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kItemDropNativeTypeId) {
        return false;
    }

    std::uint32_t item_type_id = 0;
    std::uint32_t item_recipe_uid = 0;
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> item_color_state = {};
    bool item_color_state_valid = false;
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    if (!TryReadItemDropHeldItemMetadata(
            actor.actor_address,
            &item_type_id,
            &item_recipe_uid,
            &item_color_state,
            &item_color_state_valid,
            &item_slot,
            &stack_count)) {
        return false;
    }
    const bool is_potion = item_type_id == kPotionItemTypeId;
    std::uint64_t item_content_id = 0;
    if (is_potion &&
        item_slot >= kLuaFirstConsumablePotionSubtype) {
        const auto definition =
            FindLuaConsumableDefinitionByNativeSubtype(item_slot);
        if (!definition.has_value()) {
            return false;
        }
        item_content_id = definition->content_id;
    }
    const bool is_recipe_item = !is_potion && item_recipe_uid != 0;
    const bool is_supported_nonrecipe_item =
        IsSupportedNonRecipeLootItem(item_type_id, item_recipe_uid, item_slot);
    std::int32_t resolved_potion_slot = -1;
    if ((is_potion &&
         !TryResolvePotionWireIdentity(
             item_slot,
             item_content_id,
             &resolved_potion_slot)) ||
        (!is_potion && !is_recipe_item && !is_supported_nonrecipe_item)) {
        return false;
    }

    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(
        is_potion ? LootDropKind::Potion : LootDropKind::Item);
    built.flags = LootDropSnapshotFlagActive;
    if (item_color_state_valid) {
        built.flags |= LootDropSnapshotFlagItemColorState;
        std::memcpy(
            built.item_color_state,
            item_color_state.data(),
            item_color_state.size());
    }
    built.amount = stack_count;
    built.amount_tier = item_slot;
    built.value = 0.0f;
    built.item_type_id = item_type_id;
    built.item_recipe_uid = item_recipe_uid;
    built.item_content_id = item_content_id;
    built.item_slot = item_slot;
    built.stack_count = stack_count;
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = 0;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulatePowerupLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run) ||
        actor.object_type_id != kPowerupRewardNativeTypeId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t powerup_kind = 0;
    float motion = 0.0f;
    std::uint32_t lifetime = 0;
    float progress = 0.0f;
    float value = 0.0f;
    float auxiliary = 0.0f;
    if (!memory.TryReadField(actor.actor_address, kPowerupRewardKindOffset, &powerup_kind) ||
        !memory.TryReadField(actor.actor_address, kPowerupRewardMotionOffset, &motion) ||
        !memory.TryReadField(actor.actor_address, kPowerupRewardLifetimeOffset, &lifetime) ||
        !memory.TryReadField(actor.actor_address, kPowerupRewardProgressOffset, &progress) ||
        !memory.TryReadField(actor.actor_address, kPowerupRewardValueOffset, &value) ||
        !memory.TryReadField(actor.actor_address, kPowerupRewardAuxiliaryOffset, &auxiliary) ||
        powerup_kind > static_cast<std::uint8_t>(PowerupRewardKind::DamageX4) ||
        !std::isfinite(motion) ||
        !std::isfinite(progress) ||
        !std::isfinite(value) ||
        !std::isfinite(auxiliary)) {
        return false;
    }

    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(LootDropKind::Powerup);
    built.flags = lifetime != 0 ? LootDropSnapshotFlagActive : 0;
    built.amount = 1;
    built.amount_tier = powerup_kind;
    built.value = value;
    built.motion = motion;
    built.progress = progress;
    built.auxiliary = auxiliary;
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = lifetime;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

bool TryPopulateLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (actor.object_type_id == kGoldRewardNativeTypeId) {
        return TryPopulateGoldLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    if (actor.object_type_id == kOrbRewardNativeTypeId) {
        return TryPopulateOrbLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    if (actor.object_type_id == kItemDropNativeTypeId) {
        return TryPopulateItemLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    if (actor.object_type_id == kPowerupRewardNativeTypeId) {
        return TryPopulatePowerupLootDropSnapshot(actor, network_drop_id, snapshot);
    }
    return false;
}

bool TryFindHostRunLootDropByNetworkId(
    std::uint64_t network_drop_id,
    SDModSceneActorState* actor_out,
    LootDropSnapshotPacketState* snapshot_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (snapshot_out != nullptr) {
        *snapshot_out = {};
    }
    if (network_drop_id == 0 || !g_local_transport.is_host) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (!ShouldReplicateLootDropActor(actor, scene_intent.kind)) {
            continue;
        }

        const auto network_candidate = AllocateRunLootDropNetworkId(actor);
        if (network_candidate != network_drop_id) {
            continue;
        }

        LootDropSnapshotPacketState snapshot{};
        if (!TryPopulateLootDropSnapshot(actor, network_candidate, &snapshot)) {
            return false;
        }

        if (actor_out != nullptr) {
            *actor_out = actor;
        }
        if (snapshot_out != nullptr) {
            *snapshot_out = snapshot;
        }
        return true;
    }
    return false;
}

bool TryWriteLocalGlobalGold(std::int32_t gold) {
    const auto address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGoldGlobal);
    return address != 0 && ProcessMemory::Instance().TryWriteValue(address, gold);
}

bool TryWriteLocalPlayerOrbResource(
    std::int32_t resource_kind_value,
    float life_current,
    float life_max,
    float mana_current,
    float mana_max) {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0 ||
        kProgressionHpOffset == 0 ||
        kProgressionMaxHpOffset == 0 ||
        kProgressionMpOffset == 0 ||
        kProgressionMaxMpOffset == 0 ||
        !std::isfinite(life_current) ||
        !std::isfinite(life_max) ||
        !std::isfinite(mana_current) ||
        !std::isfinite(mana_max)) {
        return false;
    }

    LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind_value, &resource_kind)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (resource_kind == LootOrbResourceKind::Health) {
        if (life_max <= 0.0f) {
            return false;
        }
        const float clamped_life = (std::clamp)(life_current, 0.0f, life_max);
        return memory.TryWriteField(player_state.progression_address, kProgressionMaxHpOffset, life_max) &&
               memory.TryWriteField(player_state.progression_address, kProgressionHpOffset, clamped_life);
    }

    if (mana_max <= 0.0f) {
        return false;
    }
    const float clamped_mana = (std::clamp)(mana_current, 0.0f, mana_max);
    return memory.TryWriteField(player_state.progression_address, kProgressionMaxMpOffset, mana_max) &&
           memory.TryWriteField(player_state.progression_address, kProgressionMpOffset, clamped_mana);
}

bool IsLootPickupRequestSequenceDuplicate(const LootPickupRequestPacket& packet) {
    const auto it =
        g_local_transport.last_loot_pickup_request_sequence_by_participant.find(packet.participant_id);
    if (it == g_local_transport.last_loot_pickup_request_sequence_by_participant.end() ||
        packet.request_sequence == 0) {
        return false;
    }
    return !IsPacketSequenceNewer(packet.request_sequence, it->second);
}

void RememberLootPickupRequestSequence(const LootPickupRequestPacket& packet) {
    if (packet.request_sequence != 0) {
        g_local_transport.last_loot_pickup_request_sequence_by_participant[packet.participant_id] =
            packet.request_sequence;
    }
}
