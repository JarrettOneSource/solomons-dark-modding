# Lua timer scheduler

`sd.timer` schedules local, per-mod Lua callbacks without requiring each mod to
subscribe to `runtime.tick` and maintain its own clock. The namespace advertises
the `timer.local.scheduler` capability.

## API

```lua
local id = sd.timer.after(delay_ms, callback)
local id = sd.timer.every(interval_ms, callback)
local id = sd.timer.sequence({
  { delay_ms = 100, callback = function() print("first") end },
  { delay_ms = 250, callback = function() print("second") end },
})
local cancelled = sd.timer.cancel(id)
local cleared_handle_count = sd.timer.clear()
```

`after` accepts an integer delay from 0 through 86,400,000 milliseconds and
runs once. `every` accepts an integer interval from 1 through 86,400,000
milliseconds and repeats until canceled or until its callback raises an error.

`sequence` accepts 1 through 64 steps and returns one handle for the whole
sequence. Each `delay_ms` is relative to completion of the preceding step. The
cumulative delay may not exceed 86,400,000 milliseconds. Canceling the handle
cancels all remaining steps.

`cancel` returns `true` only when the handle was still scheduled. `clear`
cancels every handle owned by the calling mod and returns the number of handles
it canceled.

## Scheduling and limits

The scheduler uses the same monotonic millisecond clock and game-thread pump as
`runtime.tick`. Due timer callbacks run before that mod's explicit
`runtime.tick` handlers. A timer created by a callback or tick handler cannot run
until a later tick, even when its delay is zero.

Repeating timers schedule their next invocation from the current tick instead
of replaying missed intervals. This prevents catch-up bursts after a stall.
Each mod may retain at most 256 scheduled callbacks, including remaining
sequence steps, and at most 64 callbacks are invoked for one mod in one tick.
An uncaught callback error is logged with the owning mod ID and cancels the
remaining timer or sequence.

Timer handles and callback references belong to one Lua state. They cannot be
used across mods and are released when that mod unloads.

## Multiplayer

Timers are local meta-runtime behavior and are never replicated. They are safe
for presentation work such as HUD animation, audio cues, and local UI. A timer
must not independently decide shared simulation outcomes on every peer. Put
shared values in `sd.state`, make simulation changes through owner-routed APIs,
or trigger an authority-side filter/event and let its result replicate.

The opt-in `sample.lua.timer_lab` mod demonstrates one-shot, repeating, and
sequenced callbacks.

For the complete multiplayer-local lifecycle, use a disposable pair:

```powershell
py tools/verify_lua_timer_multiplayer.py `
  --launch-pair `
  --confirm-scheduling
```

The pair verifier first removes the sample's startup timers, then schedules
different labeled suites on host and client. It proves one-shot, repeating,
sequence, callback-created, canceled, and callback-error behavior without
cross-peer state, followed by independent `clear` results. The host also fills
all 256 callback slots while the client retains its own timer, rejects the
257th callback, and releases the full local capacity. Invalid delay, callback,
sequence, and handle shapes are rejected. Window tiling and global process
cleanup are disabled, and only the two returned process IDs are stopped.
