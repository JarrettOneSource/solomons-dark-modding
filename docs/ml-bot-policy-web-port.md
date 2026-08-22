# ML Bot Policy — Web Port amendment (schema v5)

Status: proposal, 2026-08-22. Owner direction the same day: the learned bot
runs in the Web Port, and all native-game bot planning is dropped. This
document amends the v3 charter (`ml-bot-policy-v3.md`) for the Web Port
runtime and answers one question precisely: does the policy see projectiles
— its own and the enemy's — and the minions it summons? A same-day follow-up adds a second: does it
see which phase of an attack each enemy is in (W9, §6.1)?

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
| Enemy attack phase (wind-up / strike / recovery) | **3 of 19 species** | Block K reads the native animation byte through `policy_enemy_descriptors.lua:57-75`, which maps DemonSkull (1008), Dire Faculty (1010), and Imp Portal (1013) only; every regular-roster enemy reads `telegraph_known = 0` plus an opaque `anim_state / 255`. |

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
- **W9. Enemy phase and strike timing are exact.** Block K is re-sourced
  from the web enemy brains: a closed phase one-hot, time-to-strike and
  time-to-action-end from the action clock, the enemy's target links, and
  statuses joined from the secondary target-effect table. Raw animation
  poses are never observed; they are derived from the same clock (§6.1).

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
| Enemy brains and action clocks | `BoneyardEnemyActor.brain` — per-family `phase`, `actionProgress`, `markerEmitted`, `contactTargetPlayerId`, `actionTick`, `cooldownTicks`, `phaseTicksRemaining`, `impactStateTicksRemaining`, `castProgram`, `castRoll`, `actionRate`; actor `targetPlayerId`, `lifeState`, `headingDeg`, `maximumHealth`, `shieldHealth`, `shieldMaximumHealth`, `config.attackSpeed`, `config.family.armor`, `staffActionFactor` | `core-server/boneyard-enemy-store.ts:225-372`; programs `:91-120`; clock steps `:2215-2250, 2264-2300, 3368-3394`; `staffAttackSpeed` `:3498`; zombie `NATIVE_ZOMBIE_BEAT_ACTION_PROGRAM` (`core-kernels/boneyard-zombie-beat.ts`) |
| Enemy statuses | `NativeSecondaryTargetEffectState` by `targetId` — `coldSlowTicks`, `coldSlowFactor`, `frozenTicks`, `stunTicks`, `stunFactor`, `fleeTicks`, `dazzleTicks`, `disruptedTicks`, `prismaticTicks`, `electricBurn`, `frostBurnTicks`, `steamed`, `weakenFactor`, `timeScale`; burn carrier actors `fire-burn` / `ether-burn` / `electric-burn` with `targetId` | `core-kernels/native-secondary-abilities.ts:232-256, 4553-4638` |
| Enemy animation (presentation, never observed) | `BoneyardEnemySnapshot.animation` — `state`, `action`, `actionProgress`, poses, limb rotations | `protocol/game-state.ts:521-580` |

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
- **Block K** is re-sourced from the web enemy brains and the secondary
  target-effect table (§6.1).
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

### 6.1 Block K — enemy phase, action clock, targeting, statuses

v4 Block K carries `anim_state_scaled, telegraph_known, winding_up,
attack_active, recovering`, read from the native animation byte through a
per-species table that maps 3 of 19 species
(`policy_enemy_descriptors.lua:57-75`: DemonSkull 1008, Dire Faculty 1010,
Imp Portal 1013). Every regular-roster enemy reads `telegraph_known = 0`
plus an opaque `anim_state / 255`. The web enemy simulation makes the same
information exact and complete: every enemy carries a family brain with a
semantic `phase` (`boneyard-enemy-store.ts:225-328`), and every attack runs
on an action clock whose marker is the tick the hit or shot happens
(`directContactPlayerDamage` at the marker for skeletons, `:2215-2250`;
`onMarker` spawning the arrow, firebolt, or bomb for ranged families,
`:3368-3394`) and whose `strictEnd` returns the enemy to approach or
range-control. The raw animation (`BoneyardEnemySnapshot.animation`:
`state`, `action`, `actionProgress`, poses, limb rotations) is derived from
that clock and is never observed; the policy reads the clock.

Per slot, 43 values replace the 27 of v4 (prefix `enemy_<slot>_`):

```text
species_skeleton
species_archer
species_mage
species_imp
species_zombie
species_wraith
species_demon
species_coffin
facing_dx
facing_dy
phase_approach
phase_range_control
phase_orbit
phase_windup
phase_recover
phase_cooldown
phase_knockback
phase_dormant
phase_opening
phase_open
time_to_strike_scaled
time_to_action_end_scaled
phase_remaining_scaled
marker_emitted
targeting_self
contact_targeting_self
max_hp_scaled
shield_ratio
armored
status_cold_slow
status_cold_slow_remaining_scaled
status_frozen
status_frozen_remaining_scaled
status_stunned
status_stun_remaining_scaled
status_fleeing
status_flee_remaining_scaled
status_dazzled
status_disrupted
status_prismatic
status_burning
status_weaken_factor_scaled
status_time_scale
```

Phase mapping, closed — one row per brain phase, checked exhaustively by the
spec module's type test:

| Family | `brain.phase` | v5 phase |
| --- | --- | --- |
| skeleton | approach | approach |
| skeleton | attack | windup while a marker is pending, else recover (claw loops: always windup) |
| archer | range-control | range_control |
| archer | attack | windup / recover |
| mage | range-control | range_control |
| mage | cast | windup / recover |
| imp | flight | approach |
| imp | contact | windup / recover (`markerTick` 6, `strictEndTick` 11) |
| imp | cooldown | cooldown |
| zombie | approach | approach |
| zombie | swipe | windup / recover |
| zombie | knockback | knockback |
| wraith | approach | approach |
| wraith | orbit | orbit |
| wraith | drain | windup / recover (`markerTick` 4, `strictEndTick` 9) |
| wraith | cooldown | cooldown |
| demon | approach | approach |
| demon | bomb | windup / recover |
| coffin | hidden, rising, holding | dormant |
| coffin | opening | opening |
| coffin | open | open |
| any | death (`lifeState === 'dying'`) | not present |

Semantics:

- Species is a one-hot over the closed `enemyToken` union. The v4
  `species_index_scaled`/`species_known` pair and the eight role bits go
  away: roles are a deterministic function of a closed species set. A new
  token, or a new phase in any brain union, without a mapping row fails the
  contract test — the Block N rule.
- Clock math uses the rate the step uses: `rate = progressPerTick ×
  config.attackSpeed × staffActionFactor` (`staffAttackSpeed`, `:3498`),
  times `(1 + castRoll)` for the mage cast (`:2398`); the zombie swipe
  advances by `brain.actionRate` against `NATIVE_ZOMBIE_BEAT_ACTION_PROGRAM`
  (marker 100, completion 125). `time_to_strike = (next pending marker −
  actionProgress) / rate` ticks and `time_to_action_end = (strictEnd −
  actionProgress) / rate`. Imp contact and wraith drain use their tick
  clocks (`markerTick − actionTick`, `strictEndTick − actionTick`). The
  skeleton weapon swing has two markers (`NATIVE_SKELETON_WEAPON_MARKERS`
  9/20); after the first lands, `time_to_strike` points at the second. The
  skeleton claw is a looping clock that wraps at `strictEnd + 1` with
  markers at 4 and 8 (`inclusiveCircularMarkerCrossed`, `:2264-2300`), so
  the next marker is computed modulo the wrap, `phase_windup` stays set,
  and `time_to_strike` counts down to the next hit. Both times are seconds
  over `enemy_action_scale_seconds` and saturate at 1 when nothing is
  pending.
- `phase_remaining_scaled` is `cooldownTicks` (imp), `phaseTicksRemaining`
  (wraith, zombie, coffin), or `impactStateTicksRemaining` (zombie
  knockback) over `enemy_phase_scale_seconds`; 0 when the phase has no
  timer.
- `marker_emitted` is the brain's own flag: the first hit of a multi-marker
  swing has landed.
- `targeting_self` is `targetPlayerId === self` (who the enemy is chasing);
  `contact_targeting_self` is `contactTargetPlayerId === self` (who the
  current swing was locked onto when it started: skeleton, imp, zombie,
  wraith). v4 has neither.
- `max_hp_scaled = maximumHealth / hp_scale`; `shield_ratio = shieldHealth
  / shieldMaximumHealth` (0 when the maximum is 0); `armored` is
  `config.family.armor` (the armored skeleton variant, `:2305`).
- Statuses join `NativeSecondaryTargetEffectState` on `targetId`
  (`native-secondary-abilities.ts:232-256`): `status_cold_slow =
  coldSlowTicks > 0`, `status_frozen = frozenTicks > 0`, `status_stunned =
  stunTicks > 0`, `status_fleeing = fleeTicks > 0` (Turn Undead),
  `status_dazzled`, `status_disrupted`, and `status_prismatic` likewise;
  `status_burning` is `electricBurn ≠ null`, `frostBurnTicks > 0`,
  `steamed ≠ null`, or a `fire-burn`/`ether-burn`/`electric-burn` carrier
  actor (`:4553-4638`) whose `targetId` is this enemy;
  `status_weaken_factor_scaled = weakenFactor` and `status_time_scale =
  timeScale`, both 1 when unaffected. Remaining times are seconds over
  `status_duration_scale_seconds`. v4's `poisoned` and `webbed` have no web
  source (players do not poison; Spider is not ported) and are dropped.
- Dying enemies (`lifeState === 'dying'`) are absent from Blocks D, K, E,
  and L and the target-head mask drops them; the death program is
  presentation.

What this buys, at nominal rate: the skeleton claw hits every 0.32 s for
as long as the skeleton stays in attack; the pike lands at 0.16 s and
recovers until 0.96 s; the weapon swing lands at 0.36 s and 0.80 s and
recovers until 0.96 s; the archer looses at 1.54 s of a 1.90 s action; the
mage long cast fires at 1.22 s of 1.86 s (short: 0.99 s of 1.62 s); the
demon bomb leaves at 0.43 s of 0.85 s; imp contact lands at tick 6 of 11
with an 18-tick cooldown; wraith drain at tick 4 of 9 with a 50-tick
cooldown. Stepping out of reach before the marker, hitting enemies in
recovery or cooldown, and knowing which enemy is after the bot are all
learnable from these fields and were unlearnable in v4 for the regular
roster.

## 7. Scales

Reused from `policy_spec.lua` without change: `range_scale 1000`,
`velocity_scale 1000`, `radius_scale 100`, `hp_scale 1000`,
`skill_damage_scale 500`, `multiplier_scale 4`, hazard contact 10 s,
`hazard_lifetime_scale_seconds 60`, `status_duration_scale_seconds 60`.
Added:

```text
effect_lifetime_scale_seconds = 60
minion_age_scale_seconds = 60
own_effect_count_scale = 16
minion_count_scale = 4
enemy_action_scale_seconds = 2
enemy_phase_scale_seconds = 5
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
| strike-tick-exact | weapon skeleton swings at a stationary bot | `time_to_strike_scaled × enemy_action_scale_seconds × 100` predicts both `attackMarker` ticks within one tick; still exact under staff disable (`staffActionFactor < 1`) |
| claw-loop | claw skeleton held in attack | `phase_windup` stays set and `time_to_strike_scaled` saws between 0 and 0.16 with a 0.32 s period |
| ranged-strike-exact | archer attack | the predicted strike tick is the tick the arrow appears in Block N |
| phase-closed | add a token to `enemyToken` or a phase to a brain union in a test build | the spec module's exhaustiveness test fails |
| dying-excluded | kill an enemy | absent from Blocks D/K/E/L on the next decision and the target mask drops it |
| targeting-self | two participants, enemy chases the bot | bot reads `targeting_self = 1`, ally reads 0; `contact_targeting_self` flips only when the swing starts |
| status-join | freeze an enemy through the secondary kernel | `status_frozen = 1`, `status_frozen_remaining_scaled` strictly decreasing, 0 at expiry |

Behavior probes to add to the §3.9 scorecard of `ml-bot-diagnostics.md`:

| Probe | Setup | Pass |
| --- | --- | --- |
| golem-anchor | Raise Golem build, mixed melee wave | golem alive ≥ 60% of the episode; bot within 300 u of it ≥ 50% of combat ticks |
| recast-timing | golem alive at 80% HP, full mana | no Raise Golem recast within 10 s |
| circle-kite | Magic Circle build, melee pack | ≥ 1 enemy crosses the bot's own circle per 20 s of combat |
| trap-stack | live Magic Trap underfoot | no second trap within its radius while it lives |
| swing-dodge | weapon skeleton at reach, bot at full HP | leaves `BOUNDED_ENEMY_ATTACK_REACH.SKELETON` before the first marker on ≥ 70% of swings |
| recovery-punish | mixed melee wave | damage/s dealt during enemy recover or cooldown ≥ damage/s dealt during windup |

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
bootstrap. Block order preserves v4 relative order, extends B, C, and D in
place (new suffixes appended at the end of each slot), re-sources K and N
in place, and appends R and S
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
| K. Enemy phase/clock/targeting/status (re-sourced) | 8 x 43 | 344 |
| L. Persisted-target motion/facing | 4 | 4 |
| M. Exact nearest obstacles | 8 x 14 | 112 |
| N. Hostile hazards (web registry) | 12 x 24 + 1 | 289 |
| O. Potion descriptors | 12 x 19 + 2 | 230 |
| P. Equipped items | 7 x 15 | 105 |
| Q. Inventory summary | 11 | 11 |
| R. Own active effects | 6 x 23 + 3 | 141 |
| S. Friendly minions | 4 x 15 + 2 | 62 |
| **Total** |  | **1,765** |

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
5. Wave flags (`BoneyardEnemyFlag`: FLAG_PIKE, FLAG_SPLITMANY, FLAG_ROTTEN,
   FLAG_IGNITE, FLAG_IMMORTALIZE, ...) as a per-slot one-hot. Recommended
   no: the program-changing flags are already absorbed by the clock fields;
   revisit only if a flag changes whether an enemy can be killed.
