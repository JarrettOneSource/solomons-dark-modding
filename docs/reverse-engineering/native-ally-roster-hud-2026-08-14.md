# Native ally-roster HUD producers and presentation

## Scope

This report closes the native ownership question behind the compact ally health
rows: which objects publish them, what state each publisher owns, how the shared
renderer presents them, and which summon types actually participate. It is the
durable source for the Website ally-roster reconstruction. The wider HUD census
remains in [`native-hud.md`](native-hud.md).

## Evidence and provenance

The binary work used the clean retail `SolomonDark.exe` with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Fresh read-only headless Ghidra queries on 2026-08-14 decompiled the shared
renderer `0x005D2520`, enumerated all direct references to append function
`0x005CF480`, and decompiled both callers. The exact stock art comes from:

- `UI.bundle` SHA-256
  `1db00ea8826e787ca9a320c90a33e726991cae00906baddfdc8bde31da697498`;
- `UI.png` SHA-256
  `37d5e8fc543af12a9d8019e738dbe1e29b648211144a3782c3a32e71f76cd2eb`;
- `Fonts.bundle` SHA-256
  `048aa22cc715ee633f5e31f0400b4a3a9c0a8c8b49d681419e19d5ff676c214a`;
  and
- `Fonts.png` SHA-256
  `dcdcd9697624996376348a4f6d6a2d730adaab98730a7fcbc6ee88f7433db782`.

The settled retail two-participant HUD receipt is
`/mnt/d/codex-evidence/uire-20260806/hud-crops/20260806T115705Z/two-participant-ally-bar.png`
(SHA-256 `529a6f7fec4d973bada2140d57d542428d7e6eb4d25df5b152b7b2c69a8c7fe9`).
The existing host-owned and client-owned Golem receipts are respectively:

- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/host_owned/host.png`
  (SHA-256 `7c5ce25e89f649535632b9610447a33beff023a8882503d44a5cb19a20f48545`);
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/client_owned/client.png`
  (SHA-256 `a0f95f4af5a1690b44cbf9de6c3ed06fd66eb406db253af3796a5ad7bd33aa5d`).

The Golem receipts exercise loader multiplayer synchronization, while the
Golem row producer and label selection described below are stock code. They are
not presented as an untouched-retail multiplayer capture.

## Ownership thread

`0x005CF480` appends one eight-byte `{glyph, health_ratio}` entry to the
gameplay-owned vector at `+0x1C14/+0x1C18/+0x1C20`. The complete stock program
has exactly two direct references to that append function:

| Producer | Call site | Identity | Health owner | Eligibility |
| --- | --- | --- | --- | --- |
| Player/control-brain path `0x0052C910` | `0x0052D2A4` | stock `UI.0`, the 26 x 7 `ALLY` glyph | the participant progression/vitals path supplies the ratio | a nonlocal durable living participant; multiplayer loader presentation replaces `ALLY` with the exact participant name |
| Golem tick `0x00615CD0` | `0x00617804` | `DAT_008199E4 + 0x11D4`, which resolves to `UI.23`, the 37 x 7 `GOLEM` glyph | Golem current HP `+0x170` divided by maximum HP `+0x174` | only while the Golem death flag at `+0x94` is clear |

The resulting causal chain is:

```text
durable remote participant ----> player row producer --+
                                                        |
live Golem + authoritative HP --> Golem row producer ---+--> gameplay row vector
                                                               |
                                                               v
                                                        HUD renderer 0x005D2520
```

The renderer does not distinguish player and Golem rows after publication.
Identity selection, health ownership, and lifecycle eligibility stay with the
producer; ordering, row pitch, tint, and bar geometry belong to the shared HUD
consumer.

## Exact renderer contract

The `0x005D3408..0x005D3669` loop establishes the following contract at the
retail 1600 x 900 backbuffer:

1. The first row cursor is `25` in the active HUD-local coordinate system.
2. Each iteration draws identity first and health second.
3. The loop increments its row cursor by the double constant at `0x007DE810`,
   whose value is exactly `10`. The prior 20-pixel report was stale.
4. Row zero's health quad is `[560,39.5,610,44.5]`: 50 x 5, left anchored,
   with live width `50 * clamp(ratio, 0, 1)`.
5. The identity reservation is `[612,39,740,46]`. Stock fixed identities are
   seven pixels high and begin two pixels to the right of the bar.
6. At `0x005D342A`, the renderer constructs the identity color
   `(0.85, 0.73, 0.44, 1)`. At `0x005D3521`, it switches to
   `(1, 0.5, 0.5, 1)` for the health quad.
7. Additional rows repeat at `y + 10`, before concentration emblems and the
   later HUD tail.

The multiplayer participant-name replacement retains the same row slot and
color state. It draws `Fonts` group 6 (`376..442`) through stock ExactText at
quarter scale, with the name origin two HUD units after the bar and baseline
seven units below the row cursor. That font is a bundle wrapper, not a system
font: glyph metrics, the 1,043-pair kerning table, and sprite registration all
participate. The loader's 4-pixel non-space/2-pixel space values are a bounded
reservation estimate, not a replacement for the native glyph metrics.

## Lifecycle and state contract

- Participant identity comes from the durable connected roster, not an actor
  pointer that can disappear during a room or scene epoch.
- The local participant never receives a row. Remote rows are removed on
  disconnect, authoritative death, or epoch replacement and are rebuilt after
  convergence.
- Health is an authoritative producer value. The renderer consumes a ratio and
  performs no interpolation or smoothing.
- A Golem row exists only while that Golem instance exists and its death flag is
  clear. Its current/max HP fields, not its animation age or render frame, own
  the bar.
- The vector is frame-local HUD publication. It is not a persistence store for
  participant or summon state.

## Adjacent-system audit

The two-xref census is a useful negative result. Leviathan and Good Imp do not
directly publish through `0x005CF480` in the stock executable. Golem therefore
must be supported by a future shared roster-row seam, but the web port must not
generalize every future summon into this panel without separate native
evidence. Wizard clones remain PlayerWizard-family participants rather than a
third minion HUD producer.

World-space participant nameplates and health bars are a different render lane.
They follow actors/camera and must not be merged with this fixed screen-space
list. Local health/mana, concentration emblems, notifications, and the cursor
also remain separate consumers in the wider HUD census.

## Confidence and remaining unknowns

Confidence is high for producer membership, the Golem offsets and label,
append ABI, ordering, colors, bar geometry, and 10-pixel pitch. The exact
ordering policy if several simultaneously owned Golems coexist was not needed
for this reconstruction and remains unproven. No claim is made that Leviathan,
Good Imp, or an unimplemented web summon should use this lane.
