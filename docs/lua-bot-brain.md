# Autonomous Lua bot-brain roster

`mods/bot-brain/` is the opt-in reference brain for host-owned synthetic
participants. Its host-scoped `roster` list contains ordered rows with name,
element (`fire`, `water`, `earth`, `air`, or `ether`), native Discipline
(Mind, Body, or Arcane; stored as `mind`, `body`, or `arcane`), and Behavior
(`skirmisher`, `guardian`, `striker`, or `learned`). The current launcher
schema accepts up to 32 rows; the session's configured participant capacity,
not Lua, decides how many can become active. The mod is disabled by default,
so an ordinary game never gains an unsolicited participant.

The default roster contains one Arcane fire skirmisher named `Ember`. The
earlier `persona_name` scalar is gone; names belong to rows. The other launcher
controls remain: 340-unit kite radius, offense enabled, local 250/400 ms think
cadence for scripted rows, local focus key, and the confirmed host-only roster
respawn action. `policy_weld_preference` controls whether the shared skill
manager prefers, avoids, or automatically accepts Spell Welding only while
`skill_choice_mode=scripted`. The default `learned` mode routes each pending
native generation to the v3 choice-event head. Learned rows decide every
100 ms of simulation time once matching v3 weights are installed.

## Ordered reconciliation

`scripts/roster.lua` maintains one `brain.lua` context per list position. At
startup, live reload, and replicated list changes it compares rows by order:

- an unchanged row keeps its participant and behavior state;
- a removed row despawns through its bot handle;
- a new row spawns with that row's name, element, and Discipline; and
- a changed name, element, Discipline, or Behavior despawns and respawns the
  row.

The v1.0.1 launcher migration recognizes only the old bot-brain rows whose
`discipline` value was `skirmisher`, `guardian`, or `striker`. It rewrites that
value once under `behavior`, adds native `discipline: "arcane"`, and persists
the result atomically. Runtime Lua reads only the new keys; there is no lasting
legacy alias.

Retirement uses the reliable participant tombstone path. Humans and bots share
the configured multiplayer participant capacity. Roster reconciliation
iterates every configured row without a hard-coded player cap. If a row cannot
claim an open seat, the context remains desired and retries on later authority
ticks. Expected capacity refusals are summarized in `bot_brain_debug.status`
instead of becoming reconciliation errors. A rejection never crashes the mod
or game.

The brain never creates a standalone actor, writes an actor transform, or
drives a second native AI loop. All contexts run from `runtime.tick`, and
`sd.state.is_authority()` keeps decisions on the transport host. Clients adopt
read-only handles for focus/diagnostics and receive the normal participant
State, Frame, Cast, and retirement traffic.

## Shared native movement and offense

Every Behavior samples `sd.world.get_replicated_actors()` and keeps live
`tracked_enemy` rows. Scripted candidate destinations come from short steering
lookaheads clamped to the current arena and must pass `sd.nav.test_segment`
before `bot:move_to`. The learned observation uses a per-scene
`sd.nav.get_collision_geometry(participant_id)` cache. It adopts only completed
snapshots, rebuilds copied circle/segment/polygon primitives only when the
scene/run/static/dynamic revision tuple changes, and refreshes native dynamic
state about every two seconds. Lua recomputes the 48 walkability samples, eight
clearance rays, and eight nearest radius-inflated obstacles against those exact
primitives. Other live participants use their replicated positions and cached
native collision radii; the observing participant is excluded.
`sd.nav.test_segment` remains authoritative only for the learned movement
mask. The older grid snapshot is retained only for coarse scripted arena
bounds and steering, not learned patch/ray observations. Neither path writes a
transform. The loader may apply its
authority-owned, native-placement-validated stuck recovery only after a full
30-second no-progress window.

Each bot asks `sd.bots.get_primary_attack_window(participant_id)` for its own
live class primary. A cast uses
`bot:cast(0, target.x, target.y, 80)`, so Fire, Water, Earth, Air, and Ether all
enter through the same replicated participant-cast ingress. Rejected casts
remain rejected; there is no alternate damage path. Native level-up offers
prioritize the configured element's primary and same-element family before
general upgrades, and the chooser never takes a conflicting elemental
primary.

With no enemies, contexts continue short orbit/anchor movement. That preserves
native movement across spawn gaps and wave transitions rather than stopping
the actor or replacing the stock movement tick.

## Behaviors

### Skirmisher

Skirmisher is the shipped kite-and-cast policy. Enemies inside the configured
kite radius contribute inverse-distance-weighted repulsion, blended with arena
center recovery that cannot reverse through a threat. It casts on a 500 ms
cadence only when an enemy's center is inside the equipped primary spell's
native effective range. Below 35% HP it flees with a 900-unit threat sample and
longer lookahead; it resumes kiting above 45%.

When the nearest enemy sits outside that range, the skirmisher approaches and
stops just inside its live attack window even if the enemy has already entered
the wider kite radius. Long approach destinations are held for one second;
kite and flee destinations retarget every 250 ms.

### Guardian

Guardian selects the nearest living human (`controller_kind == Native`) as its
ward. Its advertised leash is 260 world units; movement destinations are
constrained 30 units inside that boundary, and a context outside the inner
return threshold steers directly toward the ward. Native path validation still
decides whether each return or orbit destination is accepted.

The guardian records enemy distance to the ward on successive think ticks. It
engages only enemies within 380 units whose ward distance is decreasing.
Enemies moving away or merely existing elsewhere in the arena are not cast
targets. The guardian retains the skirmisher's 500 ms cast cadence and
35%/45% flee hysteresis; while actually fleeing, it may evade any nearby enemy
but still does not cast.

### Striker

Striker uses a tighter 240-unit engage range and 220-unit threat radius, casts
on a faster 300 ms cadence, and flees only below 20% HP. It recovers above 30%.
It otherwise uses the same native path checks, class-primary attack-window
lookup, replicated slot-0 cast ingress, and wave-transition movement.

### Learned

Policy v3 captures exactly 1,279 ordered finite values every 100 ms. Positions
1-395 preserve v2 exactly. The appended blocks add three participant-scoped
potion timers; identity, facing, proven telegraphs, and replicated combat
statuses for eight enemies; persisted-target motion/facing; eight exact
obstacles; twelve nearest hostile projectile/area/beam hazards; twelve
count-ranked potion types; seven fixed equipment slots; and nine log-scaled
inventory taxonomy counts. Unknown hostile hazard classes remain present with
`type_known=0`, and counts use `log1p` with saturation at 99.

The main action contract has movement 9, actor-ID-persistent target 9,
mutually-exclusive ability 22, and aim 9 heads. Ability actions are none,
primary, eight secondaries, or one of twelve ranked potion slots. Cast legality
is rebuilt against the target selected on the same decision. Aim is center plus
eight 60-unit compass offsets; homing, beam/cone, self/radial, no-op, and potion
families are center-masked. Health, Mana, and Rejuvenation use the validated
participant-scoped native consumable path. Wizard Chug, Antidote, and Mind
Chug remain observable but are permanently action-masked because no synthetic
native effect path was proven. Custom potions require declared
synthetic-safe `policy_effects`. Equipment remains observation-only.

Each pending native skill generation freezes the full observation plus one
56-value semantic descriptor and mask bit per offered option. Learned mode
scores the variable option set; scripted mode keeps the deterministic v2
selector and its weld preference for A/B runs. Scripted events are tagged and
excluded from choice batches. Training records a main trajectory-v3 stream and
a separate variable-duration choice-event-v3 SMDP stream while retaining the
v2 combat reward formula unchanged.

The strict v3 runtime loads the checked-in 1,279 -> 512 -> 256 artifact and its
9/9/22/9 main heads at mod startup. Pending native skill choices use the same
state trunk plus a shared 128-unit scorer over each 56-value option descriptor.
Lua and Python reject historical v1/v2 artifacts without a shim. Inference
remains local—no Python, GPU, or network service—and all movement, casts,
pickups, and consumable uses continue through native participant rails. See
[`ml-bot.md`](ml-bot.md) for bootstrap, dual-stream PPO/SMDP training, entropy,
temperature, and hot-reload details.

## Diagnostics and acceptance

The mod publishes an address-free `bot_brain_debug` table in its own Lua state.
`bots` is an ordered array matching the roster. Each row reports identity,
participant ID, mode, HP ratio, accepted movement/casts, attack window,
Behavior thresholds, native Discipline, and guardian ward distance. Root
scalar fields mirror the first row for compatibility with the existing
diagnostic readers and the longevity verifier. The root also reports desired,
active, and
capacity-refused counts plus the aggregate status string. Learned rows also
report policy generation, decision count, selected actions/probabilities,
value estimate, target/ability/aim actions, persisted actor ID, choice
generation/option, pickup requests, potion uses, inventory/loadout counts, and
whether the scheduler is using the simulation or fallback wall clock. This is
acceptance telemetry, not a gameplay control API.

The retail host/client combat gate uses the launcher-configured roster and
stock wave schedule. Cast acceptance is diagnostic only; success requires
authoritative enemy HP damage edges linked to the same target after a cast,
and every per-cast target-distance must be inside that cast's native range:

```bash
python3 tools/verify_bot_cast_in_range.py
```

The stock-schedule longevity gate remains:

```bash
python3 tools/verify_lua_bot_brain.py --runs 3
```

The structured-settings gate is:

```bash
python3 tools/verify_mod_settings_lifecycle.py
```

It launches only `ms2-host` and `ms2-client` on UDP ports 49211/49212 with
audio disabled. The live proof covers different elements, native Disciplines,
and Behaviors, strict guardian leash distance, the striker's distinct
threshold/cadence, skirmisher movement, removal plus element respawn, client
list replication and copy isolation, and a numbered slot-exhaustion reload
error with both game processes still responsive. Cleanup targets only the
exact launcher-returned PIDs whose executable paths match the two `ms2`
stages. Evidence is written to
`/mnt/d/codex-evidence/mod-settings-v2-20260727/`.
