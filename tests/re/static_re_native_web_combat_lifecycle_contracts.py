"""Static contract for the native-to-Website survival combat integration note."""

from __future__ import annotations

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


REPORT = ROOT / "docs/reverse-engineering/native-web-combat-lifecycle.md"


def _require_tokens(text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "native/web combat lifecycle report is missing contract token(s): "
            + ", ".join(missing)
        )


def test_native_web_combat_lifecycle_integration_contract_is_pinned() -> str:
    report = read_text(REPORT)
    _require_tokens(
        report,
        (
            "native-solomon-dig-and-wave-director.md",
            "native-enemy-behavior.md",
            "native-progression-and-skills.md",
            "native-player-death-spectator.md",
            "native-game-over-session-semantics.md",
            "post-retirement live count",
            "newly materialized actors do not step until the next tick",
            "primary, secondary, tertiary, and extra damage lanes times",
            "`LEADING`, `SCATTERSHOT`, `RANDOMSHOT`",
            "`RANGEUP`, `RANGEDOWN`, `RANGEEASY`",
            "`SHIELD`, `SHIELDOTHERS`",
            "`SPLIT`: split count 1..2; `SPLITMANY`",
            "`ARMORMAYBE`",
            "`NOSKELETONS` and `MORESKELETONS`",
            "explicit resource-safety bound",
            "a second deliberate Website product deviation",
            "one deterministic dynamic-contact set",
            "stages the semantic target identity",
            "marker-time geometry",
            "Maggot helper `0x00479C30` exactly three times",
            "## Active Archer, Mage, and Wraith modifiers",
            "change authoritative aim",
            "self/ally shields remain separate lanes",
            "constructs `Mod_Dazzle` type `0x1B6E`",
            "`+0x14 = 0x32`",
            "`Mod_Dazzle::Tick 0x00623490`",
            "`+0x20 = 1 / duration`",
            "`+0x120`",
            "50-tick recovery ramp",
            "effective skill-book rank",
            "indexes the catalog mana and damage arrays",
            "rank-indexed damage payload when emitted",
            "Rank-one constants are fixtures",
            "Shield current/maximum health",
            "poison payload subtype",
            "Dazzle, and poison status counters",
            "zero/default reconstruction",
            "unconditional `effects: []`",
            "consume each new semantic event exactly once",
            "player death tick `FUN_00533520`",
            "`Anim_FadeMoveAdditive_Perspective` burst",
            "render bias `+0xA0 = -1000`",
            "BadGuys record 10",
            "without late-join replay",
            "## Named Website completion bounds (not native evidence)",
            "Coffin is excluded from this direct-action list",
            "(120,240)`, `(80,180)`, `(180,320)`, `(100,320)`",
            "terminal presentation windows are Coffin 31, Demon 49, Imp 19",
            "Arrow `(5,8,300,false)`",
            "one child every 50 ticks",
            "24-tick ballistic emergence",
            "post-emergence attack delay",
            "successful bite",
            "12-tick terminal",
            "authoritative child step",
            "launch-vector\n  distributions remain open",
            "300 ticks at movement scale 0.5",
            "Wraith collision radius is 20",
            "`min(15, max(2, 1 + floor(waveOrdinal / 3)))`",
            "strongest damage-per-tick lane and the longest",
            "point path (radius 0)",
            "explicit 500-tick safety horizon",
            "unlabeled or unbounded retirement",
        ),
    )

    stale_claims = (
        "`STRONG`/`WEAK`: primary damage times 1.5/0.5",
        "Coffin open marker/end `10/12`",
        "verticalHeight",
        "containment horizon is not native lifetime evidence and must give way",
        "They do not permit client authority,\nage-based retirement",
    )
    present = [claim for claim in stale_claims if claim in report]
    if present:
        raise StaticReTestFailure(
            "native/web combat lifecycle report retained stale claim(s): "
            + ", ".join(present)
        )

    return (
        "native/web combat ownership, effective-rank payloads, active modifiers, "
        "strict replication, product deviations, and named completion bounds are pinned"
    )
