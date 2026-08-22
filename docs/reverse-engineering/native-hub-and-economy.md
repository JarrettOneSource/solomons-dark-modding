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

The transaction owns its outcome audio. Ordinary purchase success calls
registry member 25, `sounds\\dropcoins`, at `0x0056C10E`; an insufficient-funds
rejection calls registry member 6, `sounds\\badaction`, at `0x0056C1A6`.
Hagatha's specialized purchase callback retains the same outcomes at
`0x0056CAEA` and `0x0056CC04`. The common Shop action has already played
registry member 0, `sounds\\click`, at `0x0055F054` before invoking either
purchase callback on the second activation. Selection and transaction outcome
are distinct native requests rather than one generic UI click.

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
3. starts the native `pickskill` echo and consumes `Float(0.1,false)` for the
   following distortion pitch;
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

The Float draw is before the offer-count `Integer(2)`, not after the result
list. The roll then calls `sounds\\distortreality` at `0x0055FE17` with pitch
`0.8 + Float(0.1,false)` and gain 1. `SoundEcho` (`0x00407E50`, constructor
`0x004084A0`, tick `0x00408550`) owns four `pickskill` requests at native ticks
0, 25, 50, and 75—0, 250, 500, and 750 ms—with gains 1, 0.25, 0.0625, and
0.015625. That Float consumption is part of the authoritative economic RNG
order even though its result affects only audio pitch.

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

The successful purchase plays the common `dropcoins` request, then consumes
`Float(0.1,false)` and calls `sounds\\distortreality` at `0x0056D18B` with
pitch `1.0 + Float(0.1,false)` and gain 1. The next-fee integer draw precedes
that Float. A rejected offer purchase takes the common `badaction` branch and
does not clear the offers or advance either draw.

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

Live retail input plus callback `0x0056CD00` fixes the asymmetric gesture
contract. A second activation in the lower backpack remains ordinary
InventoryScreen behavior—potions drink and equipment equips; it does **not**
deposit the item. Backpack-to-storage is drag-only. Storage-to-backpack accepts
either a second activation of the selected storage cell or a drag. The common
Shop action plays `click` before the storage double-activation callback; the
accepted callback then plays `backpack_close` at `0x0056CE80`. Starting a
storage drag plays `click` at `0x0056CF1A`, and an accepted native dragger
release plays `click` at `0x0056F55A` with pitch 0.75. Invalid release restores
the exact source object without transfer audio.

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

## Retail trader presentation and transaction contract

This section records the 2026-08-15 static follow-up used by the Website port.
It was recovered from retail `0.72.5` `SolomonDark.exe`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
in the checked-in Ghidra project. The G8 live golden above independently
corroborates the initial gold, generated stock, dowsing fee, and state changes.
A live 1600x900 client-area backbuffer receipt was added on 2026-08-15 as
`tests/fixtures/webgame/menu-reference-captures/inventory-screen.png` (SHA-256
`0d99c6bb3f1815aa061fd4ee49e7bfccbd0ee058ea69b0e8936155c7e5156d8b`).
The process executable independently hashes to the retail digest above. The
settled trader and Chat witnesses listed in
`tests/fixtures/webgame/native-hub-trader-ui-captures.json` were captured from
that same retail image on the Mac mini. Those later witnesses are explicitly
debugger-instrumented/runtime-staged: a temporary injected helper invoked the
stock constructors and adjusted gold/dialogue state, while the retail code and
retail renderers built every visible pixel. They are layout/render evidence,
not evidence that the staged entry sequence itself is naturally reachable.

### Trader actors and animation

The four services are ordinary hub actors. Their retail positions and
interaction radii are:

| Actor | Native type | Region | Root | Radius | Service |
| --- | ---: | --- | --- | ---: | --- |
| Hagatha | 5001 | Courtyard | `(1340,280)` | 15 | `PerkShop` |
| Fomentius | 5004 | Courtyard | `(1397,664)` | 30 | `Shop` |
| Luthacus | 5005 | Courtyard | `(1700.5,449.5)` | 25 | `InventoryShop` |
| Shlorio | 5016 | Library | `(900,642.5)` | 25 | `DowsingShop` |

`0x0050A4C0`, shared by Luthacus and Shlorio, first runs the engagement
dismissal helper `0x00505010`, increments the actor tick at `+0x160`, then
tails into `0x00501610` with the animation block at actor `+0x13c`.
When idle, `Integer(200)==2` begins a gesture. Its phase speed is
`(Float(3,false)+1)*0.45`, the phase ends at 180 degrees, and the displayed
frame scalar at `+0x144` is `3.99 * sin(phaseDegrees)`. Integer conversion
therefore selects all four frame indices 0..3. The starting RNG state is a
session input rather than an invariant frame epoch; a port must preserve the
1-in-200 trigger, native RNG primitive, speed draw, easing, and four-frame
range, and must make the selected session seed authoritative in multiplayer.

Luthacus composites College record 10 with records 126..129 selected by that
frame scalar. Shlorio selects Library records 21..24. Hagatha has a dedicated
eight-frame loop in College records 517..524. Constructor `0x005018D0` sets
actor `+0x144 = 0` and signed velocity `+0x148 = 0.05`. Tick `0x0051ADC0`
advances the phase by `(Float(0.25,false)+1) * actor[+0x148]`, wraps it in
`[0,8)`, and reverses its direction when `Integer(1500)==3` by multiplying the
velocity by the binary double `-1` at `0x007DE8E8`. This is a persistent
direction reversal, not a speed-up.

That tick also creates one `Anim_CrossFade` on every update. It selects one of
College records 89..92 with `Integer(4)`, seeds opacity with `Float(1,false)`,
and advances normalized lifetime by
`1 / ((Float(0.25,false)+1.25) * 100)`, so an object survives 125..150 native
ticks. Uniform scale is `Float(0.1,true)+0.15`, giving `0.05..0.25`. Its
eight authored anchor pairs are `(79.5,80.5)`, `(81.5,81.5)`, `(83.5,82.5)`,
`(86.5,83.5)`, `(90.5,83.5)`, `(103.5,77.5)`, `(104.5,75.5)`, and
`(84.5,84.5)`. Position adds the actor root, `14` to Y, and a radial jitter
from `Float(2,false)`, then subtracts half the 150x150 body-frame extent.
Renderer `0x0051B1D0` draws the selected body at `(x-5,y)` and College record
45 at `(x-25,y+15)`. The particles remain presentation-only and are not part
of transaction state, but all four particle records and the complete authored
anchor set are reachable presentation members.

### Interaction, dialogue, and service ownership

The common action path builds the 400-byte dialogue object from the actor's
dialogue definition at `+0x154`, attaches it as the active UI, and sets the
actor's engagement byte at `+0x170`. `0x00505010` dismisses that UI when:

```text
distanceSquared(player, actor) > 5 * actorRadius^2 + 1500
```

The service dispatcher at `0x00514A20` is disabled while the courtyard/region
fade value at gameplay `+0x8e48` is positive. It maps the four actor control
slots to the following exact titles:

- Hagatha (`Gameplay+0x101c`): `HAGATHA'S CHARMS AND CURSES`
- Luthacus (`Gameplay+0x10d0`): `LUTHACUS' SCAVENGED GOODS`
- Fomentius (`Gameplay+0x1184`): `FOMENTIUS' USEFUL THYNGS`
- Shlorio (`Gameplay+0x1238`): `SHLORIO'S DISCOUNT DOWSING`

Dialogue commands `!BUYPERKS`, `!INVENTORY`, `!BUYPOTIONS`, and the dowsing
service reach the same shop roots through `0x004fb890`; the dialogue is
replaced, not left underneath the shop. The runtime loads the aggregate
`data/dialogue/survival.txt`. That aggregate differs from some retained
per-NPC source fragments, so its reachable rows—not
`survival/{witch,potionguy,scavenger,dowser}.txt`—are the portable text
authority.

The scavenger data file also declares `Outfit me Randomly` / `!RANDOMEQUIP`,
but that row is dormant in this retail build. The ordinary hub builder at
`0x0050b720` installs only an `Examine Items` command leading to `!INVENTORY`.
No `RANDOMEQUIP` literal or command branch exists in the executable, and the
dispatcher at `0x004fb890` recognizes only the four reachable service
commands. A parity port must not expose the dormant data row as reachable UI.

### Gold, stock, and purchase invariants

Gold is a participant-owned profile ledger (`profile+0x58`, rooted by
`DAT_0081A388` in retail), not an item stack. The ordinary purchase callback at
`0x0056bf70` reads price at item `+0x5c` and performs one atomic operation:

1. reject without mutation when the participant cannot afford the item;
2. call `0x005a7c60(-price,false)`;
3. transfer one stock object into the active backpack, stacking where the
   inventory type permits it; and
4. remove exactly that object from the shop.

There is no sell, refund, or buyback branch. One shop object represents one
unit even when the UI groups equivalent objects.

Fomentius' `0x005c8960` restock makes the following independent rolls, in
order, only at initial hub construction and post-run return:

| Item | Price | Quantity / gate |
| --- | ---: | --- |
| Health Potion | 150 | `Integer(3)+2` (2..4) |
| Mana Potion | 75 | `Integer(6)+2` (2..7) |
| Rejuvenation Potion | 200 | `Integer(3)` (0..2) |
| Dye | 300 | `Integer(2)+2` (2..3) |
| Key | 1200 | one only when `Integer(18)==1` |
| Sack | 50 | `Integer(2)+1` (1..2) |
| Antidote | 100 | `Integer(3)+1` (1..3) |
| Wizard Chug | 2500 | one only when `Integer(8)==3` |
| Mind Chug | 1500 | one only when `Integer(8)==3` |

The total is therefore 8..24 objects. Shop open/close does not restock it.

Hagatha presents selector IDs 0..27 except 8. An owned selector is omitted on
the next rebuild. Its first-ever mix costs three times the catalog base price;
after its persistent first-mix flag is set, a later mix costs the base price.
`0x0056c340` rejects
insufficient gold and full applicable capacity before debit, then advances the
selector's participant-owned progression and first-mix state. The exact names,
base prices, icons, and capacity families remain in
`native-hagatha-perk-catalog.json`.

Luthacus' `InventoryShop` callback `0x0056cd00` transfers a selected object in
either direction between the active backpack and profile storage. It uses the
same inventory insertion/stacking rules but never reads or changes gold and
never creates a copy.

Shlorio begins with the explicitly persisted observed fee of 650. DOWSE first
rejects insufficient funds, then debits the fee and produces
`Integer(2)+3` unique offers (3..4) from the 47 equipment recipe catalog,
retrying duplicate selection at most 100 times. Each price is
`(Integer(15)+100)*50` (5000..5700). A successful ordinary purchase reaches
`0x0056d110`, clears every unbought offer, and rolls the next fee as
`(Integer(10)+10)*50` (500..950). Closing after a paid roll discards its offers
without refund.

`DowsingShop` also contains a targeted branch, now fully dispositioned. Its
constructor at `0x004f5ab0` writes target field `+0x344` to null. The only two
constructor xrefs, `0x004fbce4` and `0x00514e36`, construct the ordinary hub
service and never replace that null. If an external producer did supply a
target, `0x0055faf0` would call `0x00554af0` twice to append every eligible
recipe in the same authored set and `0x00554ce0` three times to append every
eligible recipe of the same compiled item type. Duplicate rejection makes the
repeated calls no-ops: the result is the stable union of matching-set and
matching-type recipes, not two, three, or four random offers. No retail hub
producer reaches it, so targeted dowsing is dormant and outside the reachable
hub trader system rather than unknown.

The common `StoreGrid` is visibly seven columns by four rows, retains 28
objects, and fills column-major: `column = floor(index / 4)` and
`row = index % 4`. Dowsing switches its result grid to three columns and
retains at most nine cells. The `4,2` arguments passed by `0x00550db0` to
`0x00416020` are not grid bounds: decompilation proves that helper repeats the
UI record 49 cracked-dark texture four by two times as the shop background.
Every repeat keeps the record's native 264-by-264 logical extent; the Shop
clips that 1056-by-528 submission to its `(498,-20,604,400)` content rectangle.
The arguments do not stretch four copies to 151-by-200 cells.
The ordinary field modulates that texture by native RGB `(0.85,1.0,0.85)`.
That is not a single opaque texture pass. `0x00550db0` calls the same
`0x00416020(0,0,4,2)` tiling pass twice: once in the normal state, then again
after setting render-context byte `+0x3F1` to `1` and applying it through
`0x004208a0`, before restoring the byte to `0`. The second pass is additive.
The same two-pass sequence exists in `0x00554e20` for DowsingShop. This is
visibly material: at stage `(700,45)` the browser's former one-pass rendering
was RGB `(26,29,21)`, while the retail capture is `(52,58,44)`. A one-pass
port therefore preserves the texture and tint but still renders both shop
fields at roughly half stock luminance.
`0x0055a7ad` draws every Inventory-record-10 StoreGrid cell at alpha `0.6`,
then restores white; the same cells in the backpack path at `0x0055a070` use
alpha `0.4`. These are authored renderer-state changes, not opacity inherited
from a modal parent.
Item prices are not drawn with the Skills font: their live glyph sprites have
the 26-square body-font logical size. In the first StoreGrid row their visible
glyphs occupy y=113..124, with the text baseline 67 pixels below the slot's
visible top and the first-column glyph run ending at x=605. This is why using
the extracted Skills font silently loses every price digit. Affordable prices,
shop titles, Hagatha's pane title, DOWSE/fee text, and MsgBox control labels use
the shared native RGBA `(0.85,0.73,0.44,1)`, which quantizes to `#D9BA70` in
the browser. Unaffordable prices use `(1,0.5,0.5,1)` or `#FF8080`.
Conflating that tiling pass with StoreGrid geometry caused the first Website
port's false 4-by-2/paging model. Skills record 4 supplies the paired scroll
decoration behind the store controls. Before a dowsing roll it
renders `DOWSE`, the current `%d gold` fee, the gold icon, and the
insufficient-funds state. `InventoryScreen` independently displays the same
participant gold ledger. These are views of authoritative state, never
client-side balances.

### Inventory and equipment membership

The authored equipment input is the complete 47-row recipe table in
`native-item-catalog.json`: 13 rings, nine amulets, eight wands, seven robes,
six hats, and four staffs across seven item sets, with all 86 item/set FX
declarations retained there. The reachable inventory accepts native type IDs
Potion 7001, Ring 7002, Amulet 7003, Staff 7004, Hat 7005, Robe 7006, Sack
7008, Perk 7009, Map 7010, Wand 7011, and Misc 7012. Potion subtypes Health,
Mana, Wizard Chug, Antidote, Mind Chug, and Rejuvenation select Inventory
records 46..51. Equipment icon records are catalogued per recipe; Sack uses
70/71, Perk uses Skills record `127 + selector` (bundle uses Inventory 10),
and Misc uses 42..45.

New-character inventory is not empty. `0x005CFA80` constructs the same
recipe-UID-0 loadout for all 15 element/discipline choices: a type-7005 `Hat`
in the hat sink, type-7006 `Robe` in the robe sink, type-7004 `Staff` in the
weapon sink, then one type-7001 Health Potion in backpack slot 0 and one
type-7001 Mana Potion in slot 1. `0x00571980` supplies those three exact base
equipment labels. The local participant projection repeats Hat as the primary
visual lane, Robe as the secondary lane, and Staff as the attachment lane;
those are aliases of the three equipped objects rather than five items. The
InventoryScreen similarly draws that one Staff in both hand boxes.

The equipment icons are class-owned render methods, not scaled thumbnails.
The inventory draw trace and vtable slot `+0x0C` methods recover this complete
family:

| Item class | Draw owner | Stock Inventory-atlas transform |
| --- | --- | --- |
| Ring | `0x005788B0` | selected recipe record, natural scale, centred |
| Amulet | `0x00578910` | both recipe layers at natural scale, translated `(0,-5)` |
| Staff | `0x00578A90` | selected record at natural scale, rotated `+35` degrees; matrix `(0.81915,0.57358,-0.57358,0.81915,-22.94306,32.76608)` |
| Hat | `0x005779B0` | both recipe layers at natural scale and their authored trim origins |
| Robe | `0x00577B90` | both recipe layers at natural scale and their authored trim origins |
| Wand | `0x00579720` | selected record at natural scale, rotated `+45` degrees; matrix `(0.70711,0.70711,-0.70711,0.70711,0,0)` |

For the recipe-UID-0 loadout, Hat draws Inventory 34 then 38, Robe draws 64
then 67, and Staff draws 72. In the settled EQUIP pane their bases are
`(1337,179)`, `(1337,277)`, and `(1257,259)` / `(1417,259)` respectively.
The starter Hat/Robe primary color comes from the new wizard's current
appearance color and their secondary color is white; it is not a fixed item
recipe tint. Purchased Hat and Robe objects instead use the two ordered color
fields from their row in `native-item-catalog.json` (`effective_color1` and
`effective_color2`, with null meaning the native white default). Their methods
are the only item-icon members which call the render-color setter
`0x0041FE50`; Ring, Amulet, Staff, and Wand remain white regardless of recipe
color metadata. Amulet also has a class-specific painter order: its shared
record 30/31 layer is drawn first and its recipe-specific record 18..29 second.
Shrinking large records to fit a generic 64-pixel box, reversing that layer
order, discarding the second layer, ignoring Hat/Robe colors, or leaving
Staff/Wand upright changes the native icon contract.

Recipe UID 0 is also the integration boundary with the Player death
compositor: the equipped starter Hat and Robe retain the element's default
selector-zero palette, and the starter Staff retains selector zero. They are
not missing purchased-recipe rows. The Website therefore represents those
three authored starter objects with `recipeIndex: null` while still treating
them as the stock death appearance.

The equip path is not a purchase side effect. `0x00570cd0` validates an item,
`0x00575850` attaches it, `0x00570d80` resolves the current slot occupant,
`0x0066f020` removes/reinserts on unequip, and `0x0055ff20` performs stack
insertion. The seven sinks are hat, robe, amulet, weapon (staff or wand), ring
0, ring 1, and a progression-gated ring 2. Inventory/storage ownership,
stacking, and those seven transitions belong to this service boundary.
Equipped Clothes attachment painting and the 39 recovered combat/stat FX
consumers are downstream presentation/combat systems: their complete authored
inputs remain catalogued, but applying those effects is not part of the hub
merchant transaction itself.

The full-screen inventory renderer at `0x00568b90` consumes Inventory record 1
and UI records 20, 21, 30, 31, 33, 49, 62, 75, 76, and 77. The common shop
family uses Skills record 4 for its paired scroll decoration;
its selected-item detail renderer `0x00565e00` additionally reaches UI records
12 and 72 plus the item-type icon table. The dowsing pre-roll renderer at
`0x00558160` additionally uses UI record 15, the exact `DOWSE` label,
`%d gold`, and the participant ledger. Ordinary Shop exposes all 28 retained
cells as a seven-column by four-row StoreGrid; Dowsing changes the result grid
to three columns and retains at most nine cells.

### Full stock UI correction and presentation closure

#### 2026-08-16 second-pass reopening

The Website presentation row is reopened rather than treated as closed. A
fresh Mac mini run of Website SHA
`6826e62bc981c53b7c1f9800a6de1c97c6da18db` completed the existing trader
smoke at a literal 1600 by 900 viewport without browser errors, while direct
inspection against the committed retail witnesses identified an overflowing
fourth PRIMARY SPELL stat row, incomplete right-hand robe/equipment
composition, and a missing companion-inventory input path after purchases in
Shop, PerkShop, and DowsingShop. The web renderer currently draws that lower
InventoryScreen for all services but only InventoryShop exposes its backpack
objects to the semantic action layer.

The oracle remains pinned: the 18 trader/Chat manifest rows and standalone
InventoryScreen image all revalidated at 1600 by 900 with their committed
digests, and the 4,723,200-byte retail executable independently revalidated on
Windows and the Mac mini as
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
This pass must follow the native owners below through their stat layout,
equipment painters/sinks, ItemInfo, selection, second-activation, drag, and
post-purchase callback paths. Completion now additionally requires a
deterministic region-level pixel comparison and immediate post-purchase
companion activation in every purchasing service. The earlier `exact-ported`
presentation disposition is withdrawn until those gates pass.

##### PRIMARY SPELL is one ExactText document, not four browser rows

The stats owner is `0x00562520`. Its sole `PRIMARY SPELL` literal reference is
the call at `0x005630c2`; the same function reads the InventoryScreen fields at
`+0x4b0`, `+0x4d0`, `+0x508`, and `+0x55c` and emits the equipped spell name,
`damage: %s`, `mana cost: %s`, and `mana heal: %s`. The native local y inputs
are 205, 226, 239, and 252. The settled draw trace has the companion
InventoryScreen transform `(-10,+46)`, which fixes the browser-stage text
baselines at 251, 273, 286, and 299. The visible glyph bounds are y=239..253,
y=259..274, y=273..287, and y=286..300 respectively. The heading already uses
the correct browser baseline y=226 and occupies y=215..226.

The unit tail is an inline ExactText run, not part of a uniformly sized row.
`0x00663b30` appends `_s(.7)_o(0,1)__i/_sec_i` or its `/second` sibling from
`0x007a0190`, `0x007a0214`, and `0x007a0294`. Therefore `/ SEC` or `/ SECOND`
continues the numeric run at scale 0.7, offset `(0,1)`, and italic styling.
The settled glyph centres and matching Air-profile pixel witness close another
ExactText detail: `PRIMARY SPELL` uses the 26-square font group, while its four
content rows use natural-size 32-square glyph quads with cursor/kerning advance
compressed to 0.9. The inline 0.7 unit run therefore advances at 0.63 without
shrinking the preceding glyph art. Standalone content is submitted at x=95 and
first becomes visible at x=96; companion mode submits at x=148 and first becomes
visible at x=149.

There is no 19-pixel browser line-height. The stock 13-pixel gaps between the
last three baselines are what retain `MANA HEAL: 10 / SEC` inside the lower
body. The two native opaque rectangles are also distinct: the settled
standalone heading and body primitives are `(86,207,227,24)` and
`(86,230,227,79)`, then shift 53 pixels right in companion mode. Their native
nine-slice edges form one divider; collapsing them to one large browser
rectangle removes it.

##### EQUIP owns seven typed sinks and clips each class painter

`0x00561300` owns the EQUIP pane and its seven live object references:
`+0x18` hat, `+0x1c` robe, `+0x20/+0x24/+0x28` rings, `+0x2c` amulet, and
`+0x30` weapon. It invokes `0x005504d0` to derive the sink rectangle, then
`0x00575450` to paint the sink and dispatch the item's class vtable `+0x0c`
renderer. The normal branch is 72 by 72, the small flag at `+0x14` is 46 by
46, and the tall flag at `+0x15` is 72 by 108. Every sink first receives the
opaque `(0.1,0.1,0.09,1)` interior. `Inventory.10` frames 72-square sinks,
`Inventory.9` frames 46-square sinks, while the robe uses the tall primitive
frame rather than stretching either atlas cell. That tall branch calls
`0x004a2ff0`, which delegates its outline-only nine-slice to `0x004153b0`;
`0x0041dd70` owns the preceding opaque fill. It brackets the robe class paint
with `DAT_00819e5e = 1`, then restores the flag to zero.

The settled companion centres and visible sink rectangles are:

| Sink | Centre | Rectangle / frame |
| --- | --- | --- |
| hat | `(1337,179)` | `(1301,143,72,72)`, `Inventory.10` |
| robe | `(1337,277)` | `(1301,223,72,108)`, tall primitive |
| weapon left/right | `(1257,259)`, `(1417,259)` | `(1221,223,72,72)`, `(1381,223,72,72)`, `Inventory.10` |
| amulet | `(1270,192)` | `(1247,169,46,46)`, `Inventory.9` |
| rings 0/1 | `(1270,326)`, `(1404,326)` | `(1247,303,46,46)`, `(1381,303,46,46)`, `Inventory.9` |
| gated ring 2 | `(-9999,-9999)` while locked | same 46-square contract when unlocked |

The robe's authored Inventory 64/67 quads are naturally about 71 by 91 pixels.
The Staff painter remains natural-sized and rotated 35 degrees around its
native `(-22.94306,32.76608)` translation; its unmasked quad reaches outside a
72-square hand sink. Stock contains both by switching the sink clipping state
around the class-owned paint. The same clipping ownership applies to backpack,
StoreGrid, dowsing-result, and storage cells. It does not apply to the detached
InventoryDragger, which deliberately paints the held object at natural size.
Accepting equipment sinks turn green only while the dragger holds a compatible
backpack item; a merely selected item does not activate those highlights.

##### A service never replaces its companion InventoryScreen input owner

Dispatcher `0x00514a20` attaches an independent InventoryScreen beneath every
Shop-family overlay. `InventoryScreen::PointerPress` at `0x0056f760` continues
to query that companion InventoryGrid, retain its selected object, start
ItemInfo after 20 ticks, and dispatch the same-object second activation inside
the 50-tick window. This remains true for Fomentius, Hagatha, Luthacus, and
both Shlorio states. Shop selection and companion-inventory selection are two
different native owners and must not share one browser selection variable.

Ordinary purchase `0x0056bf70` debits the participant, removes the Shop object,
inserts that same live object into the companion backpack through `0x0055ff20`,
and invokes InventoryScreen vtable `+0xb4` to rebuild it. Dowsing purchase
`0x0056d110` uses that common path before replacing its fee/flash state.
Hagatha purchase `0x0056c340` is the sibling exception: it applies/removes the
perk offer and rebuilds the charm pane without inserting a backpack item.
Luthacus' `0x0056cd00` storage selection remains a third owner layered beside
the companion InventoryGrid. Consequently a newly bought potion can
immediately be selected and double-activated, and newly bought equipment can
immediately be selected, inspected, dragged, or equipped without closing its
trader.

##### Literal 1600x900 comparison and Mac behavior receipt

The corrected Website candidate was driven with an Air/Arcane profile so its
Lightning rows, starter equipment palette, potions, stage dimensions, and
atlas membership matched the standalone retail witness. Website
`frontend/tools/compare-native-ui-captures.mjs` decoded both PNGs and searched
every translation in a three-pixel radius. At channel threshold 16, every
reviewed region chose exact offset `(0,0)`:

| Region | Mean absolute channel delta | Pixels over threshold |
| --- | ---: | ---: |
| PRIMARY SPELL pane | 21.4277 | 41.5253% |
| PRIMARY SPELL body | 25.0412 | 38.8780% |
| EQUIP pane | 10.2722 | 40.5203% |
| robe sink | 10.5521 | 25.9398% |
| backpack/grid | 4.8741 | 8.7542% |

These are raw raster deltas, not a hand-scored similarity measure. They retain
Direct3D/WebGL sampling and color differences plus independently timed preview
animation; the zero best offsets are the geometry receipt. The same exact
candidate completed the full Mac mini browser smoke with no browser errors.
Before closing the relevant service, that run selected and double-activated a
new Fomentius potion stack, selected the companion inventory after Hagatha's
perk-only callback, and selected, revealed ItemInfo for, dragged, equipped,
then restored a newly bought Shlorio object. Luthacus' asymmetric two-owner
drag and second-activation paths, required-clothing rejection, dowsing flash
and MsgBox, 10,000-gold initialization, and second-participant isolation also
remained green.

The first 2026-08-15 Website pass closed authoritative inventory and merchant
mechanics but incorrectly labelled its custom DOM modal as an exact stock UI
port. That claim is withdrawn. The stock presentation is a related class
family, not a skin over the transaction kernel:

| Owner | Vtable | Lifecycle/update | Render/action membership |
| --- | --- | --- | --- |
| `Shop` | `0x00794D7C` | ctor `0x0055E800`, slide/alpha `0x00550D80`, action `0x0055EF40` | root `0x00557D40`, grid passes `0x00550DB0`, detail `0x00565E00` |
| `PerkShop` | `0x00790374` | ctor `0x004F5890`, rebuild `0x0055F270` | common root/grid, detail suffix `0x00554690`, purchase `0x0056C340` |
| `InventoryShop` | `0x0079044C` | ctor `0x004F59A0` | common root/grid, two-owner transfer `0x0056CD00` |
| `DowsingShop` | `0x00790524` | ctor `0x004F5AB0`, update `0x005512F0`, state rebuild `0x0055F9F0` | root `0x00558160`, result/grid `0x00554E20`, red flash `0x00551350`, action `0x0055FAF0` |
| `InventoryGrid` | `0x00794C64` | ctor `0x0055D830`, input/state `0x0055FEE0`/`0x0055CEE0` | item/overlay draw `0x0055A070` |
| `InventoryScreen` | `0x00794F54` | ctor `0x00560380`, update `0x00551A10`, close `0x00555810` | root `0x00568B90`, detail/help `0x00556940` |
| `Chat` | `0x0079061C` | ctor `0x004F5D90`, init/update `0x004FFEC0`/`0x004FFEE0`, advance `0x004FFB00`, close `0x004FCB40` | root `0x004F9380`, pointer `0x004FFBC0`, action `0x004FFC40`, content `0x004FD6A0`, builder/dispatcher `0x0050B720`/`0x004FB890` |
| `MsgBox` | `0x00788E04` | ctor `0x004A98E0`, fade `0x005AB710`, primary/secondary controls `0x005AB7E0`/`0x005AB980`, lines `0x005BCCB0` | modal root `0x005C4530`; insufficient-dowsing feedback only in this trader family |

At 1600x900 the common Shop root settles directly in stage coordinates at
`(498,-20,604,430)` and slides vertically by exactly 100 stage pixels under
the companion InventoryScreen alpha. Dispatcher `0x00514A20` constructs and
attaches a separate 0x5D8-byte InventoryScreen for every service and stores it
at `Gameplay+0x15a0`; the service overlay is never a standalone modal.

A live settled-frame draw trace on 2026-08-16 detoured the retail centered,
positioned, and transformed sprite paths at `0x004142e0`, `0x004143d0`, and
`0x00414540`. The first complete Fomentius/InventoryScreen frame contained 481
calls. This distinguishes constructor layout inputs from final transformed
quads: the constructor passes 400 as the content-height argument, while the
settled root rectangle is 430 pixels high. The common StoreGrid begins at
centre `(575,92.5)`, uses the complete Inventory record 10 at 72x72 pixels,
and advances by `(75,75)`; its first visible quad is therefore
`(539,56.5,72,72)`. The seven-by-four grid is column-major. Its UI-record-74
frame repeats five times across the top and ten times down each side, with
UI-record-73 corner quads extending from x=475.5 through x=1123.5 and y=-65.5
through y=415.5. The DONE/detail stack is the exact UI 72, 12, and 86 quads at
`(714.5,358,171,58)`, `(732.5,361.5,135,47)`, and
`(737,366,126,38)`; its DONE glyphs occupy `(760,374,80,20)` from baseline
y=392. Render helper `0x00565e00` draws UI 72 white at the service alpha,
UI 12 white at `0.85` times the service alpha, and UI 86 at
`(0.75,1,0.75)` at the service alpha before resetting white for the DONE text.
The service title glyphs occupy y=14..34 from baseline y=32. Both text
rows are inside the stock draw list,
not DOM labels layered over the atlas controls.

The subclass traces close the non-common composition as well. `PerkShop`
replaces the companion InventoryScreen's left STATS contents with its authored
CHARMS/CURSES view; it does not construct a detached card over that pane. The
pane remains `(103,89,320,320)`. Its three-by-three cells are Inventory record
10 transformed to 0.8 scale: visible cells begin at `(164.2,169.2)`, measure
57.6 square, and advance by 60 pixels. The pane interior is not tiled UI 49:
helper `0x00550cc0` paints the rectangle `(139,129,227,238)` opaque
`(0.1,0.1,0.09,1)`, resets white, and adds a one-pixel white outline. Empty
cells are tinted `(0.5,0.5,0.5)`; occupied cells are white and composite the
owned perk's Skills record `127 + selector`. The bundle remains full-white
Inventory record 5. The CHARMS/CURSES glyph bounds are
`(169,139,168,15)` from baseline y=152.5, and the bundle uses Inventory record 5 at
`(207,263,92,50)`.

Before a dowsing roll, UI record 15 occupies `(693,54.5,214,41)` above the
black `(750,101,100,149)` reference-item sink. The DOWSE control is UI record
101 at `(623.5,265.5,353,69)`, flanked by UI record 54 at
`(669,259.5,70,85)` and `(861,259.5,70,85)`; DOWSE and its fee use baselines
y=302 and y=322.5. After a roll, the result grid is
three by three with 72-square Inventory-record-10 cells beginning at
`(689,94)` and advancing by 75 in both axes. Its purple field is not another
asset: `0x00554e20` reuses the UI-record-49 shop background with red and blue
at 1.0 through the same normal-plus-additive duplicate passes. Its green channel is
`sin(nativeTick * 0.5 * pi / 180) * 0.1 + 0.7`, ranging from 0.6 through 0.8
with a 720-tick (7.2-second) period. Random per-render tint is therefore not a
native approximation. The pre-roll UI-101 body and both mirrored UI-54 ends
are white; only DOWSE and `%d gold` use the shared native gold color.

Trader conversation is `Chat`, not `MsgBox`. Its UI-record-11 nine-slice root
settles at `(476.5,26,647,420)`, with content `(561.5,111,477,250)`, title
centre `(800,90)`, and SKIP/DONE text baseline y=396. The four UI-record-11
centres are `(521,70.5)`, `(1079,70.5)`, `(521,401.5)`, and
`(1079,401.5)`, producing exact 89-square corner bounds. In the question state,
the primary 1.25-scale choice baseline is y=226 and the optional price-choice
baseline is y=256. The nine-slice is renderer helper `0x00417760`, not four
corners over a generic fill: it mirrors the complete UI-11 quadrant for the
corners, stretches its rightmost five-percent UV strip across the horizontal
edges, its bottom five-percent strip across the vertical edges, and its
bottom-right five-percent square across the interior. Chat title, body,
secondary choice, and SKIP/DONE use `(0.85,0.73,0.44,1)`; the authored primary
action directive `_c(.55f,.75f,.55f)_s(1.25)` changes that row to
`(0.55,0.75,0.55,1)` at scale 1.25. It has no full-screen curtain. Alpha advances by `0.05` per
100 Hz tick. Intro copy starts at
`contentHeight - 36` and scrolls by `0.125` pixels per tick; pointer acceleration
adds `0.675` for 0.8 pixels per tick. Natural completion or SKIP exposes the
question state; a price answer loads another scrolling intro and returns to
questions. A command answer replaces Chat with the service, while a terminal
Chat closes. InventoryScreen adds `0.025` per native tick. The separate MsgBox
adds `0.035` and draws a black curtain at `0.75 * alpha`. These timings and
ownership boundaries are not optional CSS transitions.

Chat also preserves the dialogue file's inline emphasis. The survival source
uses paired asterisks, such as `*very legal*` and `*less*`; the live Chat string
at `Chat+0xb0` rewrites those pairs to ExactText italic toggles (the latter was
observed as `_iless_i`). ExactText's command marker is `_` at `+0x4d414`, and
`ExactText_Render` `0x0043bcd0` toggles italic on command `i`. In the Chat font,
the italic factor at `+0x4d418` is `0.125` and the line height at `+0xd410` is
24 pixels. The renderer consequently adds three pixels to both top x
coordinates of every italic glyph quad and subtracts three pixels from both
bottom x coordinates. A Mac retail frame of Hagatha's price explanation
confirmed that `LESS` has this right-leaning shear and that neither source
asterisk is painted. Command-aware wrapper `0x0043d230` skips the inline
commands while laying out the final string. Stripping the delimiters and
rendering an ordinary upright run therefore loses stock presentation.

At 1600x900 the inventory witness proves the following settled membership:

- opaque black stage, with STATS at upper left and EQUIP at upper right;
- centre seal plus the live wizard/equipment preview and Kills/Awesomeness;
- a BACKPACK grid of 22 columns by 4 rows (88 authored slots), filled
  column-major so indices 0 and 1 occupy the first column's first two rows,
  not 28 row-major slots;
- seven equip sinks around the right-hand preview, selected-item/stat panes,
  paired InventoryGrid/page state, and the complete fixed chrome;
- bottom-left gold icon/ledger, centre belt slots, and bottom-right exit
  control; and
- the exact Inventory, UI, Skills, Clothes/player, and bitmap-font art paths.

The same draw trace fixes the inventory geometry independently of the capture:
the backpack slot centres begin at `(60,532)`, advance by 75 in both axes, and
draw full 72x72 Inventory-record-10 quads beginning at `(24,496)`. Those cells
are white at alpha `0.4`; contained item sprites are not subjected to the cell
alpha. The left and right 320x320 content panes are `(103,89)` and
`(1177,89)`, each closed by
four transformed Inventory-record-8 corners. The authored lower frame uses
Inventory-record-8 outer corners at `(-100,477)`, `(1627,477)`,
`(-100,739)`, and `(1627,739)`, with UI-record-71 divider ends at x=-30.5 and
x=1579.5 on y=465 and y=793. The upper chrome is not a tiled generic panel:
it is the asymmetric UI 20/29/30/31/32/33 composition plus UI 107..110 corner
members recovered in the trace. Those exact authored calls are the renderer
contract.

InventoryScreen has two render modes rather than one movable modal. The
service-companion mode uses panes `(103,89,320,320)` and
`(1177,89,320,320)` and suppresses the central player preview. Standalone
inventory shifts the left pane 53 pixels outward to `(50,89,320,320)`, shifts
the right pane to `(1230,89,320,320)`, and renders the live composite wizard at
centre `(800,249)`, heading index 9 (135 degrees), scale 1.25. The dispatcher
selects the companion mode through the separately owned InventoryScreen; this
53-pixel distinction cannot be inferred from whether a CSS overlay happens to
cover the centre.

Inventory input is also a native object family, not a row of detached equip
buttons. `InventoryScreen::PointerPress` at `0x0056f760` asks the active
`InventoryGrid` for the object under the pointer, retains both the current and
previous object, and detects a second activation of the same object inside 50
native ticks (500 ms at the 100 Hz simulation rate). A settled single click
creates `ItemInfo` (`0x007946a4`, constructor `0x00553b80`, renderer
`0x005c3a60`). That object waits 20 native ticks on the ordinary press path,
then paints an opaque black contextual rectangle beside the selected object,
clamped to the client, and renders its own `ExactText` line list. It does not
paint selected name/rarity text at screen centre and it does not create an
`EQUIP ...` control.

The `ItemInfo` content list is built by the selected item's common method
`0x0057c4b0`: the item's `+0x1c` virtual supplies its name and `+0x30` supplies
its description. Recipe-less starter Hat, Robe, and Staff therefore display
their names without a fabricated rarity. Potion method `0x00571c80` supplies
the exact descriptions `Restores your health to maximum`, `Restores your mana
to maximum`, `Quadruples the damage of all attacks for 60 seconds`, `Cures
poisoning and grants immunity to poison for 10 seconds`, `Grants concentration
of all skills (at once) for 60 seconds`, and `Restores your health and mana to
maximum` for subtypes 0..5, followed by `Double-click to drink`. The double
activation dispatcher is `0x0056d920`.

That second activation reaches the central inventory-use dispatcher
`0x0056d1b0`; potion use is an authoritative inventory transaction, not a
presentation-only click. Subtype 0 sets current health to maximum, subtype 1
sets current mana to maximum, subtype 2 arms 6000 native ticks (60 seconds) of
four-times attack damage, subtype 3 clears poison and arms 1000 ticks (10
seconds) of poison immunity, subtype 4 arms 6000 ticks (60 seconds) of
all-skills concentration, and subtype 5 restores both health and mana. An
accepted use decrements exactly one stack member and removes/destroys the live
item when the count reaches zero. The accepted branch calls registry sound 24
at `0x0056d246`: `sounds\\drink`, registry member `+0x438`, retail WAV size
32642 and SHA-256
`61fdcc02a31b1c1c43264cb6ed8d02717e9dba2c5123167ad6e309053e28f322`.
These effects, stack ownership, and sound are one branch of the recovered
double-activation seam.

Once pointer travel crosses the native 10-pixel drag threshold
(`_DAT_007de984`), `InventoryDragger`
(`0x00794294`) owns the object: constructor `0x00550990`, update
`0x0056e950`, renderer `0x005579a0`, and pointer move/release members
`0x0055e030`/`0x0056ec30`. The source grid no longer paints the held object.
The dragger paints the class-owned natural-size item icon at the pointer through
shadow, ordinary, and pulsing passes. Every accepting equipment sink becomes
bright green while held. Dropping backpack equipment into one of those sinks
attaches it and reinserts any displaced object into the backpack; dropping
removable equipped equipment into the backpack unequips it; an invalid release
restores the exact source object without a transaction. Live stock witnesses
confirmed all three states with the starter Staff, including its two hand-box
aliases.

The same `InventoryDragger` owns Luthacus transfers. It hides the held item in
the lower backpack or upper StoreGrid, retains the natural-size three-pass icon
at the pointer, and transfers only when released over the opposite owner. This
is not a pair of click-to-move lists: source ownership, 10-pixel drag threshold,
valid opposite-owner sink, invalid restore, and the asymmetric
double-activation branch are one native input system.

Hat and Robe are protected invariants, not ordinary emptyable sinks.
`InventoryScreen::PointerRelease` at `0x0056fc90` rejects a direct removal and
opens MsgBox instead. The hat title is `A WIZARD WOULD NEVER REMOVE HIS HAT!`,
followed by `A wizard might switch hats.  A wizard might even wear his hat at a
jaunty angle.  But a wizard would never, under any circumstances, remove his
hat altogether.` and `After all, if you're not wearing a wizard hat, how would
people know to be awed by the presence of a wizard?`. The robe title is `A
WIZARD WOULD NEVER REMOVE HIS ROBE!`, followed by `A long, intimidating flowing
robe looks debonaire on both a gluttonously fat slob and a pathetically wasted
weakling.` and `Strip away the robe and people might make comments about the
kind of physique you get from years in wizarding school.  And then you'd have a
completely avoidable disintegration on your conscience.` Both use `OKAY` and
the common MsgBox presentation. Dropping a replacement Hat or Robe into its
sink remains valid; only leaving either sink empty is forbidden.

The browser port must therefore render one fixed 1600x900 native stage from
the recovered atlases and bitmap fonts, with transparent semantic hit targets
over the native controls. Visible HTML headings, generic buttons, CSS leather,
CSS gold frames, a 28-cell backpack, visible centre-screen item labels,
procedural equip buttons, or a generic responsive modal do not
satisfy this contract. The common Shop, PerkShop, InventoryShop, both Dowsing
states, all four dialogue introductions/choice branches, the full inventory
screen, Chat scrolling/question states, item details, affordability, selection, transfer,
equip/unequip, close, fade, and interrupted teardown states are one mandatory
presentation membership.

`DowsingShop` owns audio and visual feedback members which cannot be collapsed into button
disabled state. Successful rolling writes `1.0` to `DowsingShop+0x360` at
`0x0055FC18`; `0x005512F0` subtracts the image double `0.05` each 100 Hz tick,
and `0x00551350` draws a full-screen `(1,0,0,alpha)` rectangle. The resulting
red flash lasts 20 ticks, or 200 ms, and belongs to the roll transition rather
than the later item purchase. If the participant cannot pay the roll fee,
`0x0055FAF0` constructs a `MsgBox` with `NOT ENOUGH GOLD!`, the exact
compensation paragraph, and the executable literal `OKAY` at `0x007930D8`;
the transaction remains unchanged. The settled MsgBox is its own authored
composition: UI 107..110 enclose `(522,145.5,556,409)`, a complete
UI-record-17 nine-slice encloses `(540.5,163,519,374)`, and rotated UI record 18
forms the skull header at centre `(800,121)` with visible bounds
`(669,97,262,67)`. Three UI-8
arrows sit at `(800,592)` scale 1 and `(725,579)`/`(875,579)` scale 0.75. The
OKAY control is UI 101 at `(623.5,397.5,353,69)` with UI-54 sides at
`(696,391.5,70,85)` and `(834,391.5,70,85)`. Copy begins at x=609; the title,
body, and OKAY baselines are y=252, y=287.5, and y=440. `UiPanel_Render`
`0x005c3f40` repeats UI 10 along its horizontal edges and UI 79 along its
vertical edges, then draws the UI 107..110 corners. That base pass is not the
whole MsgBox. `HoverBox` construction at `0x005c38f0` writes 1 to the background
flag at object `+0xb8`, and the MsgBox constructor leaves it enabled. The
`0x005c4530` root tests that byte at `0x005c46e5`; its taken branch clips to the
full-alpha layout rectangle inflated by 25 pixels, `(535.5,158,529,384)`, and
repeats UI 49 from that clip's top-left. It then inflates the same layout
rectangle by 20 pixels to `(540.5,163,519,374)` and calls native nine-slice
helper `0x00417760` with UI 17. The UI atlas object array starts at `+0x38` with
stride `0xc4`, so the branch operands `+0x25bc` and `+0x0d3c` resolve exactly to
records 49 and 17; `+0x658` later in the root independently resolves to UI 8.
Thus stock owns both the leather texture and the continuous gold inner rails;
the companion InventoryScreen/service remains visible only outside that filled
clip beneath the 0.75 curtain. The UI-101 button and UI-54 ends are white; only
`OKAY` uses the shared gold text color. Four loose UI-17 corners, a generic
leather panel, or a reused shop button do not reproduce this owner.

Opening the standalone InventoryScreen is silent. The normal keyboard edge at
`0x005CB3A3` and the HUD inventory control callback at `0x005D8165` both call
`0x005C6F10` directly; that opener and constructor `0x00560380` make no sound
request. Registry member 5, `sounds\\backpack_open`, belongs to inventory
mutation paths and must not be inferred from its filename. Shop DONE calls
registry member 64, `sounds\\openpanel`, at `0x0055EFA8` and then tears down
the service. Standalone InventoryScreen close calls that same member at
`0x00555853`. These are `openpanel` requests despite the direction of the
transition; substituting `click` or `backpack_close` changes the retail event
contract.

### 2026-08-22 correction: StoreGrid and owned perks create HoverBox details

The earlier presentation closure recovered delayed InventoryScreen `ItemInfo`
but did not follow the sibling StoreGrid hover slot or the final Hagatha branch
inside the InventoryScreen pointer owner. Calling the Shop family exact without
those branches was wrong. The actual contextual-inspection ownership is:

| Owner | Construction/content path | Input and lifetime |
| --- | --- | --- |
| `HoverBox` | ctor `0x005C38F0`, vtable `0x0079AE14`, render `0x005C3A60`, horizontal/vertical layout `0x005AADE0`/`0x005AB060`, destructor `0x005C39B0` | immediate contextual box; the active object is replaced/destroyed as the current target changes |
| Shop `StoreGrid` | ctor `0x0055C740`, vtable `0x00794B8C`; hover slot `+0xCC -> 0x0055E2C0`; embedded at `Shop+0x9C`, HoverBox at `StoreGrid+0x110` | ordinary current StoreItem builds a box immediately; selected/special StoreItem kind one builds none |
| InventoryScreen `ItemInfo` | ctor `0x00553B80`, vtable `0x007946A4`; common item builder `0x0057C4B0` | selected InventoryGrid object waits 20 native ticks; drag/selection loss destroys it |
| Hagatha owned-perk grid | tail of `0x0056FC90`; current index `InventoryScreen+0x5CC`; temporary Item_Perk ctor `0x00550490`; content `0x00573E90` | only occupied cells in the row-major 3 by 3 progression list; immediate and silent; empty cells/bundle decoration produce nothing |

`0x0055E2C0` destroys the previous `StoreGrid+0x110` box first. For an
ordinary StoreItem it resolves the live item, calls item vtable `+0x2C`, then
tests Shop byte `+0x289`. Ordinary Shop, PerkShop, and DowsingShop leave this
byte set and append a blank plus exact `    Price: %d`; InventoryShop ctor
`0x004F59A0` clears it, so Luthacus item details contain no price. The function
then calls Shop vtable `+0xC0`. PerkShop maps that slot to `0x00554690`, which
adds `    Bulk discount: 50%` for selector `-1`, or
`    High price due to first mixing.` when the selector's
`DAT_0081A39C+selector` flag is clear. A selected StoreItem changes to kind one;
the only branch is the diagnostic literal `Hover over special item!`, not a
tooltip. Shop selection and hover are therefore separate native states.

The common item builder `0x0057C4B0` is broader than the prior Website port:
it emits the case-preserving item name with rarity/set tint, wraps optional
description at 300 pixels, reports an unmet effective player-level requirement,
formats every live item FX through `0x00575C20`, and for a recipe set member
adds `Item Set:`, the set name, every member name, `Complete Set Bonus:`, and
the set FX rows. The format helper's operator prefixes are exact: flat
`+%.1F`/`-%.1F`, multiplier `x%.1F`, and percent
`+%.1F%%`/negative `-%.0F%%`. It covers kinds 1..39; the complete 47 recipe,
seven-set, and 86-FX authored membership remains in
`native-item-catalog.json`. Recipe-less starter Hat/Robe/Staff legitimately
stop after the name; recipe-backed and generated gear do not.

`0x00573E90` owns the complete perk/bundle copy. It first adds the Item_Perk
name, then dispatches all selectors `0..27` and `-1`. Selector 4 and selector
26 add two description lines. Selector 7 adds the base Cheat Death line and,
when its enabled byte is set, either `   Cheats remaining: %d` or
`   Used up!`. Bundle `-1` adds `Get everything the last wizard got.` and
enumerates every selector in `DAT_0081A390/94`. The exact per-selector lines
and dynamic branches are machine-readable in
`native-hagatha-perk-catalog.json`; paraphrased behavior summaries are not UI
copy.

Both HoverBox and ItemInfo paint above their owning surface. `0x005C3A60`
uses an opaque black contextual fill, the native edge pass, and each retained
ExactText DataLine. Layout uses a 25-pixel content/client margin and flips when
the preferred side would overflow the 1600 by 900 client. StoreGrid passes a
35-pixel source gap and retains a 70-square source exclusion; the owned-perk
branch passes 25 and a 60-square exclusion. There is no hover delay and no
audio request. Pointer exit/current-cell change, purchase rebuild, drag,
notice replacement, service close, range exit, region transition, and fade
teardown must not retain the contextual object.

Complete contextual membership is now dispositioned as follows:

| Member | Disposition | Evidence |
| --- | --- | --- |
| Fomentius six Potion subtypes, Misc dye/key, and Sack | `exact-ported` | StoreGrid common slot plus class vtable content |
| Hagatha selectors 0..27 and bundle -1 | `exact-ported`; selector 8 Shop offer remains `out-of-system` because the retail builder excludes it | complete selector switch and catalog |
| Hagatha occupied owned-perk cells | `exact-ported` | `0x0056FC90` 3 by 3 loop |
| Luthacus arbitrary storage items/no-price branch | `exact-ported` | InventoryShop `+0x289 = 0` |
| Shlorio all 47 recipe result offers | `exact-ported` | Dowsing StoreGrid plus complete item catalog |
| All seven item sets and 86 item/set FX rows | `exact-ported` through shared content builder | `0x0057C4B0`, `0x00575C20`, native item catalog |
| InventoryScreen Potion/Misc/Sack/equipment ItemInfo | `exact-ported` | 20-tick ItemInfo path and every class vtable |
| selected Shop special cell, empty owned-perk cells, decorative bundle art | `exact-ported` no-tooltip states | explicit kind-one/empty-loop branches |
| Item base placeholder 7000 and Item_Map 7010 | `out-of-system` (no ordinary descriptive shop/inventory producer) | factory/vtable sweep |
| Item_Misc book subtypes 2/3 | `out-of-system` for the current Website shop producer; exact help strings retained | `0x00570ED0` |

This finding corrects the older table label “detail `0x00565E00`”:
`0x00565E00` participates in Shop control/chrome rendering, while
`0x0055E2C0` plus item vtable `+0x2C` owns contextual content.

### 2026-08-21 correction: the anvil is an unforge sink, not an exit control

The earlier InventoryScreen closure misclassified UI record 75 as the
bottom-right exit control. That visible classification never followed the
record through `InventoryDragger::PointerRelease`, so it omitted an entire
participant-owned transaction and left two of its progression fields marked
unknown. Clean stock and the complete static thread now correct that failure.

The exact evidence target remains retail Beta 0.72.5 `SolomonDark.exe`,
4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred image base `0x00400000`. A direct unmodified PID 8312, with no
loader, injected module, debugger, or constructor helper, created a fresh
Ether/Arcane wizard and exercised the complete recipe-less Staff path. The
committed 1600x900 client-area captures are:

- `tests/fixtures/webgame/menu-reference-captures/inventory-unforge-confirm.png`,
  SHA-256
  `eea3d09bf56a38b352d2c4eb53b47f29e45ff9eb8d941ef9ef0b3f857c4cca7a`;
- `tests/fixtures/webgame/menu-reference-captures/inventory-unforge-result-recipeless-staff.png`,
  SHA-256
  `5da6181a98edb94bd5c0e9fa70e17aa37f311020781ea2e1514e82d4a8dfd4f4`.

Their clean provenance is machine-readable in
`tests/fixtures/webgame/native-inventory-unforge-captures.json`. The observed
transaction moved the starter Staff into backpack slot 2, rejected releases at
right-only `(1550,450)` and bottom-only `(1000,850)`, accepted `(1550,850)`,
displayed the exact two-button confirmation, destroyed the Staff, selected
four gold, and changed the ledger `698 -> 702`. Directly dragging the equipped
Hat to the same point retained `A WIZARD WOULD NEVER REMOVE HIS HAT!`.

#### Target ownership and presentation

`InventoryScreen` root render `0x00568B90` draws UI record 75 from UI object
field `+0x39A4` at settled centre `(1562,868)`. The record is the anvil and
left-pointing arrow; it has no click callback. Its native color multiplier is

```text
red   = sin(native_tick * pi / 180) * 0.2 + 0.6
green = 1
blue  = 1
alpha = InventoryScreen reveal alpha
```

so the source's yellow pixels pulse green-gold over 360 native ticks. A static
white/yellow draw is visibly wrong.

The drop target is not the 68x57 art bounds. `InventoryDragger` update
`0x0056E950` turns on state `+0x99` after an ordinary backpack drag crosses the
lower InventoryScreen boundary, provided source-owner flag `+0x9A` is clear.
Release `0x0056EC30` additionally compares the other coordinate with client
extent minus the exact double 100. Clean boundary probes reconcile those
branches as the bottom-right stage rectangle `(1500,800,100,100)` at
1600x900. An equipped source retains its equipment-removal path; the corner
does not bypass mandatory Hat/Robe ownership.

The first service-companion Inventory may also render
`DROP ITEMS HERE\nTO UNFORGE THEM`. `0x00556940` requires service pointer
`InventoryScreen+0x160`, service byte `+0x289 == 0`, profile tutorial flag
`DAT_0081A3D0`, and `native_tick % 120 < 100`. InventoryScreen destruction
`0x005684C0` clears the flag and calls the profile saver. This is a one-shot
tutorial owner, not an eligibility gate.

#### Complete item and confirmation membership

The exhaustive predicate at `0x00550450` accepts exactly seven live types:

| Class | Type |
| --- | ---: |
| Ring | 7002 / `0x1B5A` |
| Amulet | 7003 / `0x1B5B` |
| Staff | 7004 / `0x1B5C` |
| Hat | 7005 / `0x1B5D` |
| Robe | 7006 / `0x1B5E` |
| Item_Sack | 7008 / `0x1B60` |
| Wand | 7011 / `0x1B63` |

Item 7000, Potion 7001, Perk 7009, Map 7010, and Misc 7012 fall through and
restore normally. A nonempty Item_Sack is rejected after `0x00570C10` and
`0x00552170` inspect its child inventory. An empty Item_Sack skips
confirmation. Every other eligible backpack item constructs MsgBox
`0x004A98E0` with exact lines `REALLY UNFORGE THIS?` and `Unforging grants you
a permanent small bonus to your stats, but utterly destroys the item.`, primary
button `unforge`, and secondary button `cancel`. `Dialog_Finalize 0x005AB5C0`
uses the shared content-sized HoverBox layout; cancel performs no transaction
and consumes no RNG.

That layout is not a fixed result rectangle. `Dialog_AddLine 0x005BCCB0`
measures every authored line, retains the widest value in MsgBox `+0x80`, and
the MsgBox vtable `+0xB4` finalizer at `0x005AB2C0` sizes and centers the
HoverBox from that content. The two clean captures reconcile the exact
1600x900 horizontal rule: the inner panel is the widest rendered line plus
141 pixels, centered at x `801.5`. The confirmation's widest wrapped medium
line is 373 pixels and produces width 514; `STAFF UNFORGED` is 249 pixels and
produces width 390. Result titles and outcomes remain single lines, so longer
generated equipment names widen the panel instead of overflowing it. The
one-button result height is 308 pixels; the three-line confirmation height is
326 pixels.

#### Complete transaction and authored outcome table

Confirmed release calls `0x005D6DF0`. Item_Sack or an eligible item whose
recipe pointer at `+0x74` is null consumes `Integer(4)`, grants `value+2` gold,
and returns `Transmuted to %d gold coins`. It does not increment the unforge
attempt count or enter the bonus selector. The recipe-backed branch repeats:

1. increment progression `+0x874`;
2. draw `Integer(7)` for counts 1..4, `Integer(8)` for count 5, otherwise
   `Integer(count+3)`;
3. values 0..7 enter the table below; a value above 7 consumes `Integer(6)`
   and only value 3 redirects to row 7, while the other five values destructively
   fizzle;
4. row 0 with already-full health and mana through count 5, or row 3 without
   its one-in-100 edge, emits no result and repeats from step 1.

| Selector | Result string | Exact mutation |
| ---: | --- | --- |
| 0 | `Full rejuvenation` | copy maximum HP/MP into current HP/MP; zero global cooldown `+0x64`; zero row `+0x64` for every category-2 skill |
| 1 | `+%d damage for all offensive spells` | add 2 to progression `+0x84` only when count `<5` and `Integer(3)==1`, otherwise add 1 |
| 2 | `-%d mana cost for all spells` | add 2 to progression `+0x88` only when count `<5` and `Integer(3)==1`, otherwise add 1 |
| 3 | `Transmuted to Mind Dredge (+1 skill points at next level)` | require `Integer(100)==25`, then increment deferred skill choices `+0x48` |
| 4 | `+%d to maximum health` | add 10 before count 5; from count 5 add 10 only when `Integer(4)==1`, otherwise 5, to base HP `+0x6C` |
| 5 | `+%d to maximum mana` | add 20 before count 5; from count 5 add 20 only when `Integer(4)==1`, otherwise 10, to base MP `+0x78` |
| 6 | `+%d%% faster experience gain` | through count 4 add 5 or 10 percent with `Integer(2)`; later add 1 or 2 percent; store the fraction in `+0x8C` |
| 7 | `Transmuted to %d gold coins` | grant `(Integer(6)+1)*10`, all values 10..60 |

The result string gates completion; retry rows increment the counter again and
consume their complete later selector sequence. Explicit failure writes
`Unforging fizzles!`. Both success and failure then refresh the progression
owner through `0x0065F9A0`. The caller always destroys the confirmed live item,
rebuilds the InventoryScreen, marks gameplay dirty, and constructs one of two
result families:

- success: `%s UNFORGED`, `Unforging bonus:`, exact result, `OKAY`;
- failure: `FAILED UNFORGING!`, `Spellbreaking fizzles!`, `No bonus`, `OKAY`.

Both result families use the widest-line rule above across title, summary, and
outcome. They are not allowed to reuse the starter Staff's 390-pixel exemplar
as a fixed width.

Registry member 100 at `+0x1148` is `sounds\\unforge`, 134,722 bytes,
SHA-256
`173db629737f50f3a958358dc9f88fb3b25528ee93298f2f95416517747fa9e2`.
It plays for every completed non-fizzle result, including recipe-less
transmutation. Registry member 32 at `+0x598` is `sounds\\fizzle`, 9,072 bytes,
SHA-256
`938420950d859ebc00a9b1a37e548c7c2183a8504689b32aab3de3c683899e76`;
it plays on the destructive failure branch.

These instructions also close two prior class-layout unknowns: progression
`+0x88` is the all-spell flat mana-cost reduction and `+0x8C` is the experience
gain bonus fraction. `+0x874` is the unforge attempt count used by this odds
curve. Those facts are also corrected in `native-class-loadouts.md`.

### Reachable-system membership disposition

This table is the exhaustive retail membership boundary used by the Website
port. `exact-ported` rows require per-member automated coverage and a browser
receipt before that port can claim completion; `verified-already-at-parity`
names pre-existing Website behavior independently covered before this pass.

| Member | Native source | Required disposition | Boundary proof |
| --- | --- | --- | --- |
| Participant gold, backpack, storage, stable item ownership | profile `+0x58`; inventory roots and insertion `0x0055ff20` | exact-ported | authoritative participant component and isolation tests |
| Starter Health/Mana stacks | clean retail new-profile census; Potion 7001 subtypes 0/1 | exact-ported | fresh-player catalog test |
| Fomentius stock: all nine ordered rows | `0x005c8960` | exact-ported | row/range/order and seeded-golden tests |
| Ordinary atomic buy/reject/remove/stack | `0x0056bf70` | exact-ported | success and zero-mutation rejection tests |
| Hagatha selectors 0..27, including dormant selector 8 and bundle -1 | `native-hagatha-perk-catalog.json`; `0x0056c340` | exact-ported (8 out-of-system: excluded by native builder) | 28-row catalog and rebuild/bundle/capacity tests |
| Luthacus asymmetric drag/double-activation transfer | `0x0056cd00`, `0x0056f55a` | exact-ported | both drag directions, storage double-return, backpack normal-use, invalid-restore, no-gold/no-copy tests |
| Shlorio fee, untargeted roll, offer buy, clear, close | `0x0055faf0`, `0x0056d110` | exact-ported | seeded lifecycle tests and two-participant owner-isolation browser receipt |
| All 47 dowsing recipes, seven sets, six equipment classes | `native-item-catalog.json` | exact-ported | complete catalog identity/icon tests |
| Seven equipment sinks and equip/unequip transitions | `0x00570cd0`, `0x00575850`, `0x00570d80`, `0x0066f020` | exact-ported | per-sink and gated-third-ring tests |
| Inventory unforge target, seven eligible types, complete roll table, permanent bonuses, MsgBoxes, and audio | `0x0056E950`, `0x0056EC30`, `0x005D6DF0`; UI 75; audio 32/100 | exact-ported; corrective closure 2026-08-21 | per-type/per-outcome tests, clean-stock captures, Windows browser transaction |
| Common Shop/PerkShop/InventoryShop, both Dowsing states, InventoryScreen, trader Chat, and trader MsgBox views | vtables and renderer family in the correction above | exact-ported; second-pass closure 2026-08-20 | owner-level render/input tests, per-service post-purchase activation, zero-offset deterministic pixel receipt, and full Mac browser acceptance |
| Four exact survival dialogue introductions, reachable commands, and price-return branches | runtime aggregate `data/dialogue/survival.txt`; Chat vtable `0x0079061C`; builder `0x0050b720`; dispatcher `0x004fb890` | exact-ported | dialogue state/copy tests and stock witnesses |
| Fomentius actor/balloon animation | `0x0050b110`, `0x0051c1a0`; College 54..58, 160..164 | verified-already-at-parity | existing hub presentation and render tests |
| Hagatha body/accessory/cross-fade animation | `0x0051adc0`, `0x0051b1d0`; College 45, 89..92, 517..524 | exact-ported | eight-frame and transient-member tests |
| Luthacus common four-frame composite | `0x0050a4c0`, `0x00501610`; College 10, 126..129 | exact-ported | common animator/composite tests |
| Shlorio common four-frame strip | `0x0050a4c0`, `0x00501610`; Library 21..24 | exact-ported | common animator/private-room tests |
| Distance/fade/region interruption and modal teardown | `0x00505010`, `0x00514a20` | exact-ported | range/region/input-block tests |
| Dormant Luthacus random outfit row | scavenger data row; absent executable command/xref | out-of-system (not wired by the retail builder) | literal/xref and builder inspection |
| Dormant targeted-dowsing branch | target `+0x344`; constructor xrefs and union helpers above | out-of-system (no retail hub producer) | constructor/xref/writer sweep |
| All six potion-use effects, stack mutation, and accepted/rejected audio | `0x0056d1b0`, `0x0056d246`, `0x0056d3d2` | exact-ported | per-subtype authoritative inventory/effect/audio tests |
| Ground loot and archive/persistence producer | non-shop inventory consumers | out-of-system (separate gameplay/save systems) | ownership/call-boundary trace |
| Equipment FX application and Clothes attachment painting | 86 declarations and 39 downstream consumers | out-of-system (separate combat/stat/render consumers) | complete item catalog plus consumer trace |
| Annalist, Librarian, Arch Chancellor, Painting common-animator siblings | common animator xrefs outside merchant actors | out-of-system (non-trader services/props) | complete `0x00501610` xref sweep |

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
