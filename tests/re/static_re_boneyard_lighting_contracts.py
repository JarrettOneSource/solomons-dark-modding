"""Static contracts for the recovered Boneyard Tree render-lighting path."""

from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


def _read(relative_path: str) -> str:
    return (ROOT / Path(relative_path)).read_text(encoding="utf-8")


def test_boneyard_tree_last_writer_render_path_is_registered() -> str:
    findings = _read(
        "docs/reverse-engineering/native-default-boneyard-load-seed-and-decor.md"
    )
    layout = _read("config/binary-layout.ini")

    required_findings = (
        "common scenery render dispatcher",
        "`0x00624B40`",
        "`0x00624C2F`",
        "`0x00624C4E`",
        "`0x00624C89`",
        "`0x00624D3E`",
        "`0x00624DAD`",
        "`0x00624DC7`",
        "overlay entry",
        "`0x00608830`",
        "`0x00608912`",
        "`0x3DD62F07`",
        "`0x3E145B97`",
        "last-writer failure",
    )
    missing_findings = [
        token for token in required_findings if token not in findings
    ]
    if missing_findings:
        raise StaticReTestFailure(
            "Boneyard Tree render-lighting findings are incomplete: "
            + ", ".join(missing_findings)
        )

    required_layout = (
        "scenery_render_lighting=0x00624B40",
        "scenery_render_lighting_common_scalar_write_0=0x00624C2F",
        "scenery_render_lighting_common_scalar_write_1=0x00624C4E",
        "scenery_render_lighting_common_scalar_write_2=0x00624C89",
        "scenery_render_lighting_common_scalar_write_3=0x00624D3E",
        "scenery_render_lighting_common_scalar_write_4=0x00624DAD",
        "scenery_render_lighting_common_scalar_write_5=0x00624DC7",
        "tree_render_overlay=0x00608830",
        "tree_render_overlay_common_scalar_read=0x00608912",
        "boneyard_scenery_common_scalar=0xCC",
    )
    missing_layout = [token for token in required_layout if token not in layout]
    if missing_layout:
        raise StaticReTestFailure(
            "Boneyard Tree render-lighting layout is incomplete: "
            + ", ".join(missing_layout)
        )

    return (
        "Boneyard Tree +0xCC last-writer render path and final overlay read "
        "are documented and registered"
    )


def test_complete_native_lighting_and_shadow_system_is_registered() -> str:
    chart = _read("docs/reverse-engineering/native-lighting-and-shadow-system.md")
    world = _read("docs/reverse-engineering/native-boneyards-and-world.md")
    composition = _read("docs/reverse-engineering/native-scene-composition.md")
    projectile = _read(
        "docs/reverse-engineering/native-projectile-and-spell-mechanics.md"
    )
    earth_catalog = _read(
        "docs/reverse-engineering/earth-boulder-vfx-catalog.json"
    )

    required_chart = (
        "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
        "**Persistent provider lane.**",
        "**One-tick miscellaneous lane.**",
        "**Raster lane.**",
        "**Analytic lane.**",
        "`0x005BAB60`",
        "`0x00B3BCAE`",
        "`Game.MultipleShadows`",
        "capability byte = true",
        "`Game.LightQuality`",
        "`0.25f`",
        "`0.05999999865889549f`",
        "`0x0057DF20`",
        "`0x0057D4E0`",
        "`0x0057D670`",
        "`0x0057FE40`",
        "`0x0057E2F0`",
        "`0x0057FC00`",
        "`0x0057F980`",
        "`0x0057F0E0`",
        "`0x00401110`",
        "`0x00401170`",
        "`RandomFloat 0x00401310`",
        "`RandomInt(100001,false)`",
        "100,001-point lattice",
        "stable semantic 32-bit owner/frame word",
        "normalize source/query coordinates",
        "byte 127, not 128",
        "`0x00624B40`",
        "`0x005299A0 -> 0x00580130`",
        "process-local actor",
        "`float32(phase*0.8999999761581421)`",
        "`rasterGlyphScale`",
        "`0x00474970`",
        "`0x004779E0`",
        "`0x00478180`",
        "`0x004783E0`",
        "`0x00478CC0`",
        "`0x00478E00`",
        "`0x00479470`",
        "`0x00479EA0`",
        "`0x00479F80`",
        "`0x0047A040`",
        "`0x0047BED0`",
        "`0x005EA110`",
        "`0x005E4AF0`",
        "`0x005E6220`",
        "`0x005E50D0`",
        "`0x005E5670`",
        "`0x005E48E0`",
        "`0x005E5960`",
        "`0x005E6140`",
        "`0x005E7040`",
        "`0x005E7420`",
        "`0x005E7610`",
        "`0x005E7800`",
        "`0x005E7AA0`",
        "`0x005E90C0`",
        "`0x005E9160`",
        "`0x005E94C0`",
        "`0x005E97A0`",
        "`0x005E9840`",
        "`0x005E98E0`",
        "`0x005EB5C0`",
        "`0x005EBD90`",
        "`0x005EE780`",
        "`0x005F0DB0`",
        "`0x005F18A0`",
        "`0x0044F4B0`",
        "`0x00531640`",
        "`0x00451576`",
        "`0x00460C44`",
        "`0x00531D61`",
        "`0x00531EBE`",
        "`0x00532734`",
        "`0x00532891`",
        "`0x005331B5`",
        "`0x00533312`",
        "`0x00600834`",
        "`0x00605742`",
        "`0x00628FE8`",
        "`0x00629CAE`",
        "`0x00629ED8`",
        "### Website-modeled enemy projectile dispositions",
        "### Website-modeled enemy actor dispositions",
        "### Other Website active and dormant dispositions",
        "Zombie | no persistent provider",
        "PoisonPool | no provider lane",
        "`banish`, `bouncer`, `fade`, `move-fade`",
        "`[350,350,450,550,650]`",
        "### SkeletonMage sustained lightning ownership",
        "`+0x280 = trunc((100*0.5)/attackSpeed)`",
        "once on every",
        "BadGuys `381/382` approximation is disproven",
        "target-local attachment",
        "target-following post-main overlay",
        "no ZAnimLit wrapper",
        "n = normalize(edge.dy, -edge.dx)",
        "dot(n, edgeMidpoint - lightSource) > 0",
        "Tree | `0x00608AB0`",
        "Gravestone | `0x0060F260`",
        "FenceGrate | `0x00600ED0`",
        "Rails | `0x00607440`",
        "Wall | `0x0061E780 -> 0x006561A0`",
        "before the exact owner at equal painter depth",
        "shared 256-entry alpha",
        "ramp texture",
        "no per-edge canvas, texture, gradient object",
    )
    missing_chart = [token for token in required_chart if token not in chart]
    if missing_chart:
        raise StaticReTestFailure(
            "Complete native lighting/shadow chart is incomplete: "
            + ", ".join(missing_chart)
        )

    stale_projectile_claims = (
        "Boulder body likewise enters `Puppet_RenderDispatch` through vslot `+0x0C`\n"
        "and samples Region light at its own world position; it has no recovered\n"
        "outbound light.",
    )
    if any(claim in projectile for claim in stale_projectile_claims):
        raise StaticReTestFailure(
            "Boulder lighting ledger still denies provider 0x005E5670"
        )
    for token in ("`0x005E5670`", "`max(1,2*charge)`"):
        if token not in projectile:
            raise StaticReTestFailure(
                f"Boulder provider reconciliation is missing {token}"
            )
    for token in ("provider 0x005E5670", "max(1,2*charge)", "intensity 0.5"):
        if token not in earth_catalog:
            raise StaticReTestFailure(
                f"Earth VFX catalog lost the outbound Boulder light: {token}"
            )
    if "no recovered outbound light" in earth_catalog:
        raise StaticReTestFailure(
            "Earth VFX catalog still denies the recovered Boulder provider"
        )

    stale_mage_claims = (
        "records `381` and `382` are the registered lightning source and target art",
        "one immutable, run-scoped `mage-lightning` semantic event",
        "recovered Mage lightning presentation",
    )
    present_mage_claims = [
        claim for claim in stale_mage_claims if claim in projectile or claim in chart
    ]
    if present_mage_claims:
        raise StaticReTestFailure(
            "Lighting ledgers retain superseded one-shot Mage claims: "
            + ", ".join(present_mage_claims)
        )

    stale_claims = {
        "native-boneyards-and-world.md": (
            world,
            (
                "`Multiple Shadows` setting, whose retail default is off",
                "`Game.MultipleShadows` setting (`0x00B3BCAA`) defaults to false",
                "rejects edges that do not face the source",
            ),
        ),
        "native-scene-composition.md": (
            composition,
            (
                "projects its source-facing outline edges",
                "keeps only source-facing outline edges",
                "which defaults off",
            ),
        ),
    }
    for name, (text, forbidden) in stale_claims.items():
        present = [token for token in forbidden if token in text]
        if present:
            raise StaticReTestFailure(
                f"{name} retains superseded lighting claims: " + ", ".join(present)
            )

    return (
        "Complete native lighting lanes, defaults, source census, exact shadow "
        "programs, painter ownership, and retained-resource contract are registered"
    )
