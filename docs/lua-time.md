# Shared simulation time with `sd.time`

`sd.time` provides bounded slow motion, pause, and frame-step control without
rewriting the game's native tick-frequency conversion global. It gates complete
simulation frames at the verified actor-world boundary, so nested player-actor
and wave-spawner ticks make the same advance-or-hold decision.

The namespace controls simulation only. Lua timers continue to use the loader's
monotonic game-thread clock, and local UI, drawing, camera, and audio presentation
are not slowed. That separation lets a paused mod keep accepting UI actions and
call `step` or `set_scale(1)`.

## API

```lua
local effective = sd.time.set_scale(0.25)
assert(effective <= 0.25)

sd.time.set_scale(0)
local step_sequence = sd.time.step()    -- one complete simulation frame
sd.time.step(5)                         -- up to 120 queued frames

local scale = sd.time.get_scale()
local state = sd.time.get_state()
sd.time.set_scale(1)                    -- release this mod's request
```

The functions are:

- `get_scale() -> number`
- `get_state() -> table`
- `set_scale(scale) -> effective_scale`
- `step(frames = 1) -> step_sequence`

Scale is fixed-point from `0` through `1`, with a resolution of `0.000001`.
`0` pauses, values below `1` decimate complete native simulation frames, and
`1` releases the calling mod's request. Values above `1` are rejected because
the verified gate can safely hold a native frame but cannot synthesize extra
native frames.

Requests are retained per mod and the effective scale is the minimum active
request. One mod therefore cannot accidentally resume another mod's pause or
slow-motion effect. Unloading a mod releases its request, and every run boundary
resets all requests to normal speed.

`step` is available only when the caller itself holds a zero-scale request. A
call accepts 1–120 frames, and at most 120 unconsumed frames may be queued. Menu
pause and level-up synchronization take precedence: step tokens remain queued
until those independent shared pauses release.

## State

`get_state()` returns:

```lua
{
  scale = 0.25,
  paused = false,
  revision = 7,
  step_sequence = 3,
  pending_steps = 0,
  replicated = false,
  authority_participant_id = 7656119,
  run_nonce = 1234,
  maximum_step_frames = 120,
  scale_resolution = 0.000001,
  requested_scale = 0.25, -- nil when this mod has no request
}
```

On a multiplayer client, `replicated` is true and `requested_scale` is nil.
Client mutation calls fail; clients may only inspect the authority's effective
state.

## Multiplayer contract

Offline play and the multiplayer host are simulation authorities. Only they may
call `set_scale` or `step`. Protocol 82 repeats the authority's scale and
revision in normal state checkpoints and participant frames, so late joiners
converge without replaying historical steps.

Every change also produces a prompt reliable `LuaTimeControl` packet containing
the host participant identity, current host session nonce, run nonce, revision,
effective scale, and a cumulative frame-step sequence. Receivers accept it only
from the configured authority endpoint with the current authority session and
run identities. Repeated or stale revisions do not enqueue a step twice.

Steam sends control packets with reliable no-Nagle delivery. The local UDP
backend remains a development transport: repeated scale snapshots converge, but
an individual frame-step datagram can be lost like any other UDP message.

The host and each owner peer apply the same fixed-point frame-decimation rule.
They need not enter the allowed frame on the same wall-clock millisecond;
existing authority snapshots remain the convergence source for shared world
state.

## Native boundary

The value at `kGameTimingScaleGlobal` remains untouched. Reverse engineering
shows it is a `100.0` ticks-per-second conversion constant with multiplication
and division users, not a coherent speed multiplier. `sd.time` instead opens one
scoped decision in `HookActorWorldTick`. Held frames still invoke player hooks
through the existing player-only pause path so Lua and replication pumps remain
responsive, while stock player simulation, non-player actors, and wave spawning
stay frozen.

The namespace advertises `time.shared.scale` and
`time.shared.frame_step`. The disabled `sample.lua.time_lab` mod exposes manual
helpers, `tools/verify_lua_time.py` validates the live API on an already-running
active run.

`tools/verify_lua_time_multiplayer.py --launch-pair` stages the exact time lab
on an isolated host/client pair and enters a shared run.
It proves client mutation is rejected. It then requires the host's slow-motion,
pause, and three-frame step revisions to converge on the client with the exact
authority participant, run nonce, scale, and cumulative step sequence. It
separately proves that the resume revision and normal scale converge; ordinary
snapshots omit historical step sequences by design. Cleanup must restore normal
speed.
It stops only the exact processes launched by the verifier.

The static contract checks the native gates, bounds, authentication,
replication, lifecycle cleanup, documentation, and both live verifier paths.
