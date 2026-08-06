# Native loot and reward selector

## Result and scope

This is the stock loot contract for the retail `SolomonDark.exe` whose
SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
It is sufficient to rebuild the decision, amount, ground motion, lifetime, and
crediting behavior without opening the executable. Presentation is deliberately
separate: potion icons and consumable VFX remain G4/G9 territory.

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
| SkeletonArcher | 1002 / `0x3EA` | Slot-0 scheduling at `0x00473B40` replaces it with shared `Integer(10000000)` at `0x00473B60`. |
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
- a 500-unit, mask-2 query around the dying actor must return more than 49
  entries;
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
skipped.

The total is emitted as Gold actors until no remainder is left. Nominal chunk
size is `min(remaining, 25)`. Only when the original explicit amount is greater
than 25, each chunk first rolls shared `Integer(2) == 1`; on a hit its size is
replaced by `shared.Integer(floor(nominal / 2)) + 1`. The chosen chunk is
subtracted from the remainder, so chunk randomization changes actor count and
per-actor amounts but never the total. Amount `<3`, `<5`, `<8`, or otherwise
maps to visual tier 0, 1, 2, or 3. Each Gold constructor and scatter step also
advances shared presentation RNG; after six chunks a signed
`FloatScaled(0.04)` perturbs later activation delays/positions.

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
subtype 1 (`Wizard Key`). Its additional active-shared integer only selects
scatter/activation delay: while `Arena+0x905C < 13`, `Integer(11)+15`; while it
is below 26, fixed 30; through 40, `Integer(21)+50`; above 40, the incoming
delay is unchanged. It does not randomize key quantity.

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
not a third loot RNG.

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
| Bonus 2038 | No magnet. Slot 0 only; capture radius = `20 * pickup_factor`. | `+0x154` starts 1200. On tick 1200 it reaches zero, alpha `+0x15C` falls from 1 by 2, and the actor deletes: exactly 1200 actor ticks if untouched. |

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

## Not Yet Reversed

- G4/G9 presentation details—potion inventory art, consumable VFX duration,
  and reward sprites—are intentionally outside this selector/physics contract.
- Custom Boneyard scripts can place drop actions behind arbitrary predicates.
  Their authored predicate/operand data must be imported from the Boneyard;
  there is no additional universal probability to infer here.
- The stock retail executable has no rule for resolving simultaneous network
  claims. The loader's observable first-retirement rule is pinned above; a
  browser server must choose a deterministic event order for truly
  simultaneous inputs.
