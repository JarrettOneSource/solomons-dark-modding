# Native retail in-run HUD (G9)

This is the implementation contract for Solomon's Dark's retail gameplay HUD. It closes browser-rebuild gap G9 for the retail executable and is intended to be sufficient for an implementing agent to rebuild the HUD without opening the binary. The checked-in live recording is [`hud-goldens.json`](../../tests/fixtures/webgame/hud-goldens.json); every rectangle and state value below comes from that recording or an addressable native layout path, never from eyeballing a screenshot.

## Scope and ownership

This document owns only presentation drawn during play: cast cards and belt slots, XP, local health/mana and their conditional layers, top-center ally rows, concentration emblems, the aim cursor, transient pickup text, and their visibility and scaling rules.

- G11 owns every pre-gameplay or overlay **screen**, including title, settings, pause, the level-up picker, and Game Over. Those surfaces are already specified in [`native-menus-and-boot.md`](native-menus-and-boot.md) and are not re-derived here.
- G12 owns frame composition. Its five-pass contract places this HUD in `screen-overlay`, after `scene-overdraw`, in screen coordinates that do not move with the Region camera. See [`native-scene-composition.md`](native-scene-composition.md#layers-backmost-to-frontmost). G9 specifies what the HUD draws and its order inside that pass.
- World-projected participant names/health bars, target markers, actor hit tint, potion carriers, and red edge/death feedback remain `scene-overdraw` or G12 screen feedback. They are not extra members of the 26-element HUD census.

The native renderer is `0x005D2520`. It reads the shared viewport and UI pen from `*0x00B401A8`, renders a baseline sequence of 36 sprite/quad calls for the captured loadout, renders transient notification text through `0x005CF000`, then executes the cursor/fade tail at `0x005D3D48`. The belt/skill renderer is `0x005D3E10`; the repeated strip renderer is `0x00415230`; clip save/apply/restore are `0x00427300`, `0x00420EC0`, and `0x00421380`.

This census closes the gameplay-HUD entries and renderer ownership mapped in [`ui-binary-map.md`](../ui-binary-map.md) and [`ui-engine-system-map.md`](../ui-engine-system-map.md). Those documents remain the system-level index; the rects, conditional membership, and live values below are the implementing contract.

## Coordinate and asset contract

All rectangles are `[left, top, right, bottom]` at the native `1600 x 900` backbuffer. `native rect` is the complete authored element or the union of its shadow/base calls. An element may have a smaller live clip; the exceptions are called out explicitly. Half-pixel coordinates are intentional. The baseline draw order is zero-based and is local to `0x005D2520`.

`Manifest` in the source column means that exact ID already exists in `webgame/assets/fixtures/asset-manifest-goldens.json`. `Native` means the rebuild must extract the named record from the shipped bundle. Font groups are bitmap-font wrappers, not operating-system typefaces. `Primitive` means no sprite record exists.

## Complete element census

The census unit is one semantic visual element. Shadow/base pairs and the three or seven segments emitted by the strip helper remain one element. Empty belt slots count because the native layout and input binding retain their logical boxes even though they emit no art.

| # | Stable element id | Native rect | Anchor and alignment | Art and source | Font/text metrics | Baseline order | Native owner(s) |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | `cast.primary.card` | `[730.5,825,793.5,892]` | center-bottom; base is `[730.5,825,788.5,887]`, black shadow is `+5,+5` | `UI.47` (Manifest) | none | `0..1` shadow then base | `0x005D2520`, `0x005D3E10` |
| 2 | `cast.secondary.card` | `[810.5,825,873.5,892]` | center-bottom; base is `[810.5,825,868.5,887]`, black shadow is `+5,+5` | `UI.48` (Manifest) | none | `2..3` shadow then base | `0x005D2520`, `0x005D3E10` |
| 3 | `belt.slot.0` | visual `[473.5,840.5,515.5,877.5]`; logical `[468,832.5,521,885.5]` | center-bottom; first position of 60 px pitch; 53 x 53 logical box | `Skills.72` (Native `images/Skills.bundle`, record 72) | none | `4` | `0x005D3E10` |
| 4 | `belt.slot.1` | logical `[528,832.5,581,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |
| 5 | `belt.slot.2` | logical `[588,832.5,641,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |
| 6 | `belt.slot.3` | visual `[648,834,706,889]`; logical `[648,832.5,701,885.5]` | center-bottom; shadow is `+5,+5` | `Inventory.46` (Native `images/Inventory.bundle`, record 46) | none | `6..7` shadow then base | `0x005D3E10` |
| 7 | `belt.slot.4` | visual `[899.5,834.5,954.5,888.5]`; logical `[898,832.5,951,885.5]` | center-bottom; right bank resumes after XP/cast center gap; shadow is `+5,+5` | `Inventory.47` (Native `images/Inventory.bundle`, record 47) | none | `12..13` shadow then base | `0x005D3E10` |
| 8 | `belt.slot.5` | logical `[958,832.5,1011,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |
| 9 | `belt.slot.6` | logical `[1018,832.5,1071,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |
| 10 | `belt.slot.7` | logical `[1078,832.5,1131,885.5]` | center-bottom; 60 px pitch | no draw | none | none | `0x005D3E10` |
| 11 | `belt.slot.0.input_hint` | authored `[483.5,877,505.5,908]`; clipped `[483.5,877,505.5,900]` | centered below slot 0; the bottom 8 px intentionally leave the viewport | `UI.100` (Manifest) | none | `5` | `0x005D3E10` |
| 12 | `belt.slot.3.count` | glyph `[671,888,679,897]`; backing glyph strip spans `[667.5,885,680.5,900]` | right/bottom badge on slot 3 | `UI.22` backing (Native) plus `Fonts.535-626@0x2A4C` | `Fonts` group 8, header `[10,3,28]`, measured line height 9 px; observed `3` is 8 px wide | `8..11` | `0x005D3E10`, `0x004A57C0`, `0x00415230` |
| 13 | `belt.slot.4.count` | glyph `[920,888,930,897]`; backing glyph strip spans `[917.5,885,930.5,900]` | right/bottom badge on slot 4 | `UI.22` backing (Native) plus `Fonts.535-626@0x2B20` | same group/header/9 px line; observed `4` is 10 px wide | `14..17` | `0x005D3E10`, `0x004A57C0`, `0x00415230` |
| 14 | `progression.xp.fill` | maximum `[798,833,802,881]`; live 45/90 clip `[798,857,802,881]` | center-bottom; 4 x 48 maximum, bottom-fixed at `y=881`, grows upward | `UI.81` (Native `images/UI.bundle`, record 81; UI object `+0x3E3C`) | none | `18` | `0x005D2B0C`, `0x00414D00` |
| 15 | `progression.xp.track` | `[794.5,829,806.5,885]` | center-bottom; 12 x 56 frame centered at `x=800`, bottom inset 15 | `UI.82` (Manifest) | none | `19` | `0x005D2B0C`, `0x004142E0` |
| 16 | `mana.track` | `[850,14.5,960,34.5]` | center-top; 110 x 20, left edge `center+50` | `UI.70` (Native `images/UI.bundle`, record 70) | none | `20..22` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 17 | `mana.fill` | maximum `[855,19.5,955,29.5]` | center-top; 100 x 10, left-clipped | `UI.40` (Native `images/UI.bundle`, record 40) | none | `23..25` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 18 | `health.track` | `[640,14.5,750,34.5]` | center-top; 110 x 20, right edge `center-50` | `UI.70` (Native record 70) | none | `26..28` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 19 | `health.fill` | maximum `[645,19.5,745,29.5]` | center-top; 100 x 10, left-clipped | `UI.26` (Native `images/UI.bundle`, record 26) | none | `29..31` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 20 | `mana.reserve.overlay` | observed 50/100 `[906.5,19.5,954.5,29.5]` | center-top; right-side reserved-capacity segment, right edge approximately `x=955` | `UI.41` (Native `images/UI.bundle`, record 41) | none | conditional `26..32`, before health; later baseline orders shift by 7 | `0x005D2BDD`, `0x00415230` |
| 21 | `health.magic_shield.overlay` | maximum `[645,19.5,745,29.5]` | center-top; independently left-clipped, then width-sorted against life | `UI.26` (Native record 26), cyan tint `(0.5,1,1,1)` | none | conditional three-call strip; shorter of life/shield first, longer last | `0x005D2BDD`, `0x00415230`, `0x00420EC0` |
| 22 | `ally.row.0.identity` | reserved `[612,39,740,46]` | center-top; reservation begins `center-188`; name origin `x=612`, baseline `y=46` in multiplayer | stock `UI.0` (Manifest) or `Fonts.376-442` exact-name replacement | stock `ALLY` art is 26 x 7; multiplayer uses Fonts group 6 at quarter scale with 67 glyph metrics and 1,043 kerning pairs | `32` baseline | `0x005D3408`, `0x005CF480`, `0x004142E0`, loader `0x0043BCD0` |
| 23 | `ally.row.0.health` | maximum `[560,39.5,610,44.5]` | center-top; 50 x 5, left `center-240`; subsequent rows use 10 px pitch | Primitive untextured quad | none | `33` baseline | `0x005D3408`, `0x005CF480`, `0x004142E0` |
| 24 | `concentration.binding.12.emblem` | `[783.875,9.75,816.125,41.25]` | center-top; 32.25 x 31.5 centered at `(800,25.5)` | `Skills.67` (Native `images/Skills.bundle`, record 67) | none | `34` baseline | `0x005D367A`, `0x0046B140`, `0x00414EA0` |
| 25 | `aim.cursor` | observed `[9.5,8.5,40.5,41.5]` | pointer; 31 x 33 centered on the native mouse point and viewport-clipped | `UI.42` (Manifest) | none | `35`, always in the tail | `0x005D3D48`, `0x004F6070` |
| 26 | `notification.gold` | base `[741,49,860,69]`, shadow `[741,51,860,71]`, union `[741,49,860,71]` | center-top transient stack; shadow offset `(0,+2)` | `Fonts.376-442` (Native bitmap-font group 6) | header `[24,5,28]`; exact string `_s(1)25 GOLD`; measured 119 x 20 per line | transient notification pass, after the main HUD body and before cursor tail | `0x005CA7C0`, `0x005CF000`, `0x004F5620` |

The `Fonts` wrapper inventory and ABI are already pinned in [`native-presentation-ui-fonts-and-loader.md`](native-presentation-ui-fonts-and-loader.md#fonts-wrapper-inventory). Do not replace these faces with a “similar” system font: use the extracted glyph records and kerning tables. `UI.81` is intentionally a native-bundle record even though the low-level capture sees an ownerless textured quad; the static owner is the UI object at `+0x3E3C`.

### Baseline and conditional order

The baseline order is: cast-card shadow/base pairs (`0..3`), the eight belt positions and their populated art/counts (`4..17`), XP fill then track (`18..19`), mana track then fill (`20..25`), health track then fill (`26..31`), each ally identity then its bar (`32..33` for one row), concentration binding emblems (`34` for binding 12), and cursor (`35`).

Conditional insertion does not change the semantic order:

1. A nonzero mana reserve inserts `UI.41` after mana fill and before health track. The observed 50/100 state uses seven strip calls and shifts later draw indices by seven.
2. A positive magic shield adds a second `UI.26` strip in the health section. Life and shield are sorted by visible width, shorter first and longer last; their call indices therefore swap when the widths cross.
3. Each additional ally appends identity then bar, with 10 px row pitch, before concentration emblems. Fresh instruction-level confirmation and the player/Golem producer census are in [`native-ally-roster-hud-2026-08-14.md`](native-ally-roster-hud-2026-08-14.md).
4. Binding indices 12, 16, and 20 are tested in that order. The captured loadout populates only 12; do not infer art or rects for unobserved bindings 16/20.
5. Notifications are transient and cannot be part of a structurally settled membership snapshot. Their exact-text transitions and screenshot are retained separately in the live trace.

## Behavior contract

### Health fill, damage, and magic shield

Local life uses the current and maximum progression fields (`progression+0x70` and `progression+0x6C`). Let `r = clamp(current / maximum, 0, 1)`. The visible width is:

```text
life_width_px = 100 * r * r
life_rect = [645, 19.5, 645 + life_width_px, 29.5]
```

This is a squared fill, not a linear bar: live states recorded 50/50 -> 100 px, approximately 30.035/50 -> 36.084 px, and approximately 5.035/50 -> 1.014 px. The renderer samples current HP on every HUD render. An organic native-damage trace changed `progression+0x70` while `+0x6C` stayed at the 50 maximum and the visible clip followed immediately; there is no trailing display accumulator, easing, delayed drain layer, or low-health pulse. Full, damaged, and near-death tint remained white RGBA `(1,1,1,1)`.

Magic shield is actor-local (`actor+0x1C4` current, `actor+0x1C8` maximum) and linear:

```text
shield_width_px = 100 * clamp(shield_current / shield_maximum, 0, 1)
shield_rect = [645, 19.5, 645 + shield_width_px, 29.5]
shield_tint = (0.5, 1, 1, 1)
```

Both layers reuse `UI.26`. The native branch compares shield ratio with squared life ratio and draws the shorter layer first, longer layer last. At roughly 30/50 life (about 36 px), 25/50 shield draws white life first at orders `29..31`, then 50 px cyan shield at `32..34`; 10/50 shield reverses the order, drawing 20 px cyan first and roughly 36 px white life second. Reproduce the order, not just two unordered bars.

### Mana fill and reserved capacity

Local mana uses `progression+0x7C` current and `progression+0x78` maximum. Its screen fill is linear and left-anchored:

```text
mana_width_px = 100 * clamp(current / maximum, 0, 1)
mana_rect = [855, 19.5, 855 + mana_width_px, 29.5]
```

The HUD samples the field every render; the native simulation is 100 Hz. The live refill trace observes the fill change with the native pool. G1 specifically establishes that the previously reported **250 ms mana cadence is the loader's bot-mana reserve recovery service**, layered over 25 native ticks, not a retail HUD interpolation timer; see [`native-movement-and-tick.md`](native-movement-and-tick.md#gameplay-cadence-census). When that service owns a bot's source value, its value changes at 250 ms steps, but the screen renderer itself remains per-frame.

When `progression+0x740` reserve is nonzero, stock caps usable mana at `maximum - reserve` and draws `UI.41` over the right-hand reserved capacity. The live 50 reserve / 100 maximum case exposes a 48 px art rect `[906.5,19.5,954.5,29.5]` and seven segmented calls. Preserve that observed art geometry; do not reinterpret it as a second left-growing mana fill.

### Cast cards, belt slots, cooldown, and charges

The two large `UI.47`/`UI.48` cards are fixed primary/secondary cast affordances. The eight input slots are ordered left-to-right by the G14 intent slot index `0..7`, even when empty. Empty slots keep their logical 53 x 53 boxes and emit no sprite. Populated item slots draw a black `+5,+5` shadow followed by the base art. Counts render above their `UI.22` backing at the viewport bottom.

For a skill entry, remaining cooldown is `skill_entry+0x64` and capacity is `skill_entry+0x68`, both in 100 Hz native ticks. Remaining decrements once per fixed tick; the HUD samples it per render. `0x005C6D30` calls the sector builder `0x00416330`, which emits through `0x00416450` in 45-degree segments. For `remaining > 0`:

```text
end_degrees = 360 * (1 - remaining / capacity)
covered sector = [end_degrees, 360]
```

Positive mathematical angle maps from screen-right toward screen-up, so the covered sector retreats counter-clockwise through the icon as remaining time decreases. The active icon has steady alpha `0.25`; the ready icon has steady alpha `0.375`. No cooldown-complete flash, scale pulse, or oscillating alpha was observed.

Earth hold adds no HUD charge meter, ring, count, or card fill. Its only charge presentation is the G2 world-space Boulder scale. The exact float32 recurrence starts at `0.18`, adds float32 `0.00125` per 100 Hz tick in the neutral fixture, and reaches 1 after 656 updates (about 6.56 seconds). Implement that from [`native-projectile-and-spell-mechanics.md`](native-projectile-and-spell-mechanics.md#exact-charge-time-to-magnitude-curve); do not invent an on-card progress bar.

### XP and level

XP is a bottom-anchored vertical `UI.81` clip inside `UI.82`:

```text
ratio = clamp((xp - previous_threshold) / (next_threshold - previous_threshold), 0, 1)
height_px = 48 * ratio
xp_rect = [798, 881 - height_px, 802, 881]
```

The live 45 XP state between thresholds 0 and 90 produces exactly 24 px at `[798,857,802,881]`. There is no numeric in-run level label. Crossing 90 changes level 1 -> 2 and enters the G11-owned skill-picker screen; the golden records the fixed-tick transition only and deliberately does not duplicate that screen.

### Gold, waves, score, buffs, and floaters

- A 25-gold pickup pushes `_s(1)25 GOLD`, centered at the top. Its native timer starts at 1.5 seconds; text alpha is `clamp(timer, 0, 1)`. The base stays fixed and the only animation is the expiry fade. There is no persistent numeric gold counter in the in-run HUD.
- Changing the wave counter did not add, remove, or change any screen-overlay HUD member. There is no numeric wave, score, or `SCORE` indicator in this retail HUD. The internal flag previously labeled `score_indicator` is the XP gauge branch and must not be rebuilt as score UI.
- A live `DamageX4` status added no icon. The retail HUD has no buff/debuff icon row or timer badges. The invincibility potion uses a persistent actor-attached carrier and native `SpellGlow` activation presentation in world space, as specified by [`lua-item-inventory-icon-and-consumable-vfx-duration-2026-08-04.md`](../bugs/lua-item-inventory-icon-and-consumable-vfx-duration-2026-08-04.md); it is not a screen HUD icon.
- The exhaustive `0x005D2520`/`0x005CF000` boundary contains no numeric damage or healing floater. Therefore spawn position, velocity, lifetime, and per-damage-type floater colors are **not applicable**: the rebuild must not invent them as retail behavior. Stock damage presentation is actor tint plus screen-edge feedback and sound; healing does not enqueue that feedback. See [`hit-feedback-2026-07-28.md`](../design/hit-feedback-2026-07-28.md). Those effects belong to G12's world/edge presentation, outside this census.

### Pulse and flash summary

| Element/state | Native response |
| --- | --- |
| Health damage / near death | Squared clip changes; no HUD smoothing, flash, or pulse; tint remains white. |
| Magic shield | Cyan strip; no independent pulse observed. Width ordering changes at the life/shield crossover. |
| Mana drain/refill | Linear clip changes; no HUD pulse. |
| Cooldown active/ready | Stable alpha `0.25` / `0.375` and geometric sector change; no completion flash observed. |
| Gold pickup | Fixed-position text with alpha expiry fade from a 1.5 s timer. |
| Hub decoration | `College.18` and `College.17` change non-rect tint forever. They are hub action/decor art, not gameplay HUD pulse states. |

## Visibility matrix

| State | Retail HUD visibility | Ally behavior | Evidence/constraint |
| --- | --- | --- | --- |
| Hub, local alive | The run HUD remains visible. The courtyard adds four action/decor draws. `College.18`/`College.17` continuously change tint, so the 40-draw hub surface never met the structural settle rule and is not promoted to a golden. | One row per additional durable alive participant. | Live 480-frame diagnostic; never replace this with a fixed-delay “settled” fixture. |
| Run, local alive | XP, cards/belt, local vitals, allies, concentration, transient notifications, and cursor are eligible. Conditional elements require their state. | `n-1` unique nonlocal durable alive rows. | Two independent settle-gated captures per scripted state. |
| Run with featured enemy | A native prefix branch exists before the ordinary HUD; exact panel membership/layout is Not Yet Reversed below. Ordinary HUD follows normally. | Unchanged. | Static branch `0x005D257E..0x005D2AEF`. |
| Local death (`actor+0x160 != 0`) | The early branch skips featured enemy, XP, cards/belt, vitals, allies, concentration, and notifications. The cursor tail at `0x005D3D48` and optional gameplay fade at `gameplay+0x1BB8` still run. | Hidden locally. | Static control flow plus death/spectator prior art. |
| First five seconds of `DeathPresentation` | Same stock cursor/fade tail; no product spectator panel yet. | Hidden locally. | [`native-player-death-spectator.md`](native-player-death-spectator.md#beta17-missing-spectator-affordance-and-product-ui-boundary). |
| `Spectating` a living peer | Stock body remains skipped. The loader-owned product surface shows the local `Spectating` status, selected living peer, and left/right-click instruction on the real swap-chain backbuffer. | Do not resurrect stock ally rows or create a second ownership path. | Product overlay renders only for the dead local owner in `Spectating`; living peers and inactive/death-presentation states never register it. |
| Respawned alive | Ordinary HUD returns on the next alive render. | Rebuild rows only from the durable current-epoch roster after actor and vitals convergence. | Allyvis scene-epoch contract. |
| Pause, level picker, Game Over | G11-owned screen is above or replaces gameplay presentation. Do not rebuild it here. | Preserve underlying gameplay ownership only as G11 specifies. | [`native-menus-and-boot.md`](native-menus-and-boot.md). |

## Multiplayer semantics and regression constraints

The native append ABI is exactly `0x005CF480(gameplay, glyph, health_ratio)` as a `__thiscall`. The vector pointers/counters are at gameplay `+0x1C14` (storage), `+0x1C18` (capacity), and `+0x1C20` (count). Each 8-byte row stores glyph pointer at `+0` and float ratio at `+4`. Reversing the arguments writes `0x3F800000` as a glyph pointer and faults the stock renderer, so the typed order is normative. See [`allyvis-player-visual-epoch-parity.md`](../bugs/allyvis-player-visual-epoch-parity.md#4-ally-row-identity-is-derived-from-ephemeral-actor-bindings).

For every observer:

1. Local health/mana always represent that observer's local participant. Never add a self ally row.
2. Append exactly one top-center row for each other connected, alive, durable participant; sort by participant ID for deterministic browser presentation. Two participants yield one row; `n` participants yield `n-1` rows.
3. The row ratio is `clamp(authoritative_current_hp / authoritative_max_hp, 0, 1)` and visible width is `50 * ratio`, left-anchored. Runtime vitals are authoritative; do not smooth them or substitute a stale materialized actor pool.
4. The stock single-player/bot-seam presentation uses `UI.0` (`ALLY`) in the 128 px identity reservation. Real multiplayer suppresses `UI.0` and draws the participant's exact display name with `Fonts.376-442`, left `x=614`, baseline `y=46`, 2 px padding, 4 px non-space advance, and 2 px space advance. A failed name draw does not fall back to a misleading generic identity.
5. Row identity belongs to the durable participant-presentation roster, not an ephemeral actor pointer. Scene preparation may clear and replace an actor without deleting a still-connected participant's row. Conversely, disconnect, authoritative death, or a new scene epoch must remove/replace the old row rather than leave a phantom.
6. Transform history must not interpolate across scene epochs. A replacement actor resets actor-local presentation state. Vitals remain fenced until an owner frame both ACKs the correction and reports matching HP; an ACK alone is not convergence. These are direct constraints from the landed allyvis epoch-parity fix, not optional browser hardening.

World nameplates are a separate `scene-overdraw` feature described by [`ally-healthbar-investigation.md`](../ally-healthbar-investigation.md). Do not merge their camera-projected geometry with these fixed top-center rows.

## Scaling and 1280 x 800 / 16:10

### Observed native anchoring

The retail HUD uses authored pixels at scale 1.0. It does not uniformly scale a 1600 x 900 canvas. Re-evaluate each anchor from the actual viewport:

```text
center-top:    x' = x + (viewport_width - 1600) / 2; y' = y
center-bottom: x' = x + (viewport_width - 1600) / 2; y' = y + (viewport_height - 900)
pointer:       center on the current pointer/aim point, then viewport-clip
```

At `1280 x 800`, center `x` moves by `-160`, bottom `y` moves by `-100`, top `y` is unchanged, and scale remains `1.0`. Representative retail-parity rects are:

| Element | Exact anchored rect at 1280 x 800 |
| --- | --- |
| health track | `[480,14.5,590,34.5]` |
| mana track | `[690,14.5,800,34.5]` |
| ally row 0 health | `[400,39.5,450,44.5]` |
| concentration binding 12 | `[623.875,9.75,656.125,41.25]` |
| gold notification union | `[581,49,700,71]` |
| XP track | `[634.5,729,646.5,785]` |
| primary card union | `[570.5,725,633.5,792]` |
| secondary card union | `[650.5,725,713.5,792]` |
| belt slot 0 visual | `[313.5,740.5,355.5,777.5]` |
| belt slot 7 logical | `[918,732.5,971,785.5]` |
| input hint | authored `[323.5,777,345.5,808]`, viewport-clipped at `y=800` |

This exact anchored layout is the conformance reference. It preserves the retail bottom clipping and is what pixel-diff tests should compare before accessibility/readability policy is applied.

### Designed-not-observed readability policy

The following values are browser/Steam Deck design decisions required by roadmap section 4.1. They were **not observed in retail** and must remain labeled `designed-not-observed` in implementation data:

| Designed value | Minimum |
| --- | ---: |
| safe inset on all four edges | 24 px |
| skill/cast logical target | 48 x 48 px (native logical slot is 53 x 53) |
| vital track | 110 x 20 px |
| ally bar | 50 x 8 px (native is 50 x 5) |
| participant name font / line box | 12 px / 16 px |
| item-counter font | 12 px |
| notification font | 16 px |
| general HUD text line box | 16 px |
| pointer containment | complete 31 x 33 cursor inside the drawable viewport |

Apply policy after native anchoring: translate each top or bottom cluster inward by the smallest amount needed to fit the 24 px safe rectangle, preserve internal pitch/alignment, and grow only elements below their declared minima. Do not uniformly scale the whole HUD. At 1280 x 800 this means the parity reference and the readable shipped layout are deliberately distinguishable: the former retains native top/bottom clipping; the latter moves essential clusters inward and raises the ally bar/text floors for a 7-inch display.

## Live golden and reference crops

[`hud-goldens.json`](../../tests/fixtures/webgame/hud-goldens.json) is recorder-derived. Its header derives the base commit, dirty state, executable hash, loader hash, process/instance, ports, native resolution, settle policy, raw-capture root, and crop root; the recorder accepts no provenance override. Each asynchronous HUD state requires two independent captures and at least 40 consecutive structurally identical samples spanning at least two seconds. Only rect/unclipped-rect motion may classify an element as animated, and animated membership must reproduce and remain at or below 30 percent.

The scripted session covers full/damaged/near-death health, two shield/life crossover states, mana drain/refill, mana reserve, active cooldown, Earth hold, native XP and level-up transitions, gold pickup, a live `DamageX4` absence case, wave-state absence, and a two-participant ally row via the bot seam. Every sample carries a native simulation tick. `reference_crops` contains at least one PNG crop per census element plus state crops, each with source/crop hashes and exact crop boxes for visual diffing.

## Not Yet Reversed

### Featured enemy / boss panel

`0x005D257E..0x005D2AEF` is a reachable native prefix guarded by `gameplay+0x1C2C`, a live actor, and its durable `EnemyConfig` at `actor+0x1D0`. It executes before the ordinary HUD and contains sprite/text work consistent with a featured-enemy presentation. The sanctioned exact-spawn seam deliberately retires the featured pointer when a spawned actor has no durable native `EnemyConfig`; a live Heartmonger attempt therefore returned “featured-enemy actor has no durable native config.” Fabricating that object would cross the observation-only boundary.

No panel rect, label count, font, or sprite is asserted. An implementing agent must leave this branch absent or explicitly incomplete until a naturally configured featured enemy is reachable and settle-gated. Do not infer a boss bar from screenshots or reuse the ordinary ally/health rect.

### Binding 16/20 concentration emblems

The renderer tests binding indices 12, 16, and 20, but only 12 is populated in the recorded loadout. The later bindings' conditional offsets are known; their actual art/rect combinations are not live-confirmed. Preserve the ordered conditional slots and record them when a real loadout populates them rather than copying `Skills.67` by assumption.
