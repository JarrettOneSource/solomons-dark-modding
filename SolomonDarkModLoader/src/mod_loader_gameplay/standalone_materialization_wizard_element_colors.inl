ElementColorDescriptor GetWizardElementColor(int wizard_id) {
    // Preserve the existing external bot API semantics:
    //   0 fire, 1 water, 2 earth, 3 air, 4 ether
    // The synthetic source-profile path seeds cloth color *before* the stock
    // descriptor build runs. The stock helper colors visible on player items
    // are the result of `Float4_GrayscaleMixClamp` / `FUN_0040FC60`, not the
    // raw source-profile cloth triplet itself. These values are therefore the
    // reconstructed pre-transform source colors that reproduce the observed
    // stock helper palettes for Fire/Water/Earth/Air.
    //
    // Reconstruction basis:
    //   helper = 0.2 * source + 0.8 * grayscale(source)
    //   grayscale(source) uses weights 0.3086 / 0.6094 / 0.0820
    //
    // Fire/Water/Earth/Air were solved from clean stock player helper items on
    // 2026-04-12. Ether was solved from a fresh same-element player/bot check
    // on 2026-04-13 after the public semantic remap.
    switch (wizard_id) {
        case 0: // Fire
            return {1.08003414f, 0.15461998f, 0.00474097f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 1: // Water
            return {0.18303899f, 0.51879197f, 0.94631803f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 2: // Earth
            return {-0.09265301f, 0.72661299f, -0.02961797f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 3: // Air
            return {0.01964684f, 1.01231515f, 1.02918804f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        case 4: // Ether
            return {1.05664342f, 0.10103842f, 0.99839842f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
        default: // Fallback to neutral gray
            return {0.6f, 0.6f, 0.6f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
    }
}
