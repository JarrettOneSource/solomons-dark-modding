void RestoreBoneyardGeneratorPatch() {
    if (!g_boneyard_generator_patch.installed ||
        g_boneyard_generator_patch.empty_candidate_address == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    for (auto& hook :
         g_boneyard_generator_patch.presentation_hooks) {
        RemoveX86Hook(&hook);
    }
    if (g_boneyard_generator_patch.marker_primary_tint_rng_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .marker_primary_tint_rng_address,
            kBoneyardMarkerPrimaryTintRngOriginalBytes.data(),
            kBoneyardMarkerPrimaryTintRngOriginalBytes.size());
    }
    if (g_boneyard_generator_patch.compact_ambient_rng_gate_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .compact_ambient_rng_gate_address,
            kBoneyardCompactAmbientRngOriginalBytes.data(),
            kBoneyardCompactAmbientRngOriginalBytes.size());
    }
    if (g_boneyard_generator_patch.secondary_ambient_rng_gate_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .secondary_ambient_rng_gate_address,
            kBoneyardSecondaryAmbientRngOriginalBytes.data(),
            kBoneyardSecondaryAmbientRngOriginalBytes.size());
    }
    if (g_boneyard_generator_patch.marker_secondary_tint_rng_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .marker_secondary_tint_rng_address,
            kBoneyardMarkerSecondaryTintRngOriginalBytes.data(),
            kBoneyardMarkerSecondaryTintRngOriginalBytes.size());
    }
    for (const auto address :
         g_boneyard_generator_patch.compact_flags_addresses) {
        if (address == 0) {
            continue;
        }
        (void)memory.TryWrite(
            address,
            kBoneyardCompactFlagsOriginalBytes.data(),
            kBoneyardCompactFlagsOriginalBytes.size());
    }
    (void)memory.TryWrite(
        g_boneyard_generator_patch.empty_candidate_address,
        kBoneyardGeneratorOriginalBytes.data(),
        kBoneyardGeneratorOriginalBytes.size());
    g_boneyard_generator_patch = {};
}
