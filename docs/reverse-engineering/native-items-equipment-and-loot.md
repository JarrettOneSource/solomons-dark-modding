# Native items, equipment effects, and ground loot

## Result

The retail item system has three distinct layers that must not be collapsed
into one "asset loader":

1. `data/items.cfg` creates global `ItemRecipe` and `ItemSet` definitions.
2. Factories clone those recipes, or generate random equipment, into live
   `Item` subclasses owned by inventories and equipment sinks.
3. Gold, health/mana orbs, item carriers, and powerups are separate world
   actors with their own art, timers, pickup rules, and destruction paths.

The shipped `items.cfg` contains **7 sets, 47 equipment recipes, and 86 FX
declarations**. The definitions use six compiled equipment types. Potions,
sacks, perks, maps, miscellaneous quest/consumable items, and all four ground
reward actors are constructed elsewhere.

The machine-readable inventory is
[`native-item-catalog.json`](native-item-catalog.json). It preserves every
definition, both `IMAGE` declarations on Absolox's Boomstick, the effective
last-write-wins selector, set membership, colors, all raw FX strings, parsed
operators/targets, and exact Inventory-atlas records. Rebuild it with:

```bash
python3 tools/build_native_item_catalog.py \
  --input /path/to/data/items.cfg \
  --source-label stock/data/items.cfg \
  --output docs/reverse-engineering/native-item-catalog.json
```

The complete runtime selector, actor-private seed lifecycle, amount tables,
pickup physics, lifetimes, and multiplayer credit rule are in
[`native-loot-selector.md`](native-loot-selector.md). This document remains the
definition, object-layout, ownership, art, and effect reference.

This document covers the retail `SolomonDark.exe` whose SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

## Shipped definition inventory

The cataloged source is 14,755 bytes and has SHA-256
`28e26243457b246ce48ed7f37d4c14820f9e4a67d1ddf5d328e3a0783a641963`.
Its recipe totals are:

| Type | Native type | Recipes | Inventory selector range |
| --- | ---: | ---: | ---: |
| Ring | `0x1B5A` / 7002 | 13 | 0..11 |
| Amulet | `0x1B5B` / 7003 | 9 | 0..11 |
| Staff | `0x1B5C` / 7004 | 4 | 0..5 |
| Hat | `0x1B5D` / 7005 | 6 | 0..3 |
| Robe | `0x1B5E` / 7006 | 7 | 0..2 |
| Wand | `0x1B63` / 7011 | 8 | 0..5 |

Twenty-nine recipes belong to the seven sets; eighteen are top-level unique
items. Rarity is split between 23 Rare and 24 Epic recipes. There are 73
item-owned FX declarations and 13 set-owned declarations.

### XML-like grammar and native parse behavior

`ItemSet_Parse (0x00574D60)` reads top-level `ITEMSET` and `ITEM` blocks.
`ItemRecipe_Parse (0x00573570)` recognizes these fields case-insensitively:

| Field | Native destination | Behavior |
| --- | ---: | --- |
| `TYPE` | recipe `+0x84` | Maps only Hat, Ring, Amulet, Staff, Wand, and Robe to compiled type IDs. |
| `NAME` | `+0x34` | Recipe/live display-name override. |
| `DESCRIPTION` | `+0x50` | Long item information text. |
| `IMAGE` | `+0x88` byte | Selector; `-1` normalizes to zero. Repeated fields overwrite earlier values. |
| `LEVEL` | `+0x8A` byte | Required/generated item level. |
| `RARITY` | `+0x89` byte | Common 0, Rare 1, Epic 2. |
| `FX` | list at `+0x6C` | Parsed by `0x005722A0`. Repetition appends effects. |
| `COLOR1` | `+0x8C` float4 | Primary wearable tint. |
| `COLOR2` | `+0x9C` float4 | Secondary wearable tint. |

An `ITEMSET` additionally owns a name, a list of set FX, and the nested recipe
UIDs. The final `<IGNORE>` block in the stock file is documentation text; it
does not become definitions or effects.

Absolox's Boomstick declares `IMAGE 5` before its name and `IMAGE 0` later.
The parser executes both assignments, so the effective selector is **0**, not
5. A content importer that normalizes duplicate tags before applying native
ordering would silently render the wrong staff.

### Recipe IDs are not source ordinals

Every parsed recipe calls `0x005B98C0` and stores the result at recipe `+0x14`.
That function advances the persisted property `Game.ItemRecipeUID`. Live item
construction instead calls `0x005B9870`, which advances the separate
`Game.UID` property. Consequently:

- the catalog's `source_index` is only deterministic file order;
- it is not a claim about the runtime recipe UID;
- save/boneyard and multiplayer item identity must use the assigned recipe UID
  or a loader-owned stable content identity, never a guessed ordinal.

`ItemRecipe` serialization at `0x00570D90` includes the recipe UID, strings,
FX list, type, selector, colors, rarity, and level. A zero deserialized UID is
repaired through the live-object `Game.UID` path, which is another reason a
mod layer cannot infer identity from source position alone.

## Definition and live object layouts

### Base item and subclasses

`Item_Ctor (0x00572F20)` creates an 0x88-byte base object with type 7000,
strings, an FX list, and a new live `Game.UID`. Its serializer at `0x00570AE0`
establishes this common layout:

| Offset | Field |
| ---: | --- |
| `+0x08` | runtime item type ID |
| `+0x14` | live object/item UID |
| `+0x18` | source recipe UID |
| `+0x1C` | image/slot/subtype selector, depending on subclass |
| `+0x20` | explicit display-name string |
| `+0x58` | active byte |
| `+0x59` | rarity byte |
| `+0x5A` | item level byte |
| `+0x5C` | serialized integer state |
| `+0x60` | serialized float state |
| `+0x6C` | live FX smart-pointer list |
| `+0x84` | belongs-to-item-set byte |

Hat and Robe use serializer `0x00570C60` and add independently controlled
float4 colors at `+0x88` and `+0x98`. Potion, Amulet, Perk, and Map use
`0x00570CA0` and add a 32-bit value at `+0x88` (stack count, secondary
selector, perk ID, or map-specific state). `Item_Sack` uses `0x00570C20` and
serializes its nested item list at `+0x88`.

| Type | ID | Constructor | Extra meaning |
| --- | ---: | ---: | --- |
| Item | 7000 / `0x1B58` | `0x00572F20` | Base/placeholder. |
| Potion | 7001 / `0x1B59` | `0x005A7580` | `+0x1C` subtype, `+0x88` stack count. |
| Ring | 7002 / `0x1B5A` | `0x00461FF0` | Equipment recipe instance. |
| Amulet | 7003 / `0x1B5B` | `0x00462020` | Equipment recipe instance; extra icon selector state. |
| Staff | 7004 / `0x1B5C` | `0x00462050` | Held-equipment renderer. |
| Hat | 7005 / `0x1B5D` | `0x00461ED0` | Two tint layers. |
| Robe | 7006 / `0x1B5E` | `0x00461F70` | Two tint layers. |
| Unregistered ID | 7007 / `0x1B5F` | none | Numeric hole with no factory or recipe-materializer branch in the retail executable. |
| Item_Sack | 7008 / `0x1B60` | `0x005A7520` | Owns a nested 0x58-byte item-list root. |
| Item_Perk | 7009 / `0x1B61` | `0x00550490` | `+0x88` charm/curse/perk selector. |
| Item_Map | 7010 / `0x1B62` | `0x005A75D0` | Registered/serializable; no direct stock art or non-constructor type check recovered. |
| Item_Wand | 7011 / `0x1B63` | `0x00462070` | Held-equipment renderer. |
| Item_Misc | 7012 / `0x1B64` | `0x005A75B0` | `+0x1C` dye/key/book subtype. |

`Item_Sack` copies the sack's live UID into the nested root, owns the nested
objects, participates in recursive potion/type lookup, and is opened as an
inventory root rather than consumed. Its help text at `0x00571BF0` reports
the contained item count or that it is empty.

### Item_Sack InventoryScreen navigation

`InventoryScreen` does not flatten every nested root into one visible grid.
The current visible `SdItemListRoot*` is at screen `+0x158`; the parent-root
stack begins at `+0x174` and its count is at `+0x184`. Activation handler
`0x0056D920` resolves the selected live item. For type 7008 it always accepts
the activation, including an empty Sack, pushes the current root, switches
`+0x158` to `Item_Sack_GetInventoryRoot (0x00570C10)`, and writes the owning
Sack into child root `+0x08`. The grid then contains only that root's direct
children. Nested Sacks repeat the same transition.

Game-back in `0x0056D920` pops exactly one parent root while the stack is
nonempty. Only game-back at the outer root closes the InventoryScreen. The
transition-active byte is `+0x168`, the page-motion countdown is `+0x16C`,
and signed direction is `+0x170`: `+1` opens a child from the right while the
old page moves left; `-1` returns to a parent from the left while the child
moves right. `InventoryScreen_Update (0x00551A10)` moves both InventoryGrid
pages by exactly 10 stage pixels per 100 Hz update and ignores another
activation until the full client-width traversal completes. At the stock
1600-wide stage this is exactly 160 updates / 1.6 seconds.

Opening a child root requests compiled registry member 5,
`sounds\\backpack_open`, at gain 1 and default pitch through `0x00407B70`.
Returning to a parent requests member 4, `sounds\\backpack_close`, at gain 1.
Closing the outer InventoryScreen instead requests member 64,
`sounds\\openpanel`. Standalone construction at `0x005C6F10` is silent and
is shared by the ordinary gameplay Inventory control, so Sack navigation has
no Hub-versus-Boneyard scene gate and no inventory mutation or network state.

This page-navigation action is distinct from
`Inventory_EquipAllEligible (0x0056B090)`. The common use dispatcher
`0x0056D1B0` and a compatible drag/equipment route can pass an Item_Sack to
that sibling operation. It walks eligible Hat, Robe, Staff, Wand, Amulet, and
Ring children, applies the item-level gate at `0x00577900`, swaps displaced
equipment back into the same Sack, and plays `backpack_open` at pitch 0.8 and
gain 1. It does not own the InventoryScreen child-root transition.

### Recipe, set, and FX objects

`ItemRecipe_Ctor (0x00573410)` creates type 6003 and initializes its parent
set index at `+0xAC` to `-1`. `ItemSet` is type 6005:

| Object | Important fields |
| --- | --- |
| ItemRecipe | `+0x14` recipe UID; `+0x18/+0x34/+0x50` strings; `+0x6C` FX; `+0x84` live item type; `+0x88` image; `+0x89` rarity; `+0x8A` level; `+0x8C/+0x9C` colors; `+0xAC` parent set index. |
| ItemSet | `+0x14` global/set index; `+0x18` name; `+0x34` member recipe-UID array; `+0x44` set FX list. |
| FX | `+0x14` kind byte; `+0x18` spell/skill/class selector; `+0x1C` operator byte; `+0x20` float magnitude. |

## Recipe materialization and random gear

`0x004699B0` clones a definition into a live item. Its compiled switch accepts
only Ring, Amulet, Staff, Hat, Robe, and Wand. It allocates the concrete class,
copies the image selector, recipe UID, rarity, level, strings, and cloned FX,
sets live item `+0x84` when the recipe belongs to a set, and copies wearable
colors. A Hat/Robe source color with zero alpha takes the native random-color
path before conversion.

`0x0046BDE0` selects definitions by requested rarity and level range. It also
filters recipes already owned and scenario/settings exclusions before choosing
and cloning one. This is the definition-backed reward path.

`0x004645B0` is a separate random-equipment factory. It chooses one of the six
equippable classes, chooses a selector within the compiled atlas count, creates
Hat/Robe colors where needed, and calls `0x0057A000` to synthesize level-scaled
FX. Random gear therefore does not require a matching `items.cfg` recipe, and
its recipe/set identity differs from the named-definition path.

### Fixed Tutorial authored equipment

The Tutorial Boneyard embeds a third definition source outside `items.cfg` and
the random factory: ItemRecipe UID 3010, materialized once by script 10050 as
`Sorceror's Amulet`. Its exact authored fields are type 7003 Amulet, selector
0, inventory records 30 and 18, two white RGBA colors, description
`A dull trinket, carved with a few beneficial runes`, and one FX child with
payload `02 00 00 00 00 02 00 00 20 41`.

The FX vtable is `0x007873AC`; its sync virtual at `+0x14` is `0x00570A90`.
That serializer writes kind byte `+0x14`, target dword `+0x18`, operator byte
`+0x1C`, and magnitude float `+0x20`. The payload is therefore exactly kind 2
`FX_SPELLCLASSDAMAGE`, target 0 Ether, operator 2 percentage, magnitude 10.0.
The passive application branch at `0x00576AA0` multiplies progression's Ether
class-damage lane `+0x100` by `1.1`, and formatter `0x00575C20` emits
`Ether Damage +10.0%`. Clone `0x004699B0` retains the recipe strings and clones
the FX list into the live item; common contextual builder `0x0057C4B0` emits
the description and formatted live effect. This fixed row has no
`items.cfg` source index or set membership, but it is not effectless.

The initial class selector is native `Integer(6)`: Hat and Robe results 0/1
each have two preimages out of the primitive's eight-value mask, while Staff,
Wand, Ring, and Amulet each have one. Hat/Robe color construction uses the
exact nine-row red/orange/yellow/pale-green/cyan/blue/magenta/.4-gray/.8-gray
palette, optional signed `.1` RGB jitter, optional `*1.85`, channel clamping,
then an 80-percent luminance blend with weights
`.3086000085/.6093999743/.0820000023`; the second layer is independently white.

`0x0057A000` owns 25 synthesized FX selectors and one/two-effect naming. Two
effects are possible only above requested level 18, through the short-circuited
`Integer(2)==1`, `Integer(5)==3`, `Integer(10)==3` chain; success immediately
writes generated item level 8. Skill
targets are not “learned skills”: selector 6 uses compiled row flag `+0x28`,
selector 8 uses `+0x28 || category==3`, and selector 9 uses every enabled row
8..79, with advanced 72..79 gated by their eight unlock bytes. Selector 9 uses
the native skill display name. Item level `+0x5A` begins zero, is 8 for a
two-effect result, and selector 8 raises it to at least the target skill's
compiled minimum level at row `+0x2C`.
Hat/Robe exclude selectors `2,3,8,9,12,13,17,21,22`; only the switch branches
that actually compile the half-and-tie-to-even block halve wearable magnitude.
The complete selector/magnitude/name program and draw order are recorded in
[`native-loot-selector.md`](native-loot-selector.md).

## Exact item art binding

### Inventory icons

All `items.cfg` recipes select fixed records in the 84-record `Inventory`
atlas. `IMAGE` is an index inside a compiled per-class group, not a filename.

| Live type | Renderer | Inventory records |
| --- | ---: | --- |
| Ring | `0x005788B0` | `52 + image` -> 52..63 |
| Amulet | `0x00578910` | main `18 + image` -> 18..29; secondary `30 + floor(image/6)` -> 30..31 |
| Staff | `0x00578A90` | `72 + image` -> 72..77 |
| Hat | `0x005779B0` | two layers: `34 + image` and `38 + image` -> 34..41 |
| Robe | `0x00577B90` | two layers: `64 + image` and `67 + image` -> 64..69 |
| Wand | `0x00579720` | `78 + image` -> 78..83 |

Hat and Robe icons draw both layers with the colors at item `+0x88` and
`+0x98`. This is real compositing state, not two interchangeable icon
variants.

Non-recipe item icon selectors are:

| Type | Inventory/Skills art |
| --- | --- |
| Potion | Inventory 46..51 for subtypes 0..5; stack count is rendered from `+0x88`. |
| Item_Sack | Inventory 70..71 selected by `+0x1C`. |
| Item_Perk | Inventory 10 when selector is `-1`; otherwise Skills 127..155. |
| Item_Misc | Inventory 42..45 for dye, key, and the two books. |
| Item_Map | No direct renderer recovered. |

### Wizard attachment composition

The same selector feeds a second, pose-dependent Clothes-atlas path when an
item is equipped. These functions do not copy a precomposited inventory icon
onto the wizard:

| Type | Attachment renderer | Clothes records/state |
| --- | ---: | --- |
| Hat | `0x005758F0` | Selector `s=0..3`: primary Clothes `316+24s .. 339+24s`, secondary `412+24s .. 435+24s`; both colors apply. |
| Robe | `0x00577DA0` | Selector `s=0..2`: five-pose primary Clothes `868+120s .. 987+120s`, secondary `1228+120s .. 1347+120s`; fixed primary banks 1612..2019/2428..2835 and secondary 2020..2427/2836..3243 retain the same two colors. |
| Staff | `0x00578D20` | Body selector 5..10; optional glow layers 11..12; pose banks 3244..3483 and 3484..3723; generated hand/glow geometry. |
| Wand | `0x00579820` | Clothes 15 plus dynamically built line/beam geometry around the hand attachment. |

`Staff_RenderAttachment (0x00578D20)` first indexes Clothes records 5..10 by
the live staff selector. When its optional glow-color argument is present, it
also draws records 11..12 and a generated four-vertex colored/flickering quad.
The current pose then selects from the two complete staff banks, records
3244..3483 and 3484..3723. Staff helper `0x005795E0` and the parallel wand
helper `0x00579680` return frame-specific attachment points from their native
tables. The renderer therefore requires the Clothes selector and pose tables,
the actor's current animation frame, and live item/color state; an icon
replacement alone cannot define new wearable geometry or glow composition.

The local-player compositor `0x00538B80` makes the branches mutually
exclusive. A live Hat replaces the default heading-only head pair; a live Robe
selects its two five-pose style banks and tints all four fixed banks with the
same item colors. A Staff selects shaft material `5+image` and keeps the two
240-frame hand banks. A Wand uses record 15 for its endpoint quad and does not
reuse the Staff shaft selector. An empty weapon sink draws none of these
weapon attachments; the element orb belongs to the Staff branch rather than a
free-floating player effect.

## Equipment ownership and set completion

The local gameplay scene owns the inventory at `scene +0x13B8` and seven
equipment sinks:

| Scene offset | Sink kind | Accepted item |
| ---: | ---: | --- |
| `+0x1428` | 1 | Hat |
| `+0x142C` | 2 | Robe |
| `+0x1430` | 5 | Ring slot 0 |
| `+0x1434` | 5 | Ring slot 1 |
| `+0x1438` | 5 | Ring slot 2 (progression-gated) |
| `+0x143C` | 6 | Amulet |
| `+0x1440` | 4 | Staff or Wand |

`EquipAttachmentSink_AcceptsItem (0x00570CD0)` performs that type check.
`0x00575850` attaches an object; `0x00570D80` returns the current object; and
`0x0066F020` removes the current item, reinserts it into inventory, and
refreshes progression. `Inventory_InsertOrStackItem (0x0055FF20)` merges
potions with the same subtype and otherwise inserts the live pointer.

Set completion is evaluated from exact recipe identity:

1. live item `+0x84` marks it as a set candidate;
2. live item `+0x18` resolves its `ItemRecipe` and recipe `+0xAC` resolves the
   parent `ItemSet`;
3. `0x00555DA0` gathers all seven equipped items and verifies that every UID in
   the set's `+0x34` member array is represented;
4. only completed sets contribute the FX list at set `+0x44`.

Duplicate-looking random equipment cannot complete a set without the exact
recipe UID.

## FX grammar and two-pass application

### Parser contract

`ItemFx_Parse (0x005722A0)` recognizes 39 tokens. `0x00571000` parses the
numeric operator:

| Syntax | Operator byte | Meaning |
| --- | ---: | --- |
| `+N`, `-N`, or bare `N` | 0 | Flat/additive form. |
| `*N` | 1 | Direct multiplier. |
| `+N%` or `-N%` | 2 | Percentage form, normally `1 + N/100`. |

`0x00571380` resolves quoted skill names by scanning the 82 native names at
`0x00657C00`. `0x005711C0` resolves classes exactly as Ether 0, Fire 1, Air 2,
Water 3, Earth 4, Body 5, Mind 6, and Arcane 7.

`ActorProgressionRefresh (0x0065F9A0)` reaches `0x0065F5B0`, which restores
current skill ranks from base state and resets passive accumulators. It then
uses two distinct equipment passes:

- `0x00656F60` calls the FX engine with `skill_pass = 1`;
- `0x00657310` calls it with `skill_pass = 0` for passive stats/features.

Both gather all seven sinks plus completed sets. Items containing Grant Skill
are moved to the end of the application order so prerequisite/learned-state
changes from other effects happen first. `0x00577760` walks item FX,
`0x00579D10` walks completed-set FX, and `0x00576AA0` applies each entry.

### Skill-changing effects

Only IDs 4..8 execute during the skill pass:

| ID/token | Behavior |
| --- | --- |
| 4 `FX_GRANTSKILL` | Calls `0x00660580` for the target skill and converted magnitude. |
| 5 `FX_BOOSTSKILL` | Adds to an already learned target, capped at its native maximum. |
| 6 `FX_BOOSTSKILLCLASS` | Enumerates the selected class through `0x00674E70`, boosts every learned member, and caps each. |
| 7 `FX_ADDSKILL` | Learns an unlearned target through `0x00660580`; otherwise boosts/caps it. |
| 8 `FX_ALLSKILLS` | Boosts every learned skill ID 8..79 and caps each. |

### Passive stat and feature effects

For the ordinary split fields below, operator 0 adds magnitude to the flat
field, operator 1 multiplies the multiplier field by magnitude, and operator 2
multiplies it by `1 + magnitude/100`.

| ID/token | Progression destination and exact special handling |
| --- | --- |
| 1 `FX_SPELLDAMAGE` | multiplier `+0xF4`, flat `+0xFC`. |
| 2 `FX_SPELLCLASSDAMAGE` | multiplier `+0x100[class]`, flat `+0x120[class]`. |
| 3 `FX_MELEEDAMAGE` | multiplier `+0x6F4`, flat `+0x6F8`. |
| 9 `FX_MANARECOVERY` | All three operators act directly on the single field `+0x98` (add, multiply, percent-multiply). |
| 10 `FX_MANACOST` | multiplier `+0x3D0`, flat `+0x3D8`. |
| 11 `FX_SPELLCLASSMANACOST` | multiplier `+0x3DC[class]`, flat `+0x3FC[class]`. |
| 12 `FX_CASTSPEED` | multiplier `+0x6AC`, flat `+0x6B0`. |
| 13 `FX_SPELLCLASSCASTSPEED` | multiplier `+0x6B4[class]`, flat `+0x6D4[class]`. |
| 14 `FX_GOLDBONUS` | Ignores operator byte and multiplies `+0xC0` by `1 + magnitude/100`. |
| 15 `FX_ORBPULL` | `*N` directly multiplies `+0xBC`; other forms multiply it by `1 + magnitude/100`. |
| 16 `FX_HPRECOVERY` | All three operators act directly on `+0x9C`. |
| 17 `FX_WALKSPEED` | Flat adds `magnitude/10` to `+0x90`; multiply/percent use normal multipliers on that same field. |
| 18 `FX_RESISTDAMAGE` | Adds `magnitude/100` to `+0xA0`, regardless of operator. |
| 19 `FX_RESISTMAGIC` | Adds `magnitude/100` to `+0xA4`, regardless of operator. |
| 20 `FX_RESISTPOISON` | Adds `magnitude/100` to `+0xA8`, regardless of operator. |
| 21 `FX_RECHARGE` | All three operators act directly on `+0xD0`. |
| 22 `FX_RECHARGECLASS` | All three operators act directly on `+0xD4[class]`. |
| 23 `FX_MAXHP` | All three operators act directly on `+0x74`. |
| 24 `FX_MAXMANA` | All three operators act directly on `+0x80`. |
| 25 `FX_ONESPELLDAMAGE` | multiplier `+0x140[skill]`, flat `+0x288[skill]`. |
| 26 `FX_MAXLEVIATHAN` | Sets feature bit `0x0001` at `+0x878`. |
| 27 `FX_MAXMAGICSTORM` | Sets `0x0002`; the ID-27 dispatcher doubles the new StormCloud's active counter `+0x13C` after all normal duration setup. |
| 28 `FX_MAXRINGOFFIRE` | Sets `0x0004`; the ID-21 factory copies it to Shockwave flag `+0x170 & 4`. Each newly admitted wave target then receives the normal contact plus a scale-`1.5` common explosion (165-unit query dimension, `mDamage/2` area damage) and three outward Ember actors carrying `mDamage/3` each. |
| 29 `FX_MAXGOLEM` | Sets `0x0008`. |
| 30 `FX_MAXRINGOFICE` | Sets `0x0010`; the ID-35 factory copies it to FreezeWave flag `+0x174 & 0x10`, causing every admitted wave target to receive `Mod_FrostBurn (0x1B78)` in addition to Frozen/ColdSlow. |
| 31 `FX_MAXEMBERSTOIMPS` | Sets `0x0020`. |
| 32 `FX_MAXDISINTEGRATION` | Sets `0x0040`. |
| 33 `FX_MAXETHERCHARGE` | Sets `0x0080`. |
| 34 `FX_MAXHARDEN` | Sets `0x0100`. |
| 35 `FX_MAXROCKSURGE` | Sets `0x0200`. |
| 36 `FX_MINDBLAST` | Sets `0x0400`; level-up path `0x005C88B0 -> 0x0052A220 -> 0x00645B50` emits the full common blast presentation and zero-damage expanding Shockwave for every element. Direct radius-495 `playerLevel/2` damage is gated by first element parameter zero and therefore occurs only for Ether. |
| 37 `FX_MAXWELD` | Sets `0x0800`; native display name is `Energize Weld Components`. |
| 38 `FX_WELDEFFECT` | Updates scalar `+0x8E0`: flat adds magnitude, `*` multiplies, percent adds `magnitude/100` to the scalar. |
| 39 `FX_WELDCALLING` | Sets `0x1000`; native display name is `+Bias Skills for Welding`. |

### 2026-08-21 feature-consumer xref closure

An executable-wide instruction scan of progression feature field `+0x878`
closes every downstream reader. The only gameplay reads are secondary-set bits
`0x1/0x2/0x4/0x8/0x10` in `0x0054CC50`, Mindblast `0x400` in
`0x005C88B0`, Energize Weld Components `0x800` in `0x00666020`, and Welding
offer bias `0x1000` in `0x0067CB70`. Bits `0x20`, `0x40`, `0x80`, `0x100`,
and `0x200` are written by `FX_MAXEMBERSTOIMPS`,
`FX_MAXDISINTEGRATION`, `FX_MAXETHERCHARGE`, `FX_MAXHARDEN`, and
`FX_MAXROCKSURGE`, but have no executable reader. Their named item/set effects
are shipped inert and must not synthesize extra projectiles, damage, armor, or
proc behavior.

The live consumers for the non-bit scalars remain direct. `FX_GOLDBONUS`
multiplies progression `+0xC0`, and Gold spawner `0x0046AA90` multiplies and
rounds every requested Gold total by that field before chunking. `FX_HPRECOVERY`
feeds the ordinary `+0x9C/(tickRate*10)` recovery lane independently of the
active Regenerate `1.5/tickRate` add. `FX_WELDEFFECT` changes the welded vector
materializer scalar; it is not a later generic outgoing-damage multiplier.

The percent implementation for Weld Effect is deliberately unusual: it adds
the fractional value to the scalar rather than multiplying by `1 + N/100`.
The distinction between bits `0x800` and `0x1000` also corrects the earlier
provisional welding label; see [spell-welding.md](spell-welding.md).

The max-effect consumers are event/factory branches, not refresh-time scalar
bonuses. `0x0054CC50` tests feature bits `2/4/8/16` only while creating Magic
Storm, Ring of Fire, Golem, and Ring of Ice. Max Ring of Fire's common helper
`0x00642BF0` also consumes one active `Integer(1,000,001)` seed, then runs the
three-Ember fan from a private native RNG while each Ember constructor retains
its normal active-RNG draws and ten immediate pre-ticks. Max Ring of Ice's
`FrostBurn` stores duration `round(freezeSeconds*200)`, damage `1/200` per
modifier tick, source group at `+0x20`, and merges by the existing modifier
identity/maximum-duration path. Its tick `0x006278B0` dispatches flags `0x18`
and independently owns the icy additive particle branch; it is neither the
ordinary Fire `Burn` row nor a visual-only marker.

FrostBurn's particle branch is exact as well. Every live modifier tick consumes
`Integer(2)`; result one creates one additive `Anim_MoveFadeAdditive` and the
miss consumes nothing further. Success then consumes `Integer(2)` to choose
BadGuys record 10 (result one) or 11, `Float(360)` rotation,
`Float(.5)+.5` scale, `Float(10)` plus one 100001-way unit-vector word for the
birth offset, `Float(35)` upward offset, `Float(1)+.5` plus a second unit-vector
word for velocity, and `Float(.5)` for starting alpha `1-draw`. Tint is
`(.25,.5,.5,1)`, alpha loss is `.05`, and velocity multiplies by `.96` after
each move. The child is additive/self-colored and publishes no light.

Mindblast's full event is closed at `0x0052A220/0x00645B50`. It plays
`magicshieldexplode` once at default pitch, then `bigfire` once at default
pitch and once at pitch `0.8`, all through the point-gain path. Its retained
presentation consists of one normal BadGuys-15 fade at `(x,y-25)`, scale
`9*6=54`, alpha loss `0.025`; three additive cyan Clothes-2 `Anim_FadeScale` rings at
`(x,y-35)`, initial scale `4.5`, initial alpha `1.5`, alpha loss `0.025`, and
scale multipliers `1.1/1.05/1.025`; two additive BadGuys-158..167 sprite-array
actors at the origin with scale `10`, random rotation, and frame steps
`0.075/0.1125`; and exactly 100 cyan `Anim_FuzzySpear` actors. Every spear
draws a heading `Float(360)`, speed `Float(2)+3`, doubles speed when
`Integer(5)==2`, starts 75 units along that heading, uses velocity multiplier
`0.95`, alpha `Float(1)+1`, alpha loss `0.00875`, and scale
`Float(1.5)+2`. The procedural spear draw owns a separate per-frame signed
presentation jitter. None of those additive/self-colored children samples
Region light or publishes a world light. The final zero-damage Shockwave is
the light owner: radius starts at 75 and gains 8 per tick, life starts at
`0.35` and loses `0.01`, fade begins below `0.0375`, and its provider
`0x005E7AA0` publishes intensity from the push scalar and radius divided by
140. It also retains the ordinary one-contact Dazzle and radial-push behavior.

The direct-damage branch at `0x00646345` first requires `param_2 == 0` and
positive level damage. The authoritative element catalog is Ether 0, Fire 1,
Air 2, Water 3, Earth 4, so the prior all-element damage reading was false.
Ether queries flag-2 targets through common circle helper `0x00642090` with
radius `9*55 = 495`; its exact admission is
`distanceSquared < 495^2 + targetRadius^2`, and each result receives
`level*.5`. Other elements skip only this direct contact branch.

Shockwave `0x7E7` starts radius 75, radius growth 8, alpha 1, life `.35`, life
loss `.01`, and fade threshold `.0375`. `0x005FF8C0` grows the radius before
work, admits each flag-2 target once on post-birth `age%10==0`, and attaches
400-tick Dazzle even though damage is zero. On even ages it pushes the retained
target set collision-aware along the normalized center-to-target direction by
`currentAlpha*8`. Provider `0x005E7AA0` submits intensity alpha and radius
`waveRadius/140` without a directional shadow. The burst constructors consume
exactly 502 active RNG words: two sprite-array rotations plus five words for
each of 100 FuzzySpears. Ongoing signed spear jitter remains part of the
process-global presentation stream and is not part of that constructor count.

## Potions, miscellaneous items, sacks, and perks

`0x0056D1B0` is the central inventory-use dispatcher. It resolves the selected
item recursively, dirties the gameplay inventory view, and branches by live
type.

### Potions

Potion subtype is at `+0x1C`; stack count is at `+0x88`. After a successful
use, the stack is decremented and an empty live item is removed/destroyed.

| Subtype | Native name | Inventory art | Effect |
| ---: | --- | ---: | --- |
| 0 | Health Potion | 46 | Sets current health `+0x70` to max health `+0x74`. |
| 1 | Mana Potion | 47 | Sets current mana `+0x7C` to max mana `+0x80`. |
| 2 | Wizard Chug | 48 | Arms progression `+0x824` and refreshes; stock help identifies quadruple damage for 60 seconds. |
| 3 | Antidote | 49 | Runs the poison-clear path and arms immunity state `+0x74C`; stock help identifies 10 seconds. |
| 4 | Mind Chug | 50 | Arms progression `+0x828` and refreshes; stock help identifies all-skills concentration for 60 seconds. |
| 5 | Rejuvenation Potion | 51 | Falls through from full-health to full-mana assignment, restoring both. |

The player input handlers `0x005296A0` and `0x00529710` recursively locate
health/mana potions through `0x005529A0` and `0x00552B70`, then use this same
dispatcher. Belt actions also resolve exact item UIDs before use.

### Miscellaneous item subtypes

| Subtype | Name | Behavior |
| ---: | --- | --- |
| 0 | Fabric Dye Kit | Opens `DyeClothing`; the kit remains live while colors are previewed and is removed only after a confirmed dye operation. |
| 1 | Wizard Key | Not manually consumed. Lock handler `0x00646D00` checks recursively and calls `0x005601B0` to remove exactly one key before opening the lock. |
| 2 | Book of Skill | Removes the book and opens `0x0067C320` to choose a new skill. |
| 3 | Book of Skill | Removes the book, builds the eligible learned-skill list, and opens the existing-skill improvement flow. |

The native help strings distinguish subtype 2 as "pick a new skill" and
subtype 3 as "learn existing skill." Both share the display name.

### Perks and charms

`Item_Perk` selectors 0..27 name the stock charms/curses/tonic; selector `-1`
is `Bargain Bundle`. Its icon is Skills `127 + selector`, while `-1` uses
Inventory 10. Perks are shop/progression payloads, not `items.cfg` equipment
recipes. Purchase flow `0x0056C340` checks charm capacity, charges global gold,
removes the shop item, applies the perk/tonic behavior, refreshes progression,
and rebuilds the inventory/shop UI. The complete name switch is at
`0x00571DD0`; it includes Spellwelder's Charm, Tonic, curses, and the class/
skill-oriented charms used by Hagatha's mixing flow.

## Ground reward actors

Ground rewards are world objects, not item subclasses merely drawn on the
floor:

| Actor | Type | Constructor | Tick | Renderer |
| --- | ---: | ---: | ---: | ---: |
| Orb | `0x7DB` / 2011 | `0x005E1150` | `0x005E62E0` | `0x0060FC10` |
| Gold | `0x7DC` / 2012 | `0x005E12C0` | `0x005E66B0` | `0x0060FFE0` |
| Sack item carrier | `0x7DD` / 2013 | `0x005E1460` | `0x005E6B50` | `0x006104F0` / `0x006105F0` |
| Bonus powerup | `0x7F6` / 2038 | `0x005E2D90` | `0x006039C0` | `0x0061A260` |

### Orb

Orb `+0x13C` selects health or mana; `+0x140` is remaining value; `+0x144`
starts at 900 and controls delayed value decay; `+0x148/+0x14C` drive phase
and alpha. The tick scans native player slots 0..3 using each progression
object's orb-pull radius. Between its strict pull and capture radii it moves a
constant 1.5 units per actor tick toward each qualifying slot; it has no
velocity or acceleration curve. Inside capture range it creates the collection
effect, scales the reward from remaining value, and deletes the actor. The
stock resource write is gated to slot 0: health calls `0x0052AC80`, mana calls
`0x0052B150`. Exact radii, decay endpoints, and multi-slot consequences are in
`native-loot-selector.md`.

Art is BadGuys 434/435 for the two rendered orb kinds, with BadGuys 15 and
related transient effect records used during animation/collection. Collection
constructs one normal BadGuys-15 fade at the Orb position with scale `1.5` and
alpha loss `.05`, wraps it in `ZAnim`, and registers it in the late same-row
ZAnim queue. `ZAnim` ticks the child, copies its position, and retires when the
child does; it does not home toward the player. The child consumes no RNG and
emits no light.

### Gold

Gold owns tier `+0x13C`, amount `+0x140`, activation/scatter delay `+0x144`, animation state
`+0x148`, and transient motion fields through `+0x158`. `0x005E13C0` maps
amount `<3`, `<5`, `<8`, or larger to tiers 0..3. Pickup checks only local
slot 0, deletes the actor, shows `%d GOLD`, and credits the process-global gold
scalar through `0x005A7C60(amount, false)`. Gold has no stock despawn timer;
`+0x144` is not lifetime.

The amount string is **not** part of painter `0x0060FFE0`; that painter's
misleadingly labelled `Text_Draw` call is the BadGuys-73 additive glint.
Pickup constructs `%d GOLD` and submits it to the process-global notification
manager at `0x00808878` through `0x005CA7C0`. That manager also owns Sack item
help text and Bonus result text. It uses Fonts wrapper group 3 at
`Fonts+0xE7D98` (records 216..307, header `[24,6,28]`) with a black two-pixel
shadow and the supplied foreground color.

Each notification starts with life 1.5 and scale-distance lane -18. Native tick
subtracts `.005` from life, so the maximum lifetime is 300 ticks. While the
newest lane is below zero, every tick moves all rows by one and reduces older
rows by `.025`, floored at `1-rowCount*.4`; insertion performs the same distance shift
in four-unit/`.1` chunks until the old newest row is no longer negative.
Consecutive current strings ending in `GOLD` merge while current life is above
one, sum their integer prefixes, and reset life to 1.5. Render alpha is life
clamped to `[0,1]`; the scale directive is `1-max(distance,0)/250`. The lane
does not move text vertically; every row remains screen-centered at the shared
notification origin and older rows separate through scale/alpha.

Gold text is `.85,.73,.44,1`. Bonus kind 0 is red/pink `(1,.5,.5,1)`, kind 1
is blue `(.5,.5,1,1)`, and kind 2 uses the Gold color. Sack pickup calls the
item help-text vslot and `0x00573110`: ordinary items are white, Rare starts
from `(1,1,.5,1)`, Epic from `(1,.75,.5,1)`, and an item belonging to a set
starts from `(.5,1,.5,1)`; all three colored cases use saturation lerp `.5`.
An Item_Sack help row is `Contains 1 item`, `Contains %d items`, or
`Currently empty`, not the generic word `Sack`.

Gold pickup separately creates two world-owned additive fades at
`(gold.x,gold.y-10)` from BadGuys record 83 (`BadGuys+0x3FC4`). Both use scale
one. The gold-tinted child has alpha loss `.05`; the white child has alpha loss
`.1`. They consume no RNG, retire after 20 and 10 actor ticks, emit no light,
and are not part of the notification manager.

After delay `+0x144` expires, the proximity radius is
`30 * progressionPickupScalar`. When that scalar exceeds float32
`1.25999999`, every in-range tick must pass `Integer(15)==1`. The recovered
integer helper treats 15 as an exclusive bound (`0..14`), so this is exactly a
1/15 gate, not 1/16. Constructor `0x005E12C0` stores `Integer(100000)` at
`+0x150`, `Float(360)` at `+0x154`, and signed `Float(20)` at `+0x158`.
Settled tick `0x005E66B0` adds the double `2.0` at `0x007DE838` to float32
`+0x154`; painter `0x0060FFE0` passes `+0x158`, not `+0x154`, as the settled
sprite rotation. The `+0x154` lane feeds a separate renderer-side auxiliary
effect/light branch whose full child contract remains to be closed.

The renderer selects BadGuys 188..197 and 198..201 by tier/state; record 73 is
also used by the render path and accepted pickup creates two additive record-83
fades. `0x0046AA90` splits a reward into chunks no larger than 25, performs each
collision-aware placement, applies cumulative 1..5-tick delay increments after
chunk six, consumes one dummy stack-Gold constructor, stable-sorts by world Y,
assigns remaining zero delays from `trunc(100*Float(.25))`, and registers every
actor. None of those shared draws is optional presentation entropy.

The transient/scatter branch is instruction-closed. While byte `+0x148` is
set, float32 progress `+0x14C` increases by `.5`; after it exceeds eight the
flag clears and `dropcoins` plays at `f32(1+signed Float(.1))`. Painter
`0x0060FFE0` draws its main BadGuys 188..197 frame at vertical offset
`(9-progress)*-4`, then draws `0/1/2/4` extra coins for tiers `0/1/2/3`.
Each extra advances private
seed `+0x150` through `0x004FFFF0` (xor shifts 21/11/4, multiply
`0x0A67CFCF`, absolute signed result), reduces it modulo 360, converts that
heading to a unit vector, and offsets by eight. This is actor-private cosmetic
state and consumes no shared RNG. Settled Gold draws `198+tier`; positive
`sin(+0x154 degrees)` additionally submits its native additive overlay at
`(x-5,y-5)`, rotation `+0x154`, scale `sin*1.25`. It is not a point/region
light.

Spawner `0x0046AA90` first multiplies the requested total by progression Gold
Bonus `+0xC0` and rounds it. It drains that total into chunks starting at
`min(remaining,25)`. When the original request exceeds 25, each chunk consumes
`Integer(2)` and, on value one, becomes
`Integer(floor(provisional/2))+1`. Each birth independently runs the Gold
constructor, draws `Float(3)+1` for collision-aware placement, sets scatter
active, and stores the supplied lifetime. After the sixth chunk, each later
birth increments the subsequent lifetime by
`round(timingScale*(Float(.04)+.01))`. Only after all chunks exist does the
registration loop give every zero-lifetime actor
`round(timingScale*Float(.25))`. Thus the constructor, chunking, placement,
delay-jitter, and zero-delay fills are one ordered shared-RNG program; only the
later painter offsets use private seed `+0x150`.

Placement helper `0x00645910` first returns the requested point if the
`Float(3)+1` placement circle clears Region collision and the earlier loose
Gold list. A blocked point enters randomized elliptical rings. Each ring uses
`trunc(pi*(ringRadius+actorRadius)/ringRadius)` samples, angular step
`360/count`, and a shared `Float(360)` starting angle; its X/Y axes are
`ringRadius` and `ringRadius*0.800000011920929`. After exhausting a ring it
updates `ringRadius += growth*actorRadius` and
`growth *= 1+Float(1)`. Earlier Gold actors use radius 15 and the same Y scale.
The helper preserves candidate and loose-actor order and contains no lattice
search.

### Sack item carrier

World `Sack` is distinct from inventory `Item_Sack`. Its held live item pointer
is at `+0x148`; bounce height/velocity live at `+0x140/+0x144`. The serializer
owns the held item as a smart pointer. On local-slot-0 proximity, the tick:

1. deletes/deactivates the carrier;
2. asks the held item's virtual name method for pickup text;
3. inserts the exact live object into `scene +0x13B8` through
   `Inventory_InsertOrStackItem`;
4. sets scene dirty byte `+0x7C`;
5. nulls `+0x148`, transferring ownership away from the carrier.

`Inventory_InsertOrStackItem (0x0055FF20)` stacks a matching Potion first. With
forced insertion it otherwise replaces the first Item_None type-7000 slot. If
all 88 visible cells hold real items, it still appends to the backing list;
pickup retires the carrier and the new item remains as native hidden overflow.

If transfer never occurs, the carrier destructor destroys the held item. Art
uses BadGuys 436..441 for bounds/effects, 442..445 for the carrier rendering,
and records 33/67 for supporting effects. The item's own Inventory icon is not
the ground carrier shell.

The isolated live pass confirmed this ownership directly: a type-2013 carrier
held a concrete type-7002 Ring pointer at `+0x148`, and that live Ring carried
runtime recipe UID 1 at item `+0x18`. The same session enumerated 47 stock
recipe definitions and materialized a type-2012 Gold actor with amount 7. See
[native-live-validation.md](native-live-validation.md).

### Bonus powerup

Bonus `+0x13C` has exact kind weights `1/4, 1/8, 5/8` for kinds 0, 1, and 2;
`+0x150` is animation phase and `+0x154` starts at 1200. The countdown is
followed by 101 float32 `.01` fade updates, retiring the untouched actor on
update 1300. Pickup checks
only local slot 0, fades/deletes the actor, and calls `0x005D5910(kind)`:

| Kind | Native result |
| ---: | --- |
| 0 | Shows `BONUS SKILL POINT` and opens the new-skill picker. |
| 1 | Builds eligible learned skills below their cap and applies the random-skill increase. |
| 2 | Shows `DAMAGE x4`, arms progression `+0x824`, and refreshes. |

Presentation uses BadGuys 122..139 and 140..157, plus records 7 and 61. The
first record-7 support pass is kind-colored at alpha `actor_alpha*.5`, scale
2.5, and glyph rotation; the second is white at alpha `actor_alpha*.25`, scale
2.25, and rotation `-glyph_rotation*.5`. Kind colors are pink `(1,.75,.75)`,
cyan `(.75,1,1)`, and gold `(.85,.73,.44)` for 0/1/2 respectively.

Birth plays `magicbook__stream`; pickup plays
`magicbookget__stream`, sets the full-screen scalar to `.35`, and arms a black
`.05` fade. Neither the actor nor its additive halos emit a world light.

### Goodie activation and staged presentation

Goodie use is automatic Region collision handling, not a keyboard action.
Registration `0x00607290` adds the authored Goodie collider through
`0x00526B40` with contact code `0x65`. Region `MyCollider` callback
`0x00646D00` projects 25 units along player heading and performs the
mask-`0x2000` front query. Helper `0x00641340` keeps candidate/source order,
uses a strict radius-50 footprint, and changes the winner only on a strictly
smaller squared distance. It accepts only a phase-zero inactive Goodie. It
recursively finds and removes one Item_Misc subtype-one Wizard Key from scene
inventory. Goodie vslot
`0x005F0E50` then plays `unlock__stream`, sets `+0x143`, clears timer `+0x144`,
and decrements the world locked-Goodie count. Without a Key, the handler plays
`voices/SAY_INEEDAKEY.wav` only when the current global tick is strictly more
than 200 after the stored warning tick, then updates that tick. The exact voice
SHA-256 is
`a2ccd30dd03eaccc7a81ea8ccbb98e506043735a59f74e882419889887aef39e`.
The same branch sends `SAY_INEEDAKEY` to narration manager `0x004FCEC0`. The
manager resolves fallback copy `I need a key!` from
`data/dialogue/narration.txt`, but the shipped WAV succeeds and owns the live
branch. No write then arms text countdown `+0x24`; renderer `0x004F6070` draws
text only while that countdown is positive. Retail therefore plays voice only
for this key, with no subtitle and no pickup notification. If the voice asset
were absent, the fallback duration would be `3*textLength+200` ticks. A
screen-space overlap is not authorization.

At tick 100, `0x0061F4C0` plays `breaklock__stream`, creates one BadGuys-52
bouncer, one normal BadGuys-15 fade at `(x,y-20)` with scale four and fade
multiplier `.75`, then exactly twenty bouncers selected from BadGuys 377..380.
Every Bouncer base first consumes `Float(3)`, `Float(20)`, `Float(360)`, and
`Float(10)`. The large child then consumes signed `Float(45)` and
`Float(1)+1`; each random child consumes `Integer(4)`, signed `Float(10)`,
`Integer(4)` (quadrant), and `Float(.5)` before manager insertion and the
immediate first tick. Later Bouncer ground contacts consume `Float(10)`,
`Integer(3)`, optional signed `Float(.2)` plus `Integer(4)` Hail-cue selection,
then `Integer(2)` damping. They use `.4` gravity ramp, `.65` restitution, stop
below `.75` rebound speed, and persist as debris until world teardown. Tick
200 changes phase and plays `opencrypt__stream`. The Goodie painter
draws the pre-100 BadGuys-33 indicator at `(x,y-40)`, not `(x+1,y-40)`, and
neither the shell nor its children own world lighting.

### Enemy drop selection

`0x0047C070` builds one candidate list from the monster-definition flags at
`+0xCC..+0xD1` (orbs, powerups, items, gold, specific items, potions), chooses
one candidate, and dispatches the category-specific factory. Its category
rolls use an actor-seeded private stream, while materializers continue on the
active shared stream. Enemy equipment selection uses `0x0046A360` over the
definition stores and random-equipment placeholders; the narrower
definition-only path is `0x0046BDE0`. Potions use `0x0046AE20`; keys use
`0x00468440`. See [`native-loot-selector.md`](native-loot-selector.md) for the
complete order, probabilities, seed writers, and dispatch constraints.

## Ownership and multiplayer consequences

The unmodified game is process-local in several important places:

- Gold pickup credits the single global scalar.
- Gold, Sack, and Bonus collision/application use local slot 0.
- Orb attraction scans four slots, but the health/mana write is slot-0-only.
- The scene owns one inventory root and one seven-sink equipment set.
- Recipe UIDs come from a mutable persisted counter.

These are native facts, not recommendations for the mod loader's multiplayer
authority model. Existing host-authorized pickup replication works around
several of them, but custom content must preserve exact item type, recipe
identity, selector, colors, stack count, and ownership transfer.

## Custom-content boundary for the later mod-download phase

What stock data can already do:

- add more named definitions and sets using the six compiled equipment types;
- reuse the 39 compiled FX kinds and eight fixed class IDs;
- select existing icon/attachment variants within each compiled selector
  range;
- combine any supported Boneyard/Lua behavior with those definitions outside
  the native parser.

What `items.cfg` alone cannot do:

- add a seventh recipe class, an eighth equipment sink, or a new ground actor;
- add an FX token/kind or change its hard-coded destination/formula;
- address an arbitrary image filename instead of a fixed Inventory/Clothes
  selector;
- expand icon/attachment counts beyond the compiled renderer tables;
- make source ordinal a stable multiplayer/save identity.

For custom art plus item data, the loader will need a deterministic content
registry that joins a mod/version identity to recipe identity and atlas
records before joining a lobby. Every participant must have the same active
definition order, selectors, FX payloads, and art bundle ABI before live items
or boneyards are materialized. Expanding rather than replacing the fixed
selector tables requires loader-owned registries/hooks at recipe clone,
inventory render, wizard attachment render, serialization, and multiplayer
snapshot boundaries.

No website download or automatic mod enablement was implemented during this
native decompilation pass.

## 2026-08-22 equipped Staff element-effect submission program

Fresh instruction recovery of `PlayerWizard::Render 0x0054BA80` establishes
that the generated Staff shaft/hands and the element effect have different
submission owners. A same-day follow-up corrected two material call-gate
mistakes in the first interpretation: the early back-angle helper call is
null-equipment-only, and the pose-9 helper call is mutually exclusive with the
ordinary front-angle call.

All direct xrefs to element helper `0x0053B1D0` are now drained. Five are in
main `PlayerWizard::Render`:

| Call | Exact gate | Equipped-Staff disposition |
| --- | --- | --- |
| `0x0054BDE4` | equipment lookup at `0x0054BDC4` returns null; heading `<=90` or `>270` | never a Staff copy |
| `0x0054C09E` | ordinary pose, phase `<=0.1`, heading `<=90` or `>270` | front-preservation copy |
| `0x0054C7FE` | pose 9, phase `<=0.1` | one pose-owned front copy at every heading |
| `0x0054C842` | ordinary pose, heading in inclusive `90..270` | ordinary front base copy |
| `0x0054C8AE` | phase `>0.1` | front pulse copy at every heading |

The remaining three xrefs, `0x00546E44`, `0x0054734E`, and `0x00547DE0`, are
mutually exclusive branches of the alternate PlayerWizard vslot-`0x20`
renderer `0x005468C0`; each branch submits the helper once. They are not extra
main-world copies.

For an equipped Staff in the main renderer, the exact copy counts are:

- ordinary pose, phase `<=0.1`: one copy at every heading except exact 90
  degrees, where the inclusive back/front tests submit two;
- ordinary pose, phase `>0.1`: one copy at back headings and two at front
  headings (`90..270` inclusive);
- pose 9: exactly one copy at every heading, below/equal or above the phase
  threshold.

There is no equipped-Staff back-base copy. `0x0054BDCE` is `TEST EAX,EAX` and
`0x0054BDD0` is `JNZ 0x0054BDE9`, so every present Staff skips
`0x0054BDE4`. Similarly, pose 9 reaches `0x0054C7FE`, while ordinary
`0x0054C842` is in the opposing branch. A port that derives either call from
heading alone over-submits complete element painters and visibly enlarges or
saturates the orb.

The exact threshold remains the double `0.10000000149011612` at
`0x007849E8`. `+0x248` feeds distinct colored-sprite helper `0x0053B680` and
does not authorize another element-effect copy.

`0x0053B1D0` dispatches Ether, Fire, Air, Water, and Earth through their five
already-catalogued element painters. Its Staff-type branch
`0x0053B261..0x0053B318` uses the Staff record's virtual point-1 socket and,
at `0x0053B2DB..0x0053B2F0`, passes exact scale
`actorScale * (1 + 10 * +0x268)`. The doubles are `10` at `0x007DE810` and
`1` at `0x007DE820`. That scale is not the regression and must not be reduced
to compensate for an invalid extra copy.

The adjacent helper branches are distinct, but they are not silent. A present
non-Staff item follows `0x0053B321..0x0053B412` and applies an additional
`0.6000000238418579` scalar from `0x0078C6F0`; the null-item path is
`0x0053B431..0x0053B66B` and owns separate hand/randomized placement. Neither
branch authorizes the null-equipment `0x0054BDE4` call for a Staff. Staff
selectors `0..5` share the same Staff call graph. Death/alternate drive byte
`+0x160` suppresses the helper.

Evidence is the pinned 4,723,200-byte retail `SolomonDark.exe` (SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred base `0x00400000`), re-hashed 2026-08-22, and fresh Ghidra 12.0.3
read-only decompilation/instructions for `0x0053B1D0`, `0x005468C0`, and
`0x0054BA80`, including every xref and the ranges above. Confidence is high;
no main-world equipped-Staff call, branch, element, selector, pose, phase, or
teardown member remains unknown.

## 2026-08-26 selected-primary Staff element-effect dispatch

The equipped-Staff report above recovered where and how often the helper is
submitted, but stopped before the helper's downstream selected-spell switch.
That omission matters once one wizard knows more than one category-1 primary:
the orb program is selected on every draw from the current primary, not fixed
to the wizard's creation element.

Fresh read-only Ghidra recovery used the canonical `SolomonDark` project,
program `SolomonDark.exe`, and retail image identity recorded above. All
eight xrefs to `0x0053B1D0` remain the five main-world and three alternate
renderer calls already inventoried. The helper first resolves the current
primary from the actor override at `PlayerWizard +0x21C` when present, or
from `DAT_00819E84[playerSlot + 12]` otherwise
(`0x0053B1F2..0x0053B228`). A negative selection returns without drawing.
The shared painter `0x00539B80` independently re-reads that same source at
`0x00539B8D..0x00539BD1` and
`0x00539E2D..0x00539E71` before dispatching:

| Selected primary | Painter program |
| ---: | --- |
| `8` | Ether `0x00535A30` |
| `16` | Fire `0x005360C0` |
| `24` | Air `0x00536380` |
| `32` | Water `0x005370D0` |
| `40` | Earth `0x005374C0` |
| `52` | read current build `progression +0x750` and enter the complete `1000..1014` table |
| `80`, another positive ID, or default | no ordinary element painter |
| negative/unselected | helper returns before attachment or painter work |

The complete row-52 program table is:

| Build | Ordered native program |
| ---: | --- |
| `1000` | Fire, then Ether under the saved color state with alpha `currentAlpha * 0.25` |
| `1001` | Water, then Ether under the same quarter-alpha state |
| `1002` | Air, then Ether under the same quarter-alpha state |
| `1003` | orange `(1,.5,0,1)` Earth painter, gold `(1,.75,0,1)` record-110 core work, then the two-sprite Air companion `0x00536C10` |
| `1004` | Water, then Air companion `0x00536C10` |
| `1005` | randomized green-channel Steam compositor `0x00537860`: BadGuys `2002..2007` plus record `110` |
| `1006` | magenta `(1,.5,1,1)` Earth at `0.75 * scale`, then an additive full-scale Earth copy |
| `1007` | Earth, then Fire |
| `1008` | Earth, then Water |
| `1009` | green `(.5,.75,.5,1)` record `15` at the native rotating/pulsing scale, then Air at `1.25 * scale` and alpha `.5` |
| `1010` | Ether twice |
| `1011` | Fire twice |
| `1012` | Water twice |
| `1013` | Air twice |
| `1014` | Earth twice |

Rows `1000..1009` are the ten player-selectable mixed builds. Rows
`1010..1014` are native internal pure-build programs; they are real table
members even though the retail player acquisition path does not expose them as
learned Weld recipes. Planewalker temporarily selects Plane Orb `80`, so
the ordinary colored element effect is absent while its separate Plane Orb
actor owns primary presentation. Returning from Planewalker restores the saved
selection and therefore restores its orb program on the next draw.

The program inherits the already recovered Staff/Wand/empty-hand socket,
submission count, `1 + 10 * +0x268` pulse scale, main/alternate renderer
branches, death suppression, and color-state push/pop lifetime. Switching
selection does not reconstruct the PlayerWizard, change robe/hat creation
element, or create an independent world-sorted orb actor. Confidence is high:
the current-primary source, complete switch/jump table, painter call order,
color/alpha constants, all authored rows, assets, and default branches are
instruction- or catalog-derived; no runtime address or injected observation is
used.
