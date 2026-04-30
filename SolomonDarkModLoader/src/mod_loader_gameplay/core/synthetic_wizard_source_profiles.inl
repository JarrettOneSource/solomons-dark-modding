struct ElementColorDescriptor {
    float primary_r, primary_g, primary_b, primary_a;
    float secondary_r, secondary_g, secondary_b, secondary_a;
};

ElementColorDescriptor GetWizardElementColor(int wizard_id);
int ResolveStandaloneWizardRenderSelectionIndex(int wizard_id);

struct WizardSourceProfileTemplate {
    std::int8_t variant_primary = 0;
    std::int8_t variant_secondary = 0;
    std::int8_t weapon_type = 1;
    std::uint8_t variant_tertiary = 0;
};

struct WizardAppearanceChoiceIds {
    int primary_a = 0;
    int primary_b = 8;
    int primary_c = 0x0B;
    int secondary = 7;
};

// Gameplay-slot actors and temporary source actors are not the same contract.
// Real gameplay-slot actors settle at `0/0/0/1/0`, but the stock source/preview
// side compiles a fuller wizard render window before helper-item and attachment
// extraction. Keep the gameplay-slot actor clean later; let the source actor
// use the richer selector window so `ActorBuildRenderDescriptorFromSource` can
// still synthesize the staff/orb attachment and helper visuals.
constexpr WizardSourceProfileTemplate kWizardSourceProfileTemplates[] = {
    {1, 1, 1, 0},  // fire source actor
    {1, 1, 1, 0},  // water source actor
    {1, 1, 1, 0},  // earth source actor
    {1, 1, 1, 0},  // air source actor
    {1, 1, 1, 0},  // ether source actor
};
constexpr int kWizardSourceProfileTemplateCount =
    static_cast<int>(sizeof(kWizardSourceProfileTemplates) / sizeof(kWizardSourceProfileTemplates[0]));

WizardAppearanceChoiceIds ResolveWizardAppearanceChoiceIds(int wizard_id) {
    switch ((std::max)(0, (std::min)(wizard_id, 4))) {
    case 0:
        return {1, 0x10, 0x15, 6};   // fire + arcane
    case 1:
        return {3, 0x20, 0x23, 6};   // water + arcane
    case 2:
        return {4, 0x28, 0x2D, 6};   // earth + arcane
    case 3:
        return {2, 0x18, 0x1B, 6};   // air + arcane
    case 4:
    default:
        return {0, 0x08, 0x0B, 6};   // ether + arcane
    }
}

std::int32_t ResolveProfileElementId(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return character_profile.element_id;
}

bool HasExplicitProfileAppearanceChoices(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return std::all_of(
        character_profile.appearance.choice_ids.begin(),
        character_profile.appearance.choice_ids.end(),
        [](std::int32_t value) {
            return value >= 0;
        });
}

WizardAppearanceChoiceIds ResolveProfileAppearanceChoiceIds(
    const multiplayer::MultiplayerCharacterProfile& character_profile) {
    if (HasExplicitProfileAppearanceChoices(character_profile)) {
        return {
            character_profile.appearance.choice_ids[0],
            character_profile.appearance.choice_ids[1],
            character_profile.appearance.choice_ids[2],
            character_profile.appearance.choice_ids[3],
        };
    }

    auto choice_ids = ResolveWizardAppearanceChoiceIds(ResolveProfileElementId(character_profile));
    switch (character_profile.discipline_id) {
    case multiplayer::CharacterDisciplineId::Mind:
        choice_ids.secondary = 4;
        break;
    case multiplayer::CharacterDisciplineId::Body:
        choice_ids.secondary = 5;
        break;
    case multiplayer::CharacterDisciplineId::Arcane:
    default:
        choice_ids.secondary = 6;
        break;
    }
    return choice_ids;
}

uintptr_t CreateSyntheticWizardSourceProfile(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    const auto wizard_id = ResolveProfileElementId(character_profile);
    const auto& profile = kWizardSourceProfileTemplates[
        (wizard_id >= 0 && wizard_id < kWizardSourceProfileTemplateCount) ? wizard_id : 0];
    const auto element_color = GetWizardElementColor(wizard_id);

    auto* buffer = static_cast<std::uint8_t*>(_aligned_malloc(kSyntheticSourceProfileSize, 16));
    if (buffer == nullptr) {
        return 0;
    }
    std::memset(buffer, 0, kSyntheticSourceProfileSize);

    // +0x4C must be 3 or FUN_005E3080 returns early
    *reinterpret_cast<std::int32_t*>(buffer + kSourceProfileVisualSourceTypeOffset) =
        kStandaloneWizardVisualSourceKind;

    // Variant bytes that drive the wizard descriptor build and staff/orb
    // attachment creation while the synthetic source profile is staged. The
    // coarse render-selection byte is the stock element branch consumed by the
    // attachment/orb path; keep it aligned with the public element semantics.
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantPrimaryOffset) =
        profile.variant_primary;
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantSecondaryOffset) =
        profile.variant_secondary;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileRenderSelectionOffset) =
        static_cast<std::uint8_t>(ResolveStandaloneWizardRenderSelectionIndex(wizard_id));
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileWeaponTypeOffset) =
        profile.weapon_type;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileVariantTertiaryOffset) =
        profile.variant_tertiary;

    auto write_color = [&](std::size_t offset, float r, float g, float b, float a) {
        *reinterpret_cast<float*>(buffer + offset + 0x00) = r;
        *reinterpret_cast<float*>(buffer + offset + 0x04) = g;
        *reinterpret_cast<float*>(buffer + offset + 0x08) = b;
        *reinterpret_cast<float*>(buffer + offset + 0x0C) = a;
    };
    write_color(
        kSourceProfileClothColorOffset,
        element_color.primary_r,
        element_color.primary_g,
        element_color.primary_b,
        element_color.primary_a);
    write_color(
        kSourceProfileTrimColorOffset,
        element_color.secondary_r,
        element_color.secondary_g,
        element_color.secondary_b,
        element_color.secondary_a);

    return reinterpret_cast<uintptr_t>(buffer);
}

void DestroySyntheticWizardSourceProfile(uintptr_t address) {
    if (address != 0) {
        _aligned_free(reinterpret_cast<void*>(address));
    }
}
