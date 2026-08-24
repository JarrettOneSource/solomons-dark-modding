# Native Hall of Fame and Memoratorium memorial system

Status: closed for the retail executable with preferred image base `0x00400000`;
row presentation reopened and re-closed on 2026-08-22 (see
[Hall row render contract](#hall-row-render-contract-0x005a2c80)); the
Memoratorium portrait archive/FIFO producer was reopened and closed on
2026-08-24.
The executable used for static analysis and the clean populated observation has
SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

## Scope and method

This report joins two native consumers that were previously documented apart:

- the front-end `HallOfFame` controller and its scrollable `HallOfFameBox`;
- the Mortuary/Memoratorium's ordinary memorial presentation and adjacent
  eulogy/portrait branches; and
- the generic shipped `Social` leaderboard file loader, which is nearby in
  name but has no call edge into the Hall of Fame.

Evidence combines read-only Ghidra decompilation, raw x86 instructions, the
committed pristine Hall fixture, the stock atlas/bundle records, and a clean
direct launch seeded only with the retail distribution's own
`sandbox/halloffame.dat`. No loader DLL or mod was present in that populated
observation. The observed process was PID `18232`; the executable remained at
its preferred image base.

## Hall controller and collection ownership

| Owner | Address / record | Recovered role |
| --- | --- | --- |
| `HallOfFame` vtable | `0x00799334` | outer front-end controller |
| outer constructor | `0x00598120` | constructs the controller and child box |
| outer build | `0x005A07A0` | lays out the scroll box and Main Menu control |
| outer tick | `0x00589CD0` | integrates close progress and reinstalls Main Menu |
| outer continue | `0x00589DB0` | starts close only while the close rate is zero |
| `HallOfFameBox` vtable | `0x00799264` | scrollable entry collection and row input |
| box constructor/load | `0x005A13A0` | loads entries, materializes wizard views, sorts, and caps |
| box tick | `0x00589DD0` | advances entry/scroll presentation |
| row activation | `0x005981A0` | toggles one row's expanded state and recomputes extent |
| box render | `0x005A2C80` | collapsed wizard summary and expanded record details |
| death/archive writer | `0x005BC400` | appends the completed wizard record and writes `halloffame.dat` |

The outer close transition is exact: input writes rate `1.0` only when it is
currently zero. Tick integrates `progress += rate * dt`, clamps negative
progress, and installs Main Menu only after progress exceeds `1.0`. Entry-fade
input is therefore a no-op at the application surface even if a lower-level
call returns.

`HallOfFameBox` materializes the persisted wizard records, orders them by the
integer at wizard offset `+0x30`, and retains at most 100. Clean observation
identifies that sort key as the rendered `AWESOMENESS` value. The insertion
loop at `0x005A25F0..0x005A266D` stops when
`existing.awesomeness <= incoming.awesomeness`; an equal incoming record is
therefore inserted before the equal records already traversed. Because the
archive writer appends the current record, equal scores are newest-first, not
a stable oldest-first tie. The cap removes the lowest non-current entry first;
the current completed wizard is not silently discarded while the list is
reduced.

## Hall run-stat writers

The archive call at `0x005BC400` does not derive Awesomeness from experience.
It copies the already-authoritative `Game` counters into the Hall record:

| Hall field | Runtime source |
| --- | --- |
| monsters killed `WizardData+0x2C` | `Game+0x1C34` |
| Awesomeness `WizardData+0x30` | `Game+0x1C38` |
| elapsed ticks `WizardData+0x34` | `Game+0x28` |
| wave `WizardData+0x38` | local Arena wave `+0x8FF0` |
| awesomest-kill name `WizardData+0x40` | `Game+0x1CB0` |

The Time field is the Game-wide 100-Hz clock, not an Arena-entry duration.
Every base `Region::Tick` increments `Game+0x28` at `0x0063F223..0x0063F228`,
so normal Hub preparation is included. Local Player death tick
`PlayerActor+0x1BC` calls the archive writer at exactly decimal `300`
(`0x00533DCF..0x00533DE0`). The serialized value consequently includes the
three-second death presentation through that archive edge.

The same writer temporarily replaces two live PlayerActor fields before
serializing the wizard composite, then restores them afterward:

```text
portraitHeading = float32(180 + Float(65, signed))  // 115..245 degrees
portraitScale   = float32(0.85 + Float(0.15, unsigned)) // 0.85..1.0
```

The instruction spans are `0x005BC437..0x005BC488` and
`0x005BC48B..0x005BC4B8`; constants are exact float/double values
`65`, `180`, `0.15000000596046448`, and `0.8500000238418579`. These three
native RNG words and the resulting pose belong to the archived row. A Hall
renderer that reuses the corpse's last heading or fixes every portrait scale
to one is not reading the stock record.

Every staged contact returns through the shared Region callback
`0x0063E7D0` (84 direct callsites). When the contacted actor's virtual `+0x4C`
reports the newly accepted lethal state, that branch immediately calls the
awesomest-kill writer `0x005C9F40`, awards the enemy's experience, adds one
kill through `0x005C9430`, and finally calls the Awesomeness writer
`0x005C94E0` with base value one. Those are separate counters; experience is
not a score proxy.

`0x005C94E0` applies the following exact integer score recipe while an Arena is
active:

```text
pulseGate = trunc(min(regionPulseAccumulator + 0.5, 1.0))  // 0 or 1
points = basePoints * pulseGate

if local player is not in its alternate/death state:
    if currentHealth < 0: points *= 3
    else if currentHealth / maximumHealth < 0.1: points *= 2

streakMultiplier = clamp(
    floor((playerLevel * 100 + killStreak) / (playerLevel * 100)),
    1,
    5,
)
points *= streakMultiplier
awesomeness += points
```

Without an Arena, the raw base value is added. The health threshold is the
double at `0x007849E8`, exactly `0.10000000149011612`; the half-rounding term
at `0x007DE808` is exactly `0.5`. Potion use (`0x0056D1B0` subtype family
`0x1B59`) resets `Game+0x1CCC` through `0x005CB810` before applying the potion.

The awesomest-kill path compares the enemy's constructed maximum health at
actor `+0x170` against `Game+0x1CAC`. Once a prior positive maximum exists it
increments the kill streak before the comparison. A new maximum first awards
`71 + Integer(5) * playerLevel` through the same multiplier recipe, then
stores the exact formatted enemy name and maximum. The subsequent connected
death still adds the ordinary base-one award and kill count. The complete
formatter covers Skeleton equipment/burning variants, Archer headgear and
Fire/Poison variants, all four Skeleton Mage elements, Imp/Green Imp, Zombie
and Rotten Zombie, Wraith, The Discorporeal, Lesser Demon/Legion, Dire
Faculty, Heartmonger, Putrid/Tainted Coffin, Maggot, Spider, and Deep Portal.
The Coffin split is live actor `+0x238`, copied from recipe `+0x90`: zero
poison damage formats as Putrid and a positive Maggot-poison payload as
Tainted; it is not the max-Maggot field at actor `+0x22C`.

Awesomeness shares the Region pulse accumulator at `+0x8E08`; this is the
same state consumed by Arena world scaling, not a private Hall combo meter.
`Region::Tick 0x0063EFC0` subtracts `0.0025` per 100-Hz tick with a `0.1`
floor. `Region::ApplyCameraShake 0x0063EEB0` adds float32
`0.20000000298023224`, capped at `3.5`, after writing the presentation
magnitude. The complete ordinary death-presenter membership is:

| Later death presenter | Pulse request(s) |
| --- | --- |
| Skeleton / Archer / Mage `0x0048D2A0` | `0.1` |
| Imp `0x004824A0` | `0.05` when the two-child split is accepted; otherwise `0.1` |
| Zombie `0x004947B0` | `0.1` |
| Wraith `0x00495600` via shared dissolve `0x0047F8D0` | `0.1`, then `0.1` |
| Demon terminal helper `0x00482930` | `0.2` |
| Coffin `0x0049B310` | `0.2` |
| Dire Faculty `0x0049E8F0` | `0.2` |
| Heartmonger `0x0049FB60` | `0.2` |

Absorbed/sucked deaths take the shared dissolve branch and its single `0.1`
request instead of the family payload. Maggot retirement suppresses the
reward path. The Website survival roster exposes the first eight ordinary
families through Coffin; Dire Faculty, Heartmonger, the story bosses, external
portal actors, and absorbed-death producer remain separate product surfaces.

The order is material: the lethal-contact callback and both score writes occur
before that actor's later family death presentation requests its pulse. A kill
therefore reads the accumulator left by prior presentations; it does not count
its own pulse. The new-maximum bonus reads the pre-XP player level, experience
is then awarded, and the ordinary base-one call reads the resulting post-XP
level. This ordering is visible at `0x0063E81D..0x0063E85C` and must remain one
host transaction.

`0x005BC400` has one adjacent story-boast adjustment: a completed authored
Annalist boast multiplies the accumulated score by `1.100000023841858` and
truncates it before serialization. The ordinary survival path has boast index
`-1`, so this does not modify survival records. It belongs with the Hall's
already-dispositioned story/boast row branch rather than the Website survival
score.

## Hall row contract

The stock row has two visible states.

Collapsed:

- one-based rank (`#1`, `#2`, ...);
- the live serialized wizard composite;
- wizard name;
- `LEVEL <n> <discipline>`; and
- `AWESOMENESS: <n>`.

Class-title lookup `0x00658B40` drains the complete element-root by
discipline-root table (`body=5`, `mind=6`, `arcane=7`):

| Element | Body | Mind | Arcane |
| --- | --- | --- | --- |
| Ether | Sage | Seer | Occultist |
| Fire | Warlock | Pyromancer | Fire Mage |
| Air | Stormcaller | Astrologer | Storm Mage |
| Water | Icebinder | Thaumaturge | Frost Mage |
| Earth | Ritualist | Channeler | Earth Mage |

The fallback outside those 15 rows is `WIZARD`; valid Website loadouts never
need that invalid-selector fallback.

Expanded survival record:

- `SURVIVAL`;
- `TIME` and `WAVE`;
- the three highest learned skills, including icon and rank;
- `MONSTERS KILLED` and `AWESOMEST KILL`; and
- the authored 3-by-3 `PERKS USED` grid.

The renderer also has the compiled story/boast branch: boast text, failed,
succeeded, and not-accomplished states. That branch is data-bearing native
behavior, not another leaderboard metric.

The clean populated sample showed:

```text
#1 VOLUSIUS
LEVEL 1 SEER
AWESOMENESS: 91

SURVIVAL
TIME: 0:05:39
WAVE: 1
MONSTERS KILLED: 17
AWESOMEST KILL: SKELETON
```

The pristine committed fixture correctly shows the same frame with no entry
rows. Empty is a valid collection state, not a loading error.

### Highest-skill selection and colour ownership (2026-08-23 correction)

The 2026-08-22 render pass recovered the three destination fields and their
draw order but did not trace the producer that fills them. That omission let
the Website rank every positive serialized skill row, including the element
and discipline roots, even though stock ranks only the learned/visible list.

`HallOfFameBox` construction initializes the three skill-id fields at entry
`+0x88`, `+0x8C`, and `+0x90` to `-1`. The instruction range
`0x005A2210..0x005A22F3` then fills each slot independently:

1. scan the ordered learned/visible skill-id list at
   `Skills_Wizard +0x850/+0x854`;
2. skip an id already present in any of the three destination fields;
3. read its permanent rank from the signed 16-bit row field `+0x22`;
4. replace the current candidate only when `candidateRank > bestRank`; and
5. repeat for the next destination slot.

The strict comparison makes ties preserve `+0x850` list order. The list is
the same authoritative public-skill membership consumed by Skill Screen
construction (`0x0066B380`): roots `0..7` live in the rank table but are not
members, public learned rows `8..79` are members in acquisition order, and
runtime Plane Orb `80`, reserved row `81`, and the row-82 storage pad are not
members. Thus a fresh Ether/Mind wizard produces rows `8` (Magic Missile) and
`11` (Call Leviathan), followed by an empty third slot. The clean level-one
capture `solomon-hall-20260822/04-hall-expanded.png` shows exactly those two
icons and one empty frame.

Colour lookup is a separate renderer contract. The virtual call used by
`0x005A2C80` is `Skills_Wizard::vftable +0x90 -> 0x00660CE0`. It reads the
selected row's root field at `+0x1C`, maps that root through the eight-entry
wizard colour table, and returns the tint used on Skills record `164`.
Constructor `0x00674EE0` stores each root row's own id in `+0x1C` for rows
`0..7`; descendants store their owning root, and Plane Orb `80` stores Ether
root `0`. Therefore the renderer can colour a root row correctly if supplied
one, although the stock highest-skill producer never supplies roots. This
distinction matters for Website records written by the faulty pre-correction
producer: they can remain visible without weakening the native selection rule.

Validation receipt: the selection loop was decompiled from the canonical
read-only `SolomonDark` Ghidra replica and its strict comparison was confirmed
against raw instructions `0x005A2210..0x005A22F3`; vtable slot `+0x90` resolved
to `0x00660CE0`. The corrected report on base `17e5a6be` was transferred
byte-identically to the Mac worktree
`/Users/jarrett/codex-acceptance/hall-skill-native-re-20260823.z4DZyv/mod-loader`.
The final exact-tree
`python3 tests/re/run_static_re_tests.py --ci` run passed `494/494`.

## Hall row render contract (`0x005A2C80`)

Recovered 2026-08-22 against the same retail image (SHA-256 above). The
2026-08-20 pass closed the row as a text list; this section is the full draw
contract of `HallOfFameBox::Render` (`0x005A2C80`), verified pixel by pixel
against a clean populated 1600x900 stock capture (`solomon-hall-20260822`,
PID 1856, 19:43:56-20:01:58 local). Every number below is box space unless it
says screen space; the box is `(200, 80)`-`(1400, 775)` at 1600x900, so
`W = 1200`, `H = 695`, and screen = box + `(200, 80)`.

### Cursor, pen, and row cadence

- `yCursor` starts at `80`. Each row advances `yCursor += 250` (`rowH`), plus
  `150` (`expH`) first when the row is expanded.
- Every sprite and text draw of a row goes through a pushed pen
  `pen = (px, yCursor + 15)`. On wide clients (`>= 1280` px) `px` starts at
  `-10`, becomes `+10` after the skill block (`px += 20`) and `+25` after the
  perk block (`px += 15`). The highlight rectangle and the separators are
  computed from `yCursor` directly and do not move with the pen.
- Narrow clients (`< 1280` px) take a second layout branch with different
  column constants. The Website stage is fixed at 1600 wide, so only the wide
  branch was extracted; the narrow branch stays documented as unreachable.
- Global tick: 100 Hz (`elapsedTicks / 100` is the same clock the survival
  time formats). Pulses below use `sin(tick * 3 deg)`, period 1.2 s.

### Background

- UI record `49` (`264x264`) tiled 5 columns by 4 rows across the box. The
  tile origin is the box origin plus the scroll offset modulo 264, so the tile
  scrolls with the content. The unscrolled capture matches a 264-pixel vertical
  period aligned to the box top (mean abs diff 6.2 at `dy = 264` against
  13.8 at `dy = 263/265`).

### Row block (`rowH = 250`)

| Member | Draw | Position |
| --- | --- | --- |
| Highlight rectangle | filled rect | `(50, yCursor - 25, W - 100, rowH - 10 + (expanded ? expH : 0))` |
| Current-wizard fill | gold `(0.85, 0.73, 0.44)` | alpha `0.1 + 0.05 * sin(tick * 3 deg)`; other rows draw no fill |
| Row frame | 9-slice UI record `17` (`80x83`), white | current wizard alpha `0.5 + 0.2 * sin(tick * 3 deg)`; other rows alpha `0.2` |
| Rank numeral | font 4 (heading, 29 px digits), gold, centered | baseline `(W/2 - 60, pen.y + rowH/2 - 65)` = `(540, yCursor + 75)` |
| Rank ornament | UI record `25` (`22x21`), center-anchored | `(W/2 - 60 - rankW/2 - 11, pen.y + rowH/2 - 65 - 10.5)`; `rankW` = measured numeral width, so the ornament's right edge meets the numeral's left edge |
| Wizard composite | serialized wizard (`entry + 0x20`) incl. the element orb VFX, RNG seed 5 swapped around the draw | scale `1.25 * entry.portraitScale`, anchor (frame center / feet) `(W/2, pen.y + 73)` = `(600, yCursor + 88)` |
| Name | font 3 (menu), gold, centered | baseline `(W/2, pen.y + 125)` = `(600, yCursor + 140)` |
| `Level %d %s` (exe string `0x0079965c`; `%s` is the class name in capitals) | font 1 (medium, font object `+0x4d530`), gold, centered | baseline `(W/2, pen.y + 140)` = `(600, yCursor + 155)` |
| `Awesomeness: %d` (exe string `0x0079964c`) | font 1 (medium), gold, centered; `eA` = measured medium width (`155` for `Awesomeness: 91`) | baseline `(W/2, pen.y + 155)` = `(600, yCursor + 170)` |
| Expand chevron | UI record `9` (`22x20`), gold, center-anchored, rotated 90 deg collapsed / 180 deg expanded; quad placed per "Sprite placement" below | `(W/2 - eA/2 - 25, pen.y + 140)` = `(600 - eA/2 - 25, yCursor + 155)`; the click hotspot is the chevron's rect and toggles `entry + 0x10c` |

Capture proof (row 1, `yCursor = 80`, screen space = box space + `(200, 80)`;
the capture's client origin is `(3, 26)`): highlight top `135`;
name `VOLUSIUS` ink `731-866 x 284-300` (center 798.5, baseline 300);
`Level 3 SEER` ink `741-858 x 304-315` (medium width 118, centered pen 740;
column 0 of `L` is the blank atlas gutter so the ink starts at 741 — the
first-pass "font 0" reading measured the all-capitals string `LEVEL 3 SEER`
against 113.5 body / 138.5 medium and is withdrawn); `Awesomeness: 91` ink
`722-873 x 319-330` (medium width 155, pen 722); chevron ink `688-707 x
306-323` (center 697.5 = `800 - 155/2 - 25`); rank `1` ink
`733-743 x 208-234` (centered at 740, baseline 235); ornament ink
`704-724 x 214-234` (center 714 = `725.5 - 11`, 224 = `234.5 - 10.5`);
composite ink `774-869 x 174-253` around the anchor `(800, 248)` with 1,723
ether-purple orb pixels at `831-869 x 179-239`.

### Expanded block (`expH = 150`, `T = pen.y + rowH - 75`)

All text is gold unless stated. `T` lands at `yCursor + 190`.

| Member | Draw | Position |
| --- | --- | --- |
| `SURVIVAL` | font 1 (medium), left | `(100 + px, T)` |
| `Time:` / `Wave:` labels | font 1, left | `(131 + px, T + 20)` / `(120 + px, T + 35)` |
| Time / wave values | font 1, left, plain gold | `(180 + px, T + 20)` / `(180 + px, T + 35)` |
| `HIGHEST SKILLS` | font 1, left | `(100 + px, T + 70)` |
| Skill cell `i = 0..2` | see below | `cellX = 100 + 60 i + px`, `Y = T + 108`, anchor center `(cellX + 30, Y)` |
| `PERKS USED` | font 1, right-aligned, after `px += 20` | `(W - 100 + px, T)` |
| Perk cell `k = 0..8` | Inventory record `10` scale `0.57`, then Skills record `127 + selector` scale `0.7` when the perk exists; no numeral | center `(W - 162 + 42 gx + px, T + 75 + 42 gy)`, `gx = k % 3 - 1`, `gy = floor(k / 3) - 1` |
| Kills box | after `px += 15`; `y_k = T + expH/2 - f60/2 + 8`, `f60 = 50` (the font-3 line box), `-18` when the boast branch adds a line | `Monsters Killed: %d` font 1 centered `(W/2 + px, y_k)`; `Awesomest Kill:` font 1 centered `(W/2 + px, y_k + 20)`; awesomest name font 3 centered `(W/2 + px, y_k + 40)`; 9-slice UI record `50` (`13x14`) white alpha `0.5` at `(W/2 - 150 + px, y_k - 30, 300, f60 + 40)` |
| Boast / story branch | boast text and failed / succeeded / not-accomplished states | campaign data only; no Website counterpart |

Skill cell draw order (anchor `(cx, Y) = (cellX + 30, Y)`):

1. empty slot: Inventory record `10` (`72x72`) at scale `0.8`, nothing else;
2. otherwise Skills record `164` (`57x57`) tinted with the skill's element
   color (`skillbook slot + 0x90`), scale `1`;
3. Skills record `27 + skillId` at scale `0.9`;
4. black alpha `0.5` badge rect `(cellX + 52 - w, Y + 11, w + 3, 15)` where
   `w` = font-0 width of the rank string;
5. rank numeral, font 0, white, right-aligned at `(cellX + 53, Y + 22)`;
6. Inventory record `10` frame at scale `0.8` on top.

Capture proof (row 1 expanded): `SURVIVAL` ink `291-379 x 339-350`
(baseline 350 = `80 + 255 + 15`); `Time:` `321-356`, values from `371`;
`Wave:` `310-356`, value `373`; `HIGHEST SKILLS` `290-435 x 409-419`; skill
frames `292-347`, `352-407`, `412-467` x `430-484` (centers 319.5 / 379.5 /
439.5 x 457); `PERKS USED` right ink edge `1308` (`1310 = 1300 + px 10`);
perk grid center `(1248, 425)` (`1048 = 1200 - 162 + 10`); kills frame ink
`675-974 x 378-467` (`675 = 800 - 150 + 25`, height 90 = `f60 + 40`);
`Monsters Killed` ink `736-911 x 396-408` (center 823.5, baseline 408 =
`y_k`); `Awesomest Kill:` bottom 428/429; awesomest name ink `752-895 x
427-448` (baseline 448 = `y_k + 40`). The measured medium widths of
`SURVIVAL` (91), `PERKS USED` (116), and `HIGHEST SKILLS` (147) match the ink
within 2 px, which is what proves the name-block lines are the smaller font.

### Separators

After `yCursor += rowH`, two 2-px lines at `y = yCursor - 50`:
`(150, y) -> (W/2, y)` and `(W - 150, y) -> (W/2, y)`. Each is a gradient from
transparent gold at the outer end to opaque gold `(217, 186, 112)` at the
center. The instruction-derived reading of the gradient direction was wrong;
the capture (first separator at screen `y = 359-360`, bright at `x = 800`,
fading toward `350` and `1250`) fixed it. The ramp is linear in alpha; the
brighter row under it belongs to the row frame (see the mirrored-texel note
in the 9-slice section), not to the separator.

### 9-slice primitive (`FUN_00417760`)

`FUN_00417760(glyph, x, y, W, H, fill)` draws a frame from a single corner
glyph of size `w x h`:

- corners: top-left as drawn; top-right mirrored in X; bottom-left mirrored in
  Y; bottom-right mirrored in both;
- top and bottom strips: the glyph's last `5%` of columns (UV `0.95..1.0`,
  constant `_DAT_007de96c = 0.95`) stretched across `W - 2w`; the bottom strip
  is the vertical mirror;
- left and right strips: the glyph's last `5%` of rows stretched across
  `H - 2h`; the right strip is the horizontal mirror;
- `fill` is `0` for both Hall frames (row frame record `17`, kills box record
  `50`), so the interior stays untouched;
- mirrored pieces sample texel `w - j` (or `h - j`) at pixel `j`: the art
  lands one pixel further out along each mirrored axis and the glyph's
  column / row 0 (the transparent atlas gutter) is never drawn on the mirrored
  sides. Measured on the row frame: the right edge's column profile
  `[61, 61, 52, 48]` is the left edge's `[58, 61, 53, 45]` mirrored and shifted
  by exactly +1 px, and the frame's inner decorative line sits one pixel lower
  on the bottom strip than a naive mirror predicts. That inner line, not the
  separator, is the "brighter row" visible under each separator.

### Sprite placement (`FUN_00414ea0` / `FUN_00414f90`)

Traced (Ghidra, 2026-08-22): a UI sprite is drawn by `FUN_00414ea0(x, y, scale)`
(uniform scale matrix) or `FUN_00414f90(x, y, angleDeg)` (rotation matrix from
`FUN_00403120`: `angle = -deg * pi / 180` with the pi global `DAT_00b4027c`;
the chevron passes `_DAT_00785d98` = 90 collapsed and `_DAT_00784738` = 180
expanded). Both add the translation `(x, y)` to the matrix and call
`FUN_00414540`, which transforms the sprite's four stored corners
(`sprite + 0x2c .. + 0x48`) as floats and hands them to `TextQuad_Draw`
(`0x0041e990`); `FUN_00412d70` appends each vertex verbatim (corner + the
renderer's pending translation `+0x68 / +0x6c`, tint `+0x448`, UV) and
`FUN_0041c540` emits the two triangles. Nothing in that path rounds or applies
a pixel-center correction, so sprite quads are not snapped to whole pixels.

Measured (alpha-aware bilinear fit of the stock captures against the atlas
art, box space): the unrotated rank ornament (UI `25`, `22x21`, nominal quad
left/top `503.5 / 134`) sits at `503.75 / 134.05`; the chevron (UI `9`,
`22x20`, nominal center `(497.5, 235)`) sits at `488.25 / 224.05` collapsed
(90 deg, nominal `487.5 / 224`) and `487.30 / 225.85` expanded (180 deg,
nominal `486.5 / 225`). The rotated states are therefore about `+0.75 px`
right of nominal and the 180 deg state about `+0.85 px` lower, with
bilinear-soft edges on all four sides. That pattern is consistent with the
stored corners carrying a half-pixel bias that rotates with the quad against
Direct3D 9's half-pixel convention; the corner values themselves were not
dumped, so the sub-pixel offsets are carried as measurements. The nearest
whole-pixel quads are `x 488..507, y 224..245` collapsed and
`x 487..508, y 226..245` expanded (within 0.3 px of the fitted positions);
the earlier claim that the sprite pass itself snaps to round-half-up edges
is withdrawn.

### Fonts and anchors

| Group | Name | Nominal px | Line box | Space advance |
| --- | --- | --- | --- | --- |
| 0 | body | 13 | 28 | 3 |
| 1 | medium | 16 | 28 | 4 |
| 3 | menu | 24 | 28 | 6 |
| 4 | heading | 40 (digits 29 px tall) | 28 | 20 |

Text anchors are baselines. Every metric is an integer (per-glyph advance /
`offX` / `offY`, the 105 kerning pairs, the space advances), and the pen is
an integer: centered text (`String_Assign(font)`) starts at
`pen = trunc(x - width / 2)` (= `x - ceil(width / 2)`), right-aligned text
(`FUN_0042d610`) at `x - width`, left-aligned text
(`DarkCloudBrowser_ExactTextRender`) at `x`; `FUN_0042d700` measures a
string. Each glyph quad is then placed at
`left = round-half-up(pen + offX - w / 2)`,
`top = round-half-up(y + offY - h / 2)` (per-glyph `offY` negative) and
`pen += advance + kerning`, so every quad sits on whole pixels and the glyphs
are crisp — there is no half-pixel blur. Verified by per-glyph fits on 73
glyphs across 7 strings of the 2026-08-22 captures (every quad on a whole
pixel, constant +0.125 fit phase from the colour model). Colour is set through
`FUN_0041fe50`; the `0.85` constant next to the row text is the red channel
of the gold `(0.85, 0.73, 0.44)`, not a font scale. Font objects:
`+0x1351cc` = group 4 (rank numeral), `+0xe7d98` = group 3 (name, awesomest
kill — rendered exactly as stored), `+0x4d530` = group 1 (every other row
line). Sprites go through `FUN_00414ea0`, gradient rects through
`FUN_0041dd70`. The font has no `…` glyph; what the renderer does with a
character the font lacks was not traced.

### Scroll and current-wizard behavior

- Rows whose wizard id equals the active wizard (`DAT_00819ed8`) are the
  "current" rows: they get the pulsing gold fill and the brighter frame,
  default to expanded (`entry + 0x10c = 1` on load), and the box performs a
  one-shot scroll to the first current row (`box + 0xDC`).
- The scroll extent is `yCursor - H` after the last row. The mouse wheel
  scrolls the box; the expand toggle only flips `entry + 0x10c` and never
  writes the scroll. (The earlier reading that the toggle "eases the scroll so
  the expanded row stays in view" was wrong: the only eased scroll write in
  the box tick is the one-shot program below.)
- One-shot scroll contract, box fields: `+0xDC` pending target (float; init
  `-2.0` = `_DAT_00784edc`, "never targeted"; `-1.0` = `_DAT_007de858`,
  "done"), `+0xE0` ease counter (init 0), `+0x84` / `+0x88` scroll x / y,
  `+0xFC` = 250 (`_DAT_007853a0`, row height), `+0x100` = 150
  (`_DAT_0078489c`, expansion height; the narrow client overrides it), `+0x20`
  = box height `H` (695).
  - Render (`0x005A2C80`), the first frame that draws the current row while
    `+0xDC == -2`: `f = max(0, yCursor + 250 + 150 + 0.25 * H)`;
    `target = f - (250 + 150) - 0.5 * H = yCursor - H / 4` (`rowTop - 173.75`
    at `H = 695`); `+0xDC = target`; the scroll is pushed through vtable slot
    `0xC4 / 4` `setScroll(x, y)` (which clamps to the extent), `+0xDC` is
    re-read from the clamped scroll, and the previous scroll is restored so
    the ease starts from the old position.
  - Box tick (`0x00589DD0`, 100 Hz) while `+0xDC > 0`:
    `scroll = sin(pi * t / 180) * target` with `t = +0xE0`, then `t += 1.0`
    (`_DAT_007de820`); once `t >= 90` (`_DAT_00785d98`) it writes
    `+0xDC = -1`; `setScroll(x, scroll)` runs every tick. The sine is the CRT
    `_CIsin` (`0x007470d0`, `FSIN` at `0x00747128`); pi is `_DAT_007de8a8` =
    3.14159274f copied into `0x00b4027c` by `0x004100d0`; the divisor is
    `_DAT_007de888` = 180.0. Net effect: the scroll eases from 0 to
    `sin(89 deg) * target` over 90 ticks (0.9 s) and parks the current row a
    quarter box below the top edge.
  - Other constants on this path: `_DAT_007847b8` = 80.0 (`yCursor` start),
    `_DAT_007de808` = 0.5 (double), `_DAT_007de8f0` = 0.25 (double),
    `_DAT_007de810` = 10.0.
- The toggle path contains no sound call.

## Global leaderboard adjacency

Retail has a separate generic `Social` singleton at `0x00B40600`, vtable
`0x007DE2FC`. Constructor `0x004452B0` owns two lists:

- `PointerList<SmartPointer<Leaderboard>>` at `Social+0x24`; and
- `PointerList<SmartPointer<Achievement>>` at `Social+0x3C`.

Loader `0x00445480` enumerates `social\`. It parses
`social\__achievements.dat` into achievements and every other accepted file
into a `Leaderboard` record containing a name plus a
`PointerList<SmartPointer<HighScore>>`. The shipped content tree has neither a
`social` directory nor any leaderboard file. An exhaustive direct-reference
scan of `0x00B40600..0x00B40654` found only construction, destruction, config
initialization, and this loader; the Hall constructors/renderers never touch
the Social block.

Therefore retail ships a dormant generic file format, not an online Hall of
Fame. A Website-global board is a product extension. It should reuse the
Hall's visible metrics and ordering vocabulary, but must not claim that the
retail Hall queried a server.

## Memoratorium consumer closure

The ordinary Mortuary composition is:

1. record 0 architecture before world actors;
2. ten Painting composites: record 3, portrait `14+id`, record 7, and optional
   record 8 at Painting-relative `(10,15)`;
3. the 16-heading Memorator body/head bank `28+i` plus `44+2i` and ordinary
   question marker 27;
4. 50 additive record-1 flames;
5. every normal world actor/effect consumer; and then
6. record 5 submitted three consecutive times at the room center after a
   five-unit vertical registration adjustment.

The record-5 pass is instruction-level, not an atlas-xref inference. At
`0x0050F45C`, `0x0050F4DE`, and `0x0050F567`, `ECX` is loaded from the
Memoratorium singleton and advanced by `0x40C`, the exact record-5 field. The
three calls at `0x0050F4D3`, `0x0050F55C`, and `0x0050F5E5` submit the same
registered `71 x 54` white memorial glow. Its world root is the room center,
`(512,507)` for the normal `1024 x 1024` Mortuary. The previous room report
recorded record 5 as effect-owned but the Website port implemented only the
record-1 flame family; that silent member caused the reopened room report.

The adjacent stateful branches remain distinct:

- portrait id `-1` selects blank easel record 4;
- portrait ids `0..9` select bundled records `14..23`;
- ids `>=100` load `Portraits\portrait<id>` and draw the raw captured image;
- marker bits select the urn overlay record 8;
- nonzero `Region+0x8F10` drives the Memorator eulogy state machine at
  `0x00513090`, including records 2, 6, and 7; and
- `Annalist2` uses records 11..13 in the alternate story population.

The normal new-game values remain portrait ids `0..9` and marker bits
`0,1,1,1,0,1,1,0,0,1`. The Website survival loop has no story campaign, so
the `Annalist2` replacement and story-only population are outside that product
surface. The ordinary glow, portrait, marker, Memorator, flame, collision, and
transition members are not optional.

## Memoratorium portrait archive and FIFO producer (2026-08-24 reopening)

The earlier consumer closure stopped at the three renderer branches and left
the producer behind portrait ids `>=100` untraced. That omission also caused
the save-format report to misname two persisted ten-element arrays as class
selector permutations. Read-only Ghidra decompilation and raw instructions now
close the full producer against the same retail image named above.

### Persisted state and defaults

The profile singleton is rooted at `0x0081A330`. Its initializer
`0x005A8390` writes the complete memorial state:

| Profile field | Runtime address | Default | Recovered role |
| --- | --- | --- | --- |
| marker bits `+0x90[10]` | `0x0081A3C0..0x0081A3C9` | `0,1,1,1,0,1,1,0,0,1` | record-8 urn marker for each Painting slot |
| age stamps `+0xA4[10]` | `0x0081A3D4..0x0081A3FB` | `9,1,0,2,7,4,3,8,5,6` | FIFO age for each physical Painting slot |
| portrait ids `+0xCC[10]` | `0x0081A3FC..0x0081A423` | `0..9` | bundled id `0..9`, blank `-1`, or external raw id `100..109` |
| age counter `+0xF4` | `0x0081A424` | `1000` | monotonically incremented by each portrait capture |
| next raw id `+0xF8` | `0x0081A428` | `100` | next `Portraits\\portrait<N>.raw` id |
| latest raw id `+0xFC` | `0x0081A42C` | `0` | portrait carried into the completed-run Mortuary |

All six fields are serialized through the existing `darkdata.cfg` profile
path. The age permutation is deliberately not spatial order: its ascending
slot order is `2,1,3,6,5,8,9,4,7,0`, so the first ten completed portraits
replace the ten authored residents in exactly that sequence.

### Capture, rollover, eviction, and reveal

`PlayerWizard` local death calls portrait writer `0x005BED10`. The writer
temporarily presents the wizard alive, selects the already-documented random
heading and scale, draws `images\\paintbkg` into a `64 x 64` capture, places the
wizard at capture center plus 20 pixels on Y, and writes raw RGBA bytes to
`Portraits\\portrait<profile+0xF8>.raw`. Instructions
`0x005BF3B6..0x005BF3CD` then increment the age counter, copy the current raw
id to `+0xFC`, and increment the next raw id.

The completed-run transition `0x005CF4F0` constructs the Mortuary, writes
`Region+0x8F10 = 1`, copies the latest raw id into `Region+0x8F14`, and resets
the next id to `100` only when it has advanced past `109`
(`0x005CF85A..0x005CF88A`). The files are therefore a ten-id ring, not an
unbounded archive.

`Mortuary::Build 0x00515290` scans all ten age stamps at
`0x0051549F..0x00515547`. Every comparison is strict: it replaces the current
candidate only when the next age is lower. The minimum age is evicted; an
equal-age tie keeps the lower slot index already selected. The chosen slot is
then updated atomically at `0x00515547..0x0051557A`:

```text
marker[slot] = Integer(5) != 3
portraitId[slot] = -1
age[slot] = profileAgeCounter
memorator.selectedSlot = slot
```

This is FIFO eviction by persisted age. It is neither Hall Awesomeness order
nor a fixed spatial ring cursor.

`Memorator::Tick 0x00513090` owns the staged ceremony. State 0 begins with a
235-tick countdown; state 1 waits 25 more ticks and then copies
`Region+0x8F14` into both the selected Painting actor's `+0x174` and the
persisted portrait-id slot; states 2 and 3 retain the subsequent 50- and
100-tick presentation intervals. `Mortuary::RenderPainting 0x00518620` then
selects blank easel record 4 for `-1`, bundled portrait `14+id` for `0..9`, or
the raw capture for `100..109`, always inside records 3 and 7 and with optional
marker record 8. Painting callback `0x00506190 -> 0x00506100` formats
`SAY_EULOGY_<current portrait id>`, so the interaction follows the replaced
portrait rather than the physical easel's original id.

### Multiplayer/Web consequence

Retail owns one persisted local profile and one completing wizard. A Website
shared-Hub memorial is therefore an explicit authority extension: the server
must apply the same ten-slot age/FIFO rule to every completed participant,
publish the resulting slots in the authoritative Hub snapshot, and let late
joiners receive that same state. A browser-local list, Hall-score sort, or one
memorial per party would contradict both the recovered owner and the requested
shared-Hub product boundary.

Validation receipt: after rebasing onto `c00f8143`, the eight-file Mod Loader
manifest was byte-identical in the Mac worktree. The registered
`python3 tests/re/run_static_re_tests.py --ci` suite passed `500/500`, including
the new strict-min FIFO, ten-id ring, reveal, and corrected profile-field
contract. No native binary, loader runtime, push, or deployment changed.

## Implementation consequences

- Keep local browser history at the native 100-entry cap, descending
  Awesomeness order, and newest-first equal-score insertion.
- Replicate the authoritative run counters rather than reconstructing score
  from experience or retained client events. Use the same complete
  death-presenter pulse membership for Arena feedback and the score gate.
- Start Time with the Game/Hub lifecycle, freeze it at local death tick 300,
  and archive the writer-selected heading/scale from the same RNG stream.
- Preserve all collapsed and expanded survival fields. Website-global views
  may additionally sort those same records by wave, kills, or survival time,
  but those are explicit web views rather than invented retail behavior.
- Treat global submission and public query as Website ownership. Account
  authentication alone is not score provenance: the backend must bind the
  account id into the consumed server admission, the authoritative host must
  seal the completed row, and the API must verify that signed receipt against
  the caller. Guests and cheat-tainted runs remain local-only.
- Track initial and live `Enable Cheats` state at the host. Enabling it during
  an authoritative connection permanently revokes that connection's global
  eligibility; disabling it later does not restore eligibility. An accepted
  authoritative Lua execution independently revokes it. Any ineligible party
  participant taints the shared run.
- Treat the current client-held save document as untrusted provenance. Its
  schema validates shape but carries no server attestation, so a resumed
  lineage remains local-only rather than turning a forged save into a signed
  global score.
- Use the serialized wizard's element and heading for its row portrait instead
  of substituting an unrelated account avatar.
- Render Memoratorium record 5 as the exact extracted registered asset, three
  additive submissions at `(512,507)`, after normal actors/effects.
- Do not route the Hall through the dormant Social file loader, and do not
  describe that loader as a network service.

## Validation contract

- Collection tests cover empty, newest-first ties, all four visible metrics, the
  100-entry cap, idempotent run identity, and every expanded survival field.
- Score-kernel tests cover the pulse gate, every family pulse request, both
  health multipliers, the capped level-scaled streak multiplier, potion reset,
  new-maximum RNG bonus, exact variant names, and bonus-before-base ordering.
- Archive tests cover the Game-wide clock, death tick 300, signed heading draw,
  scale draw, RNG advancement, and one-time immutable pose.
- API tests cover signed server provenance, authenticated account binding,
  guest/body/signature/account tamper rejection, strict enums and bounds,
  idempotency, public reads, and independent Awesomeness/wave/kills/time
  ordering. Host tests cover clean receipt issuance plus anonymous, resumed,
  initial-cheat, live-cheat, and accepted-console withholding.
- Browser tests enter Hall from the stock main-menu control, exercise local and
  global boards, expand a row, scroll, and return through the Main Menu control
  without page or console errors.
- Mortuary tests assert record-5 identity, size, count `3`, position `(512,507)`,
  additive blend, and late painter depth, then the real room journey captures
  the settled 1600-by-900 scene.

## Validation receipt

- The 2026-08-21 authority reopening replaced browser-authored global rows with
  account-bound host HMAC receipts and made anonymous, resumed, initial-cheat,
  live-cheat, and accepted-console branches local-only. Rebased Website focused
  matrices passed protocol `24/24`, host authority/resume `4/4`, supervisor
  `8/8`, and Hall `17/17`; the signed API integration passed raw-body,
  signature-tamper, account-mismatch, idempotency, and all four sort branches.
- The Mac mini ran the exact Website canonical matrix successfully and passed
  Loader static CI `491/491`. A Windows-native clone passed the same Website
  matrix after closing two checkout-line-ending test defects; native Chrome
  displayed the signed global row on all four boards with zero page/console
  errors while raw and tampered submissions failed closed.
- Static/native tooling: the focused binary-layout identity contract passed
  against the root and staged Solomon Dark Beta `0.72.5` layouts after the Hall
  address additions, and `run_static_re_tests.py --ci` passed `489/489` after
  refreshing the class-loadout fixture's provenance hash for that intentional
  layout-file change. The recovered addresses remain relative to preferred
  image base `0x00400000`; the analyzed executable SHA-256 is
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
- Website canonical gate: `./scripts/validate.sh` exited zero on 2026-08-21.
  Its current-main receipts include backend integration `12/12`, Boneyard
  prerequisite `158/158`, Boneyard/game `1048/1048`, parties `13/13`, Hall
  `15/15`, and successful production build/bundle/media gates. The same matrix
  passed from Windows, including the shared-Hub monotonic-expiry branches.
- Browser proof: the current Windows Hall journey exercised local history,
  expansion, all four global boards, newest-first equal Awesomeness, account
  attribution, and Main Menu return with no console/page errors. The current
  authoritative Hub journey entered Mortuary along six collision-safe
  waypoints, observed both fades, settled at `(512,904)`, captured the complete
  ordinary compositor including the triple record-5 glow, returned to the
  Courtyard, and reported no console/page errors.
- Evidence roots: clean stock Hall captures are in
  `C:\\codex-validation\\sdr-hall-filled-20260820`; current web captures are in
  `C:\\Users\\User\\Documents\\GitHub\\SB Modding\\Solomon Dark\\.codex-windows-validation\\hall-fame-memoratorium-20260820-root`.
