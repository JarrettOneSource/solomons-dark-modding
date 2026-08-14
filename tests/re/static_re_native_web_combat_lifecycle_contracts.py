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
            "## Named Website completion bounds (not native evidence)",
            "Coffin open marker/end `10/12`",
            "Archer and Mage range-control minima are 120 and 100 world units",
            "terminal presentation windows are Coffin 31, Demon 49, Imp 19",
            "Arrow `(5,8,300,false)`",
            "Maggot movement step, collision radius, attack reach, and death window",
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
        "native/web combat ownership, tick order, product deviations, and named "
        "completion bounds are pinned"
    )
