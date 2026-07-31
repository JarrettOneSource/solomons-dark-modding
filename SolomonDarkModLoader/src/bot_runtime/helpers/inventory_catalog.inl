struct NativeItemPolicyCatalogEntry {
    std::int32_t catalog_index = -1;
    std::uint32_t native_type_id = 0;
    std::string_view name;
    std::int32_t rarity_id = 0;
    std::int32_t level = 0;
    std::int32_t parent_set_index = -1;
    float offense_effect = 0.0f;
    float resource_effect = 0.0f;
    float mobility_effect = 0.0f;
    float defense_effect = 0.0f;
    std::int32_t target_kind = 0;
    std::int32_t target_id = -1;
    float target_magnitude = 0.0f;
    bool special_feature = false;
};

// Generated from native-item-catalog.json. Aggregate magnitudes preserve sign
// and use the catalog's percent convention divided by 100.
constexpr std::array<NativeItemPolicyCatalogEntry, 47>
    kNativeItemPolicyCatalog = {{
    {0, 7002, "Pentaclostic Ring", 1, 0, 0, 0.0f, 0.0f, 0.0f, 0.0f, 2, 11, 0.01f, true},
    {1, 7006, "Arcanoric Robe", 2, 0, 0, 0.0f, 0.0f, 0.0f, 0.0f, 2, 27, 0.01f, true},
    {2, 7011, "Cosmofluxic Wand", 2, 0, 0, 0.0f, 0.0f, 0.0f, 0.0f, 2, 49, 0.01f, true},
    {3, 7003, "Theptoplasmar Amulet", 1, 0, 0, 0.0f, 0.0f, 0.0f, 0.0f, 2, 21, 0.01f, true},
    {4, 7002, "Synertauxic Ring", 1, 0, 0, 0.0f, 0.0f, 0.0f, 0.0f, 2, 35, 0.01f, true},
    {5, 7005, "Sublunarous Hat", 2, 0, 0, 0.0f, 0.0f, 0.0f, 0.0f, 2, 45, 0.01f, true},
    {6, 7005, "Combinator's Cap", 2, 0, 1, 0.10f, 0.0f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {7, 7006, "Combinator's Cape", 2, 0, 1, 0.10f, 0.0f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {8, 7004, "Combinator's Club", 2, 0, 1, 0.0f, 0.0f, 0.0f, 0.0f, 0, -1, 0.0f, true},
    {9, 7003, "Combinator's Choker", 1, 0, 1, 0.05f, 0.05f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {10, 7002, "Combinator's Circle", 1, 0, 1, 0.05f, 0.05f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {11, 7005, "Bug-Master's Cap", 2, 0, 2, 0.01f, 0.0f, 0.0f, 0.0f, 2, 11, 0.01f, false},
    {12, 7006, "Bug-Master's Robe", 2, 0, 2, 0.01f, 0.0f, 0.0f, 0.0f, 2, 11, 0.01f, false},
    {13, 7011, "Bug-Master's Wand", 1, 0, 2, 0.0f, 0.0f, 0.0f, 0.0f, 2, 11, 0.01f, true},
    {14, 7002, "Bug-Master's Loop", 1, 0, 2, 0.01f, 0.0f, 0.0f, 0.0f, 2, 11, 0.01f, false},
    {15, 7003, "Pan-Dimensional Strangler", 1, 0, 2, 0.01f, 0.0f, 0.0f, 0.0f, 2, 11, 0.01f, true},
    {16, 7005, "Cloudcover Hood", 2, 0, 3, 0.10f, 0.0f, 0.0f, 0.0f, 2, 27, 0.10f, false},
    {17, 7006, "Ozone Cape", 2, 0, 3, 0.02f, 0.0f, 0.0f, 0.0f, 2, 30, 0.02f, false},
    {18, 7004, "Lightning Rod", 2, 0, 3, 0.50f, 0.0f, 0.0f, 0.0f, 2, 24, 0.50f, false},
    {19, 7003, "Storm Choker", 1, 0, 3, 0.0f, 0.0f, 0.0f, 0.0f, 2, 27, 0.01f, true},
    {20, 7005, "Burning Hat", 2, 0, 4, 0.15f, 0.0f, 0.0f, 0.0f, 2, 16, 0.05f, false},
    {21, 7006, "Burning Robe", 2, 0, 4, 0.12f, 0.0f, 0.0f, 0.0f, 2, 23, 0.02f, false},
    {22, 7002, "Biting Ring", 2, 0, 5, 0.10f, 0.0f, 0.0f, 0.0f, 1, 3, 0.10f, false},
    {23, 7002, "Bitter Ring", 2, 0, 5, 0.10f, 0.0f, 0.0f, 0.0f, 1, 3, 0.10f, false},
    {24, 7003, "Glittering Amulet", 2, 0, 5, 0.02f, 0.0f, 0.0f, 0.0f, 2, 39, 0.01f, false},
    {25, 7006, "Potter's Apron", 2, 0, 6, 0.0f, 0.0f, 0.50f, 0.0f, 1, 4, 0.50f, false},
    {26, 7002, "Clayshaper's Ring", 2, 0, 6, 0.0f, 0.0f, 0.0f, 0.0f, 2, 45, 0.01f, true},
    {27, 7002, "Claybaker's Ring", 2, 0, 6, 0.0f, 0.0f, 0.0f, 0.0f, 2, 45, 0.01f, true},
    {28, 7011, "Kiln", 2, 0, 6, 0.0f, 0.0f, 0.0f, 0.0f, 2, 16, 0.02f, true},
    {29, 7003, "Obfuscate's Meddler", 1, 8, -1, 0.50f, 0.0f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {30, 7003, "Karen You Scandalous Wench", 2, 15, -1, 0.01f, 0.50f, 0.60f, 0.0f, 1, 5, 0.01f, false},
    {31, 7003, "Poxproof", 1, 30, -1, 0.0f, 0.0f, 0.0f, 1.0f, 0, -1, 0.0f, false},
    {32, 7003, "Ethereal Choker", 2, 10, -1, 0.06f, -0.15f, 0.0f, 0.0f, 2, 8, 0.02f, false},
    {33, 7004, "Absolox's Boomstick", 1, 5, -1, 0.0f, 0.0f, 0.0f, 0.0f, 2, 16, 0.02f, true},
    {34, 7004, "Staff of Dawn", 1, 15, -1, 0.02f, 0.0f, 0.0f, 0.0f, 1, 6, 0.02f, false},
    {35, 7002, "Ringwall", 1, 3, -1, 0.0f, 0.0f, 0.0f, 0.0f, 2, 54, 0.02f, true},
    {36, 7002, "Fleetfinger", 1, 10, -1, 0.0f, 0.0f, 1.0f, 0.0f, 0, -1, 0.0f, false},
    {37, 7002, "Gritchenscorn", 1, 10, -1, 0.0f, -0.77f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {38, 7002, "Mindblowing Ring", 1, 1, -1, 0.0f, 0.0f, 0.0f, 0.0f, 0, -1, 0.0f, true},
    {39, 7002, "Smartest Ring", 2, 20, -1, 0.01f, 0.0f, 0.0f, 0.0f, 0, -1, 0.0f, false},
    {40, 7005, "Yzmar's Handicap", 1, 3, -1, 0.0f, 0.0f, 0.0f, 0.0f, 2, 64, 0.01f, true},
    {41, 7011, "Qubar's Ether", 1, 10, -1, 0.50f, -0.50f, 0.0f, 0.0f, 1, 0, 0.50f, false},
    {42, 7011, "Qubar's Fire", 1, 10, -1, 0.50f, -0.50f, 0.0f, 0.0f, 1, 1, 0.50f, false},
    {43, 7011, "Qubar's Air", 1, 10, -1, 0.50f, -0.50f, 0.0f, 0.0f, 1, 2, 0.50f, false},
    {44, 7011, "Qubar's Water", 1, 10, -1, 0.50f, -0.50f, 0.0f, 0.0f, 1, 3, 0.50f, false},
    {45, 7011, "Qubar's Earth", 1, 10, -1, 0.50f, -0.50f, 0.0f, 0.0f, 1, 4, 0.50f, false},
    {46, 7006, "Robe of Thaumic Unperturbability", 2, 15, -1, -0.35f, -0.50f, -0.40f, 0.95f, 0, -1, 0.0f, false},
}};

const NativeItemPolicyCatalogEntry*
FindNativeItemPolicyCatalogEntry(
    std::uint32_t native_type_id,
    std::string_view name) {
    const auto found = std::find_if(
        kNativeItemPolicyCatalog.begin(),
        kNativeItemPolicyCatalog.end(),
        [&](const NativeItemPolicyCatalogEntry& entry) {
            return entry.native_type_id == native_type_id &&
                entry.name == name;
        });
    return found == kNativeItemPolicyCatalog.end()
        ? nullptr
        : &*found;
}
