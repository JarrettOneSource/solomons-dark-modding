# Native gameplay and art systems

## Purpose

This is the coverage ledger and integration map for the native-art
decompilation. It deliberately includes the gameplay logic that gives each
asset meaning: casting, projectiles, effects, enemies, equipment attachments,
world construction, ground loot, boneyards, UI, and lifetime/ownership.

The phase is complete only when every row below is either documented with
static and/or runtime evidence or explicitly proved unused in the retail
build. A sprite contact sheet without its native consumer does not count as a
finished mapping.

Evidence statuses:

- **Complete**: construction, relevant object state, update/render flow, asset
  range, lifetime, and custom-content boundary are documented.
- **Mapped**: principal entry points and assets are known; edge cases or one
  ownership/formula detail remains.
- **In progress**: active decompilation, not a completeness claim.
- **Queued**: inventoried but not yet traced deeply enough.

## Coverage ledger

| System | Native/config roots | Art roots | Status | Detail document |
| --- | --- | --- | --- | --- |
| Asset lookup/decode/upload/cache/device reset | `0x00413030`, `0x0043DAD0`, `0x0043DE70`, `0x00420140` | all image inputs | Complete | [native-asset-system.md](native-asset-system.md) |
| Bundle byte grammar and extraction | `0x00413B10`, `0x00413DE0` | 28 `.bundle`/PNG pairs | Complete | [sprite-bundle-format.md](../../tools/sprite-bundle-format.md) |
| Native RTTI/object registry | 598 recovered vtables and 13,010 slots | constructors, ticks, renderers, destructors | Mapped | [native-class-and-object-registry.md](native-class-and-object-registry.md) |
| Main-menu Solomon figure | `0x004F3210` and title-screen renderers | `Title[3,8,11..15]` | Complete | [main-menu-solomon-visual-re.md](../main-menu-solomon-visual-re.md) |
| Wizard profile/body/animation/equipment render | `0x005E3080`, `0x0061AA00`, `0x00621780` | Solomon, Clothes, Inventory | Mapped | [wizard-render-animation-deep-dive.md](../wizard-render-animation-deep-dive.md) |
| Skill catalog and level-up picker | `0x00674EE0`, `0x0067C250`, `0x0066F920` | Skills, LevelPicker | Mapped | [skill-picker-re.md](../skill-picker-re.md) |
| Spell welding | `0x0067CB70`, `0x006566A0`, `0x00666020` | Skills weld icons/effects | Mapped | [spell-welding.md](spell-welding.md) |
| Cast ownership/cleanup | `0x00548B00`, `0x00548A00`, `0x0052F3B0` | spell-dependent | Mapped | [spell-cast-cleanup-chain.md](../spell-cast-cleanup-chain.md) |
| Every primary/secondary spell | skill CFG catalog and native handlers | Skills plus effect atlases | In progress | [native-skills-and-spells.md](native-skills-and-spells.md) |
| Every projectile/transient effect | object constructors/ticks/renderers | BadGuys/Faculty/etc. | In progress | This document, projectile matrix pending |
| Enemy families, attacks, death effects, drops | factory/config/tick/render vtables | BadGuys, Demon, Golem, Heartmonger, Unholy, Faculty | In progress | This document; [skeleton-death-effects-re.md](../skeleton-death-effects-re.md) |
| Boneyard grammar and world materialization | `0x0046DC60`, `0x00653660`, `0x006388B0` | Bonedit plus world atlases/loose images | Complete | [boneyard-system.md](boneyard-system.md) |
| World tiles/props/doors/portals/NPCs/boss rooms | world initializer and object factories | College, Library, Office, Storage, Memoratorium, NPCs, loose images | Queued | This document |
| Item catalog/recipes/effects | `0x00574D60`, `0x00573570`, `0x005722A0` | Inventory, Clothes, Solomon attachments | In progress | [inventory-item-investigation.md](../inventory-item-investigation.md) plus item matrix pending |
| Equipment attachment and stat application | wizard/equipment render and item FX | Clothes, Inventory, Solomon | In progress | This document |
| Ground loot spawn/render/pickup/materialization | `0x0046AA90` and loot object vtables | Inventory/UI/effect atlases | In progress | This document |
| UI, fonts, controls, creation, loader/game-over | UI state/render roots | UI, Fonts, ControlPanel, Controls, Create, Loader, GameOver | Queued | This document |
| Sound/music/voice asset registry and gameplay triggers | preload/registry beginning `0x004EE010` | 304 WAV plus MO3/music table | Queued | This document |

## Confirmed cross-system architecture

```text
disk image + bundle metadata
          |
          v
page decoder -> global GPU page handle
          |
          v
generated atlas builder -> fixed runtime Sprite fields/arrays
          |
          +-------------------+
          |                   |
          v                   v
actor/object renderer     UI/world renderer
          ^                   ^
          |                   |
config + factory -> object state/update logic
```

Art is not self-describing. The `.bundle` supplies geometry and UV metadata;
the generated builder fixes each record's runtime destination; object and UI
code assigns behavior and semantic identity. Therefore every custom-art seam
must be evaluated at three layers:

1. disk lookup and decode;
2. bundle record ABI and resident texture lifetime;
3. the gameplay/UI consumer that selects a fixed runtime sprite.

## Atlas builder ranges already proved

All 28 builders have been traced record-by-record with
`tools/ghidra-scripts/trace_bundle_sprite_loads.py`. Two illustrative layouts:

The second-stage consumer join is machine-readable in
[`native-atlas-consumers.json`](native-atlas-consumers.json). It decompiles
every function that references an atlas singleton, extracts literal fields of
that singleton, and joins those fields to the builder's record destinations.
Across the 28 atlases it found 823 distinct consumer functions, 2,676 source
use lines, and 2,123 literal singleton-relative offsets. Of those offsets,
2,086 map directly to a sprite or font-wrapper destination; 584 functions have
at least one such direct mapping. The remaining 37 offsets are the four
asynchronous residency flags and higher-level BadGuys/Clothes selector tables,
not unparsed sprite destinations.

[`native-asset-object-map.json`](native-asset-object-map.json) performs the
next join against the RTTI catalog. It covers all 767 compiled sprite/array/
font destinations and attaches named classes and vtable slots to their direct
consumers. Static code directly references 506 destinations through 496
functions; 436 of those functions have a recovered class relation. Indirect
array indexing and selector-table paths remain explicit rather than receiving
guessed class names.

| Atlas | Singleton | Records | Referencing functions | Functions mapped directly to records |
| --- | ---: | ---: | ---: | ---: |
| BadGuys | `0x00819978` | 2,509 | 246 | 196 |
| Bonedit | `0x0081997C` | 84 | 40 | 37 |
| Clothes | `0x00819980` | 3,724 | 18 | 14 |
| College | `0x00819984` | 543 | 28 | 23 |
| ControlPanel | `0x00819988` | 116 | 16 | 11 |
| Controls | `0x0081998C` | 4 | 4 | 1 |
| Create | `0x00819990` | 24 | 4 | 3 |
| DeadHawg | `0x00819994` | 348 | 86 | 74 |
| Demon | `0x00819998` | 116 | 9 | 3 |
| Faculty | `0x0081999C` | 523 | 7 | 2 |
| Fonts | `0x008199A0` | 627 | 136 | 78 |
| GameOver | `0x008199A4` | 3 | 2 | 1 |
| Golem | `0x008199A8` | 209 | 4 | 1 |
| Heartmonger | `0x008199AC` | 380 | 14 | 3 |
| Inventory | `0x008199B0` | 84 | 31 | 24 |
| LevelPicker | `0x008199B4` | 8 | 4 | 3 |
| Library | `0x008199B8` | 33 | 7 | 6 |
| Loader | `0x008199BC` | 5 | 1 | 0 |
| Memoratorium | `0x008199C0` | 76 | 5 | 4 |
| NPCs | `0x008199C4` | 219 | 5 | 1 |
| Office | `0x008199C8` | 27 | 6 | 5 |
| Skills | `0x008199CC` | 166 | 16 | 14 |
| Solomon | `0x008199D0` | 273 | 7 | 5 |
| SolomonRiff | `0x008199D4` | 13 | 4 | 1 |
| Storage | `0x008199DC` | 27 | 3 | 2 |
| Title | `0x008199E0` | 25 | 7 | 4 |
| UI | `0x008199E4` | 113 | 85 | 58 |
| Unholy | `0x008199E8` | 219 | 28 | 10 |

This table counts static references, not runtime draw frequency. A consumer can
select many records through one array field, while selector tables can point at
sprites without embedding their final record offset in the consuming function.

### Skills

| Records | Runtime destination | Current semantic mapping |
| --- | --- | --- |
| `0..18` | inline sprites `+0x38` through `+0x0E00` | picker/control chrome and utility art |
| `19..26` | array `+0x0EC8`, 8 sprites | discipline/element labels |
| `27..122` | array `+0x0ED8`, 96 sprites | skill and spell glyph catalog |
| `123..124` | array `+0x0EE8`, 2 sprites | presentation pair, consumer trace pending |
| `125..126` | array `+0x0EF8`, 2 sprites | presentation pair, consumer trace pending |
| `127..155` | array `+0x0F08`, 29 sprites | colored level/perk/weld presentation |
| `156..163` | array `+0x0F18`, 8 sprites | small picker/status symbols |
| `164..165` | array `+0x0F28`, 2 sprites | presentation pair, consumer trace pending |

Weld build IDs 1000..1009 map to display selectors `0x51..0x5A` within the
skill-glyph portion through `0x00665F10`; see
[spell-welding.md](spell-welding.md).

### Inventory

The 84-record Inventory atlas is visually and structurally grouped as:

| Records | Extracted content | Consumer status |
| --- | --- | --- |
| `0` | bag/backpack icon | type/loot render trace in progress |
| `1..17` | inventory UI/utility and early item symbols | exact IDs in progress |
| `18..31` | charms/jewelry | item-definition mapping in progress |
| `32..51` | bottles/potions | potion type mapping in progress |
| `52..63` | rings | item-definition mapping in progress |
| `64..71` | robes/sacks | equipment/ground-loot mapping in progress |
| `72..83` | staffs/wands | equipment/attachment mapping in progress |

These visual labels are correlations, not yet the final item-ID table. The
final table will cite the item parser/factory and the exact sprite selector.

## Wizard rendering and equipment attachment

The persistent profile/config source begins at `0x005E3080`; a gameplay wizard
is cloned at `0x0061AA00`, and its body/equipment renderer is `0x00621780`.
The renderer composes rather than draws one monolithic wizard frame: body,
hood/hair, arm/hand, clothing, and held equipment are selected independently
from Solomon and Clothes sprite groups, transformed through actor pose state,
then layered. Equipped item definitions drive staff/robe/hat attachment
choices. The already recovered state offsets, directional selection, animation
groups, and layer ordering are maintained in
[wizard-render-animation-deep-dive.md](../wizard-render-animation-deep-dive.md).

The remaining work here is to join every item-definition selector to the exact
Clothes/Inventory/Solomon record range and to document attachment lifetime when
equipment changes.

## Skill and weld logic recovered

`0x00674EE0` constructs 80 skills at 0x70-byte stride and loads their CFGs via
the ID-to-name resolver at `0x00657C00`. The ordinary level-up path begins at
`0x0067C250`; `0x0066F920` creates/builds the picker; `0x00671470` applies the
selected skill and refreshes state. Normally three choices are shown, or four
when the special skill `0x3F` is visible.

Spell welding is the special choice `0x34`. It uses ten hard-coded
cross-element primary recipes and regenerates the live primary-spell stats
from six component rows. Its complete recovered pair/component mapping is in
[spell-welding.md](spell-welding.md).

## Cast object ownership already established

The player cast update is `0x00548B00`, sustained-spell dispatch is
`0x00548A00`, action selection/startup plus post-start damage scaling is
`0x0052DA80`, and common active-handle cleanup is `0x0052F3B0`.
Active cast group/slot state is stored at actor `+0x27C/+0x27E`; aim state is
at `+0x2A8/+0x2AC`. Handlers allocate concrete world objects/projectiles and
the common cleanup path releases cast-owned state when a cast finishes or is
cancelled. The established ownership chain and cleanup evidence is in
[spell-cast-cleanup-chain.md](../spell-cast-cleanup-chain.md).

The next pass expands this root into one row per CFG spell: gate, handler,
spawned object types, tick/render/destructor, atlas range, sound triggers, and
interaction with welded primary stats.

## Item and ground-loot roots already established

The item system uses:

| Function | Role |
| ---: | --- |
| `0x00574D60` | `ItemSet`/item-definition parser |
| `0x00573570` | `ItemRecipe` parser |
| `0x005722A0` | `ItemFx` parser |
| `0x0055FF20` | inventory insert/stack path |
| `0x0047C070` | drop selector using flags at `+0xCC..+0xD1` |
| `0x0046AA90` | common drop spawn path |

Known item object fields include type at `+0x08`, slot/side at `+0x1C`, and
active state at `+0x58`. A scene's inventory root is at `+0x13B8`; confirmed
equipment sinks include `+0x1428`, `+0x142C`, and `+0x1440`. Confirmed native
type IDs include potion `0x1B59`, staff attachment `0x1B5C`, hat `0x1B5D`, robe
`0x1B5E`, and sack `0x1B60`; potion stack/count state is at `+0x88`.

Ground objects already identified are:

| Type | Constructor | Tick/update |
| --- | ---: | ---: |
| Orb `0x7DB` | `0x005E1150` | `0x005E62E0` |
| Gold `0x7DC` | `0x005E12C0` | `0x005E66B0` |
| Sack `0x7DD` | `0x005E1460` | `0x005E6B50` |
| Bonus `0x7F6` | `0x005E2D90` | `0x006039C0` |

RTTI identifies the `0x7DD` class as `Sack`; the earlier provisional
`ItemDrop` label was too broad. The final loot pass must still prove exact probability/materialization paths,
render selector and atlas range for every ground type, host/owner-independent
native lifetime, pickup collision, inventory insertion, and destructor.

## Loose world images

The initializer at `0x005BBD90` loads roads 1..5, fence grate, ether plane,
green plasma, river/rise, and WallTop into a large world-render object. The
exact destinations are recorded in
[native-asset-system.md](native-asset-system.md#loose-image-consumers-recovered-so-far).
`paintbkg` belongs to portrait capture at `0x005BED10`, not ordinary world
rendering.

## Custom-content seam criteria

For each remaining family, the final documentation will answer:

1. Is content enumerated from disk/config, or is its count/identity compiled?
2. Is art selected by filename, numeric record index, runtime pointer, or
   object type?
3. Which object owns decoded pixels, GPU pages, sprite descriptors, actor state,
   and transient effects?
4. What must be rebuilt or invalidated when content changes?
5. Can stock data add a new member, only replace one, or neither?
6. Which state must be identical before multiplayer join for deterministic
   object construction and presentation?

Answers will be consolidated only after the native phase is complete. No
website download or mod-enablement implementation belongs in this phase.
