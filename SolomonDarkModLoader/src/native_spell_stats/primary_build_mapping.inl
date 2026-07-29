struct NativePrimaryBuildMapping {
    int native_build_id;
    int normalized_build_id;
    int primary_entry_index;
    int combo_entry_index;
};

constexpr std::array<NativePrimaryBuildMapping, 20>
    kNativePrimaryBuildMappings = {{
        {1000, 1000, 0x08, 0x10},
        {1001, 1001, 0x08, 0x20},
        {1002, 1002, 0x08, 0x18},
        {1003, 1003, 0x10, 0x18},
        {1004, 1004, 0x20, 0x18},
        {1005, 1005, 0x10, 0x20},
        {1006, 1006, 0x08, 0x28},
        {1007, 1007, 0x10, 0x28},
        {1008, 1008, 0x20, 0x28},
        {1009, 1009, 0x18, 0x28},
        {0x3F2, 0x08, 0x08, 0x08},
        {0x3F3, 0x10, 0x10, 0x10},
        {0x3F4, 0x20, 0x20, 0x20},
        {0x3F5, 0x18, 0x18, 0x18},
        {0x3F6, 0x28, 0x28, 0x28},
        {0x08, 0x08, 0x08, 0x08},
        {0x10, 0x10, 0x10, 0x10},
        {0x20, 0x20, 0x20, 0x20},
        {0x18, 0x18, 0x18, 0x18},
        {0x28, 0x28, 0x28, 0x28},
    }};

const NativePrimaryBuildMapping* FindNativePrimaryBuildMapping(
    int native_build_id) {
    const auto it = std::find_if(
        kNativePrimaryBuildMappings.begin(),
        kNativePrimaryBuildMappings.end(),
        [&](const NativePrimaryBuildMapping& mapping) {
            return mapping.native_build_id == native_build_id;
        });
    return it == kNativePrimaryBuildMappings.end() ? nullptr : &(*it);
}

const NativePrimaryBuildMapping* FindNativePrimaryPairMapping(
    int primary_entry_index,
    int combo_entry_index) {
    const auto it = std::find_if(
        kNativePrimaryBuildMappings.begin(),
        kNativePrimaryBuildMappings.end(),
        [&](const NativePrimaryBuildMapping& mapping) {
            return
                (mapping.primary_entry_index == primary_entry_index &&
                 mapping.combo_entry_index == combo_entry_index) ||
                (mapping.primary_entry_index == combo_entry_index &&
                 mapping.combo_entry_index == primary_entry_index);
        });
    return it == kNativePrimaryBuildMappings.end() ? nullptr : &(*it);
}
