# Native progression and per-skill effects

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
   A category-4 candidate is retried while the result already contains a
   category-4 row and fewer than 50 such collisions have occurred; after 50 it
   is allowed. Stock performs no ID-equality rejection and never removes a
   chosen candidate, so duplicate non-category-4 IDs are possible. On attempt
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
| 10 | **More Missiles.** At Missile cast, `quantity = round(mQuantity[r])`; create that many alternating-heading projectiles and add `mManaCost[r]` to cost. The fan alternates left/right and applies the native per-projectile scale decay closed by G2. | HIGH |
| 11 | **Call Leviathan.** On secondary cast, pay `mManaCost[r]`, create `Leviathan 0x7F2`, and build `round(mQuantity[r])` appendages. Its active phase emits `EtherBolt 0x7F3` children carrying `mDamage[r]`; duration/lifecycle belongs to the spawned actor, not progression. | HIGH |
| 12 | **Planewalker.** On toggle-on, pay `mManaCost[r]`, attach `Mod_Planewalker 0x1B75` for `mDuration[r] * 100` native ticks, save the previous selected spell at wizard `+0x308`, set target flag `+0x138 |= 0x10`, and force Plane Orb 80. Expiry/removal restores plane state/selection. Reapplying keeps the greater remaining duration. | HIGH |
| 13 | **Piercing.** Refresh caches `pierces=round(mPierces[r])` at `+0x8C0` and residual factor `1-mLoss[r]/100` at `+0x8C4`. A Missile can pass through `pierces` contacts; each subsequent payload is multiplied by the residual factor. Add `mManaCost[r]`. Mutually exclusive with Ether Blast in offers. | HIGH |
| 14 | **Ether Blast.** Refresh `charges=round(mCharges[r])` at `+0x8C8`. While Magic Missile is not firing, the actor charges up to that count; the next qualifying pulse reduces enemy maximum-health state through the Missile contact payload. Charges are runtime actor/cast state and the learned rank supplies only the cap. Mutually exclusive with Piercing. | MEDIUM |
| 15 | **Phasing.** On cast, pay `mManaCost[r]`; probe at most 20 forward collision-tested steps and relocate the actor to the first accepted point, then emit traversal presentation. Refresh stores cooldown cap/current in the row-relative cooldown fields (`+0x6F8/+0x6F4`) from `mCooldown[r]`; there is no second cooldown write inside the relocation helper. | HIGH |
| 16 | **Fireball.** On cast, pay `mManaCost[r]`, create one `Fireball 0x7D4`, and copy `mDamage[r]` plus rows 17-20/22 into its impact payload. Direct impact dispatches that base damage through the common damage path. | HIGH |
| 17 | **Embers.** Fireball impact creates `round(mFragments[r])` ember children, each with `mDamage[r]`; add `mManaCost[r]` to Fireball cost. Embers-to-Imps and Immolate replace/extend the spent-ember event, not the learned row. | HIGH |
| 18 | **Explode.** Fireball impact performs an area query of configured `mRadius[r]` and applies `mDamage[r]` splash payload; add `mManaCost[r]`. Its result is impact-local, with no refreshed actor scalar. | HIGH |
| 19 | **Embers to Imps.** In `Ember::Tick 0x0060D7E0`, a spent authoritative mode-2 Ember creates `GoodImp 0x3ED` and `Fire 0x7E3`, copies its owner/team, writes the snapshotted `mDamage[r]` payload to both Imp attack lanes, and gives the Imp `300` native ticks. `GoodImp::Tick 0x0052C1A0` owns nearest-target chase, decrements lifetime once per tick and once more while targetless, then creates Fire and removes the Imp. Add `mManaCost[r]`; mutually exclusive with Immolate. | HIGH |
| 20 | **Immolate.** On ember impact/expiry, apply an additional explosion carrying `mDamage[r]`; add `mManaCost[r]`. Mutually exclusive with Embers to Imps. | HIGH |
| 21 | **Ring of Fire.** Pay `mManaCost[r]`; create the expanding `MovingFire 0x7E6` segment ring and terminal `Shockwave 0x7E7`, each attributed to the caster and carrying `mDamage[r]`. Contact pushes enemies through the ring actor's event path. | HIGH |
| 22 | **Burn.** Refresh `mDamage[r]` at actor `+0x89C`. Qualifying fire contact attaches/refreshes `Mod_Burn 0x1B73`, whose timed tick applies that damage payload. It has no separate mana cost. | HIGH |
| 23 | **Firewalker.** Toggle actor byte `+0x8DC`; refresh copies `mDamage[r]` and `mDuration[r]` to `+0x894/+0x898` and adds scalar **`mHoard=50` MP** to actor `+0x740`. While moving, the player tick emits owned `Fire_Goodguy 0x7EE` trail patches with that damage/duration. The reserve is absolute: `hoarded_mp += 50`, not `maxMP*50%`. | HIGH-LIVE |

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
| 35 | **Ring of Ice.** Pay `mManaCost[r]`; create the radial `FreezeWave 0x7E8` carrying `mDamage[r]`. Each outward contact attaches the frozen/cold modifier selected by the target state and applies the configured damage. | HIGH |
| 36 | **Harden.** While Frost Jet is held, add `mArmorPlus[r]/100` armor per native tick, capped at `mMaxArmor[r]`; add `mManaCost[r]/100` mana per tick. Refresh caches the cap/increment at progression `+0x8B8/+0x8BC`; stopping the channel stops accrual, not the existing armor value. | HIGH |
| 37 | **Cold Aura.** Refresh slow factor `1-mPercent[r]/100` at `+0x8AC` and radius `mRadius[r]` at `+0x8B0`. While Frost Jet is held, query that radius around the caster and attach/refresh cold slow on targets using the factor; add `mManaCost[r]/100` per tick. Mutually exclusive with Harden. | HIGH |
| 38 | **Hail.** Refresh damage endpoints and hit chance at `+0x8A0/+0x8A4/+0x8A8`. Each Frost Jet tick rolls `mToHit[r]%` on the active gameplay stream; success emits a hail contact with damage drawn between `mDamage1[r]` and `mDamage2[r]`. Add `mManaCost[r]/100` per tick. | HIGH |
| 39 | **Permafrost.** Refresh `slow_scale=1+mSlowdown[r]/100` at `+0x8B4`; all cold/freeze modifier applications multiply their slowdown effect by that scale and enforce a minimum 200-tick cold duration. No mana cost. | HIGH |
| 40 | **Boulder.** A held cast creates `Boulder 0x7D5`; base damage `B` is the exact additive/multiplicative formula in [`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md), whose rank input is `mDamage[r]`. Charge starts float32 `0.18`, grows by float32 `growth*0.0025` per tick, and scales damage on release; pay `mManaCost[r]/100` while held. Distinct-target ledger and residual damage pool live on the Boulder. | HIGH |
| 41 | **Earthquake.** Pay `mManaCost[r]`; create `Earthquake 0x7F1` with duration `mDuration[r]*100`. Every 30 ticks it shuffles hostile candidates with the active gameplay RNG and disrupts up to half by cancelling/replacing action state and perturbing heading/reaction. It has no damage property and never enters the normal damage ABI. | HIGH |
| 42 | **Hasten Rocks.** Set wizard/Boulder growth factor to `1+mSpeedUp[r]/100`; the exact charge recurrence therefore uses `growth=float32(0.5 * cast_speed * (1+mSpeedUp[r]/100))`. Add `mManaCost[r]/100` per held tick. It does not multiply Boulder damage. | HIGH |
| 43 | **Bind Rocks.** Set the Boulder toughness input copied from wizard `+0x29C` to `mStrength[r]/100`; that factor governs damage-pool consumption when the rock is struck. Add `mManaCost[r]/100` per held tick. It does not multiply outgoing damage. | HIGH |
| 44 | **Rock Surge.** At Boulder creation/hold, roll `mChance[r]%` on the active gameplay RNG; success springs the current rock to full-size/release behavior. Charge the one-shot `mManaCost[r]` when the surge branch fires. Mutually exclusive with Gargantuan. | HIGH |
| 45 | **Raise Golem.** Pay `mManaCost[r]`, enforce this caster's summon cap, create `Golem 0x7F4`, and write current/max HP=`mHP[r]`, attack range=`mDamage1[r]..mDamage2[r]`, and owner identity. Base cap is one; the actor feature bit `+0x878 & 0x08` permits two and evicts the lower-HP incumbent on replacement. | HIGH |
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
| 48 | **Teleport.** Pay `mManaCost[r]`; the world relocation query selects the safe destination and writes it to this wizard. Refresh stores `mCooldown[r]` in the row-relative cooldown cap/current fields `+0x1568/+0x1564`; rank replaces the cooldown and cost. | HIGH |
| 49 | **Magic Circle.** Pay `mManaCost[r]`; create `MagicCircle 0x7EA` with fixed 1,500-tick life and slow input `mSlow[r]` at circle `+0x140`. Every 10 ticks, eligible enemies receive `Mod_CircleSlow 0x1B70`. A local player inside gains `mana_recovery(+0x98) * 2 / game_timing_scale` MP per callback, capped at max MP. **Stock healing defect:** it computes `candidate = HP + health_regeneration(+0x9C)*2/game_timing_scale`, compares candidate with current HP instead of max HP, and for normal positive regeneration writes current HP unchanged; the advertised healing boost is inert. | HIGH |
| 50 | **Magic Trap.** Pay `mManaCost[r]`; derive the current primary's damage, multiply it by `mDamage[r]`, and store that full-charge payload at trap `+0x140`. Charge at `+0x144` rises from 0 to 1 over the configured 800 native ticks; the 25-tick trigger query applies `full_payload * charge` once to every returned target, then removes the trap. Fire/air/water also attach Burn/ElectricBurn/ColdSlow; ether/earth use direct contact. | MEDIUM |
| 51 | **Dampen.** Pay the single ranked `mManaCost`; query the cast rectangle, remove hostile guided/fire/dark missile actors, interrupt hostile caster actions, and use an active-gameplay-RNG 50% test to dispel qualifying shields. It then starts cast-spin action 21 at `0.5 * normal action damage`. No persistent actor scalar. | HIGH |
| 52 | **Spell Welding.** Learning enables selection of a pair among primaries 8/16/24/32/40. The pair becomes build 1000-1009; `0x00666020` normalizes the two current component vectors and the cast routes consume that vector, including component costs and upgrades. There is no conventional rank array. Exact pair/vector/dispatch semantics are normative in [`spell-welding.md`](spell-welding.md). | HIGH |
| 53 | **Flash.** Refresh chance/duration at actor `+0x744/+0x748`. When this actor is struck, roll `mChance[r]%` on the active gameplay RNG; success attaches the native dazzle/flash response to the attacker for `mDuration[r]*100` ticks. No mana cost and no additive stacking; reapplication uses modifier merge semantics. | MEDIUM |
| 54 | **Magic Shield.** Pay `mManaCost[r]`; install/refresh this wizard's shield state with absorb pool `mAbsorb[r]`. Incoming physical and magical damage consumes that pool before HP. Recast replaces/refreshes through the wizard virtual `+0x64`; parallel pools are not added. | HIGH |
| 55 | **Explosive Shield.** Add `mManaCost[r]` to Magic Shield. When that actor's shield breaks, its break event performs an area contact with `mDamage[r]`; the effect does not fire on an ordinary unbroken refresh. | HIGH |

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
| 65 | **Enchant Staff.** With a staff, add `mDamage[r]` to both staff damage accumulators `+0xC4/+0xC8`; each melee action uses those absolute refreshed totals. Concentration multiplies staff action timing scalar `action+0x34` by **1.75**, not the advertised 2.0. | HIGH |
| 66 | **Telekinesis.** On refresh, pickup-range scalar `+0xCC = mValue[r]*1.25`; concentration doubles it to `mValue[r]*2.5`. It changes this actor's pickup query, not item physics or another actor's magnet. | HIGH |
| 67 | **Rush.** On refresh, movement factor `+0x90 = 1+mValue[r]/100`; concentration multiplies by `1.25`, producing `(1+mValue[r]/100)*1.25`. The movement integrator consumes the actor-private factor. | HIGH |
| 68 | **Deflect.** While staff type `0x1B5C` is equipped, write chance `mValue[r]` to `+0xB8`; the harmful-contact gate rolls that percent and deflects on success. Without a staff the refreshed field is absent/zero. **Concentration is inert:** stock reads nonexistent `mConcentration` as zero and adds it to poison accumulator `+0xA8`; no advertised x5 reflection branch exists. | HIGH |
| 69 | **Resist Poison.** On refresh, poison-duration resistance `+0xA8 += mValue[r]/100`; concentration adds `0.10`. Poison modifier duration is scaled by the remaining fraction `1-resistance`. | HIGH |
| 70 | **Faster Caster.** On refresh, cast progress factor `+0x94 = 1+mValue[r]/100`; concentration makes it `1+(mValue[r]+25)/100`. Native cast/action progress multiplies by this actor-private factor. | HIGH |
| 71 | **Fortunate Flailing.** On each staff attack, roll `mChance[r]%` on the active gameplay RNG. Success uniformly selects Knockback, Disabling Hit, Critical Hit, or Whirl; failure is normal. Disabling Hit multiplies target `+0x120` by `0.75` and flagged target `+0x1B4` by `0.5`; Critical is `3*` base; Whirl uses the radial action. Concentration multiplies damage of any non-normal result by `1.2`. | HIGH |

These concentration formulas are the landed
[`skills-concentration-discipline.md`](../re/skills-concentration-discipline.md)
contract. The Deflect and Creativity negative verdicts and the loader's
discipline replication repair are additionally pinned by
[`skillfix-discipline-and-concentration-2026-08-02.md`](../re/skillfix-discipline-and-concentration-2026-08-02.md).
They are stock behavior, including the defects; G6 does not invent fixes.

### Advanced, toggled, and runtime-only rows

| ID | Runtime effect, state, timing, and stacking | Confidence |
| ---: | --- | --- |
| 72 | **Acid Rain.** Pay `mManaCost[r]`; create `AcidRain 0x7FE` for 1,500 active ticks. Every 25 ticks after its delay, shuffle hostile candidates with the active gameplay RNG and damage at most roughly one third using `mDamage[r]/100` per-second-normalized contact with flags `0x18`. It is direct damage, not poison. | HIGH |
| 73 | **Fire Wall.** Pay `mManaCost[r]`; build a line perpendicular to aim and create owned `Fire_Goodguy 0x7EE` patches. Each patch carries `mDamage[r]` and applies the existing fire-patch per-second/tick normalization and Burn interaction. | HIGH |
| 74 | **Ether Drain.** Pay `mManaCost[r]`; create `EtherDrain 0x807` with scale-in, 100 active ticks, and scale-out. Nearby actors are pulled inward and close actors receive `mDamage[r]/100` per-tick contact with flags `0x10A`; loose objects are also pulled and consumable nonempty Gold/Sack containers are protected from premature removal. | HIGH |
| 75 | **Iron Golem.** When Raise Golem creates a summon, set golem byte `+0x210`, write `reflectRatio=mReflect[r]/100` at `+0x214`, and include `mManaCost[r]` in the summon cost. After the 400-tick assembly grace, a nearby physical source receives `incomingPrimary * reflectRatio`; secondary incoming damage is not reflected. | HIGH |
| 76 | **Call Comet.** Pay `mManaCost[r]`; create `Comet 0x80C`, copy damage `mDamage[r]` to `+0x13C` and freeze duration `mFreeze[r]*100` to `+0x140`. Impact creates the large FreezeWave burst, applies damage, and dispatches that freeze duration to the area. | HIGH |
| 77 | **Turn Undead.** Before its target query, dispatch registry 52 `sounds\levelup` twice as a fixed ordered pair at pitches `2.0` then `3.0`; each request separately derives gain from the cast point. Pay `mManaCost[r]`; affect only Skeleton, Archer, Mage, and Zombie. Set flee heading/state for `mFlee[r]*100` ticks and, once per stamped application, multiply attack strength by `1-mWeaken[r]/100`. Reapplication refreshes control state without repeatedly compounding the weakening stamp. | HIGH |
| 78 | **Mindstar.** Toggle actor byte `+0x8DD`. On refresh, add `maxMP * mHoard[r]/100` to actor `+0x740`, then add one temporary effective rank to every learned row `8..77`, capped at each compiled maximum. Permanent ranks do not change. | HIGH |
| 79 | **Regenerate.** Toggle actor byte `+0x8DE`. Refresh adds `maxMP * mHoard[r]/100` to actor `+0x740`. Each specialized progression update adds `1.5/game_timing_scale` HP; with generic health regeneration the combined per-update delta is `(1.5 + health_regeneration(+0x9C)/10)/game_timing_scale`, capped at max HP. Rank changes only the hoard percentage. | HIGH-LIVE |
| 80 | **Plane Orb.** Runtime-only primary forced by Planewalker. Cast creates `PlaneOrb 0x7EF`, copies caster ownership, derives payload `+0x154` from equipped-item state, and uses the plane-side contact lifecycle. It has no CFG, learned ranks, or ordinary offer eligibility. | MEDIUM |
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
