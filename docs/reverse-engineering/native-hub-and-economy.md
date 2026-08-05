# Native hub, trader economy, and Solomon Dig

Status: **G8 closed** for retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

This document specifies what the between-runs hub is and what it does. The live
recording is
[`hub-economy-goldens.json`](../../tests/fixtures/webgame/hub-economy-goldens.json),
SHA-256 `770fa976c9faea7eab731ba6d40b3798c548546dfec6a62780862b0b59c3ae3f`.
It contains a five-region entity census, three independently launched trader
states, 24 paid Dowsing rolls, and eight Solomon Dig trials.

G12/rendre owns how these rooms and actors are drawn. Its
[`native-scene-composition.md`](native-scene-composition.md) is the renderer
contract for layer order, atlas and sprite resolution, parallax, decor, fog,
lighting, tint, sort keys, camera transforms, and draw positions. This document
does not duplicate those rules. Positions below are semantic world/collision
positions and interaction targets. G13/flowre owns the fade, destruction,
construction, load barrier, and failure behavior of transitions between the hub
and a run. G8 owns the state handed across that boundary and the control which
requests it.

No gameplay behavior was changed for this investigation. The only new native
surface is the opt-in debug call
`sd.debug.call_stdcall_u32_u32_ret_u32(address, arg0, arg1)`. It validates that
the resolved address is executable, invokes the retail two-argument `stdcall`
under the existing structured-exception boundary, and returns the native
`uint32_t` result, including zero. It was necessary because the existing Lua
execution probes could not call Hagatha's two-argument price function
`0x005A7CA0`. It is a probe seam, not a hub implementation or mutation path.

## System summary

The hub is five compiled `Region` subclasses. A participant enters one region
at a time; the Courtyard is the shared outdoor space and the other four are
interiors. Region actors and props are constructed again when their region is
entered. The participant's gold, backpack, equipment, progression, Hagatha
flags, map unlocks, selected run, and Luthacus storage live outside those region
objects and survive region replacement.

There is no generic friendly-NPC recipe behind the stock hub population. The
named people are compiled factory types with individual dialogue/service
callbacks. Roaming Students are a separate ambient class and are not
interactable. The start-run affordance is a Courtyard UI control, not a portal
actor; factory type 5021 named `Portal` is an enemy-spawning run actor and must
not be used for hub entry.

The economic loop is:

```text
finished run
  -> retain eligible equipment/backpack contents in a named Sack
  -> optionally collect Last Word ground Sacks and Gold
  -> write participant-private gold/inventory/progression/storage
  -> rebuild hub and Fomentius/Hagatha catalogs
  -> spend participant gold or move participant items
  -> choose an unlocked Boneyard
  -> next run reads the same participant-private state
```

Solomon `Dig` is not a mining or excavation economy. `Solomon_Dig` is the name
of the run-intro NPC (factory type 5009). Completing his dialogue releases the
participant's controls and arms the Arena; it consumes no item or gold and
produces no loot. Eight live trials all yielded exactly that one state change.

## Hub layout and entity census

### Region topology

The fixed region classes were previously recovered in
[`native-regions-npcs-and-world-props.md`](native-regions-npcs-and-world-props.md).
The G8 capture re-censused all five through live region switches:

| Region index | Factory type | Class | Fixed gameplay population in the live normal hub |
| ---: | ---: | --- | --- |
| 0 | 4001 | Courtyard | Six named actors, eight collision obstacles, one statue, roaming Students; Tyrannia is optional |
| 1 | 4002 | Mortuary | Memorator, ten interactive Paintings, and ten paired collision props |
| 2 | 4004 | Library | Librarian, Shlorio/Dowser, and four collision props |
| 3 | 4003 | StoreRoom | Three collision props; no named NPC |
| 4 | 4005 | Office | Arch Chancellor and one collision prop |

Every row also contains the local participant actor (`type 1`). Its recorded
position is a live post-entry sample, not a fixed layout constant, so it is not
part of the tables below.

### Courtyard

The normal-hub named actors are fixed at these world centers. `r` is the native
actor collision/click radius recorded by `sd.world.list_actors()`.

| Type | Person | Center `(x, y)` | `r` | Gameplay role |
| ---: | --- | ---: | ---: | --- |
| 5001 | Hagatha / `PerkWitch` | `(1340, 280)` | 15 | Charms and curses (`PerkShop`) |
| 5004 | Fomentius / `PotionGuy` | `(1397, 664)` | 30 | Potions and useful items (`Shop`) |
| 5003 | Annalist | `(895.5, 455.5)` | 8 | Dialogue and Boast service |
| 5005 | Luthacus / `ItemsGuy` | `(1700.5, 449.5)` | 25 | Participant's Scavenged Goods storage |
| 5007 | Tyrannia | one of three builder placements; live `(669, 705.5)` | 10 | Optional dialogue-only visitor |
| 5008 | Teacher | `(576.5, 710.5)` | 25 | Progression-gated spell service |

The collision scenery is gameplay state even though G12 owns its drawing:

| Type | Radius | Centers |
| ---: | ---: | --- |
| 2007 `CollegeObstacle` | 40 | `(1458.5,320.5)`, `(955.5,239.5)`, `(749.5,162.5)`, `(1893,490)`, `(1746,534)`, `(1840,715)`, `(628,215)`, `(956,169)` |
| 2008 `CollegeStatue` | 50 | `(961,834)` |

Students (type 5002) are ambient, collision-bearing wanderers. The final live
census happened to contain six, but independent hub launches have contained
five through eleven. Their constructor `0x00501B80` consumes both native
`Integer` and the still-un-goldened G1 `Float` primitive to choose movement,
appearance, radius, and behavior fields. Their interaction vtable slot `+0x68`
is the no-op `0x0055C300`; they have no talk or service target. Their count,
positions, radii, and appearance are therefore regenerated observations, not
portable layout constants.

Tyrannia is also regenerated. The normal builder `0x0050B720` creates her only
when `Integer(3) == 1`, then a second `Integer(3)` chooses one of three variants
or placements. The final census is one successful realization, not a guarantee
that every Courtyard contains her.

### Mortuary

Memorator (type 5017) stands at `(628,770)`, radius 25. Ten Paintings (type
5018) are clickable, radius 15. Field `Painting+0x174` selects the eulogy line:

| World center | Eulogy index | World center | Eulogy index |
| ---: | ---: | ---: | ---: |
| `(512,697)` | 0 | `(350,683)` | 1 |
| `(673,683)` | 100 | `(744,540)` | 3 |
| `(590,540)` | 4 | `(434,540)` | 5 |
| `(279,540)` | 6 | `(354,400)` | 7 |
| `(512,400)` | 8 | `(670,400)` | 9 |

Each Painting is paired with a noninteractive type-2041 `CustomObject` collision
prop of radius 40, two world units above it: `(512,695)`, `(350,681)`,
`(673,681)`, `(744,538)`, `(590,538)`, `(434,538)`, `(279,538)`,
`(354,398)`, `(512,398)`, and `(670,398)`. The Painting callback
`0x00506190` finds the room's Memorator and dispatches `SAY_EULOGY_<index>`;
the value 100 is intentional and must not be normalized into the missing index
2.

### Library, StoreRoom, and Office

| Region | Actor/prop | Center | Radius | Role |
| --- | --- | ---: | ---: | --- |
| Library | Librarian 5013 | `(512,595)` | 55 | Books service |
| Library | Shlorio / Dowser 5016 | `(900,642.5)` | 25 | Paid Dowsing offers |
| Library | `CustomObject` 2041 x4 | `(239.5,788)`, `(258.5,678.5)`, `(762,732.5)`, `(831,620.5)` | 40 | Collision scenery |
| StoreRoom | `CustomObject` 2041 x3 | `(538,324)`, `(537.5,434)`, `(536,542.5)` | 40 | Collision scenery; no service |
| Office | Arch Chancellor 5012 | `(514,467)` | 55 | Dialogue |
| Office | `CustomObject` 2041 | `(517.5,681)` | 40 | Collision scenery |

### Alternate story/tutorial population

`0x00513BE0` is a second fixed-region builder selected by
`Gameplay+0x1CD8`. It is not the normal live state captured in the fixture, but
an implementation must preserve its statically recovered population:

- Courtyard phase 0 writes `Gameplay+0x1CDC = 1` and creates the Annalist,
  Fomentius, and Luthacus `_0` dialogue trees with their ordinary service
  actions. Phase 1 writes `Gameplay+0x1CDD = 1`, creates standing Arch
  Chancellor type 5024, and uses Luthacus/Annalist `_1` dialogue.
- The alternate Courtyard can generate named Luthacus Sacks. Total generated
  item count is `Integer(2)+2` (2 or 3); `Integer(total)+1` splits the first
  Sack's count from the remainder; two different names are selected from a
  15-name table; item filling delegates to `0x004645B0`. That downstream item
  selector belongs to G7 and is not guessed here.
- The alternate Library uses `_0` dialogue and writes booleans in the table at
  `Gameplay+0x22F8` for indices `0,2,8,11,15,17,25`.
- Office phase 0 contains Polisher type 5011 plus Arch Chancellor type 5012 and
  `_0` dialogue. Phase 1 contains desk Arch Chancellor type 5023.
- Mortuary retains Memorator and Paintings; StoreRoom has no named actor.

The semantic meaning and complete reachability conditions for
`Gameplay+0x1CD8` values are listed under *Not Yet Reversed*. The facts above
pin what the alternate builder does once selected.

### Persistent versus regenerated

| State | Lifetime |
| --- | --- |
| Five region classes, fixed named-NPC coordinates, Paintings, and collision props | Reconstructed from compiled builders on region entry |
| Student population and fields | Regenerated; active-stream `Integer` and G1 `Float` consumers |
| Tyrannia presence/variant | Regenerated; two active-stream `Integer(3)` calls |
| Fomentius catalog | Rebuilt at game startup and after a completed run; retained while merely reopening the shop |
| Hagatha catalog | Rebuilt beside Fomentius from current participant progression; no RNG |
| Shlorio result list | Created by each paid DOWSE action; destroyed on Done or successful purchase |
| Luthacus Scavenged Goods | Participant-private persistent storage, not region stock |
| Gold, active backpack/equipment, progression, Hagatha ownership/first-mix flags, map unlocks/selection | Participant/profile state; survives hub region construction |

## Interaction model (G14 intents)

G14 has landed as
[`intent-schema.json`](../../webgame-contracts/intent-schema.json). G8 does not
define another input schema. A hub producer emits G14's existing forms:

```json
{"kind":"interact","target":"hub.npc.hagatha","phase":"press"}
{"kind":"interact","target":"hub.npc.hagatha","phase":"release"}
{"kind":"menu_nav","command":"confirm","phase":"press"}
{"kind":"menu_nav","command":"confirm","phase":"release"}
```

`menu_nav.command` may be `up`, `down`, `left`, `right`, `confirm`, `back`,
`next`, or `previous`. G14 owns mouse/controller event routing and click
precedence; G11 owns focus order inside menus. G8 assigns semantic target names
and resulting hub actions.

### Hit and dialogue lifetime

For named actors and Paintings, the world hit target is the actor circle in the
layout tables. The native common NPC action at vtable slot `+0x68`
(`0x00501800` for Hagatha and the corresponding overrides for other named
actors) allocates a 400-byte dialogue object from `NPC+0x154`, attaches it
through the active game UI owner, and sets `NPC+0x170 = 1`.

While engaged, common update `0x00505010` dismisses the interaction when the
participant distance satisfies:

```text
distance_squared > 5 * actor_radius^2 + 1500
```

The constants are the binary doubles at `0x007DE8D8` (`5`) and `0x00784D00`
(`1500`). A dialogue also closes when its line/button flow completes or when
G14 `menu_nav.back` is pressed. A service screen closes through its Done/back
control; the underlying NPC dialogue is not a second simultaneously actionable
surface. Run entry is a UI target and has no world radius.

### Canonical targets and actions

| G14 `interact.target` | Opens / talk flow | Service action and gate | Close |
| --- | --- | --- | --- |
| `hub.npc.hagatha` | `WITCH_INTRO`, then `WITCH_Q` | “Buy Charms and Curses” -> `!BUYPERKS`; PerkShop at `Gameplay+0x101C`, catalog `+0x15FC` | back, dialogue completion, distance, or shop Done |
| `hub.npc.fomentius` | `POTIONGUY_INTRO` | `!BUYPOTIONS`; Shop at `+0x1184`, catalog `+0x15A4` | same |
| `hub.npc.annalist` | `ANNAL_INTRO` | Boast -> `!BOAST`; action bubble suppressed when `DAT_0081A3CA` is set | same |
| `hub.npc.luthacus` | `SCAVENGER_INTRO` | Examine Items -> `!INVENTORY`; action bubble suppressed by `DAT_0081A3CC` | same |
| `hub.npc.tyrannia` | `ENFORCER_INTRO` | None; actor itself exists only on the 1-in-3 builder roll | dialogue completion, back, distance |
| `hub.npc.teacher` | `TEACHER_INTRO`, then `TEACHER_Q` | “Per$uade” -> `!SPELLS`; actor is created only when gate `0x004736D0` succeeds | back, completion, distance, service Done |
| `hub.npc.memorator` | `MEMORATOR_INTRO`, `MEMORATOR_Q1`, `MEMORATOR_Q2`, dismiss | None | dialogue completion, back, distance |
| `hub.painting.<eulogy_index>` | Memorator line `SAY_EULOGY_<index>` | Painting must be the exact room actor; valid suffixes are `0,1,100,3,4,5,6,7,8,9` | line completion or back |
| `hub.npc.librarian` | `LIBRARIAN_INTRO` | Books -> `!BOOKS` | back, completion, service Done |
| `hub.npc.shlorio` | `DOWSER_INTRO`, then `DOWSER_Q` | Dowse -> `!DOWSE`; paying the current fee produces an offer list | Done/back or successful offer purchase |
| `hub.npc.arch_chancellor` | `ARCH_INTRO`, then `ARCH_Q`, dismiss | None in the normal Office | dialogue completion, back, distance |
| `hub.run_entry` | Stock `MapPicker` | Courtyard control at `Gameplay+0xE00`; connected non-authority clients cannot activate it | `menu_nav.back`, invoking the toggle again, or successful selection |

Hagatha's own action bubble is suppressed by `DAT_0081A3CB`. The service
dispatcher `0x00514A20` refuses to open a shop while the owning room fade field
`+0x8E48` is positive. Roaming Students and all type-2007/2008/2041 scenery are
noninteractive; collision with them does not emit an `interact` intent.

### Run entry is a control, not a portal

`0x00514A20` compares the activated UI control with `Gameplay+0xE00` and
calls `0x0050E5E0`. That function opens `MapPicker`, or begins the existing
picker's close when invoked again. The picker scans exactly 50 unlock bytes at
`Gameplay+0x1CDC`; choosing index `i` writes
`data\levels\story<i>.boneyard` into the native String at
`Gameplay+0x1BD8`. See [`map-picker.md`](../re/map-picker.md) for the exact
entry and cancellation contract. G13 owns the ensuing transition lifecycle.

## Trader economy

### Currency and common purchase transaction

The currency is integer gold. Retail's local profile root begins at
`0x0081A330`; its gold field is `+0x58`, absolute `DAT_0081A388`. That global
shape is single-player-shaped, but its portable meaning is **the purchasing
participant's gold ledger**.

The common Shop purchase callback `0x0056BF70` reads the selected item's exact
integer price at `item+0x5C`. On sufficient funds it calls the gold adjuster
`0x005A7C60` with `-price` and `false`, transfers/stacks the item into the
buyer's active backpack, and removes one stock object. On insufficient funds it
returns failure without a partial transfer. Fomentius, Hagatha, and Shlorio are
buy-only: there is no sell price, buyback, cancellation refund, or later refund
path. Closing a catalog does not refund an already completed purchase.

One object in a native Shop list is one unit of stock. The fixture groups
identical Fomentius objects into `{quantity}` solely to make the recording
readable; `stock_count` retains the ungrouped object count.

### RNG provenance and portability

All identified economic integer rolls consume the native active stream through
`0x00401170`; the active object pointer is `DAT_00818B08`. Its state is:

```text
+0x00 index A
+0x04 index B
+0x08..+0xE0 55 state words
+0xE4 Float divisor (100000 in every G8 capture)
```

G1 proved that construction-time streams are seeded from elapsed unpaused app
ticks:

```text
construction_seed = App[+0x28] * 0xEF3
```

The Lua pipe cannot become runnable until after the initial hub constructors
have seeded and advanced the stream. Accordingly, G8 does **not** pretend that
`sd.rng.set_seed` controls trader stock; the recorder never calls it. For each
Fomentius replay, the recorder snapshots all 58 dwords immediately before
calling the retail generator and traces every identified call back to that exact
stream object. The three pre-generation state hashes are:

```text
705c3e146ca2e660efbc00335d3f2e72eb71babbe878b0ecf2e6b4912c45501e
3a6dccd560dfccdda14a2ed8eb7196682a57fd4cee501980e42ce40d83248efa
7fb4719304e51481bc0af05bcce8b5f9a5e51c24b75a288789e4400895097289
```

The construction app tick and seed are therefore `null` in the fixture, and
`portable_from_seed_alone` is false. A browser save/replay must carry either the
full stream state at each economic generation boundary, or the construction app
tick **plus the exact ordered history of every earlier consumer**. The app tick
alone is insufficient after advancement. Student construction is stricter: it
also uses G1's Float primitive, whose three float32 rounding points and signed
two-word cost are statically known but still have no live goldens. Do not turn
the captured Student coordinates into a seeded fixture.

No price, stock quantity, or direct Dig yield below uses native Float. Shlorio
does call `Float(0.1,false)` at `0x0055FDE9`, but only for a presentation effect
after the result list is built. That effect remains dependent on the open G1
Float golden; it is not allowed to perturb the recorded offer count, identity,
or price.

### Fomentius: fixed catalog with rolled quantities

Generator `0x005C8960` clears/rebuilds Fomentius's list, then performs these
nine positive integer calls in this exact order:

| Draw | Type/variant | Offer | Price | Quantity / gate |
| ---: | --- | --- | ---: | --- |
| `Integer(3)` | 7001/0 | Health Potion | 150 | result `+2`: 2..4 |
| `Integer(6)` | 7001/1 | Mana Potion | 75 | result `+2`: 2..7 |
| `Integer(3)` | 7001/5 | Rejuvenation Potion | 200 | 0..2; zero omits the offer |
| `Integer(2)` | 7012/0 | Dye Kit | 300 | result `+2`: 2..3 |
| `Integer(18)` | 7012/1 | Wizard Key | 1200 | one only when result equals 1 |
| `Integer(2)` | 7008/0 | Item Sack | 50 | result `+1`: 1..2 |
| `Integer(3)` | 7001/3 | Antidote | 100 | result `+1`: 1..3 |
| `Integer(8)` | 7001/2 | Wizard Chug | 2500 | one only when result equals 3 |
| `Integer(8)` | 7001/4 | Mind Chug | 1500 | one only when result equals 3 |

Thus the ungrouped catalog contains 8..24 objects. Wizard Key has probability
`1/18`; each Chug has probability `1/8`; the three rare tests are independent
draws. There is no progression gate in this generator. The traced return sites
are, in order:

```text
0x005C89B4 0x005C8A33 0x005C8AB2 0x005C8B31 0x005C8BA9
0x005C8C1A 0x005C8C9F 0x005C8D24 0x005C8D97
```

`0x005CFA80` calls the generator during gameplay startup and `0x005CF920`
calls it after switching back from a completed run. Opening and closing
Fomentius without either boundary does not restock. Buying removes units only
from the buyer's process-local catalog.

### Hagatha: progression-gated deterministic catalog

Hagatha shares generator `0x005C8960` but consumes no RNG. It reads the catalog
limit through `*(DAT_008199CC)+0xF0C`; all three live states read 29. It loops
selectors less than `limit-1`, so the live range is 0..27, and explicitly skips
selector 8. For every other selector:

- `progression+0x7CC+selector == 0` creates one visible type-7009 `Item_Perk`;
- a nonzero owned byte creates a type-7000 placeholder instead of an offer;
- selector 8 is absent even when unowned;
- a nonempty participant bulk-selector list at profile `+0x60/+0x64` appends
  one type-7009 offer with selector `-1`.

The individual price function is `0x005A7CA0`. Its second argument does not
change the result. With `base[selector]` from the native table and the
participant's first-mix byte at absolute `0x0081A39C+selector`:

```text
individual_price(selector) =
    base[selector]                    if first_mixed[selector] != 0
    3 * base[selector]                otherwise

bulk_price = floor(sum(individual_price(member)) / 2 + 0.5)
           = ceil(sum(individual_price(member)) / 2)
```

The complete individual catalog is:

| Selector | Offer | Base price | First purchase price |
| ---: | --- | ---: | ---: |
| 0 | LIFE CHARM | 200 | 600 |
| 1 | MANA CHARM | 200 | 600 |
| 2 | SPEED CHARM | 250 | 750 |
| 3 | ITEM CHARM | 1000 | 3000 |
| 4 | GOLD CHARM | 500 | 1500 |
| 5 | SEEKER'S CHARM | 200 | 600 |
| 6 | REVELATION CHARM | 800 | 2400 |
| 7 | CHEAT DEATH CHARM | 5000 | 15000 |
| 8 | PERKY CHARM | 1500 | 4500, but never emitted by this builder |
| 9 | SCATTER CURSE | 150 | 450 |
| 10 | WAR CHARM | 800 | 2400 |
| 11 | CURING CHARM | 250 | 750 |
| 12 | THE LAST WORD CHARM | 500 | 1500 |
| 13 | SPELLWELDER'S CHARM | 2000 | 6000 |
| 14 | WEIRD CASTER CHARM | 2500 | 7500 |
| 15 | DRINKER'S CHARM | 1000 | 3000 |
| 16 | GLASS CANNON CURSE | 1000 | 3000 |
| 17 | SORCEROR'S CHARM | 3000 | 9000 |
| 18 | FOCUS CHARM | 1000 | 3000 |
| 19 | DISFIGURING CURSE | 3000 | 9000 |
| 20 | BARE HANDS CHARM | 500 | 1500 |
| 21 | SPLIT MIND CHARM | 4000 | 12000 |
| 22 | CURSE BOSSES | 2000 | 6000 |
| 23 | ARCANE ATTRACTOR CHARM | 2000 | 6000 |
| 24 | SERENDIPITY CHARM | 1000 | 3000 |
| 25 | REVERIE CHARM | 1000 | 3000 |
| 26 | BRUTE'S CHARM | 3000 | 9000 |
| 27 | TONIC | 1000 | 3000 |

A successful purchase spends the buyer's gold, applies the selector to that
participant's progression, and records the first-mix flag. Owned selectors are
not visible offers on the next catalog construction. Every visible individual
row has quantity one; there is no timed restock and no shared scarcity. The
perk effects are catalogued in
[`native-hagatha-perk-catalog.json`](native-hagatha-perk-catalog.json); G6 owns
their complete combat/progression semantics. For the economic gate, Tonic
increases charm/curse capacity in steps of three up to nine, so at most two
capacity increases apply.

The three live progression states prove the important branches: all-unmixed
fresh stock (27 visible, triple prices), selector 0 previously mixed (Life Charm
200 while untouched offers remain triple), and selector 12 owned (one
placeholder, 26 visible offers).

### Shlorio: paid rolled offers

Shlorio's Dowsing fee is the runtime integer at `DAT_0081A430`. The retail image
value is zero, but all three clean live processes exposed 650 before their first
G8 roll. No save read or unambiguous initializer for that 650 was recovered; it
is therefore explicit runtime state in a port, not a value to regenerate from a
claimed seed.

Pressing DOWSE in callback `0x0055FAF0`:

1. rejects without mutation when participant gold is below the current fee;
2. spends exactly that fee through `0x005A7C60`;
3. calls the native Float presentation effect once;
4. chooses `Integer(2)+3`, producing three or four offer slots;
5. with no target item, repeatedly draws `Integer(47)` from the 47-entry native
   prototype catalog through `0x00554A70`, rejects ineligible or duplicate
   recipe UIDs through `0x00554A10`, and gives up a slot after 100 attempts;
6. assigns each accepted offer
   `(Integer(15)+100)*50`, exactly 5000..5700 in steps of 50.

The final 24 untargeted rolls all produced three or four unique eligible offers,
one `Integer(15)` price draw per offer, and zero or more retry
`Integer(47)` draws. Tracing proves every count, selector, price, and the one
presentation Float call used the captured active stream object. Each fixture
roll includes the complete before/after state, return addresses
`0x0055FE2A`, `0x00554A94`, `0x0055FE8E`, and price binding function
`0x0055ACB0`.

If a target item exists at DowsingShop `+0x344`, the static branch first invokes
the set-matching helper `0x00554AF0` twice, then invokes type-matching helper
`0x00554CE0` `Integer(2)+3` times. Both helpers scan the same 47-entry prototype
catalog and use `0x00554A10` for eligibility/duplicate rejection. The exact
accepted cardinality for this targeted branch is not inferred from the call
count; see *Not Yet Reversed*.

The result list is screen-local stock, one unit per offer. Done calls the reset
path `0x0055EF40` and closes it. Buying an offer runs the common purchase first;
on success callback `0x0056D110` clears the list and rolls the **next** fee:

```text
next_dowsing_fee = (Integer(10) + 10) * 50   // 500..950
```

Merely paying DOWSE does not reroll the fee. The G8 trials intentionally bought
no result item, so their 650 fee stayed fixed across all eight rolls per
process. There is no sell or refund path: closing discards offers, not the fee
already paid.

### Luthacus: storage, not a merchant

Luthacus's `InventoryShop` (`0x004F59A0`, transfer callback `0x0056CD00`)
moves objects between the participant's active backpack and persistent
Scavenged Goods storage at profile `+0x8C` (absolute pointer
`DAT_0081A3BC`). It neither prices items nor changes gold. There is no random
inventory, stock limit, restock, sale, or refund. The apparent catalog is the
buyer's own storage, including retained Sacks from earlier runs.

This owner-private behavior is already live-proven in
[`inventory-item-investigation.md`](../inventory-item-investigation.md#hub-inventory-shop-ownership-boundary):
moving a potion into and out of Luthacus changed only the initiating
participant's native backpack/storage and published that participant's
inventory revisions.

### Other service surfaces

Annalist (`!BOAST`), Librarian (`!BOOKS`), and Teacher (`!SPELLS`) are hub
upgrade/progression services but not gold-stock traders in the paths recovered
here. Their content tables and exact progression mutations belong to G6. G8
pins their actors, gates, trigger targets, and open/close behavior; it does not
invent offer rows or prices for services whose content path was not reachable
through the existing probes.

## Solomon Dig and the upgrade loop

### What Dig is

`Solomon_Dig` is factory type 5009, constructor `0x00481C20`, dispatcher
`0x0048A8B0`. It is an Arena prelude actor. Lantern type 5010 is a separate
run prop with tick `0x005FF010`; neither object is a hub currency source.

The existing multiplayer ownership analysis in
[`dig-npc-movement-lock-2026-07-28.md`](../design/dig-npc-movement-lock-2026-07-28.md)
established the principal fields and paired input lock. G8 adds the economic
answer and a fresh eight-trial distribution:

| Actor field | Meaning |
| ---: | --- |
| `+0x220` | interaction state |
| `+0x2A0` | a gameplay participant has been acquired |
| `+0x2A4` | selected gameplay slot |
| `+0x218` | movement/animation accumulator used by the rail |

The state machine is:

| State | Native body | Mechanical result |
| ---: | ---: | --- |
| 0 | `0x00481FC0` | scans up to four gameplay slots; acquisition uses the native proximity rail and records slot/acquired fields |
| 1 | `0x0047D0F0` | faces/approaches the selected participant, locks the local initiator through `0x005C7300(...,1,0)` and `0x005C7390(...,1,0)`, queues narration |
| 2 | `0x0047D450` | waits for the dialogue pointer and queued-line count to clear; restores both controls; writes `Arena+0x902A = 1`; advances to state 3 |
| 3 | `0x0047D570` | starts the combat prelude and retreat setup |
| 4 | `0x004857B0` | retreat movement; eventual actor retirement is presentation/world lifecycle, not a reward |

The first-run greeting chooses `SAY_SOLOMON_HELLO<Integer(4)>`. That draw is
dialogue variation, not a yield roll. It uses the active stream, but the G8
probe could not arm before Arena construction and did not record a portable
pre-greeting state. A port which must replay the exact line must serialize the
chosen variant or the full stream state; it must not use `sd.rng.set_seed` as a
substitute.

### Consumption and yield distribution

The G14 action is proximity acquisition followed by ordinary dialogue
`menu_nav.confirm`; there is no click-to-dig resource action. The recorder parks
the participant 64 world units from Solomon so native facing has a defined
direction, then lets the original state machine run. It never writes
`Solomon+0x220` or `Arena+0x902A`.

The complete direct yield table is:

| Outcome | Gold consumed | Items consumed | Gold yielded | Items/reward actors yielded | Arena flag | Probability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete Solomon prelude | 0 | 0 | 0 | 0 | `Arena+0x902A = 1` | 1 |

All eight independent processes observed zero gold delta, identical backpack
rows, and zero delta for reward actor types 2011, 2012, 2013, and 2038. Observed
start-to-completion app-tick spans were `144,185,205,198,204,200,186,201`;
each trace contains acquisition, state 1, and native completion. One sample
caught state 3 and seven caught the later state 4, but every sample had the same
completed Arena flag and zero yield.

Gold, Sacks, potions, and upgrades which appear after combat are downstream
enemy/drop behavior. In particular, drop function `0x0047C070` uses an
actor-private stream and belongs to G7. Treating those later drops as Dig output
would merge two authority and RNG boundaries.

### How run output feeds the hub

The real upgrade loop is run rewards -> completed-run archival -> hub storage
and gold -> Fomentius/Hagatha/Shlorio or progression services. Solomon Dig only
opens the combat side of that loop. Fomentius supplies consumables, Hagatha
turns gold into persistent participant progression, Shlorio sells a rolled
equipment search, and Luthacus preserves/reclaims eligible carried items.

## State crossing the hub/run boundary

### Finished run -> hub

Game-over archival `0x005C9670` calls completed-run processor `0x005BE320`
with these retail fields:

| Source | Field | Consumer meaning |
| --- | ---: | --- |
| Gameplay | `+0x1C90` | participant name used as the retained Sack name prefix |
| Gameplay | `+0x13B8` | active inventory root |
| Gameplay | `+0x1410` | seven equipment sinks |
| local player actor (`*(Gameplay+0x1358)`) | `+0x1C0` | boolean controlling ordinary equipment/backpack transfer; exact producer semantics unresolved |
| progression (`**(Gameplay+0x1654)`) | `+0x7D8` | Last Word owned flag controlling ground-Sack/Gold sweep |
| Arena actor world | actor list; Sack 2013 `+0x148`, Gold 2012 `+0x140` | eligible Last Word ground contents |

When ordinary transfer is enabled, the processor moves each of seven equipped
items whose `item+0x58` marker is clear, then the active inventory, into a new
type-7008 Sack. Sack suffix consumes `Integer(5)` and selects exactly:

```text
Earthly Possessions | Stuff | Dead Stuff | Bag | Loot
```

When Last Word is enabled, it additionally scans the Arena actors, moves the
held item from every type-2013 Sack, and credits the `+0x140` amount of every
type-2012 Gold actor. An empty retained Sack is destroyed. A nonempty one is
inserted into Luthacus storage at profile `+0x8C`, and persistence helper
`0x005BE0B0` runs. The exact pre-suffix active state is not present in the live
fixture; a replay must persist the selected name or full stream state.

### Hub/profile state used by the next run

| Portable semantic field | Retail location | Hub read/write |
| --- | ---: | --- |
| participant gold | profile `+0x58`, `DAT_0081A388` | run archival credits; traders debit |
| active inventory/equipment | Gameplay `+0x13B8/+0x1410` and participant ledger | archival drains/retains; shops/storage insert; next run materializes |
| Luthacus storage | profile `+0x8C`, `DAT_0081A3BC` | archival inserts nonempty Sack; InventoryShop transfers both ways |
| Hagatha bulk selector list/count | profile `+0x60/+0x64` (`DAT_0081A390/+0x04`) | catalog reads; bulk purchase applies participant progression |
| Hagatha first-mix flags | profile `+0x6C`, `DAT_0081A39C+selector` | price reads; purchase writes |
| perk ownership | progression `+0x7CC+selector` | catalog gate and purchase result |
| perk selector list/count/capacity | progression `+0x7C0/+0x7C4/+0x800` | purchase/application and next-run derived state |
| Last Word | progression `+0x7D8` | completed-run ground sweep gate |
| Hagatha catalog limit | `*(DAT_008199CC)+0xF0C` | generation upper bound |
| selected Boneyard String | Gameplay `+0x1BD8` | picker writes; run creation reads |
| map unlock bitmap | Gameplay `+0x1CDC`, 50 bytes | picker reads; story/progression writes |
| Shlorio current fee | `DAT_0081A430` | DOWSE reads; successful offer purchase rewrites |

`0x005CFA80` supplies starter gear and health/mana potions for a new game before
building the initial hub catalogs. `0x005CF920` is the completed-run return path:
it switches back to the hub and invokes the catalog generator. G13 owns the
ordering, fade, teardown, and network barrier around those calls; the table
above is the G8 state contract.

## Multiplayer ownership and authority

Retail exposes one process-local native profile root, not a shared merchant
server. The browser rebuild must project it through the participant model rather
than copying that singleton shape:

| State/action | Owner / authority |
| --- | --- |
| gold, backpack, equipment, perk/book state, first-mix flags, Shlorio fee, Luthacus storage | per participant |
| Fomentius and Hagatha UI catalogs | process/participant-local presentation; no shared stock scarcity |
| purchase request | initiating participant; the authoritative participant ledger validates gold and applies debit/result atomically |
| Luthacus transfer | initiating participant only |
| Shlorio paid roll/result list | initiating participant; owner-local until a purchase/result is published |
| hub Student/world presentation | host/server authoritative world population; peers present snapshots rather than independently treating local rolls as canonical |
| run-entry selection and shared transition | host/session authority; a relayed non-host participant cannot impersonate it |
| Solomon local dialogue/control transaction | initiating participant's process until native completion |
| Arena waves, enemies, drops, and shared world | host/server authority |

The live multiplayer merchant proofs are already documented in
[`inventory-item-investigation.md`](../inventory-item-investigation.md#hub-inventory-shop-ownership-boundary):
a Fomentius purchase changed only the buyer's gold/backpack, a Hagatha Life Charm
changed only the buyer's gold/native HP progression, and Luthacus moved only the
initiator's item. Peers received the resulting participant revisions; they did
not decrement their own catalog or mutate another native inventory root.

This agrees with
[`multiplayer-participant-model.md`](../multiplayer-participant-model.md#participant-owned-inventory-and-books):
stock inventory, equip, merchant, and storage consumers have no participant
parameter and address the one local native root. The network/session layer must
therefore authenticate the requester, transact against that participant's
ledger, and publish the result. “First click wins a shared item” is wrong for
these shops.

Solomon is deliberately split. A client which initiates owns its local modal
and paired controller restore through state 2; authority reconciliation must
not retire that actor before state 3. The host remains the only wave/enemy/world
authority. That is why a single-player-shaped “host owns the whole Dig NPC” or
“client starts its own waves” implementation is incorrect.

No dedicated connected-client Shlorio purchase was added in G8. Its owner-local
authority follows the same recovered Shop root and participant model, but this
specific multiplayer transaction remains an explicit evidence gap below.

## Live golden contract

The committed fixture was recorded on 2026-08-05 from source base
`acc4ef5d7a2a03ae4f4b7b3350cb06f13960836d` with loader SHA-256
`93017506384cf86a69f5a4452c7061265f38028fb6bf03a779fe6804ca5867bd`.
Every section header names its `hub-g8-capture-*` instance, retail and loader
hashes, capture method, source revision, and trial count.

- Census: five live `sd.scene.switch_region` plus
  `sd.world.list_actors` snapshots.
- Traders: three clean instances/progression states; retail Lua execution,
  native call traces, and full active RNG snapshots; eight Dowsing rolls per
  state.
- Dig: eight clean instances; live proximity/dialog drive with before/after
  gold, inventory, reward actors, Arena flag, and state transitions.

The recorder permits only instance names `hub-*`, UDP ports 52311..52318, and
`SDMOD_DISABLE_AUDIO=1`. It distinguishes a runnable Lua pipe from a merely
present path and distinguishes busy capture from broken setup. It never uses
`sd.rng.set_seed`, never writes the Dig state/complete fields, and fails rather
than choosing between ambiguous actors, shops, traces, or result pointers.

## Not Yet Reversed

These are portability findings, not invitations to fill in plausible behavior:

- **Random hub population replay.** The pipe is not runnable before Student and
  Tyrannia construction. Their construction app tick, complete pre-construction
  stream state, Student count distribution, and exact three Tyrannia placements
  were not captured. Students also use the un-goldened G1 Float primitive. Carry
  the generated population/variants explicitly or make the server's one
  generated population authoritative; do not replay the final census as if it
  were a seed fixture.
- **Alternate story-phase selector.** `Gameplay+0x1CD8` selects the alternate
  builder and its phase-dependent population, but the full story/save producer
  and every reachable selector value were not recovered. The static contents
  once selected are documented; the missing producer belongs with G13/G10.
- **Shlorio initial fee.** The image value at `DAT_0081A430` is zero while three
  clean live instances observed 650 before their first G8 roll. No save read or
  unambiguous initializer was found. Persist `current_dowsing_fee` explicitly.
- **Targeted Dowsing cardinality.** The set/type helper paths and eligibility
  rules are statically pinned, but no live target-item roll was captured. A
  helper may add several matching prototypes, so two helper calls do not prove
  “two offers.” Record the branch before fixing its final count/order.
- **Shlorio multiplayer purchase.** Fomentius, Hagatha, and Luthacus have live
  two-owner evidence. Shlorio uses the same local Shop root, but a dedicated
  connected-client purchase/fee/result proof has not been recorded.
- **G1 Float presentation.** Shlorio's `Float(0.1,false)` and Student constructor
  floats use the mechanism G1 recovered, but no native Float golden exists.
  Prices, quantities, and Dig yield do not depend on those values; visual
  effects and exact Student randomization remain gated on that recorder run.
- **Completed-run transfer boolean.** `0x005C9670` passes the local actor byte at
  `+0x1C0` into the ordinary inventory/equipment transfer branch, but the byte's
  producer and user-facing semantic name are not recovered. Preserve it as
  `transfer_carried_items` rather than guessing “alive,” “won,” or “insured.”
- **RNG-selected Sack name.** The five suffixes and `Integer(5)` path are exact,
  but G8 did not capture the full active state immediately before archival.
  Persist the chosen suffix or stream state if exact replay spans run completion.
- **Annalist/Librarian/Teacher content.** Their target, gate, special action, and
  lifetime are pinned. Their complete progression offer tables and effects are
  G6 work; no prices or rewards are inferred here.
