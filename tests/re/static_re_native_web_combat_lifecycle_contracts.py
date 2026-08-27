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
            "native-enemy-hit-and-death-effects.md",
            "post-retirement live count",
            "newly materialized actors do not step until the next tick",
            "primary, secondary, tertiary, and extra damage lanes times",
            "`LEADING`, `SCATTERSHOT`, `RANDOMSHOT`",
            "`RANGEUP`, `RANGEDOWN`, `RANGEEASY`",
            "`SHIELD`, `SHIELDOTHERS`",
            "`SPLIT`: remaining split depth 1..2. `SPLITMANY`",
            "`q = trunc((wave - 25) / 5)`",
            "inclusive range `[q + 1,q + 3]`",
            "a second independent draw",
            "`ARMORMAYBE`",
            "`NOSKELETONS` and `MORESKELETONS`",
            "explicit resource-safety bound",
            "a second deliberate Website product deviation",
            "one deterministic dynamic-contact set",
            "stages the semantic target identity",
            "marker-time geometry",
            "`actorRadius + targetRadius + 0.1`",
            "greater of the named center reach",
            "nativeSeparationEpsilon",
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
            "Shared helper\n`0x0052B150` is called with `rejectIfInsufficient=0`",
            "zero-MP pure-primary casts therefore all\nmaterialize through a fixed weak branch",
            "`max(0.25,min((base*charge)*charge,base*1.25))`",
            "Rank-one constants are\nfixtures",
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
            "## Hit and terminal-effect ownership",
            "damage reaction `0x00627F80`",
            "subtracts exactly `0.05` per fixed tick",
            "20-tick refreshed overlay",
            "shipped-default Enhanced Effects shatter sequence",
            "fresh\n50-percent horizontal-damping RNG draw on every ground contact",
            "Skeleton family\n`.75/.0225`",
            "initial alpha `1.25`",
            "Demon and Maggot do not create\nUnbind",
            "Persistent effect\nactors replicate as entity state",
            "## Named Website completion bounds (not native evidence)",
            "Coffin is excluded from this direct-action list",
            "(120,240)`, `(80,180)`, `(180,320)`, `(100,320)`",
            "terminal presentation windows are Demon 49, Imp 19",
            "Arrow `(5,8,300,false)`",
            "`ratio=charge/(baseSpeed*timeScale)`",
            "`Float(ratio)<1`",
            "Births are not capped",
            "two recovered launch segments/headings",
            "retained `+/-1` X scale and signed\n  `Float(15)` rotation",
            "two\n  independent `Float(8)` offsets",
            "`Float(5)` visual phase advances by\n  float32 `0.25` modulo five",
            "there\n  is no 24-tick duration",
            "`Integer(5)==3`",
            "first 30 inactive children remain noncombat",
            "invalid or non-Coffin parent retires every child lane",
            "300 ticks at movement scale 0.5",
            "Wraith collision radius is 20",
            "each permitted death emits two children at one-lower depth",
            "pre-pair live-Imp guard is 68",
            "persistent Imp construction is capped at",
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
        "`SPLIT`: split count 1..2; `SPLITMANY`",
        "`min(15, max(2, 1 + floor(waveOrdinal / 3)))`",
        "reject insufficient mana before materialization",
        "one child every 50 ticks",
        "24-tick ballistic emergence",
        "launch-vector\n  distributions remain open",
        "separate bounded child program",
        "terminal presentation windows are Coffin 31",
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
