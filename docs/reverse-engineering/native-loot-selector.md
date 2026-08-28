# Native loot and reward selector

## Result and scope

This is the stock loot contract for the retail `SolomonDark.exe` whose
SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
It is sufficient to rebuild the decision, materialization, collision placement,
amount, ground motion, lifetime, presentation, notification, and crediting
behavior without opening the executable. Post-pickup Potion consumption remains
the downstream item-system boundary.

There are two random domains, and treating them as one is a determinism bug:

1. `Enemy_SelectDeathDrop (0x0047C070)` constructs a fresh private
   `0xE8`-byte RNG on its stack and seeds it from the dying actor's
   `actor+0x1C0`. Category eligibility, category choice, and the final orb
   kind/value/phase use this private stream.
2. Constructors and category materializers use the process's active shared
   stream through `[0x00818B08]`. This covers the emergency-health pre-check,
   gold amount/chunking, potion subtype, item recipe/equipment choice, Bonus
   kind, Goodie contents, and presentation scatter. These shared draws do not
   become private merely because they happen inside the death call.

The shared-global determinism result in
[`native-movement-and-tick.md`](native-movement-and-tick.md) therefore does
**not** imply loot lockstep. The source actor seed is authoritative state.

The ground actors are outcomes, not enemies and not secondary selectors:
Orb `2011/0x7DB`, Gold `2012/0x7DC`, Sack `2013/0x7DD`, and Bonus
`2038/0x7F6`. Their object layouts and art territory begin in
[`native-items-equipment-and-loot.md`](native-items-equipment-and-loot.md).

## RNG primitive used by every table

`NativeRng::Integer (0x00401170)` is biased for non-power-of-two bounds. For a
positive bound `n`, let `P` be the smallest power of two at least `n`, starting
at 2. One 30-bit lagged-Fibonacci word `u` is consumed and the result is:

```text
Integer(n) = ((u >> 6) & (P - 1)) % n
```

Consequently result `r` has
`floor((P - 1 - r) / n) + 1` preimages out of `P`. All probabilities below
mean this primitive, not an ideal uniform integer. `Integer(0)` returns zero
without a useful choice. The float primitive at `0x00401310` consumes
`Integer(100001)`, rounds to float32 after integer conversion, division, and
multiplication, and includes both endpoints. Signed floats consume a second
word for their sign. The bit-exact rounding schedule and goldfix goldens are
the reference; do not replace it with a double-precision expression.

## Actor-private seed lifecycle

<!-- LOOT_ACTOR_SEED_LIFECYCLE_BEGIN -->

The base hostile constructor `Badguy_Ctor (0x00473390)` calls
`active_shared.Integer(10000000, false)` and writes the result to
`actor+0x1C0` at `0x0047345E`. The bound is ten million, not one million.
`Enemy_SelectDeathDrop` later performs this exact lifecycle on each call:

```text
NativeRng private_rng                 // 0xE8 bytes on caller stack
NativeRng_Constructor(&private_rng)   // call at 0x0047C0CF
NativeRng_Seed(&private_rng,
               dying_actor.seed_1c0) // call at 0x0047C0DF
... private category draws ...
destroy private_rng                   // no state copied back
```

The seed written by construction is not immutable for every family:

| Family | Type | Seed at death |
| --- | ---: | --- |
| Badguy | 1000 / `0x3E8` | Base-constructor shared `Integer(10000000)`; no later writer recovered. |
| Skeleton | 1001 / `0x3E9` | Slot-0 action scheduling at `0x00473980` replaces `+0x1C0` with shared `Integer(10000000)` at `0x004739D1`. |
| SkeletonArcher | 1002 / `0x3EA` | Corrected by the 2026-08-27 volley drain: slot-0 scheduling at `0x00473B40` replaces it with shared `Integer(1000000)` at `0x00473B60`; the value is also the private volley seed consumed by `0x00477B90`. |
| SkeletonMage | 1003 / `0x3EB` | Slot-0 scheduling at `0x00478290` replaces it at `0x004782B7`; cast scheduling in `0x00490860` replaces it again at `0x004909D0`. Both use shared `Integer(10000000)`. |
| Imp | 1004 / `0x3EC` | Base-constructor seed only. |
| Zombie | 1006 / `0x3EE` | Base-constructor seed only. |
| Wraith | 1007 / `0x3EF` | Base-constructor seed only. |
| DemonSkull | 1008 / `0x3F0` | Base seed, then scheduler `0x00474930` increments `+0x1C0` by exactly one rather than drawing the shared stream. |
| Demon | 1009 / `0x3F1` | Base-constructor seed only. |
| DireFaculty | 1010 / `0x3F2` | Base-constructor seed only. |
| Heartmonger | 1011 / `0x3F3` | Base-constructor seed only. |
| Coffin | 1013 / `0x3F5` | Base-constructor seed only. |
| GreenImp | 2044 / `0x7FC` | Base-constructor seed only. |
| Spider | 2057 / `0x809` | Base-constructor seed only. |
| Portal | 5021 / `0x139D` | Base-constructor seed only. |

GoodImp `1005/0x3ED` and Crow `1012/0x3F4` never enter the hostile reward
path. Maggot `2045/0x7FD` and Cocoon `2058/0x80A` call the death path but
return from `0x0047C070` before the private RNG is even constructed. The full
family behavior catalog is
[`native-enemies.md`](native-enemies.md); the live state-machine cross-check is
[`native-enemy-behavior.md`](native-enemy-behavior.md).

Every private roll below is seeded by the actor named in this table at the
moment of death. Every shared roll instead continues whatever state the active
process-global stream has at that call; its startup/level-generation seed
lifecycle is documented in `native-movement-and-tick.md` and is not replaced
by `actor+0x1C0`.

<!-- LOOT_ACTOR_SEED_LIFECYCLE_END -->

## Enemy drop decision

### Inputs and early exits

The selector reads the source's `MonsterRecipe` pointer at `actor+0x1D0`.
A null pointer is legal and means six zero/default policies; this is the same
null-config boundary whose missing guard caused the invincibility-potion
`potiondrop` crash. Policy bytes are:

| Recipe offset | Policy |
| ---: | --- |
| `+0xCC` | orb |
| `+0xCD` | powerup |
| `+0xCE` | item/equipment |
| `+0xCF` | gold |
| `+0xD0` | specific-item/rarity selector passed to the item materializer |
| `+0xD1` | potion |

For category policies, `0` is ordinary, `1` halves the ordinary chance by
doubling its bound, `2` doubles it by halving the bound, `3` is forced, and
`4` disables the category. Gold policy `5` is an extra special case described
below. Arena `+0x8F04` independently suppresses gold/potion/powerup/orb/key/item
with bits `0/1/2/3/4/5` respectively.

If recipe byte `+0x54 == 2`, `0x00467FE0` checks the associated special-hostile
population. A nonzero result arms `special_suppression`: normal gold, item, and
the policy-5 gold bonus are suppressed while orb, potion, powerup, and key
remain eligible. The actor's `+0x160` context is retained for the policy-5
gold call.

### Emergency health-potion short circuit

Before the private candidate table, the active shared stream is used if none
of orb, gold, potion, or item is policy `3` and gold is not policy `5`:

1. `shared.Integer(2) == 0` (`1/2`);
2. only then, `shared.Integer(10) == 1` (`2/16 = 1/8` under the native bias).

The joint gate is exactly `1/16`. If it misses, ordinary candidate evaluation
continues. If it hits, the function returns after the following attempt even
when no potion was created:

- active `Badguy` count at `0x0081984C` must be greater than 79;
- recursive player inventory must contain no health potion;
- the world must contain no Sack whose held item is a subtype-0 health potion;
- a mask-2 query with 500-unit **diameter** around the dying actor must return
  more than 49 entries. Query `0x00642280` halves the supplied width, so this is
  strict center radius 250, and its exclusion argument removes the dying actor;
- then Arena vtable `+0x148` is called with potion subtype 0.

The two rolls and all checks are shared-stream behavior. They do not advance
the actor-private stream because that stream has been seeded but not yet drawn.

### Candidate construction and choice

<!-- LOOT_SELECTOR_TABLES_BEGIN -->

Candidates are considered in exactly this order:

```text
key -> orb -> gold -> item -> potion -> powerup
```

Each eligible category appends one pointer to the candidate list. After all
tests, an empty list means no drop. A nonempty list consumes
`private.Integer(candidate_count)` and dispatches exactly one entry. Native
choice-index weights are:

| Candidate count | Index weights |
| ---: | --- |
| 1 | `1` |
| 2 | `1,1` out of 2 |
| 3 | `2,1,1` out of 4 |
| 4 | `1,1,1,1` out of 4 |
| 5 | `2,2,2,1,1` out of 8 |
| 6 | `2,2,1,1,1,1` out of 8 |

The first candidates are therefore favored for list sizes 3, 5, and 6. Do not
use a uniform array picker.

For a non-forced category the selector computes the listed float bound, lets
the Arena virtual modify it, multiplies by the active participant progression
field when active participant index `0..3` exists, truncates toward zero, and
then appends when either `bound <= 0` or `private.Integer(bound) == 1`.

| Order | Candidate | Gate and exact bound before final truncation | Stream/target |
| ---: | --- | --- | --- |
| 1 | key | mask bit 4 clear; `0x00463500` requires `Arena+0x905C <= Arena+0x8FF0` and `Arena+0x9060 > 0`; `bound = trunc(((trunc((arena_level - 20) / 5)) + 10) * 100)` | private `Integer(bound) == 2` |
| 2 | orb | mask bit 3 clear; policy not 4; ordinary base `8/16/4` for policy `0/1/2`; Arena vtable `+0x130`; multiply progression `+0x804`; policy 3 appends without a roll | private target 1 |
| 3 | gold | mask bit 0 clear; policy `<4`; no special suppression; ordinary base `11/22/5.5`, then multiply by 2 -> `22/44/11`; Arena `+0x134`; progression `+0x808`; policy 3 appends without a roll | private target 1 |
| 4 | item | mask bit 5 clear; policy not 4; no special suppression; ordinary base `30/60/15`, then multiply by 12 -> `360/720/180`; Arena `+0x13C`; progression `+0x80C`; policy 3 appends without a roll | private target 1 |
| 5 | potion | mask bit 1 clear; policy not 4; ordinary base `50/100/25`, then multiply by 8 -> `400/800/200`; policy 3 appends only while scene `+0x1CD0` is nonzero | private target 1 |
| 6 | powerup | mask bit 2 clear; policy not 4; participant level must be greater than 1 and not divisible by 5; level base below, policy 1 multiplies by 2 and policy 2 by 0.5, then multiply by 9; Arena `+0x138`; progression `+0x810`; policy 3 bypasses level and roll | private target 1 |

Arena's ordinary orb/gold/powerup virtual is the no-op `0x0042E260`. Its item
virtual `0x00463380` multiplies the bound by 200 when arena level is below 5,
always by 2, and by 2 again when `Arena+0x8FF0 != Arena+0x9064` (the last
successful item-drop level). Thus the live level-0/last-level-`-1` corpus has
an item bound of `360 * 200 * 2 * 2 = 288000`; a successful item writes the
current level to `+0x9064`.

Powerup level bases before policy and `*9` are:

| Participant level | Base |
| --- | ---: |
| 2..10, excluding 5 and 10 | 75 |
| 11..15, excluding 15 | 77 |
| 16..20, excluding 20 | 82 |
| 21..25, excluding 25 | 92 |
| 26..30, excluding 30 | 102 |
| 31..35, excluding 35 | 117 |
| 36+ when not divisible by 5 | 137 |

For reference, ordinary unmodified target-1 chances are orb `1/8`, gold
`1/16` (bound 22), item `1/256` before Arena/progression modifiers (bound
360), and potion `1/256` (bound 400). Policy-1 chances for those same bases are
`1/16`, `1/32`, `1/512`, and `1/512`; policy-2 chances are `1/4`, `1/8`,
`1/128`, and `1/128`. The formula above, rather than these examples, is the
contract after modifiers.

Dispatch is then:

- key -> `0x00468440`;
- orb -> factory type 2011, overwrite kind/value/phase through `0x005E1220`
  using the still-live private stream, optional `progression+0x814` value
  multiplier, then world registration;
- gold -> Arena vtable `+0x144` / `0x0046AA90` with amount sentinel `-1`;
- item -> Arena vtable `+0x140` / `0x0046A360`, passing recipe `+0xD0` mode;
- powerup -> factory type 2038 and world registration;
- potion -> one final **shared** `Integer(2)`, then Arena vtable `+0x148` /
  `0x0046AE20`.

Key and orb dispatch occur for every source slot. Gold, item, powerup, and
potion dispatch are inside `actor+0x5C == 0`; a non-slot-0 hostile can consume
the private decision and produce nothing for those four categories.

Gold policy `5` does not enter the normal gold candidate test. If some other
candidate exists and is selected, and special suppression is clear, it also
consumes a shared signed presentation float in `[0.9,1.1]` and calls the gold
materializer with explicit base amount 1000 and the saved `actor+0x160`
context. With an empty candidate list it produces no gold.

<!-- LOOT_SELECTOR_TABLES_END -->

## Amounts and subtype selectors

<!-- LOOT_AMOUNT_TABLES_BEGIN -->

### Orb kind, value, and credit

Factory construction initially consumes the active shared stream for a default
kind, value, and phase. The enemy selector then calls `0x005E1220` while its
private RNG is active and overwrites all three; those constructor draws remain
spent on the shared stream.

The final private draws are:

1. `Integer(3)`: result 1 means health; results 0 or 2 mean mana. Because the
   native weights are `2,1,1` out of 4, health is `1/4` and mana is `3/4`.
2. unsigned `FloatScaled(0.45)`, then float32 addition of `0.25`: raw value is
   inclusive `[0.25, 0.70]`. The underlying `Integer(100001)` gives outputs
   `0..31070` two preimages and `31071..100000` one preimage out of 131072.
3. unsigned `FloatScaled(360)` for phase only.

If active progression byte `+0x814` is set, raw value is multiplied by 1.25,
making the inclusive range `[0.3125, 0.875]` after native float32 rounding.
On slot-0 capture, health adds `remaining_value * 25`; mana adds
`remaining_value * 40`.

### Gold quantity and chunk distribution

`Arena_CreateGold (0x0046AA90)` uses the active shared stream. For sentinel
amount `-1` and arena level `L`:

```text
q = max(1, trunc(L / 5))
x = shared.Integer(trunc(L / 2) + 6)
r = x + q
if r == 1 and shared.Integer(3) != 2:
    r = 2
total = trunc(progression_slot0.gold_multiplier_at_0xC0 * r)
```

At stock level 0 with multiplier 1, the exact total distribution is:

| Total gold | Weight |
| ---: | ---: |
| 1 | `1/16` |
| 2 | `7/16` |
| 3 | `1/8` |
| 4 | `1/8` |
| 5 | `1/8` |
| 6 | `1/8` |

For an explicit amount, including crate gold and policy-5 amount 1000, the
same progression `+0xC0` multiplier and truncation apply, but the level draw is
skipped. If that post-multiplier total is zero or negative, the chunk loop
emits no actors. The later unused sorter-probe Gold is still constructed, so
its four RNG words remain spent even for an empty explicit result.

The total is emitted as Gold actors until no remainder is left. Nominal chunk
size is `min(remaining, 25)`. Only when the original explicit amount is greater
than 25, each chunk first rolls shared `Integer(2) == 1`; on a hit its size is
replaced by `shared.Integer(floor(nominal / 2)) + 1`. The chosen chunk is
subtracted from the remainder, so chunk randomization changes actor count and
per-actor amounts but never the total. Amount `<3`, `<5`, `<8`, or otherwise
maps to visual tier 0, 1, 2, or 3. Each Gold constructor consumes shared
`Integer(100000)`, `Float(360)`, and signed `Float(20)`, then placement consumes
`Float(3)+1` before any blocked-ring draws. After constructing chunk six and
every later chunk, shared `Float(0.04)` is stored after adding double
`0.009999999776482582`, multiplied by timing scalar 100, truncated, and added
to the delay used by the next actor: an increment of 1..5 ticks.

After the chunk loop, `0x0046AA90` constructs one otherwise-unused stack Gold
solely so generic sorter `0x00428A60` can recover field offset `+0x1C`; its four
constructor words remain spent. The actor list is stable-sorted by world Y.
During registration, each actor whose accumulated delay is still zero consumes
shared `Float(0.25)`, multiplies by 100, and truncates to 0..25 ticks. These are
authoritative delays and RNG edges, not client presentation jitter.

### Collision-aware ground placement

`0x00645910` first tests the supplied point. Potion and Item use one radius-15,
mask-4 pass; Key uses two consecutive radius-15, mask-4 passes. Gold draws its
radius as `Float(3)+1` and passes mask `0x404`, adding `0x00645820`'s dynamic
actor-overlap ellipse. That ellipse scales both candidate and resident radii in
Y by exact double `0.800000011920929`.

When the origin is blocked, search radius begins at the supplied radius. Each
ring consumes shared `Float(360)` for its start angle, uses
`trunc(pi*(search_radius+base_radius)/search_radius)` samples, and scales its Y
radius by `0.800000011920929`. A failed ring adds `growth*base_radius`; shared
`Float(1)+1` then multiplies `growth` for the following ring. Leaving drops at
the source point and spending none of these conditional words is correct only
when the native collision tests accept that point.

### Potion selection, including invincibility

Normal enemy-potion dispatch consumes shared `Integer(2)`: subtype 0 health
and subtype 1 mana are each exactly `1/2`. `Arena_CreatePotion (0x0046AE20)`
forces subtype 0 whenever scene `+0x1CD0` is nonzero. The result is one Sack
actor holding one type-7001 Potion.

The stock enemy selector cannot choose stock subtypes 2..5 and has no subtype
6. Loader invincibility subtype 6 is an additive `HookEnemyDeath` path from the
`potiondrop` work. Its prior null-`actor+0x1D0` dereference was fixed by making
the registered-potion hook accept the same legal null config as stock. It is
not inserted into this stock 0/1 selector. Potion presentation, inventory art,
and VFX duration remain owned by `potionvfx`/G4/G9.

### Item and equipment selection

Enemy item dispatch uses `Arena_SelectAndDropItem (0x0046A360)`, not only the
simpler definition selector `0x0046BDE0`. It builds candidates from the global
`ItemRecipe`/`ItemSet` stores documented in
[`native-items-equipment-and-loot.md`](native-items-equipment-and-loot.md),
filters recipe level to inclusive `Arena+0x8F0C..+0x8F10`, filters recipes
already owned or excluded by scenario state, and interprets recipe `+0xD0`
mode as:

| Mode | Definition rarities entered |
| ---: | --- |
| 0 | common always; rare when shared `Integer(15) == 1`; epic when shared `Integer(20) == 1` |
| 1 | common |
| 2 | rare |
| 3 | epic |
| 4 | rare and epic |

If no candidate survives and Arena mode `+0x8F08 == 1`, the selector retries
the other relevant rarity lanes. When Arena mode is not 1 and requested mode
is 0 or 1, it also appends exactly 110 placeholder entries. One active-shared
`Integer(candidate_count)` selects the entry. A real recipe is cloned by
`0x004699B0`; a placeholder calls random-equipment factory `0x004645B0`.

Random equipment starts with shared `Integer(6)`. Because its power-of-two
mask is 8, classes 0 and 1 each weigh `2/8`, while classes 2, 3, 4, and 5 each
weigh `1/8`; subsequent selector, color, and synthesized-FX rolls are also
shared. A successful carrier writes its exact recipe/type/selector/colors and
updates `Arena+0x9064` to the current arena level.

`RandomEquipment_AddFX (0x0057A000)` chooses one or two unique selectors from
0..24 and owns three distinct skill target pools through `0x00579E90`. A
second selector is possible only when the requested level is greater than 18:
it tests `Integer(2)==1`, then on a miss `Integer(5)==3`, then on a second miss
`Integer(10)==3`. Levels 18 and below never enter any of those three draws.
Choosing two immediately writes generated item level `+0x5A = 8` before any
selector-specific adjustment.

The skill pools are:

- selector 6 uses mode 0: compiled row byte `+0x28` is nonzero;
- selector 8 uses mode 1: `+0x28` is nonzero or category `+0x26 == 3`;
- selector 9 uses mode 2: every enabled row 8..79.

Rows 72..79 first require their corresponding compiled advanced-unlock byte.
The generated item's level byte `+0x5A` starts at zero, becomes 8 for a
two-effect item, and selector 8 raises it to at least the selected row's
compiled minimum level at `+0x2C`. Selector 9 formats the
native skill name and `of %s`, never a numeric placeholder. Hat/Robe selector
exclusions are `2,3,8,9,12,13,17,21,22`. Magnitude halving and tie-to-even
rounding occur only in switch branches
`0..6,10..13,17..24`; allowed wearable families 7,14,15,16 remain unhalved.

Hat/Robe color factory `0x004630E0` uses this exact nine-row palette:
`(1,0,0)`, `(1,.5,0)`, `(1,1,0)`, `(.25,1,.25)`, `(.25,1,1)`,
`(.25,.25,1)`, `(1,.25,1)`, `(.4,.4,.4)`, `(.8,.8,.8)`. A 50-percent branch
adds three independent signed `Float(.1)` values. A one-in-four branch multiplies
RGB by `1.85`; both steps clamp. `0x0040FC60` then blends 80 percent toward
luminance weights `.3086000085/.6093999743/.0820000023`. The second wearable
layer is separately constructed white and remains white.

Goodie's definition-backed bucket instead calls `0x0046BDE0` with mode 4. It
uses the same global recipe stores, ownership/level filtering, active-shared
rarity gates, active-shared candidate choice, and recipe clone, but has no 110
random-equipment placeholders.

### Bonus powerup kind

The Bonus constructor uses two active-shared draws. First `Integer(3)` has
weights `2,1,1`; then `Integer(2) == 1` overwrites the first result with kind 2.
Final weights are:

| Kind | Result | Weight |
| ---: | --- | ---: |
| 0 | bonus skill point | `1/4` |
| 1 | random learned-skill rank | `1/8` |
| 2 | damage x4 | `5/8` |

### Key

The key materializer produces one Sack containing `Item_Misc 7012/0x1B64`,
subtype 1 (`Wizard Key`). `Arena+0x905C` is the next arena level eligible for a
key, not a carrier delay. Arena load `0x0046DC60` seeds it with active-shared
`Integer(8)+5` (5..12). On a key drop `0x00468440` advances the threshold:
while it is below 13, `Integer(11)+15` (15..25); while below 26,
`Integer(11)+30` (30..40); through 40, `Integer(21)+50` (50..70); above 40 it
remains unchanged. The function applies two collision-aware radius-15 placement
passes, then creates exactly one key; it does not randomize quantity or write a
Sack activation delay.

<!-- LOOT_AMOUNT_TABLES_END -->

## Non-enemy reward sources

<!-- LOOT_SOURCE_TABLES_BEGIN -->

### Goodie/crate

Goodie actor `2061/0x80D` (`0x005E3D60`, tick `0x0061F4C0`) draws
`shared.Integer(1000)` at construction and stores it at `+0x148`. Activation
sets `+0x143`; effects occur at timers 100 and 200, and the contents resolve at
timer 250 from `stored_seed % 18`. Because `Integer(1000)` uses a 1024 mask,
the exact remainder weights for selectors 0..17 are:

```text
58,58,58,58,58,58,57,57,57,57,56,56,56,56,56,56,56,56
```

The content table is:

| Selector | Weight / 1024 | Contents and further shared rolls |
| --- | ---: | --- |
| 0..3 | 232 | exactly five health potions (subtype 0) |
| 4..7 | 230 | exactly six mana potions (subtype 1) |
| 8..9 | 114 | two random-equipment items, plus a third iff `Integer(2) == 1`; each level is slot-0 level plus `Integer(5)`, whose offset weights are `2,2,2,1,1` out of 8 |
| 10 | 56 | one definition-backed mode-4 item through `0x0046BDE0` |
| 11..12 | 112 | exactly three Item_Misc books; each subtype is `Integer(2)+2`, so subtype 2/3 is `1/2` each |
| 13..16 | 224 | explicit base gold `Integer(3)*300+500`: 500 with `1/2`, 800 with `1/4`, 1100 with `1/4`; 1400 is impossible |
| 17 | 56 | six potions in exact subtype order `5,0,1,4,2,2` |

The Goodie creates a Sack only if the constructed inventory is nonempty. The
selector-17 native implementation allocates four subtype-unset Potion objects,
retains only the last, then assigns subtype 5 before building the intended six
entries. The first three are leaks, not observable rewards; a browser port
must produce the six listed potions without reproducing allocator garbage.

Those table rows describe the construction sequence, not the finished live
child list. Every Goodie insertion calls `0x0055FF20` with both boolean
operands equal to one (`0x0061FAB3..0x0061FABA` and sibling sites), enabling
Potion-only same-subtype stacking. The final Item_Sack root therefore contains
one subtype-0 Potion with count 5 for selectors 0..3, one subtype-1 Potion with
count 6 for selectors 4..7, and selector 17 contains subtypes `5,0,1,4,2` with
counts `1,1,1,1,2`. All constructed and leaked Potion objects still consume
their live UIDs before merging/destruction; only the first same-subtype node
survives.

### Ground actors and script drops

Types 2011, 2012, 2013, and 2038 do not reroll a category when ticked. They
carry the kind/amount/item already chosen by an enemy, Goodie, or script.
Direct construction does still have the constructor draws named above: Orb
defaults and Bonus kind use shared RNG, Gold uses shared presentation RNG, and
Sack owns a preselected item.

Boneyard actions `DROP ITEM` 1008, `DROP RANDOM ITEM` 1015, `DROP GOLD` 1016,
`DROP RANDOM GOLD` 1017, `DROP POTION` 1059, and `DROP KEY` 1086 bypass
`0x0047C070`. Explicit operands remain explicit; random forms enter their
category materializer on the active shared stream. `LIMIT DROPS` 1018 and
`ENABLE/DISABLE DROPS` 1087 alter Arena policy/mask state consumed by later
enemy decisions. The action grammar and recipe/UIDGroup stores are already
fixed in [`boneyard-scripting.md`](boneyard-scripting.md); they are data inputs,
not a third loot RNG. Their exact helpers are `0x00469FE0`, `0x00466D20`,
`0x00466D90`, `0x00466DF0`, `0x00462690`, `0x00466B50`, `0x0046A0F0`, and
`0x00463520`. Random Gold selects inclusive `[min,max]` with one shared
`Integer(max-min+1)` when endpoints differ. `LIMIT DROPS` writes Arena mode and
either `[-9999,9999]`, one repeated item level, or an explicit min/max pair.
Enable operand zero clears the supplied disable-mask bits; nonzero sets them.
Direct Key does not advance the enemy key threshold. Direct/random Item updates
the last-item level as described by its helper.

### Solomon Dig

The G8 fixture contains eight independent live completions of the stock
Courtyard Solomon Dig sequence. Every trial changed the native dig state to
complete but had zero gold delta, unchanged inventory, and zero delta for
reward actors 2011/2012/2013/2038. G7 embeds the first complete sequence and
compares it byte-for-byte with
`tests/fixtures/webgame/hub-economy-goldens.json`; Dig is not a stock reward
source in that route.

### Wave end

No generic wave-end ground reward exists. A complete reference census for
Bonus type 2038 reaches only its constructor and the enemy-selector allocation
at `0x0047CA03`; no wave-end producer references it. Enemy XP and death loot
are accounted per enemy. A Boneyard END WAVE trigger may explicitly run one of
the script-drop actions above, but that is scripted action data, not an
implicit wave bonus.

<!-- LOOT_SOURCE_TABLES_END -->

## Magnet, pickup, lifetime, and field capacity

<!-- LOOT_PHYSICS_TABLE_BEGIN -->

All distances are center-to-center world units and all comparisons are strict
`distance_squared < radius_squared`. `pickup_factor` is progression `+0xCC`;
the captured stock value is 1.25. `orb_pull_multiplier` is progression
`+0xBC`; the captured value is 1.0.

| Family | Attraction and capture | Lifetime |
| --- | --- | --- |
| Orb 2011 | Scans participant slots 0,1,2,3 in ascending order. Pull radius = `60 * pickup_factor * orb_pull_multiplier`; capture radius = `20 * pickup_factor`. Between them, normalize the current delta and move exactly 1.5 units toward that slot per actor tick. There is no velocity state, acceleration, easing, or overshoot clamp. Multiple in-range slots can each move it during one tick. | `+0x144` starts 900 and decrements every actor tick. When the post-decrement timer is below 1, remaining `+0x140` loses float32 0.002 each tick and deletes at `<=0`. Attraction runs only while remaining is strictly greater than 0.01. With raw values `[0.25,0.70]`, untouched lifetime is exactly 1024..1250 actor ticks, endpoint dependent. |
| Gold 2012 | No magnet. Slot 0 only; capture radius = `30 * pickup_factor`. If `pickup_factor > 1.25999999`, an in-range tick additionally needs shared `Integer(15) == 1`, exactly `1/16`; stock 1.25 bypasses this gate. | No despawn timer. `+0x144` is an activation/scatter delay that decrements through zero, not lifetime. Persists until pickup, scene teardown, or failed ownership. |
| Sack 2013 | No magnet. Slot 0 only; capture radius = `30 * pickup_factor`. Initial bounce is height `+0x140 = -25`, velocity `+0x144 = 0.1`; after delay `+0x14C`, each tick adds velocity to height and multiplies velocity by 1.5, clamping both to zero once height becomes positive. | No despawn timer. Persists like Gold. This covers potion, item, key, and Goodie carriers. |
| Bonus 2038 | No magnet. Slot 0 only; capture radius = `20 * pickup_factor`. | `+0x154` starts 1200. Once its post-decrement value is below one, alpha `+0x15C` loses float32 `0.009999999776482582`. Float residue needs 101 fade updates, so untouched retirement is update 1300. |

Orb capture always deletes the actor, but the health/mana write is guarded by
`slot_index == 0`. Thus a nonzero slot can consume an orb for no credit. The
ascending scan means slot 0 wins if it is already inside capture range; if slot
0 is outside capture and a later slot is inside, that later slot destroys it
without receiving the resource. Gold/Sack/Bonus never inspect slots 1..3.

World allocator `0x0063E750` owns IDs 1..2047 independently per owner slot. It
advances round-robin and scans at most 2048 candidates; if all are occupied it
returns `-1`. Registration `0x0063F6D0` then fails. It never evicts an existing
drop, never replaces the oldest reward, and has no loot-specific sub-cap.
Bonus's per-frame render vector is dynamically grown and is not another field
cap.

<!-- LOOT_PHYSICS_TABLE_END -->

## Multiplayer authority and credit

<!-- LOOT_MULTIPLAYER_RULE_BEGIN -->

Retail Solomon Dark has no native network authority. In one process, Gold,
Sack, and Bonus are hard-wired to local slot 0; Orb scans four slots but only
credits slot 0 as described above. The single gold scalar and inventory root
make per-peer native simulation unsuitable for a port.

The current loader resolves the gap host-side:

1. The host alone runs enemy death selection and materializes the authoritative
   native reward. Clients suppress local death loot.
2. Host `LootSnapshot` state supplies stable drop id, kind, amount/value,
   held-item identity, position, lifetime, and active state. Clients materialize
   pickup-suppressed presentation actors; they do not roll the selector.
3. A remote participant submits a pickup claim. The host validates run nonce,
   drop identity/active state, participant state, stock-family pickup radius,
   and reported-position drift, then queues native actor retirement.
4. The first path that retires/accepts the drop receives credit. A pending or
   retired drop makes later claims `AlreadyGone`. There is no nearest-player
   comparison and no distance ranking among valid claimants.

Host-local slot-0 stock pickup and a remote claim can therefore race in update
order. The two-participant live golden puts the host 18 units from an 11-gold
drop and the client only 6 units away, both inside the 37.5-unit stock radius;
the farther host gains all 11 and the client receives `AlreadyGone`. This pins
first retirement rather than nearest participant. Accepted remote gold instead
credits only the requesting participant's owned ledger, not host global gold.

A browser rebuild must roll once on its server/host, replicate the resulting
drop, and serialize accepted pickup/retirement. Rolling `0x0047C070` per peer
will diverge even when the shared global stream matches because its seed is the
host actor's private lifecycle state. For deterministic simultaneous browser
inputs, preserve one canonical server processing order; do not invent
nearest-player arbitration.

<!-- LOOT_MULTIPLAYER_RULE_END -->

## Complete ground-loot presentation and modifier ownership

The 2026-08-16 closure pass rechecked the retail image and the existing G7
capture against the preserved 4,723,200-byte executable (SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`).
Headless Ghidra project `Decompiled Game/ghidra_project/SolomonDark` was opened
read-only as program `SolomonDark.exe`; the renderer, pickup, Goodie, and
progression-finalizer functions below were decompiled from that same image.
This closes the presentation and purchased-drop-modifier rows that the original
selector report deliberately left to G4/G9.

### System boundary and membership

Native system: the reward system begins with an enemy/private selector, an
explicit Boneyard drop action, or an active Goodie, owns the materialized
ground actor through render/tick/pickup/destruction, and ends after currency,
resource, inventory, or Bonus credit is applied.

| Member | Native owner | Recovered disposition |
| --- | --- | --- |
| Enemy selector and emergency health-potion lane | `0x0047C070` | complete: all six policy bytes, masks, private/shared draws, candidate weights, slot gates, and special suppression |
| Gold | ctor `0x005E12C0`, tier `0x005E13C0`, tick `0x005E66B0`, draw `0x0060FFE0` | complete: amount/chunks, four tiers, scatter, persistence, pickup, feedback, art, and audio |
| Health and mana Orb | ctor `0x005E1150`, overwrite `0x005E1220`, tick `0x005E62E0`, draw `0x0060FC10` | complete: private kind/value/phase, pull/capture, decay, credit, art, and audio |
| Potion carrier | materializer `0x0046AE20`, Sack ctor/tick `0x005E1460`/`0x005E6B50` | complete: subtypes 0/1, bounce, potion glyph, transfer/stack, and drop/pickup audio |
| Equipment/item carrier | selector `0x0046A360`, definition clone `0x004699B0`, random equipment `0x004645B0`, Sack actor | complete at the ground-loot boundary: definition/placeholder selection, exact live item identity, carrier art, ownership transfer, and audio; equipped FX consumers remain the item system documented in `native-items-equipment-and-loot.md` |
| Key carrier | `0x00468440`, Item_Misc subtype 1, Sack actor | complete: candidate gate, delay bands, carrier art, one-item credit, and shared Sack audio |
| Bonus kinds 0/1/2 | ctor `0x005E2D90`, tick `0x006039C0`, apply `0x005D5910`, draw `0x0061A260` | complete: biased kind weights, 1200-tick full-alpha countdown plus 101-update float32 fade, pickup, three effects, art, and feedback |
| Goodie unlock and selectors 0..17 | Region `MyCollider` callback `0x00646D00`, activation `0x005F0E50`, ctor/setup `0x005E3D60`/`0x005E3E40`, tick `0x0061F4C0`, draw `0x0061F070` | complete: local-player class 101, facing probe, recursive Wizard Key check/removal, nearest unopened Goodie, timers 100/200/250, all eighteen rows, materialization, art, and teardown |
| Boneyard actions 1008/1015/1016/1017/1059/1086 and policy actions 1018/1087 | `boneyard-scripting.md` action grammar | complete materializer/policy semantics; arbitrary authored predicates remain owned by the Boneyard script interpreter rather than a hidden loot probability |
| Solomon Dig and implicit wave-end reward | G7/G8 live census plus Bonus xrefs | excluded as producers: Dig has zero direct reward and there is no implicit wave-end drop |
| Multiplayer claim arbitration | loader `LootSnapshot`/claim retirement | complete loader extension: one host roll and first accepted retirement; retail itself has no network rule |

### Purchased drop modifiers

`Skills_FinalizePass (0x0067C360)` is the writer for the progression fields
read by `0x0047C070`. The selector bytes are the purchased `Item_Perk` flags at
`progression+0x7CC+selector`; these are multiplicative bound changes, so a
smaller value improves the chance.

| Perk selector | Native write | Exact consequence |
| ---: | --- | --- |
| 3 Item Charm | `+0x80C *= 0.75` at `0x0067C64E` | item candidate bound is three quarters of the unmodified bound |
| 4 Gold Charm | `+0xC0 *= 1.25` and `+0x808 *= 0.75` at `0x0067C421`/`0x0067C65A` | gold quantity gains 25 percent before truncation and the candidate bound falls to three quarters |
| 9 Scatter Curse | byte `+0x814 = 1`, `+0x804 *= 0.5` at `0x0067C669..0x0067C675` | Orb bound is halved and final raw Orb value is multiplied by 1.25 |
| 23 Arcane Attractor Charm | `+0x810 *= 0.800000011920929` at `0x0067C6A6` | Bonus candidate bound is multiplied by the exact float32 constant |

The ordinary finalized values remain Orb/Gold/Item/Bonus bound multipliers
`1,1,1,1`, gold amount multiplier `1`, Orb bonus byte `0`, Orb-pull multiplier
`1`, and pickup factor `1.25`.

### Ground actor art, clocks, and audio

All atlas records below are registered static data, not inferred alpha hulls or
replacement icons.

| Family | Exact draw program | Exact sound program |
| --- | --- | --- |
| Orb | `0x0060FC10` indexes BadGuys `434 + kind`; remaining value times alpha owns scale, phase owns the native jitter, and the full-alpha branch submits the normal plus white additive passes. | accepted pickup requests registry 2 `sounds\\gotorb` at `0x005E659F` |
| Gold | Scatter state starts at zero, advances by 0.5, remains active through 8.0, and clears at 8.5 on update 17. `0x0060FFE0` draws BadGuys `188 + trunc(scatter)` for the base trail plus one/two/four additional `188 + tier` phase-offset copies at tiers 1/2/3. Settled Gold uses BadGuys `198 + tier` with constructor signed rotation `Float(20)`. Pickup feedback uses BadGuys 73 and the `%d GOLD` text path. | settlement requests registry 25 `sounds\\dropcoins` at `0x005E67BD`; accepted pickup requests registry 69 `sounds\\pickupcoin` at `0x005E6A1B` |
| Potion Sack | after the strict delay, `0x006105F0` draws BadGuys `436 + subtype` for potion subtypes 0..5 | bounce settlement requests registry 26 `sounds\\droppotion`; accepted pickup uses registry 68 `sounds\\pickupbag` |
| Misc Sack | Item_Misc draws fixed BadGuys 33 | ordinary Sack drop consumes shared `Integer(2)` and selects pool 185..186 (`dropbag1`/`dropbag2`); accepted pickup uses registry 68 |
| Equipment or nested Item_Sack carrier | main pass `0x006104F0` draws BadGuys `442 + shell selector`; supporting pass uses BadGuys 67 | same two-entry drop-bag pool and pickup-bag cue |
| Bonus kind 0 | BadGuys `140 + frame` (18 frames) | pickup effect opens `BONUS SKILL POINT` and the new-skill picker |
| Bonus kind 1 | BadGuys `122 + frame` (18 frames) | pickup chooses one learned below-cap skill and increments it |
| Bonus kind 2 | fixed BadGuys 61 | pickup shows `DAMAGE x4`, writes the shared damage-x4 duration state, and refreshes progression |
| Goodie | DeadHawg `145 + phase` for phase 0/1/2; while active before timer 100 it alternates the BadGuys 33 indicator. Timer 100 creates the flash plus twenty children sampled from BadGuys 377..380. | timer 250 hands the resulting Gold/Sack actors to their normal family sound owners; there is no separate pickup bypass |

Bonus orbit phase advances by float32 `2.5` degrees, frame phase by
`0.20000000298023224`, and independent glyph rotation by `1` degree per actor
tick. Frame phase resets only when it is strictly greater than the 18-record
count. Alpha remains one until the 1200 countdown crosses below one; it then
subtracts float32 `0.009999999776482582` each update. Float32 residue makes the
fade 101 updates, so an untouched Bonus retires on actor update 1300. Sack
bounce starts at height `-25`, velocity
`0.10000000149011612`, and multiplies velocity by `1.5` after each move until
height becomes positive, where both fields clamp to zero. Gold's `+0x144`
remains an activation delay, never a despawn clock. Goodie timer 100 constructs
one BadGuys-52 flash and twenty `Anim_Bouncer` children selected from BadGuys
377..380; their constructor/customization draws advance the active shared RNG
and therefore are part of later loot outcomes, not client-only decoration.

Accepted Gold pickup creates two additive BadGuys-83 `Anim_Fade` objects at
Y-10: gold RGB `(.85,.73,.44)` loses `.05`, and white loses `.1`. Accepted Orb
pickup creates normal BadGuys-15 at scale 1.5 with `.05` loss. Orb registry-2
`gotorb` playback rate is fixed 1 and spends no pitch word. Gold and Sack
pickup alone consume signed `Float(.1)+1` pitch.

Notification manager insertion/update/draw is
`0x005CA7C0/0x005D7EF0/0x005CF000`. A message begins with lifetime 1.5 and
offset -18, rises one per update, and loses float32 `.005` per update: 300
updates absent earlier list pressure. A new message immediately moves an
unfinished active row in four-unit steps; active `%d GOLD` rows above lifetime
one merge and reset to 1.5. The draw is centered at screen Y 67, uses the stock
body bitmap font, black +2 shadow, `1-max(0,offset)/250` scale, and caller color.
The `+0x20` offset enters only that clamped scale expression in `0x005CF000`;
ordered font-row layout owns vertical placement, so it is not an additional
screen-Y translation.
Bonus messages are pink `(1,.5,.5)`, cyan `(.5,1,1)`, and gold
`(.85,.73,.44)` for kinds 0, 1, and 2.

`Inventory_InsertOrStackItem (0x0055FF20)` is forced by Sack pickup. It stacks
a matching Potion; otherwise it replaces the first type-7000 Item_None slot.
If no placeholder remains, the underlying list append still runs, so the item
is retained beyond the 88 visible cells and the carrier retires. Rejecting or
discarding a ground item merely because the visible grid is full is not stock.

### Goodie unlock owner

A fresh read-only caller/xref pass on 2026-08-20 closes the formerly unnamed
writer of Goodie `+0x143`. `Region` installs `MyCollider` vtable `0x0079F078`;
its sole callback `0x00646D00` handles local-player collider class 101. It forms
the native facing unit vector, samples a point exactly 25 world units ahead of
the player, and calls nearest-object query `0x00641340` with strict radius 50
and mask `0x2000`. An unopened Goodie (`+0x142 < 1`, `+0x143 == 0`) is eligible.

The callback then recursively searches the scene inventory for `Item_Misc`
type 7012/subtype 1 with `0x00552A10`. If absent, the throttled
`SAY_INEEDAKEY` lane runs and the Goodie stays closed. If present,
`0x005601B0` removes exactly one key, including from nested `Item_Sack` roots,
before `0x005F0E50` sets active byte `+0x143`, resets timer `+0x144`, and
decrements the arena's unopened-Goodie counter at `+0x9060`. There is no
keyboard-interact action and no arbitrary authored predicate in this stock
path. Once active, `0x0061F4C0` remains the sole staged reward owner. The stored
constructor-time `shared.Integer(1000)` seed is never rerolled at break time.

## Live golden and replay contract

[`loot-goldens.json`](../../tests/fixtures/webgame/loot-goldens.json) was
recorded by `tests/re/record_live_loot_goldens.py` from an owned audio-disabled
host/client retail pair on UDP 52391/52392. The recorder derives Git revision,
binary hashes, executable paths, PIDs, ports, and its own hash; no provenance
override is accepted. It distinguishes a runnable-but-busy pipe from a broken
process/dependency and verifies exact owned-PID cleanup.
The committed fixture's reviewed SHA-256 is
`dabdd9cdd87dc78b4b800477d2765a1afd63f86da22cf19427b5eb077cc6be26`.

The fixture contains 100 deaths—34 Skeleton, 33 Zombie, 33 Wraith. Every row
has the death-time actor seed and seed-writer lifecycle, tick/monotonic stamps,
table inputs, ordered candidate rolls, complete 55-word private state before
and after, per-roll state hashes, complete shared-state boundaries, native
call hits, selected category, and materialized actors. The corpus produced 84
no-drop, 10 orb, and 6 gold outcomes. It also contains the settled eight-trial
Dig result, three tick-indexed Orb trajectories, and the farther-host
two-participant credit case.

This corpus is evidence for the algorithm and draw order, not a frequency
estimate for all levels/configs. Item, potion, powerup, key, and forced-policy
paths are pinned statically because the ordinary level-0 sample did not happen
to select them.

## Adjacent ownership boundaries

- Potion inventory art and post-consumption VFX are downstream item-use
  consumers. Ground potion glyphs, drop/pickup audio, transfer, and stacking
  are closed here; use-after-pickup remains documented by
  `native-items-equipment-and-loot.md`.
- Custom Boneyard predicates belong to the script interpreter. Every universal
  loot action and policy mutation is enumerated above; there is no additional
  probability to guess.
- Retail has no simultaneous network-claim rule. The loader extension's
  first-retirement rule is the explicit multiplayer contract, and a browser
  host must preserve one deterministic participant/event order.
