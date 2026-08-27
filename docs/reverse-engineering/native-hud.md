# Native retail in-run HUD (G9)

This is the implementation contract for Solomon's Dark's retail gameplay HUD.
It closes browser-rebuild gap G9 for the retail executable and is intended to
be sufficient for an implementing agent to rebuild the HUD without opening the
binary. The checked-in baseline recording is
[`hud-goldens.json`](../../tests/fixtures/webgame/hud-goldens.json). The
2026-08-21
[`derived-stat recapture`](../../tests/fixtures/webgame/native-derived-hud-goldens.json)
reopens and corrects that baseline's former fixed-width inference: every
rectangle and state value below now comes from the baseline recording, the
derived-stat recording, or an addressable native layout path, never from
eyeballing a screenshot.

## Scope and ownership

This document owns only presentation drawn during play: cast cards and belt
slots, XP, local health/mana and their conditional layers, top-center ally
rows, the selected-primary and concentration emblems, the aim cursor,
transient pickup text, and their visibility and scaling rules.

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
| 12 | `belt.slot.3.input_hint` | glyph `[671,888,679,897]`; backing glyph strip spans `[667.5,885,680.5,900]` | centered below slot 3 | `UI.22` backing (Native) plus `Fonts.535-626@0x2A4C` | `Fonts` group 8, header `[10,3,28]`, measured line height 9 px; default Health-Potion binding `3` is 8 px wide | `8..11` | `0x005D3E10`, `0x004A57C0`, `0x00415230`, `0x004299F0` |
| 13 | `belt.slot.4.input_hint` | glyph `[920,888,930,897]`; backing glyph strip spans `[917.5,885,930.5,900]` | centered below slot 4 | `UI.22` backing (Native) plus `Fonts.535-626@0x2B20` | same group/header/9 px line; default Mana-Potion binding `4` is 10 px wide | `14..17` | `0x005D3E10`, `0x004A57C0`, `0x00415230`, `0x004299F0` |
| 14 | `progression.xp.fill` | maximum `[798,833,802,881]`; live 45/90 clip `[798,857,802,881]` | center-bottom; 4 x 48 maximum, bottom-fixed at `y=881`, grows upward | `UI.81` (Native `images/UI.bundle`, record 81; UI object `+0x3E3C`) | none | `18` | `0x005D2B0C`, `0x00414D00` |
| 15 | `progression.xp.track` | `[794.5,829,806.5,885]` | center-bottom; 12 x 56 frame centered at `x=800`, bottom inset 15 | `UI.82` (Manifest) | none | `19` | `0x005D2B0C`, `0x004142E0` |
| 16 | `mana.track` | baseline `[850,14.5,960,34.5]`; dynamic width | center-top; left edge fixed at `center+50`, grows right | `UI.70` (Native `images/UI.bundle`, record 70) | none | `20..22` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 17 | `mana.fill` | baseline maximum `[855,19.5,955,29.5]`; dynamic width | center-top; left edge fixed at `center+55`, left-clipped | `UI.40` (Native `images/UI.bundle`, record 40) | none | `23..25` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 18 | `health.track` | baseline `[640,14.5,750,34.5]`; dynamic width | center-top; right edge fixed at `center-50`, grows left | `UI.70` (Native record 70) | none | `26..28` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 19 | `health.fill` | baseline maximum `[645,19.5,745,29.5]`; dynamic width | center-top; right edge fixed at `center-55`; content remains left-clipped | `UI.26` (Native `images/UI.bundle`, record 26) | none | `29..31` | `0x005D2520`, `0x00415230`, `0x00420EC0` |
| 20 | `mana.reserve.overlay` | observed 50/100 `[906.5,19.5,954.5,29.5]` | center-top; right-side reserved-capacity segment, right edge approximately `x=955` | `UI.41` (Native `images/UI.bundle`, record 41) | none | conditional `26..32`, before health; later baseline orders shift by 7 | `0x005D2BDD`, `0x00415230` |
| 21 | `health.magic_shield.overlay` | maximum `[645,19.5,745,29.5]` | center-top; independently left-clipped, then width-sorted against life | `UI.26` (Native record 26), cyan tint `(0.5,1,1,1)` | none | conditional three-call strip; shorter of life/shield first, longer last | `0x005D2BDD`, `0x00415230`, `0x00420EC0` |
| 22 | `ally.row.0.identity` | reserved `[612,39,740,46]` | center-top; reservation begins `center-188`; name origin `x=612`, baseline `y=46` in multiplayer | stock `UI.0` (Manifest) or `Fonts.376-442` exact-name replacement | stock `ALLY` art is 26 x 7; multiplayer uses Fonts group 6 at quarter scale with 67 glyph metrics and 1,043 kerning pairs | `32` baseline | `0x005D3408`, `0x005CF480`, `0x004142E0`, loader `0x0043BCD0` |
| 23 | `ally.row.0.health` | maximum `[560,39.5,610,44.5]` | center-top; 50 x 5, left `center-240`; subsequent rows use 10 px pitch | Primitive untextured quad | none | `33` baseline | `0x005D3408`, `0x005CF480`, `0x004142E0` |
| 24 | `skill.binding.12.primary` | baseline Earth `[783.875,9.75,816.125,41.25]`; cluster-dependent center | selected-primary emblem at 0.75 scale/alpha; conditional A/B are child variants of this selected-skill cluster | selected row's authored Skills record; Earth is `Skills.67` | none | `34` baseline | `0x005D367A`, `0x0046B140`, `0x00414EA0` |
| 25 | `aim.cursor` | observed `[9.5,8.5,40.5,41.5]` | pointer; 31 x 33 centered on the native mouse point and viewport-clipped | `UI.42` (Manifest) | none | `35`, always in the tail | `0x005D3D48`, `0x004F6070` |
| 26 | `notification.gold` | base `[741,49,860,69]`, shadow `[741,51,860,71]`, union `[741,49,860,71]` | center-top transient stack; shadow offset `(0,+2)` | `Fonts.376-442` (Native bitmap-font group 6) | header `[24,5,28]`; exact string `_s(1)25 GOLD`; measured 119 x 20 per line | transient notification pass, after the main HUD body and before cursor tail | `0x005CA7C0`, `0x005CF000`, `0x004F5620` |

The `Fonts` wrapper inventory and ABI are already pinned in [`native-presentation-ui-fonts-and-loader.md`](native-presentation-ui-fonts-and-loader.md#fonts-wrapper-inventory). Do not replace these faces with a “similar” system font: use the extracted glyph records and kerning tables. `UI.81` is intentionally a native-bundle record even though the low-level capture sees an ownerless textured quad; the static owner is the UI object at `+0x3E3C`.

### Baseline and conditional order

The baseline order is: cast-card shadow/base pairs (`0..3`), the eight belt
positions and their populated art/counts (`4..17`), XP fill then track
(`18..19`), mana track then fill (`20..25`), health track then fill
(`26..31`), each ally identity then its bar (`32..33` for one row), selected
skill emblems (`34` for the selected primary in the baseline), and cursor
(`35`).

Conditional insertion does not change the semantic order:

1. A nonzero mana reserve inserts `UI.41` after mana fill and before health track. The observed 50/100 state uses seven strip calls and shifts later draw indices by seven.
2. A positive magic shield adds a second `UI.26` strip in the health section. Life and shield are sorted by visible width, shorter first and longer last; their call indices therefore swap when the widths cross.
3. Each additional ally appends identity then bar, with 10 px row pitch, before concentration emblems. Fresh instruction-level confirmation and the player/Golem producer census are in [`native-ally-roster-hud-2026-08-14.md`](native-ally-roster-hud-2026-08-14.md).
4. Binding indices 12, 16, and 20 are tested and drawn in that order. They are
   selected primary, concentration A, and concentration B. With A only, their
   centers are primary `780`, A `820`; with Split Mind A+B they are primary
   `760`, B `800`, A `840` even though A draws before B. Every emblem is
   centered at `y=25.5`, scaled to `0.75`, and drawn at white alpha `0.75`.
5. Notifications are transient and cannot be part of a structurally settled membership snapshot. Their exact-text transitions and screenshot are retained separately in the live trace.

## Behavior contract

### Health fill, damage, and magic shield

The old baseline capture had base HP equal to maximum HP and therefore
misidentified `progression+0x6C` as maximum. The actual fields are base
`+0x6C`, current `+0x70`, and maximum `+0x74`. Instructions
`0x005D2FDD..0x005D30C5` derive the repeated-strip length from base and
maximum before applying the squared current ratio:

```text
health_core_width =
    2 * (base_health + 0.25 * (maximum_health - base_health))
health_track_width = health_core_width + 10
health_ratio = clamp(current_health / maximum_health, 0, 1)
health_visible_width = health_core_width * health_ratio * health_ratio

health_track = [750 - health_track_width, 14.5, 750, 34.5]
health_core = [745 - health_core_width, 19.5, 745, 29.5]
health_visible = [
    745 - health_core_width,
    19.5,
    745 - health_core_width + health_visible_width,
    29.5
]
```

At stock base 50, default maximum 50 produces a 100-pixel core and
110-pixel track. Health Up rank one raises maximum to 100 and produces a
125-pixel core at `[620,19.5,745,29.5]` and 135-pixel track at
`[615,14.5,750,34.5]`: both right edges remain fixed and the meter grows
left. Authored Health Up maximum 700 produces a 425-pixel core and 435-pixel
track. There is no cap at an authored skill maximum.

The fill remains squared, not linear. The renderer samples current HP on every
HUD render; there is no trailing display accumulator, easing, delayed drain
layer, or low-health pulse. Full, damaged, and near-death tint remained white
RGBA `(1,1,1,1)`.

Magic shield is actor-local (`actor+0x1C4` current, `actor+0x1C8` maximum) and linear:

```text
shield_width_px =
    health_core_width * clamp(shield_current / shield_maximum, 0, 1)
shield_rect = [
    745 - health_core_width,
    19.5,
    745 - health_core_width + shield_width_px,
    29.5
]
shield_tint = (0.5, 1, 1, 1)
```

Both layers reuse `UI.26`. The native branch compares shield ratio with
squared life ratio and draws the shorter layer first, longer layer last. The
2026-08-21 maximum-100 capture proved that both layers share the expanded
125-pixel core and begin at `x=620`: approximately 30/100 life exposed
11.262756 pixels and 25/50 shield exposed 62.5 pixels. Reproduce the dynamic
shared core and order, not just two unordered default-width bars.

### Mana fill and reserved capacity

The actual fields are base `progression+0x78`, current `+0x7C`, and maximum
`+0x80`. Instructions `0x005D2C02..0x005D2DF6` derive a dynamic strip
length before applying the linear current ratio:

```text
mana_core_width = base_mana + 0.25 * (maximum_mana - base_mana)
mana_track_width = mana_core_width + 10
mana_ratio = clamp(current_mana / maximum_mana, 0, 1)
mana_visible_width = mana_core_width * mana_ratio

mana_track = [850, 14.5, 850 + mana_track_width, 34.5]
mana_core = [855, 19.5, 855 + mana_core_width, 29.5]
mana_visible = [855, 19.5, 855 + mana_visible_width, 29.5]
```

At stock base 100, default maximum 100 produces a 100-pixel core and
110-pixel track. Mana Up rank one raises maximum to 200 and produces a
125-pixel core at `[855,19.5,980,29.5]` and 135-pixel track at
`[850,14.5,985,34.5]`: both left edges remain fixed and the meter grows
right. Authored Mana Up maximum 1350 produces a 412.5-pixel core and
422.5-pixel track. There is no authored-rank cap in the renderer.

The HUD samples the field every render; the native simulation is 100 Hz. The
live refill trace observes the fill change with the native pool. G1
specifically establishes that the previously reported **250 ms mana cadence is
the loader's bot-mana reserve recovery service**, layered over 25 native ticks,
not a retail HUD interpolation timer; see
[`native-movement-and-tick.md`](native-movement-and-tick.md#gameplay-cadence-census).
When that service owns a bot's source value, its value changes at 250 ms steps,
but the screen renderer itself remains per-frame.

When `progression+0x740` reserve is nonzero, stock caps usable mana at
`maximum - reserve` and draws `UI.41` over the right-hand reserved capacity.
Its logical segment is
`mana_core_width * clamp(reserve / maximum_mana, 0, 1)`, anchored to the
dynamic core's right edge. The maximum-200/reserve-50 capture retained the
125-pixel core and exposed `UI.41` at
`[950.25,19.5,979.5,29.5]`; the 29.25 visible art pixels sit inside the
31.25-pixel logical quarter. Preserve this dynamic right-edge ownership; do
not reinterpret the overlay as a second left-growing mana fill.

### Maximum-vital producers and refresh ownership

The renderer does not know why maximum HP or MP changed. Every producer that
ultimately writes `+0x74` or `+0x80` receives the same dynamic geometry:

| Producer | Native consequence | HUD consequence |
| --- | --- | --- |
| Health Up 64 / Mana Up 56 | adds authored `mValue` to the respective base | grows the core by one quarter of the maximum delta (health then doubles for the two-pixel-per-base-HP scale) |
| equipment `FX_MAXHP` 23 / `FX_MAXMP` 24 | ordered native scalar transform | grows or shrinks from the resulting authoritative maximum, including fractional widths |
| Hagatha Life Charm 0 / Mana Charm 1 | multiplies the resulting maximum by 1.25 | same resulting-maximum geometry; no separate charm badge |
| skill/equipment/perk refresh | preserves the current HP/MP ratio while replacing maxima | geometry and visible fill change in the same refresh |
| level/new-run reset | installs refreshed maxima and full current pools | full dynamic core |
| damage, healing, mana cost/recovery, potion/orb, poison, Magic Circle, Regenerate | changes current only | ratio/fill only; track/core geometry is unchanged |

Remote ally rows and world-projected nameplates are separate fixed-width ratio
systems. A remote participant with a larger maximum changes its ratio
denominator, not the authored 50-pixel ally width or nameplate width policy.

### Selected-primary and concentration emblems

The three conditional bindings are not three interchangeable concentration
slots:

| Binding | Semantic value | Icon resolution |
| ---: | --- | --- |
| 12 | active selected primary | read the selected skill row, then its authored icon selector at row `+0x30`; Weld uses its active build selector and Planewalker forces Plane Orb 80 |
| 16 | concentration A | selected category-3 row; reachable IDs 57..63 and 65..71 resolve to `Skills.84..90` and `Skills.92..98` |
| 20 | concentration B | same mapping; valid only with Split Mind |

The full live renderer sweep proves the direct icon rule, while the category
predicate limits reachable concentrations to
`57->84, ..., 63->90, 65->92, ..., 71->98`. Health Up 64 is passive
category 0; its `Skills.91` art is not a reachable concentration emblem. With
only Channel Mana selected, Earth
primary `Skills.67` is centered at `x=780` and `Skills.84` at `x=820`.
With Meditation A and Battle Mage B, the draw order is primary, A, B, while
the visual centers are `760,840,800`: Earth `Skills.67` rect
`[743.875,9.75,776.125,41.25]`, A `Skills.85` rect
`[822.375,8.625,857.625,42.375]`, and B `Skills.86` rect
`[787.25,7.125,812.75,43.875]`.

Mind Chug does not allocate a fourth emblem or a buff row. It makes every
concentratable consumer active and locks selection while leaving the selected
A/B presentation owner intact. DamageX4 and the other potion/status timers
likewise add no screen-HUD badge.

### Selected-skill hit targets and compact selectors

The emblem cluster is interactive even though `0x005D2520` paints it directly.
`Game` embeds three `UIButton` children at `+0x3AC/+0x46C/+0x52C`; constructor
registration `0x005CBA00`, layout `0x005D76C0`, refresh `0x005D50E0`, and Game
vtable action `+0x10 -> 0x005D8120` own their lifetime. The former
`SettingsControl_HandleAction` label for `0x005D8120` is superseded: the
Settings `MyCPanel` has a different vtable and callback.

Each logical button is exactly `40 x 65`, shares the selected emblem's dynamic
center, and normally spans `y=[-7,58)`. With zero, one, and two concentrations,
the button centers are respectively `[800]`, `[780,820]`, and
`[760,800,840]` in visual order primary, B, A; the inactive A/B controls are
parked at `-1000/-9999`. These rectangles participate in the ordinary reverse-z
HUD hit test, so their click is swallowed before the arena aim/cast fallback.

Primary opens the category-1 `Skills_Quickbar` titled `Select Primary Attack`;
A/B open the category-3 `Skills_Quickbar` titled `Select Concentration` and
target the clicked slot. The compact selector, its complete option and audio
membership, and exact renderer geometry are owned by
[`native-skill-screen-and-quickbar.md`](native-skill-screen-and-quickbar.md#selected-skill-hud-controls-and-selector-modal).

### Cast cards, belt slots, cooldown, and charges

The two large `UI.47`/`UI.48` cards are fixed primary/secondary cast affordances. Game construction owns eight `BeltButton` objects at `Game+0x5EC`, stride `0xEC`; each object's byte `+0xE8` is its input-slot index `0..7`. The eight input slots are ordered left-to-right by that index, even when empty. Each logical box is 53 x 53 and the horizontal pitch is 60 px. Empty slots emit no sprite. Populated item slots draw a black `+5,+5` shadow followed by the base art.

For a skill entry, remaining cooldown is `skill_entry+0x64` and capacity is `skill_entry+0x68`, both in 100 Hz native ticks. Remaining decrements once per fixed tick; the HUD samples it per render. `0x005C6D30` calls the sector builder `0x00416330`, which emits through `0x00416450` in 45-degree segments. For `remaining > 0`:

```text
end_degrees = 360 * (1 - remaining / capacity)
covered sector = [end_degrees, 360]
```

Positive mathematical angle maps from screen-right toward screen-up. The builder intersects each ray with the 53 x 53 **square**, inserts every crossed 45-degree square-corner boundary, and emits a center-origin triangle fan; this is not a circular pie wedge. `BeltButton::Present` sets the fan's base RGBA to `(0.5,0.1,0.1,0.75)`, draws that dark-red cooldown square fan first, changes the skill-icon base to white alpha `0.25`, and only then draws the icon. The ready path instead reaches the icon with base RGBA `(1,1,1,0.75)`. The captured final icon alpha was steady `0.25` while cooling down and `0.375` when ready. No cooldown-complete flash, scale pulse, oscillating alpha, or Planewalker/Firewalker/Mindstar/Regenerate toggle highlight exists in this presenter.

Before slot contents, a clear `gameplay+0x1AC2` installs renderer RGB multiplier `(0.25,0.25,0.25)` with alpha multiplier `1`; the Hub therefore presents the same art through its quarter-RGB scene modulation. Gameplay leaves the multiplier unchanged. This scene modulation is separate from the base RGBA transitions above.

The input hint is emitted only when the slot has visible content. The default binding table at `0x00B3BCD0` is `[0x201,0x02,0x03,0x04,0x05,0x06,0x07,0x08]`: right mouse for slot 0 and DirectInput number keys `1..7` for slots 1..7. All hints begin at white alpha `0.6`. Mouse pseudo-keys use `UI.98..100` for left/middle/right; default slot 0 therefore centers `UI.100` at local `(26.5,60)`, allowing its 31 px height to cross the viewport bottom. Keyboard bindings use the stock name from `0x004299F0`, Fonts group 8 (`Fonts.535..626`, header `[10,3,28]`) at native scale, and a three-piece `UI.22` plaque. Its width is measured text width plus 6, its local left is `(53-width)/2`, and its top is 53; the black centered label uses local x `26.5` and baseline y `64`. The default single-digit plaques are therefore 13 x 15.

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
| baseline health track (50 maximum) | `[480,14.5,590,34.5]` |
| baseline mana track (100 maximum) | `[690,14.5,800,34.5]` |
| ally row 0 health | `[400,39.5,450,44.5]` |
| selected-primary binding 12, no concentrations | `[623.875,9.75,656.125,41.25]` |
| gold notification union | `[581,49,700,71]` |
| XP track | `[634.5,729,646.5,785]` |
| primary card union | `[570.5,725,633.5,792]` |
| secondary card union | `[650.5,725,713.5,792]` |
| belt slot 0 visual | `[313.5,740.5,355.5,777.5]` |
| belt slot 7 logical | `[918,732.5,971,785.5]` |
| input hint | authored `[323.5,777,345.5,808]`, viewport-clipped at `y=800` |

This exact anchored layout is the default-vital conformance reference. Apply
the derived-stat formulas before the center-top translation: Health Up and
other maximum-HP producers retain the translated health right edge, while Mana
Up and other maximum-MP producers retain the translated mana left edge. The
layout preserves retail bottom clipping and is what pixel-diff tests should
compare before accessibility/readability policy is applied.

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

The original scripted session covers full/damaged/near-death health, two
shield/life crossover states, mana drain/refill, mana reserve, active cooldown,
Earth hold, native XP and level-up transitions, gold pickup, a live `DamageX4`
absence case, wave-state absence, and a two-participant ally row via the bot
seam. Every sample carries a native simulation tick. `reference_crops` contains
at least one PNG crop per census element plus state crops, each with source/crop
hashes and exact crop boxes for visual diffing.

The 2026-08-21 correction used the same capture owner on clean source commit
`9ba0feb1453eaf4d98437c118f48c13dc4f4982c`. The retail image SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3` and
the evidence loader SHA-256 is
`7ca4c7655a84a554a9b15e6842375e2ef2027cb7e71fee4df561e395a89736ce`.
The vital run is
`D:\codex-evidence\uire-derived-stats-20260821\live\20260821T155745Z`.
Selected-concentration member runs are
`D:\codex-evidence\uire-derived-skill-hud-20260821\live\20260821T161333Z`,
`...\20260821T161933Z`, and `...\20260821T162025Z`. Every run used an
owned process and records a path-matched stopped-process cleanup receipt.

## 2026-08-21 correction acceptance

Mod Loader cutoff `ced002e3d54374afb4954cbdbf4e37a7ee4349cc` is one commit
above current `origin/main`
`f682ab1b14a54a861068816e3e56643984bfaa91`. The correction includes the
machine-readable
[`native-derived-hud-goldens.json`](../../tests/fixtures/webgame/native-derived-hud-goldens.json),
updates the original baseline metadata without changing recorded pixels, and
teaches the recorder the corrected fields and selected-primary identity.

- Linux and the arm64 Mac mini each pass all 88 ordinary Python modules
  (801 tests) plus all 491 registered static RE contracts.
- Native Windows passes the six focused derived-HUD contracts and the same
  491/491 static registry. `scripts/Build-All.ps1 -Configuration Release`
  rebuilds the complete Win32 loader and publishes launcher, UI, and updater
  with zero C++ warnings and zero errors.
- The x86 DLL is a Windows artifact, so no Mac binary build is claimed. Mac
  validates every platform-neutral document, fixture, recorder, parser, and
  provenance member.
- The `[gameplay.pause]` / `[gameplay.globals]` section correction is pinned by
  actual parsed ownership, not token presence. It both enabled the owned retail
  captures above and prevents `cursor_secondary_at_mouse` or later globals from
  being silently assigned to the pause section again.
- Website cutoff `a8c955726938d01f880efb4860abb5ef5213230f` passes the
  unchanged canonical gate on Linux, native Windows, and Mac, then returns
  identical Chrome geometry and Skills-record receipts on all three. Exact
  browser evidence is recorded in the Website v52 ledger.

## 2026-08-21 local HP depletion-direction audit

A fresh read-only headless Ghidra pass against the same retail image (SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`)
rechecked the local HP meter after a Website direction concern. The decisive
instruction range is `0x005D2FDD..0x005D3403` inside HUD renderer
`0x005D2520`; clip setter `0x00420EC0` takes `(x, y, width, height)`, and the
repeated strip renderer remains `0x00415230`.

The meter has two different anchors that must not be conflated:

- maximum-HP layout keeps the track/core **right** edges at `750/745` and grows
  the complete meter left;
- current-HP clipping keeps the visible `UI.26` strip's **left** edge at
  `745 - health_core_width` and changes only its right edge.

Therefore damage depletes the local red meter **right-to-left**. At half HP the
squared fill retains the leftmost quarter of the core; it does not retain the
quarter nearest the central skill cluster. The clean-stock damaged and
near-death crops at
`/mnt/d/codex-evidence/uire-20260806/hud-crops/20260806T115705Z/`
visibly corroborate the instructions: red remains at the far-left end while
the empty track opens from the center-facing right end. Magic Shield uses the
same left origin with a linear ratio and only changes draw order at the
life/shield width crossover.

The owning membership is local health in Hub and run scenes; default and every
dynamic maximum; every current-health writer; the shield layer; and the
alive/death/respawn visibility branches. Fixed ally rows, world-projected
remote bars, mana/XP, and the featured-enemy prefix have independent owners.
No timing accumulator, interpolation, delayed-drain layer, tint transition,
audio, or randomness participates.

The membership sweep also narrows the independent featured-enemy prefix without
folding it into this local-meter contract. `0x005D2671..0x005D273A` reads enemy
current/max HP at `+0x174/+0x170`, clips a separately drawn strip to a
current/max-scaled width from its own left origin, and restores clipping before
the outlined name pass. This proves that prefix contains its own left-origin
health fill, but it does not make it a local-player meter consumer and does not
settle the panel's remaining art, exact rect, identity font, or natural
eligibility membership.

No G9 derived-stat or selected-skill member remains `Not Yet Reversed`. The
featured-enemy prefix below is an independent pre-existing G9 boundary.

## HUD control layout and modal slide (`0x005D76C0`, `0x005C7200`)

Recovered 2026-08-25 (retail 0.72.5, image base `0x00400000`, read-only
replica) while closing the Tutorial modal callouts. `0x005D76C0(Game)` is the
HUD control layout writer that positions the backpack, tome, and belt
controls from the backbuffer size `(W, H)` read at `*0x00B401A8 + 0x1DC/+0x1E0`;
`0x005C7200(Game, p)` is the modal slide writer that rewrites their `y`
every tick from the open-modal progress `p`. `0x007DE808` is the double
`0.5`, `0x007DE8D8` = `5`, `0x007DE910` = `3`, `0x0079ABE8` = `53` (float),
`0x00785F00` = `65` and `0x007866E4` = `75` are the `FUN_00427710` push
arguments for the backpack/tome control size (the drawn glyphs UI 47/48 are
`58 x 62`).

| Control | Game field (rect) | Layout `x` | Layout `y` (`p = 0`) | Slide `y` (`0x005C7200`) | Size |
| --- | --- | --- | --- | --- | --- |
| backpack | `Game+0x22C` (`+0x240`) | `W/2 - 69.5` | `H - 75` | `(H - 75) + 15p` | `58 x 62` |
| tome | `Game+0x2EC` (`+0x300`) | `W/2 + 10.5` | `H - 75` | `(H - 75) + 15p` | `58 x 62` |
| belt `k < 4` | `Game+0x5EC + 0xEC k` (`+0x600 + 0xEC k`) | centre `c(bp).x - 5 - 260 + 60k` | centre `c(bp).y + 3` | `(H - 75) + 8 + 15p` (top) | `53 x 53` |
| belt `k >= 4` | same stride | centre `c(tome).x + 5 + 80 + 60(k - 4)` | centre `c(tome).y + 3` | same | `53 x 53` |
| top controls | `+0x3C4`, `+0x484`, `+0x544` | unchanged | `-7` | `-7 - 80p` | |

At `1600 x 900` the control centres are backpack `(759.5, 856)`, tome
`(839.5, 856)`, belt `494.5, 554.5, 614.5, 674.5, 924.5, 984.5, 1044.5,
1104.5` at `y = 859.5` when closed, and `(759.5, 871)`, `(839.5, 871)`,
belt `y = 874.5` at `p = 1`. Belt loop bounds in `0x005D76C0` are the
`int*` offsets `-0x104 .. < -0x14` and `0x50 .. < 0x140` in 60-byte steps
(four slots each). The slide writer forces `p = 1` whenever both
`Game+0x15A0` (InventoryScreen) and `Game+0x1664` (SkillScreen) exist;
otherwise the InventoryScreen tick `0x00551A10` ramps `+0x150` by `0.025`
(`0x007847B0`) per tick and the SkillScreen tick `0x006567E0` ramps `+0x94`
the same way, so a modal is fully slid after 40 ticks.

Tutorial stages 10 and 13 begin as soon as `Tutorial::Tick 0x005D6330` sees
the corresponding screen pointer (`Game+0x15A0` / `Game+0x1664`), not after
the 40-tick ramp settles. `Tutorial::Render` therefore reads the live control
rectangles throughout opening. Closing sets the screen close byte and leaves
the teaching stage at that edge; the teaching overlay is absent during the
visual close ramp.

### InventoryScreen reuse of the backpack control (2026-08-27 correction)

A secondary Sack-navigation report exposed a missing membership row in the
earlier page-stack pass. The visible return/exit affordance is the existing
Game backpack control, not an `InventoryScreen` child. Fresh canonical-replica
decompilation of `0x005D76C0`, `0x005C7200`, and `0x0056D920` confirms:

- `Game+0x22C` is the 58 by 62 control; its image field at `Game+0x2B8`
  receives UI record 47 (`UI+0x2434`) during Game construction;
- the painter emits a black shadow at `+5,+5` and the untinted base, matching
  the HUD census's `[730.5,825,793.5,892]` resting union;
- `0x005C7200` changes only modal geometry. It has no read of the active
  `InventoryScreen` root, parent-stack count, Sack pointer, or depth;
- its complete xref set is four calls in two functions: InventoryScreen update
  `0x00551A10` at `0x00551BC5/0x00551BF5` and SkillScreen update `0x006567E0`
  at `0x0065682C/0x00656872`; no third modal owner consumes the writer;
- the same UI-47 control therefore remains visible at the participant root,
  inside empty or nonempty Sacks, through every nested parent, in gameplay,
  and beside all companion services. It submits game-back: `0x0056D920` pops
  one parent when available and closes only at the outer root;
- UI record 48 at `Game+0x2EC` is the complete painter/layout sibling for the
  independent SkillScreen. No alternate Sack arrow or breadcrumb record
  exists.

At settled inventory progress `p=1`, the backpack base is
`[730.5,840,788.5,902]`; native viewport clipping removes its bottom two
pixels. This is intentional stock composition, not evidence that the control
should be hidden. Website validation must inspect the visible UI-47 pixels as
well as the semantic hit target, because a transparent browser button can
exercise the back state machine while the native affordance is absent.

## Tutorial teaching overlay (`0x005D08C0`)

`0x005D08C0` is `Tutorial::Render` (class vtable `0x0079AFC4` slot `0x0C`;
slot `0x08` is the tick `0x005D6330`). The class catalog keeps its historical
name `InventoryHint_Render`; it renders every tutorial stage's callouts and
pointers, not only inventory hints. Two primitives draw everything:

- `0x005C9C70(String, x, y)` (wrapper `0x005CA560`): measures the `menu`
  font text with `0x0043B890` -> `(w, h)`, draws UI record 4 (20 x 20
  nine-slice) through `FUN_00417760` over
  `(x - W/2, y + 4 - H/2, W, H)` with `W = w + 28` (`0x00795160`),
  `H = h + 20` (`0x007DE920`), `+4` from `0x007DE8C8`, colour
  `(0.85, 0.73, 0.44, 1)` (`0x00784D60`, `0x00788BDC`, `0x00788BE0`), then
  draws the text with `0x004A57C0('menu', String, x, y)` in centred mode:
  line `k` at `x_k = trunc(x - w_k/2)`, `y_k = trunc(y) + 25k`
  (`0x007DE960` = 25 line pitch), `h = 24 + 25(n - 1)`, `w = max w_k`.
- `0x005C9BB0(origin, direction, blink)`: draws UI record 28 (58 x 61)
  centred AT `origin` (the first float pair), rotated by
  `atan2(direction.x - origin.x, direction.y - origin.y)` in degrees (`+360`
  when negative) through `0x00414F90(origin.x, origin.y, angle)`;
  `direction` only steers the rotation and is not the painted arrowhead.
  `0x00414F90` builds a rotation matrix and sends UI 28's four local vertices
  through `0x00414540`; the sibling unrotated draw `0x004142E0` adds
  `width/2,height/2` before drawing the same centred quad, confirming the
  pivot. At every call site the pair allocated last
  (`sub esp,8` nearest the call, lowest stack address) is `origin`. When
  `blink != 0` it draws only while `0x0081F658 % 50 > 19`. `0x0081F658` is
  `App+0x28`, the 100 Hz application tick (see
  `native-movement-and-tick.md`): incremented by the base tick `0x00427800`
  from the scheduler `0x0040D1B0`, never paused (`App+0x2C` has no writer),
  skipped only while the scene-transition field `App+0x68 > 0`, and still
  counting while InventoryScreen / SkillScreen are open. A blinking pointer
  is therefore hidden 200 ms and shown 300 ms of every 500 ms, modal or not.
  `0x00403730` is `Rect::Centre` (`(x + w/2, y + h/2)`).

Pointer/callout members by stage (`Tutorial::Render` jump table `0x005D2324`
on `[this+0x7C]`; stages 0/2/11/19 draw text only), with `c(r)` the
rectangle centre, `bp`/`tome`/`belt[k]` the control rects above at the screen's
live `p` for modal stages 10/13 and the resting layout otherwise. Every
`0x005C9BB0` call
site is listed with its pushed blink immediate:

| Stage | Member | Gate | Anchor | Callout centre / pointer origin -> direction | Blink |
| --- | --- | --- | --- | --- | --- |
| 5 | secondary-slot pointer (`0x005D0EFA`) | none | secondary HUD slot | placement owned by the Website ledger 2026-08-23 row | 1 |
| 8 | first ground-Sack world pointer (`0x005D10B6`) | first registered type `0x7DD` | projected Sack | placement owned by the Website ledger 2026-08-23 row | 1 |
| 9 | inventory pointer (`0x005D11F8`) | none | `c(bp)` (`p = 0`) | `(c.x - 40, c.y - 40) -> c` | 1 |
| 10 | resume callout + pointer (`0x005D133E`) | none | `c(bp)` | callout `(c.x - 50, c.y - 120)`; pointer `(c.x - 50, c.y - 50) -> c` | 1 |
| 10 | quick-use callout + pointer (`0x005D143C`) | none | `c(belt[7])`, direction `c(belt[6])` | callout `(c7.x + 0, c7.y - 115)`; pointer `(c7.x - 20, c7.y - 50) -> c6` | 0 |
| 10 | equipment callout + pointer (`0x005D1529`) | none | `pt = FUN_00570f80([[[Game+0x15A0]+0x15C]+0x30])` = STAFF/WAND sink centre | callout `(pt.x - 250, pt.y + 50)`; pointer `(pt.x - 60, pt.y + 40) -> pt` | 0 |
| 10 | backpack callout + pointer (`0x005D16E1`) | `Game+0x15A0 && [screen+0x294]`; entry 0 of grid `screen+0x188` (`0x005D07A0`), `*entry`, holder `[[entry]+0x10]`, item `[holder]`, `[item+4] != 0` | `pt = 0x004282D0(grid, [obj+0], [obj+4])` = cell-0 top-left | callout `(pt.x + 410, pt.y - 7)`; pointer `(pt.x + 60, pt.y - 5) -> pt` | 0 |
| 12 | skills pointer (`0x005D1875..0x005D18C0` sets `origin.x`, pushes 1 at `0x005D188D`, then `jmp 0x005D11E2` into the stage-9 tail that sets `origin.y` and shares the `0x005D11F8` call) | none | `c(tome)` (`p = 0`) | `(c.x + 40, c.y - 40) -> c` | 1 |
| 13 | resume callout + pointer (`0x005D1A00`) | none | `c(tome)` | callout `(c.x + 50, c.y - 110)`; pointer `(c.x + 40, c.y - 40) -> c` | 1 |
| 13 | quick-use callout + pointer (`0x005D1AF5`) | none | `c(belt[1])` | callout `(c1.x + 0, c1.y - 125)`; pointer `(c1.x - 20, c1.y - 50) -> c1` | 0 |
| 13 | concentration pointer + callouts A/B (`0x005D1B9B`) | `[ss+0x84] > 2 && [[ss+0x90]+8]` (`ss = [Game+0x1664]`) | `pt = 0x004282D0(page[2], 100, 80)` | pointer `(pt.x + 100, pt.y - 20) -> pt`; A `(pt.x + 50, pt.y - 165)`; B `(pt.x + 50, pt.y - 100)` | 0 |
| 13 | hover pointer + callout (`0x005D1CD9`) | `[ss+0x84] > 0 && [[ss+0x90]]` | `pt = 0x004282D0(page[0], 100, 70)` | pointer `(pt.x - 100, pt.y - 30) -> pt`; callout `(pt.x - 115, pt.y - 30)` | 0 |
| 14 | selected-HUD pointer + two text lines (`0x005D1D36..0x005D1DE9`, `0x005D1DEE..0x005D1EAA`) | `[this+0xAC] == 0` (`0x005D1D29`) | primary control rect `[Game+0x3C0]` (control `+0x3AC`), concentration-A rect `[Game+0x480]` (control `+0x46C`) | origin `c(primary) + (30, 50)` -> tip `0.5 * (c(primary) + c(A))` (`0x007DE808`, `0x00784D50`, `0x007847C8`); lines at `(c(primary).x - 220, c(primary).y + 50)` and `(.., + 70)` | 1 |
| 17 | first ground-Sack world pointer (`0x005D206A`) | first registered type `0x7DD` | projected Sack | placement owned by the Website ledger 2026-08-23 row | 1 |
| 18 | potion pointer (`0x005D21BE`) and HP pointer (`0x005D2274`) | none | potion belt slot / health meter | placement owned by the Website ledger 2026-08-23 row | 1 |

Texts: `Click here or press '%s'\nagain to resume playing`, `Put items
here\nfor quick use`, `Put equippable items\nhere to wear them.`, `Found
items go in your backpack.  Click and\ndrag to move items, double-click to
use them.`, `Drag skills here\nfor quick use`, `You are CONCENTRATING
on\nyour new skill automatically`, `This confers a bonus, but is\nlimited
to one skill at a time.`, `Hover your mouse over a\nskill icon for more
information.`.

Anchor providers:

- InventoryScreen ctor `0x00560380` fits `FUN_0040f9e0(0, 54, 1024, 600)`
  with `FUN_00404000`, stores `+0x3AC = fitted.bottom - 261` (`H >= 801`;
  `-241` for 768..800; `-241 + 40` for 600..767), and places the
  `320 x 320` equipment pane at `(W - 370, +0x3AC - 400)` standalone or
  `(W/2 + 377, ..)` with a companion. `0x00551610` writes the sinks from
  `(cx, cy) = (x + 160, y + 160)`: hat `(cx, cy - 70)`, robe
  `(cx, cy + 28)`, STAFF/WAND `container+0x30 = (cx - 80, cy + 10)`,
  amulet `(cx - 67, cy - 57)`, ring0 `(cx - 67, cy + 77)`, ring1
  `(cx + 67, cy + 77)`, ring2 `-9999` unless perk byte
  `[[Game+0x1654]]+0x7DF`. At `1600 x 900` standalone the STAFF/WAND sink
  is `(1310, 259)`.
- InventoryGrid (`0x0055D830`; two instances at `screen+0x188` and
  `screen+0x298`): entry `{x, y, .., holder@+0x10}`; the draw `0x0055A070`
  translates the world matrix by `(x, y)` and draws the cell glyph at
  `(0, 0)`, so the entry position is the cell top-left. `0x004282D0(rect,
  x, y)` adds the parent chain (`+0x14`, `+0x18`; parent at `+0x70`).
  Cell 0 of the backpack grid is `(24, 496)` at `1600 x 900`.
- SkillPage builder `0x0066B380` writes the page origin to `+0x14/+0x18`;
  the root icon anchors are `(100, 80)` and `(100, 70)` inside the page.

## Not Yet Reversed

### Featured enemy / boss panel

`0x005D257E..0x005D2AEF` is a reachable native prefix guarded by `gameplay+0x1C2C`, a live actor, and its durable `EnemyConfig` at `actor+0x1D0`. It executes before the ordinary HUD and contains sprite/text work consistent with a featured-enemy presentation. The sanctioned exact-spawn seam deliberately retires the featured pointer when a spawned actor has no durable native `EnemyConfig`; a live Heartmonger attempt therefore returned “featured-enemy actor has no durable native config.” Fabricating that object would cross the observation-only boundary.

The 2026-08-21 local-meter direction audit proves only the prefix's independent
enemy current/max ratio and left-origin health-fill clipping described above.
No complete panel rect, label count, font, sprite identity, or natural featured
membership is asserted. An implementing agent must leave this branch absent or
explicitly incomplete until a naturally configured featured enemy is reachable
and settle-gated. Do not reuse the ordinary local or ally-health rect.

## 2026-08-25 stage-8 pickup secondary-report audit

A second web report described missing arrow/text at the first equipment pickup.
Retail 0.72.5 was rechecked through the canonical read-only Ghidra replica
wrapper (slot 01), using `dump_insns_around.py 80,20,0x005D0F04,0x005D10B6`.
The instruction window confirms the table above without adding a new member:

- stage 8 starts at `0x005D0F04`, looks up the first registered object of type
  `0x7DD` through `0x00646CB0`, and exits when none exists;
- with a live object it computes the camera-projected pointer geometry, pushes
  blink immediate `1` at `0x005D106D`, calls only pointer primitive
  `0x005C9BB0` at `0x005D10B6`, and jumps to the renderer exit at
  `0x005D10BB`;
- there is no call to callout/text primitive `0x005C9C70` anywhere in the
  complete stage-8 branch. Stage 9 begins separately at `0x005D10C0` and owns
  the Inventory instruction/pointer.

Therefore a web `GRAB THIS ITEM` string would be invented behavior. The exact
stock contract remains: blinking world-Sack arrow at stage 8, then Inventory
copy/control at stage 9; the SkillScreen gate remains a later stage-12 member.

## 2026-08-25 Tutorial pointer centred-quad and responsive-composition audit

A mobile web report reopened the complete `Tutorial::Render` pointer family.
The earlier report recovered all origins and direction pairs, but called the
second pair a painted `tip` and did not prove UI 28's pivot. Fresh canonical
read-only Ghidra replica queries against retail 0.72.5 (4,723,200 bytes,
SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`)
closed that gap:

- `trace_call_arguments.py 0x005C9BB0 6 1` returns 15 direct call sites, all
  inside `Tutorial::Render 0x005D08C0`: `0x005D0EFA`, `0x005D10B6`,
  `0x005D11F8` (shared by stages 9 and 12), `0x005D133E`, `0x005D143C`,
  `0x005D1529`, `0x005D16E1`, `0x005D1A00`, `0x005D1AF5`, `0x005D1B9B`,
  `0x005D1CD9`, `0x005D1DE9`, `0x005D206A`, `0x005D21BE`, and
  `0x005D2274`. The table above is therefore the complete membership.
- `0x005C9BB0` binds UI record 28 at `UI+0x15A8`, computes only an angle from
  `direction-origin`, and calls `0x00414F90(origin.x, origin.y, angle)`.
  The direction pair is never consumed as a draw position.
- `0x00414F90` creates a rotation matrix, translates it by the supplied
  origin, and calls `0x00414540`, which transforms the record's four stored
  vertices. `0x004142E0` adds the record's `width/2,height/2` before the
  unrotated draw of those same vertices. Together these instructions prove a
  centred quad: the first pair is UI 28's centre/pivot, while its visible
  arrowhead is the rotated top of the 58 x 61 record.
- Asset record UI 28 is the complete crop `(202,656,58,61)` with logical size
  `58 x 61`, no authored point, no trim offset, and nontransparent bounds
  `(2,2)..(55,59)`. No per-call-site hotspot or alternate arrow record exists.

This does not change any native origin or direction constant in the table.
It changes the browser projection contract: when a browser deliberately
uniformly scales a live HUD control for UI scale or coarse-pointer use, the
pointer's origin offset and centred UI-28 quad must receive the same uniform
scale. Tracking only the enlarged control's centre while leaving the origin
offset and quad at scale 1 is not the native composition. Fixed-stage modal
and world-projected members already share one outer transform with their
targets and retain pointer scale 1 inside that owner.
