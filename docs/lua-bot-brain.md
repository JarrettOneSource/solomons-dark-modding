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
manager prefers, avoids, or automatically accepts Spell Welding. Learned rows
decide every 100 ms of simulation time once matching v2 weights are installed.

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
`sd.nav.get_grid(4)` cache, adopts only completed snapshots about every two
seconds, and computes its 48 walkability samples and eight clearance rays in
Lua. `sd.nav.test_segment` remains authoritative only for the learned movement
mask. Neither path writes a transform. The loader may apply its
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

Policy v2's learned runtime is bundled. Every 100 ms it
can capture exactly 395 ordered finite values: self state; dynamic primary and
eight-secondary descriptors; eight enemies with actor-ID velocity history;
the persisted target; cached local geometry; four pickups; the four nearest
in-run allies plus a cap-independent ally count; and aggregate, history, weld,
and combat-multiplier values. Target selection is a separate nine-action head.
The cast mask is rebuilt against the target selected on that same decision, so
secondary range/readiness is not constrained by the primary attack window.

The strict 395 -> 192 -> 96 three-head weights run locally in Lua: inference
does not start Python, require a GPU, or contact a model service, and all
movement and casts still use the native participant rails. Historical v1
weights are rejected explicitly rather than reinterpreted.

The shared skill manager sees learned primary progression, pending weld build
IDs, and Spell Welding option 52. In `auto` mode it accepts a weld only after
both component primaries are learned; `prefer` and `avoid` provide explicit
owner control. Learned rows also make rate-limited pickup requests only for
host-owned replicated drops inside the drop's native pickup radius. The
current native bot API still has no owner-safe per-bot consume/equip mutation,
so inventory actions remain out of scope. See [`ml-bot.md`](ml-bot.md) for
player setup, live PPO training, checkpoint replacement, and the versioned
action boundary.

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
value estimate, target action and persisted actor ID, pickup requests,
inventory/loadout counts, and whether the scheduler is using the simulation or
fallback wall clock. This is acceptance telemetry, not a gameplay control API.

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
