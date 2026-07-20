// Participant-owned inventory, spellbook/statbook, and loadout snapshot helpers.

std::uint16_t ClampInventoryCountForPacket(int value) {
    if (value <= 0) {
        return 0;
    }
    if (value > static_cast<int>((std::numeric_limits<std::uint16_t>::max)())) {
        return (std::numeric_limits<std::uint16_t>::max)();
    }
    return static_cast<std::uint16_t>(value);
}

std::vector<ParticipantInventoryItemState> BuildOwnedInventoryItems(
    const SDModInventoryState& inventory_state) {
    std::vector<ParticipantInventoryItemState> items;
    items.reserve(inventory_state.items.size());
    for (const auto& item : inventory_state.items) {
        if (!item.valid || item.type_id == 0) {
            continue;
        }
        ParticipantInventoryItemState built;
        built.type_id = item.type_id;
        built.recipe_uid = item.recipe_uid;
        built.slot = item.slot;
        built.stack_count = item.stack_count;
        items.push_back(built);
    }
    return items;
}

bool InventoryItemsEqual(
    const std::vector<ParticipantInventoryItemState>& left,
    const std::vector<ParticipantInventoryItemState>& right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0; index < left.size(); ++index) {
        if (left[index].type_id != right[index].type_id ||
            left[index].recipe_uid != right[index].recipe_uid ||
            left[index].slot != right[index].slot ||
            left[index].stack_count != right[index].stack_count) {
            return false;
        }
    }
    return true;
}

void RefreshOwnedInventoryFromSnapshot(
    const SDModInventoryState& inventory_state,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !inventory_state.valid) {
        return;
    }

    auto next_items = BuildOwnedInventoryItems(inventory_state);
    const auto next_total_count = ClampInventoryCountForPacket(inventory_state.item_count);
    const bool next_truncated =
        inventory_state.truncated ||
        inventory_state.item_count > static_cast<int>(next_items.size());
    const bool changed =
        owned_progression->inventory_item_total_count != next_total_count ||
        owned_progression->inventory_truncated != next_truncated ||
        !InventoryItemsEqual(owned_progression->inventory_items, next_items);
    if (!changed) {
        return;
    }

    owned_progression->inventory_item_total_count = next_total_count;
    owned_progression->inventory_truncated = next_truncated;
    owned_progression->inventory_items = std::move(next_items);
    owned_progression->inventory_revision += 1;
}

ParticipantEquippedItemState BuildOwnedEquippedItem(
    const SDModEquipVisualLaneState& lane) {
    ParticipantEquippedItemState item;
    item.type_id = lane.current_object_type_id;
    item.recipe_uid = lane.current_object_recipe_uid;
    return item;
}

bool EquippedItemsEqual(
    const ParticipantEquippedItemState& left,
    const ParticipantEquippedItemState& right) {
    return left.type_id == right.type_id &&
           left.recipe_uid == right.recipe_uid;
}

bool EquipmentStatesEqual(
    const ParticipantEquipmentState& left,
    const ParticipantEquipmentState& right) {
    if (left.valid != right.valid ||
        !EquippedItemsEqual(left.hat, right.hat) ||
        !EquippedItemsEqual(left.robe, right.robe) ||
        !EquippedItemsEqual(left.weapon, right.weapon) ||
        !EquippedItemsEqual(left.amulet, right.amulet)) {
        return false;
    }
    for (std::size_t index = 0; index < left.rings.size(); ++index) {
        if (!EquippedItemsEqual(left.rings[index], right.rings[index])) {
            return false;
        }
    }
    return true;
}

void RefreshOwnedEquipmentFromSnapshot(
    const SDModInventoryState& inventory_state,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !inventory_state.valid) {
        return;
    }

    ParticipantEquipmentState next;
    next.valid =
        inventory_state.primary_visual_lane.holder_address != 0 &&
        inventory_state.secondary_visual_lane.holder_address != 0 &&
        inventory_state.attachment_visual_lane.holder_address != 0 &&
        inventory_state.amulet_lane.holder_address != 0;
    for (const auto& ring_lane : inventory_state.ring_lanes) {
        next.valid = next.valid && ring_lane.holder_address != 0;
    }
    if (!next.valid) {
        return;
    }

    next.hat = BuildOwnedEquippedItem(inventory_state.primary_visual_lane);
    next.robe = BuildOwnedEquippedItem(inventory_state.secondary_visual_lane);
    next.weapon = BuildOwnedEquippedItem(inventory_state.attachment_visual_lane);
    for (std::size_t index = 0; index < next.rings.size(); ++index) {
        next.rings[index] = BuildOwnedEquippedItem(inventory_state.ring_lanes[index]);
    }
    next.amulet = BuildOwnedEquippedItem(inventory_state.amulet_lane);
    if (EquipmentStatesEqual(owned_progression->equipment, next)) {
        return;
    }

    owned_progression->equipment = next;
    owned_progression->equipment_revision += 1;
}

std::uint16_t ClampProgressionBookEntryCountForPacket(int value) {
    if (value <= 0) {
        return 0;
    }
    if (value > static_cast<int>((std::numeric_limits<std::uint16_t>::max)())) {
        return (std::numeric_limits<std::uint16_t>::max)();
    }
    return static_cast<std::uint16_t>(value);
}

std::vector<ParticipantProgressionBookEntryState> BuildOwnedProgressionBookEntries(
    const SDModProgressionBookState& book_state) {
    std::vector<ParticipantProgressionBookEntryState> entries;
    entries.reserve(book_state.entries.size());
    for (const auto& entry : book_state.entries) {
        if (!entry.valid) {
            continue;
        }

        ParticipantProgressionBookEntryState built;
        built.entry_index = entry.entry_index;
        built.internal_id = entry.internal_id;
        built.active = entry.active;
        built.visible = entry.visible;
        built.category = entry.category;
        built.statbook_max_level = entry.statbook_max_level;
        entries.push_back(built);
    }
    return entries;
}

bool ProgressionBookEntriesEqual(
    const std::vector<ParticipantProgressionBookEntryState>& left,
    const std::vector<ParticipantProgressionBookEntryState>& right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0; index < left.size(); ++index) {
        if (left[index].entry_index != right[index].entry_index ||
            left[index].internal_id != right[index].internal_id ||
            left[index].active != right[index].active ||
            left[index].visible != right[index].visible ||
            left[index].category != right[index].category ||
            left[index].statbook_max_level != right[index].statbook_max_level) {
            return false;
        }
    }
    return true;
}

void RefreshOwnedProgressionBookFromSnapshot(
    const SDModProgressionBookState& book_state,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !book_state.valid) {
        return;
    }

    auto next_entries = BuildOwnedProgressionBookEntries(book_state);
    const auto next_total_count = ClampProgressionBookEntryCountForPacket(book_state.entry_count);
    const bool next_truncated =
        book_state.truncated ||
        book_state.entry_count > static_cast<int>(next_entries.size());
    const bool changed =
        owned_progression->progression_book_entry_total_count != next_total_count ||
        owned_progression->progression_book_truncated != next_truncated ||
        !ProgressionBookEntriesEqual(owned_progression->progression_book_entries, next_entries);
    if (!changed) {
        return;
    }

    owned_progression->progression_book_entry_total_count = next_total_count;
    owned_progression->progression_book_truncated = next_truncated;
    owned_progression->progression_book_entries = std::move(next_entries);
    owned_progression->spellbook_revision += 1;
    owned_progression->statbook_revision += 1;
}

bool ApplyAuthoritativeProgressionBookEntryState(
    std::int32_t entry_index,
    std::uint16_t resulting_active,
    std::uint16_t resulting_visible,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || entry_index < 0) {
        return false;
    }

    const auto entry = std::find_if(
        owned_progression->progression_book_entries.begin(),
        owned_progression->progression_book_entries.end(),
        [&](const ParticipantProgressionBookEntryState& candidate) {
            return candidate.entry_index == entry_index;
        });
    if (entry == owned_progression->progression_book_entries.end()) {
        return false;
    }

    const bool changed =
        entry->active != resulting_active ||
        entry->visible != resulting_visible;
    entry->active = resulting_active;
    entry->visible = resulting_visible;
    if (changed) {
        owned_progression->spellbook_revision += 1;
        owned_progression->statbook_revision += 1;
    }
    return true;
}

void RefreshOwnedConcentrationSelections(
    std::int32_t entry_a,
    std::int32_t entry_b,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || entry_a < -1 || entry_b < -1) {
        return;
    }

    const bool changed =
        !owned_progression->concentration_selection_valid ||
        owned_progression->concentration_entry_a != entry_a ||
        owned_progression->concentration_entry_b != entry_b;
    if (!changed) {
        return;
    }

    owned_progression->concentration_selection_valid = true;
    owned_progression->concentration_entry_a = entry_a;
    owned_progression->concentration_entry_b = entry_b;
    owned_progression->concentration_revision += 1;
}

bool DerivedStatsEqual(
    const ParticipantDerivedStatState& left,
    const ParticipantDerivedStatState& right) {
    return left.valid == right.valid &&
           left.cast_speed_multiplier == right.cast_speed_multiplier &&
           left.mana_recovery_multiplier == right.mana_recovery_multiplier &&
           left.resist_magic_fraction == right.resist_magic_fraction &&
           left.resist_poison_fraction == right.resist_poison_fraction &&
           left.deflect_chance == right.deflect_chance &&
           left.staff_melee_damage_a == right.staff_melee_damage_a &&
           left.staff_melee_damage_b == right.staff_melee_damage_b &&
           left.pickup_range == right.pickup_range &&
           left.secondary_recharge_multiplier == right.secondary_recharge_multiplier &&
           left.offensive_damage_multiplier == right.offensive_damage_multiplier &&
           left.offensive_mana_multiplier == right.offensive_mana_multiplier &&
           left.meditation_recovery_bonus == right.meditation_recovery_bonus &&
           left.meditation_idle_ticks == right.meditation_idle_ticks;
}

void RefreshOwnedDerivedStats(
    const SDModDerivedProgressionStatState& native_stats,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !native_stats.valid) {
        return;
    }

    ParticipantDerivedStatState next;
    next.valid = true;
    next.cast_speed_multiplier = native_stats.cast_speed_multiplier;
    next.mana_recovery_multiplier = native_stats.mana_recovery_multiplier;
    next.resist_magic_fraction = native_stats.resist_magic_fraction;
    next.resist_poison_fraction = native_stats.resist_poison_fraction;
    next.deflect_chance = native_stats.deflect_chance;
    next.staff_melee_damage_a = native_stats.staff_melee_damage_a;
    next.staff_melee_damage_b = native_stats.staff_melee_damage_b;
    next.pickup_range = native_stats.pickup_range;
    next.secondary_recharge_multiplier = native_stats.secondary_recharge_multiplier;
    next.offensive_damage_multiplier = native_stats.offensive_damage_multiplier;
    next.offensive_mana_multiplier = native_stats.offensive_mana_multiplier;
    next.meditation_recovery_bonus = native_stats.meditation_recovery_bonus;
    next.meditation_idle_ticks = native_stats.meditation_idle_ticks;
    if (DerivedStatsEqual(owned_progression->derived_stats, next)) {
        return;
    }

    owned_progression->derived_stats = next;
    owned_progression->derived_stat_revision += 1;
}

void BuildDerivedStatPacketState(
    const ParticipantOwnedProgressionState& owned_progression,
    std::uint32_t* revision,
    ParticipantDerivedStatPacketState* packet) {
    if (revision == nullptr || packet == nullptr) {
        return;
    }
    *revision = owned_progression.derived_stat_revision;
    *packet = ParticipantDerivedStatPacketState{};
    const auto& stats = owned_progression.derived_stats;
    packet->valid = stats.valid ? 1 : 0;
    packet->cast_speed_multiplier = stats.cast_speed_multiplier;
    packet->mana_recovery_multiplier = stats.mana_recovery_multiplier;
    packet->resist_magic_fraction = stats.resist_magic_fraction;
    packet->resist_poison_fraction = stats.resist_poison_fraction;
    packet->deflect_chance = stats.deflect_chance;
    packet->staff_melee_damage_a = stats.staff_melee_damage_a;
    packet->staff_melee_damage_b = stats.staff_melee_damage_b;
    packet->pickup_range = stats.pickup_range;
    packet->secondary_recharge_multiplier = stats.secondary_recharge_multiplier;
    packet->offensive_damage_multiplier = stats.offensive_damage_multiplier;
    packet->offensive_mana_multiplier = stats.offensive_mana_multiplier;
    packet->meditation_recovery_bonus = stats.meditation_recovery_bonus;
    packet->meditation_idle_ticks = stats.meditation_idle_ticks;
}

bool IsSaneDerivedStatPacketState(const ParticipantDerivedStatPacketState& packet) {
    const auto sane_float = [](float value) {
        return std::isfinite(value) && std::fabs(value) <= 1000000.0f;
    };
    return packet.valid != 0 &&
           sane_float(packet.cast_speed_multiplier) &&
           sane_float(packet.mana_recovery_multiplier) &&
           sane_float(packet.resist_magic_fraction) &&
           sane_float(packet.resist_poison_fraction) &&
           sane_float(packet.deflect_chance) &&
           sane_float(packet.staff_melee_damage_a) &&
           sane_float(packet.staff_melee_damage_b) &&
           sane_float(packet.pickup_range) &&
           sane_float(packet.secondary_recharge_multiplier) &&
           sane_float(packet.offensive_damage_multiplier) &&
           sane_float(packet.offensive_mana_multiplier) &&
           sane_float(packet.meditation_recovery_bonus) &&
           packet.meditation_idle_ticks >= -1 &&
           packet.meditation_idle_ticks <= 1000000000;
}

void ApplyDerivedStatPacketState(
    std::uint32_t revision,
    const ParticipantDerivedStatPacketState& packet,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || !IsSaneDerivedStatPacketState(packet) ||
        (owned_progression->derived_stats.valid &&
         revision <= owned_progression->derived_stat_revision)) {
        return;
    }

    ParticipantDerivedStatState stats;
    stats.valid = true;
    stats.cast_speed_multiplier = packet.cast_speed_multiplier;
    stats.mana_recovery_multiplier = packet.mana_recovery_multiplier;
    stats.resist_magic_fraction = packet.resist_magic_fraction;
    stats.resist_poison_fraction = packet.resist_poison_fraction;
    stats.deflect_chance = packet.deflect_chance;
    stats.staff_melee_damage_a = packet.staff_melee_damage_a;
    stats.staff_melee_damage_b = packet.staff_melee_damage_b;
    stats.pickup_range = packet.pickup_range;
    stats.secondary_recharge_multiplier = packet.secondary_recharge_multiplier;
    stats.offensive_damage_multiplier = packet.offensive_damage_multiplier;
    stats.offensive_mana_multiplier = packet.offensive_mana_multiplier;
    stats.meditation_recovery_bonus = packet.meditation_recovery_bonus;
    stats.meditation_idle_ticks = packet.meditation_idle_ticks;
    owned_progression->derived_stats = stats;
    owned_progression->derived_stat_revision = revision;
}

bool LoadoutsEqual(const BotLoadoutInfo& left, const BotLoadoutInfo& right) {
    return left.primary_entry_index == right.primary_entry_index &&
           left.primary_combo_entry_index == right.primary_combo_entry_index &&
           left.secondary_entry_indices == right.secondary_entry_indices;
}

void RefreshOwnedAbilityLoadoutFromProfile(
    const BotLoadoutInfo& loadout,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr) {
        return;
    }

    const bool changed =
        !owned_progression->ability_loadout_valid ||
        !LoadoutsEqual(owned_progression->ability_loadout, loadout);
    owned_progression->ability_loadout_valid = true;
    owned_progression->ability_loadout = loadout;
    if (changed) {
        owned_progression->loadout_revision += 1;
    }
}

std::int32_t NormalizeInventoryLootStackCount(std::uint32_t type_id, std::int32_t stack_count) {
    if (type_id != kPotionItemTypeId) {
        return (std::max)(stack_count, 1);
    }
    return (std::max)(stack_count, 1);
}

bool ApplyOwnedInventoryLootItem(
    std::uint32_t type_id,
    std::uint32_t recipe_uid,
    std::int32_t slot,
    std::int32_t stack_count,
    ParticipantOwnedProgressionState* owned_progression) {
    if (owned_progression == nullptr || type_id == 0) {
        return false;
    }

    const auto normalized_stack_count = NormalizeInventoryLootStackCount(type_id, stack_count);
    if (type_id == kPotionItemTypeId) {
        for (auto& item : owned_progression->inventory_items) {
            if (item.type_id == type_id && item.slot == slot) {
                const auto next_stack =
                    static_cast<std::int64_t>(item.stack_count) +
                    static_cast<std::int64_t>(normalized_stack_count);
                item.stack_count = next_stack >
                        static_cast<std::int64_t>((std::numeric_limits<std::int32_t>::max)())
                    ? (std::numeric_limits<std::int32_t>::max)()
                    : static_cast<std::int32_t>(next_stack);
                owned_progression->inventory_item_total_count =
                    ClampInventoryCountForPacket(
                        static_cast<int>(owned_progression->inventory_items.size()));
                owned_progression->inventory_truncated =
                    owned_progression->inventory_items.size() > kParticipantInventorySnapshotMaxItems;
                owned_progression->inventory_revision += 1;
                return true;
            }
        }
    }

    ParticipantInventoryItemState item;
    item.type_id = type_id;
    item.recipe_uid = recipe_uid;
    item.slot = slot;
    item.stack_count = normalized_stack_count;
    owned_progression->inventory_items.push_back(item);
    owned_progression->inventory_item_total_count =
        ClampInventoryCountForPacket(static_cast<int>(owned_progression->inventory_items.size()));
    owned_progression->inventory_truncated =
        owned_progression->inventory_items.size() > kParticipantInventorySnapshotMaxItems;
    owned_progression->inventory_revision += 1;
    return true;
}
