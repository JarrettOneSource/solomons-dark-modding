# Autonomous Lua bot-brain roster

`mods/bot-brain/` is the opt-in reference brain for host-owned synthetic
participants. Its host-scoped `roster` list contains zero to three ordered rows:
name, element (`fire`, `water`, `earth`, `air`, or `ether`), and discipline
(`skirmisher`, `guardian`, or `striker`). The mod is disabled by default, so an
ordinary game never gains an unsolicited participant.

The default roster contains one fire skirmisher named `Ember`. The earlier
`persona_name` scalar is gone; names belong to rows. The other launcher
controls remain: 340-unit kite radius, offense enabled, local 250/400 ms think
cadence, local focus key, and the confirmed host-only roster respawn action.

## Ordered reconciliation

`scripts/roster.lua` maintains one `brain.lua` context per list position. At
startup, live reload, and replicated list changes it compares rows by order:

- an unchanged row keeps its participant and behavior state;
- a removed row despawns through its bot handle;
- a new row spawns with that row's name and element; and
- a changed name, element, or discipline despawns and respawns the row.

Retirement uses the reliable participant tombstone path. Creation remains
subject to the three stock remote gameplay slots. If a row cannot claim a
slot, the context remains desired and retries on later authority ticks, while
the immediate settings reload returns an `entry_errors.roster` message naming
the row. A rejection never crashes the mod or game.

The brain never creates a standalone actor, writes an actor transform, or
drives a second native AI loop. All contexts run from `runtime.tick`, and
`sd.state.is_authority()` keeps decisions on the transport host. Clients adopt
read-only handles for focus/diagnostics and receive the normal participant
State, Frame, Cast, and retirement traffic.

## Shared native movement and offense

Every discipline samples `sd.world.get_replicated_actors()` and keeps live
`tracked_enemy` rows. Candidate destinations come from short steering
lookaheads clamped to the current arena. Every candidate must pass
`sd.nav.test_segment` before `bot:move_to`; there is no Lua grid fallback or
teleport.

Each bot asks `sd.bots.get_primary_attack_window(participant_id)` for its own
live class primary. A cast uses
`bot:cast(0, target.x, target.y, 80)`, so Fire, Water, Earth, Air, and Ether all
enter through the same replicated participant-cast ingress. Rejected casts
remain rejected; there is no alternate damage path. Native level-up offers
prefer Health Up. Fire bots retain the shipped Fireball, Explode, then Embers
fallback order; other elements otherwise take their first stock option.

With no enemies, contexts continue short orbit/anchor movement. That preserves
native movement across spawn gaps and wave transitions rather than stopping
the actor or replacing the stock movement tick.

## Disciplines

### Skirmisher

Skirmisher is the shipped kite-and-cast policy. Enemies inside the configured
kite radius contribute inverse-distance-weighted repulsion, blended with arena
center recovery that cannot reverse through a threat. It casts on a 500 ms
cadence. Below 35% HP it flees with a 900-unit threat sample and longer
lookahead; it resumes kiting above 45%.

When enemies sit outside both threat and class-primary range, the skirmisher
approaches the nearest enemy and stops just inside its live attack window.
Long approach destinations are held for one second; kite and flee destinations
retarget every 250 ms.

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

## Diagnostics and acceptance

The mod publishes an address-free `bot_brain_debug` table in its own Lua state.
`bots` is an ordered array matching the roster. Each row reports identity,
participant ID, mode, HP ratio, accepted movement/casts, attack window,
discipline thresholds, and guardian ward distance. Root scalar fields mirror
the first row for compatibility with the existing wave-five verifier. This is
acceptance telemetry, not a gameplay control API.

The existing retail-schedule longevity gate remains:

```bash
python3 tools/verify_lua_bot_brain.py --runs 3
```

The structured-settings gate is:

```bash
python3 tools/verify_mod_settings_lifecycle.py
```

It launches only `ms2-host` and `ms2-client` on UDP ports 49211/49212 with
audio disabled. The live proof covers two different elements/disciplines,
strict guardian leash distance, the striker's distinct threshold/cadence,
skirmisher movement, removal plus element respawn, client list replication and
copy isolation, and a numbered slot-exhaustion reload error with both game
processes still responsive. Cleanup targets only the exact launcher-returned
PIDs whose executable paths match the two `ms2` stages. Evidence is written to
`/mnt/d/codex-evidence/mod-settings-v2-20260727/`.
