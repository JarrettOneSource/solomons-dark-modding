constexpr std::uint32_t kBotPotionItemTypeId = 7001;

BotInventoryRevisionTuple ResolveBotInventoryRevisionTuple(
    const ParticipantInfo& participant) {
    return BotInventoryRevisionTuple{
        participant.runtime.run_nonce,
        participant.owned_progression.inventory_revision,
        participant.owned_progression.equipment_revision,
        participant.owned_progression.derived_stat_revision,
        participant.owned_progression.statbook_revision,
    };
}

BotPotionInventoryDetails BuildStockPotionDetails(
    std::int32_t subtype) {
    BotPotionInventoryDetails row;
    row.stock_subtype = subtype;
    row.effect_resolved = subtype >= 0 && subtype <= 5;
    row.synthetic_use_supported =
        subtype == 0 || subtype == 1 || subtype == 5;
    switch (subtype) {
    case 0:
        row.identity_key = "stock:potion:health";
        row.effect.restores_hp_fraction = 1.0f;
        break;
    case 1:
        row.identity_key = "stock:potion:mana";
        row.effect.restores_mana_fraction = 1.0f;
        break;
    case 2:
        row.identity_key = "stock:potion:wizard_chug";
        row.effect.damage_multiplier = 4.0f;
        row.effect.effect_duration_seconds = 60.0f;
        break;
    case 3:
        row.identity_key = "stock:potion:antidote";
        row.effect.cures_poison = true;
        row.effect.poison_immunity_duration_seconds = 10.0f;
        row.effect.effect_duration_seconds = 10.0f;
        break;
    case 4:
        row.identity_key = "stock:potion:mind_chug";
        row.effect.concentrates_all = true;
        row.effect.effect_duration_seconds = 60.0f;
        break;
    case 5:
        row.identity_key = "stock:potion:rejuvenation";
        row.effect.restores_hp_fraction = 1.0f;
        row.effect.restores_mana_fraction = 1.0f;
        break;
    default:
        row.identity_key = "stock:potion:unknown";
        row.effect_resolved = false;
        row.synthetic_use_supported = false;
        break;
    }
    return row;
}

BotPotionInventoryDetails BuildCustomPotionDetails(
    const ParticipantInventoryItemState& item) {
    BotPotionInventoryDetails row;
    row.stock_subtype = -1;
    row.content_id = item.content_id;
    row.custom = true;
    row.identity_key =
        "custom:potion:" + std::to_string(item.content_id);
    const auto definition =
        FindLuaConsumableDefinition(item.content_id);
    if (!definition.has_value()) {
        return row;
    }

    row.identity_key =
        "lua:" + definition->mod_id + ":" + definition->key;
    const auto& policy = definition->policy_effects;
    row.effect_resolved = policy.declared;
    row.synthetic_use_supported =
        policy.declared && policy.synthetic_safe;
    row.effect.restores_hp_fraction =
        policy.restores_hp_fraction;
    row.effect.restores_mana_fraction =
        policy.restores_mana_fraction;
    row.effect.damage_multiplier =
        policy.damage_multiplier;
    row.effect.cures_poison = policy.cures_poison;
    row.effect.poison_immunity_duration_seconds =
        policy.poison_immunity_duration_seconds;
    row.effect.concentrates_all =
        policy.concentrates_all;
    row.effect.effect_duration_seconds =
        policy.effect_duration_seconds;
    return row;
}

BotPotionInventoryDetails* FindMatchingPotionRow(
    std::vector<BotPotionInventoryDetails>* rows,
    const BotPotionInventoryDetails& candidate) {
    if (rows == nullptr) {
        return nullptr;
    }
    const auto found = std::find_if(
        rows->begin(),
        rows->end(),
        [&](const BotPotionInventoryDetails& row) {
            return row.custom == candidate.custom &&
                row.stock_subtype == candidate.stock_subtype &&
                row.content_id == candidate.content_id;
        });
    return found == rows->end() ? nullptr : &*found;
}

bool IsEquipmentItemType(std::uint32_t type_id) {
    return type_id == 7002 || type_id == 7003 ||
        type_id == 7004 || type_id == 7005 ||
        type_id == 7006 || type_id == 7011;
}

void AccumulateInventorySummary(
    const ParticipantInventoryItemState& item,
    BotInventorySummary* summary) {
    if (summary == nullptr) {
        return;
    }
    const auto count = (std::max)(item.stack_count, 1);
    switch (item.type_id) {
    case 7001:
        summary->potion_count += count;
        if (item.content_id != 0) {
            summary->registered_custom_count += count;
        }
        return;
    case 7002:
    case 7003:
    case 7004:
    case 7005:
    case 7006:
    case 7011:
        summary->equipment_count += count;
        return;
    case 7008:
        summary->sack_count += count;
        return;
    case 7009:
        summary->perk_count += count;
        return;
    case 7010:
        summary->map_count += count;
        return;
    case 7012:
        summary->misc_count += count;
        // Item_Misc subtype 1 is the non-stacking Wizard Key. Count rows,
        // not an untrusted stack value, so malformed/custom Item_Misc state
        // cannot alias one row into multiple keys.
        if (item.slot == 1) {
            summary->wizard_key_count += 1;
        }
        return;
    default:
        summary->unknown_count += count;
        return;
    }
}

void ResolveEquippedItemDetails(
    const char* slot,
    const ParticipantEquippedItemState& item,
    BotEquippedItemDetails* row,
    bool* descriptors_resolved) {
    if (row == nullptr || descriptors_resolved == nullptr) {
        return;
    }
    *row = {};
    row->slot = slot;
    row->present = item.type_id != 0 && item.recipe_uid != 0;
    if (!row->present) {
        return;
    }

    std::uint32_t resolved_type_id = 0;
    std::string recipe_name;
    std::string error;
    if (!TryResolveNativeItemRecipeIdentityByUid(
            item.recipe_uid,
            item.type_id,
            &recipe_name,
            &resolved_type_id,
            &error)) {
        row->identity_key =
            "native:item:type:" + std::to_string(item.type_id);
        *descriptors_resolved = false;
        return;
    }

    row->recipe_name = recipe_name;
    row->identity_key =
        "stock:item:" + std::to_string(resolved_type_id) +
        ":" + recipe_name;
    const auto* catalog = FindNativeItemPolicyCatalogEntry(
        resolved_type_id,
        recipe_name);
    if (catalog == nullptr) {
        *descriptors_resolved = false;
        return;
    }
    row->catalog_index = catalog->catalog_index;
    row->catalog_resolved = true;
    row->rarity_id = catalog->rarity_id;
    row->level = catalog->level;
    row->offense_effect = catalog->offense_effect;
    row->resource_effect = catalog->resource_effect;
    row->mobility_effect = catalog->mobility_effect;
    row->defense_effect = catalog->defense_effect;
    row->targeted_effect_present =
        catalog->target_kind != 0;
    row->target_kind = catalog->target_kind;
    row->target_id = catalog->target_id;
    row->target_magnitude = catalog->target_magnitude;
    row->special_feature_present =
        catalog->special_feature;
}

std::int32_t NativeItemSetMemberCount(
    std::int32_t set_index) {
    constexpr std::array<std::int32_t, 7> kSetSizes = {
        6, 5, 5, 4, 2, 3, 4};
    if (set_index < 0 ||
        set_index >= static_cast<std::int32_t>(
            kSetSizes.size())) {
        return 0;
    }
    return kSetSizes[
        static_cast<std::size_t>(set_index)];
}

void ResolveEquippedSetCompletion(
    std::array<BotEquippedItemDetails, 7>* equipped) {
    if (equipped == nullptr) {
        return;
    }
    for (auto& row : *equipped) {
        if (!row.catalog_resolved) {
            continue;
        }
        const auto& catalog =
            kNativeItemPolicyCatalog[
                static_cast<std::size_t>(row.catalog_index)];
        if (catalog.parent_set_index < 0) {
            continue;
        }
        const auto members = std::count_if(
            equipped->begin(),
            equipped->end(),
            [&](const BotEquippedItemDetails& candidate) {
                return candidate.catalog_resolved &&
                    kNativeItemPolicyCatalog[
                        static_cast<std::size_t>(
                            candidate.catalog_index)]
                            .parent_set_index ==
                        catalog.parent_set_index;
            });
        row.set_complete =
            members >= NativeItemSetMemberCount(
                catalog.parent_set_index);
    }
}

void BuildStaticParticipantInventoryDetails(
    const ParticipantInfo& participant,
    BotInventoryDetails* details) {
    if (details == nullptr) {
        return;
    }
    *details = {};
    details->available = true;
    details->participant_id = participant.participant_id;
    details->run_nonce = participant.runtime.run_nonce;
    const auto& progression = participant.owned_progression;
    details->inventory_revision =
        progression.inventory_revision;
    details->equipment_revision =
        progression.equipment_revision;
    details->descriptors_resolved = true;
    details->summary.item_total_count =
        progression.inventory_item_total_count;

    for (const auto& item : progression.inventory_items) {
        AccumulateInventorySummary(item, &details->summary);
        if (item.type_id != kBotPotionItemTypeId ||
            item.stack_count <= 0) {
            continue;
        }
        auto row = item.content_id != 0
            ? BuildCustomPotionDetails(item)
            : BuildStockPotionDetails(item.slot);
        row.count = item.stack_count;
        if (!row.effect_resolved) {
            details->descriptors_resolved = false;
        }
        auto* existing =
            FindMatchingPotionRow(&details->potions, row);
        if (existing == nullptr) {
            details->potions.push_back(std::move(row));
        } else {
            existing->count += item.stack_count;
        }
    }
    std::sort(
        details->potions.begin(),
        details->potions.end(),
        [](const BotPotionInventoryDetails& left,
           const BotPotionInventoryDetails& right) {
            if (left.count != right.count) {
                return left.count > right.count;
            }
            return left.identity_key < right.identity_key;
        });

    const auto& equipment = progression.equipment;
    ResolveEquippedItemDetails(
        "hat",
        equipment.hat,
        &details->equipped[0],
        &details->descriptors_resolved);
    ResolveEquippedItemDetails(
        "robe",
        equipment.robe,
        &details->equipped[1],
        &details->descriptors_resolved);
    ResolveEquippedItemDetails(
        "weapon",
        equipment.weapon,
        &details->equipped[2],
        &details->descriptors_resolved);
    for (std::size_t index = 0;
         index < equipment.rings.size();
         ++index) {
        const auto slot =
            "ring_" + std::to_string(index + 1);
        ResolveEquippedItemDetails(
            slot.c_str(),
            equipment.rings[index],
            &details->equipped[3 + index],
            &details->descriptors_resolved);
    }
    ResolveEquippedItemDetails(
        "amulet",
        equipment.amulet,
        &details->equipped[6],
        &details->descriptors_resolved);
    ResolveEquippedSetCompletion(&details->equipped);
}

void OverlayLiveParticipantConsumableState(
    BotInventoryDetails* details) {
    if (details == nullptr) {
        return;
    }
    SDModParticipantConsumableState state;
    if (!TryGetParticipantConsumableState(
            details->participant_id,
            &state) ||
        !state.available ||
        state.run_nonce != details->run_nonce) {
        details->timers_resolved = false;
        return;
    }
    details->damage_x4_remaining_seconds =
        state.damage_x4_remaining_seconds;
    details->poison_immunity_remaining_seconds =
        state.poison_immunity_remaining_seconds;
    details->all_concentration_remaining_seconds =
        state.all_concentration_remaining_seconds;
    details->timers_resolved = state.timers_resolved;
}
