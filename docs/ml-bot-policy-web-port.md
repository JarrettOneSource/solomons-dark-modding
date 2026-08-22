# ML Bot Policy — Web Port amendment (schema v5)

Status: proposal, 2026-08-22. Owner direction the same day: the learned bot
runs in the Web Port, and all native-game bot planning is dropped. This
document amends the v3 charter (`ml-bot-policy-v3.md`) for the Web Port
runtime and answers one question precisely: does the policy see projectiles
— its own and the enemy's — and the minions it summons?

It is a contract document in the v3 sense. Every field has a named source in
the web simulation (`Website/frontend/src/game/`), every scale is a named
constant, and nothing here is a compatibility shim over schema v4. Schema,
model, main-trajectory, and choice-trajectory versions become 5.

## 1. What v3/v4 actually observes

Verified 2026-08-22 against `origin/codex/ml-bot-v3-20260730`.

| Entity | v4 | Where |
| --- | --- | --- |
| Enemy projectiles, persistent areas, beams | observed | Block N. `policy_hazards.lua` reads `sd.world.get_replicated_hazards()`, keeps rows with `active == true and hostile == true`, and sorts the 12 nearest by edge distance. |
| The bot's own projectiles (Fireball, boulder, Ether Bolt, Magic Missile, Comet, ...) | **not observed** | Same filter: `hostile == true` drops every row the bot or an ally sourced. Adjudication 5 excludes "friendly/self effects" by rule. |
| The bot's own persistent areas (Magic Circle, Magic Trap, Storm Cloud, Fire Patch, Acid Rain, Earthquake, Ether Drain, ...) | **not observed** | Same filter. Block C exposes the slot's cooldown/mana/readiness only: the bot knows it cast, never where the effect is or whether it is still live. |
| The bot's own golem (Raise Golem 45, Iron Golem 75) | **not observed** | Run replication carries it as a `native_minion` actor with owner, iron flag, and timers (`world_snapshot_capture.inl` `IsNativeMinionType`; Lua row fields `native_minion*` at `lua_engine_bindings_gameplay.cpp:200-281`), but `steering.live_enemies` keeps only `tracked_enemy` actors, Block I is built from `participants[]`, and no bot-brain script reads any `native_minion*` field. |
| Allied players' golems | **not observed** | Same. |
| Enemy-side summons (Imp splits, Portal spawns, Coffin maggots, cocoons) | observed | They are `tracked_enemy` actors, so Blocks D/K carry them as ordinary enemies. |

The golem omission is an absence, not a misclassification: the golem never
leaks into the enemy block, so the target head cannot select it. But a golem
build cannot learn to anchor on its tank, time the recast, or value Iron
Golem, and every build is blind to its own areas, so "pull the melee line
through my Magic Circle" is unlearnable. The game has exactly one HP-bearing,
AI-driven minion (the golem); every other "summon" in the skill text
(Storm Cloud, Hurricane, boulder) is an owned effect without HP and belongs
to the own-effects block below.

## 2. Ruling (proposed)

- **W1. Own effects are first-class.** Block N keeps its hostile-only rule.
  Friendly/self effects stop being "excluded" and get their own block (R).
- **W2. Minions are first-class.** Own and allied minions get Block S. They
  never enter Blocks D/K (enemies) or Block I (participants).
- **W3. Cross-link.** Each enemy slot gains `targeted_by_own_minion`, so the
  target head can see what the golem is already holding.
- **W4. Truncation-proof complement.** The active primary gains
  `primary_effect_active`; each secondary slot gains `effect_active`. These
  per-slot booleans do not depend on K-nearest truncation.
- **W5. Masks stay legality-only.** Raise Golem is legal when mana and
  cooldown allow. A failed placement (fizzle) is an outcome the policy
  learns, never a mask input.
- **W6. Reward is frozen.** The formula in `policy_training.lua` is
  unchanged. "Own source" damage and kill XP already include golem contact,
  own areas, and reflected damage on the web because the simulation
  attributes every enemy damage request through `sourcePlayerId` (§8).
- **W7. Hostile hazards are re-sourced** from the closed web registry: exact
  velocity and time-to-contact, no `type_known`, a kind one-hot, and the
  damage/status payload (§6).
- **W8. No native seam, no Lua.** Every field below is a read of immutable
  simulation state; the observation builder is TypeScript inside the
  headless environment. The v3 seam list (`ml-bot-policy-v3-implementation.md`
  §F) is retired, not ported.

## 3. Web simulation sources

| Source | Type / field | File |
| --- | --- | --- |
| Enemy projectiles | `BoneyardEnemyProjectile` — `kind` (arrow, demon-bomb, firebolt, guided-missile, poison-pool), `position`, `headingDeg`, `speed`, `homing`, `targetPlayerId`, `contactRadius`, `damage`, `coldSlowTicks`, `poisonDamage`, `poisonDuration`, `ageTicks`, `lifetimeTicks`, `hitPlayerIds`, `nativeTypeId` | `core-server/boneyard-enemy-store.ts:384-420`; snapshot `BoneyardWorldSnapshot.enemyProjectiles` (`protocol/game-state.ts`) |
| Enemy beams | `BoneyardMageLightningPulseSnapshot` — `source`, `midpoint`, `endpoint`, `contact`, `ownerActorId` | `protocol/game-state.ts`; `BoneyardWorldSnapshot.mageLightningPulses` |
| Enemy projectile presentation | `BoneyardEnemyProjectileEffect` (tumble, trails, auras, fades) | `core-server/boneyard-enemy-store.ts:422-455` — **never an observation** |
| Own primary projectiles | `PrimarySpellSimulationState.projectiles[]` — `ownerId`, `kind` (earth, ether, fire, weld), `phase` (flight, held), `position`, `velocity`, `direction`, `charge`, `damage`, `ageTicks`, `flightTicks`; ether adds `targetId`, `piercesRemaining`, `speed`; fire adds `explodeRadius`; earth adds `remainingDamage`, `toughness` | `core-kernels/primary-spells.ts:143-232, 510-513` |
| Own primary channels and areas | `PrimarySpellSimulationState.transients[]` — `ownerId`, `kind` (air, water, weld-channel, air-hurricane, air-storm, fire-patch, weld-persistent, ether-blast, ...), `origin`/`position`, `direction`, `targetId`, damage bounds | `core-kernels/primary-spells.ts:232-330`; contact resolution in `core-server/boneyard-spell-combat.ts` |
| Own secondary effects | `NativeSecondarySimulationState.actors[]` — `NativeSecondaryActorState`: `ownerId`, `kind` (one of 60 `NATIVE_SECONDARY_ACTOR_KINDS`), `skillId`, `position`, `velocity`, `radius`, `endpoint`, `midpoint`, `damage`, `freezeTicks`, `slowFactor`, `ageTicks`, `lifetimeTicks`, `targetId`, `hitTargetIds`, `rank`, `enhanced` | `core-kernels/native-secondary-abilities.ts:75-153, 263-272` |
| Own and allied golems | Secondary actor with `kind: 'golem'` and `golem: NativeSecondaryGolemState` — `currentHealth`, `maximumHealth`, `iron`, `phase` (active, assembly, attack, provoke), `reflectFactor`, `damageMaximum`; actor `position`, `rotationRadians`, `targetId`, `ageTicks`, `ownerId` | `core-kernels/native-secondary-golem.ts:30-75`; `deriveGolemAllyHudRows` already lists them for the ally HUD |
| Per-player secondary state | `NativeSecondaryPlayerState` — `heldSlot`, `planeOrbHeld`, `magicShieldAbsorb`, `stoneskinTicksRemaining`, `cooldownTicksBySkill`, `globalCooldownTicks` | `core-kernels/native-secondary-abilities.ts:189-211` (self-state; see §12) |
| Golem cap and placement | `maximumGolem` feature, `golemPlacement`, `golemMovement` | `core-server/game-simulation.ts:1847-1880, 1991` |

Everything is owner-keyed by `PlayerId` (string). "Own" means
`ownerId === self`; "allied" means any other participant in the run.

## 4. Block R — own active effects

Six slots sorted by edge distance ascending (ties by effect id), then three
aggregates: `6 x 23 + 3 = 141` values. Names repeat with the prefix
`own_effect_<slot>_`:

```text
present
source_primary
source_slot_1
source_slot_2
source_slot_3
source_slot_4
source_slot_5
source_slot_6
source_slot_7
source_slot_8
family_projectile
family_area
family_channel
dx
dy
distance_scaled
velocity_dx
velocity_dy
radius_scaled
remaining_time_scaled
damage_scaled
held
has_target
```

followed by `own_effect_count_scaled`, `own_projectile_count_scaled`, and
`own_area_count_scaled`.

Semantics:

- `source_*` is a one-hot over the casting slot (primary, or belt slots 1-8
  matching Block C order), so the policy can tie a live effect to the slot
  that produced it without learning a skill-id table. It is loadout-agnostic
  by construction, like Block C.
- `family_*`: projectile = moves under its own velocity and resolves on
  contact; area = a region applying damage/status over its lifetime;
  channel = originates at the caster and extends along `direction` while
  held. Exactly one is set when `present`.
- `dx/dy` is the unit vector to the effect center; channels use the
  midpoint of the emitted segment. `distance_scaled` is edge distance
  (`max(center distance - radius, 0) / range_scale`).
- `velocity_*` is the simulation velocity divided by `velocity_scale`; areas
  report zero.
- `remaining_time_scaled` is `(lifetimeTicks - ageTicks) / 100 s` divided by
  `effect_lifetime_scale_seconds`, clamped to 1. Effects without a lifetime
  (golem excluded here; held boulders) report 1.
- `damage_scaled` is the effect's per-contact damage over
  `skill_damage_scale`; for primaries the projectile `damage`, for
  secondaries `NativeSecondaryActorState.damage`.
- `held` is set for a primary in `phase === 'held'` (a charging boulder sits
  at the caster with distance 0; release timing is an action, so the policy
  needs to see it).
- `has_target` is set when `targetId` is non-null (homing ether, captured
  air target).

### 4.1 Partition rule

A kind is in Block R iff the simulation step applies damage, freeze, slow,
burn, knockback, or target capture to enemies through that actor or
transient (`addDamage`, `electricBurnRequests`, freeze/slow assignments in
`native-secondary-abilities.ts`; contact resolution in
`boneyard-spell-combat.ts`). Presentation-only kinds — fades, particles,
debris, shimmer, flashes, trails, motes, dust, wobble, death — are excluded.
The golem is Block S, never Block R. The implementation freezes the list with
one evidence line per kind; a kind that cannot be classified with evidence
is **included**, not dropped (the same default as adjudication 5).

Provisional partition, to be frozen with evidence:

| Include (family) | Exclude (presentation) | Resolve with evidence |
| --- | --- | --- |
| Primaries: `projectiles[]` earth/ether/fire/weld (projectile); transients `air`, `water`, `weld-channel` (channel); `air-hurricane`, `air-storm`, `fire-patch`, `weld-persistent`, `ether-blast`, `water-hail`, `fire-explosion`, `fire-ember`, `weld-meteor`, `weld-steam` (area) | Primaries: `*-impact`, `earth-boulder-bit`, `ether-pierce-streak`, `water-aura`, `weld-meteor-marker`, `weld-*-fade`, `weld-boulder-debris` | `fire-good-imp`, `air-storm-strike`, `air-prismatic`, `weld-hail-knockback` |
| Secondaries: `ether-bolt`, `plane-orb-shot`, `comet`, `moving-fire` (projectile); `magic-circle`, `magic-trap`, `magic-trap-burst`, `storm-cloud`, `storm-strike`, `fire-patch`, `acid-rain`, `earthquake`, `ether-drain`, `freeze-wave`, `prismatic-wave`, `ice-blast`, `ring-fire-explosion`, `mindblast-burst`, `mindblast-shockwave`, `dampen-wave`, `shockwave`, `turn-undead`, `leviathan`, `leviathan-appendage` (area) | Secondaries: `leviathan-mote`, `ether-fade`, `plane-orb-particle`, `fire-burn-flame`, `ether-burn-flare`, `storm-drop`, `freeze-wave-visual`, `frost-burn-flare`, `earthquake-scenery-wobble`, `earthquake-dust`, `earthquake-debris`, `golem-death`, `magic-circle-player-flash`, `magic-trap-shimmer`, `flash-response-fade`, `flash-response-grow`, `shield-break`, `ring-fire-fragment`, `ether-drain-cloud`, `ether-drain-debris`, `ether-drain-capture-flare`, `comet-trail`, `comet-debris` | `acid-drop`, `acid-splash`, `comet-impact`, `earthquake-quake`, `shield-explosion`, `teleport-burst`, `phase-burst`; per-target status carriers `fire-burn`, `ether-burn`, `electric-burn` (these ride on the enemy and belong to Block K statuses, not Block R) |

Evidence already pinned for the include column: `addDamage` sites under
`case 'ether-bolt'` (1628), `'fire-patch'` (1765), `'storm-cloud'` (2140),
`'golem'` (2534), `'acid-rain'` (2850), `'ether-drain'` (3055), `'comet'`
(3169) in `native-secondary-abilities.ts`; primary contact resolution for
`air`, `water`, `fire`, `ether`, `earth`, `weld`, `air-hurricane`,
`fire-patch`, `fire-ember`, `fire-explosion`, `ether-blast`, `water-hail`,
`weld-channel`, `weld-persistent`, `weld-meteor`, `weld-steam` in
`boneyard-spell-combat.ts`.

## 5. Block S — friendly minions

Four slots, own minions first (by distance), then allied minions (by
distance), then two aggregates: `4 x 15 + 2 = 62` values. Names repeat with
the prefix `minion_<slot>_`:

```text
present
owner_is_self
dx
dy
distance_scaled
hp_ratio
max_hp_scaled
iron
phase_assembly
phase_active
phase_attack
phase_provoke
has_target
reflect_factor_scaled
age_scaled
```

followed by `own_minion_count_scaled` and `ally_minion_count_scaled`.

Semantics:

- Source: secondary actors with `kind === 'golem'`, any owner in the run.
  A golem in its death presentation (`golem-death`) is not present.
- `hp_ratio = currentHealth / maximumHealth`; `max_hp_scaled` uses
  `hp_scale` so the policy can tell a rank-1 golem from a rank-10 one.
- `phase_*` is a one-hot over `NativeGolemPhase`.
- `has_target` is `targetId !== null`. The enemy slot that carries that id
  sets `targeted_by_own_minion` (W3); Block S does not repeat the vector.
- `reflect_factor_scaled = min(reflectFactor, multiplier_scale) /
  multiplier_scale` (Iron Golem `mReflect / 100`).
- `age_scaled = min(ageTicks / 100 s, minion_age_scale_seconds) /
  minion_age_scale_seconds`.
- Two slots suffice for own golems today (the summon cap is one or two with
  the `maximumGolem` feature); four slots leave room for party golems
  without perturbing Block I.

## 6. Deltas to existing blocks

- **Block B** appends `primary_effect_active` (any own primary projectile,
  channel, or area live).
- **Block C** appends `effect_active` to each of the eight secondary slots
  (any live Block R effect or Block S minion whose `skillId` resolves to
  that slot). Raise Golem's slot therefore reads "golem alive" even when
  Block S is full of party golems.
- **Block D** appends `targeted_by_own_minion` to each of the eight enemy
  slots.
- **Block N** is re-sourced from `enemyProjectiles` and
  `mageLightningPulses`. Per slot the v4 list drops
  `hazard_type_index_scaled`, `type_known`, and `source_enemy` (every web
  hazard is enemy-sourced) and becomes 24 values:

```text
present
kind_arrow
kind_demon_bomb
kind_firebolt
kind_guided_missile
kind_poison_pool
kind_mage_lightning
dx
dy
distance_scaled
velocity_dx
velocity_dy
radius_scaled
time_to_contact_scaled
remaining_time_scaled
kind_projectile
kind_area
kind_beam
homing
targeting_self
damage_scaled
applies_cold
applies_poison
already_hit_me
```

  `velocity` is `speed` along `headingDeg` (exact, no history);
  `time_to_contact` is the analytic circle intercept already used in
  `policy_hazards.lua`, now against exact inputs; `remaining_time` is
  `(lifetimeTicks - ageTicks) / 100 s`; `targeting_self` is
  `targetPlayerId === self`; `applies_cold` is `coldSlowTicks > 0`;
  `applies_poison` is `poisonDamage > 0`; `already_hit_me` is
  `hitPlayerIds.includes(self)`. Families: arrow, demon-bomb, firebolt, and
  guided-missile are projectiles; poison-pool is an area; a mage lightning
  pulse is a beam whose `dx/dy` points at the closest point of its
  source-endpoint segment. The registry is closed by the TypeScript union,
  so there is no unknown class; adding a kind to the union without adding
  it here must fail the contract test.

## 7. Scales

Reused from `policy_spec.lua` without change: `range_scale 1000`,
`velocity_scale 1000`, `radius_scale 100`, `hp_scale 1000`,
`skill_damage_scale 500`, `multiplier_scale 4`, hazard contact 10 s,
`hazard_lifetime_scale_seconds 60`. Added:

```text
effect_lifetime_scale_seconds = 60
minion_age_scale_seconds = 60
own_effect_count_scale = 16
minion_count_scale = 4
```

Counts are `min(count, scale) / scale`, the Block I convention. None of
these is a fitted statistic.

## 8. Reward attribution

The reward is unchanged: `1.25 * self_hp_ratio_delta + 0.65 *
own_source_enemy_hp_ratio_damage + max(0, own_kill_xp_delta) / 25 + 1.5 *
min(max(wave_delta, 0), 1) - 2.0 on terminal death`, clamped to ±4, no
survival tick.

On the web, "own source" needs no new plumbing. Golem contact damage is
applied with the golem as the source actor (`addDamage(actor, target,
stepped.contact.damage, 'physical')`, `native-secondary-abilities.ts:2534`),
hit rows carry `ownerId: sourceActor.ownerId` (`:2482`), and every enemy
damage request reaches the store as `damageBoneyardEnemy(..., {
sourcePlayerId })` (`game-simulation.ts:2351-2356, 2807-2812`;
`boneyard-spell-combat.ts:286`), including reflected damage
(`reflection.playerId`). So golem kills, area kills, and Iron Golem/Stoneskin
reflections all credit the owner. The golem-kill-credit fixture in §9 proves
it rather than assuming it.

## 9. Diagnostics and fixtures

Two-surface order applies: these integration fixtures run before any
training claim, and each ships with its mutation (the block zeroed or the
flag inverted must fail the fixture).

| Fixture | Setup | Pass |
| --- | --- | --- |
| own-projectile-visible | cast Fireball east | Block R slot 1 present on the next decision, `family_projectile`, `source_primary`, `velocity_dx > 0`, `held = 0` |
| own-held-visible | hold an earth boulder | slot 1 present at distance 0 with `held = 1`; clears on release |
| own-area-visible | cast Magic Circle | slot present with `family_area`, `source_slot_n` matching the belt slot, `remaining_time_scaled` strictly decreasing per tick, absent on the expiry tick |
| effect-active-flags | same casts | Block C `effect_active` mirrors presence independent of Block R truncation (fill Block R with six embers first) |
| own-golem-visible | cast Raise Golem | Block S slot 1 `present`, `owner_is_self`, `phase_assembly` then `phase_active`; `hp_ratio` drops when an enemy hits it; absent once `golem-death` spawns |
| ally-golem-visible | second participant casts Raise Golem | slot present with `owner_is_self = 0`, sorted after own golems |
| minion-target-link | golem engages enemy k | Block S `has_target = 1` and exactly the Block D slot carrying enemy k has `targeted_by_own_minion = 1` |
| hazard-ttc-exact | archer arrow aimed at a stationary bot | `time_to_contact_scaled` equals the tick the store reports contact, within one tick |
| already-hit-me | bouncing demon-bomb hits the bot | `already_hit_me` flips to 1 and the row persists until the projectile dies |
| golem-kill-credit | golem alone kills an enemy | owner's `own_source_enemy_hp_ratio_damage > 0` and `own_kill_xp_delta > 0`; allies read 0 |

Behavior probes to add to the §3.9 scorecard of `ml-bot-diagnostics.md`:

| Probe | Setup | Pass |
| --- | --- | --- |
| golem-anchor | Raise Golem build, mixed melee wave | golem alive ≥ 60% of the episode; bot within 300 u of it ≥ 50% of combat ticks |
| recast-timing | golem alive at 80% HP, full mana | no Raise Golem recast within 10 s |
| circle-kite | Magic Circle build, melee pack | ≥ 1 enemy crosses the bot's own circle per 20 s of combat |
| trap-stack | live Magic Trap underfoot | no second trap within its radius while it lives |

Observation audit (§3.4): Blocks R and S must be non-constant on every
composition that includes Raise Golem or an area skill, so the composition
rotation must include both in every training run set. A constant Block S on
a golem composition is a seam bug, not a learning failure.

Bootstrap: the deterministic expert gains two rules so BC has signal in the
new blocks — cast Raise Golem when no own golem is present and mana covers
the cost; prefer the movement direction that keeps the bot within 300 u of
a live own golem while a target is engaged.

## 10. Versioning and layout

Hard cut, no shim: observation, model, main trajectory, and choice
trajectory are all version 5; loaders reject 1-4; the seed is a fresh
bootstrap. Block order preserves v4 relative order, extends B, C, D, and N in
place (new suffixes appended at the end of each slot), and appends R and S
after Q.

| Block | Shape | Count |
| --- | ---: | ---: |
| A. Self | fixed | 15 |
| B. Active primary (+1) | fixed | 12 |
| C. Secondary slots (+1 each) | 8 x 14 | 112 |
| D. Enemy slots (+1 each) | 8 x 11 | 88 |
| E. Selected target | fixed | 10 |
| F. Exact patch/rays | 8 + 48 | 56 |
| G. Replicated pickups + item identity | 4 x 21 + 1 | 85 |
| I. Allies | 4 x 10 + 1 | 41 |
| H. Aggregates/history | fixed | 45 |
| J. Self potion timers | 3 | 3 |
| K. Enemy identity/combat/status | 8 x 27 | 216 |
| L. Persisted-target motion/facing | 4 | 4 |
| M. Exact nearest obstacles | 8 x 14 | 112 |
| N. Hostile hazards (web registry) | 12 x 24 + 1 | 289 |
| O. Potion descriptors | 12 x 19 + 2 | 230 |
| P. Equipped items | 7 x 15 | 105 |
| Q. Inventory summary | 11 | 11 |
| R. Own active effects | 6 x 23 + 3 | 141 |
| S. Friendly minions | 4 x 15 + 2 | 62 |
| **Total** |  | **1,637** |

Exact positions are derived from this table by one TypeScript spec module
that also emits the ordered-name JSON the trainer validates. The Lua/Python
duplicated spec is retired with the native runtime. Heads, the choice head,
trunk sizes, PPO and SMDP settings are unchanged by this amendment; the
owner's capacity decision (trunk 512/256) stands until a measured reason to
revisit it.

## 11. Dropped native work

Retired, not ported: native seams 1-5 (`ml-bot-policy-v3-implementation.md`
§F), the Lua observation builder and `sd.nav` masks, the 512-KiB hot-reload
chunking, `policy_spec.lua`/`spec.py` duplication, the disposable native
session trainer (the ~5-8 env steps/s ceiling), and every slot-0 hardwire.
Kept: the doctrine (egocentric fixed-scale observations, masks = legality,
no fallbacks, strict versioning), the four masked heads plus the SMDP choice
head, the reward, the diagnostics playbook, frozen eval seed sets, and the
promotion rule.

## 12. Owner decisions

1. Block sizes: six own-effect slots and four minion slots as proposed, or
   other values with rationale.
2. Allied minions share Block S with `owner_is_self` (recommended) versus a
   separate block.
3. Self-state gap, out of this amendment's scope but adjacent: `heldSlot`,
   `planeOrbHeld`, `magicShieldAbsorb`, `stoneskinTicksRemaining` from
   `NativeSecondaryPlayerState` are not in Block A. Recommended as a small
   v5 delta to Block A so shields and toggles are visible.
4. Expert rules in §9 for the bootstrap, or a narrower variant.
