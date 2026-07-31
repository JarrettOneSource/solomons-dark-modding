# ML Bot Policy v3 implementation proposal

Status: Phase V3-1 investigation and proposal only. This document does not
implement Policy v3 behavior, native APIs, model changes, or trainer changes.

Baseline:

- branch: `codex/ml-bot-v3-20260730`
- v3 charter: `d589973` (`docs/ml-bot-policy-v3.md`)
- landed v2 baseline: `ccef342`
- v2 observation/model/trajectory version: 2
- v2 observation count: 395

The proposal preserves v2's cap-agnostic roster handling, disposable seeded
episodes, team-composition rotation, native authority, exact masks, and strict
version rejection. Values that can be derived in Lua from semantic replicated
state stay in Lua.

## A. Obstacles

### A1. Live fidelity measurement

#### Method

The v2 feature producer adopts only subdivision-4 nav snapshots, converts the
native samples into a 25-by-25-world-unit lookup lattice on the measured stock
100-by-100 cells, and answers arbitrary patch/ray points with the containing
lattice sample. It emits eight 60-unit-step rays out to 480 and a 7-by-7,
60-unit-spaced patch with the center omitted
(`mods/bot-brain/scripts/policy_geometry.lua:37-70,116-190`;
`mods/bot-brain/scripts/policy_spec.lua:254-270`).

The native truth predicate was the same player-radius placement predicate used
by production path admission. `IsGameplayPathPlacementTraversable` reads the
observer's radius/mask, checks exact static-circle overlap, excludes the
observer from participant overlap, then calls native
`movement_collision_test_circle_placement[_extended]`
(`SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_traversability.inl:14-40,113-173,175-333`;
`config/binary-layout.ini:852-853`).

The public API exposes only a segment test, not a direct placement test. The
probe converted it into an endpoint-only placement query without a raw address:

```text
sd.nav.test_segment(x - 50.51, y, x, y)
```

For the observed radius 25 and 100-unit cells, the segment sampler steps by
12.5 and skips all points at most `2 * radius + 0.5 = 50.5` from the start.
For a 50.51-unit segment, the first four points are skipped and only the
endpoint is passed to the placement predicate
(`SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_traversability.inl:336-389`;
`SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl:355-407`).

Three fresh disposable, audio-disabled headless sessions were run against this
worktree's `ccef342` staged install. The stock survival procedural selector was
forced before run entry; the tested native seeds were `0x2A0FC5AA`,
`0x11111111`, and `0x22222222`. Each comparison used the exact v2 Lua lookup
at a requested coordinate and the endpoint-only native placement result at the
same coordinate. The resulting layouts were:

| Seed | Grid | Movement circles | Static circles | Pushable circles | Shapes | Shape points | Openable segments |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `0x2A0FC5AA` | 41 x 18 | 459 | 452 | 4 | 14 | 76 | 2 |
| `0x11111111` | 29 x 30 | 388 | 381 | 4 | 17 | 80 | 4 |
| `0x22222222` | 22 x 37 | 465 | 458 | 4 | 17 | 80 | 4 |

#### Results

“False open” means v2 reported walkable while the exact native predicate
blocked. “False block” is the reverse.

| Sample population | Samples | Mismatches | Error | False open | False block |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dense in-bounds lattice-independent points | 155,008 | 9,226 | **5.952%** | 4,657 / 3.004% | 4,569 / 2.948% |
| In-bounds v2 patch points | 27,648 | 1,471 | **5.320%** | 658 / 2.380% | 813 / 2.941% |
| In-bounds v2 ray points | 36,864 | 1,646 | **4.465%** | 802 / 2.176% | 844 / 2.289% |

Across 4,608 ray-clearance values, 3,825 were exact (**83.008%**). The mean
absolute clearance error was **32.539 world units**. Defining signed error as
`v2 clearance - native clearance`, the mean was **+2.357 units**. Per-layout
95th-percentile absolute errors were 300, 240, and 240 units; the maximum was
420.

A boundary-inclusive pass on the first layout produced 12.413% patch error and
15.747% ray-point error. Those higher figures are dominated by the deliberate
v2 rule that anything beyond the grid is blocked, so they are reported
separately and are not attributed to missing static geometry.

The live raw circle radii ranged from 1 to 30. Of 1,312 raw circle rows, 1,262
(96.189%) were smaller than 17.68, the half-diagonal of a 25-unit sample
square. They are visually “small” relative to the lattice, but the observing
radius inflates every tested forbidden circle to at least 26, larger than that
half-diagonal. Therefore no complete forbidden disk disappeared between four
sample centers in these runs. Instead, quantization moved the boundary in both
directions: 8,544 of 9,226 dense mismatches (92.608%) lay on static-circle
edges. This explains both the nearly symmetric false-open/false-block rates and
the long clearance-error tail.

Conclusion: v2 does detect the stock obstacles, but 4.47-5.95% point error and
up to 420 units of ray error are materially wrong for tight kiting. This is a
v2 fidelity bug, not merely a v3 enhancement. V3 must recompute the retained
patch and rays from exact cached primitives; merely appending a K-nearest block
while leaving the old lookup unchanged is insufficient. The native
`sd.nav.test_segment` movement mask remains authoritative.

### A2. Exact primitive inventory and address-free exposure

The movement controller owns all of the relevant registries:

```text
controller +0x28/+0x34  shape count/list
controller +0x40/+0x4C  primary overlap count/list
controller +0x70/+0x7C  secondary overlap count/list
controller +0xA0/+0xAC  circle count/list
controller +0x12C/+0x138 static-circle count/list
```

Shapes expose point/cached-point pointers, bounds `(x,y,w,h)`, and a point
count. Circles expose native object type, mask, center, and radius
(`config/binary-layout.ini:1754-1788`). The existing debug enumerator proves
that those fields can be read live and shows the exact point/bounds and
circle/mask payloads, but it also exposes addresses and is therefore not a
policy API
(`SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_nav_grid_and_copy.inl:248-479`).

The production grid builder already converts part of this into safe value
objects. It copies circles with mask bit `0x4`, excludes pushable bit `0x2000`,
and captures openable Gate segment endpoints by walking scene scenery and
matching the Gate collision-builder virtual
(`SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_grid_setup.inl:3-28,40-49,83-160,252-362`;
`config/binary-layout.ini:1865-1878`). Exact native/RE classifications are:

- fixed Fenceposts: circle mask `0x4`, raw radius 10;
- Goodies: circle mask `0x2004`, so they occur in the same circle list but are
  pushable and excluded from path blocking;
- fixed FenceGrates and moving Gate leaves: segment mask `0x100`; that mask
  cannot be globally treated as openable because both classes share it;
- Gates rebuild their exact segment as they move;
- walls and other area geometry are represented by shape point arrays/bounds.

Evidence:
`docs/pathfinding-investigation.md:1001-1061`;
`docs/reverse-engineering/native-boneyards-and-world.md:414-472,514-566`.

The controller's secondary list is per-query overlap scratch, not a stable
segment registry. Fixed and moving segment enumeration must therefore walk the
owning scenery classes/records, as the existing Gate-specific producer already
does; snapshotting the secondary list would race and silently omit idle
segments (`docs/pathfinding-investigation.md:1045-1057`).

An address-free seam is practical because every output is a copied scalar or
point list. Proposed API:

```lua
sd.nav.get_collision_geometry(participant_id) -> {
  valid = true,
  scene_epoch = 0,
  run_nonce = 0,
  static_revision = 0,
  dynamic_revision = 0,
  refresh_pending = false,

  observer_radius = 25.0,
  observer_radius_resolved = true,

  circles = {
    {
      geometry_id = 1,             -- per-scene stable, never an address
      native_type_id = 3006,
      x = 0.0, y = 0.0, radius = 10.0,
      mask = 0x4,
      path_blocks = true,
      pushable = false,
      destructible = false,
      destructible_resolved = true,
      dynamic = false,
    },
  },
  segments = {
    {
      geometry_id = 2,
      native_type_id = 3007,
      start_x = 0.0, start_y = 0.0,
      end_x = 0.0, end_y = 0.0,
      mask = 0x100,
      path_blocks = true,
      openable = false,
      dynamic = false,
    },
  },
  polygons = {
    {
      geometry_id = 3,
      native_type_id = 0,
      bounds_x = 0.0, bounds_y = 0.0,
      bounds_w = 0.0, bounds_h = 0.0,
      path_blocks = true,
      dynamic = false,
      points = {{x = 0.0, y = 0.0}},
    },
  },
  participant_radii = {
    {participant_id = 1, radius = 25.0, radius_resolved = true},
  },
}
```

The producer caches immutable rows by `(scene_epoch, run_nonce,
static_revision)`, updates Gate/destructible rows under `dynamic_revision`,
and returns `refresh_pending=true` until a complete coherent snapshot exists.
Lua adopts only complete revisions, exactly as v2 does for the grid. No world,
controller, object, record, point-array, or participant actor address crosses
the boundary.

### A3. Dynamic obstacles and K-nearest features

Dynamic categories are not uniform:

- Goodies/destructibles are in the same native circle list as static
  Fenceposts, distinguished by mask `0x2000` and type/state. They are
  collision objects but the production path policy deliberately permits the
  pushable circle.
- Gate leaves are scene-owned segment records in the same geometric family as
  fixed FenceGrates, but move and rebuild their segments every tick.
- participant bodies are **not** part of the static circle vector copied by
  the path producer. The production predicate separately walks the materialized
  participant registry, explicitly excludes the observing actor/bot ID, and
  tests the other wizard radii
  (`SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_traversability.inl:113-173`).

Participant positions are already replicated, so the seam should expose only
the irreducibly native radii; Lua joins them by `participant_id`. Goodie/Gate
state belongs in the geometry seam because it is not replicated semantically.

Recommended K is **8**, matching the enemy block. Lua filters to rows with
`path_blocks=true`, adds other participant circles from replicated positions,
computes exact player-radius-inflated clearance, sorts by `(clearance,
geometry_id)`, and emits these 14 ordered values per slot:

```text
present
nearest_dx
nearest_dy
clearance_scaled
normal_dx
normal_dy
radius_scaled
extent_x_scaled
extent_y_scaled
kind_circle
kind_segment
kind_polygon
is_participant
is_destructible
```

`nearest_dx/dy` is the egocentric vector to the closest point on the raw
primitive; `clearance` additionally subtracts the observing radius. Radius is
zero for non-circles; extents are zero for circles. The same analytic
circle/segment/polygon tests replace the quantized v2 patch/ray lookup.
Nonblocking pushables/openables remain visible in the seam for diagnostics or
future policy work but do not masquerade as path blockers in this K block.

## B. Enemies

### B1. Identity

The authoritative `WorldActorSnapshot` already stores:

```text
network_actor_id, native_type_id, enemy_type, actor_slot, world_slot,
target identity, dead/tracked/lifecycle/run-static/native-minion flags,
anim_drive_state, position, radius, heading, hp, max_hp,
animation/render fields, status_flags, Lua content/config fields,
Turn Undead state, and native-minion state
```

Evidence:
`SolomonDarkModLoader/include/multiplayer_runtime_state.h:415-464`;
wire shape at
`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h:1211-1255`;
authority capture at
`SolomonDarkModLoader/src/multiplayer_local_transport/local_snapshot_packet_builders.inl:111-190`.

The public actor row already exposes `network_actor_id`, `object_type_id`
(the native type), `enemy_type`, custom `content_id`, render/animation state,
position/radius/heading, and HP
(`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:150-375`).
The v2 `steering.live_enemies` adapter discards most of that and retains only
ID, position, radius, and HP
(`mods/bot-brain/scripts/steering.lua:85-112`). Identity therefore needs no
native seam; it needs a Lua descriptor table and observation fields.

The retail census has 19 compiled enemy-system types with exact roles,
including melee Skeleton, ranged Archer, Mage, splitter Imps, poison Zombie,
orbit/fade Wraith, four bosses, Coffin/Maggot, Spider/Cocoon, and Portal
(`docs/reverse-engineering/native-enemies.md:3-60`). Proposed per-enemy
identity is:

- `species_index_scaled`: index in a pinned static native/custom enemy catalog;
- `species_known`: 1 only when that catalog row exists;
- eight semantic role bits: melee, ranged, caster, spawner, exploder, boss,
  flying, stationary.

Unknown native/custom species gets index zero, `species_known=0`, and only role
bits explicitly supplied by its registered config. It remains a normal enemy
row and cannot crash or index past an embedding table.

### B2. Combat state, facing, and statuses

Facing and two animation fields are already captured and replicated:
`heading`, `anim_drive_state`, and `anim_drive_state_word`. Native actor offsets
are heading `+0x6C`, drive byte `+0x160`, and animation selection state
`+0x21C` (`config/binary-layout.ini:1549-1574,1604`). Species-specific RE
identifies meaningful action states—for example Archer shot creation,
Skeleton Mage cast cadence, boss states `0x18..0x21`, Coffin's four states,
Spider states `0..5`, and Portal's stationary countdown
(`docs/reverse-engineering/native-enemies.md:249-273,293-358,385-477`).

There is no proven universal “wind-up/attack/recovery” bit across all 19
families. V3 should pin a Lua table keyed by `(native_type_id, anim_state)` and
emit:

```text
anim_state_scaled, telegraph_known, winding_up, attack_active, recovering
```

Unknown species/state yields `telegraph_known=0` and zero phase bits; it is not
guessed from sprite motion. Completing all species' telegraph rows is an RE
coverage decision, not a new runtime seam.

Status data is incomplete today. The wire/state contains only a two-bit
Turn-Undead validity/active flag plus duration/flee/scalar
(`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h:254-274`;
`SolomonDarkModLoader/src/multiplayer_local_transport/world_snapshot_capture.inl:457-503`),
and the Lua actor marshaller does not expose even those fields
(`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:282-375`).

The native actor has a modifier pointer list at `+0x104`, count `+0x10C`,
storage `+0x118`; every modifier exposes type `+0x08` and remaining duration
ticks `+0x14`. The existing address-taking helper already enumerates those
rows, but is only public through `sd.debug.get_actor_modifiers(actor_address)`
(`SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl:198-257`;
`SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_combat_observations.inl:363-386`;
`SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl:78-95`).

The semantic types required by the charter are proven:

- slowed: `ColdSlow 0x1B69` or `CircleSlow 0x1B70`;
- frozen: `Frozen 0x1B6F`;
- poisoned: `Poisoned 0x1B72`;
- webbed: `Mod_Webbed 0x1B79`;
- Turn Undead: existing status fields.

Evidence:
`docs/reverse-engineering/native-projectiles-and-effects.md:245-267,269-297,299-339`.

Minimal native change: capture these semantic flags/durations while the
authority still has the actor, add them to the existing actor snapshot/wire,
and marshal address-free values to Lua. The public row should carry one
`combat_status_resolved` flag plus `{active, remaining_seconds}` for each
status and the already-replicated Turn-Undead fields. No general modifier type
or pointer list is exposed.

### B3. Projectiles and hazards

`sd.world.get_replicated_spell_effects()` is an owner-keyed **player spell
presentation** feed, not a hostile hazard census. Its wrapper row is:

```text
valid, owner_participant_id, received_ms, sequence, run_nonce, scene_epoch,
effect_total_count, truncated, effects
```

Each effect contains:

```text
effect_serial, cast_sequence, native_type_id, effect_ordinal,
active, terminal, transform_valid, motion_valid,
ember_runtime_valid, firewalker_runtime_valid,
position_x, position_y, radius, heading, motion_x, motion_y,
Ember vertical/damage/lifetime/animation/config fields,
Firewalker collision/phase/lifetime/fade/direction/scale/damage/source/
active/variant/aux/damage-mask fields
```

Evidence:
runtime shape at
`SolomonDarkModLoader/include/multiplayer_runtime_snapshot_state.inl:41-93`;
wire at
`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h:1384-1433`;
Lua at
`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:1674-1795`.
The same API's `native_effects` audit lane exposes `actor_address` and must
never feed the policy
(`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:1928-1952`).

`sd.world.get_replicated_air_chains()` is narrower still. Its semantic packet
is a Lightning-chain presentation: owner/run/cast/frame sequences and target
rows `{network_actor_id, ordinal, source_x/y, target_x/y}`
(`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h:1453-1474`).
Lua also exposes local/fallback addresses and reconciliation errors in the
audit/apply structures
(`SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp:1956-2109`).
Those addresses are diagnostics, and a chain line is not a persistent damaging
hazard.

The generic world snapshot does not close the gap. Run replication explicitly
includes tracked enemies, static layout actors, and native minions, not
projectile/effect actors
(`SolomonDarkModLoader/src/multiplayer_local_transport/world_snapshot_capture.inl:59-82`).

Native state beyond the two feeds is extensive. All 46 mapped projectile,
persistent-area, summon, and transient classes share factory type `+0x08`,
position `+0x18/+0x1C`, radius `+0x30`, owner group/slot `+0x5C/+0x5E`, and
heading `+0x6C`
(`docs/reverse-engineering/native-projectiles-and-effects.md:22-50,88-144`).
Motion, remaining lifetime, homing target, and allegiance are family-specific:
MagicMissile derivatives have target identity and steering state; Arrow,
Fireball, EtherBolt, Silk, UnholySpit, and boulders have straight-motion
fields; MagicCircle, Fire, StormCloud, MagicTrap, PoisonPool, AcidRain,
TragicCircle, and EtherDrain are persistent areas
(`docs/reverse-engineering/native-projectiles-and-effects.md:197-267,345-443,489-507`).

That requires one new semantic feed:

```lua
sd.world.get_replicated_hazards() -> {
  valid = true,
  authority_participant_id = 1,
  scene_epoch = 0,
  run_nonce = 0,
  sequence = 0,
  hazard_total_count = 0,
  truncated = false,
  hazards = {
    {
      hazard_id = 1,              -- stable for its per-run lifetime
      native_type_id = 0x7DA,
      active = true,
      hostile = true,
      kind = "projectile",         -- projectile|area|beam
      source_participant_id = 0,
      source_network_actor_id = 0,
      target_participant_id = 0,
      target_network_actor_id = 0,
      x = 0.0, y = 0.0, radius = 0.0, heading = 0.0,
      motion_resolved = true,
      motion_x = 0.0, motion_y = 0.0,
      lifetime_resolved = true,
      remaining_ticks = 0,
      homing = false,
    },
  },
}
```

The authority enumerates only a pinned hazard-type registry, copies
family-specific fields into this common shape, assigns a non-address stable ID,
and publishes allegiance/source/target semantically. Lua derives velocity
history where native motion is unresolved, merges any useful address-free
player spell-effect rows, sorts K=12 by edge distance, and emits only active
hostile hazards. Air-chain presentation does not enter the persistent K block.

### B4. Aim-point offset

Current policy casts exactly at the selected actor's current `x,y`
(`mods/bot-brain/scripts/brain.lua:513-538`). Benefit varies sharply:

| Family | Native behavior | Aim-offset value |
| --- | --- | --- |
| MagicMissile/FireMissile/BallLightning/FrostMissile, GuidedMissile, SkullMissile | Native target identity and bounded steering/homing | Low; center only avoids learning noise |
| toggles, self buffs, radial caster effects, beams/cones | No meaningful free lead point | None/low; center only |
| Arrow, Fireball, EtherBolt, Silk, UnholySpit, GroundSpark, boulders | Straight or weakly corrected trajectory | High |
| Storm/Circle/Trap/Rain/Wall/Drain/Comet | Point/line/area placement | Moderate to high |

The family behavior is established by
`docs/reverse-engineering/native-projectiles-and-effects.md:197-267,345-443`
and the secondary dispatcher by
`docs/reverse-engineering/native-skills-and-spells.md:608-640`.

Recommendation: a **nine-way discrete aim head**, not an unbounded continuous
Gaussian. Actions are center plus the eight compass offsets at 60 world units,
relative to the policy-selected target. The spell descriptor masks center only
for homing/self/radial families and all nine for lead/placement families.
Discrete legality, a bounded offset, and deterministic Lua/Python parity are
worth more than the marginal precision of a continuous head. Per-enemy velocity
and facing provide the lead signal. No native seam is needed because the cast
API already accepts an arbitrary finite target coordinate.

## C. Learned skill choices

### C1. Event-driven head and invocation flow

The native picker normally rolls three options and four with Creativity 63.
The bot path calls the same progression virtual `+0x74`; its temporary native
array is bounded to 16 entries
(`docs/skill-picker-re.md:46-95`;
`SolomonDarkModLoader/src/bot_runtime/helpers/skill_choices.inl:1-22,93-220`).

The existing public APIs are sufficient:

```lua
sd.bots.get_skill_choices(participant_id) -> {
  pending, generation, level, experience,
  options = {{id, apply_count}},
}

sd.bots.choose_skill(participant_id, generation, option_index)
```

The roll captures option 52's pending weld build at generation creation, and
apply validates generation/option membership and promotes the captured build
only after applying that choice
(`SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl:84-155`;
`SolomonDarkModLoader/src/bot_runtime/public_api/bot_skill_choice_api.inl:1-160`;
Lua bindings at
`SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp:248-332`).
No native skill-choice seam is needed.

Invocation flow:

1. The bot manager observes a new pending `generation`.
2. It freezes the full v3 observation, option rows, and option mask once for
   that generation.
3. The choice network scores every offered option with shared weights and
   samples one masked categorical action.
4. Lua calls `choose_skill(participant_id, generation, option_index)`.
5. The event remains open until the pending generation clears and progression/
   loadout revisions advance; duplicate manager ticks cannot resample it.
6. The chosen event is appended to the choice-event trajectory. The normal
   10-Hz policy never gains a “choose skill” action.

### C2. Option descriptor encoding

`native-skill-catalog.json` covers 82 IDs (80 CFG-backed and two runtime-only)
and 43 parsed property kinds
(`docs/reverse-engineering/native-skill-catalog.json:1-63`). Spell Welding 52
has a normal catalog row but no numeric mechanics
(`docs/reverse-engineering/native-skill-catalog.json:2778-2799`); Health Up 64
illustrates a ranked utility property
(`docs/reverse-engineering/native-skill-catalog.json:3261-3298`). Permanent
and effective ranks are distinct row fields and are already replicated through
progression book rows
(`docs/reverse-engineering/native-skills-and-spells.md:120-160`).

Each option gets **56 ordered descriptor values**:

```text
present
option_id_index_scaled
catalog_known
apply_count_scaled
learned_rank_scaled
effective_rank_scaled
cap_rank_scaled
max_rank_scaled
band_index_scaled

family_element
family_discipline
family_ether
family_fire
family_air
family_water
family_earth
family_arcane
family_mind
family_body
family_advanced
family_runtime_only

is_primary
is_secondary
is_passive
is_utility
is_weld
is_health_up
is_mana_up

weld_element_ether
weld_element_fire
weld_element_air
weld_element_water
weld_element_earth
weld_build_index_scaled

mana_cost_scaled
damage_min_scaled
damage_max_scaled
range_scaled
cooldown_scaled
radius_scaled
duration_scaled
value_scaled
concentration_scaled
chance_scaled
quantity_or_strength_scaled

mana_cost_present
damage_min_present
damage_max_present
range_present
cooldown_present
radius_present
duration_present
value_present
concentration_present
chance_present
quantity_or_strength_present
```

The row joins the pending option with the participant's permanent/effective
progression rows, the static skill catalog, v2's semantic loadout details, and
the pending weld pair/build. A new catalog family/ID gets
`catalog_known=0`, its stable scaled ID, zero unknown semantics, and remains
selectable. The model is a pointer/scorer rather than a fixed “82 skill logits”
table:

```text
state_latent = encode(full_observation)
score_i = option_mlp(state_latent, descriptor_i)
choice = masked_softmax(score_1 .. score_n)
```

Thus option order has no learned meaning and three, four, or future bounded
offer counts share one scorer.

### C3. Credit assignment and exploration

Recommendation: option **(c), a separate semi-Markov (SMDP) PPO stream**.

Putting a rare choice into every 10-Hz composite action would repeat a
non-action thousands of times, distort entropy/log probability, and assign
choice gradients to frames where no choice existed. Plain episode-return
regression is better isolated but has unnecessarily high variance and cannot
bootstrap between multiple choices.

For choice event `i`, store the frozen observation/options/mask, selected
option, old log probability, and choice value. Let `d_i` be the number of
10-Hz reward steps until the next choice or terminal, and retain the existing
combat reward unchanged:

```text
R_i = sum(k=0..d_i-1) gamma^k * reward_(t_i+k)
delta_i = R_i + gamma^d_i * (1-done_i) * V(choice_(i+1)) - V(choice_i)
A_i = delta_i + (gamma * lambda)^d_i * (1-done_i) * A_(i+1)
```

Train a separate clipped PPO policy/value loss over these event records. The
main and choice encoders may share the observation trunk, but trajectory
schemas, log probabilities, entropy metrics, batching, and advantages remain
separate. Spell Welding is an ordinary option row; its pair/build features are
the only special input.

To maintain build exploration:

- choice entropy coefficient: proposed 0.05, normalized by
  `log(valid_option_count)`;
- sampling temperature: 1.25 until every offered family/weld pair has minimum
  offer and selection coverage, then anneal to 1.0;
- batch choice events across many seeded/team episodes rather than updating on
  one run;
- report offer, selection, and return statistics by family, option ID, and
  weld pair so a biased native offer distribution is visible.

### C4. Scripted-manager retirement and A/B escape hatch

The current deterministic manager prioritizes a same-element band, Health Up,
new primaries, and the `prefer|avoid|auto` weld rule
(`mods/bot-brain/scripts/brain.lua:145-252`). It is called before every policy
decision loop (`mods/bot-brain/scripts/brain.lua:979-980`), and the setting is
loaded in `mods/bot-brain/scripts/main.lua:118-128`.

V3 replaces that default with:

```text
policy.skill_choice_mode = learned | scripted
```

`learned` is the default and removes `policy_weld_preference` from the learned
path. `scripted` preserves the v2 function, including weld preference, solely
for A/B evaluation and scripted-bot compatibility. Scripted choice events are
tagged and excluded from choice PPO batches. There is no silent fallback from
a missing/invalid v3 choice model to the scripted manager.

## D. Inventory, items, and potions

### D1. End-to-end native system map

#### Taxonomy and identities

The retail runtime types are:

| Type | ID | Identity/state |
| --- | ---: | --- |
| Base/placeholder Item | 7000 / `0x1B58` | not participant inventory |
| Potion | 7001 / `0x1B59` | subtype `+0x1C`, stack `+0x88` |
| Ring | 7002 / `0x1B5A` | recipe-backed equipment |
| Amulet | 7003 / `0x1B5B` | recipe-backed equipment |
| Staff | 7004 / `0x1B5C` | recipe-backed equipment |
| Hat | 7005 / `0x1B5D` | recipe-backed equipment |
| Robe | 7006 / `0x1B5E` | recipe-backed equipment |
| Unregistered hole | 7007 / `0x1B5F` | no retail factory |
| Sack | 7008 / `0x1B60` | nested inventory root |
| Perk | 7009 / `0x1B61` | selector at `+0x88` |
| Map | 7010 / `0x1B62` | serializable map state |
| Wand | 7011 / `0x1B63` | recipe-backed equipment |
| Misc | 7012 / `0x1B64` | dye/key/book subtype |

Evidence:
`docs/reverse-engineering/native-items-equipment-and-loot.md:97-145`;
matching runtime layout at `config/binary-layout.ini:1339-1355`.

Every live item has a live object UID `+0x14`; recipe-backed equipment carries
source recipe UID `+0x18`. Recipe UIDs are allocated from persisted
`Game.ItemRecipeUID`, while live object UIDs use a different counter.
`native-item-catalog.json`'s `source_index` is deterministic file order and is
explicitly **not** a runtime recipe UID
(`docs/reverse-engineering/native-items-equipment-and-loot.md:80-95`;
`docs/reverse-engineering/native-item-catalog.json:1-12,694-744`).

The catalog has 47 named equipment recipes across seven sets and all 86 item/
set FX entries. Per item it carries parent set, type/native type, name,
description, image declarations, level, rarity, colors, parsed FX, and art
binding; each FX carries kind/operator/magnitude/target semantics
(`docs/reverse-engineering/native-item-catalog.json:14-65,694-744`).
`native-content-inventory.json` is the executable/content/atlas manifest, not a
live item or effect table (`docs/reverse-engineering/native-content-inventory.json:1-30`).

For custom items, stable `sd.content.v1` content ID is the network identity;
the peer-local recipe UID/native subtype is diagnostic only
(`docs/lua-items.md:3-5,19-41,78-82`). V3 observations must never learn raw
live item UIDs or peer-local recipe UIDs.

#### Potion effects and stacking

The six stock subtypes and exact effects are:

| Subtype | Potion | Exact effect |
| ---: | --- | --- |
| 0 | Health | set HP `+0x70` to max HP `+0x74` |
| 1 | Mana | set MP `+0x7C` to max MP `+0x80` |
| 2 | Wizard Chug | quadruple damage for 60 seconds via `+0x824`, then refresh |
| 3 | Antidote | clear poison and arm 10 seconds of immunity via `+0x74C` |
| 4 | Mind Chug | all-skills concentration for 60 seconds via `+0x828`, then refresh |
| 5 | Rejuvenation | restore both HP and MP to their maxima |

Evidence:
`docs/reverse-engineering/native-items-equipment-and-loot.md:352-374`;
the progression tick decrements `+0x824/+0x828` at
`docs/reverse-engineering/native-skills-and-spells.md:189-201`.

`Inventory_InsertOrStackItem (0x0055FF20)` merges potions only when type,
stable/custom content identity, and subtype match. The replicated authority
ledger uses the same `(type_id, content_id, slot)` key and advances
`inventory_revision`
(`docs/inventory-item-investigation.md:58-72`;
`SolomonDarkModLoader/src/multiplayer_local_transport/owned_progression_state.inl:444-498`).

#### Equipment and effects

The local gameplay scene owns one inventory root and exactly seven sinks:
hat, robe, three rings, amulet, and staff-or-wand
(`docs/reverse-engineering/native-items-equipment-and-loot.md:230-261`;
`config/binary-layout.ini:1327-1345`). Exact recipe membership determines set
completion. Two native equipment passes apply 39 parsed FX kinds, including
skill grants/boosts, class/spell damage/mana/cast/recharge, movement/recovery/
resistance/max-resource modifiers, summon caps, and weld features
(`docs/reverse-engineering/native-items-equipment-and-loot.md:263-350`).

V2 derived stats expose important aggregates, but exact item identity adds:

- completed-set identity and conditional set FX;
- per-skill/per-class targeted effects;
- grant/add/boost skill behavior;
- summon/spell cap feature bits and weld features;
- interactions that collapse into the same current aggregate but imply
  different future build value.

#### Pickup to inventory

A world Sack carrier owns the exact live item at `+0x148`. Stock local pickup
deactivates the carrier, transfers that pointer through
`Inventory_InsertOrStackItem` into `scene +0x13B8`, dirties the view, and nulls
the carrier ownership
(`docs/reverse-engineering/native-items-equipment-and-loot.md:437-459`).

In replicated play, host-authorized Item/Potion pickup instead updates the
participant-owned semantic inventory ledger and revision
(`SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl:132-151,605-619`).
Only when the accepting participant is the process-local peer does the receiver
queue a concrete native inventory credit
(`SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_packet_handlers.inl:601-637`).
Synthetic participants therefore own replicated inventory rows but do not own
a second scene inventory root.

The state/wire already carries inventory
`{type_id, recipe_uid, content_id, slot, stack_count, parent_item_index,
container_depth}` and equipment identities
(`SolomonDarkModLoader/include/multiplayer_runtime_state.h:124-146`;
`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h:475-488`).
The Lua runtime row currently omits `content_id`
(`SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp:228-256`).

#### Native use/equip entry points and synthetic safety

`Inventory::Use (0x0056D1B0)` is the central stock use dispatcher. It accepts a
live item UID, resolves the item recursively, applies the subtype effect,
decrements the stack, and removes/destroys an empty item
(`config/binary-layout.ini:966-990`;
`docs/reverse-engineering/native-items-equipment-and-loot.md:352-374`).
The custom-potion hook observes that local call, then queues the replicated Lua
use event (`SolomonDarkModLoader/src/lua_item_native_hooks.cpp:318-357`).
The current public custom-use queue always stamps the local participant
(`SolomonDarkModLoader/src/multiplayer_local_transport/lua_consumable_use_sync.inl:44-109`).

Equipping is similarly local. The safe transaction resolves a concrete item in
the one scene inventory, removes it, validates the one matching sink, returns
the previous item, refreshes progression, verifies exact identity, and rolls
back failures
(`SolomonDarkModLoader/src/mod_loader_gameplay/local_player_native_equipment.inl:235-470`).
The public queue accepts only a local recipe UID
(`SolomonDarkModLoader/src/mod_loader_gameplay/public_api_inventory.inl:30-94`).

Therefore:

- stock use/equip entry points are safe for the local player;
- **neither is directly safe for an authority-side synthetic participant**,
  because that participant has no native inventory root or seven native sinks;
- synthetic stock potion use needs a new authority transaction that validates
  the semantic ledger, applies the exact stock native effect to that
  participant's materialized actor/progression, decrements the ledger once,
  advances revisions, and publishes the result;
- synthetic equipment requires a substantially larger ownership/sink system
  and is not cheap. Equip/unequip should be deferred from v3.

### D2. Observation proposal

#### Potion descriptors

Use 12 stable potion-type slots. Slots 1-6 are always stock subtypes 0-5.
Slots 7-12 are registered custom potions in stable content-ID order. Each has
19 values:

```text
present
count_scaled
stock_health
stock_mana
stock_wizard_chug
stock_antidote
stock_mind_chug
stock_rejuvenation
custom
restores_hp_fraction
restores_mana_fraction
damage_multiplier_scaled
cures_poison
poison_immunity_duration_scaled
concentrates_all
effect_duration_scaled
custom_effect_known
identity_hash_a
identity_hash_b
```

Append `potion_type_count_scaled` and `potion_total_count_scaled` so overflow is
observable without assuming a global type cap. Stock descriptors come from the
proven table above. Custom registration should gain optional, non-native
`policy_effects` metadata with these same semantics; an arbitrary callback
cannot be reverse-inferred. Unknown custom effects remain identifiable and
possessed with `custom_effect_known=0`.

Also append three self timers, because the v2 booleans do not tell whether a
buff would actually change:

```text
self_damage_x4_remaining_scaled
self_poison_immunity_remaining_scaled
self_all_concentration_remaining_scaled
```

#### Equipped-item descriptors

Use the fixed semantic slot order `hat, robe, weapon, ring_1, ring_2, ring_3,
amulet`. Each has 15 values:

```text
present
catalog_known
identity_hash_a
identity_hash_b
rarity_scaled
level_scaled
set_complete
offense_effect_scaled
resource_effect_scaled
mobility_effect_scaled
defense_effect_scaled
targeted_effect_present
target_kind_scaled
target_magnitude_scaled
special_feature_present
```

The two deterministic identity buckets let known items learn exact synergies;
the semantic aggregates let random/custom/unknown gear generalize. The static
catalog supplies known recipe FX; the authority must capture an effect summary
for generated gear before the live item disappears into a synthetic ledger.
Current v2 derived stats remain and are not duplicated field-for-field.

#### Inventory summary

Nine bounded/log-scaled counts provide truncation/overflow context without
pretending non-actionable objects have actions:

```text
inventory_item_total_count_scaled
inventory_potion_count_scaled
inventory_equipment_count_scaled
inventory_sack_count_scaled
inventory_misc_count_scaled
inventory_perk_count_scaled
inventory_map_count_scaled
inventory_registered_custom_count_scaled
inventory_unknown_count_scaled
```

No per-item rows are proposed for unequipped gear, keys, dyes, books, sacks,
maps, or perks in v3. Their taxonomy is visible for state accounting, but no
illegal use/equip action is created.

### D3. Minimum item action set

Replace the 10-way cast head with one mutually exclusive **22-way ability
head**:

```text
none
primary
secondary_1
secondary_2
secondary_3
secondary_4
secondary_5
secondary_6
secondary_7
secondary_8
drink_potion_1
drink_potion_2
drink_potion_3
drink_potion_4
drink_potion_5
drink_potion_6
drink_potion_7
drink_potion_8
drink_potion_9
drink_potion_10
drink_potion_11
drink_potion_12
```

One decision cannot both cast and drink. Potion legality is possession plus
whether native state can change, never a behavioral threshold:

- Health: owned and HP below max.
- Mana: owned and MP below max.
- Rejuvenation: owned and either resource below max.
- Wizard/Mind Chug: owned and applying it would increase/reset the proven
  timer.
- Antidote: owned and poison would clear or immunity duration would increase.
- known custom potion: owned and its declared semantic effect can change;
- unknown custom potion: owned; possession-only legality preserves exploration
  rather than encoding a wrapper preference.

There is no equip, unequip, key, dye, sack, book, perk, map, ammo, or generic
“use item” action. The v3 escape hatch is to defer those, not to expose a
synthetic action that bypasses native validation.

### D4. Required inventory seams

#### Address-free semantic read

```lua
sd.bots.get_inventory_details(participant_id) -> {
  participant_id = 1,
  run_nonce = 0,
  inventory_revision = 0,
  equipment_revision = 0,
  descriptors_resolved = true,

  damage_x4_remaining_seconds = 0.0,
  poison_immunity_remaining_seconds = 0.0,
  all_concentration_remaining_seconds = 0.0,
  timers_resolved = true,

  potions = {
    {
      stock_subtype = 0,           -- or -1 for custom
      content_id = 0,              -- stable custom identity only
      identity_key = "stock:potion:health",
      count = 0,
      custom = false,
      effect_resolved = true,
      -- semantic effect descriptor fields
    },
  },
  equipped = {
    {
      slot = "hat",
      identity_key = "stock:hat:...",
      catalog_index = 0,
      catalog_resolved = true,
      -- normalized effect summary fields
    },
  },
  summary = {},
}
```

Static descriptors are cached by `(run_nonce, inventory_revision,
equipment_revision, derived_stat_revision, statbook_revision)`; live timers
are sampled without rebuilding recipe/FX descriptors. The producer resolves a
peer-local recipe UID to native name/type, then to the pinned catalog identity.
It never returns live item/recipe/catalog addresses. For a synthetic pickup,
the authority captures and retains the semantic identity/effect summary in the
owned ledger before carrier teardown. Also marshal the already-carried
`content_id` in existing `inventory_items[]`; Lua must not infer it from
`recipe_uid`.

#### Authority-side use transaction

```lua
sd.bots.use_consumable(participant_id, {
  potion_slot = 1,
  inventory_revision = 17,
}) -> true, {
  use_id = 42,
  inventory_revision = 18,
}
-- or false, "semantic rejection"
```

It is simulation-authority-only and rejects stale revision, absent stack,
dead/unmaterialized participant, run mismatch, unresolved identity, duplicate
use, and an effect that cannot be applied through a validated path.

- For the authority's local participant, queue exact item-UID
  `Inventory::Use` on the gameplay pump and verify stack/revision afterward.
- For a synthetic participant, validate the authoritative ledger, route the
  exact stock subtype behavior through that participant's native progression/
  actor routines, then atomically decrement the semantic stack and replicate
  the resulting timer/vitals/inventory revisions. Phase V3-2 must live-prove
  all six subtypes; if any cannot be invoked without field emulation or local
  player mutation, stop and return that subtype for owner adjudication.
- For custom potions, generalize the deduplicated `item.consumed` transaction
  to a target-aware authority participant. `policy_effects` is Lua metadata,
  not a native seam. Callback-only custom content remains an explicit risk
  because current callbacks are documented as local-owner-only
  (`docs/lua-items.md:43-95`).

No equipment mutation seam is proposed.

## E. Proposed v3 contract deltas

### E1. Main observation layout

V3 preserves the exact 395 v2 names in positions 1-395, then appends these
blocks in order:

| Block | Positions | Shape | Count |
| --- | ---: | ---: | ---: |
| v2 A-I unchanged | 1-395 | fixed | 395 |
| J. Self potion timers | 396-398 | 3 | 3 |
| K. Enemy identity/combat/status | 399-614 | 8 x 27 | 216 |
| L. Persisted-target motion/facing | 615-618 | 4 | 4 |
| M. Exact nearest obstacles | 619-730 | 8 x 14 | 112 |
| N. Hostile hazards | 731-935 | 12 x 17 + count | 205 |
| O. Potion descriptors | 936-1165 | 12 x 19 + 2 | 230 |
| P. Equipped items | 1166-1270 | 7 x 15 | 105 |
| Q. Inventory summary | 1271-1279 | 9 | 9 |
| **Total** | **1-1279** |  | **1279** |

Block K suffix order, repeated for enemy slots 1-8:

```text
species_index_scaled
species_known
role_melee
role_ranged
role_caster
role_spawner
role_exploder
role_boss
role_flying
role_stationary
facing_dx
facing_dy
anim_state_scaled
telegraph_known
winding_up
attack_active
recovering
slowed
slow_remaining_scaled
frozen
frozen_remaining_scaled
poisoned
poison_remaining_scaled
webbed
webbed_remaining_scaled
turn_undead
turn_undead_remaining_scaled
```

The existing ten v2 fields per enemy remain where they are; Block K is an
extension, not a reorder. Block L is:

```text
target_velocity_dx
target_velocity_dy
target_facing_dx
target_facing_dy
```

Block M uses the 14-name obstacle list in A3. Block N repeats these 17 values
for hazard slots 1-12, then appends `hazard_count_scaled`:

```text
present
hazard_type_index_scaled
type_known
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
source_enemy
```

Blocks O, P, and Q use the exact ordered names in D2. All K-nearest work,
relative velocity, normals, time-to-contact, role/telegraph lookup, item
catalog join, and counts are Lua computations. Native `*_resolved` fields gate
adoption and feed diagnostics; no address or exception code is an observation.

Proposed fixed additions reuse v2 scales and add:

```text
status_duration_scale_seconds = 60
hazard_lifetime_scale_seconds = 60
obstacle_count = 8
hazard_count = 12
potion_type_count = 12
aim_offset_world = 60
inventory_count_encoding = bounded log1p
```

The main v3 model proposal is a 1279-input two-layer tanh trunk with hidden
sizes 512/256. That capacity change is deliberately an owner decision rather
than an RE fact.

### E2. Main action/value heads

```text
movement head: 9, unchanged
target head: 9, unchanged
ability head: 22 (none, primary, 8 secondaries, 12 potions)
aim head: 9 (center + 8 compass offsets)
value head: 1
```

Main PPO composite selected-action log probability is the sum of movement,
target, ability, and aim log probabilities. The aim mask is center-only when
the selected ability is none, a potion, or a center-only spell family. The
ability mask remains target-conditioned for casts and state-conditioned for
potions.

### E3. Choice-event head

```text
state input: full 1279-value observation
option input: 56 values per offered option
option count: variable, native bound 16
policy: shared option scorer + masked softmax
value: one choice-event value
trajectory: separate variable-duration SMDP v3
```

Main observation/model/trajectory versions and choice-event trajectory version
all become 3. Lua and Python loaders reject every v1/v2 artifact; no shim or
weight/data reuse is proposed.

## F. Minimal native seam list

| # | Native responsibility | Proposed Lua surface | Why Lua cannot compute it |
| ---: | --- | --- | --- |
| 1 | Coherent address-free circle/segment/polygon geometry and participant radii | `sd.nav.get_collision_geometry(participant_id)` | Exact controller/scenery primitives and collision radii are not replicated |
| 2 | Semantic enemy modifier capture plus existing Turn-Undead fields | extend `sd.world.get_replicated_actors()` rows | Modifier lists require authority actor access; current Lua omits even replicated status fields |
| 3 | Stable hostile projectile/area/beam snapshots | `sd.world.get_replicated_hazards()` | Run actor replication filters these classes and existing effect feeds are player presentation subsets |
| 4 | Revision-cached item/potion/equipment identities, FX summaries, and three timers | `sd.bots.get_inventory_details(participant_id)` plus existing `inventory_items[].content_id` marshal | Synthetic ledgers have no native item objects; runtime recipe identity/FX/timers are not semantically exposed |
| 5 | Validated, exactly-once authority consumable mutation | `sd.bots.use_consumable(participant_id, selector)` | Stock use is local-inventory/local-player-only; synthetic participants need native effect routing plus atomic ledger replication |

Native evidence for seams 1-5 is in A2, B2, B3, and D1/D4 respectively. There
is no native seam for K sorting, exact geometric math, enemy role/telegraph
tables, velocity history, aim offsets, target selection, option descriptors,
the skill-choice decision/apply flow, custom potion policy metadata, inventory
summary, or equipment actions.

## G. Phased implementation plan

### Phase V3-2: native seams and live proof

- `config/binary-layout.ini`
  - add only newly proven modifier/timer/projectile/segment offsets or native
    functions; keep every value SHA-pinned and address-free at Lua.
- `SolomonDarkModLoader/src/gameplay_seams/*`
  - bind the new offsets/functions and source-organization pins.
- `SolomonDarkModLoader/src/mod_loader_gameplay/bot_pathfinding_grid_setup.inl`
  and adjacent nav state/public API files
  - build coherent static/dynamic geometry revisions, all fixed/moving segment
    classes, polygons, observer/participant radii, and stable non-address IDs.
- `SolomonDarkModLoader/include/multiplayer_runtime_state.h`,
  `SolomonDarkModLoader/include/multiplayer_runtime_protocol.h`,
  `SolomonDarkModLoader/src/multiplayer_local_transport/world_snapshot_capture.inl`,
  and snapshot packet builders/receivers
  - add semantic enemy status validity/durations.
- new hazard state/protocol/capture units under the existing runtime/local
  transport modules
  - add the pinned hostile type registry, stable hazard IDs, source/target,
    transform/motion/lifetime capture, bounded packets, and stale retirement.
- participant-owned progression/inventory state, loot pickup authority, and
  packet marshalling units
  - retain stable item descriptor/effect summaries across synthetic pickup and
    expose the existing content ID.
- bot/inventory public API and Lua binding units
  - implement `get_inventory_details` revision caching and
    authority-only `use_consumable`; generalize custom use IDs/events without
    exposing item UIDs.
- `docs/lua-nav.md`, `docs/lua-enemies.md`, `docs/lua-spells.md`,
  `docs/lua-bots.md`, `docs/lua-items.md`
  - document exact shapes, authority, revisions, resolved flags, and custom
    policy metadata.
- native/static/live tests
  - pin layouts/protocols/no-address contracts;
  - live-probe three layouts against exact patch/rays;
  - prove moving Gate and Goodie transitions;
  - prove all required enemy statuses and hostile hazard families;
  - prove all six stock potions for local and synthetic participants, timer
    units, exact stack decrement, no local-player mutation, and replication.

Exit rule: if any stock subtype requires field emulation instead of a proven
participant-scoped native path, stop that seam for owner adjudication.

### Phase V3-3: Lua observations, masks, actions, and choice events

- `mods/bot-brain/scripts/policy_spec.lua`
  - define the exact 1279 names/scales, 9/9/22/9 heads, 56-value option
    descriptor, versions 3, and strict counts.
- `mods/bot-brain/scripts/policy_geometry.lua`
  - replace quantized patch/ray queries with exact cached primitive tests and
    emit K=8 obstacle rows; retain `test_segment` only for movement legality.
- `mods/bot-brain/scripts/steering.lua`
  - preserve actor identity, heading, animation, semantic status, and stable
    velocity history.
- `mods/bot-brain/scripts/policy_spell_descriptors.lua`
  - add aim-family/offset masks without changing v2 loadout semantics.
- new focused descriptor modules, expected:
  - `policy_enemy_descriptors.lua`
  - `policy_hazards.lua`
  - `policy_inventory.lua`
  - `policy_skill_choices.lua`
- `mods/bot-brain/scripts/policy_observation.lua`
  - append Blocks J-Q in exact order; preserve actor-ID target persistence and
    cap-agnostic allies/rosters.
- `mods/bot-brain/scripts/brain.lua` and `main.lua`
  - issue mutually exclusive cast/potion abilities, apply the selected aim
    offset, invoke one learned choice event per generation, and retain explicit
    scripted A/B mode.
- `mods/bot-brain/scripts/policy_training.lua`
  - record main trajectory-v3 plus separate choice-event transitions while
    keeping the v2 reward formula unchanged.
- Lua fixtures
  - exact 1279 finite values/order; geometry cache/revision behavior; status,
    hazard, potion/equipment transitions; four-head masks; actor/hazard ID
    persistence; option permutation invariance and one apply per generation.

### Phase V3-4: strict runtime, model, bridge, and trainer

- `mods/bot-brain/scripts/policy.lua`, `policy_weights.lua`, and
  `models/bot-brain/policy-v3.json`
  - strict four-head v3 inference, 512/256 trunk if approved, option scorer/
    choice value, chunked hot reload, and explicit v1/v2 rejection.
- `tools/ml_bot/spec.py`
  - mirror every observation/action/option name and tensor shape.
- `tools/ml_bot/model.py`
  - four-head PPO with per-head entropy/metrics and composite log probability;
    separate variable-duration SMDP PPO/value/entropy loss for choice events.
- `tools/ml_bot/bridge.py`
  - strict main trajectory-v3 and choice-event-v3 parsing.
- `tools/ml_bot/expert.py`
  - target/aim/potion-aware bootstrap only; do not generate ground-truth skill
    choices from the retired script or reuse v2 data/weights.
- `tools/train_bot_policy.py`
  - collect enough complete choice intervals before choice updates; report
    offer/selection/build coverage; train/export/hot-load main and choice
    parameters atomically across all learned participants.
- docs
  - record fixed scales, entropy/temperature schedule, semantic coverage, and
    known limitations.

### Phase V3-5: contracts, verifiers, and headless smoke

- `tools/verify_lua_bot_brain.py`, `tools/verify_ml_bot_live.py`
  - 1279/version/finite checks; exact primitive fidelity; status/telegraph/
    hazard population; four-head legality; aim offset; potion counts/use and
    exactly-once credit; choice generation/apply/trajectory; solo/team zeros
    and population.
- Python/Lua round-trip fixtures
  - every name, mask, tensor, log probability, entropy, value, export, and v2
    rejection.
- static RE/launcher/source-organization contracts
  - pin every new native evidence claim and keep all prior floors green.
- accelerated disposable PPO smoke
  - multiple seeds/layouts and solo/team compositions; multiple learned
    participants; finite main and SMDP losses; choice exploration across runs;
    chunked hot reload.
- live behavior checks
  - dodge a hostile projectile/area using the hazard block;
  - preserve clearance around exact small geometry;
  - lead one straight projectile while keeping a homing spell center-masked;
  - make/apply a learned skill choice including a weld offer;
  - drink each stock potion only through its legal action and observe exact
    timer/vitals/stack transitions;
  - keep existing scripted skirmisher/guardian/striker verifiers green.

## H. Risks and owner decisions

1. **Observation/model size.** Approve or revise the proposed 1279 values,
   K-obstacles 8, K-hazards 12, potion slots 12, and 512/256 trunk. These are
   engineering choices, not native facts.
2. **Mandatory v2 fidelity correction.** The measured 4.47-5.95% point error
   is material. Recommendation: exact patch/rays is a Phase V3-2/V3-3 gate,
   not an optional late enhancement.
3. **Geometry classification.** Circles/shapes/segments are proven, but a
   universal destructible bit is not. Goodie is proven by type plus `0x2000`.
   Approve type-backed `destructible_resolved` with unknown types left false/
   unresolved rather than guessing from masks.
4. **Telegraph coverage.** Decide whether v3 requires every one of the 19
   retail families mapped before training, or accepts `telegraph_known=0` for
   unresolved states while identity/facing/raw animation remain available.
5. **Hazard registry.** The 46-class corpus is closed, but allegiance,
   velocity, radius, and lifetime fields remain family-specific. The
   orchestrator must freeze which classes count as damaging hazards versus
   presentation/summons before the wire shape is pinned.
6. **Aim head.** Approve discrete center+8 at 60 units and family masks, or
   request a different offset/radius. Continuous aim is not recommended for
   the first v3 contract.
7. **Choice SMDP hyperparameters.** Approve the variable-duration GAE scheme,
   entropy 0.05, temperature 1.25-to-1.0 schedule, and the minimum coverage
   threshold used before annealing.
8. **Custom potions.** Existing `on_consume` is local-owner-only and arbitrary.
   Decide whether v3 requires custom authors to declare target-aware
   `policy_effects`/synthetic safety, or permits possession-only learned use
   with callbacks invoked by the authority. Stock six are not affected.
9. **Synthetic stock use is a hard proof obligation.** Local
   `Inventory::Use` cannot target a bot. If exact participant-scoped native
   effect paths cannot be proven for all six subtypes, the affected actions
   must be removed or explicitly adjudicated; direct offset emulation would
   violate the charter.
10. **Equipment mutation.** Recommendation: affirm equip/unequip is deferred.
    A synthetic participant lacks the scene inventory root and seven sinks, so
    adding it would be a separate ownership system, not a cheap action.
11. **Generated/custom equipment identity.** Named stock recipes map cleanly
    to the pinned 47-item catalog. Random generated gear has no matching
    recipe definition, so its effect summary must be captured at pickup.
    Decide whether the proposed aggregates are sufficient or whether v3 needs
    a larger normalized FX grammar.
12. **Inventory overflow/count encoding.** Twelve potion types and bounded
    `log1p` counts are proposed without a native stack cap. The exact saturation
    constant and custom-slot overflow policy need to be frozen with the final
    observation contract.
13. **Recurrent memory.** Nothing in this investigation requires it:
    actor/hazard IDs, velocity history, telegraph state, and event-duration
    choice credit close the demonstrated gaps. Recommendation: keep recurrence
    out of v3 as chartered.

## I. Phase V3-2 implementation record

The charter adjudications supersede the open decisions in H. Phase V3-2
implemented only the five approved native seams:

1. `sd.nav.get_collision_geometry(participant_id)` publishes exact native
   circles, fixed and moving segments, polygons, observer/participant radii,
   scene-scoped semantic IDs, and separate static/dynamic revisions. Fixed
   FenceGrate and BrokenFenceGrate endpoints come from their class-owned
   working fields; moving Gate lines come from their retained collision
   records. Wizard bodies are excluded from the primitive list and participant
   radii are published separately.
2. `sd.world.get_replicated_actors()` rows now carry resolved slow, frozen,
   poison, web, and existing Turn-Undead state in native ticks and seconds.
   Protocol 90 owns the bounded semantic wire fields.
3. `sd.world.get_replicated_hazards()` unions and deduplicates the world
   transient list with gameplay buckets. It classifies all 38 frozen hostile
   families, retains unknown hostile effect-band actors with
   `type_known=false`, and exposes no address or exception data.
4. `sd.bots.get_inventory_details(participant_id)` joins replicated inventory
   and equipment to stable content identity, catalog/effect summaries, and
   native timers. Static rows are cached by `(run_nonce, inventory_revision,
   equipment_revision, derived_stat_revision, statbook_revision)` while live
   timers are overlaid on each call. Replicated inventory rows now marshal
   `content_id`.
5. `sd.bots.use_consumable(participant_id, selector)` reserves one ranked
   stack against an exact inventory revision, advances the authoritative
   revision once, routes only proven participant-scoped native effects, and
   publishes reliable inventory/use state. A stale selector cannot reapply
   the effect.

### Live acceptance

The fresh end-to-end probe used three disposable procedural runs with seeds
`0x2A0FC5AA`, `0x11111111`, and `0x22222222`:

- exact policy patch: 27,648 samples, zero mismatches;
- exact policy rays: 36,860 samples, zero mismatches;
- ray clearance: 4,604 distances, MAE 0 and maximum error 0;
- wider dense placement diagnostic: 154,803 samples, six conservative
  false-blocks and zero false-opens, an aggregate 0.00387589% error. All six
  occurred outside the policy patch/ray samples in the first seed.

The former 4.47-5.95% policy error class is therefore eliminated. Every run
also published hundreds of circles, fixed/moving segments, polygons, the
observer radius, and two participant-radius rows. Pushable Goodies remained
nonblocking and Gate segments remained openable.

The modifier probe observed clean false baselines followed by slow
`5425 ticks / 54.25 s`, frozen `5203 / 52.03 s`, poison
`5004 / 50.04 s`, and web `4814 / 48.14 s`; the native factory poison path
also surfaced before the classifier sweep. The hazard probe captured real
Archer Arrow, DemonSkull EyeLaser, and DireFaculty RainOfBones production,
with concurrent maxima of seven projectiles, one area, and two beams. Its
synthetic unknown hostile row remained visible with `type_known=false`.

All six stock potion subtypes survived pickup-to-ledger round trips with six
distinct drop IDs and monotonic inventory revisions. Inventory details
returned six stock/content/identity rows, seven equipment slots, and native
timer conversions of 60 seconds Damage x4, 10 seconds poison immunity, and
30 seconds all-concentration. Synthetic use proved:

| Subtype | Result |
| ---: | --- |
| 0 Health | one stack and one revision consumed; HP restored through the participant-scoped native path |
| 1 Mana | one stack and one revision consumed; mana restored through the participant-scoped native path |
| 2 Wizard Chug | rejected without stack, timer, or revision mutation |
| 3 Antidote | rejected without stack, timer, or revision mutation |
| 4 Mind Chug | rejected without stack, timer, or revision mutation |
| 5 Rejuvenation | one stack and one revision consumed; HP and mana restored through the two native paths |

Repeating each successful selector was rejected as stale. Runtime vitals
matched the native result and the local player's HP/MP stayed unchanged.
Subtypes 2-4 therefore lose learned actions exactly as adjudicated: the retail
binary exposes only local-player or direct-field paths, not a proven
participant-scoped native effect route.

### Verification

- clean Win32 Release loader rebuild: zero warnings and zero errors;
- source organization: 672 fragments;
- static RE contracts: 306/306;
- Python unittest discovery: 526/526;
- live v3 native-seam probe: passed, with all public-table forbidden-key
  checks at zero and no address, pointer, SEH, exception code, or hexadecimal
  diagnostic in public errors.

The ordinary `dist/launcher` DLL was held by an unrelated process that could
not be touched under the environment guardrails. Verification therefore used
a worktree-local launcher publish with the byte-identical clean Release DLL;
the native build and launched binary hashes matched.

## J. Phase V3-3 implementation record

Phase V3-3 implements the frozen Lua contract without loading a learned model.
The strict runtime, Python mirror, trainer, and replacement v3 weights remain
one V3-4 cutover; the historical v2 Lua artifact is neither adapted nor loaded.

### Contract and Lua behavior

- `policy_spec.lua` now defines exactly 1,279 unique ordered observation names,
  preserves the 395-value v2 prefix, fixes versions at 3 and the trunk at
  512/256, and declares movement/target/ability/aim heads of 9/9/22/9.
  Inventory counts use `log1p(min(count, 99)) / log(100)`. The choice contract
  contains exactly 56 ordered option descriptor names, a maximum of 16 native
  options, entropy 0.05, initial/final temperatures 1.25/1.0, and coverage 20.
- `policy_geometry.lua` adopts only complete collision snapshots, keys copied
  primitives by `(scene_epoch, run_nonce, static_revision, dynamic_revision)`,
  polls native dynamic state at two-second cadence, and uses current replicated
  participant positions between polls. Circle, segment, and polygon overlap
  recompute the 48-cell patch, eight clearance rays, and K=8 obstacle rows with
  the observing participant excluded. `sd.nav.test_segment` is used only for
  movement-action legality.
- Focused enemy, hazard, inventory, and skill-choice modules populate Blocks
  J-Q. Unknown active hostile hazards are retained with `type_known=0`.
  Potions are ranked by descending count; Wizard Chug, Antidote, and Mind Chug
  remain visible but are permanently masked independent of vitals or timers.
  Health, Mana, Rejuvenation, and declared synthetic-safe custom effects retain
  state/usefulness legality. Equipment is observation-only.
- Ability execution is mutually exclusive across none, primary, eight
  secondaries, and twelve ranked potion slots. The nine-way aim head is
  center-only for none, potions, homing, beam/cone, toggle, self, and radial
  families; proven heading/point/line/area families receive all offsets.
- Each new pending native skill generation freezes the full observation,
  option rows, and mask. Learned mode invokes the choice head once per
  generation; scripted mode retains the deterministic manager and weld
  preference as an A/B escape hatch. Main trajectory-v3 and separate
  choice-event-v3 SMDP records are bounded independently. Scripted choice rows
  carry `trainable=false` and are excluded by the normal choice drain. The
  combat reward remains exactly the v2 formula.

There is no observation-layout or option-descriptor delta from the adjudicated
proposal: the final sizes are 1,279 and 56 respectively. The only
implementation-time concretization is the aim-family mask, derived from the
already cited native primary/secondary dispatch tables; it changes no tensor
shape or descriptor.

### Deterministic and static verification

The V3-3 Lua fixture proves:

- 1,279 finite values in exact name order;
- exact self-excluding primitive geometry, three native refresh requests but
  only two revision-driven geometry builds, and no per-observation rebuild;
- enemy-status, target-motion/facing, obstacle, unknown-hazard, hazard,
  potion, equipment, and ally transitions;
- target-conditioned ability masks, the three permanent stock-potion masks,
  and center/free aim-family masks;
- 56-value permutation-invariant option rows, one apply per generation,
  a two-step choice duration, scripted-row exclusion, and both trajectory-v3
  record shapes.

Every bot-brain Lua file passes `luac -p`. Final repository verification is
306/306 static RE contracts, 526/526 Python unittests, and 672 checked
source/header fragments.

### Fresh scripted-live verification

`verify_mod_settings_lifecycle.py` passed on the worktree's isolated
`ms2-host`/`ms2-client` stages with audio disabled. It explicitly started the
stock wave schedule before measuring behavior. Guardian `Ward` completed 190
think ticks and 158 accepted moves while holding 50.24997 units from human
participant 1. Striker `Spark` completed 249 think ticks, 149 accepted moves,
and 125 accepted casts with a 262.014 attack window. The skirmisher reload was
accepted, the third requested bot reported `lobby full` without a reconciliation
error, both processes stayed responsive, and no crash artifact appeared.

`verify_lua_bot_brain.py` also passed fresh on isolated
`bot-host`/`bot-client` stages with audio disabled. The bot reached wave 7 alive
at 50/50 HP, issued and accepted 15/15 casts, accepted 75 movement requests,
and accumulated 3,579.427 units of brain-measured path motion. Both peers
reported policy version 3, observation size 1,279, hidden sizes 512/256, and
9/9/22/9 heads. The active Fireball primary resolved at mana cost 12 and range
297.993988. Cleanup stopped only the exact launcher-returned staged process
IDs after executable-path equality checks.

Three verifier corrections were required to make those gates measure the
intended behavior, not to change game or policy semantics: the settings
verifier now starts stock waves after entering its test run; numeric parsing
preserves decimal string participant IDs before any floating-point conversion;
and primary priming accepts an already-active requested Fireball instead of
requiring the verifier itself to select it from an offer.

## K. Phase V3-4 implementation record

Phase V3-4 is the strict runtime/trainer cutover. The historical v1 and v2 JSON
files remain historical inputs only; neither runtime accepts them and no old
weights, rollouts, or scripted skill-choice labels seed v3.

### Runtime and artifact

- `policy.lua` validates the exact 1,279 -> 512 -> 256 trunk, four masked
  9/9/22/9 main heads, main value, and all choice-scorer tensors. Main
  inference selects target before target-conditioned ability, then ability
  before family-conditioned aim. Its composite log probability is the sum of
  the four selected-head logs.
- The choice scorer shares the 256-value state latent. Each offered 56-value
  descriptor is concatenated with that latent and passed through one 128-unit
  tanh option layer, followed by a shared scalar score. Masked softmax is over
  the offered set and a separate choice value reads the shared state. The
  128-unit option width is the only implementation-time concretization not
  fixed numerically by the adjudication; it adds no observation/action delta.
- `models/bot-brain/policy-v3.json` and `policy_weights.lua` are exact exports
  of one parameter map. Hot reload transfers the larger Lua artifact in
  512-KiB tokenized chunks, then compiles and validates the full candidate
  before one runtime swap. Main now installs the v3 runtime at startup; the
  V3-3 unavailable branch is removed.
- Both loaders explicitly classify model/observation versions 1 and 2,
  architectures `mlp-tanh-two-head-v1` and `mlp-tanh-three-head-v2`, and the
  old 87/395 observation shapes as incompatible. There is no adapter or shim.

### Main PPO and choice-event SMDP PPO

- Python mirrors every ordered observation, descriptor, action name, parameter
  name, tensor shape, and dynamic choice temperature. NumPy inference and Lua
  inference are compared on one fixed 1,279-value input for all four main
  heads/value and on a masked three-option scorer/value input.
- Main PPO trains all four heads with a composite old log probability and
  reports movement, target, ability, and aim entropy separately. Defaults are
  0.01, 0.02, 0.01, and 0.01 respectively.
- Choice PPO uses complete variable-duration intervals only. For interval
  duration `d`, it applies the frozen discounted interval return,
  `gamma^d` value bootstrap, and `(gamma lambda)^d` advantage recursion.
  Entropy coefficient 0.05 is normalized per row by `log(valid options)`; a
  one-option row has zero normalized entropy.
- Choice softmax temperature starts at 1.25. Coverage registers every offered
  semantic family and weld-pair key and counts selected keys. It changes to
  1.0 only when every registered key has at least 20 selections. Coverage and
  the active temperature persist in checkpoint metadata.
- Live collection is enabled before learned participants materialize so native
  choice offers enter training. Trainer-side scripted progression priming is
  removed. Once the curriculum arena is ready, a main-only reset finishes and
  clears setup rows while preserving the open choice interval and its duration
  rewards. A new episode-finalization edge terminalizes pending main and choice
  records before drain; scripted rows stay tagged through bridge transport and
  are partitioned out before choice batching. Main responses are limited to
  16 records and choice responses to one interval; live rollouts are capped at
  8,192 steps so worst-case finite text remains below the loader's fixed
  1-MiB response ceiling. Complete choice intervals accumulate across
  disposable sessions until the configured minimum batch (default 32).
- Main and choice Adam states are independent while both update the shared
  trunk. Every learned participant in the composition contributes main and
  choice records. Checkpoints include both streams' parameters and are written
  through temporary JSON/Lua files before atomic replacement and hot reload.

### Bootstrap and limitations

The deterministic v3 expert chooses an enemy first, derives target-conditioned
spell legality, selects potions from vitals and ranked possession, and derives
free aim from target velocity plus hazard context. It produces no option-choice
labels. The checked-in 6,000-sample, 20-epoch seed achieved held-out accuracies:

| Head | Accuracy |
| --- | ---: |
| movement | 0.8850 |
| target | 0.7617 |
| ability | 0.7175 |
| aim | 0.9158 |
| joint | 0.4583 |

The seed is initialization, not a competence claim. Wizard Chug, Antidote,
and Mind Chug remain observed/permanently masked; equipment remains
observation-only. Learned-live dual-stream behavior is deliberately left to
the V3-5 smoke and verifier gate.

### Verification

The deterministic suite proves exact Lua/Python name and tensor agreement,
finite bootstrap and PPO updates for both streams, duration-zero and positive
SMDP intervals, normalized choice entropy, the coverage temperature gate,
strict v1/v2 rejection in both loaders, byte-identical JSON-to-Lua export,
chunked atomic runtime swap, and fixed-input inference parity for every head,
both values, and the option scorer. Final repository suite counts are recorded
as 528/528 Python unittests, 306/306 static RE contracts, and 672 checked
source/header fragments.

## L. Phase V3-5 implementation record

Phase V3-5 closes the learned-live gate without changing the 1,279-value
layout, 56-value option descriptor, model shape, action set, reward, or checked
in seed weights. Runtime acceptance uses forced policy parameters only to make
each behavioral assertion deterministic; every observation, mask, native
action, and resulting state transition remains the production path.

### Contract fixtures and verifiers

The Lua/Python parity fixture now compares all ordered observation, descriptor,
and action names; every parameter tensor shape; all four masks; selected-head
log-probability components and their composite; per-head entropy; main value;
choice mask, probability, entropy, normalized entropy, log probability, and
value; both version-3 trajectory shapes; and strict v1/v2 rejection errors.
The bridge fixture also retains scripted choice rows through transport and
proves that they cannot enter a learned choice batch.

`verify_ml_bot_live.py` uses disposable worktree-local sessions and checks:

- exactly 1,279 finite values at observation version 3, with exact live
  movement, target, target-conditioned ability, and family-conditioned aim
  masks;
- a collision spot audit over 48 patch cells and 64 ray samples against
  `sd.nav.test_segment`, with zero mismatches and a walkable observing-bot
  cell;
- replicated enemy species, combat-status, and telegraph rows; actor-ID target
  persistence across a slot re-sort; known hostile hazard population; solo
  ally count zero and authority/team counts one/two;
- a learned choice generation, native apply, weld build-1000 promotion, and a
  trainable choice-event-v3 record with duration/reward count 11; and
- ranked inventory/potion rows, permanent masks for Wizard Chug, Antidote, and
  Mind Chug, and exactly one native use/revision/stack transition for Health,
  Mana, and Rejuvenation.

The scripted verifier samples the same v3 geometry, enemy, hazard, inventory,
and no-address contracts while retaining its original replicated combat gate.
Its declared god-mode run now sustains scripted bot vitals on both isolated
replicas. A two-second death confirmation prevents a single snapshot in which
`sd.bots.list()` is transiently empty from being mislabeled as a death; a
persistent disappearance still fails. The settings/profile verifier likewise
uses god mode because it measures guardian, striker, and skirmisher behavior,
not survival against a random stock wave.

### Live behavior evidence

The final learned-live report is
`runtime/v3-phase5/live-33073130.json` (runtime evidence, not committed):

- exact geometry: 407 circles, 10 segments, 18 polygons, 48/48 patch and
  64/64 ray samples correct. The bot moved away from radius-8 geometry 374,
  from distance 98.316 to 208.113, even though the v2 cell sample reported the
  location open: `policy exact-obstacle clearance accepted geometry_id=374
  slot=2 radius=8.0 clearance=65.3155804356 movement=west`;
- projectile dodge: known Arrow hazard 2 occupied hazard slot 1 and caused a
  perpendicular east move with 3.210 units of observed displacement:
  `policy hazard dodge accepted hazard_id=2 slot=1 movement=east
  time_to_contact=0.0`;
- straight-projectile lead: a released stock Skeleton produced normalized
  target velocity `(-0.355737,-0.035518)` and the Fire projectile selected
  northwest offset `(-42.426407,-42.426407)`, with positive lead dot 16.600:
  `policy lead cast accepted target=281474976710658 aim=northwest ...`;
- homing mask: Ether primary exposed `100000000` and cast only at center:
  `policy center-mask cast accepted ability=primary
  target=281474976710657`;
- learned build: option 52 was selected from a real weld offer and promoted
  build 1000: `policy skill choice accepted mode=learned generation=3
  option_id=52`;
- potion actions: Health, Mana, and Rejuvenation each changed count 1 to 0,
  advanced inventory revision once, returned use IDs 1/2/3, and converged to
  the expected native HP/MP values. Their corresponding log lines are
  `policy potion accepted slot=1 use_id=1`, `slot=1 use_id=2`, and
  `slot=1 use_id=3`; and
- the existing v2 checks still passed: target selection, an actor-ID-preserved
  slot 1 to slot 2 re-sort, a secondary accepted at 593.226 beyond the 431.594
  primary window, and one gold pickup credited exactly once.

The stock Arrow family does not currently resolve a participant target or
positive contact time, so this sample reports `targeting_self=false` and
`time_to_contact=0`. The verifier independently proves a known hostile Arrow,
its source lane, a clear perpendicular movement action, native retrigger, and
bot displacement; it does not invent the two unresolved fields.

Fresh scripted-live evidence is also green. The profile lifecycle observed
guardian Ward engaging human participant 1 at distance 238.323 with 38 moves,
striker Spark with 26 casts and 32 moves, and a live skirmisher reload. The
replicated wave verifier reached wave 6 with both peers alive, 23/23 accepted
casts, 4,346.774 path units, 14 status-resolved/telegraph enemies, and all v3
semantic seams valid.

### Disposable dual-stream PPO smoke

One three-episode invocation rotates `solo-learned`, `mixed-skirmisher`, and
`multi-learned-2` on fresh native seeds/observed nonces 366588449, 784326015,
and 941597147. Every episode records the stock layout hash
`fe2e01b0ab62f644c3e5bf53f71df3a41968b95c8e22fa44c1d1250ba08cdb5b`,
composition, participant IDs, trajectory counts, losses, and buffer-drop
counts in an atomic `episode-NNNN.json`; the complete report is
`runtime/v3-phase5/ppo-final-33075001/live-training-report.json`.

| Composition | Main rows | Learned participants | Main policy/value loss | Choice intervals | Choice policy/value loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| solo learned | 134 | 1 | 0.117395 / 0.003521 | 1 | -0.184081 / 0.034163 |
| learned + skirmisher | 129 | 1 | 0.055703 / 0.001111 | 1 | -0.144840 / 0.022177 |
| two learned | 132 (66 + 66) | 2 | 0.309937 / 0.003250 | 2 | 0.002321 / 0.000976 |

All losses and entropies are finite; both trajectory buffers report zero
drops. Each episode atomically exported JSON/Lua checkpoints and advanced the
runtime generation through the chunked hot-reload path. Natural combat in the
bounded curriculum arena produced no level-up after 2,053 decisions because
that arena does not award progression. Acceptance therefore uses the explicit
`--validation-native-choice-event` option: it invokes one debug-only native
level-up, then leaves learned option scoring, native application, reward
duration, terminal close, bridge transport, and SMDP PPO untouched. The option
is off by default and ordinary training never synthesizes progression.

### Final verification and deviations

The exact candidate passes a clean Release build with zero warnings/errors,
537/537 Python unittests, 306/306 static RE contracts, and 672 checked
source/header fragments. The only contract-level evidence limitation is the
unresolved Arrow target and contact-time pair described above. The stock
boneyard is the only supplied layout, so layout-override plumbing remains
validated but a multi-layout quality corpus remains non-blocking as
adjudicated. No v3 layout, descriptor, head, action, reward, or native seam
changed in this phase.

## M. Phase V3-6 natural-XP wave training

This phase supersedes only V3-5's acceptance-only validation-choice smoke.
V3-6 does not change policy v3's observation, action, model, reward, or
trajectory contracts. Section N records the subsequently approved V3-7 reward
change; it deliberately keeps the version-3 trajectory schema. Section O is
the definitive V3-8 multiplayer progression, attribution, and normal-campaign
guard behavior; the original V3-6 acceptance evidence below is retained as a
reproducible historical proof.

### XP root cause

Two independent conditions made the curriculum incapable of producing a
natural learned choice:

1. The trainer launched every episode with `-FreshInstall`. The solo launcher
   translates that switch to `--fresh-install`; without it, the same
   disposable staging path uses `--temporary-profile`
   (`scripts/Launch-LocalSoloSession.ps1:191-201`). Fresh-install deliberately
   passes no retail profile into temporary-profile preparation, whereas the
   ordinary temporary profile copies the retail app-data tree
   (`SolomonDarkModLauncher/src/Launch/IsolatedProfileBootstrapper.cs:18-26,
   71-101`). Stage mirroring also excludes the top-level `sandbox` directory
   when that mode is selected
   (`SolomonDarkModLauncher/src/Staging/FileTreeMirror.cs:11-29,46-54`). In a
   fresh owned probe, `start_testrun` therefore materialized only participant
   actors: `Solomon_Dig` type `0x1391`, the Lantern, the stock survival state,
   and a functioning wave spawner were absent. Calling the wave start seam
   could not create a wave. Repeating the probe with the isolated temporary
   profile materialized actor types 5009/5010 and the player immediately.

2. The curriculum manager does not ask the retail wave spawner for a wave. It
   repeatedly requests exact type-1001 enemies with
   `allow_direct_arena_spawn=true`
   (`tools/ml_bot/bridge.py:666-770`). That request calls the stock exact-group
   constructor directly, including a null spawner in the no-spawner path
   (`SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/
   manual_enemy_spawning.inl:278-319,396-448`), while manual-spawner test mode
   suppresses the normal wave tick
   (`SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/
   wave_spawn_filter.inl:327-362`). The native XP hook can observe XP only if
   stock code actually invokes the native experience-gain function
   (`SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/
   enemy_death_reward_level_up_hooks.inl:122-164`). In the owned curriculum
   probe, the learned bot killed successive exact enemies and their HP cycled
   through death, but its profile remained level 1 / XP 0 and the
   `xp.gaining` callback count remained exactly zero. The failure is upstream
   of synthetic profile sync or pending-choice handling: the direct death has
   no active stock-wave reward context and never enters native XP gain.

Giving that arena XP would require either reconstructing the stock wave reward
bookkeeping around exact spawns or inventing a second XP/kill-attribution
path. The former is the retail wave path; the latter would no longer prove
native progression. There is no cheap, correct curriculum patch. Curriculum
therefore remains intentionally XP-free, and wave episodes are the honest
choice-training environment. A final explicit curriculum-mode probe confirmed
level 1 / XP 0 before and after 261 collected combat decisions, with zero
native or learned choice events.

### Wave episode and progression gate

`live-ppo --episode-mode waves` is now the default. Each disposable session
uses the isolated temporary profile, idle preset, and the existing stock
survival state. The address-free wave router reads exact openable collision
segments, drives physical slot-0 input through the gate, approaches Solomon,
invokes `sd.hub.trigger_solomon_dig`, and waits for a positive native wave and
live-enemy count. It never calls `start_waves`, directly spawns an enemy, or
writes a transform. `--episode-mode curriculum` retains the fresh-install
direct arena for targeted drills.

Training is active before the retail wave starts and before any natural XP or
choice event can occur. The original acceptance probe required XP, a level,
and an accepted learned choice in one episode. V3-8 separates that competence
proof from normal integration health: ordinary campaigns proceed after an
aggregate learned `experience_delta >= 1`, while
`--require-natural-choice-proof` enables the strict level/choice assertion for
the first episode only. Complete choice intervals continue to accumulate
across episodes; episodes without a choice are valid.

The remaining divergence is inside the retail reward helper itself. Ghidra
shows `0x0063E7D0` dispatching `Badguy::Contact` through vtable slot `+0x4C`,
testing its nonzero return at `0x0063E80A`, reading the enemy reward at
`enemy+0x178` at `0x0063E829`, and calling helper `0x005C8880`. That helper
multiplies the reward by `gameplay+0x1AB8` but resolves the progression through
the hard-wired slot-0 handle at `gameplay+0x1654`. The recovered fields are
named in `config/binary-layout.ini:1312-1315,1836`; the loader's native
ExperienceGain and LevelUp entry points are pinned there at
`config/binary-layout.ini:1928-1929`.

Consequently, real waves invoke the correct kill/reward path but stock routes
that reward only to slot 0. V3-6 first closed the learned-bot XP gap by routing
a confirmed synthetic killer through its owned native progression. V3-8
replaces that narrow route with the game-wide shared progression transaction
described in Section O. Natural level-up still rolls each participant's native
options in its scoped Concentrate context, and the normal learned manager
scores and applies learned offers. Episode finalization closes every complete
choice interval with `trainable`, `accepted`, duration, reward count, and
reward sum before SMDP PPO.

### Rollout timeout

An omitted `--rollout-timeout` now resolves to
`max(180, 60 + rollout_steps / 10 * 1.25)` seconds: worst-case one-learned-bot
10-Hz collection, 25 percent headroom, and 60 seconds of allowance. An
explicit value remains an exact override. The resulting timeout and source are
written to checkpoint metadata and every episode/report JSON. At the transport
ceiling, 8,192 requested steps now receive 1,084 seconds instead of the old
fixed 180 seconds.

### V3-6 live evidence

The final post-build disposable episode was
`ml-v37-final-smoke-0731b-e0001`, with audio disabled, requested/observed native
seed and run nonce `772072821`, stock layout SHA-256
`fe2e01b0ab62f644c3e5bf53f71df3a41968b95c8e22fa44c1d1250ba08cdb5b`,
and composition `solo-learned`. The physical route acquired Solomon, invoked
the stock conversation, and entered wave 1 with nine live/spawned stock
enemies. Learned progression moved from level 1 / XP 0 to the collection gate
at level 2 / XP 92, then to level 2 / XP 140. The exact authority lines were:

```text
[bots] natural synthetic level-up choices pending. participant_id=1152921504606851072 generation=1 level=2 xp=92 next_xp=160 requested_choice_count=3 option_count=3 options=[35,50,49]
[bots] synthetic stock XP routed. participant_id=1152921504606851072 wave=9 enemy_type=1001 base_reward=3.825000 gameplay_multiplier=1.000000 native_amount=3.825000 level_before=1 level_after=2 xp_before=87.974991 xp_after=91.799988 credited_xp=3.824997
[bot-brain] roster=1 name=Learner 1 element=fire behavior=learned discipline=arcane native skill choice pending mode=learned generation=1 options=3
[bot-brain] roster=1 name=Learner 1 element=fire behavior=learned discipline=arcane policy skill choice accepted mode=learned generation=1 option_id=35
[bot-brain] roster=1 name=Learner 1 element=fire behavior=learned discipline=arcane choice interval closed mode=learned trainable=true accepted=true duration_steps=519 reward_sum=396.14
```

The updated-reward smoke trained 517 main rows and one complete natural choice
interval (`duration_steps=reward_count=519`, `reward_sum=396.14`). Main policy
and value losses were finite at `0.2900690866454867` and
`169.40483129402406`; choice policy and value losses were finite at
`-82.9435917130743` and `6760.121099500875`. Chunked hot reload advanced the
policy to generation 3, with 623 learned decisions and 621 accepted movement
requests. The omitted timeout resolved through the autoscale path to 180
seconds for the 512-step request.

The clean Release build completed with zero warnings and zero errors. Final
repository gates are 541/541 Python tests, 307/307 static RE contracts, and
675 checked source/header fragments. Fresh scripted-live verification remained
green: the skirmisher reached wave 6 alive at 50/50 HP with 32/32 accepted
casts, while the profile verifier exercised guardian, striker, and skirmisher
behavior without a reconciliation error. Runtime evidence is retained outside
the repository under `/mnt/d/codex-evidence/ml-bot-v37/`.

## N. Phase V3-7 reward semantics

The flat `+0.002` decision tick is removed. Merely remaining alive, including
while live enemies are unchanged, earns no reward. The controller retains the
approved dense own-damage coefficient `0.65`, self-HP delta coefficient
`1.25`, positive wave transition `+1.5`, terminal death `-2.0`, and clamp
`[-4,4]`. V3-8 makes both combat inputs source-attributed:

```text
xp_reward = max(0, attributed_kill_xp_current - previous) / XP_SCALE
damage_reward = max(0, attributed_enemy_hp_ratio_damage_current - previous) * 0.65
XP_SCALE = 25
```

The two monotonic counters are host-authoritative and reset by run nonce. The
kill-XP counter advances only for the native damage source that achieved the
kill; the damage counter consumes the same authoritative
`source_participant_id` / target HP before/after edge used by botcombat
verification. Shared party XP never advances either counter.
`Controller:finish_pending` computes one reward and passes that exact scalar to
`accumulate_choice_reward`, so the choice SMDP stream inherits the main
per-step stream without a second reward mechanism.

### Stock-wave calibration

An owned disposable episode used native seed/run nonce `29271575`, stock
layout SHA-256
`fe2e01b0ab62f644c3e5bf53f71df3a41968b95c8e22fa44c1d1250ba08cdb5b`,
composition `solo-learned`, and the real wave route. The authority log recorded
every learned-attributed stock kill as `(wave, enemy type, base reward, native
amount, XP before, XP after, credited XP)`. Waves 1–10 produced:

| Wave | Learned-attributed kills | Credited XP per kill |
|---:|---:|---:|
| 1 | 4 | 3.825000 |
| 2 | 7 | 3.825000–3.825001 |
| 3 | 6 | 3.825001 |
| 4 | 0 | — |
| 5 | 0 | — |
| 6 | 3 | 3.824997 |
| 7 | 0 | — |
| 8 | 19 | 3.442497–3.824997 |
| 9 | 0 | — |
| 10 | 0 | — |

Across the 39 kills, credited XP was `3.442497–3.825001`, median `3.824997`
and mean `3.677884`. `XP_SCALE=25` maps the median early kill to `0.15299988`,
inside the owner's `0.1–0.2` target. The exact zero-reward fixture holds HP,
XP, wave, and one live enemy's HP constant, obtains reward `0.0`, then appends
that same `0.0` to a choice interval while advancing its duration by one.

The V3-8 team fixture additionally advances shared progression by four XP
without advancing either attribution counter and obtains reward `0.0`. Its
solo-own-kill twin advances attributed XP by four and attributed enemy HP ratio
damage by `0.2`, producing exactly `4/25 + 0.2*0.65 = 0.29`, identical to the
pre-attribution solo formula for that edge.

This is a semantic discontinuity for future reward curves. No model,
observation, trajectory, or serialization shape changes, so there is no
version bump.

## O. Phase V3-8 shared progression, attribution, and campaign guard

### Stock root cause and threshold composition

The native damage dispatcher at `0x0063E7D0` calls the enemy contact method at
vtable `+0x4C`; only a nonzero result enters the stock reward block. That block
reads `enemy+0x178` and calls `0x005C8880`. The helper multiplies by
`gameplay+0x1AB8`, then always calls `ExperienceGain` on the slot-0 progression
at `gameplay+0x1654`. The damage source is absent from that final lookup. This
is why a remote or synthetic participant can own the lethal edge while retail
XP still advances only the host progression.

`ExperienceGain` at the hooked post-gate entry `0x00680AD8` applies native
level/bonus scaling once, adds the result at `progression+0x34`, and invokes
`level_up` at `0x0067C250` when appropriate. The latter indexes one global
float threshold table at `0x008096F8`; the first values are `0, 90, 160, 275,
390, 520, 650, 800, 1060, 1300, 1600`. It does not vary by participant,
element, Discipline, or book. Exact threshold evidence and the strict
greater-than loop are recorded in `docs/skill-picker-re.md`. Applying the
reward independently to every participant would repeat native scaling and
could drift. The canonical transaction therefore lets stock mutate slot 0
once and mirrors the exact resulting snapshot.

### Host-authoritative shared transaction

`shared_stock_xp_hook.inl` captures the authoritative damage source participant,
run nonce, wave, enemy type, base reward, and gameplay multiplier before the
contact call. It arms a short-lived credit only after the exact native lethal
return and nonpositive post-contact HP. The five-byte wrapper at the outer
`0x0063E7D0` damage dispatcher snapshots slot 0 before calling the unmodified
dispatcher, then consumes the credit synchronously after the contact and stock
reward block return. If stock advanced slot 0, that exact native result is
canonical. The headless host path can fail stock's local-player eligibility
gates even though the synthetic killer is valid; in that case the wrapper
calls the proven native `ExperienceGain` once on the killer's owned progression
and uses its result as canonical. It never applies the input amount separately
to every participant. The existing `HookExperienceGain` remains the ordinary
filter/observation hook and does not own this transaction.

The host then:

1. updates every in-run participant's runtime/profile snapshot;
2. synchronizes each materialized nonlocal progression through native
   `level_up`, under that participant's Concentrate context, and restores live
   HP/MP after the native refresh;
3. retains the exact float XP rather than independently rounding/rewarding;
4. lets the existing native per-participant option roll and synchronized
   level-up barrier produce choices; and
5. publishes protocol-90 `SharedProgressionPacket` reliably with authority,
   killer, run nonce, revision, level, float XP, and next threshold.

Clients accept the packet only from their configured authority and for their
active run, reject stale sequence/revision state, synchronize their local
native progression, and update participant rows. Later owner-authored state or
frame packets are overlaid with the retained shared snapshot and cannot roll
the total backward. No Lua-facing address or exception code is exposed.

### Learned reward attribution

Shared progression and learned reward are intentionally separate. The host
maintains two monotonic, run-scoped counters per participant:
`reward_attributed_experience` and
`reward_attributed_enemy_hp_ratio_damage`. The first advances only for the
killer identified by the consumed native kill credit and uses the actual
post-scaling XP delta. The second advances from the authoritative botcombat
damage edge's `source_participant_id`, HP before/after, and maximum HP; overkill
is clamped at zero HP so solo behavior matches the former snapshot decrease.
The damage layer's local-human source identity is the transport peer ID, while
the owned participant-framework row is the stable local ID 1. Shared kill and
reward lookup normalize that one representation boundary; remote-human and
synthetic IDs already match their participant rows.
Lua publishes zero until the counter's run nonce matches the participant's
current run. `policy_training.lua` differences only these counters. A learned
bot therefore receives shared levels and offers when a teammate kills, but
earns neither XP nor damage reward for the teammate's work.

### Normal guard versus acceptance proof

The normal wave integration guard is explicitly
`WAVE_INTEGRATION_MIN_EXPERIENCE_DELTA = 1`, polled every `0.2` seconds within
the `300`-second startup/integration window. It measures only whether stock
waves can move learned progression. Level-up and choice events are not required
per episode. `--require-natural-choice-proof` is the one-time stricter path:
the first episode must observe level delta at least one, one native learned
choice, one accepted learned choice, and a complete accepted interval. Every
episode log records the gate result plus final per-learned-participant and total
XP deltas. Rollout timeout remains independently autoscaled from requested
steps unless explicitly overridden.

Shared progression also levels the disposable trainer owner's stock slot. Its
native picker participates in the same pause barrier but is not controlled by
the learned policy. While collecting headless trajectories, the bridge resolves
that host-self offer through `sd.runtime.choose_level_up_option` using the first
native-valid option, records the resolution separately, and waits for the
barrier to clear. This choice is trainer-owned, never emitted as a learned or
scripted choice event, and cannot enter either PPO batch.

### V3-8 acceptance evidence

The final exact tree rebuilt the loader and all launcher surfaces in Release;
the loader reported zero warnings and zero errors. The complete gates passed
546/546 Python tests, 308/308 static RE contracts, and 678 checked source/header
fragments. The deterministic Lua fixture produced:

- teammate progression `level 1 -> 2`, `experience 89 -> 92`, with both
  attribution counters unchanged and reward exactly `0.0`;
- the same solo own-kill edge with four attributed XP and `0.2` attributed HP
  ratio damage, yielding exactly `4/25 + 0.2*0.65 = 0.29`; and
- an idle bot with a live enemy and no attributed edge yielding exactly `0.0`,
  including the unchanged per-step choice-interval accumulator.

The one-time natural acceptance run is
`runtime/evidence/v38-final-choice-0731i/live-training-report.json`. Seed and
observed nonce `661733774` ran one learned bot with guardian and striker. The
normal integration gate passed at eight XP without demanding a level or
choice. At the native boundary, the canonical snapshot moved from
`87.974991` XP at level 1 to `91.799988` XP at level 2 against threshold 90.
The native log then showed pending offers for learned, guardian, striker, and
host-self progressions; the learned bot accepted generation 2 option 64,
guardian generation 4 option 32, striker generation 6 option 42, and the
trainer resolved host-self option 21. The barrier completed with
`timed_out=0`. All four party rows finished synchronized at rounded XP 95 and
level 2. The learned choice interval was `trainable=true`, `accepted=true`,
duration/reward count 40, and reward sum `0.0`; finite SMDP policy/value losses
were `0.0 / 0.0`, and finite main policy/value losses were `0.0 / 0.0`. The
zero-reward result is expected for this interval: teammates supplied the
shared progression while the learned participant had no attributed kill or
damage edge.

The ordinary no-override smoke is
`runtime/evidence/v38-final-default-0731h/live-training-report.json`. Two
disposable episodes completed on seed/nonces `830849934` and `884979204`,
rotating `solo-learned` then `mixed-skirmisher`. Both positive-XP gates passed
at delta 4; final learned deltas were 11 and 8, with every in-run party row
synchronized to the same value. Neither episode leveled or produced a choice,
which is valid in normal campaign mode. Main policy/value losses were finite:
`0.0887129229996 / 0.289422446510` and
`0.0464687056305 / 0.443288686016`. Both recorded the default
`rollout-steps-autoscale` timeout source at 180 seconds.

Finally, `runtime/evidence/v38-final-scripted-0731b/result.json` passed the
unchanged scripted stock-wave verifier: the skirmisher reached wave 5 alive at
50/50 HP with 35/35 accepted casts and 3,665.659 movement units. The strict
team proof above independently exercised guardian and striker through their
native synchronized level-up choices. The scripted verifier's paired
host/client logs also matched 14 reliable progression publications to 14
client applications, ending at the same exact `53.550007` XP snapshot for run
nonce `546838040`.
