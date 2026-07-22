# Native gameplay and art systems

## Purpose

This is the coverage ledger and integration map for the native-art
decompilation. It deliberately includes the gameplay logic that gives each
asset meaning: casting, projectiles, effects, enemies, equipment attachments,
world construction, ground loot, boneyards, UI, and lifetime/ownership.

The native phase is complete: every row below is documented with static and/or
runtime evidence, and every former residual record is either joined to its
consumer or proved dormant in the retail executable. A sprite contact sheet
without its native consumer was not counted as a finished mapping.

Evidence statuses:

- **Complete**: construction, relevant object state, update/render flow, asset
  range, lifetime, and custom-content boundary are documented. All ledger rows
  have reached this state.

## Coverage ledger

| System | Native/config roots | Art roots | Status | Detail document |
| --- | --- | --- | --- | --- |
| Asset lookup/decode/upload/cache/device reset | `0x00413030`, `0x0043DAD0`, `0x0043DE70`, `0x00420140` | all image inputs | Complete | [native-asset-system.md](native-asset-system.md) |
| Bundle byte grammar and extraction | `0x00413B10`, `0x00413DE0` | 28 `.bundle`/PNG pairs | Complete | [sprite-bundle-format.md](../../tools/sprite-bundle-format.md) |
| Native RTTI/object registry | 598 recovered vtables and 13,010 slots | constructors, ticks, renderers, destructors | Complete | [native-class-and-object-registry.md](native-class-and-object-registry.md) |
| Main-menu Solomon figure | `0x004F3210` and title-screen renderers | `Title[3,8,11..15]` | Complete | [main-menu-solomon-visual-re.md](../main-menu-solomon-visual-re.md) |
| Wizard profile/body/animation/equipment render | `0x005E3080`, `0x0061AA00`, `0x00621780` | Solomon, Clothes, Inventory | Complete | [wizard-render-animation-deep-dive.md](../wizard-render-animation-deep-dive.md) |
| Skill catalog and level-up picker | `0x00674EE0`, `0x0067C250`, `0x0066F920` | Skills, LevelPicker | Complete | [skill-picker-re.md](../skill-picker-re.md) |
| Spell welding | `0x0067CB70`, `0x006566A0`, `0x00666020` | Skills weld icons/effects | Complete | [spell-welding.md](spell-welding.md) |
| Cast ownership/cleanup | `0x00548B00`, `0x00548A00`, `0x0052F3B0` | spell-dependent | Complete | [spell-cast-cleanup-chain.md](../spell-cast-cleanup-chain.md) |
| Every primary/secondary spell | skill CFG catalog and native handlers | Skills plus effect atlases | Complete | [native-skills-and-spells.md](native-skills-and-spells.md) |
| Every projectile/transient effect | 46 factory classes and 197 decompiled lifecycle methods | BadGuys, DeadHawg, Golem, Unholy, UI plus child animation art | Complete | [native-projectiles-and-effects.md](native-projectiles-and-effects.md) |
| Enemy families, attacks, death effects, drops | factory/config/tick/render vtables | BadGuys, Demon, Golem, Heartmonger, Unholy, Faculty | Complete | [native-enemies.md](native-enemies.md); [skeleton-death-effects-re.md](../skeleton-death-effects-re.md) |
| Boneyard grammar, base-field rendering, procedural generation, and outdoor scenery materialization | `0x0046EC80`, `0x004D5F40`, `0x0046DC60`, `0x006388B0`, `0x00653660`, `0x006531B0` | Direct3D clear, DeadHawg 20/21, road/fence loose images, and generated meshes | Complete | [native-boneyards-and-world.md](native-boneyards-and-world.md) |
| World tiles/props/doors/portals/NPCs/boss rooms | world initializer and object factories | College, Library, Office, Storage, Memoratorium, NPCs, loose images | Complete | [native-regions-npcs-and-world-props.md](native-regions-npcs-and-world-props.md) |
| Item catalog/recipes/effects | `0x00574D60`, `0x00573570`, `0x005722A0` | Inventory, Clothes, Solomon attachments | Complete | [native-items-equipment-and-loot.md](native-items-equipment-and-loot.md); [native-item-catalog.json](native-item-catalog.json) |
| Equipment attachment and stat application | wizard/equipment render and item FX | Clothes, Inventory, Solomon | Complete | [native-items-equipment-and-loot.md](native-items-equipment-and-loot.md) |
| Ground loot spawn/render/pickup/materialization | `0x0046AA90`, `0x0047C070`, and four reward-actor vtables | BadGuys, Inventory, transient effects | Complete | [native-items-equipment-and-loot.md](native-items-equipment-and-loot.md#ground-reward-actors) |
| UI, fonts, controls, creation, loader/game-over | UI state/render roots | UI, Fonts, ControlPanel, Controls, Create, Loader, GameOver | Complete | [native-presentation-ui-fonts-and-loader.md](native-presentation-ui-fonts-and-loader.md) |
| Sound/music/voice asset registry and gameplay triggers | preload/registry beginning `0x004EE010` | 304 WAV plus MO3/music table | Complete | [native-audio-system.md](native-audio-system.md); [native-audio-catalog.json](native-audio-catalog.json) |
| Isolated runtime verification | Create -> Courtyard -> Arena -> wave/loot -> GameOver | live atlas refs, actors, recipes, reward objects | Complete | [native-live-validation.md](native-live-validation.md) |

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
| `123..124` | array `+0x0EE8`, 2 sprites | dark tab/square pair; built and released but statically dormant |
| `125..126` | array `+0x0EF8`, 2 sprites | gray square pair; built and released but statically dormant |
| `127..155` | array `+0x0F08`, 29 sprites | colored level/perk/weld presentation |
| `156..163` | array `+0x0F18`, 8 sprites | small picker/status symbols; built and released but statically dormant |
| `164..165` | array `+0x0F28`, 2 sprites | record 164 is a shared skill/picker/Hall-of-Fame tile; record 165 is never selected |

The residual Skills arrays have now been closed at the machine-code level.
`FUN_005AF160` is the only function that touches the `+0x0EE8`, `+0x0EF8`,
and `+0x0F18` vector owners after construction, and its accesses are the
bundle teardown sequence. The `+0x0F28` vector is consumed by
`0x004FECB0`, `HallOfFame_Render`, `0x0065E4D0`, `0x00671810`,
`0x006720F0`, and `0x0067DF80`; each live selection loads the first pointer
without a one-record stride, proving record 164 is used and record 165 is not.
The contact-sheet descriptions above identify pixels only; the dormant groups
must not be treated as hidden gameplay states.

Weld build IDs 1000..1009 map to display selectors `0x51..0x5A` within the
skill-glyph portion through `0x00665F10`; see
[spell-welding.md](spell-welding.md).

### Inventory

The 84-record Inventory atlas has these exact native item bindings:

| Records | Native consumer |
| --- | --- |
| `0` | bag/backpack presentation |
| `1..9`, `11..17`, `32..33` | inventory UI/utility records; not recipe-addressable |
| `10` | `Item_Perk` Bargain Bundle icon |
| `18..29` | amulet main layer, `18 + image` |
| `30..31` | amulet secondary layer, `30 + floor(image/6)` |
| `34..37`, `38..41` | hat color layers, `34 + image` and `38 + image` |
| `42..45` | miscellaneous dye/key/two-book subtypes |
| `46..51` | six potion subtypes |
| `52..63` | rings, `52 + image` |
| `64..66`, `67..69` | robe color layers, `64 + image` and `67 + image` |
| `70..71` | nested inventory sacks |
| `72..77` | staffs, `72 + image` |
| `78..83` | wands, `78 + image` |

The exact parser fields, selectors, subtype meanings, and corresponding
Clothes attachment renderers are in
[native-items-equipment-and-loot.md](native-items-equipment-and-loot.md#exact-item-art-binding).

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

The item-definition selectors are joined to their exact Inventory ranges, and
the Hat/Robe/Staff/Wand attachment paths, seven sink owners, equip/unequip
transfers, refresh lifetime, and pose-dependent Clothes selector logic are
documented in
[native-items-equipment-and-loot.md](native-items-equipment-and-loot.md).
The isolated Create/Courtyard/Arena run also verified representative wizard
and atlas residency against rebased retail addresses.

## Skill and weld logic recovered

`0x00674EE0` constructs 80 skills at 0x70-byte stride and loads their CFGs via
the ID-to-name resolver at `0x00657C00`. The ordinary level-up path begins at
`0x0067C250`; `0x0066F920` creates/builds the picker; `0x00671470` applies the
selected skill and refreshes state. Normally three choices are shown, or four
when Creativity `0x3F` has a nonzero effective rank. Concentrating on
Creativity gives an exact 20% roll to mark one eligible displayed choice as an
Insight; choosing it applies that skill twice. The eligibility predicate,
rank-headroom test, and native index-vs-ID typo are recorded in
[skill-picker-re.md](../skill-picker-re.md).

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

The native object side is indexed across 46 projectile/effect classes and 197
decompiled methods. The vtable roles, construction inheritance, update and
render roots, contact ABI, modifier creation, direct class-owned art, borrowed
animation descriptors, owned child animations, and cleanup containers are in
[native-projectiles-and-effects.md](native-projectiles-and-effects.md). The
cast-side map covers every compiled primary, weld, secondary, and advanced
case, including passive/concentration refresh, spawned types, initialization
payloads, status modifiers, and persistent toggles.

## Enemy families and enemy-owned children

The native enemy census is now closed at 19 participating runtime types,
including the `Badguy` base, Good/Green Imp variants, Heartmonger Crow helper,
Coffin Maggot, Spider Cocoon, and stationary Imp Portal. The complete config
parser, wave-flag transforms, construction/registration path, target/chase
ABI, family action state machines, child ownership, boss spell dispatch,
death presentation, reward eligibility, one-candidate drop selector, and
direct atlas ranges are documented in
[native-enemies.md](native-enemies.md). The generated
[native-enemy-catalog.json](native-enemy-catalog.json) preserves the finite
type list and evidence joins.

The two former enemy residuals are closed. Dire Faculty's index-3
primary/secondary strings are present but have no dispatcher branch, proving
them dormant. Portal's six frequency presets, timing-scale conversion,
inclusive ordinary reset, and one-in-eight fast-reset override are recovered
from the machine instructions and preserved in the generated catalog.

## Item, equipment, and ground-loot map

The static item/loot pass is closed in
[native-items-equipment-and-loot.md](native-items-equipment-and-loot.md). It
recovers the complete shipped definition grammar (47 recipes, seven sets, and
39 FX kinds), the separate recipe/live UID allocators, definition cloning and
random-equipment generation, all item subclasses, consumables, nested sacks,
perks, exact Inventory/Clothes art binding, and two-pass stat application.

The gameplay scene owns one inventory root at `+0x13B8` and seven equipment
sinks: Hat `+0x1428`, Robe `+0x142C`, rings `+0x1430/+0x1434/+0x1438`, Amulet
`+0x143C`, and Staff/Wand `+0x1440`. Set completion uses exact recipe UIDs from
all seven sinks; insertion, potion stacking, equip/unequip transfer, and
progression refresh are mapped.

The four ground-reward actors are Orb `0x7DB`, Gold `0x7DC`, Sack carrier
`0x7DD`, and Bonus `0x7F6`. Their category selection, construction, state,
render records, collision/pickup behavior, ownership transfer, timers, and
destructors are mapped. In particular, the Sack carrier owns a live item until
pickup transfers that exact pointer through `Inventory_InsertOrStackItem`; it
is not merely a generic Inventory icon drawn in the world.

## Loose world images

The initializer at `0x005BBD90` loads roads 1..5, fence grate, ether plane,
green plasma, river/rise, and WallTop into a large world-render object. The
exact destinations are recorded in
[native-asset-system.md](native-asset-system.md#loose-image-ownership-and-consumers).
WallTop is a dormant stock load: its store to owner `+0x31C5F4` is the only
compiled reference to that field, so neither Wall nor another renderer reads
it after initialization.
`paintbkg` belongs to portrait capture at `0x005BED10`, not ordinary world
rendering.

The arena base field is also closed positively. Arena renderer `0x0046EC80`
and editor renderer `0x004D5F40` clear the target to opaque black through
`0x0041D840` -> `0x00440D40` -> Direct3D `Clear`, then stamp DeadHawg record
21 across the visible field at 200-pixel logical intervals. Arena modes 1/2
substitute record 20. Their use of absolute Sprite addresses
`0x00B2F368`/`0x00B2F2A4` is a compiler-folded exception to the generated
singleton-relative consumer join. The website editor's mirror-tiled ground
WebP is a documented capture of this composed retail presentation, not a
native loose texture. See
[native-boneyards-and-world.md](native-boneyards-and-world.md#arena-and-editor-base-field-rendering).

## Closed custom-content contracts

1. Atlas counts, destination fields, factory types, skill/enemy dispatchers,
   item recipes, and the sound registry are finite compiled identities.
   Boneyards and their bounded recipe grammar are data-driven; voices and a
   small set of loose assets are filename-addressed; stock code does not
   generally enumerate asset directories.
2. Atlas art is selected by fixed numeric record/pointer ABI, gameplay actors
   by factory type and config selector, and loose/voice/music content by the
   specific path grammar documented for that subsystem.
3. `MyApp`/atlas globals own decoded pages and GPU residency; sprite wrappers
   borrow or own animation children according to their concrete class; actors
   own gameplay state and transient children; Region/RegionLayout owns the
   materialized world graph; reward actors retain live item ownership until a
   pickup transfer succeeds.
4. Art changes must be installed before the relevant atlas or region is built.
   Compatible replacement preserves bundle record count/geometry ABI; reload
   must follow the documented release/cache/device-reset path. World or logic
   changes require normal actor, collision, derived-child, audio-request, and
   layout teardown rather than pointer substitution.
5. Stock data can replace existing records and compose existing boneyard/NPC
   primitives within their grammars. New factory types, render cases, spell or
   enemy dispatcher branches, and gameplay audio triggers require Lua/native
   hooks or loader-owned extension logic.
6. Before multiplayer construction, peers must agree on the active mod set and
   content hashes for Boneyard, Lua, and art, plus every behavior-affecting
   config, hook, record-layout, timing, RNG-order, collision, and derived-child
   change. Pixel-only replacement may be classified as presentation state only
   when geometry and consumer ABI are unchanged.

No website download or mod-enablement implementation was performed during
this native decompilation phase.
