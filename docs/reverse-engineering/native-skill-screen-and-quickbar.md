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
  `e5bc0420354e3155579234ffe227b59daaf5f3aa2821c5620adb041286186904`
- Stock capture after dragging Call Leviathan into another slot:
  `15392a41dabb67eae6b02fc14d5dbb2b9c071be492caf3b92edd1570c8f7aabc`
- Stock capture after dragging Magic Missile into another slot:
  `8ea604ef93ee4d11b312faae2b5c719f6f3e6a116d560dd513f5ba4282f61597`

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
| Full-screen chrome painter | `0x0065BEF0` |
| `SkillPage` constructor | `0x006577F0` |
| Page interactive-card builder | `0x00673EE0` |
| Page/card/tooltip painter | `0x006720F0` |
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

Every `SkillPage` is a vertical card with the skill icon, upper-case name,
family, quick description, and one of `PRIMARY CAST`, `SECONDARY CAST`, or the
other native category labels. Hover/hold opens the authored full description,
current rank, and evaluated rank values in a black tooltip.

The card painter at `0x006720F0` uses the native Skills atlas:

- record `5` is the ordinary card/icon frame;
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
| `3` | `0x0067BEE0` | concentration | selected through the separate concentration control |

Category `1` contains the five elemental primary rows and Spell Welding row
`52`. Category `2` contains all 23 secondary abilities. Those two categories
are the complete skill membership accepted by automatic belt population and by
the gold/green Skill Screen drag affordance.

`HoverButton` click callback `0x00674110` adds one category-specific branch.
When the card is draggable and no drag began, category `1` is passed to
`0x005D5600` and immediately becomes the selected primary. Category `2` is
excluded from that click branch because clicking a secondary card does not cast
it; it must be dragged to the quickbar and invoked there. Category `3` remains
non-draggable and is selected through the separate `Select Concentration`
`Skills_Quickbar` modal.

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

`SettingsControl_HandleAction (0x005D8120)` routes a clicked/pressed
`0x1B67` belt entry to `0x005D5600`. That function asks the same authoritative
wizard skill object for the row category:

- category `1`: write the selected primary id and rebuild dependent skill/UI
  state;
- category `3`: update the separately selected concentration action;
- category `2`: validate current actor eligibility and invoke the exact skill.

The category-`3` branch is shared with the separate `Skills_Quickbar` modal
used by the settings control; category-`3` cards are not gold/green Skill
Screen drag members. The gameplay quickbar model should consequently expose
category `1` and `2`, while concentration remains its own selected skill.

## Port consequences

The Website model named `secondaryBelt` is incomplete if it rejects primary
ids or duplicates. Native parity requires a `skillQuickbar`, native category
validation, category-routed activation, authoritative bind mutations, and a
Skill Screen that reads the full learned catalog. Spell Welding is a category-
`1` primary selection: learned weld identity and currently selected primary
must not be represented by the same nullable field.
