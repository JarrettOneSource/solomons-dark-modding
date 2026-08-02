struct BotPotionEffectDetails {
    float restores_hp_fraction = 0.0f;
    float restores_mana_fraction = 0.0f;
    float damage_multiplier = 1.0f;
    bool cures_poison = false;
    float poison_immunity_duration_seconds = 0.0f;
    bool concentrates_all = false;
    float effect_duration_seconds = 0.0f;
};

struct BotPotionInventoryDetails {
    std::int32_t stock_subtype = -1;
    std::uint64_t content_id = 0;
    std::string identity_key;
    std::int32_t count = 0;
    bool custom = false;
    bool effect_resolved = false;
    bool synthetic_use_supported = false;
    BotPotionEffectDetails effect;
};

struct BotEquippedItemDetails {
    std::string slot;
    bool present = false;
    std::string identity_key;
    std::string recipe_name;
    std::int32_t catalog_index = -1;
    bool catalog_resolved = false;
    std::int32_t rarity_id = 0;
    std::int32_t level = 0;
    bool set_complete = false;
    float offense_effect = 0.0f;
    float resource_effect = 0.0f;
    float mobility_effect = 0.0f;
    float defense_effect = 0.0f;
    bool targeted_effect_present = false;
    std::int32_t target_kind = 0;
    std::int32_t target_id = -1;
    float target_magnitude = 0.0f;
    bool special_feature_present = false;
};

struct BotInventorySummary {
    std::int32_t item_total_count = 0;
    std::int32_t potion_count = 0;
    std::int32_t equipment_count = 0;
    std::int32_t sack_count = 0;
    std::int32_t misc_count = 0;
    std::int32_t perk_count = 0;
    std::int32_t map_count = 0;
    std::int32_t registered_custom_count = 0;
    std::int32_t unknown_count = 0;
    std::int32_t wizard_key_count = 0;
};

struct BotInventoryDetails {
    bool available = false;
    std::uint64_t participant_id = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t inventory_revision = 0;
    std::uint32_t equipment_revision = 0;
    bool descriptors_resolved = false;
    float damage_x4_remaining_seconds = 0.0f;
    float poison_immunity_remaining_seconds = 0.0f;
    float all_concentration_remaining_seconds = 0.0f;
    bool timers_resolved = false;
    std::vector<BotPotionInventoryDetails> potions;
    std::array<BotEquippedItemDetails, 7> equipped;
    BotInventorySummary summary;
};

struct BotUseConsumableRequest {
    std::uint64_t participant_id = 0;
    std::int32_t potion_slot = 0;
    std::uint32_t inventory_revision = 0;
};

struct BotUseConsumableResult {
    std::uint64_t use_id = 0;
    std::uint32_t inventory_revision = 0;
    std::int32_t stock_subtype = -1;
    std::uint64_t content_id = 0;
};
