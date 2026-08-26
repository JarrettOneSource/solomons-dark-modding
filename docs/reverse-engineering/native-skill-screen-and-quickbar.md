# Native Skill Screen and Quickbar

This document records the retail Solomon Dark Skill Screen, its authoritative
skill-card membership, and the eight-slot quickbar contract. It corrects the
earlier shorthand "secondary belt": the native belt is a heterogeneous action
bar, and skill entries may be either primary attacks or secondary casts.

## Evidence identity

- Binary: `SolomonDark.exe`
- SHA-256: `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`
- Stock logical render size: `1600x900`
- Clean Ether/Arcane level-one capture, Skill Screen open:
  `5b2423d5daf56e6bb5d154dd2ce0abc80d947286f087c8f81134b01686bb1c87`
- Stock capture after dragging Call Leviathan into another slot:
  `e934a18512ef5ed92753be150f5a37e5182751c8ed25644f5030a5d63b87f05d`

The captures came from a clean retail process with a newly created
Ether/Arcane wizard. The process was stopped after the observations; no
pre-existing Solomon Dark process was touched.

## Screen ownership and lifecycle

`0x005CA640` owns the Skill Screen singleton at the application field
`+0x1664`. It closes an existing instance before allocating the `SkillScreen`
object (`0x006576C0`, vtable `0x0079F72C`) and registering it with the ordinary
UI-object owner.

| Role | Native owner |
|---|---|
| Open/create | `0x005CA640` |
| `SkillScreen` constructor | `0x006576C0` |
| Page construction and layout | `0x0066B380` |
| Opening/closing tick | `0x006567E0` |
| Begin close | `0x006568E0` |
| Screen-local animation tick | `SkillScreen` vtable `+0x20 -> 0x00427800` |
| Root/background/chrome painter | `0x0065B550` (`SkillScreen` vtable `+0x0C`) |
| Page-region overlay/help painter | `0x0065BEF0` (`SkillScreen` vtable `+0x28`) |
| `SkillPage` constructor | `0x006577F0` |
| Page interactive-card builder | `0x00673EE0` |
| Page/card painter | `0x006720F0` |
| Hover construction | `0x00656CE0 -> Skills_Wizard +0xA4` |
| Hover content builder | `0x0066B990` |
| Shared `HoverBox` constructor/render/layout | `0x005C38F0` / `0x005C3A60` / `0x005AB060` |
| `HoverButton` drag threshold | `0x00656980` |
| `HoverButton` click/release | `0x00674110` |
| `SkillDragger` release | `0x006564A0` |

The screen fades with scalar `SkillScreen +0x94`: `0x006567E0` approaches one
while open and zero after close flag `+0x98` is set. At zero, the screen removes
itself through the common object lifecycle. The painter applies the cubic fade
to the screen and hides the live scene interaction beneath it while fully open.

`0x0066B380` walks the authoritative learned/visible skill list at the wizard
skill system `+0x850/+0x854`. It creates one `SkillPage` for each top-level
visible member and folds descendants into the same page through recursive
relationship predicate `0x0065E670`. Pages are laid out and wrapped from their
measured widths; the screen is not a hard-coded list of just the two starting
skills.

## 2026-08-25 corrective full-renderer closure

The 2026-08-20 Website pass stopped at `SkillScreen` vtable `+0x28`
(`0x0065BEF0`) and treated that overlay as the complete renderer. That was a
one-hop ownership failure. The actual vtable root at `+0x0C` is `0x0065B550`,
and hover is a separately owned shared `HoverBox` family reached through
`HoverButton +0x98 -> 0x00656CE0`. The old report also called Skills record `5`
the page/card background even though its authored logical size is only
`87 x 88`; instructions prove that record `0` is the page-wide nine-slice and
record `5` is only the ordinary icon frame. The earlier `exact-ported` visual
claim is withdrawn.

Fresh read-only Ghidra replica queries on the same retail image recover these
complete settled root passes at `1600 x 900`:

- `0x0065B550` first draws an opaque black full-screen curtain. Its eight
  additive UI record `3` seal arcs share logical centre `y=490`, scale `1.9`,
  and rotations separated by `45` degrees. For member angle
  `theta = 0,45,...,315`, the draw centre is
  `x = 800 + 40*sin(2*theta*pi/180)`, `y = 490`; rotation is
  `theta - screenTick/60` degrees. `screenTick` is the screen-local `+0x28`
  field initialized to zero by `0x00427370` and advanced at 100 Hz by inherited
  vtable slot `+0x20 -> 0x00427800`. Settled alpha is `0.15`; the opening
  envelope applies the native higher-order fade.
- UI record `33` is centred at `(80,30)` rotated `-90` degrees and at
  `(1520,30)` rotated `+90` degrees. UI record `31` is centred at `(200,20)`
  mirrored in X and `(1400,20)` ordinary. These authored quads are mostly
  above the viewport; placing whole wizard statues inside the leather field is
  not stock.
- UI record `30` is centred at `(0,860)` and `(1600,860)`. A bottom-only clip
  `(0,820,1600,80)` contains UI record `32` at `(60,880)` and its mirrored
  sibling at `(1540,880)`.
- The page region remains `(0,50,1600,760)`. UI record `49` supplies its
  leather field over the black root; semitransparent texels therefore reveal
  black, not the earlier off-screen fixture pass. Overlay `0x0065BEF0` adds UI
  record `10` horizontal chain rails, UI record `71` rail endcaps, the
  UI-record-`4` title backing, and the exact title/help text. `SKILLS` and all
  four help lines use Fonts group `3`
  (`+0x0E7D98`, menu/dialog), not the medium/body faces. Title RGB is
  `(0.5,0.5,0.5)`; help RGB is the same at settled alpha `0.75`.
- `0x005C8740` renders the live XP, backpack, tome, and all eight `BeltButton`
  children after the SkillScreen chrome. It does not invent a separate bright
  numbered web belt.

The complete settled SkillPage pass at `0x006720F0` is:

1. One page-wide Skills-record-`0` nine-slice at `(0,0,pageWidth,300)` plus an
   inset primitive `(12,12,pageWidth-24,276)`. RGB comes from the page root.
   An unselected page uses alpha `0.1`; a page containing the first selected
   primary/concentration row uses `0.5`. Record `0` then receives one
   white-alpha-`0.5` additive edge pass, plus one additional pass for a
   selected page.
2. Every row centres at local `y=80`: root x `100`, first dependent x `280`,
   then `+160` per dependent. Skills record `13` and root-tinted record `164`
   are both drawn there at scale `1.15`; Spell Welding delegates its split
   presentation to `0x00671810`. Record `6` connects each dependent to the
   previous member.
3. Record `5` is the ordinary `87 x 88` icon frame. Record `14` is the
   actionable frame. The selected actionable row uses record `5` tinted
   `0x97c797`: source RGB `(0.25,1,0.25)` blended `0.75` toward luminance by
   `FUN_0040FC60`, with alpha `1`. The authored icon receives one opaque-black
   copy at `(+4,+4)` followed by the white copy at the row centre.
4. Source `casting` / `concentrate` uses Fonts group `0` (whose lowercase
   glyphs produce the stock small-cap presentation); the name uses group `1`,
   family uses group `5`, quick description uses group `1`, and the category
   footer uses group `0`. `FUN_0043D030` wraps the original-case name and quick
   description at `140` pixels before render; rank greater than one is appended
   to the page name. The quick description is the sole white pass, without the
   `(+1,+1)` black text shadow used by the other lanes. Its line-restart
   behavior is visible in stock Call Leviathan as
   `call leviathan / from the / ether`.
   A per-row stretched frame, rounded primitive, fixed
   purple fill, and universal white card copy are all non-native.

Hover is not part of the page painter. `HoverButton +0x98` calls
`0x0066B990(skillId,0,0)`, marks the returned shared `HoverBox` opaque, and
lays it out vertically with a `50`-pixel source gap and `25`-pixel viewport /
content margin. The box is centred above the source unless that would cross the
top margin, in which case it flips below; horizontal bounds clamp to 25 pixels.
It uses the shared opaque black fill, native edge pass, and case-preserving
Fonts-group-`0` `ExactText` lines. Content is fully extractable from all public
row CFGs:

- optional `GRANTED BY ITEM` or `BOOSTED` when effective rank exceeds the
  permanent rank;
- the native name plus ` _s(.7)_o(0,1)%d/%d` rank suffix;
- category, full `mDescription`, a blank line, and
  `   Current Level: %d`;
- every `mStats` row in authored order, prefixed `   `;
- every category-3 `mBonus` row in authored order, also prefixed `   `.

The formatter at `0x0065D7F0` uses `D -> %.0f`, `F -> %.1f`, `X -> %.2f`,
and `N -> %.0f` for integral values otherwise `%.1f`; `%%` is a literal
percent. ExactText commands such as `_s(.7)_o(0,1)_i` remain presentation
commands and are not visible source text. This drains every public row
`8..79`, including all fourteen concentration bonus sets, instead of choosing
six generic properties in web-defined order.

### 2026-08-25 ambient-seal motion correction

The earlier full-renderer closure misread `_CIsin 0x007470D0` as a random
generator and called the deterministic `40*sin(2*theta)` placement lane
"per-frame horizontal jitter." That was a raw-instruction verification
failure. The x87 sequence at `0x0065B6E1..0x0065B721` doubles the loop angle,
converts degrees to radians with runtime pi, calls `_CIsin`, and multiplies by
`40`; no RNG call, seed, cursor, or time value participates. The prior Website
hash of `(wallFrame,index)` therefore invented 60 Hz 30-40-pixel jumps that
stock cannot produce.

The same pass also makes the clock ownership explicit. `0x0065B68F` reads
`SkillScreen+0x28`, negates it, and divides by `60`; the class vtable at
`0x0079F72C` places shared base tick `0x00427800` at `+0x20`. That method
increments the screen-local field at 100 Hz. The phase begins at zero for each
new screen rather than inheriting an absolute application/page time. The exact
rotation rate is therefore `100/60` degrees per second and resets on every
SkillScreen construction.

UI record `3` is a trimmed `1024 x 768` logical sprite (frame `211 x 94`, trim
origin `(405,108)`). `Text_Draw 0x00415130` consumes logical-centre placement,
rotation, and uniform scale; the web native-UI Pixi adapter's `orig`/`trim` plus
`anchor=.5` is the correct equivalent. The defect is solely the invented
position generator and absolute/slow phase, not the asset registration, eight
member count, additive blend, alpha envelope, scale, or painter order.

## Stock visual contract

At `1600x900`, `0x0065BEF0` paints the dark leather field, top and bottom
chains, corner stone/chain fixtures, centered `SKILLS` title, mirrored close
buttons, instructional copy, and the live belt at the bottom. The stock copy is:

```text
HOVER OVER A SKILL ICON FOR MORE
INFORMATION ABOUT A SKILL.

SKILLS WITH A GOLD OR GREEN BORDER
CAN BE DRAGGED INTO YOUR BELT
```

Touch input substitutes `TOUCH AND HOLD` for `HOVER OVER`.

Every `SkillPage` is one root-tinted page panel containing the root and every
learned transitive dependent. Each row has the skill icon, upper-case name,
family, quick description, and one of `PRIMARY CAST`, `SECONDARY CAST`, or the
other native category labels. Hover/hold constructs the shared authored
`HoverBox` with the full description, current rank, evaluated `mStats`, and
category-3 `mBonus` membership.

The page painter at `0x006720F0` uses the native Skills atlas:

- record `0` is the page-wide nine-slice;
- record `13` is the row aura and record `164` is the root-tinted glow;
- record `5` is the ordinary icon frame;
- record `14` is the gold draggable frame;
- the selected primary is tinted green and receives the `CASTING` label;
- record `6` is the rank/upgrade overlay;
- records `27..122` are the skill icons;
- records `164..165` are page presentation records.

`SkillPage +0x7C/+0x80` is the exact ordered skill-id array. The interactive
builder `0x00673EE0` creates a `HoverButton` for every member, copies its skill
id to `HoverButton +0xB4`, the parent screen to `+0xBC`, and the authored
draggable bit to `+0xC0`.

## Category contract

The wizard `Skills` vtable classifies the authored byte at skill-row `+0x26`:

| Category | Predicate | Meaning | Skill Screen border/action |
|---:|---|---|---|
| `0` or `4` | `0x0067BF40` | passive/modifier | no draggable border |
| `1` | `0x0067BEB0` | primary attack | green when selected; quickbar selects it |
| `2` | `0x0067BF10` | secondary cast | gold; quickbar invokes it |
| `3` | `0x0067BEE0` | concentration | non-draggable card click selects through the shared category router |

Category `1` contains the five elemental primary rows and Spell Welding row
`52`. Category `2` contains all 23 secondary abilities. Those two categories
are the complete skill membership accepted by automatic belt population and by
the gold/green Skill Screen drag affordance.

`HoverButton` click callback `0x00674110` reads the authored action byte at row
`+0x32`; when it is nonzero and no drag began, every category except `2` is
passed to `0x005D5600`. Category `1` immediately becomes the selected primary.
Category `3` remains non-draggable but its card selects the first concentration
or consumes the shared Split Mind fill/alternating-replacement rule. This is the
path that seeds concentration A before an A emblem exists. Category `2` is
excluded from the click branch because clicking a secondary card does not cast
it; it must be dragged to the quickbar and invoked there.

## Drag/drop and quickbar representation

Once pointer movement exceeds the common drag threshold, `0x00656980` creates
a `SkillDragger` carrying the exact skill id. Its release callback
`0x006564A0` passes that id and the release position to `0x005C7090`.

`0x005C7090` tests all eight live `BeltButton` rectangles, beginning at
application `+0x5EC` with stride `0xEC`, and chooses the containing rectangle
with the greatest overlap area. A skill drop writes:

- entry type `0x1B67` at button `+0xB4`;
- the exact skill id at button `+0xB8`;
- zero at button `+0xBC`;
- refresh flags `0x21` through the button lifecycle.

It overwrites only the destination slot. It performs no scan for an existing
copy of the skill and removes no prior binding. The clean stock captures prove
both sides of this contract: Call Leviathan can occupy multiple slots, and
Magic Missile can coexist with it in the quickbar.

The quickbar therefore has these authoritative rules:

1. It has exactly eight slots.
2. Each skill slot contains `null` or a learned category-`1`/category-`2` skill
   id.
3. Duplicate skill ids are valid and remain independent bindings.
4. Dropping onto an occupied slot replaces only that slot.
5. A primary binding selects the primary; it does not cast a secondary.
6. A secondary binding invokes that ability and shares the skill's ordinary
   mana/cooldown/toggle state with any duplicate bindings.

The selected primary is not restricted to the wizard's creation element.
`0x005D5600` accepts every learned category-`1` row, while the creation element
continues to own the wizard's robe/hat appearance. Spell dispatch, mana cadence,
Staff cast pose, audio, HUD icon, and projectile family follow the selected
primary row.

### 2026-08-26 corrective SkillDragger closure

A user report that dragging a spell did nothing reopened the drag member that
the 2026-08-25 presentation pass had called exact. That claim was premature:
the old browser journey used Playwright `dragTo` against the transparent DOM
quickbar action, so it never proved that a pointer released over the painted
live belt followed the native hit owner. A fresh read-only replica pass against
the same retail image closes the complete transient drag contract:

- `HoverButton` movement handler `0x00656980` compares pointer displacement
  squared with float `0x0078473C = 9`. Drag begins only on the strict `>9`
  branch, i.e. after more than three screen pixels; the prior Website used
  `>16`.
- That branch destroys the live HoverBox, constructs one `0x80`-byte
  `SkillDragger`, stores the exact skill id at `+0x78` and the parent
  SkillScreen at `+0x7C`, attaches it at screen `+0xA0`, and transfers pointer
  capture to the transient owner. Cancellation/ordinary release destroys it.
- `SkillDragger::Render 0x0065E4D0` reads the live pointer
  `0x0082025C/+0x04` every paint. At that exact center it draws Skills record
  `164` in the skill's native root color, then the authored icon selected from
  Skills `27..122`, both at scale `0x00784D58 = 1.25`. Spell Welding row 52
  uses its live build icon through the same wizard-skill owner. There is no
  stationary source-card substitute.
- Release `0x006564A0` centers a `40 x 40` rectangle
  (`0x007849B0 = 40`) on the pointer and passes it to `0x005C7090`. The latter
  intersects that rectangle with all eight live `BeltButton` rectangles
  (`Game+0x5EC`, stride `0xEC`) in slot order and selects the strictly greatest
  positive overlap area. A pointer point need not itself be inside the winning
  slot; equal overlap retains the earlier slot.
- An accepted drop overwrites only the winning slot, refreshes it, and plays
  registry entry 1 `sounds\\pickskill` at gain one (`Game` audio registry
  `+0x18 -> Sound::Play 0x00407B70`). A rejected drop mutates nothing and is
  silent. Both paths destroy the `SkillDragger` immediately.
- The rectangles are the same live HUD rectangles moved by modal writer
  `0x005C7200`; hit testing cannot remain at the unslid belt positions while
  the painted SkillScreen belt is at progress one.

The complete draggable membership remains every learned category-1 primary
and category-2 secondary, including Welding row 52. Categories 0/4 remain
passive and category 3 remains the separate click/concentration path. Hub and
Boneyard use the same SkillScreen owner; mouse and a browser Pointer Events
projection must feed the same threshold, pointer-centered overlap, accepted /
rejected sound, and teardown contract.

### 2026-08-26 corrective BeltButton pull-off closure

The skill-card `SkillDragger` above is only the assignment half of the belt
editing system. A second user report that a populated browser slot could not be
dragged out reopened the eight live `BeltButton` objects themselves. The prior
pass stopped at `SkillDragger` release and did not inspect the destination
button's movement override. A fresh read-only pass against the same retail
image closes that omitted sibling:

- `BeltButton::vftable +0x68 -> 0x005C7DF0` first calls the common pressed-
  control movement handler `0x004308D0`. It continues only while the button's
  pressed byte `+0x78` is set and entry type `+0xB4` is not empty type `7000`
  (`0x1B58`). Thus the member applies uniformly to skills, both fixed Potion
  entries, and an ordinary item binding.
- The handler subtracts the captured press root
  `Input +0xC34/+0xC38` from the live pointer root `Input +0xC2C/+0xC30`,
  computes Euclidean length, and uses the strict threshold `length > 50.0`
  (`double 0x007847C8`). Motion of exactly 50 does not clear the slot. The
  visual displacement field at button `+0xC0` is `length / 5` while held.
- Common `Button` construction `0x00430430` initializes release-callback byte
  `+0x7B = 1` and press-callback byte `+0x7C = 0`. `0x00430890` therefore
  captures the press without invoking the BeltButton action; ordinary release
  `0x00430A40` invokes it. A successful pull-off clears the entry before that
  release path, so removing a skill cannot cast it as a side effect.
- The accepted movement edge is immediate; it does not wait for pointer
  release and does not create a movable belt-to-belt dragger. It plays registry
  row 73, `sounds\\poof`, at gain one, then `0x005C79C0` writes the complete
  empty state: `+0xC0=0`, `+0xB4=7000`, `+0xB8=0`, `+0xBC=0`, `+0xC4=0`,
  `+0xE4=0`, and an empty label. The button refreshes and remains the same live
  slot object.
- The local burst contains exactly 24 UI-record-65 bouncers: two at each
  30-degree lane through the full 360 degrees. It then chooses a 90- or
  120-degree step and emits respectively four or three moving/fading
  UI-record-69 members. This is presentation-local; it does not create a
  `SkillDragger`, mutate another slot, or play `pickskill`.
- A release/cancel before the strict 50-unit edge leaves the binding intact and
  follows the ordinary button release path. After the edge the same press is
  already empty, so release cannot invoke the removed skill or item again.

The complete edit contract is consequently asymmetric by design: dragging a
learned category-1/2 card onto the belt assigns/replaces through the centered
40-by-40 overlap router; dragging any populated belt button more than 50 units
pulls that one entry off with `poof` and the two-record burst. There is no stock
belt-to-belt move operation.

## Automatic population

`0x005C85E0` is the first-empty-slot helper. It scans the eight `BeltButton`
entries for type `7000` (empty), writes type `0x1B67` plus the supplied skill
id, refreshes that slot, and returns. It never removes duplicates.

Normal rank acquisition in `0x00660320` and `0x00660580` calls this helper only
when the permanent rank was zero and the newly learned row is category `1` or
`2`. Rank increases do not create another automatic entry. New elemental game
setup explicitly inserts only the starting secondary after creating the
starting primary, which is why a fresh wizard has its secondary in slot zero
but no primary binding.

## Activation routing

`Game_HandleControlAction (0x005D8120)` routes a clicked/pressed
`0x1B67` belt entry to `0x005D5600`. That function asks the same authoritative
wizard skill object for the row category:

- category `1`: write the selected primary id and rebuild dependent skill/UI
  state;
- category `3`: update the separately selected concentration action;
- category `2`: validate current actor eligibility and invoke the exact skill.

The category-`3` branch is shared by SkillScreen card clicks and the compact HUD
`Skills_Quickbar` modal; category-`3` cards are not gold/green Skill Screen drag
members. The gameplay quickbar model should consequently expose category `1`
and `2`, while concentration remains its own selected skill.

The HUD concentration branches at `0x005D8120` build a horizontal
`Skills_Quickbar` through `0x0066F0B0` with category filter `3` and title
`Select Concentration`. `0x005D5600` returns without mutation when the selected
row already occupies concentration action `0x10` or `0x14`. Without Split Mind,
the new row replaces action `0x10`; with Split Mind, it fills the empty action
first and otherwise alternates replacement between `0x10` and `0x14`. The HUD
buttons pre-clear one addressed slot before this shared category router, so a
button-originated choice replaces that exact A/B slot rather than consuming the
alternating fallback. This selector is a separate HUD modal which coexists with
the SkillScreen category-3 click path; neither path makes category 3 draggable.

## Selected-skill HUD controls and selector modal

The earlier `SettingsControl_HandleAction` name was a bad ownership inference.
`0x005D8120` is `Game::vftable +0x10`, while `MyCPanel::vftable +0x10` is the
unrelated `0x00434C60`. The three skill actions are live HUD children registered
by `0x005CBA00`, not Settings rows:

| Game field | Binding | Purpose |
|---:|---:|---|
| `+0x3AC` | `12` | selected primary; opens `Select Primary Attack` |
| `+0x46C` | `16` | concentration A; opens a category-3 selector targeting A |
| `+0x52C` | `20` | concentration B; opens a category-3 selector targeting B |

`0x005D76C0` gives every button a `40 x 65` logical rectangle. The normal HUD
top is `y=-7`, so the clickable vertical interval is `[-7,58)`. Refresh
`0x005D50E0` centers the buttons on the same cluster positions drawn by
`0x005D367A..0x005D399F`:

- primary only: primary center `800`; A/B are parked off-screen;
- primary plus one concentration: primary `780`, occupied concentration `820`;
- Split Mind A+B: primary `760`, B `800`, A `840`.

The exact hit rectangles are therefore the corresponding centers plus
`[-20,+20)` horizontally and `[-32.5,+32.5)` vertically around center
`y=25.5`. `0x005C7200` moves all three controls with the same HUD-hide vertical
offset, so their hit geometry cannot remain behind when the HUD slides away.
Reverse-z UI traversal gives a winning HUD button the click; it never falls
through into world primary casting.

The primary action returns without opening while binding 12 is the temporary
Plane Orb row `80`. Otherwise it plays registry sound 0 `sounds\\click`, builds
the selector with category `1`, and includes every learned category-1 row in
ascending native row-id order. This drains pure primaries `8,16,24,32,40` and
learned Spell Welding `52`; Welding uses its active build icon.

Builder `0x0066F0B0` also skips a row when the corresponding byte in Game's
512-byte `+0x1668` exclusion array is nonzero. The Game constructor zeroes the
array; `0x005C7AB0` imports/exports it with raw native game state, while skill
acquisition/offer/selector paths read it. The complete xref sweep found no
ordinary fresh-session gameplay writer. It is therefore a persisted native-
state exclusion input, not a selector-local filter or a reason to reorder the
remaining rows.

The A and B actions both use category `3`, covering exactly
`57..63,65..71`. Each passes the other slot's current skill as the selector's
one exclusion, preventing a duplicate across A/B. On acceptance, A clears
action `0x10` and B clears action `0x14` before routing the selected row through
`0x005D5600`. B exists only under Split Mind. Mind Chug prevents the mutation.

`Skills_Quickbar` constructor `0x00657A70`, builder `0x0066F0B0`, renderer
`0x0066F330`, pointer handler `0x00659AD0`, destructor `0x00658DC0`, and the
generic modal loop `0x004281F0` own the complete selector lifecycle. Its stable
`1600 x 900` geometry is:

- one horizontal `52 x 52` cell per eligible skill, ordered by native row id;
- cells centered as a group at `y=100`, so their top is `74`;
- a black `0.95`-alpha rectangle at `y=52`, height `79`, width
  `max(optionCount * 52, titleWidth) + 10`, centered on `x=800`;
- the title centered at baseline `y=69` in the medium bitmap font
  (`Fonts.93..184`), color `(0.85,0.73,0.44,0.75)`;
- full-white, full-alpha authored Skills icons centered at
  `x=left+26+52*i,y=100`.

Pointer hit testing is strict inside the option strip. An outside click returns
`-1` and closes without mutation. Opening either family and accepting a primary
both play registry 0 `sounds\\click`. Accepted concentration plays the same
click followed by registry 17 `sounds\\concentrate`. The modal owns local input
suspension from before its first frame until teardown and has no open/close
animation.

## Port consequences

The Website model named `secondaryBelt` is incomplete if it rejects primary
ids or duplicates. Native parity requires a `skillQuickbar`, native category
validation, category-routed activation, authoritative bind mutations, and a
Skill Screen that reads the full learned catalog. Spell Welding is a category-
`1` primary selection: learned weld identity and currently selected primary
must not be represented by the same nullable field. The selected-skill HUD must
retain three actor-addressed buttons, the compact selector modal, exact A/B
replacement, click/concentrate audio, and modal input ownership; opening the
full Skill Screen in place of this selector is not the stock interaction.

Presentation must also preserve the root/overlay split above: exact root
records and partial off-screen transforms, one root-tinted page panel per
dependency family, all CFG-authored HoverBox lines, and the live eight-button
HUD painter. Stretching record `5` into a per-row card or replacing HoverBox
with a fixed web tooltip is not a legal approximation.
