const char* HazardKindLabel(HazardKind kind) {
    switch (kind) {
    case HazardKind::Projectile:
        return "projectile";
    case HazardKind::Area:
        return "area";
    case HazardKind::Beam:
        return "beam";
    default:
        return "unknown";
    }
}

bool TryResolveKnownHazardKind(
    std::uint32_t native_type_id,
    HazardKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    switch (native_type_id) {
    // Straight, ballistic, or guided contact actors.
    case 0x07D3: // MagicMissile
    case 0x07D4: // Fireball
    case 0x07D5: // Boulder
    case 0x07D6: // Ember
    case 0x07DA: // Arrow
    case 0x07DE: // FireMissile
    case 0x07DF: // BallLightning
    case 0x07E0: // FrostMissile
    case 0x07E1: // EBoulder
    case 0x07E2: // Meteor
    case 0x07E4: // Hailstones
    case 0x07E5: // GroundSpark
    case 0x07EB: // Firebolt
    case 0x07EC: // GuidedMissile
    case 0x07F3: // EtherBolt
    case 0x07FB: // UnholySpit
    case 0x0800: // SkullMissile
    case 0x0804: // DarkFireball
    case 0x0808: // Silk
    case 0x080B: // EvilEmber
    case 0x080C: // Comet
        *kind = HazardKind::Projectile;
        return true;

    // Persistent or expanding contact/status areas.
    case 0x07E3: // Fire
    case 0x07E6: // MovingFire
    case 0x07E7: // Shockwave
    case 0x07E8: // FreezeWave
    case 0x07E9: // Knockback
    case 0x07F0: // StormCloud
    case 0x07F1: // Earthquake
    case 0x07F5: // MagicTrap
    case 0x07F7: // DemonBomb
    case 0x07FA: // GreenFire
    case 0x07FE: // AcidRain
    case 0x0801: // RainOfBones
    case 0x0802: // TragicCircle
    case 0x0805: // DireFire
    case 0x0806: // PoisonPool
    case 0x0807: // EtherDrain
        *kind = HazardKind::Area;
        return true;

    case 0x07FF: // EyeLaser
        *kind = HazardKind::Beam;
        return true;
    default:
        return false;
    }
}

bool IsPinnedNonHazardEffectBandType(
    std::uint32_t native_type_id) {
    switch (native_type_id) {
    // Base/presentation wrappers, loot carriers, support effects, and summons.
    case 0x07D0:
    case 0x07D1:
    case 0x07D2:
    case 0x07D7:
    case 0x07D8:
    case 0x07D9:
    case 0x07DB:
    case 0x07DC:
    case 0x07DD:
    case 0x07EA: // MagicCircle: player support.
    case 0x07ED: // Gravestone: interaction/presentation.
    case 0x07EE: // Fire_Goodguy.
    case 0x07EF: // PlaneOrb: summoned actor.
    case 0x07F2: // Leviathan: summoned actor; its bolts are hazards.
    case 0x07F4: // Golem: summoned actor; covered by actor observations.
    case 0x07F6: // Bonus carrier.
    case 0x07F8:
    case 0x07F9:
    case 0x07FC:
    case 0x07FD:
    case 0x0809:
    case 0x080A: // Cocoon: target-owned actor.
    case 0x080D: // Goodie carrier.
    case 0x080E:
    case 0x080F: // OffscreenMagic presentation.
        return true;
    default:
        return false;
    }
}

bool IsUnknownEffectBandCandidate(
    std::uint32_t native_type_id) {
    return native_type_id >= 0x07D3 &&
           native_type_id <= 0x080F &&
           !IsPinnedNonHazardEffectBandType(
               native_type_id);
}

bool IsHomingHazardType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x07D3: // MagicMissile
    case 0x07DE: // FireMissile
    case 0x07DF: // BallLightning
    case 0x07E0: // FrostMissile
    case 0x07EC: // GuidedMissile
    case 0x0800: // SkullMissile
        return true;
    default:
        return false;
    }
}

bool IsHazardSyntheticUnknownProbeEnabled() {
    char value[8] = {};
    const auto length = GetEnvironmentVariableA(
        "SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD",
        value,
        static_cast<DWORD>(std::size(value)));
    return length == 1 && value[0] == '1';
}
