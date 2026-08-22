# ML Bot Policy — Web Port amendment (schema v5)

Status: proposal, 2026-08-22. Owner direction the same day: the learned bot
runs in the Web Port, and all native-game bot planning is dropped. This
document amends the v3 charter (`ml-bot-policy-v3.md`) for the Web Port
runtime and answers one question precisely: does the policy see projectiles
— its own and the enemy's — and the minions it summons? A same-day follow-up adds a second: does it
see which phase of an attack each enemy is in (W9, §6.1)? Same-day owner
decisions then fix how the bot joins a session (W10, §2.1) and re-source
every remaining v4 block for the web (§6.2-6.3).

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

- **W10. The bot is a server-hosted client.** Owner decision 2026-08-22.
  The policy runs in the host process, but the bot joins, plays, and
  leaves through the same path as a remote player: its own `PlayerId`,
  `client-hello` admission, `addPlayerCharacter`, a `HostClient` row with
  `activeInput`/`queuedInputs`, per-tick `client-input` semantics, and the
  ordinary per-player snapshot. Nothing in the protocol or the snapshot
  names a bot; other clients see it as any other player (§2.1).

### 2.1 W10 — the server-hosted client path

The host has exactly one way to become a player, and the bot uses it
unchanged (`host/game-host.ts`):

| Step | Human client | Bot (same function, in-process) |
| --- | --- | --- |
| Admission | `client-hello` carries a credential; shared mode accepts the shared credential, ticket mode calls `authentication.claim` and requires a valid `leaderboardUserId` (`:2725-2741`; tickets minted by `POST /admin/hub/tickets`, `game-session-supervisor.ts:281`, claimed at `:118-124`) | the supervisor mints a bot ticket (or hands over the shared credential) and the host's bot controller submits the same `ClientHelloMessage` (`protocol/game-protocol.ts:420`) with a `PlayerCharacterConfig` and a social profile |
| Join | `:585-717`: `playerId` allocated (`player-<n>`, random in shared worlds), `addPlayerCharacter(state, playerId, character)` (`:593`), `HostClient` row (`:224`) with `activeInput = createIdlePlayerCharacterInput()` (`:651`), `server-welcome` (`:683`) | identical; the `HostClient` row has no socket (its send is a sink) and carries `controller: 'bot'`, the only bot-specific state on the host (Block I `is_human` reads it) |
| Input | `client-input` (`:798-843`): dedupe by `sequence`, idle while paused / `levelUpBarrier` / `pendingOffer`, reject `targetTick > tick + 2 × GAME_TICK_RATE`, queue by `targetTick`; `applyQueuedInput` (`:2767-2782`) promotes the newest eligible queued input to `activeInput`; the tick loop writes `inputs[playerId] = activeInput` (`:1431-1457`, `:1548-1553`) | the bot controller enqueues a `ClientInputMessage` (`:432`) with `targetTick = nextTick` and a monotonic `sequence` through the same handler; the simulation never sees a bot-specific input path |
| Hub actions | `client-hub-action` (`:967-1001`) → `applyGameSimulationHubAction` (`game-simulation.ts:680-760`), then `activeInput` reset to idle and the queue cleared (`:996-997`) | same handler (potion drinking, §6.3); the idle reset costs the bot that tick's movement and cast, which the `hub-action-idle-tick` fixture asserts |
| Skill offers | `client-select-skill` (`:439`), `client-level-up-action` (`:462`) | a scripted chooser (the v3 deterministic skill chooser) answers `pendingOffer` through the same message; the policy does not choose skills |
| Match lifecycle | `client-start-match` (`:1251-1288`) and `client-confirm-loadout` (`:1289`) are authority-only | the bot never sends them; the authority starts matches, and the host confirms the bot's loadout and binds its quickbar (`client-skill-quickbar-bind`, `:446`) at admission |
| Replication | every client receives `server-snapshot` (`:593`) through `broadcastSnapshot` / `stateForPlayer` (`:1766`, `:1802`) | the bot's player is in every other client's frame through the same per-player snapshot; no protocol field distinguishes it |
| Leave | socket close → `removePlayerCharacter` (`game-simulation.ts:442`) | controller shutdown → the same removal |

The observation is built host-side from the authoritative
`GameSimulationState` keyed by the bot's `PlayerId`; the forward pass runs
in the host process (or a worker thread) once per decision tick; the chosen
action becomes the next `ClientInputMessage`. The public snapshot protocol
is not extended: if the policy ever moves out of process, the host ships
the observation vector over a privileged channel, never through the
snapshot. Bots do not resume (`resumeToken` unused) and count as members in
the party directory like anyone else (`public-party-directory.ts:9`); a
badge for humans is a lobby decision outside this contract.
`protocolVersion` is unchanged.

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
| Session join and input path (W10) | `client-hello` handler, `HostClient` (`activeInput`, `queuedInputs`, `acknowledgedSequence`), `client-input`, `applyQueuedInput`, tick-loop input map, `client-hub-action`, `client-start-match`, `client-confirm-loadout`, authentication | `host/game-host.ts:224, 585-717, 798-843, 967-1001, 1251-1289, 1431-1457, 1548-1553, 2725-2741, 2767-2782`; tickets `host/game-session-supervisor.ts:118-124, 281` |
| Client and server messages | `ClientHelloMessage`, `ClientInputMessage`, `ClientSelectSkillMessage`, `ClientSkillQuickbarBindMessage`, `ClientSelectPrimarySkillMessage`, `ClientSelectConcentrationMessage`, `ClientLevelUpActionMessage`, `ClientHubActionMessage`, `ServerWelcomeMessage`, `ServerSnapshotMessage` | `protocol/game-protocol.ts:420, 432, 439, 446, 452, 457, 462, 468, 564, 593` |
| Player input and locomotion | `PlayerCharacterInput` (`aim`, `cast.primary`, `cast.quickbar` = belt slot index, `movement`), `createIdlePlayerCharacterInput`, `PlayerCharacterState` (`position`, `velocity`, `headingIndex`, `primaryCast`), `PLAYER_CHARACTER_RADIUS 25`, `PLAYER_CHARACTER_STEADY_SPEED 100`, `playerPrimaryCastOwnsFacing` | `core-kernels/player-character.ts:16-79, 139`; slot resolution `core-server/player-combat-input.ts:8-13` |
| Player combat and progression | `PlayerCombatComponent` (`currentHealth`, `maximumHealth`, `currentMana`, `maximumMana`, `lifeState`, `poisonTicksRemaining`, `coldSlowTicksRemaining`, `dazzleTicksRemaining`, `lastDamageTick`), `playerMovementScale`, `playerCanAcceptInput`, `playerCanCast`; `PlayerProgressionComponent` (`level`, `damageX4TicksRemaining`, `mindChugTicksRemaining`, `poisonImmunityTicksRemaining`, `pendingOffer`), `PlayerSkillOffer`, `PlayerLevelUpBarrierState`, `applyPlayerPotionEffect` | `core-kernels/player-combat.ts:19-28, 105, 312-320`; `core-kernels/player-progression.ts:114-147, 166-174, 525-564` |
| Skill book, quickbar, welds | `PlayerSkillBookComponent` (`primarySkillId`, `weldBuildId`, `skillQuickbar` 8-tuple, `effectiveRanks`), `NativeSkillQuickbarId`, `NATIVE_WELD_BUILDS` (ids 1000-1009, `primarySkillIds`), `SPELL_WELDING_SKILL_ID 52`, `MAX_PLAYER_LEVEL 75` | `core-kernels/player-progression.ts:82-112, 149-158, 233-242` |
| Secondary contracts and player secondary state | `NATIVE_SECONDARY_ABILITY_IDS` (23), `NativeSecondaryAbilityContract.rank.manaCost[]`; `NativeSecondaryPlayerState` (`cooldownTicksBySkill`, `cooldownMaximumTicksBySkill`, `globalCooldownTicks`, `heldSlot`, `planeOrbHeld`, `magicShieldAbsorb`/`magicShieldMaximum`, `stoneskinTicksRemaining`, `reservedMana`, `staffCastTicksRemaining`, `castSpinTicksRemaining`), `NATIVE_SECONDARY_GLOBAL_COOLDOWN_TICKS 150`, `nativeSecondaryAvailableMana` | `core-kernels/native-secondary-ability-contract.ts:23-39, 111`; `core-kernels/native-secondary-abilities.ts:120, 189-210, 870` |
| Primary profiles | `nativePrimarySkillProfile` (`manaCost`, damage bounds, air/water `reach`), `PRIMARY_SPELL_AIR_REACH 205`, `PRIMARY_SPELL_WATER_REACH 205`, `PlayerPrimaryCastState.underpowered` | `core-kernels/native-primary-skill-profile.ts:20-108`; `core-kernels/primary-spells.ts`; `core-kernels/player-character.ts:25` |
| Derived stats | `PlayerSkillDerivedStats` (`movementFactor`, `offensiveDamageFactor`, `offensiveManaCostFactor`, `castProgressFactor`, `secondaryRechargeFactor`, `pickupRangeScalar`, `orbPullMultiplier`) | `core-kernels/player-skill-runtime.ts:75`; `playerSkillDerivedStatsAt` `core-server/player-entity-store.ts:319` |
| Enemy bodies | `BoneyardEnemyActor` (`position`, `headingDeg`, `currentHealth`, `lifeState`, `targetPlayerId`, `config.collisionRadius`, `config.maximumHealth`), `BoneyardMaggotActor` (`position`, `headingDeg`, `currentHealth`, `maximumHealth`, `collisionRadius`, `damage`, `poisonDamage`, `movementPhase`, `nextAttackTick`, `lastAttackTick`, `targetPlayerId`, `lifeState`), `BoneyardEnemyStore.actors` / `.maggots` | `core-server/boneyard-enemy-store.ts:336-371, 457-492, 660`; `core-kernels/boneyard-enemy-config.ts:97-117` |
| Arena, collision, gates | `BoneyardBounds`, `BoneyardScene`, `BoneyardCollisionWorld` (`circles`, `segments`, `polygons`, each with `sourceId`), `createBoneyardCollisionWorld`, `withBoneyardGateCollision`, `canPlaceBoneyardBody`, `resolveBoneyardMovement`, `scenerySpellTargets` | `core-kernels/boneyard.ts:6, 83`; `core-server/boneyard-collision.ts:18-39, 103-165, 182-209, 353`; `core-server/boneyard-world.ts:126-149, 215` |
| Solomon encounter and wave director | `BoneyardSolomonEncounterState` (`phase`, `targetPlayerId`), `isSolomonPlayerLocked`; `BoneyardWaveDirectorState` (`phase` over the 8 `BONEYARD_WAVE_DIRECTOR_PHASES`, `waveOrdinal`) | `core-kernels/boneyard-encounter.ts:10, 65, 180`; `core-kernels/boneyard-wave-director.ts:27, 53` |
| Loot | `BoneyardLootActor` (`kind` gold / orb / bonus / sack, `orbKind`, `bonusKind`, `item: NativeLootItem`, `amount`, `position`); pickup radius `(bonus ? 20 : 30) × pickupFactor`; orb pull `60 × pickupFactor × orbPull` | `core-server/boneyard-loot-store.ts:64, 128, 514, 569-571` |
| Economy and inventory | `HubItemKind` (11), `EquipmentSlot` (7), `HubInventoryItem` (`kind`, `nativeTypeId`, `nativeSubtype`, `quantity`, `rarity`, `recipeIndex`, `generatedLevel`, `nativeEffects`, `modContent`), `HubEquipmentState`, `backpack`, `ownedPerkSelectors`, set predicates, stock potion subtypes, `consumeInventoryItem`, `economyHasWizardKey`; hub action dispatch and potion effect | `core-kernels/hub-economy.ts:19, 40, 66-83, 122-127, 164-170, 214-225, 264-282, 315-323, 616-634, 921`; `core-server/game-simulation.ts:680-760`; `core-server/player-entity-store.ts:521` |
| Equipment effects | `NATIVE_EQUIPMENT_FEATURE`, `NativeEquipmentModifiers`, `resolveEquippedNativeEffects`, `nativeEquipmentHasFeature` | `core-kernels/native-equipment-effects.ts:14-28, 35-66, 151, 259` |
| Run lifecycle | `GameRunLifecycleState.phase` over `GAME_RUN_PHASES` (hub, active, game-over, loadout), `eligiblePlayerIds` | `core-kernels/game-run.ts:5-23` |

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

### 6.2 Blocks A-Q — web re-source

Owner decision 2026-08-22 ("update it to be web port now"): every
remaining v4 block is re-sourced field by field. Each row is **keep** (same
meaning, web source), **change** (same name, different rule), **drop** (no
web source, or constant on the web — a constant is not an observation), or
**add** (a web-only signal). Timers count ticks at `tick_rate` (100,
`GAME_TICK_RATE`) and are converted to seconds before scaling. Self state
is read through the entity-store accessors (`getPlayerCharacter`,
`getPlayerProgression`, `getPlayerSkillBook`, `getPlayerEconomy`,
`game-simulation.ts:652-916`; `playerSkillRuntimeAt`,
`playerSkillDerivedStatsAt`, `player-entity-store.ts:243-443`) plus the
self row of `NativeSecondaryPlayerState`. "Builder memory" means state the
observation builder keeps between decisions for its own player (previous
action, previous positions, previous counts) — it runs every tick on the
host, so per-tick deltas are exact.

#### A. Self — 15 → 32

| Field | v5 rule | Source | |
| --- | --- | --- | --- |
| `self_hp_ratio` | `currentHealth / maximumHealth`, clamped to [0, 1] | `PlayerProgressionComponent` (`player-combat.ts:28`) | keep |
| `self_mana_ratio` | `currentMana / maximumMana` | progression | keep |
| `self_level_scaled` | `level / level_scale`; `level_scale` becomes `MAX_PLAYER_LEVEL` (75) | progression; `player-progression.ts` | change |
| `wave_scaled` | `waves.waveOrdinal / wave_scale` | `BoneyardWaveDirectorState` (`boneyard-wave-director.ts:53`) | keep |
| `self_move_speed_scaled` | `PLAYER_CHARACTER_STEADY_SPEED × derived.movementFactor × playerMovementScale(progression) / velocity_scale` | `player-character.ts`; `player-skill-runtime.ts:75`; `player-combat.ts:105` | keep |
| `self_moving` | `velocity.x ≠ 0 ∨ velocity.y ≠ 0` | `PlayerCharacterState.velocity` (`player-character.ts:44`) | keep |
| `self_cast_active` | `playerPrimaryCastOwnsFacing(primaryCast)` (action tick running or channel active) `∨ staffCastTicksRemaining > 0 ∨ castSpinTicksRemaining > 0` | `player-character.ts:139`; secondary self state (`native-secondary-abilities.ts:189-210`) | keep |
| `self_cast_ready` | `playerCanCast(progression) ∧ ¬self_cast_active ∧ globalCooldownTicks = 0` | `player-combat.ts:316`; secondary self state | keep |
| `self_poisoned` | `poisonTicksRemaining > 0` | progression | keep |
| `self_webbed` | — | no web source (Spider is not ported) | drop |
| `self_damage_x4` | `damageX4TicksRemaining > 0` | progression (`player-progression.ts:129`) | keep |
| `self_status_active` | — | opaque native flag mask; replaced by the explicit flags below | drop |
| `self_mana_current_scaled` | `currentMana / mana_scale` | progression | keep |
| `self_mana_max_scaled` | `maximumMana / mana_scale` | progression | keep |
| `self_hp_max_scaled` | `maximumHealth / hp_scale` | progression | keep |
| `self_cold_slowed` | `coldSlowTicksRemaining > 0` | progression | add |
| `self_dazzled` | `dazzleTicksRemaining > 0` | progression | add |
| `self_movement_scale` | `playerMovementScale(progression)` (1 when unaffected) | `player-combat.ts:105` | add |
| `self_mind_chug` | `mindChugTicksRemaining > 0` | progression (`:135`) | add |
| `self_held_slot_active` | `heldSlot ≠ null` | secondary self state | add (§12 item 3) |
| `self_plane_orb_held` | `planeOrbHeld` | secondary self state | add (§12 item 3) |
| `self_magic_shield_ratio` | `magicShieldMaximum > 0 ? magicShieldAbsorb / magicShieldMaximum : 0` | secondary self state | add (§12 item 3) |
| `self_stoneskin_remaining_scaled` | `stoneskinTicksRemaining / tick_rate / status_duration_scale_seconds` | secondary self state | add (§12 item 3) |
| `self_global_cooldown_scaled` | `globalCooldownTicks / global_cooldown_ticks` | `native-secondary-abilities.ts:120` | add |
| `self_solomon_locked` | `encounter ≠ null ∧ isSolomonPlayerLocked(encounter, self)` | `boneyard-encounter.ts:180` | add |
| `self_level_up_pending` | `pendingOffer ≠ null ∨ levelUpBarrier ≠ null` | `player-progression.ts:140, 166`; `GameSimulationState.levelUpBarrier` | add |
| `wave_phase_{dormant, opening, opening_threshold, spawning, wave_threshold, wave_lull_delay, wave_lull, interwave}` | one-hot over the closed `BONEYARD_WAVE_DIRECTOR_PHASES` (8) | `boneyard-wave-director.ts:27` | add (8) |

#### B. Active primary — 12 → 11

Source: `skillBook.primarySkillId ∈ {8, 16, 24, 32, 40, 52}` and
`skillBook.weldBuildId`; `profile = nativePrimarySkillProfile(primarySkillId,
effectiveRanks[primarySkillId], weldBuildId)`.

| Field | v5 rule | Source | |
| --- | --- | --- | --- |
| `primary_element_{fire,water,earth,air,ether}` | base id → its band (8 ether, 16 fire, 24 air, 32 water, 40 earth); 52 → both components of `NATIVE_WELD_BUILDS[weldBuildId].primarySkillIds` | `player-progression.ts:233-242` | keep |
| `primary_welded` | `primarySkillId = 52 ∧ weldBuildId ≠ null` | skill book | keep |
| `primary_build_index_scaled` | welded: `(weldBuildId − 1000) / 10`; else band identity (ether 0.0, fire 0.2, air 0.4, water 0.6, earth 0.8) — the v4 formula; the web weld ids 1000-1009 pair the same primaries as native `WELD_PAIRS` | skill book | keep |
| `primary_mana_cost_scaled` | `profile.manaCost / mana_scale` | `native-primary-skill-profile.ts:108` | keep |
| `primary_range_min_scaled` | — | constant 0 on the web (no primary has a minimum range) | drop |
| `primary_range_max_scaled` | air/water: `PRIMARY_SPELL_AIR_REACH` / `PRIMARY_SPELL_WATER_REACH` (205) `/ range_scale`; projectile families (ether, fire, earth, weld): 1.0 — the kernel bounds them by lifetime and contact, not reach | `primary-spells.ts` | change |
| `primary_affordable` | `nativeSecondaryAvailableMana(self) ≥ profile.manaCost` (`currentMana − reservedMana`); the kernel's own `underpowered` outcome is the oracle (`primary-affordable-exact`) | `native-secondary-abilities.ts:870`; `player-character.ts:25` | keep |
| `primary_effect_active` | W4, unchanged | §4 | keep |

#### C. Secondary slots — 8 × 14 → 8 × 15

Slot `i` (0-7) is `skillBook.skillQuickbar[i]`; ability action
`secondary_<i+1>` sends `cast.quickbar = i` (`player-combat-input.ts:8-13`
resolves the slot). A slot may hold a primary id (`NativeSkillQuickbarId`);
such a slot reads `is_primary_binding = 1` and `occupied = 0` — switching
the active primary is not a v5 action (§12 item 7).

| Field | v5 rule | Source | |
| --- | --- | --- | --- |
| `occupied` | `skillQuickbar[i] ∈ NATIVE_SECONDARY_ABILITY_IDS` | `native-secondary-ability-contract.ts:111` | keep |
| `element_{fire,water,earth,air,ether}` | band of the skill id (ether 8-15, fire 16-23, air 24-31, water 32-39, earth 40-47); ids 48-79 have no element | v4 bands; ids identical on the web | keep |
| `band_index_scaled` | `(id − band.first) / 8`; 0 outside the bands | same | keep |
| `mana_cost_scaled` | `NATIVE_SECONDARY_ABILITY_CONTRACTS[id].rank.manaCost` at `effectiveRanks[id]` (the contract's index convention) `/ mana_scale` | `native-secondary-ability-contract.ts:23-39` | keep |
| `range_scaled` | — | no per-skill reach table on the web yet (§12 item 8) | drop |
| `cooldown_scaled` | `cooldownMaximumTicksBySkill[id] / tick_rate / cooldown_scale` | `native-secondary-abilities.ts:189-210` | keep |
| `cooldown_remaining_scaled` | `cooldownTicksBySkill[id] / tick_rate / cooldown_scale` | same | add |
| `ready` | `cooldownTicksBySkill[id] = 0 ∧ globalCooldownTicks = 0 ∧ playerCanCast(progression)` | same; `player-combat.ts:316` | keep |
| `affordable` | `occupied ∧ nativeSecondaryAvailableMana(self) ≥ mana cost` | `:870` | keep |
| `in_range_of_target` | — | dropped with `range_scaled` | drop |
| `effect_active` | W4, unchanged | §4 | keep |
| `held` | `heldSlot = i` | secondary self state | add |
| `is_primary_binding` | `skillQuickbar[i] ∈ {8, 16, 24, 32, 40, 52}` | `player-progression.ts:82-83` | add |

#### D. Enemy slots — 8 × 11, re-sourced

Pool: `enemies.actors` with `lifeState = 'alive'` plus `enemies.maggots`
with `lifeState = 'alive'` — maggots bite, poison, and die, so they are
enemies (§12 item 6). Sorted by distance, then id.

| Field | v5 rule | Source | |
| --- | --- | --- | --- |
| `present` | slot filled | store | keep |
| `dx`, `dy` | `(position − self.position) / range_scale` | actor | keep |
| `distance_scaled` | centre distance `/ range_scale` | actor | keep |
| `hp_ratio` | `currentHealth / config.maximumHealth` (maggot: `maximumHealth`) | `boneyard-enemy-config.ts:97-117`; `boneyard-enemy-store.ts:457-492` | keep |
| `radius_scaled` | `config.collisionRadius / radius_scale` (maggot: `collisionRadius`) | same | keep |
| `velocity_dx`, `velocity_dy` | `(position − position one tick earlier) × tick_rate / velocity_scale` from the builder's per-actor previous-position map; 0 on first sighting. The store has no velocity field; the builder runs every tick, so the delta is exact | actor | keep |
| `in_primary_range` | contact distance (`distance − radius`) `≤ primary_range_max` (B) | — | keep |
| `is_current_target` | builder target memory (target head) | — | keep |
| `targeted_by_own_minion` | W3 | §5 | keep |

#### E. Selected target — 10 → 9

`target_present`, `target_dx`, `target_dy`, `target_distance_scaled`,
`target_contact_distance_scaled` (centre distance minus the enemy radius),
`target_hp_ratio`, `target_radius_scaled`, `target_in_primary_range`, and
`primary_max_range_scaled` are kept with the D and B rules;
`primary_min_range_scaled` is dropped (constant 0 on the web).

#### L. Persisted-target motion and facing — 4

`target_velocity_dx/dy` as in D; `target_facing_dx/dy` is the unit vector
of the actor's `headingDeg` in the store's own convention (the one its
movement step uses). Maggots carry `headingDeg` too.

#### F. Exact patch and rays — 56

The probe is the movement kernel's own predicate:
`canPlaceBoneyardBody(point, world.bounds,
withBoneyardGateCollision(world.collision, gateLeaves),
PLAYER_CHARACTER_RADIUS)` (`boneyard-collision.ts:182`, `:148`). Rays run
in movement-action order (east, southeast, south, southwest, west,
northwest, north, northeast), sampled at multiples of `ray_step` up to
`ray_range`; the value is the first blocked sample's distance
`/ ray_range`, 1.0 when clear. The patch is 7 × 7 at `patch_spacing`
without the centre, 1.0 where the probe passes. A closing gate leaf
changes the affected ray on the next tick. Bodies (players, enemies,
minions) are not in the probe; they are Blocks D, I, and S (§12 item 9).
The `rays-exact` fixture pins every sample to the predicate.

#### M. Exact nearest obstacles — 8 × 14 → 8 × 13

Rows are the primitives of the gate-aware collision world (`circles`,
`segments` including gate leaves, `polygons`), sorted by clearance then by
primitive index (circles, segments, polygons). Per row: `present`;
`nearest_dx`, `nearest_dy` (nearest point on the primitive minus self,
`/ range_scale`); `clearance_scaled` (distance to that point minus
`PLAYER_CHARACTER_RADIUS` minus the primitive radius, `/ range_scale`);
`normal_dx`, `normal_dy` (unit vector from the nearest point to self);
`radius_scaled` (circle radius, segment radius 0 or 10, polygon 0);
`extent_x_scaled`, `extent_y_scaled` (half-extents of the primitive's
axis-aligned bounds `/ range_scale`); `kind_circle`, `kind_segment`,
`kind_polygon`; `is_destructible` (the primitive's `sourceId` names a scene
object in `scenerySpellTargets`, `boneyard-world.ts:215`).
`is_participant` is dropped: bodies are not obstacle rows on the web
(§12 item 9).

#### G. Pickups — 4 × 21 + 1

Pool: `loot.actors` sorted by distance, then id. `type_gold` is `kind =
'gold'`; `type_health_orb` / `type_mana_orb` are `kind = 'orb'` with
`orbKind`; `type_item_carrier` is `kind = 'sack'` (carries `item`);
`type_powerup` is `kind = 'bonus'`. `item_identity_known` is `1` for every
sack (the `HubItemKind` union is closed). `item_stock_{health, mana,
wizard_chug, antidote, mind_chug, rejuvenation}` map `item.kind` =
health-potion / mana-potion / wizard-chug / antidote / mind-chug /
rejuvenation-potion; `item_custom` = mod-potion; `item_is_equipment` =
equipment; `item_is_wizard_key` = key; dye and sack kinds read
`item_identity_known = 1` with every type flag 0 (mapping rows exist; the
`item-kind-closed` fixture). `item_stack_count_scaled` is the v4
log-saturated `count_scaled(item.quantity)` and `item_amount_scaled` is
`count_scaled(actor.amount)`; `pickup_count_scaled = min(count,
pickup_count_scale) / pickup_count_scale`. Pickup reach is not a field but
pins the expert and fixtures: `(bonus ? 20 : 30) × pickupFactor`, orbs
pulled within `60 × pickupFactor × orbPull` (`boneyard-loot-store.ts:514,
569-571`) — the same multipliers as v4's `PICKUP_RANGE_MULTIPLIERS`.

#### H. Aggregates and history — 45 → 43

| Field | v5 rule | |
| --- | --- | --- |
| `enemy_count_scaled` | alive pool size (D) `/ enemy_count_scale` | keep |
| `threat_count_scaled` | pool members within `threat_radius_world` `/ threat_count_scale` | keep |
| `nearest_enemy_dx/dy/distance_scaled` | nearest pool member | keep |
| `nearest_threat_dx/dy/distance_scaled` | nearest within `threat_radius_world`; 0 when none | keep |
| `escape_dx/dy` | `−unit(nearest threat offset)`; 0 when none | keep |
| `suggested_move_dx/dy` | native nav-frame steering hint; no web source | drop |
| `arena_center_dx/dy/distance_scaled` | bounds centre `(x + w/2, y + h/2)` minus self, `/ range_scale` (`BoneyardBounds`, `boneyard.ts:6`) | keep |
| `arena_x_normalized`, `arena_y_normalized` | `(self − bounds.x) / bounds.w`, `(self − bounds.y) / bounds.h` | keep |
| `edge_pressure` | `1 − min(d_edge, edge_pressure_range) / edge_pressure_range`, `d_edge` = distance to the nearest bounds edge | change |
| `element_{fire,water,earth,air,ether}`, `discipline_{mind,body,arcane}` | one-hot of `PlayerCharacterConfig.element` / `.discipline` (`WIZARD_ELEMENTS`, `WIZARD_DISCIPLINES`) | keep |
| `hp_delta`, `mana_delta`, `target_hp_delta`, `enemy_count_delta` | versus the previous decision (builder memory) | keep |
| `previous_move_dx/dy`, `previous_cast_primary`, `previous_cast_secondary`, `previous_target_action_scaled`, `previous_target_switched` | the builder's own last emitted action | keep |
| `time_since_damage_scaled` | `(tick − lastDamageTick) / tick_rate / history_time_scale_seconds`, 1 when `lastDamageTick = null` | keep |
| `time_since_cast_scaled`, `time_since_move_scaled` | builder memory | keep |
| `has_spell_welding_skill` | `effectiveRanks[52] > 0` | keep |
| `weld_offer_pending` | `pendingOffer ≠ null ∧ ∃ option with weldBuildId` (`player-progression.ts:114-125`) | keep |
| `offensive_damage_multiplier_scaled`, `offensive_mana_multiplier_scaled`, `cast_speed_multiplier_scaled`, `secondary_recharge_multiplier_scaled` | `derived.offensiveDamageFactor`, `.offensiveManaCostFactor`, `.castProgressFactor`, `.secondaryRechargeFactor`, each `/ multiplier_scale` | keep |

#### I. Allies — 4 × 10 + 1

Pool: `run.eligiblePlayerIds` minus self, present in `playerEntities`,
sorted by distance then `PlayerId`. `present`, `dx`, `dy`,
`distance_scaled`; `hp_ratio`, `mana_ratio` from that player's
progression; `alive = lifeState = 'alive'`; `is_human` reads the host's
`HostClient.controller = 'human'` — the contract's only non-simulation
read (W10, §12 item 10); `intent_dx/dy` is that client's
`activeInput.movement` on the host, the exact input the simulation applies
this tick; `ally_count_scaled = min(count, ally_count_scale) /
ally_count_scale`.

#### J. Self potion timers — 3

`self_damage_x4_remaining_scaled`, `self_poison_immunity_remaining_scaled`,
`self_all_concentration_remaining_scaled` are `damageX4TicksRemaining`,
`poisonImmunityTicksRemaining`, `mindChugTicksRemaining` (Mind Chug is the
all-concentration potion, subtype 4), each `/ tick_rate /
status_duration_scale_seconds`.

#### O. Potion descriptors — 12 × 19 + 2

Rows are `economy.backpack` items with `nativeTypeId = 7001` (the six stock
kinds and `mod-potion`), sorted by `quantity` descending, then kind, then
`id`, twelve rows (`potion_slot_count`). Per row: `present`;
`count_scaled(quantity)`; `stock_{health, mana, wizard_chug, antidote,
mind_chug, rejuvenation}` from `kind`; `custom` = mod-potion;
`restores_hp_fraction` = 1 for health-potion and rejuvenation-potion
(subtypes 0 and 5 restore fully, `applyPlayerPotionEffect`,
`player-progression.ts:525-564`), else 0; `restores_mana_fraction` = 1 for
mana-potion and rejuvenation-potion; `damage_multiplier_scaled = 4 /
multiplier_scale` for wizard-chug (subtype 2 sets `damageX4TicksRemaining =
NATIVE_DAMAGE_X4_POTION_TICKS`), else 0; `cures_poison` = antidote;
`poison_immunity_duration_scaled` = antidote's
`NATIVE_ANTIDOTE_IMMUNITY_TICKS / tick_rate / status_duration_scale_seconds`;
`concentrates_all` = mind-chug; `effect_duration_scaled` = wizard-chug and
mind-chug `6_000 / tick_rate / 60` (= 1), antidote `1_000 / tick_rate / 60`,
mod-potion `modContent.durationMs / 1000 / 60`; `custom_effect_known = 0`
for mod potions (the effect is applied by the mod's Lua, opaque to the
simulation); `identity_hash_a/b` are the v4 rolling hashes over the
identity key — the kind for stock potions, `modId:contentId` for mod
potions. `potion_type_count_scaled` and `potion_total_count_scaled` as v4.

`potion_legal` (the mask input; replaces native `potion_can_change`):
`playerCanAcceptInput(progression) ∧ levelUpBarrier = null ∧` the
`consumeInventoryItem` preconditions (`hub-economy.ts:616-634`: type 7001,
`nativeSubtype ≠ null`, mod-potion requires `modContent`) `∧`
state-changing: subtype 0 `hp < max`; 1 `mana < max`; 2
`damageX4TicksRemaining < NATIVE_DAMAGE_X4_POTION_TICKS`; 3
`poisonTicksRemaining > 0 ∨ poisonImmunityTicksRemaining <
NATIVE_ANTIDOTE_IMMUNITY_TICKS`; 4 `mindChugTicksRemaining <
NATIVE_MIND_CHUG_TICKS`; 5 `hp < max ∨ mana < max`; mod-potion: accepted by
the simulation's own consume path. Native V3-2's permanent rejection of
subtypes 2/3/4 is lifted: the web has a participant-scoped route
(`applyPlayerEntityPotionEffect`, `player-entity-store.ts:521`) and no
world-kind guard (`game-simulation.ts:750`), so potions are drinkable in the
Boneyard.

#### P. Equipped items — 7 × 15

Slots hat, robe, weapon, ring_1-3, amulet read `equipment.hat`, `.robe`,
`.weapon`, `.rings[0..2]`, `.amulet` (`HubEquipmentState`,
`hub-economy.ts:164-170`). Per slot: `present`; `catalog_known =
recipeIndex ≠ null`; `identity_hash_a/b` over `nativeTypeId:recipeIndex`
(`nativeTypeId:name` when `recipeIndex` is null); `rarity_scaled` = Epic 2,
Rare 1, null 0, `/ equipment_rarity_scale`; `level_scaled = (generatedLevel
?? 0) / level_scale`; `set_complete` = the item's set predicate
(`hub-economy.ts:264-282`) evaluated on the wearer's equipment;
`offense_effect_scaled`, `resource_effect_scaled`,
`mobility_effect_scaled`, `defense_effect_scaled` fold the item's
`nativeEffects` alone through `resolveEquippedNativeEffects`
(`native-equipment-effects.ts:151`) and sum each family's deviation from
identity (multipliers minus 1, offsets and flats as-is), `/
equipment_effect_scale`, clamped to ±1. The families partition
`NativeEquipmentModifiers` (`:35-66`) and are closed: offense =
`globalDamageFlat`, `globalDamageMultiplier`, `classDamageFlat`,
`classDamageMultiplier`, `skillDamageFlat`, `skillDamageMultiplier`,
`meleeDamageFlat`, `meleeDamageMultiplier`, `weldEffect`; resource =
`maximumMana`, `manaRecovery`, `healthRecovery`, `globalManaCostFlat`,
`globalManaCostMultiplier`, `classManaCostFlat`,
`classManaCostMultiplier`, `recharge`, `classRecharge`; mobility =
`walkSpeed`, `castSpeedFlat`, `castSpeedMultiplier`, `classCastSpeedFlat`,
`classCastSpeedMultiplier`, `orbPullMultiplier`, `goldMultiplier`; defense
= `maximumHealth`, `damageResistance`, `magicResistance`,
`poisonResistance`; `featureBits` is `special_feature_present`
(`nativeEquipmentHasFeature`, `:259`). A modifier field without a family
row fails the contract test (`equipment-family-closed`).
`targeted_effect_present` = any effect with `target ≠ 0`;
`target_kind_scaled` = that effect's `target / equipment_target_kind_scale`;
`target_magnitude_scaled` = its `magnitude / equipment_effect_scale`.

#### Q. Inventory summary — 11 → 9

From `economy.backpack`, all log-saturated with `count_scaled`:
`inventory_item_total_count_scaled` (sum of `quantity`),
`inventory_potion_count_scaled` (type 7001 kinds),
`inventory_equipment_count_scaled` (kind equipment),
`inventory_sack_count_scaled` (kind sack), `inventory_misc_count_scaled`
(kind dye), `inventory_perk_count_scaled` (`ownedPerkSelectors.length`,
`hub-economy.ts:225`), `inventory_registered_custom_count_scaled`
(mod-potion rows with `modContent`), `inventory_wizard_key_count_scaled`
(kind key), and `inventory_has_wizard_key = economyHasWizardKey(economy)`
(`:921`). Dropped: `inventory_map_count_scaled` (no map items in the web
hub) and `inventory_unknown_count_scaled` (closed union, always 0).

#### K addendum — maggots

`species_maggot` is appended after `species_coffin` (43 → 44 per slot, 8 ×
44 = 352). The phase row for `BoneyardMaggotActor` is proposed here and
pinned by the `maggot-enemy` fixture against the store's maggot attack
step: `movementPhase = 'emerging'` → approach (in flight from the coffin,
clocks saturate); `'crawl'` → approach while no bite is scheduled, cooldown
from a bite (`lastAttackTick`) until `nextAttackTick`; `time_to_strike =
nextAttackTick − tick` when a target is in reach; `targeting_self =
targetPlayerId = self`; `contact_targeting_self = 0`; `max_hp_scaled` from
`maximumHealth`; `shield_ratio = 0`; `armored = 0`; statuses join on the
maggot id like any enemy.

#### Closed unions the spec module tests exhaustively

`enemyToken` (8) plus the maggot row; every brain `phase` union (§6.1);
`BONEYARD_WAVE_DIRECTOR_PHASES` (8); `BONEYARD_SOLOMON_PHASES` (7, only
the lock predicate is observed); `HubItemKind` (11); `EquipmentSlot` (7);
`NATIVE_SECONDARY_ABILITY_IDS` (23); `NativePlayerPrimarySkillId` (6);
the fields of `NativeEquipmentModifiers`; `PLAYER_LIFE_STATES` (4);
`GAME_RUN_PHASES` (4); `NATIVE_SECONDARY_ACTOR_KINDS` (60, Block R); the
five enemy projectile kinds (Block N). Adding a member without a mapping
row fails the contract test.

### 6.3 Action heads and masks on the web

The four heads and the choice head are unchanged in shape (9 movement, 9
target, 22 ability, 9 aim). Emission and legality:

- **Movement.** `none` → `movement = (0, 0)`; a direction → its unit
  vector (the input kernel applies `MOVEMENT_LANE_CAP`). A direction is
  legal when its first ray sample (`ray_step`) passes the F probe.
- **Target.** Builder-side, as v4: slot 0 keeps the current target; slot
  `k` is legal when Block D slot `k` is present.
- **Ability.** `primary` → `cast.primary = true` with `aim`; legal when
  `self_cast_ready ∧ primary_affordable ∧ (aim_is_free ∨ target in
  primary range)`. `secondary_k` → `cast.quickbar = k − 1`; legal when the
  slot reads `occupied ∧ ready ∧ affordable`. `drink_potion_j` → a
  `client-hub-action {type: 'consume', itemId}` for Block O row `j`, a host
  message rather than a tick input; legal when `potion_legal`. The host
  idles the bot's input after a hub action (`game-host.ts:996-997`), so
  the movement and cast chosen on the same decision are dropped for that
  tick — an outcome the policy learns, asserted by `hub-action-idle-tick`.
- **Aim.** `center` → the target position, or the facing direction times
  `aim_offset_world` without a target; the eight offsets are legal only
  when `aim_is_free`, `aim = target + dir × aim_offset_world`. The free-aim
  set carries over from v4 as a closed TypeScript map (ids identical):
  builds {16, 40, 1006, 1007, 1008, 1009} and secondary entries {11, 15,
  16, 27, 45, 48, 49, 50, 72, 73, 74, 76, 77}.
- **Global gate.** While `self_level_up_pending ∨ self_solomon_locked ∨
  ¬playerCanAcceptInput(progression)`, every head is null-only: the host
  idles inputs during the barrier anyway (`game-host.ts:798-843`), and the
  Solomon lock and death are simulation facts.
- **Not actions.** Skill offers (`client-select-skill`, answered by the
  scripted v3 chooser), quickbar binding (`client-skill-quickbar-bind` at
  admission), primary switching, `client-level-up-action`,
  `client-start-match`, `client-confirm-loadout` (W10).

## 7. Scales

Reused from `policy_spec.lua`: `range_scale 1000`,
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
tick_rate = 100                      (GAME_TICK_RATE)
level_scale = 75                     (MAX_PLAYER_LEVEL; v4 used 20)
threat_radius_world = 340            (native bot-brain default, main.lua:127)
edge_pressure_range = 480            (= ray_range)
global_cooldown_ticks = 150          (NATIVE_SECONDARY_GLOBAL_COOLDOWN_TICKS)
```

Counts are `min(count, scale) / scale`, the Block I convention. None of
these is a fitted statistic.

The other v4 scales are reused unchanged for Blocks A-Q: `mana_scale
2000`, `cooldown_scale 60`, `wave_scale 20`, `enemy_count_scale 16`,
`threat_count_scale 8`, `history_time_scale_seconds 5`, `ray_range 480`,
`ray_step 60`, `patch_spacing 60`, `patch_radius 3`, `pickup_count_scale
8`, `ally_count_scale 50`, `inventory_count_saturation 99`,
`aim_offset_world 60`, `equipment_rarity_scale 2`,
`equipment_target_kind_scale 8`, `equipment_effect_scale 4`,
`target_action_scale 8`, `potion_slot_count 12`. Tick timers divide by
`tick_rate` before any seconds-based scale.

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
| bot-join-replicated | a bot joins a session with one human client | the human's next `server-snapshot` frame lists the bot's player with the same fields as a second human would have; `ServerWelcomeMessage` and `protocolVersion` unchanged; mutation: admitting the bot by calling `addPlayerCharacter` directly (bypassing `client-hello`) leaves no `HostClient` row and fails |
| bot-input-path | the bot emits a movement for tick `t` | `inputs[botId]` at tick `t` equals the emitted input and was set only by `applyQueuedInput`; mutation: writing `activeInput` directly is caught by the fixture's spy on the handler |
| hub-action-idle-tick | the bot drinks a potion while moving | `activeInput` is idle for that tick (`game-host.ts:996-997`) and movement resumes on the next tick from the bot's next input |
| potion-legality-exact | one of each of the seven potion kinds in the backpack, across hp/mana/timer states | `potion_legal` ⇔ `applyGameSimulationHubAction` accepts the consume and the player state changes; native subtypes 2/3/4 are legal on the web |
| quickbar-cooldown-exact | cast belt slot `k` | `cooldown_remaining_scaled × cooldown_scale × tick_rate` equals `cooldownTicksBySkill[id]` every tick; `ready` flips exactly when it reaches 0 with `globalCooldownTicks = 0` |
| primary-affordable-exact | mana swept across the primary's cost | `primary_affordable` ⇔ the cast attempt on the same tick does not set `primaryCast.underpowered` |
| rays-exact | bot near fences, posts, and a gate | every ray sample and patch cell equals `canPlaceBoneyardBody` at that point; closing the gate changes the affected ray on the next tick |
| ally-intent-exact | a second human sends a movement input | `intent_dx/dy` equals that input on the tick the host applies it |
| wave-phase-exact | run a wave from dormant to interwave | `wave_phase_*` follows `BoneyardWaveDirectorState.phase` tick-exactly; adding a phase to the union fails the exhaustiveness test |
| solomon-lock-mask | Solomon turns to and speaks to the bot | while `isSolomonPlayerLocked` holds, every head's mask is null-only and `self_solomon_locked = 1`; inputs sent anyway do not move the player |
| level-up-mask | the bot levels up | `self_level_up_pending = 1` and masks are null-only until the scripted chooser answers through `client-select-skill`; the barrier clears and masks reopen |
| maggot-enemy | a coffin releases maggots | each alive maggot occupies a D/K slot with `species_maggot`, `hp_ratio` from `maximumHealth`, and `time_to_strike` predicts the bite tick; dying maggots are absent |
| equipment-family-closed | add a field to `NativeEquipmentModifiers` in a test build without a family row | the contract test fails |
| item-kind-closed | add a `HubItemKind` in a test build without Block G/O/Q mapping rows | the contract test fails |

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
bootstrap. Block order preserves v4 relative order: A-Q are re-sourced in place
with their v5 widths (§6.2; new suffixes appended at the end of each
slot), K and N are re-sourced in place, and R and S are appended after Q.

| Block | Shape | Count |
| --- | ---: | ---: |
| A. Self (re-sourced, +statuses, +wave phase) | fixed | 32 |
| B. Active primary (+1, −1) | fixed | 11 |
| C. Secondary slots (re-sourced, +3 −2 each) | 8 x 15 | 120 |
| D. Enemy slots (+1 each) | 8 x 11 | 88 |
| E. Selected target (−1) | fixed | 9 |
| F. Exact patch/rays | 8 + 48 | 56 |
| G. Pickups + item identity | 4 x 21 + 1 | 85 |
| I. Allies | 4 x 10 + 1 | 41 |
| H. Aggregates/history (−2) | fixed | 43 |
| J. Self potion timers | 3 | 3 |
| K. Enemy phase/clock/targeting/status (re-sourced, +maggot) | 8 x 44 | 352 |
| L. Persisted-target motion/facing | 4 | 4 |
| M. Exact nearest obstacles (−1 each) | 8 x 13 | 104 |
| N. Hostile hazards (web registry) | 12 x 24 + 1 | 289 |
| O. Potion descriptors | 12 x 19 + 2 | 230 |
| P. Equipped items | 7 x 15 | 105 |
| Q. Inventory summary (−2) | 9 | 9 |
| R. Own active effects | 6 x 23 + 3 | 141 |
| S. Friendly minions | 4 x 15 + 2 | 62 |
| **Total** |  | **1,784** |

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
3. Self-state delta — **applied** 2026-08-22 in §6.2 Block A (owner:
   "update it to be web port now"): `heldSlot`, `planeOrbHeld`, magic
   shield ratio, Stoneskin timer, plus cold-slow, dazzle, movement scale,
   Mind Chug, global cooldown, the Solomon lock, and the level-up gate.
   Revert by dropping the eleven added A fields.
4. Expert rules in §9 for the bootstrap, or a narrower variant.
5. Wave flags (`BoneyardEnemyFlag`: FLAG_PIKE, FLAG_SPLITMANY, FLAG_ROTTEN,
   FLAG_IGNITE, FLAG_IMMORTALIZE, ...) as a per-slot one-hot. Recommended
   no: the program-changing flags are already absorbed by the clock fields;
   revisit only if a flag changes whether an enemy can be killed.
6. Maggots are enemies — **applied**: they enter the D/K pool with
   `species_maggot` (K 43 → 44 per slot). Alternative: exclude them and
   return K to 43; then a biting maggot is invisible to the policy.
7. Primary switching is not an action — **applied**: a belt slot bound to
   a primary reads `is_primary_binding = 1`, `occupied = 0`. Alternative:
   `secondary_k` on such a slot sends `client-select-primary-skill`.
8. Secondary reach — `range_scaled` and `in_range_of_target` are dropped
   from Block C until a per-skill reach table (23 rows, pinned from the
   secondary kernel's constants) exists; restoring them is +2 per slot.
9. Bodies are not obstacles — **applied**: other players, enemies, and
   minions are absent from the F probe and the M rows, and M's
   `is_participant` is dropped. `rays-exact` is the arbiter: if the
   movement kernel blocks on players, add them back as circle rows and
   restore `is_participant`.
10. `is_human` reads host metadata (`HostClient.controller`), the only
    non-simulation read in the contract (W10). Alternative: drop it.
11. `level_scale` 20 → 75 (`MAX_PLAYER_LEVEL`) — **applied**.
12. Goodie chests (wizard-key objects) are not observed and "open goodie"
    is not an action; Block Q carries `inventory_has_wizard_key` only.
13. Wave-director phase one-hot in Block A — **applied** (8 fields).
    Distinct from item 5 (per-enemy wave flags, still recommended no).

## 13. Training-side carry-overs

Owner-approved 2026-08-22. These ride with the web port's first training
run and are not blocked on any observation decision:

- **PyTorch trainer.** The hand-rolled NumPy PPO/SMDP trainer is retired
  with the native runtime. Same objective (clipped PPO on the four masked
  heads plus the SMDP choice head, value head, entropy), same frozen eval
  seed sets and promotion rule; deterministic seeding; observation and
  action contracts validated from the spec module's ordered-name JSON
  before the first gradient step.
- **Return normalization.** Running standard deviation of discounted
  returns normalizes the value target and advantage scale; the reward
  formula itself stays frozen (§8). Clipping ±4 remains on the raw reward.
- **Gamma sweep past 0.99.** At a 100 Hz tick and multi-tick decisions the
  effective horizon of 0.99 is short; sweep 0.99 / 0.995 / 0.997 / 0.999
  with the SMDP discount `gamma^ticks` per decision, promote by the frozen
  eval seeds only.
- **SMDP loss watchlist.** The choice-head loss stays on the per-run
  watchlist from v3: log it per update, alarm when it dominates the policy
  loss or collapses to a constant choice, and treat either as a
  two-surface question (integration first) before touching the algorithm.
- **Throughput.** The headless environment (§14) is the training surface;
  the native 5-8 env steps/s ceiling is gone, and the worker pool sets the
  new one. Measure it before sizing the sweep.

## 14. Dispatch — `BoneyardHeadlessEnvironment` (owner fires)

One-paragraph Codex dispatch, approved 2026-08-22 ("sure whatever on this
is fine"); the owner fires it in the Website repo, and the verification
stays with Claude:

> In the Website repo, add `frontend/src/game/headless/boneyard-headless-environment.ts` mirroring `hub-headless-environment.ts` exactly in shape (`reset`, `step`, `stepPacked`, `observe`, `stateHash` via `deterministicStateHash(authoritativeHashState(sim))`, `state`, a `createBoneyardHeadlessActionBuffer(worldCount)` helper, the same uint32 seed and 1..100000 tick validators, and the same worker-pool packed API) but driving a full Boneyard run: `createGameSimulation` → `addPlayerCharacter` for the agent (and optional scripted allies) → `confirmGameSimulationLoadout` → `enterBoneyardWorld` on a seeded boneyard choice → wave start, all through the same simulation functions `host/game-host.ts` calls, with no network and no host process. Actions are four masked heads with a fixed stride (movement 9, target 9, ability 22, aim 9) translated into `PlayerCharacterInput` per tick, potion actions into the `consume` hub action, and skill offers answered by a deterministic chooser; the observation is the schema v5 vector of `docs/ml-bot-policy-web-port.md` (width 1,784, emitted by one spec module that also writes the ordered-name JSON) with the legality masks returned alongside it. Ship a contract test that asserts the width and name order, runs the closed-union exhaustiveness checks listed in that document (§6.2), and includes a mutation check (zeroing any block or flipping any mask must fail), plus a determinism test (same seed and actions → same `stateHash` across runs and across the worker pool). `npm run validate` green; no changes to the host, protocol, or snapshot; report the measured env steps/s for 1, 4, and 8 workers.
