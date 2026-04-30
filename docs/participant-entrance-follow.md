# Participant Entrance Follow

This document describes how Lua-controlled participants follow the player across
the shared hub, private hub interiors, and runs.

## Goal

Hub and private-interior following should behave like participant travel, not
instant scene mirroring. A bot should walk to the appropriate hub entrance,
follow the same transition shape the player uses, and materialize in the
destination scene through the participant scene-intent model.

Coordinated run starts are different: the party can be promoted directly into
the run scene once the stock run transition reaches a stable `testrun` tick.

## Runtime Model

The Lua bot policy uses the participant scene contract from
`docs/multiplayer-participant-model.md`:

- `shared_hub`
- `private_region`
- `run`

For hub and private interiors, Lua owns travel policy. The DLL exposes primitive
facts and actions: scene state, pathfinding movement, participant scene intent,
and gameplay materialization. The DLL should not decide when a bot waits,
regroups, enters, or exits.

## Same-Scene Follow

The current Lua follow band lives in `mods/lua_bots/scripts/lib/app.lua`:

- stop distance: `100` units
- resume distance: `250` units
- when the bot is already following, it closes to a traversable point inside the
  follow band
- once stopped, it waits until the player moves beyond `250` units
- if the player walks into the bot, the bot does not back away

Before issuing `sd.bots.move_to`, the Lua policy snaps the chosen target to the
nearest traversable nav-grid sample. Requested spawn/materialization transforms
are also sanitized in the loader against the live path/collision grid.

## Hub And Private Travel

When the player enters a private hub region, Lua should:

1. Resolve the target private region.
2. Move the bot to the matching hub-side entrance or staging anchor.
3. Arm the transition only after the bot has crossed the expected outside-to-
   inside path shape.
4. Update the bot scene intent to `private_region`.
5. Let gameplay rematerialize the participant in the destination.

When the player returns to the hub, Lua performs the reverse transition and sets
the scene intent back to `shared_hub`.

Run entry uses the existing pending run promotion: `run.started` latches the
promotion, and the Lua policy completes it from the next stable `testrun` tick.

## Measured Anchors

Current measured stock player positions from the live harness:

- `memorator`
  - interior arrival: `(512.0, 798.25897216797)`
  - hub return: `(87.480285644531, 443.60046386719)`
  - bot staging point: `(75.0, 375.0)`
- `dowser`
  - interior arrival: `(537.5, 647.73309326172)`
  - hub return: `(627.5, 137.6875)`
  - provisional bot staging point: `(675.0, 75.0)`
- `polisher_arch`
  - interior arrival: `(512.0, 867.88549804688)`
  - hub return: `(952.5, 106.6875)`
  - bot staging point: `(825.0, 75.0)`
- `librarian`
  - interior arrival: `(512.0, 924.0)`
  - provisional hub-side anchor before entry: `(124.76531219482, 496.97552490234)`
  - bot staging point: `(75.0, 525.0)`

`librarian` is still a stock-client instability case rather than a normal
entrance-follow target. Keep its exception behavior tracked in
`docs/bugs/librarian-region-switch-instability.md`.

## Implementation References

- `mods/lua_bots/scripts/lib/app.lua` owns the travel policy, same-scene follow
  band, entrance anchor table, run promotion latch, and active bot set.
- `mods/lua_bots/README.md` documents the public sample-mod behavior and bot
  configuration surface.
- `SolomonDarkModLoader/include/multiplayer_runtime_state.h` defines scene
  intent and participant profile types.
- `SolomonDarkModLoader/src/bot_runtime/public_api/scene_intents_api.inl`
  exposes scene-intent helpers to the bot runtime.
- `SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_scene_context.inl`
  maps scene intent to the live scene context during materialization decisions.

## Known Runtime Boundaries

- `librarian` can raise first-chance access violations even with the Lua bot mod
  disabled; treat that as stock-client region-switch work.
- Multi-participant region switching has a separate crash edge tracked in
  `docs/bugs/multi-participant-region-switch-instability.md`.
- Entrance anchors are measured constants today. If the game exposes typed
  entrance objects later, the Lua policy should consume those instead of fixed
  coordinates.
