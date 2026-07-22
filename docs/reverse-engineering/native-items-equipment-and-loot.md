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
| Hat | `0x005758F0` | Dynamic primary/secondary selector tables at `DAT_00B2E9A4` and `DAT_00B2E9B4`; both colors apply. |
| Robe | `0x00577DA0` | 5..10, 220..315, and 1588..3243 across pose/selector tables; both colors apply. |
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
| 27 `FX_MAXMAGICSTORM` | Sets `0x0002`. |
| 28 `FX_MAXRINGOFFIRE` | Sets `0x0004`. |
| 29 `FX_MAXGOLEM` | Sets `0x0008`. |
| 30 `FX_MAXRINGOFICE` | Sets `0x0010`. |
| 31 `FX_MAXEMBERSTOIMPS` | Sets `0x0020`. |
| 32 `FX_MAXDISINTEGRATION` | Sets `0x0040`. |
| 33 `FX_MAXETHERCHARGE` | Sets `0x0080`. |
| 34 `FX_MAXHARDEN` | Sets `0x0100`. |
| 35 `FX_MAXROCKSURGE` | Sets `0x0200`. |
| 36 `FX_MINDBLAST` | Sets `0x0400`; emits the level-up mindblast behavior. |
| 37 `FX_MAXWELD` | Sets `0x0800`; native display name is `Energize Weld Components`. |
| 38 `FX_WELDEFFECT` | Updates scalar `+0x8E0`: flat adds magnitude, `*` multiplies, percent adds `magnitude/100` to the scalar. |
| 39 `FX_WELDCALLING` | Sets `0x1000`; native display name is `+Bias Skills for Welding`. |

The percent implementation for Weld Effect is deliberately unusual: it adds
the fractional value to the scalar rather than multiplying by `1 + N/100`.
The distinction between bits `0x800` and `0x1000` also corrects the earlier
provisional welding label; see [spell-welding.md](spell-welding.md).

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
object's orb-pull radius. Outside pickup range it accelerates toward the
candidate. Inside range it creates the collection effect, scales the reward
from remaining value, and deletes the actor. The stock resource write is
gated to slot 0: health calls `0x0052AC80`, mana calls `0x0052B150`.

Art is BadGuys 434/435 for the two rendered orb kinds, with BadGuys 15 and
related transient effect records used during animation/collection.

### Gold

Gold owns tier `+0x13C`, amount `+0x140`, lifetime `+0x144`, animation state
`+0x148`, and transient motion fields through `+0x158`. `0x005E13C0` maps
amount `<3`, `<5`, `<8`, or larger to tiers 0..3. Pickup checks only local
slot 0, deletes the actor, shows `%d GOLD`, and credits the process-global gold
scalar through `0x005A7C60(amount, false)`.

The renderer selects BadGuys 188..197 and 198..201 by tier/state; record 73 is
also used by the render path and record 83 by the tick effect. `0x0046AA90`
splits a gold reward into chunks no larger than 25, perturbs later chunk
lifetimes/positions, and registers every actor in the world.

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

Bonus `+0x13C` is randomized among 0..2 with a native reroll that biases one
branch; `+0x150` is animation phase and `+0x154` starts at 1200. Pickup checks
only local slot 0, fades/deletes the actor, and calls `0x005D5910(kind)`:

| Kind | Native result |
| ---: | --- |
| 0 | Shows `BONUS SKILL POINT` and opens the new-skill picker. |
| 1 | Builds eligible learned skills below their cap and applies the random-skill increase. |
| 2 | Shows `DAMAGE x4`, arms progression `+0x824`, and refreshes. |

Presentation uses BadGuys 122..139 and 140..157, plus records 7 and 61.

### Enemy drop selection

`0x0047C070` builds one candidate list from the monster-definition flags at
`+0xCC..+0xD1` (orbs, powerups, items, gold, specific items, potions), chooses
one candidate, and dispatches the category-specific factory. Definition-backed
equipment selection reaches `0x0046BDE0`; potions use `0x0046AE20`; keys use
`0x00468440`; the owner vtable supplies item and potion carrier creation. See
[`native-enemies.md`](native-enemies.md) for the exact candidate/mask policy.

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
