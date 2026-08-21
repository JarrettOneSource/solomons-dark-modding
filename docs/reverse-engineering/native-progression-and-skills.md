# Native progression and per-skill effects

> **Secondary correction (2026-08-20):** Complete-equipment bits and the
> reopened Storm, Golem, Leviathan, Ring of Fire, and FreezeWave owners are
> specified in
> [`native-secondary-parity-correction-2026-08-20.md`](native-secondary-parity-correction-2026-08-20.md).
> Its feature-bit, target-modifier, composite-painter, and Region-feedback
> findings supersede any broader secondary closure wording in this file.

This is the implementation contract for browser-rebuild gap G6. It specifies
experience, levels, level-up offer construction, and the runtime effect of all
82 native skill IDs. An implementing agent should use this document together
with the machine-readable
[`native-skill-catalog.json`](native-skill-catalog.json); opening the retail
binary is not required.

The contract is deliberately **per actor**. Every player and every bot owns a
separate progression object, rank table, HP/MP pools, derived-stat block,
offer seed, and toggle state. Nothing below is a process-global character
sheet. Process-global state is named only where stock deliberately draws a
seed or synchronizes presentation.

## Evidence and confidence

The evidence stack is:

- read-only headless decompilation of the retail executable with the principal
  progression routines at `0x006594E0`, `0x0065F5B0`, `0x00660220`,
  `0x006614D0`, `0x00661530`, `0x006623F0`, `0x0067C250`, `0x0067CB70`, and
  `0x00680AB0`;
- a serialized 2026-08-15 read-only headless-Ghidra closure pass over
  `Ember::Tick 0x0060D7E0`, the GoodImp lifecycle at
  `0x00529FE0/0x0052A050/0x0052C1A0`, Lightning `0x0053F9C0`,
  `Mod_Stun 0x00623180/0x006231B0/0x00625850`, and StormCloud
  `0x005E22E0/0x005E2440/0x006021A0`;
- the generated 82-row native catalog and its exact CFG arrays;
- the landed spell/effect lifecycle work in
  [`native-skills-and-spells.md`](native-skills-and-spells.md) and
  [`native-projectiles-and-effects.md`](native-projectiles-and-effects.md);
- the landed concentration and discipline work in
  [`skills-concentration-discipline.md`](../re/skills-concentration-discipline.md)
  and its replication/stock-defect addendum
  [`skillfix-discipline-and-concentration-2026-08-02.md`](../re/skillfix-discipline-and-concentration-2026-08-02.md);
- the offer screen control-flow map in
  [`skill-picker-re.md`](../skill-picker-re.md). This campaign owns the pool and
  selection semantics, not G11's layout;
- a fresh quiet retail recording at
  [`progression-goldens.json`](../../tests/fixtures/webgame/progression-goldens.json).

Confidence labels mean:

- **HIGH**: exact native control/data flow, or exact configuration consumed by
  an already-closed native handler;
- **HIGH-LIVE**: HIGH plus a before/after retail actor-state proof in the G6
  golden;
- **MEDIUM**: the native consumer and output state are known, but a complete
  event trajectory was not captured in G6;
- **LOW**: no honest runtime effect can yet be assigned.

## Per-actor progression ABI

The live fixture proves that the local player and the bot have different actor,
progression, rank-table, seed, derived-stat, and toggle addresses. Applying
four skills to the bot did not change the player's book; activating Regenerate
on the player did not change the bot's book. Treat identity as part of every
progression operation.

| Actor-owned field | Location | Meaning |
| --- | ---: | --- |
| progression pointer | actor `+0x200` | Direct route used by the retail actor code |
| progression handle | actor `+0x300` | Participant/network-facing route to the same actor-owned book |
| skill rows | progression `+0x20` pointer, count `+0x24` | 0x70-byte rows; retail count is 83, with the public catalog occupying IDs `0..81` |
| permanent/effective rank | row `+0x20/+0x22` | Saved rank and refresh-time rank; Mindstar modifies only effective rank |
| skill category | row `+0x26` | Offer-family/category discriminator |
| level/XP | progression `+0x30/+0x34` | Current integer level and cumulative float XP |
| previous/next threshold | progression `+0x38/+0x3C` | Thresholds surrounding the current level |
| HP | progression `+0x6C/+0x70/+0x74` | Base/current/maximum |
| MP | progression `+0x78/+0x7C/+0x80` | Base/current/maximum |
| movement/cast/recovery/regen | progression `+0x90/+0x94/+0x98/+0x9C` | Refreshed per-actor scalars |
| magic/poison resistance | progression `+0xA4/+0xA8` | Per-actor accumulators |
| Deflect chance | progression `+0xB8` | Present only while a staff is equipped |
| staff damage | progression `+0xC4/+0xC8` | Two per-actor staff-damage accumulators |
| pickup/recharge/offense | progression `+0xCC/+0xD0/+0xF8` | Telekinesis, Focus, and Siege Mage results |
| Battle Mage factor | progression `+0x3D4` | Offensive mana-cost factor |
| hoarded MP | progression `+0x740` | Sum of active Firewalker/Mindstar/Regenerate reserves |
| element/discipline | progression `+0x82C/+0x830` | Actor's current roots |
| offer RNG seed | progression `+0x834` | Actor-private offer-generator seed |
| Firewalker/Mindstar/Regenerate | progression `+0x8DC/+0x8DD/+0x8DE` | Actor-private active toggles |

`ActorProgressionRefresh (0x0065F9A0)` copies permanent ranks into effective
ranks, rebuilds passive/equipment/spell caches, preserves the actor's HP and MP
ratios across changed maxima, restores those ratios, and clamps. On a normal
acquisition the rank is incremented and refresh runs immediately. Rank arrays
are **absolute values at rank `r`**, not increments to add on each acquisition.
Unless a row below explicitly says otherwise, `P[r]` means the property value
at effective rank `r` in `native-skill-catalog.json`.

## Experience and levels

### Award pipeline

For a normal enemy death, the one-player raw family reward is built as:

```text
raw_reward = 2 * (evaluated_recipe_xp + runtime_bonus_xp) * arena_player_count
evaluated_recipe_xp = recipe.mXP * Arena.xp_recipe_scalar
actor_reward = raw_reward * Gameplay.xp_scalar
credited_xp = actor_reward * difficulty_level_factor(level)
                         * (1 + actor_xp_bonus)
```

The evaluated recipe field is recipe `+0xD4`; the runtime bonus is enemy actor
`+0x174`; the resulting actor reward is at enemy `+0x178`. The common gameplay
wrapper `0x005C8880` applies `Gameplay+0x1AB8` (default `1.0`) before
`0x00680AB0` applies the receiving actor's level and `+0x8C` bonus. A Boneyard
action `1090` changes `Gameplay+0x1AB8` to `1 +/- percent/100`. The recipe
builder applies Arena `+0x9024` before actor construction. The complete enemy
type/config census is already closed in
[`native-enemy-behavior.md`](native-enemy-behavior.md); G6 adds the reward
meaning, not another enemy catalog.

The level factor is exact:

| Mode | Receiving actor level | Factor before `1 + actor_xp_bonus` |
| --- | ---: | ---: |
| normal | 1 | `1` |
| normal | 2 | `0.75` |
| normal | 3-4 | `0.75^2 = 0.5625` |
| normal | 5+ | `0.75^3 = 0.421875` |
| survival | 1 | `1` |
| survival | 2-5 | `0.9` |
| survival | 6-15 | `0.9 * 0.8 = 0.72` |
| survival | 16-30 | `0.9 * 0.8 * 0.7 = 0.504` |
| survival | 31+ | `0.9 * 0.8 * 0.7 * 0.6 = 0.3024` |

The receiving actor's `+0x8C` scalar is additive before multiplication:
`final_factor = level_factor * (1 + actor_xp_bonus)`. It is not shared among
participants.

Three additional award paths are intentional exceptions:

- the tutorial grants `10 * Gameplay.xp_scalar` until level 2;
- the forced-next-level helper grants
  `(next_threshold - current_xp + 1) * Gameplay.xp_scalar` and does **not** run
  the receiving actor's level/bonus scaling;
- the generic non-family fallback reward is `10.0` before the normal wrapper.

### One-player family rewards

These are the unscaled one-player family baselines after the native `*2`
conversion, before Arena/Gameplay/difficulty/actor-bonus multipliers. Helpers
that do not enter the ordinary death-credit listener are explicitly `none`.

| Enemy family/type | Baseline XP | Notes |
| --- | ---: | --- |
| Badguy base/fallback | 10 | Generic base path |
| Skeleton / Skeleton Archer / Skeleton Mage | 10 | Same family baseline |
| Imp | 2 | Green Imp inherits this |
| Good Imp | none | Friendly helper, no ordinary death credit |
| Zombie | 210 | |
| Wraith | 4 | |
| Demon Skull | 7000 | Boss |
| Demon | 800 | |
| Dire Faculty | 4020 | Boss |
| Heartmonger | 4000 | Boss |
| Crow | none | Heartmonger-owned helper |
| Coffin | 200 | |
| Green Imp | 2 | Inherited Imp reward |
| Maggot | 0 | Explicit zero |
| Spider | 30 | |
| Cocoon | 10 | Generic reward value; normal loot is suppressed |
| Portal | 600 | |
| XP Bonus helper | 4 | Recipe `mXP=2`, then the common `*2` conversion |

The live golden observed retail Arena scaling `0.425` and then recorded
Skeleton `10 -> 4.25`, Imp `2 -> 0.85`, and Wraith `4 -> 1.70`, including
ticks and actor-state before/death-presenter/after snapshots. The recorder uses
the stock wave spawner and death presenter, then invokes the native progression
grant seam with the actor's native `+0x178` reward; the death presenter alone
does not credit XP in that sanctioned synthetic-spawn setup.

### Exact level curve

The native table at `0x008096F8` contains 76 cumulative thresholds. Entry
`T[L]` is the XP needed to leave level `L`; the actor starts at level 1 with
previous threshold `T[0]=0` and next threshold `T[1]=90`.

| Level | XP to leave level | Level | XP to leave level | Level | XP to leave level |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 26 | 13000 | 52 | 500000 |
| 1 | 90 | 27 | 14000 | 53 | 600000 |
| 2 | 160 | 28 | 15000 | 54 | 700000 |
| 3 | 275 | 29 | 16000 | 55 | 800000 |
| 4 | 390 | 30 | 20000 | 56 | 900000 |
| 5 | 520 | 31 | 25000 | 57 | 1000000 |
| 6 | 650 | 32 | 30000 | 58 | 1200000 |
| 7 | 800 | 33 | 35000 | 59 | 1400000 |
| 8 | 1060 | 34 | 40000 | 60 | 1700000 |
| 9 | 1300 | 35 | 45000 | 61 | 2000000 |
| 10 | 1600 | 36 | 51000 | 62 | 2300000 |
| 11 | 2000 | 37 | 57000 | 63 | 2600000 |
| 12 | 2400 | 38 | 64000 | 64 | 3000000 |
| 13 | 2850 | 39 | 71000 | 65 | 3500000 |
| 14 | 3400 | 40 | 79000 | 66 | 4000000 |
| 15 | 4200 | 41 | 88000 | 67 | 4500000 |
| 16 | 4800 | 42 | 98000 | 68 | 5000000 |
| 17 | 5650 | 43 | 110000 | 69 | 5500000 |
| 18 | 6000 | 44 | 120000 | 70 | 6000000 |
| 19 | 6500 | 45 | 130000 | 71 | 6500000 |
| 20 | 7200 | 46 | 135000 | 72 | 7000000 |
| 21 | 7850 | 47 | 150000 | 73 | 7500000 |
| 22 | 8900 | 48 | 175000 | 74 | 8500000 |
| 23 | 9900 | 49 | 200000 | 75 | 10000000 |
| 24 | 11000 | 50 | 300000 | - | - |
| 25 | 12000 | 51 | 400000 | - | - |

On every crossed threshold, `0x0067C250` increments the actor's level, advances
the previous/next threshold fields, refills that actor's HP and MP, and queues
one level-up choice in local non-network mode. A single large award can cross
multiple levels and repeats those actions for every threshold.

After that threshold loop, the local-only tail runs once through
`0x0067C30B -> 0x005C88B0 -> 0x00528A20`. That player owner both rearms the
180-tick presentation lane and requests registry 52 `sounds\levelup` once at
gain `1.0`. Therefore one award crossing N levels creates N pending choices but
only one presentation rearm and one level-up sound. Separate award invocations
remain distinct events even when a sparse snapshot observes their sequence as
a gap.

**Stock cap defect and browser rule.** Level 75 is entered at 8,500,000 XP.
The last table value, 10,000,000, is the threshold to leave level 75. Stock has
no guard: crossing it increments to level 76 and reads beyond the 76-entry
table. That is an out-of-bounds stock defect, not a secret post-cap curve. The
browser rebuild MUST clamp at level 75, keep cumulative XP at no more than
10,000,000 for progression comparisons, issue no further offers, and retain
full HP/MP semantics at the cap. This safe clamp is a designed compatibility
policy; the exact stock defect remains recorded for diagnostics.

## Level-up offer pool and selection

### RNG streams and seed ownership

There are two named streams; they must not be collapsed:

1. During progression construction `0x006594E0` draws
   `active_gameplay_rng.Integer(1_000_000)` and stores the result at this
   actor's progression `+0x834`. The active shared gameplay RNG has the
   tick-derived seed lifecycle closed by G1 in
   [`native-movement-and-tick.md`](native-movement-and-tick.md).
2. Every call to offer builder `0x0067CB70` constructs a fresh **actor-private
   level-up offer RNG** from that stored seed. It is the same 55-word lagged
   additive generator and biased bounded sampler specified by G1. The builder
   does not write `+0x834`; identical actor book, level, and seed therefore
   reproduce an identical pool and order.

Concentrated Creativity's later Insight roll is not part of the offer stream.
It uses the active concentration/gameplay RNG after the displayed list exists.
Naming these streams matters: replaying the offer RNG must not consume or
advance the gameplay RNG.

### Eligibility predicates

The builder scans skill IDs `8..81`; ID 52 is excluded from the ordinary scan
because Spell Welding has its own injection branch. Disabled/hidden Game-array
entries are rejected. A row is eligible only when all of the following hold:

- its permanent rank is below its compiled maximum (Spell Welding is the
  special exception);
- an unlearned non-root row satisfies its minimum player level, reduced by 2
  when Creativity 63 is learned;
- its root matches this actor's element `+0x82C` or discipline `+0x830`, or the
  row is otherwise in the native general/advanced family;
- every `requires_all` rank pair is satisfied;
- at least one `requires_any` pair is satisfied when that list is nonempty;
- no `forbidden_if_at_least` pair is satisfied;
- IDs `72..79` have their corresponding global content-unlock bit;
- Spell Welding 52 additionally requires more than one learned elemental
  primary among IDs `8,16,24,32,40`.

The exact compact rule matrix follows. Blank dependency cells mean none. `A:x`
means skill A at rank at least x. Minimum levels are the native values before
Creativity's `-2` adjustment.

| ID | Skill | Min | Root | Cat | Any | All | Forbidden |
| ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| 8 | Magic Missile | 1 | 0 | 1 | | | |
| 9 | Smart Missiles | 1 | 0 | 0 | | 8:1 | |
| 10 | More Missiles | 1 | 0 | 0 | | 8:1 | |
| 11 | Call Leviathan | 3 | 0 | 2 | | | |
| 12 | Planewalker | 25 | 0 | 2 | | | |
| 13 | Piercing | 20 | 0 | 4 | | 9:1 | 14:1 |
| 14 | Ether Blast | 20 | 0 | 4 | | 9:1 | 13:1 |
| 15 | Phasing | 6 | 0 | 2 | | | |
| 16 | Fireball | 1 | 1 | 1 | | | |
| 17 | Embers | 1 | 1 | 0 | | 18:1 | |
| 18 | Explode | 1 | 1 | 0 | | 16:1 | |
| 19 | Embers to Imps | 20 | 1 | 4 | | 17:1 | 20:1 |
| 20 | Immolate | 20 | 1 | 4 | | 17:1 | 19:1 |
| 21 | Ring of Fire | 4 | 1 | 2 | | | |
| 22 | Burn | 12 | 1 | 0 | 16,21,23 | | |
| 23 | Firewalker | 8 | 1 | 2 | | | |
| 24 | Lightning | 1 | 2 | 1 | | | |
| 25 | Chaining | 1 | 2 | 0 | | 24:1 | |
| 26 | Stun | 1 | 2 | 0 | | 24:1 | |
| 27 | Magic Storm | 1 | 2 | 2 | | | |
| 28 | Magic Tornado | 12 | 2 | 0 | | 27:1 | |
| 29 | Hurricane | 20 | 2 | 4 | | 25:1 | 31:1 |
| 30 | Prismatic Shock | 12 | 2 | 2 | 24,27 | | |
| 31 | Disintegrate | 20 | 2 | 4 | | 25:1 | 29:1 |
| 32 | Frost Jet | 1 | 3 | 1 | | | |
| 33 | Chill Wind | 1 | 3 | 0 | | 32:1 | |
| 34 | Cone of Ice | 1 | 3 | 0 | | 32:1 | |
| 35 | Ring of Ice | 1 | 3 | 2 | | | |
| 36 | Harden | 20 | 3 | 4 | | 33:1 | 37:1 |
| 37 | Cold Aura | 20 | 3 | 4 | | 33:1 | 36:1 |
| 38 | Hail | 18 | 3 | 0 | | 34:1 | |
| 39 | Permafrost | 16 | 3 | 0 | 32,35 | | |
| 40 | Boulder | 1 | 4 | 1 | | | |
| 41 | Earthquake | 3 | 4 | 2 | | | |
| 42 | Hasten Rocks | 1 | 4 | 0 | | 40:1 | |
| 43 | Bind Rocks | 1 | 4 | 0 | | 40:1 | |
| 44 | Rock Surge | 20 | 4 | 4 | | 43:1 | 47:1 |
| 45 | Raise Golem | 6 | 4 | 2 | | | |
| 46 | Stoneskin | 25 | 4 | 2 | | | |
| 47 | Gargantuan | 20 | 4 | 4 | | 43:1 | 44:1 |
| 48 | Teleport | 1 | 7 | 2 | | | |
| 49 | Magic Circle | 1 | 7 | 2 | | | |
| 50 | Magic Trap | 1 | 7 | 2 | | | |
| 51 | Dampen | 18 | 7 | 2 | | | |
| 52 | Spell Welding | 1 | 7 | 1 | | special | |
| 53 | Flash | 8 | 7 | 0 | | | |
| 54 | Magic Shield | 4 | 7 | 2 | | | |
| 55 | Explosive Shield | 10 | 7 | 0 | | 54:1 | |
| 56 | Mana Up | 1 | 6 | 0 | | | |
| 57 | Channel Mana | 1 | 6 | 3 | | | |
| 58 | Meditation | 8 | 6 | 3 | | | |
| 59 | Battle Mage | 5 | 6 | 3 | | | |
| 60 | Focus | 8 | 6 | 3 | | | |
| 61 | Siege Mage | 25 | 6 | 3 | | 59:1 | |
| 62 | Resist Magic | 18 | 6 | 3 | | | |
| 63 | Creativity | 12 | 6 | 3 | | | |
| 64 | Health Up | 1 | 5 | 0 | | | |
| 65 | Enchant Staff | 1 | 5 | 3 | | | |
| 66 | Telekinesis | 10 | 5 | 3 | | | |
| 67 | Rush | 1 | 5 | 3 | | | |
| 68 | Deflect | 10 | 5 | 3 | | 71:1 | |
| 69 | Resist Poison | 6 | 5 | 3 | | | |
| 70 | Faster Caster | 25 | 5 | 3 | | | |
| 71 | Fortunate Flailing | 5 | 5 | 3 | | 65:1 | |
| 72 | Acid Rain | 1 | 2 | 2 | | unlock bit | |
| 73 | Fire Wall | 5 | 1 | 2 | | unlock bit | |
| 74 | Ether Drain | 10 | 0 | 2 | | unlock bit | |
| 75 | Iron Golem | 10 | 4 | 0 | | 45:1 + unlock bit | |
| 76 | Call Comet | 10 | 3 | 2 | | unlock bit | |
| 77 | Turn Undead | 6 | 7 | 2 | | unlock bit | |
| 78 | Mindstar | 10 | 6 | 2 | | unlock bit | |
| 79 | Regenerate | 10 | 5 | 2 | | unlock bit | |
| 80 | Plane Orb | 0 | -1 | 0 | | runtime-only | |
| 81 | Reserved | 0 | -1 | 0 | | runtime-only | |

Element and discipline roots `0..7` are acquired through creation/loadout, not
the `8..81` level-up scan. Plane Orb 80 and Reserved 81 have no ordinary CFG
and fail normal material eligibility despite occupying runtime rows.

### Focus filters, weighting, welding, and final draw

Offer construction first decides whether to focus on already-started primary
and discipline families. Every mentioned draw uses the actor-private offer RNG:

- category 1 focus starts true below level 5; becomes true below level 10 when
  more than one category-1 row is owned; then an unconditional `Integer(2)`
  sets it true on nonzero; with more than one owned row, another `Integer(4)`
  sets it true unless the result is 1;
- category 2 focus is disabled when progression `+0x7DA` is set. Otherwise,
  owning more than one/two/three category-2 rows adds `Integer(2) != 1`,
  `Integer(3) != 1`, and `Integer(6) != 2` chances. It is also forced true at
  `(owned>0 && level<9)`, `(owned>1 && level<16)`,
  `(owned>2 && level<26)`, and `(owned>3 && level<36)`.

#### Exact candidate assembly and draw

The following phases execute in this order in `0x0067CB70`. `rank(i)` and
`effective(i)` are row `+0x20/+0x22`; `root(i)` and `category(i)` are row
`+0x1C/+0x26`; `eligible(i)` means the level, unlock, any/all/forbidden, and
below-maximum-rank gates above all pass. For category 2, `mana_cost(i, r)` is
the wizard cost query at vtable `+0x78`. Pointer-list duplicates are deliberate
weights, not set insertion.

1. **Seed and desired count.** Construct a fresh private RNG from actor
   `+0x834`. Set `desired=3`, or `4` when Creativity 63 is learned. Count owned
   visible category-1 and category-2 rows, then consume the focus draws in the
   exact order listed above.
2. **Build the root-priority pool.** Scan IDs `8..81`, skipping 52 and either
   globally disabled/hidden byte. Apply the focus filters, except that an
   unlearned focused category-2 row may remain when discipline is Arcane 7.
   Require `eligible(i)`. For category 2 also require
   `mana_cost(i, effective(i)+1) <= actor.maxMP`. Append exactly those rows for
   which `root(i)` equals this actor's element or discipline.
3. **Build and pre-shuffle the general pool.** Repeat the same scan, but a
   focused unlearned category-2 row is always rejected and its affordability
   query is the stock oddity `mana_cost(i, actor.level+1) <= actor.maxMP`.
   Append a row once when its root matches neither actor root. If byte `+0x7DA`
   is nonzero, append each discipline-root row **twice** instead. Then, for
   every index `j`, swap `general[j]` with
   `general[rng.Integer(general.length)]`. This consumes one draw per entry and
   is not Fisher-Yates.
4. **Copy forced-prefix entries.** Inspect only the first
   `min(desired, count(+0x864))` IDs in the actor list at `+0x860`. Preserve
   their order and append each whose first global-disable byte is clear and
   whose dependency/unlock predicate `0x0065E830` passes.
5. **Inject one root-priority entry when space remains.** Normally append a
   uniform `root_priority[rng.Integer(root_priority.length)]`. With
   `+0x878 & 0x1000` (Bias Skills for Welding), first draw `Integer(2)`: only
   result `1` takes the related-skill branch. That branch adds every learned
   category-1 primary and its two `0x00658450` neighbors that pass the start
   predicate; if the related list has fewer than six entries, it repeats that
   construction for unlearned category-1 primaries. Append one uniform entry
   from that related list. The adjacency map is `8:(10,9)`, `16:(18,17)`,
   `24:(25,26)`, `32:(34,33)`, and `40:(43,42)`.
6. **Optionally inject Spell Welding.** Only while space remains and the raw
   weld scheduling marker `+0x840 <= 999`, require row 52 to be unlearned,
   level/dependency/unlock eligible, globally visible, and backed by more than
   one learned elemental primary. The cadence gate is exactly
   `((u32(+0x848)-u32(+0x840)) % 5 == 0) ||
   (u32(+0x848) <= u32(+0x840)+1)`. Build only the learned pairs in the table
   below, choose one uniformly, append the special choice, and store its
   synthetic build at `+0x844`. The prior/current-weld filter from
   [`spell-welding.md`](spell-welding.md) remains part of that candidate list.
7. **Apply the learned-skill pruning draw.** Count permanent-ranked IDs
   `8..81`. Above 8, set `keep_started = (Integer(2)==1)`; above 12, consume
   another draw and overwrite it with `Integer(5)!=2`; above 20, consume a
   third and overwrite it with `Integer(10)!=2`. When true, filter the root,
   general, and already-selected lists through `0x0066F840`: retain a row only
   when its effective rank is positive or the **first** ID in its `requires_all`
   array is already learned. The later thresholds overwrite the Boolean but do
   not erase the earlier RNG consumption.
8. **Merge and fill.** Append the entire root-priority list to the general
   list. Draw uniformly **with replacement** until `desired` entries exist.
   A category-4 candidate is always retried while the result already contains
   a category-4 row. Separately, a category-1 candidate is retried while the
   result already contains a category-1 row and fewer than 50 such collisions
   have occurred; after 50, another category-1 row is allowed.
   Stock performs no ID-equality rejection and never removes a chosen
   candidate, so duplicate non-category-4 IDs are possible. On attempt
   100, append every ID `8..81` except 52 that passes the first global-disable
   byte plus `0x0065EBA0/0x0065ED00`; do not clear the old list, so repeated
   pointers add weight. On attempt 200, stop and return an undersized pool.
9. **Final display shuffle.** Clear the output, perform another full-range
   swap for every result index using the same private RNG, and then append the
   shuffled entries. This second shuffle is also not Fisher-Yates.

The ten Spell Welding build IDs used by phase 6 are:

| Build | Primaries | Build | Primaries |
| ---: | --- | ---: | --- |
| 1000 | 8 + 16 | 1005 | 16 + 32 |
| 1001 | 8 + 32 | 1006 | 8 + 40 |
| 1002 | 8 + 24 | 1007 | 16 + 40 |
| 1003 | 16 + 24 | 1008 | 32 + 40 |
| 1004 | 32 + 24 | 1009 | 24 + 40 |

The live actor-private seed `79225` produced these full three-choice pools when
pre/post actor snapshot and applied choice:

| Level | Displayed offer order | Selected |
| ---: | --- | --- |
| 2 | Teleport 48, Magic Circle 49, Channel Mana 57 | Teleport 48 |
| 3 | Enchant Staff 65, Magic Circle 49, Smart Missiles 9 | Enchant Staff 65 |
| 4 | Magic Circle 49, Mana Up 56, Smart Missiles 9 | Magic Circle 49 |

The ordinary picker has no unconditional reroll or skip: a pending local
choice still blocks normal play. Selector 17 `SORCEROR'S CHARM`, however,
enables the screen's two authored sibling actions while current-offer byte
`+0x839` is set. ROLL AGAIN writes
`active_gameplay_rng.Integer(1_000_000)` to actor-private offer seed `+0x834`,
clears `+0x839`, and rebuilds without decrementing pending count. SAVE SKILL
moves one count from pending `+0x44` to deferred `+0x48`, closes the screen,
and `0x0065F480` merges that deferred count back on a later screen creation.
Neither action exists without the owned byte at `+0x7DD` (the
`+0x7CC + selector` span). Reopening with unchanged book/level/seed still
reproduces the same selection. The live recorder deliberately rewrites
`79225` before each of its three independent rolls; the builder itself never
writes `+0x834`, while the explicit charm reroll action does. Concentrated
Creativity then independently has a
20% `RandomInt(5)==1` Insight chance, marks one eligible displayed row, and applies
that row twice when chosen. The shipped branch checks only concentration slot
A/index 16, not slot B or Mind Chug; preserve that verdict from the landed
concentration work.

## Per-skill runtime semantics

### Common rules

All rank-scaled constants below come from the named property array in
`native-skill-catalog.json`. This avoids maintaining a second hand-copied
catalog while still giving an implementation-complete formula: read the array
at effective rank `r` and apply exactly the transform in this table. Scalar
properties such as Firewalker's `mHoard=50` are not rank arrays.

The common rules are:

- permanent rank is actor row `+0x20`; effective rank is row `+0x22`;
  acquiring another rank replaces every `P[r]` input with the new absolute
  value rather than adding the new row value to the old result;
- ordinary offers stop at `mCapLevel`, while apply and effective-rank paths
  clamp at `mMaxLevel`. Creativity Insight can double-apply `cap-1` to
  `cap+1` when max permits; the row then remains above the ordinary offer
  ceiling. Property reader `0x0065D540` clamps short arrays to their last
  authored entry (for example ID 19 `mManaCost` is `62` at every rank >=8);
- Mindstar raises effective rank by one, capped at the compiled maximum, but
  never changes permanent rank;
- offensive mana cost is assembled by `0x006741B0` from the base and upgrade
  `mManaCost[r]` values, then multiplied by this actor's Battle Mage factor at
  `+0x3D4`; spell damage passes through this actor's Siege Mage factor at
  `+0xF8` and the already-documented common damage application path;
- a configured duration in seconds is converted against the 100 Hz simulation
  clock. Per-tick divisions use the live game timing scalar, not render FPS;
- probabilities written as `chance/100` use an event draw from the active
  gameplay RNG unless the row explicitly names an actor/object-private stream;
- spell rows keep ownership in the caster's rank book. A cast copies the
  resolved payload into a newly created action/projectile/modifier actor; that
  transient object's fields are not a second progression book.

### Roots and discipline

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 0 | **Element of Ether.** On create/loadout, activate root row 0, write actor `+0x82C=0`, set starting primary/secondary rows `+0x86C/+0x870` to Magic Missile 8 / Call Leviathan 11. Admits Ether offers. Root is boolean; no ranks or direct stat bonus. | HIGH |
| 1 | **Element of Fire.** Same actor-owned create operation with `+0x82C=1`; starts Fireball 16 / Ring of Fire 21 and admits Fire offers. No direct stat bonus. | HIGH |
| 2 | **Element of Air.** `+0x82C=2`; starts Lightning 24 / Magic Storm 27 and admits Air offers. No direct stat bonus. | HIGH |
| 3 | **Element of Water.** `+0x82C=3`; starts Frost Jet 32 / Ring of Ice 35 and admits Water offers. No direct stat bonus. | HIGH |
| 4 | **Element of Earth.** `+0x82C=4`; starts Boulder 40 / Raise Golem 45 and admits Earth offers. No direct stat bonus. | HIGH |
| 5 | **Body Discipline.** Activate row 5 and write actor `+0x830=5`; admits rows 64-71. It grants no HP, passive, item, or hidden rank by itself. | HIGH |
| 6 | **Mind Discipline.** Activate row 6 and write actor `+0x830=6`; admits rows 56-63. It grants no MP or passive by itself. | HIGH |
| 7 | **Arcane Discipline.** Activate row 7 and write actor `+0x830=7`; admits rows 48-55. It grants no spell or passive by itself. | HIGH |

The three discipline values above are native roots. The wire enum remains Mind
0, Body 1, Arcane 2, and the Create screen indices remain Arcane 0, Body 1,
Mind 2. Do not interchange those domains. Concentration is selected per
participant and modifies only the selected actor; its exact formulas and the
stock Deflect/Creativity defects are inherited below rather than re-derived.

### Ether and fire

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 8 | **Magic Missile.** On cast, pay resolved cost and create `quantity` homing `MagicMissile 0x7D3` actors. Base quantity is one unless row 10 changes it. Each gets cast-time active-gameplay-RNG damage in the closed interval between `mDamage1[r]` and `mDamage2[r]`, caster ownership, target handle, and current upgrade payload. Rank replaces both endpoints and base cost. | HIGH |
| 9 | **Smart Missiles.** At Magic Missile creation, `speed_factor = 1 + mSpeed[r]/100`; multiply both projectile speed and turn-rate fields by it. Smart projectiles reacquire after target loss. Add `mManaCost[r]` to the Missile cast cost. State remains row 9 until copied into each missile. | HIGH |
| 10 | **More Missiles.** At Missile cast, `quantity = round(mQuantity[r])`; create zero-based children `i=0..N-1` in native order and add `mManaCost[r]` to cost. With `step = N<4 ? 30deg : 20deg` and `base = aim + (N even ? step/2 : 0)`, heading is `base + (-1)^i*i*step` (for example `N=4`: `+10,-10,+50,-50`). One cast-time damage roll is copied unchanged to every child. Visual scale stays `1`; only homing turn input decays, as `2*(1+mSpeed/100)*0.75^i`, while every child speed is `3*(1+mSpeed/100)`. | HIGH |
| 11 | **Call Leviathan.** On secondary cast, pay `mManaCost[r]` and create `Leviathan 0x7F2` at the aimed point. An ordinary cast chooses the appendage count uniformly from the inclusive integer range `[1, round(mQuantity[r])]`; the complete five-piece Pandimensional Bug-Master's Outfit sets `FX_MAXLEVIATHAN`, skips that count draw, forces the configured maximum, and its separate `FX_ONESPELLDAMAGE *2 "Call Leviathan"` doubles every child bolt payload. Float32 scale-in takes 41 updates: update 40 is `0.9999995827674866`, and update 41 clamps to one and also executes active update one. The 1,600 active updates are ages `41..1640`; age 1640 also performs the first `-0.04` scale-out step, and age 1664 reaches zero and removes the owner. Each appendage independently deploys, performs the native 50-degree/300-unit lane query, tracks a retained identity, and fires an owned `EtherBolt 0x7F3` carrying the effective damage. Its shot counter starts in `[0,99]` and resets to `75 + Integer(26)`. Bolts move 10 units per update, begin `-0.01` alpha fade when the 100-count reaches zero, remain contact-active throughout the fade, and retire on the 101st fade update or contact. | HIGH |
| 12 | **Planewalker.** On toggle-on, pay `mManaCost[r]`, attach `Mod_Planewalker 0x1B75` for `mDuration[r] * 100` native ticks, save the previous selected spell at wizard `+0x308`, set target flag `+0x138 |= 0x10`, and force Plane Orb 80. Casting while already active removes the modifier without another application; expiry/removal clears the flag, restores the saved primary, and emits the off edge. Same-type merge keeps the greater remaining duration. Plane state also forces Ether Blast charge to zero. | HIGH |
| 13 | **Piercing.** Refresh caches `pierces=round(mPierces[r])` at `+0x8C0` and residual factor `1-mLoss[r]/100` at `+0x8C4`. A Missile can pass through `pierces` contacts; each subsequent payload is multiplied by the residual factor. Add `mManaCost[r]`. Mutually exclusive with Ether Blast in offers. | HIGH |
| 14 | **Ether Blast.** Refresh `charges=round(mCharges[r])` at `+0x8C8`. `PlayerWizard::Tick 0x00548B00` adds float32 `0.007` per native tick only while Magic Missile is selected, the actor is outside its firing state, the full Missile cost is affordable, a charge cap is learned, and Planewalker is inactive; it clamps at the cap. On the next Missile release, round-to-nearest-even charge count `c>0` produces a 200-unit-forward, 350-radius hostile pulse, flashes the world by `0.1*c`, and resets charge before the Missile is born. Each target receives `Mod_EtherBurn 0x1B74` for 300 ticks with maximum-health reduction `min(0.15*c,0.95) * target_max_hp` (minimum payload `0.001`). Same-type merge keeps both maximum duration and maximum reduction. Mutually exclusive with Piercing. | HIGH |
| 15 | **Phasing.** On cast, pay `mManaCost[r]`; `0x0052A0B0` tests exactly 20 forward points at distances `80,90,...,270` in 10-unit increments and relocates to the first collision-clear point. If all probes fail, mana/cooldown acceptance remains but there is no movement, phase sprite, or phase sound. A successful move emits one additive `BadGuys[53]` traversal streak at old-position plus 10 units along the path, scale 2, and 20-tick fade. Refresh stores cooldown cap/current in the row-relative cooldown fields (`+0x6F8/+0x6F4`) from `mCooldown[r]`; there is no second cooldown write inside the relocation helper. | HIGH |
| 16 | **Fireball.** On cast, pay the sum of active rows 16-20, create one `Fireball 0x7D4`, and snapshot rows 16-20/22 plus a private random seed. If Explode is active, accepted direct contact deals row-16 `mDamage[r]` minus row-18 `mDamage[r]`; otherwise it deals row-16 `mDamage[r]`. Removal and the fixed Fireball impact presentation precede the area/ember helper. | HIGH |
| 17 | **Embers.** Fireball impact creates exactly `round(mFragments[r])` Ember children carrying `mDamage[r]`; add `mManaCost[r]`. A projectile-private RNG chooses one starting heading, then children advance by `360/N` with signed jitter up to one third of that step. Each is born airborne, pre-ticked ten times, and owns bounce, ground-life, contact, and retirement state. Contact consumes an Ember without running its retirement mode. | HIGH |
| 18 | **Explode.** Fireball impact derives `visual_scale=(mRadius[r]-10)*0.18+1`, queries the native rectangular footprint with dimension `visual_scale*110`, and gives every returned target fixed damage `mDamage[r]*0.5`; add `mManaCost[r]`. This is impact-local and also runs on terrain impact. | HIGH |
| 19 | **Embers to Imps.** When a grounded authoritative mode-2 Ember naturally falls below life `1`, `Ember::Tick 0x0060D7E0` creates `GoodImp 0x3ED` and `Fire 0x7E3`, copies owner/team, writes `mDamage[r]*0.5` to both Imp attack lanes, and gives the Imp `300` ticks. `GoodImp::Tick 0x0052C1A0` owns nearest-hostile chase, decrements lifetime once per tick and once more while targetless, then creates Fire and removes the Imp. Contact-consumed Embers do not convert. Add `mManaCost[r]`; mutually exclusive with Immolate. | HIGH |
| 20 | **Immolate.** When a grounded authoritative mode-1 Ember naturally falls below life `1`, dispatch the common explosion helper with scale `1`, no child fragments, footprint dimension `110`, and fixed target damage `mDamage[r]*0.5`, then remove the Ember. Contact-consumed Embers do not immolate. Add `mManaCost[r]`; mutually exclusive with Embers to Imps. | HIGH |
| 21 | **Ring of Fire.** Pay `mManaCost[r]`; `0x0063F920` creates exactly 30 visual-only `MovingFire 0x7E6` segments at 12-degree base-heading intervals and one damaging `Shockwave 0x7E7`. Each segment consumes constructor phase and mirror-sign RNG before heading jitter, independent radial-unit geometry, and speed jitter. The Shockwave starts at radius `75`, grows by `6` per tick, carries `mDamage[r]`, writes one half to each of two target damage lanes (summed to full `mDamage`) plus Burn/Dazzle on each actor's first ten-tick contact, and pushes retained contacts on every even tick by `(target-origin)*pushScalar*6`. The ten-tick query precedes the push, so newly retained targets move on that same even tick. During the final `0.12375` life band the push scalar recurs by float32 `*0.899999976` per tick. Its draw slot does not paint a missile sprite: it submits DeadHawg record 18 to the Arena light field at radius `waveRadius/140`, intensity `pushScalar`, and shadow flag false. The MovingFire children never receive a damage write in this helper. | HIGH |
| 22 | **Burn.** Refresh total authored damage `mDamage[r]` at actor `+0x89C`. Qualifying fire contact attaches `Mod_Burn 0x1B73` for exactly `200` ticks with per-tick damage `mDamage[r]/200`. Same-type merge retains maximum remaining duration and maximum per-tick damage. Each tick owns one additive BadGuys `333..342` flame and one no-shadow misc light, consumes two gameplay RNG words, and fades both while fewer than 50 ticks remain. It has no separate mana cost. | HIGH |
| 23 | **Firewalker.** Toggle actor byte `+0x8DC`; refresh copies `mDamage[r]` and `mDuration[r]` to `+0x894/+0x898` and adds scalar **`mHoard=50` MP** to actor `+0x740`. Toggle-on immediately creates one owned `Fire_Goodguy 0x7EE`, forces its contact-geometry byte `+0x160=1`, and does not advance the periodic geometry counter. While active and outside player mode `2`, `PlayerWizard::Tick 0x00548B00` emits another patch on every global tick divisible by ten; this branch is not gated by nonzero movement. Every birth consumes the same seven-word program in native order: constructor `Float(32)`, constructor `Sign(1)`, signed `Float(10)` (two words), `Float(8)`, `Float(0.5)`, and `Float(0.25)`. The signed-10 and unsigned-8 values multiply the player's perpendicular and forward velocity lanes for the birth offset; scale becomes `1-Float(0.5)`, and life becomes `mDuration[r]*(1.1-Float(0.25))`. Periodic births use the process-global counter at `0x00819E54` to set `+0x160` in the repeating sequence `true,false,false`; the activation patch is independently always true. Only a geometry-enabled patch builds its strict center-radius contact list, though all patches render and renew ambient fire. The reserve is absolute: `hoarded_mp += 50`, not `maxMP*50%`. | HIGH-LIVE |

The G6 golden proves Firewalker's exceptional scalar semantics on a bot whose
Mana Up had raised maximum MP from 100 to 200: activation changed `+0x740`
from 0 to exactly 50, not 100. This is the template for actor-local effect
state: a learned row feeds derived state in the same actor's progression
object, and each emitted world actor carries that actor's ownership.

### Air, water, and earth

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 24 | **Lightning.** A held cast performs an ordered ray/chain query every native tick. Primary contact payload is `mDamage[r] / 100` per 100 Hz tick and mana use is `mManaCost[r] / 100` before actor modifiers. There is no projectile lifetime. Every subsequent chain hop multiplies the prior hop's damage by `0.6`. | HIGH |
| 25 | **Chaining.** The per-tick Lightning query may append `round(mArcs[r])` additional distinct targets; add `mManaCost[r]/100` mana per held tick. The target list prevents reuse within that tick; each appended hop uses the `0.6` damage decay. | HIGH |
| 26 | **Stun.** Lightning `0x0053F9C0` consumes the refreshed movement factor derived from `mStunAmount[r]` at wizard `+0x288`; when it is below one, contact creates `Mod_Stun 0x1B6A`, copies that factor to modifier `+0x1C`, and sets `+0x14=25` native ticks. Apply `0x006231B0` multiplies target movement `+0x120`; merge `0x00625850` keeps the maximum remaining duration and minimum movement factor. Add `mManaCost[r]/100` per held tick. | HIGH |
| 27 | **Magic Storm.** Pay `mManaCost[r]`; create `StormCloud 0x7F0` for 1,000 active ticks. At its authoritative strike cadence, choose a target with the active gameplay RNG and draw damage between `mDamage1[r]` and `mDamage2[r]`; dispatch electric flag `0x20`. | HIGH |
| 28 | **Magic Tornado.** Magic Storm enables moving-cloud mode at cloud `+0x180`, computes `frequency_factor = 1 + mSpeed[r]/100`, and adds `trunc(mDuration[r]*100)` ticks to the StormCloud's base 1,000-tick lifetime. `StormCloud::Tick 0x006021A0` resets each strike countdown to `trunc(numerator / frequency_factor)` for a uniform integer `numerator` in `[30,120]`, then authoritatively chooses one hostile target and rolls the configured storm damage. `mSpeed` changes strike frequency, not cloud translation; add `mManaCost[r]`. | HIGH |
| 29 | **Hurricane.** While Lightning is held, the handler can create storm/hurricane strikes using cached damage endpoints `mDamage1[r]/mDamage2[r]` at progression `+0x8D4/+0x8D8`; add `mManaCost[r]/100` per held tick. Each strike uses its event-time active gameplay RNG draw. Mutually exclusive with Disintegrate in offers. | MEDIUM |
| 30 | **Prismatic Shock.** Pay `mManaCost[r]`; the rectangular cast wave attaches `Mod_Prismatic 0x1B76` for `mDuration[r]*100` ticks. Apply sets target byte `+0x15C |= 0x20`; removal clears that bit. When an incoming contact's flags share `0x20`, `Badguy_Contact 0x0048A290` subtracts the secondary damage component a second time. This is the exact electric-susceptibility effect. | HIGH |
| 31 | **Disintegrate.** Refresh `round(mChance[r])` at progression `+0x8D2`; add `mManaCost[r]/100` per Lightning tick. On a successful active-gameplay-RNG percentile roll, the current Lightning contact sets transient flag `0x4`; `Badguy_Contact` forces HP to zero only when post-hit HP is below `0.20 * maxHP`. Mutually exclusive with Hurricane. | HIGH |
| 32 | **Frost Jet.** A held cast queries the current cone every native tick. Damage is `mDamage[r]/100` and mana is `mManaCost[r]/100` per 100 Hz tick before actor modifiers. Every candidate requires line of sight; there is no projectile actor or lingering gameplay contact after release. | HIGH |
| 33 | **Chill Wind.** Every Frost Jet contact adds configured `mPushback[r]` to the native impulse/tumble payload; add `mManaCost[r]/100` per held tick. It can tumble hostile arrows through the same contact query. | MEDIUM |
| 34 | **Cone of Ice.** The resolved widening scalar is copied to the wizard cast state. Exact forward reach is `205 + 4*mWiden[r]` world units (`180 + 25 + mWiden/2.5*10`); the same scalar expands the cone query width. Add `mManaCost[r]/100` per held tick. | HIGH |
| 35 | **Ring of Ice.** Pay `mManaCost[r]`; create `FreezeWave 0x7E8` with float32 life `0.924`, radius `75`, growth `6/tick`, and a ten-tick one-contact-per-target ledger. Life loses `.01/tick`, so gameplay retires on update 93. The independent presentation is three additive DeadHawg-114 fades, one normal DeadHawg-121 fade, and 100 `Anim_WhirlSnow` children (200 with Enhanced Effects) using BadGuys-72. Construction consumes exactly `3+8*N` RNG draws (803/1603), and the longest snow child lives 175 ticks after the gameplay wave. Records 16/17 are not used by this helper. | HIGH |
| 36 | **Harden.** While Frost Jet is held, add `mArmorPlus[r]/100` armor per native tick, capped at `mMaxArmor[r]`; add `mManaCost[r]/100` mana per tick. Refresh caches the cap/increment at progression `+0x8B8/+0x8BC`; stopping the channel stops accrual, not the existing armor value. | HIGH |
| 37 | **Cold Aura.** Refresh slow factor `1-mPercent[r]/100` at `+0x8AC` and radius `mRadius[r]` at `+0x8B0`. While Frost Jet is held, query that radius around the caster and attach/refresh cold slow on targets using the factor; add `mManaCost[r]/100` per tick. Mutually exclusive with Harden. | HIGH |
| 38 | **Hail.** Refresh damage endpoints and hit chance at `+0x8A0/+0x8A4/+0x8A8`. Each Frost Jet tick rolls `mToHit[r]%` on the active gameplay stream; success emits a hail contact with damage drawn between `mDamage1[r]` and `mDamage2[r]`. Add `mManaCost[r]/100` per tick. | HIGH |
| 39 | **Permafrost.** Refresh `slow_scale=1+mSlowdown[r]/100` at `+0x8B4`; all cold/freeze modifier applications multiply their slowdown effect by that scale and enforce a minimum 200-tick cold duration. No mana cost. | HIGH |
| 40 | **Boulder.** A held cast creates `Boulder 0x7D5`; base damage `B` is the exact additive/multiplicative formula in [`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md), whose rank input is `mDamage[r]`. Charge starts float32 `0.18`, grows by float32 `growth*0.0025` per tick, and scales damage on release; pay `mManaCost[r]/100` while held. Distinct-target ledger and residual damage pool live on the Boulder. | HIGH |
| 41 | **Earthquake.** Pay `mManaCost[r]`; create `Earthquake 0x7F1` with duration `mDuration[r]*100`. Its pulse is keyed to post-decrement `remaining % 30 == 0`, queries strict center distance `<512`, performs the native one-draw-per-entry full-bound shuffle, and visits exactly `floor(N/2)` hostiles. Each local visit consumes the pause gate, optional 50..99-tick pause draw, and heading perturbation. It has no damage property and never enters the normal damage ABI. A separately shuffled group-4 scenery ledger drives one prop wobble per update, enhanced BadGuys-10 dust, and lit BadGuys-2008..2010 bouncer debris. | HIGH |
| 42 | **Hasten Rocks.** Set wizard/Boulder growth factor to `1+mSpeedUp[r]/100`; the exact charge recurrence therefore uses `growth=float32(0.5 * cast_speed * (1+mSpeedUp[r]/100))`. Add `mManaCost[r]/100` per held tick. It does not multiply Boulder damage. | HIGH |
| 43 | **Bind Rocks.** Set the Boulder toughness input copied from wizard `+0x29C` to `mStrength[r]/100`; that factor governs damage-pool consumption when the rock is struck. Add `mManaCost[r]/100` per held tick. It does not multiply outgoing damage. | HIGH |
| 44 | **Rock Surge.** At Boulder creation/hold, roll `mChance[r]%` on the active gameplay RNG; success springs the current rock to full-size/release behavior. Charge the one-shot `mManaCost[r]` when the surge branch fires. Mutually exclusive with Gargantuan. | HIGH |
| 45 | **Raise Golem.** Pay `mManaCost[r]`, enforce this caster's summon cap, then ignore cursor aim. Consume `RandomSign(45)`, place an unadjusted point 100 units along `casterHeading +/- 45`, commit that pre-adjustment facing to the caster, and call `0x00645910` with radius `25`, scenery mask `0x205`, and no actor-body flag. A blocked point enters the resolver's random-phase elliptical rings with dynamic round-even sample count before `Golem 0x7F4` construction consumes its `RandomInt(2)` limb selector. The summon starts facing `casterFacing+180`; current/max HP=`mHP[r]`, attack range=`mDamage1[r]..mDamage2[r]`, and owner identity are copied. Base cap is one; actor feature bit `+0x878 & 0x08` permits two and evicts the lower-HP incumbent on replacement. | HIGH |
| 46 | **Stoneskin.** Pay `mManaCost[r]`; attach `Mod_StoneSkin` to this actor for `mDuration[r]*100` ticks. Its active damage gate rejects physical and magical harm. Reapplication merges through modifier lifetime rules rather than adding parallel invulnerability. | HIGH |
| 47 | **Gargantuan.** Raise the Boulder maximum-size scalar to `1+mSize[r]/100` and add `mManaCost[r]/100` per held tick. It changes size/charge ceiling, contact radius, and charge-derived output through the existing Boulder formula; it is not an independent damage multiplier. Mutually exclusive with Rock Surge. | HIGH |

The detailed primary geometry, float32 charge recurrence, projectile ownership,
and contact cadence remain normative in
[`native-projectile-and-spell-mechanics.md`](native-projectile-and-spell-mechanics.md).
G6 owns the rank/property inputs and actor-local state; it does not fork those
already-closed mechanics.

### Arcane

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 48 | **Teleport.** Pay `mManaCost[r]`; Arena virtual `+0x12C` (`0x00465440`) ignores the cursor and tiles the Region bounds on a 100-unit lattice inset by 100. Every cell receives the maximum truncated squared distance to any live Region actor carrying flag `0x2`, capped at `0x100000`; the complete cell list is shuffled with one `RandomInt(cellCount)` per cell and the first strict maximum wins. With no positive score it draws Y then X uniformly from the full bounds. The chosen point is passed through radius-40 resolver `0x00645910` with all collision flags and actor exclusion `-1`. A blocked point uses random-phase elliptical rings whose sample count is `round-even(pi*(searchRadius+40)/searchRadius)`, not a fixed six-point circle; failed rings expand by the multiplicative `Float(1)` recurrence. Base indoor Region virtual `0x00508900` instead returns `(0,0)`. The query has no rejection return. Refresh stores `mCooldown[r]` in row-relative cooldown cap/current fields `+0x1568/+0x1564`; rank replaces cooldown and cost. | HIGH |
| 49 | **Magic Circle.** Pay `mManaCost[r]`; create `MagicCircle 0x7EA` with fixed 1,500-tick life and slow input `mSlow[r]` at circle `+0x140`. Every 10 ticks, eligible enemies receive `Mod_CircleSlow 0x1B70`. A local player inside gains `mana_recovery(+0x98) * 2 / game_timing_scale` MP per callback, capped at max MP. **Stock healing defect:** it computes `candidate = HP + health_regeneration(+0x9C)*2/game_timing_scale`, compares candidate with current HP instead of max HP, and for normal positive regeneration writes current HP unchanged; the advertised healing boost is inert. | HIGH |
| 50 | **Magic Trap.** Pay `mManaCost[r]`; choose the bound component first (welds consume `Integer(2)`). Selector `0/1/2/3/4` resolves the effective rank of primary skill `8/16/24/32/40`. Ether alone calls inclusive float wrapper `0x00448480(mDamage1[ether rank],mDamage2[ether rank])` and consumes one damage RNG word; fire/air/water/earth read the selected skill's single `mDamage[element rank]` without that draw. Store `f32(base_damage * trap_mDamage[r])` at `+0x140`—never the equipped primary's maximum or a weld-wide aggregate. Float32 charge at `+0x144` adds `1/(mFullChargeSeconds*100)` and clamps on update 800. Every age divisible by 25, a 130-wide group-2 arming query may trigger one terminal 300-wide payload query; every target in that wider result receives `f32(full_payload * charge)` without a synthetic floor. Fire/water attach Burn/ColdSlow; water uses factor `f32(0.5/permafrostSlowScale)` for `max(50,trunc(400*charge))` ticks. Air instead zeroes direct contact and attaches one mergeable `Mod_ElectricBurn` for 100 updates at `payload/100`: every update follows the target, consumes signed `Float(.25)` for a light of radius `.5+jitter` and intensity one, renews `electric__loop`, consumes `Integer(3)` plus conditional `Float(.5)`, and deals its slice. Trap chain count is zero, so it draws no lightning sprite. Ether/earth use direct contact. Initialization owns `settrap` plus the bound primary start sample, updates 1..32 own two RNG words and an independent perspective shimmer each, and detonation owns the exact 502-word two-array/100-FuzzySpear burst plus the decaying 1.25 camera pulse. | HIGH |
| 51 | **Dampen.** Pay the single ranked `mManaCost`; query the cast rectangle, remove hostile guided/fire/dark missile actors, interrupt hostile caster actions, and dispel qualifying shields when `RandomInt(100) < 0x33`. Because the draw is `0..99`, that accepts **51/100** outcomes even though the authored UI says 50%. It then starts cast-spin action 21 at `0.5 * normal action damage`. No persistent actor scalar. | HIGH |
| 52 | **Spell Welding.** Learning enables selection of a pair among primaries 8/16/24/32/40. The pair becomes build 1000-1009; `0x00666020` normalizes the two current component vectors and the cast routes consume that vector, including component costs and upgrades. There is no conventional rank array. Exact pair/vector/dispatch semantics are normative in [`spell-welding.md`](spell-welding.md). | HIGH |
| 53 | **Flash.** Refresh chance/duration at actor `+0x744/+0x748`. When this actor is struck, roll `mChance[r]%` on the active gameplay RNG; success attaches the native dazzle/flash response to the attacker for `mDuration[r]*100` ticks. No mana cost and no additive stacking; reapplication uses modifier merge semantics. | MEDIUM |
| 54 | **Magic Shield.** Pay `mManaCost[r]`; install/refresh this wizard's shield state with absorb pool `mAbsorb[r]`. Incoming physical and magical damage consumes that pool before HP. Recast replaces/refreshes through the wizard virtual `+0x64`; parallel pools are not added. An absorbed hit drives the exact 40-tick player-shell pulse; break owns 20 additive BadGuys-68 children and clears the stored pool/factor only after its terminal callback. | HIGH |
| 55 | **Explosive Shield.** Add `mManaCost[r]` to Magic Shield and resolve `factor=mDamage[r]/100`. Magic Shield install writes that factor beside the shield's absorbed pool. On break, payload is `installed_absorb_pool * factor` (rank 1: `25*0.5=12.5`), not flat configured damage. Helper `0x00648790` writes half that payload to each of the two native contact lanes, which the target sums back to the full payload, over radius 110; it also owns the 502-word explosion VFX program and a zero-damage Shockwave. It does not fire on an ordinary unbroken refresh. | HIGH |

Magic Circle's mana branch and inert HP branch were read directly from
`0x005FB020`; they correct the earlier broad “boosts healing and mana” wording
in the projectile lifecycle document. A browser fidelity mode should preserve
the inert HP branch. Fixing it is a gameplay balance change, not reconstruction.

### Mind and body passives, including concentration

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 56 | **Mana Up.** On refresh, `maxMP(+0x80) = baseMP(+0x78) + mValue[r]`; HP/MP ratios are then restored and clamped. Rank 1 is exactly `+100`. | HIGH-LIVE |
| 57 | **Channel Mana.** On refresh, `mana_recovery(+0x98) = base_recovery * (1+mValue[r]/100)`. Concentration multiplies that result by `1+mConcentration/100 = 1.15`. Generic tick recovery is `+0x98/game_timing_scale`, capped at `maxMP-hoardedMP`. Rank 1 changes 10 to 12.5. | HIGH-LIVE |
| 58 | **Meditation.** Refresh writes idle delay `mSeconds[r]*100` to `+0x884` and recovery input `mValue[r]-1` to `+0x890`. Specialized tick `0x006614D0` increments idle elapsed `+0x888`; once it reaches the delay it calls `0x00656640`, then decrements activity ramp `+0x88C` toward zero. Activity hook `0x00659A40` increments `+0x88C` up to the delay and resets `+0x888`, except concentrated Meditation suppresses that elapsed reset. Recovery is `mana_recovery(+0x98) * multiplier / game_timing_scale`, where `multiplier=mValue[r]` at zero ramp and `1+(mValue[r]-1)*0.25` while the ramp is positive. Concentration therefore preserves an exact quarter-strength moving/acting bonus; it does not change the rank arrays. | HIGH |
| 59 | **Battle Mage.** On refresh, offensive mana factor `+0x3D4 = 1-mValue[r]/100`; concentration makes it `1-(mValue[r]+15)/100`. The cost resolver multiplies every flagged offensive cost by this actor-private factor. | HIGH |
| 60 | **Focus.** On refresh, secondary recharge factor `+0xD0 = 1+mValue[r]/100` (rank 1 is `2.0`). Concentration does not add the CFG value to that factor; each recharge event instead has a hard-coded active-gameplay-RNG 25% chance to bypass the normal recharge and become immediately available. | HIGH |
| 61 | **Siege Mage.** On refresh, offensive damage factor `+0xF8 = 1+mValue[r]/100`; concentration makes it `1+(mValue[r]+15)/100`. Flagged spell payload builders multiply by this actor-private factor. | HIGH |
| 62 | **Resist Magic.** On refresh, magic resistance accumulator `+0xA4 += mValue[r]/100`; concentration adds another `0.20`. The common magic-damage path retains `incoming * (1-resistance)`, subject to its native clamps. | HIGH |
| 63 | **Creativity.** When learned, desired offer count becomes 4 and every offer/item minimum requirement is reduced by 2. Concentration independently gives a 20% Insight roll after offers and applies the selected marked row twice. **Stock defect:** only slot A/index 16 is tested; slot B and Mind Chug never enable it. | HIGH |
| 64 | **Health Up.** On refresh, `maxHP(+0x74) = baseHP(+0x6C) + mValue[r]`; ratios are restored/clamped. Rank 1 is exactly `+50`. | HIGH-LIVE |
| 65 | **Enchant Staff.** With a staff, add `mDamage[r]` to both staff damage accumulators `+0xC4/+0xC8`; each melee action uses those absolute refreshed totals. The row declares maximum rank 15 but supplies 15 values (`0..14`); native property reader `0x0065D540` clamps rank 15 to the terminal value, so ranks 14 and 15 both contribute `36`. Concentration multiplies staff action timing scalar `action+0x34` by **1.75**, not the advertised 2.0. | HIGH |
| 66 | **Telekinesis.** On refresh, pickup-range scalar `+0xCC = mValue[r]*1.25`; concentration doubles it to `mValue[r]*2.5`. It changes this actor's pickup query, not item physics or another actor's magnet. | HIGH |
| 67 | **Rush.** On refresh, movement factor `+0x90 = 1+mValue[r]/100`; concentration multiplies by `1.25`, producing `(1+mValue[r]/100)*1.25`. The movement integrator consumes the actor-private factor. | HIGH |
| 68 | **Deflect.** While staff type `0x1B5C` is equipped, write chance `mValue[r]` to `+0xB8`; `PlayerActorMagicDamage 0x00548150` rolls `RandomInt(100)` and deflects when the result is below the truncated chance. A success faces the source, requests `swipe.wav` with pitch `1+RandomFloat(1,signed)`, and cancels the incoming event. The refresh-time concentration property read is still a zero-valued dead write to poison accumulator `+0xA8`, but concentration slots `16/20` or Mind Chug are checked again at event time: for a non-null nearby physical source and positive primary damage, `0x0054837B` reflects exactly `incoming*5` through `0x0063E7D0` onto the original source. Without a staff the refreshed chance is absent/zero. | HIGH |
| 69 | **Resist Poison.** On refresh, poison-duration resistance `+0xA8 += mValue[r]/100`; concentration adds `0.10`. Poison modifier duration is scaled by the remaining fraction `1-resistance`. | HIGH |
| 70 | **Faster Caster.** On refresh, cast progress factor `+0x94 = 1+mValue[r]/100`; concentration makes it `1+(mValue[r]+25)/100`. Native cast/action progress multiplies by this actor-private factor. | HIGH |
| 71 | **Fortunate Flailing.** On each staff attack, roll `mChance[r]%` on the active gameplay RNG. Success uniformly selects Knockback, Disabling Hit, Critical Hit, or Whirl; failure is normal. Disabling Hit multiplies target `+0x120` by `0.75` and flagged target `+0x1B4` by `0.5`; Critical is `3*` base; Whirl uses the radial action. Concentration multiplies damage of any non-normal result by `1.2`. | HIGH |

These concentration formulas are the landed
[`skills-concentration-discipline.md`](../re/skills-concentration-discipline.md)
contract. The older Deflect negative verdict in that campaign covered only the
refresh switch and is superseded by the event-time branch at
`0x005481A6..0x005483A8` above. Creativity's slot-A-only defect and the
loader's discipline replication repair remain pinned by
[`skillfix-discipline-and-concentration-2026-08-02.md`](../re/skillfix-discipline-and-concentration-2026-08-02.md).

### Advanced, toggled, and runtime-only rows

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 72 | **Acid Rain.** Pay `mManaCost[r]`; create `AcidRain 0x7FE` for 1,500 active ticks and store ranked `mDamage[r]` at actor `+0x154`. Every 25 ticks after its delay, shuffle hostile candidates with the active gameplay RNG and damage exactly `min(n,floor(n/3)+1)` targets. Tick `0x00604E90` publishes float32 `mDamage[r] / 6.0` from compiled double `0x007852E0`, with flags `0x18`; this is not the generic `/100` fire/contact normalizer. It is direct damage, not poison. | HIGH |
| 73 | **Fire Wall.** Pay `mManaCost[r]`; build a 300-unit line perpendicular to aim and create eleven owned `Fire_Goodguy 0x7EE` patches at 30-unit intervals, including both endpoints. At distance `d=0,30,...,300` from the first endpoint, multiply constructor scale by `0.8 + 0.6*sin(pi*d/300)`, overwrite life with scalar `7`, then add a random offset with unsigned radius `RandomFloat(10)` and a random unit heading. The creation loop explicitly writes each patch's contact-geometry byte `+0x160=1` at `0x0054F883`, so all eleven use the shared contact path; this differs from periodic Firewalker's `true,false,false` geometry cycle. The shared `Fire_Goodguy` tick subtracts `0.01` per tick, so this overwrite yields **700 ticks**, not the constructor's 200. Each patch carries `mDamage[r]` and applies the existing fire-patch per-second/tick normalization and Burn interaction. Creation requests `ignite` then `fireballhit`; live patches renew `lowfire__loop`. Dispatcher `0x0054CC50`; creation range `0x0054F759..0x0054F8EC`; constants `0x00785D90=150`, `0x00784ED8=30`, `0x007DE810=10`. | HIGH |
| 74 | **Ether Drain.** Pay `mManaCost[r]`; create `EtherDrain 0x807` with a nominal 40-tick scale-in, 1,000 active ticks, and 20-tick scale-out. Because scale is stored as float32 on every `+0.025`, update 40 is `0.9999995827674866` and the state transition occurs on update 41; total live updates are 1,061. Constructor `0x005F8360` computes the active countdown as `float32(0x00820230) * double(0x007DE810) = 100 * 10 = 1,000`; tick `0x0061CF20` decrements `+0x144` once per fixed tick. Candidate countdown `+0x180` starts at zero, falls by six per scale-in tick, one per active tick, and eleven per scale-out tick; hostile identities therefore refresh on ages `1,18,35,105,205,...,1005`. The strict 1,024 by 819.2 ellipse feeds a radius-512 pressure field with normalized inward strength `intensity*1.1*max(0.1,1-distanceSquared/262144)`; flag-`0x400` objects multiply by the falloff again. Contact is strict squared distance `<400`: start with `mDamage[r]/100`, double below `225`, double again below `100`, and double for target flag bit `0x1`; every hostile dispatch consumes `RandomFloat(0.5)`. Loose objects are also pulled; nonempty Gold/Sack containers are protected from premature center capture. Parent art is four additive `BadGuys[75]` galaxy layers plus source-over `BadGuys[38]` shimmer/pulse and the radius-2 random-intensity light. Ages `42..990` independently gate `SuckCloud` (BadGuys `10/11`, eight words on a successful spawn) and free-floating `SuckDebris` (DeadHawg `177..179`, five words on spawn and three per tick). Cloud retirement has no callback; debris completion calls `0x005EE840(0.5)`, producing capture pulse two without a flare. BadGuys-36 flares instead belong to direct center capture (`1.0`) and `Anim_Sucked` destruction (`1.5`). The actor renews `PlaneCross__Loop`. The dedicated `sounds\crunchdrain` registry entry is associated but its birth-playback callsite remains unresolved. | HIGH |
| 75 | **Iron Golem.** When Raise Golem creates a summon, set golem byte `+0x210`, write `reflectRatio=mReflect[r]/100` at `+0x214`, and include `mManaCost[r]` in the summon cost. After the 400-tick assembly grace, a nearby physical source receives `incomingPrimary * reflectRatio`; secondary incoming damage is not reflected. | HIGH |
| 76 | **Call Comet.** Pay `mManaCost[r]`; create `Comet 0x80C`, copy Permafrost-scaled freeze seconds to `+0x13C` and damage `mDamage[r]` to `+0x140`. Impact multiplies `+0x13C` by the native fixed-tick scalar for the large FreezeWave duration and dispatches `+0x140` through its damage lane. | HIGH |
| 77 | **Turn Undead.** Before its target query, dispatch registry 52 `sounds\levelup` twice as a fixed ordered pair at pitches `2.0` then `3.0`; each request separately derives gain from the cast point. Pay `mManaCost[r]`; query a strict 500-diameter footprint (radius 250, mask 2) and affect only Skeleton, Archer, Mage, and Zombie. Set both heading lanes away from the cast point and write `round(mFlee[r]*100)` as the target-owned countdown at `+0x20C`; the common hostile tick decrements that field. Only while its pre-cast value is the untouched sentinel `<=-9000`, multiply attack strength once by `1-mWeaken[r]/100`. Reapplication refreshes the countdown without compounding weakening. Presentation creates 35 source-alpha, gray `(0.5,0.5,0.5,1)` BadGuys-record-48 `Anim_FadeScale_Perspective` children at the cast point: initial angle is `RandomFloat(360)`, each next angle adds `20+RandomFloat(40)`, initial scale is `1+RandomFloat(1)`, scale recurs by `*1.1`, and alpha/life falls by `0.05` for 20 ticks. Native consumes the next-angle draw after every child, including one discarded draw after child 35, for 71 total VFX RNG words. | HIGH |
| 78 | **Mindstar.** Toggle actor byte `+0x8DD`. On refresh, add `maxMP * mHoard[r]/100` to actor `+0x740`, then add one temporary effective rank to every learned row `8..77`, capped at each compiled maximum. Permanent ranks do not change. | HIGH |
| 79 | **Regenerate.** Toggle actor byte `+0x8DE`. Refresh adds `maxMP * mHoard[r]/100` to actor `+0x740`. Each specialized progression update adds `1.5/game_timing_scale` HP; with generic health regeneration the combined per-update delta is `(1.5 + health_regeneration(+0x9C)/10)/game_timing_scale`, capped at max HP. Rank changes only the hoard percentage. | HIGH-LIVE |
| 80 | **Plane Orb.** Runtime-only primary forced by Planewalker. Cast creates `PlaneOrb 0x7EF`, copies caster ownership, and writes per-tick damage `2 * ether_line_effective_rank_sum / 100` from progression `+0x8D0` (IDs `8,10,9,13,14,15,12`). It starts at speed 1.75, countdown 1000, visual scale 0.5, acceleration scalar 1, and random maximum scale in `[1,2.5)`; every update advances position by `(acceleration+1)*velocity`. Ages `1..999` run the active branch, where acceleration recurs by float32 `*0.980000019` and scale grows by `0.01`; age `1000` starts the `0.02` terminal fade. Every sixth active authority update its `2*scale` hostile query applies exactly five stored per-tick payloads. Presentation is an additive `BadGuys[75]` core rotating at `1.5` degrees/tick plus a normal repeat-wrapped `images/etherplane.png` mesh with seven sectors, fifteen with Enhanced Effects, `1+2*N` vertices and `3*N` triangles. Cast helper `0x0052D360` creates 27 inward perspective children (`BadGuys[11,45]`) from exactly 180 VFX RNG words; with the constructor scale draw, birth consumes 181. Enhanced mode then emits one five-word `BadGuys[11]` perspective mote per active-branch update. Birth requests `distortreality` and `lightningstart` at exact pitch `2.0`, then writes the retained magenta Region flash to alpha `0.1`. It has no terrain collision, CFG, learned ranks, or ordinary offer eligibility. | HIGH |
| 81 | **Reserved.** Runtime row shares native selector space with the first weld path but has no CFG and no recovered standalone acquisition, cast, passive, or effect consumer. A browser must reserve the ID and never offer or synthesize an effect for it. | LOW |

For active Firewalker, Mindstar, and Regenerate, overload handling is common:
if the sum at actor `+0x740` exceeds that actor's max MP, `0x006639D0`
clears that actor's three toggles, current/reserved mana, and shows “Overloaded
Mana!” only for the local player. Firewalker contributes absolute 50; Mindstar
and Regenerate contribute rank-selected percentages of final max MP. They may
be active together, and their reserves add.

## Multiplayer ownership and observation

The multiplayer rule is the same as the native rule: **one materialized actor,
one progression object, one rank book, and one pair of HP/MP pools**. There is
no shared spellbook, statbook, hoard counter, or derived-stat singleton. A
session-level barrier may coordinate when participants resolve a level-up, but
it never aliases their actor state.

The loader's landed protocol makes that boundary explicit:

- `StatePacket` carries the owning participant's level, current/next XP,
  current/max HP and MP, element, discipline, concentration revision and A/B
  selections, absolute derived-stat snapshot, and persistent Firewalker,
  Mindstar, and Regenerate status bits. Each field is sampled from that
  participant's materialized actor/profile.
- `ParticipantProgressionBookSnapshotPacket` is reliable and revision-gated.
  It names the owner and session nonce, carries independent spellbook/statbook
  revisions, and sends each row's `entry_index`, `internal_id`, permanent
  `active` rank, effective/visible rank, category, and statbook cap. Receivers
  reject duplicate entry indices, stale revisions, wrong owners, and wrong
  session nonces before replacing only that participant's book snapshot.
- `LevelUpOfferPacket` names an authority participant, target participant,
  offer ID, run nonce, level, XP, and the target's ordered options. The reply
  names the chosen index and ID; the result returns the apply count and
  resulting active rank. `LevelUpBarrierPacket` coordinates completion for the
  cohort. This is synchronization of independently owned choices, not one
  shared offer pool.
- Concentration follows the already-landed transactional rule: A/B are stored
  per participant; a remote refresh temporarily installs that participant's
  lanes, refreshes that participant's progression, then restores the local
  lanes. Derived stats are separately replicated as absolute owner state. See
  [`skills-concentration-discipline.md`](../re/skills-concentration-discipline.md#multiplayer-semantics).
- The 2026-08-02 discipline repair captures the local actor's native quartet,
  converts the native root to the semantic wire enum, and primes the remote
  actor's own `+0x830`. See
  [`skillfix-discipline-and-concentration-2026-08-02.md`](../re/skillfix-discipline-and-concentration-2026-08-02.md).

What a peer observes is intentionally narrower than the owner's private ABI.
Peers receive level/XP, HP/MP, persistent toggles, resolved ranks and derived
stats; owned casts, projectiles, modifiers, and status presentation then use
those values. They do **not** receive a raw `+0x740` hoard float or a pointer to
the owner's progression. The attainable mana ceiling is reproduced from the
replicated toggles, ranks, and max MP. One-shot action state, RNG state, and
private cooldown counters remain owner-authoritative and are observed through
their resulting cast/effect snapshots.

### Bots use the same actor-private seams

A materialized bot exposes its own runtime progression at its actor's `+0x200`.
The bot path sets that progression's non-local mode, calls native `level_up`
against that object, calls the object's native offer-roll vtable, applies the
chosen row through the native appearance/progression choice method, and finally
calls the native actor progression refresh. The bot therefore gets:

1. its own `+0x30/+0x34/+0x38/+0x3C` level/XP tuple;
2. a pool built from its own element, discipline, permanent ranks,
   prerequisites, and actor-private offer seed at `+0x834`;
3. its own selected rank write and derived-stat rebuild; and
4. its own HP/MP ratio preservation around refresh.

The shared-level-up coordinator may copy a target level/XP milestone into each
participant before invoking those seams, but every bot rolls and applies its
own options. The G6 live fixture additionally uses different player and bot
actors and proves that writes to Mana Up, Channel Mana, Health Up, and
Firewalker change only the addressed bot progression while Regenerate changes
only the local-player progression.

## Persistence boundary

G8 establishes that participant gold, inventory/equipment, and progression
live outside hub `Region` objects and survive region replacement and a normal
completed-run return. The next run materializes from the same
participant-private state. See
[`native-hub-and-economy.md`](native-hub-and-economy.md#persistent-versus-regenerated)
and its
[`next-run state table`](native-hub-and-economy.md#hubprofile-state-used-by-the-next-run).
G13 likewise distinguishes durable participant progression from scene-local
actors and unfinished actions in
[`native-session-flow.md`](native-session-flow.md#teardown-and-reset-ownership).

The progression serializer `0x0065EE80` carries permanent ranks, selected
element `+0x82C`, selected discipline `+0x830`, the offer seed `+0x834`, and the
Hagatha flag span. The derived-state serializer `0x0067C830` carries the
principal refreshed block including the three active-toggle bytes
`+0x8DC..+0x8DE`. On materialization, effective ranks and the scalar caches in
this document are rebuilt from that actor's permanent book and persistent
flags; they are not independent durable skill data.

| State | Boundary |
| --- | --- |
| level, accumulated XP, permanent row ranks, element, discipline, Hagatha ownership, learned active toggles | participant progression; survives ordinary hub region reconstruction and completed-run return |
| effective rank `row+0x22`, max HP/MP and derived multipliers/resistances, `+0x740` hoard | reconstructed actor cache; reproduce from the durable rank/toggle book whenever the actor is materialized or refreshed |
| concentration A/B and Mind Chug `+0x828` timer | process/run selection state; explicitly not serialized and cleared by Create/reset |
| current HP/MP | participant vitals ledger across an ordinary scene handoff; preserve ratios while a progression refresh changes maxima |
| projectiles, spell-effect actors, modifier lifetimes, action ticks, target locks, offer UI state, and partially charged objects | scene/run transient; destroyed at teardown and never replayed into the next world |
| a fresh Create generation after the multiplayer match lifecycle resets | starts a fresh base progression; raw element/discipline may be preselected for convenience, but prior learned ranks are not retained merely by that preselection |

G10 owns the on-disk save/account codec, slot migration, and cross-process
restore contract. Its
[`Skills, books, class, and loadout`](native-save-format.md#skills-books-class-and-loadout)
section locates this durable subset in the resumable `gamestate`/Region object
graph, while its
[`Browser implementation contract`](native-save-format.md#browser-implementation-contract)
defines the browser codec and migration boundary. G6 does not duplicate that
format: "durable" here means the participant/profile lifecycle proven by G8
and mapped to bytes by G10.

## Golden recording and implementation contract

[`progression-goldens.json`](../../tests/fixtures/webgame/progression-goldens.json)
is a tick-stamped, actor-addressed recording from the stock game. Its recorder,
[`record_progression_goldens.py`](../../tools/record_progression_goldens.py),
derives source revision and binary hashes itself; it accepts no provenance
override. The recording contains:

- Skeleton, Imp, and Wraith kill presentation plus exact base, multiplier, and
  credited XP;
- three consecutive level-ups, each actor seed, full ordered pool, chosen
  index/ID, and before/after level/XP;
- before/after snapshots for Mana Up, Channel Mana, Health Up, Regenerate, and
  Firewalker, including actor/progression addresses and tick stamps; and
- a process/port cleanup receipt tied to the exact staged executable PID.

The kill recorder first exercises stock spawn and death presentation, then uses
the sanctioned native XP-grant seam against `actor+0x178`. Synthetic death
presentation alone does not credit XP, so the fixture identifies that boundary
rather than implying an unobserved stock kill reward dispatch. This is a
state/tick recording, not an asynchronously populated UI surface; the screen
settle rule does not apply. Every snapshot is instead ordered by native tick and
read back after the responsible native refresh/event call.

An implementing browser agent can rebuild progression without the binary by
using this order:

1. allocate the ABI table once per actor and seed its offer RNG from the named
   active-gameplay draw;
2. credit each kill with the family baseline and ordered actor/gameplay
   multipliers, then consume every crossed threshold;
3. build each offer from that actor's roots, ranks, requirements, adjacency,
   exclusions, focus rule, and private seed; preserve option order;
4. apply the selected permanent rank, refresh effective ranks and all cached
   formulas, then restore HP/MP ratios; and
5. publish owner state and resulting effects, never a shared mutable skill book.

## 2026-08-20 shared secondary cooldown and action gate closure

Fresh read-only decompilation of the retail image rejoined the belt input,
wizard dispatcher, action object, cooldown arming, and progression recurrence.
This closes the stock behavior around the already-recovered Phasing and
Teleport row capacities; those two row-local timers are not standalone delays.

### Input and action ownership

`Game` belt activation `0x005D5600` rejects an input before dispatch when the
game is paused, `PlayerWizard +0x1EC` has its no-interrupt latch set, the
progression-wide timer at `+0x64` is positive, or the selected row's current
cooldown at row `+0x64` is positive. The no-interrupt and progression-wide
branches are silent. The row-cooldown branch requests its stock unavailable
sound, then returns without calling the category-2 dispatcher.

An accepted input calls `PlayerWizard` vtable `+0x6C = 0x0054CC50`. Successful
ordinary category-2 branches call `0x005297D0`, which installs equipped-item
cast action mode 4 for a staff. `Action_PlayerWizard_StaffCast2` constructor /
tick `0x0044B7E0` / `0x0044B770` advances float32 progress by
`0.1 * progression(+0x94)` and releases only after the strict `progress > 5`
boundary. At neutral Faster Caster this occupies exactly 51 fixed updates,
holds `PlayerWizard +0x1EC`, and selects attachment pose 9. Faster Caster row
70 supplies `1+mValue/100` through `+0x94`, so the action interval shortens by
the native float32 recurrence rather than by an unrelated cooldown scalar.

The dispatcher does not install that common StaffCast2 action for Firewalker
toggle-off, Mindstar, or Regenerate. Their state changes and refresh/audio
owners remain the rows documented below. Dampen additionally replaces the
ordinary presentation action with its specialized mode-21 CastSpin contract.
All other accepted members of the 23-row category-2 dispatcher use the common
no-interrupt occupancy in addition to any row-local cooldown.

### Arming and recharge

After a successful dispatcher return, the belt calls `Skills_Wizard` vtable
`+0x80 = 0x00661F40`. Without concentrated Focus it calls `0x0065EDE0`, which
copies the selected row's authored cooldown capacity into that row's current
counter, clears every active row current strictly below the common capacity,
and copies progression `+0x68` into the progression-wide current timer at
`+0x64`. Constructor `0x006594E0` initializes `+0x68` from retail float
`0x0078489C = 150.0` fixed ticks. The common timer is therefore a fixed
1.5-second gate, not the maximum row cooldown: a Teleport keeps its 6,000-tick
private row while other skills become available after the 150-tick common
gate. Phasing's 100-tick row is cleared because the common timer outlasts it.
With Focus selected in a
concentration lane (or the timed concentration override), `RandomInt(100)`
values `75..99` bypass that copy: the skill is immediately ready in exactly
25 of 100 outcomes. This roll is part of the active gameplay RNG stream.

Progression recurrence `0x00656E70` walks every skill row and subtracts
`max(progression +0xD0, progression +0xD4 + 4*row.category)` from its current
float cooldown, clamping at zero. It separately subtracts `+0xD0` from the
progression-wide timer and clamps that value at zero; it does not recompute the
maximum on each update. `+0xD0` is the Focus-derived global recharge
factor and defaults to one. `+0xD4[...]` is the equipment-owned per-category
recharge factor used by `FX_RECHARGECLASS`; it also defaults to one. Therefore
rank-1 Focus makes ordinary secondary timers drain two native ticks per fixed
update, while an equipped category bonus may win the maximum independently.
The Website currently models no concentration selection or
`FX_RECHARGECLASS` producer; those two branches must be added only with their
own complete owners, never synthesized as a random cooldown shortcut.

`BeltButton::Present 0x005D3E10` enters cooldown drawing only when the selected
row's authored capacity is positive. It compares row current with common
current and draws the larger. When row current is positive it divides by the
row capacity; otherwise it divides common current by common capacity 150.
Consequently Phasing displays the 150-tick common fan, Teleport displays its
longer 6,000-tick row fan, and zero-`mCooldown` abilities can be silently common-
gated without drawing a fan. The dark-red square geometry and icon alpha remain
as previously recovered.

### Implementer and regression contract

- Preserve the shared action lock independently from row timers. A zero-
  cooldown ability still cannot be recast during its accepted StaffCast2.
- Store and decrement row capacities in native fixed-tick units: Phasing rank
  one is authored as 100 but is subsumed by the common 150; Teleport rank one
  is 6,000 and remains row-local after the common gate expires.
- Arm the progression-wide timer to exactly 150 after each dispatcher success,
  clear every shorter row current, and gate every secondary slot on it.
- Apply the Focus scalar to every cooling row, not only the selected belt slot.
- Keep cooldown rejection, action rejection, mana rejection, and a helper-level
  post-payment failure (for example fully blocked Phasing) as distinct edges.
- Regress neutral 51-update occupancy, Faster Caster float32 shortening,
  Focus rank-one two-per-update recharge, the common/Phasing/Teleport presenter
  branches, and the three actionless toggle/state branches.

## SkillScreen, InventoryScreen coexistence, and live loadout editing

This closes the reusable native interaction contract for the optional player
books in both the College and an active Boneyard. Evidence uses the unmodified
retail Beta 0.72.5 executable, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
launched directly from an isolated copy with no loader. The settled clean-stock
frames are
`tests/fixtures/webgame/menu-reference-captures/skill-screen.png` (SHA-256
`5b2423d5daf56e6bb5d154dd2ce0abc80d947286f087c8f81134b01686bb1c87`)
and `skill-screen-duplicate-belt.png` (SHA-256
`e934a18512ef5ed92753be150f5a37e5182751c8ed25644f5030a5d63b87f05d`).
The same fresh Ether/Mind actor was observed in the Hub and Boneyard; the
settled SkillScreen pixels and interaction geometry were identical.

### Ownership, entry, and lifetime

- DirectInput preset construction at `0x005A8790` binds Inventory to scan code
  `0x17` (`I`) and Skills to `0x14` (`T`) in both control presets. The HUD
  callbacks are parallel mouse/touch entry points.
- Action dispatcher `0x00689750` maps action `0x405` to Inventory opener
  `0x005C6F10` when gameplay `+0x15A0` is empty and action `0x406` to
  SkillScreen opener `0x005CA640` when gameplay `+0x1664` is empty. The
  dispatcher does not repeatedly toggle a screen while its pointer is live.
- `0x005CA640` first closes the live InventoryScreen, closes an existing
  SkillScreen when called directly, otherwise constructs the 0x168-byte
  `SkillScreen` through `0x006576C0`, writes gameplay `+0x1664`, and attaches
  it to the UI tree. `SkillScreen` destruction `0x0066B200` clears suspension,
  refreshes the actor-owned derived book when necessary, destroys every page,
  and releases the actor reference. Inventory has the symmetric exclusion
  contract recovered in `native-hub-and-economy.md`.
- Open `0x0067CAC0` increments the UI nesting/suspension depth through
  `0x005CBD40(1)`, assigns the page region `(0,50,screenWidth,screenHeight-140)`,
  opens the child, installs the actor's quickbar state, and builds all pages.
  `SkillScreen::Tick 0x006567E0` adds exactly `0.025` to opacity each 10 ms
  fixed tick and clamps at one. Close `0x006568E0` marks the screen closing;
  the same tick subtracts `0.025` until zero and destroys the screen. The
  auxiliary pulse at `+0x9C` multiplies by `0.9` and clamps below `0.01`.
  The open and close envelopes are therefore 40 fixed ticks each.
- Neither `0x005CA640`, constructor `0x006576C0`, open `0x0067CAC0`, close
  `0x006568E0`, nor the tick path requests an audio-registry member. Skills
  open/close is silent. Inventory open is also silent; standalone Inventory
  close owns registry 64 `openpanel` as documented separately.

### Fixed chrome and complete asset membership

`SkillScreen::RenderRoot 0x0065B550` paints an opaque stock screen rather than
dimming the live world. Its direct UI membership is records `3`, `30`, `31`,
`32`, and `49`; its page and quickbar members are Skills `5`, `6`, `12`, `14`,
the full authored icon span `27..122`, and glows `164..165`. Text uses Fonts
groups `1..92`, `93..184`, `216..307`, and uppercase `350..375`. The complete
membership is extractable from `native-asset-object-map.json`; no CSS leather,
generic rectangle, OS font, or screen capture is a runtime substitute.

The root draws the stock leather fill and its shared `UI.10/79` chain rails,
four masonry
corner/edge assemblies, the top-centred `SKILLS` label, two exact help lines,
and the persistent eight-slot bottom quickbar. At 1600 by 900 the quickbar
logical slot origins are `468,528,588,648,898,958,1018,1078` at `y=832.5`,
with 53-square slots and the stock centre gap. The same HUD inventory/XP/cast
strip remains at the bottom; it is part of the screen composition, not the
hidden world.

### Pages, selection state, and interactions

- Builder `0x0066B380` performs two actor-owned learned-vector passes in stored
  order. Every learned row with no dependency creates one `SkillPage`; every
  learned transitive dependent is appended to each reachable root through
  recursive predicate `0x0065E670`. Shared `any` dependencies intentionally
  repeat because no consumed set exists. Runtime-only 80, reserved 81, and
  allocated reserve 82 are never public page rows.
- A page is 200 by 300; each appended dependent adds 160 width. Pages wrap at
  screen width minus 10, rows advance by 300, all rows share the widest-row
  centred X origin, and the one-row case is vertically centred in the
  `(0,50,screenHeight-140)` region. `SkillPage::Open 0x00673EE0` creates one
  exact icon hit target per row from the atlas record's logical dimensions.
- `SkillPage::Render 0x006720F0` uses Skills `5` for the ordinary card, `6` for
  dependency arrows, `14` for Spell Welding, icons from `27..122`, and
  `164..165` for root/selection light. It always renders row name, element,
  quick description, and category footer. The selected primary carries the
  green `CASTING` label/border; selectable category-2 rows carry the gold belt
  border; concentrated category-3 rows carry their native selected treatment.
- `Skills_Quickbar` constructor `0x00657A70`, render `0x0066F330`, and pointer
  handler `0x00659AD0` expose all eight participant-owned intent slots.
  Slot zero is right mouse; slots one through seven are keyboard actions
  `1..7`. Dragging an enabled learned category-2 card replaces the addressed
  slot. Clean stock placed Call Leviathan in slots zero and one simultaneously:
  duplicate skill IDs are legal and each slot remains independently bound.
  A port that removes the old occurrence or rejects duplicate belt IDs is not
  native behavior.
- Learned-category selector `0x0066F0B0` and settings action
  `0x005D8120` own `Select Primary Attack` and `Select Concentration` modal
  choices. Primary accepts learned category-1 primary identities.
  Concentration accepts exactly `57..63` and `65..71`, fills A, conditionally
  fills B with Split Mind, alternates replacement when full, rejects
  duplicates, and rejects changes while Mind Chug owns the timed override.
- Both screens suspend the local actor input before the first presented frame.
  Accepted inventory use/equip and book/loadout commands mutate only the
  addressed actor/profile. Hub and Boneyard are consumers of the same screen
  objects and actor books; neither scene owns a parallel inventory or skill
  book.

### Regression contract

An implementation must cover `I`, `T`, both HUD buttons, Hub, Boneyard,
Inventory-to-Skills replacement, close during each 40-tick envelope, all 72
public authored skill rows `8..79`, every dependency root/branch, all eight
belt slots including duplicate IDs, primary selection, concentration A/B and
Mind Chug rejection, inventory selection/details, six potion subtypes, seven
equipment sinks, and owner isolation. A real browser journey must prove local
movement/cast suppression while either screen is live and authoritative state
survival after close in both scenes.

## Not Yet Reversed

- **Row 81 has no recovered consumer (LOW).** It occupies native selector space
  beside weld-special handling, but no CFG, ordinary acquisition, cast, passive,
  or event path was reachable. Reserve it and never offer it.
- **Rows 14, 29, 33, 50, 53, and 80 remain MEDIUM.** Their catalog
  inputs, state locations, and principal consumers are statically recovered,
  but a complete live event trajectory or one initializer edge was not safely
  reachable in the solo fixture. Implement only the stated behavior; do not
  invent additional stacking, targeting, or persistence.
- **Retail behavior after the level-75 table overrun is intentionally not
  probed.** Native code can read beyond the 76-entry threshold table. The
  browser contract is the explicit safe clamp at level 75 and 10,000,000 XP.
- **G10 did not capture a nonempty permanent skill book.** Its native container,
  lifecycle, byte preservation, and browser migration contract are complete in
  [`native-save-format.md`](native-save-format.md); the runtime meanings and
  serializer boundary are complete here. Do not invent a second save codec or
  infer additional per-skill save fields from the empty specimen.
