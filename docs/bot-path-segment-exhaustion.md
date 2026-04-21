# Bot Path Segment Exhaustion vs Final Arrival

Date: 2026-04-20

Note: this was a real pathing bug, but it was not the full explanation for the
live "sliding" regression. The primary movement-ownership bug for that symptom
is documented in `docs/standalone-bot-stock-tick-drift.md`.

## Symptom

Standalone clone-rail bots in hub follow could:

- visually slide or zig-zag around the player
- appear to have "goofed" speed because heading kept flipping between two local goals
- fail to converge to the requested stop point

Live log signature:

```text
[lua.bots] follow_move ... point=(975.00, 2675.00)
[bots] built path ... first_waypoint=(950.000000, 2650.000000)
...
[lua.bots] follow_move ... point=(975.00, 2675.00)
[bots] built path ... first_waypoint=(975.000000, 2675.000000)
```

The revision churn alternated between same-cell micro-goals, usually `950,2650`
and `975,2675`.

## Mechanical Cause

`UpdateWizardBotPathMotion()` treated "ran out of waypoints" as equivalent to
"arrived at the commanded destination".

That assumption is false.

`TryBuildBotPath()` is allowed to emit waypoint lists that are only local
steering segments:

- same-cell direct paths can emit a traversable in-cell sample instead of the
  raw target
- fallback paths can emit a start-anchor sample
- the final waypoint list therefore does not guarantee that the last waypoint
  equals `binding->target_x/y`

Before the 2026-04-20 fix, this branch fired:

```cpp
if (binding->path_waypoint_index >= binding->path_waypoints.size()) {
    ...;
    multiplayer::StopBot(binding->bot_id);
}
```

If the bot reached the current segment waypoint within the 8-unit final-waypoint
threshold, gameplay called `StopBot()` even when the true destination was still
far away.

That propagated outward as:

1. gameplay set the controller idle too early
2. Lua follow logic observed `bot.moving == false` / `bot.has_target == false`
3. Lua re-issued `move_to()` for the same follow point
4. runtime assigned a new movement-intent revision
5. gameplay rebuilt a fresh one-segment path from the current actor position
6. the rebuilt segment often picked the other same-cell sample
7. the bot zig-zagged forever instead of converging

## Fix

Waypoint exhaustion now only calls `multiplayer::StopBot()` when the actor is
actually within `kWizardBotPathFinalArrivalThreshold` of the true target.

If the current steering segment is exhausted but the actor is still outside the
final target threshold, gameplay now:

- clears the current path segment state
- keeps the high-level movement intent alive
- rebuilds the next segment on the next path-follow tick

Diagnostic log added:

```text
[bots] path segment exhausted ... remaining_distance=... action=rebuild
```

## Invariant

`path_waypoints` describe steering work, not proof of final arrival.

Only `distance(actor, binding->target)` is authoritative for deciding whether a
movement command is complete.
