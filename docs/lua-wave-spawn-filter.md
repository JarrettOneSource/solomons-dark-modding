# Lua wave-spawn filter

`sd.events.filter("wave.spawning", handler)` runs synchronously on the run
authority when a stock wave-spawner action is about to tick for the first
time. It can change that action's remaining enemy count and pacing or cancel
the action entirely.

## Minimal example

```lua
sd.events.filter("wave.spawning", function(event)
  return {
    count = math.min(event.count * 2, 4096),
    spawn_delay = math.floor(event.spawn_delay / 2),
  }
end)
```

The opt-in `sample.lua.wave_spawn_filter_lab` mod doubles each stock spawn
action and accelerates both delay paths.

## Payload

Every handler receives a fresh table containing the result of earlier
handlers:

```lua
{
  event = "wave.spawning",
  wave_index = 1,
  count = 14,
  spawn_delay_remaining = 0,
  spawn_delay = 50,
  wave_delay = 100,
  randomize_spawn_delay = true,
  sequential_groups = false,
  spawner_address = 12345678,
  action_record_address = 23456789,
}
```

One callback represents one native `SPAWN` action, not the whole parsed
`WAVE` block. `count` is the action's remaining spawn budget. `spawn_delay` is
the base per-enemy delay; rewriting it also resets the current countdown so
the new cadence takes effect immediately. `wave_delay` is the action's longer
burst countdown. `randomize_spawn_delay` controls the retail half-delay jitter.
`sequential_groups` reports whether a zero-budget grouped record expanded into
its member counts; it is read-only because changing it without rebuilding the
group cursors would violate the stock traversal contract.

`wave_index` is the live arena combat index. Both addresses are process-local
diagnostics valid only during the callback; never persist or replicate them.

## Handler results

A handler may return:

- `nil` or `true` to retain the current action;
- `false` or `{cancel = true}` to cancel it;
- a partial table containing `count`, `spawn_delay`, `wave_delay`, or
  `randomize_spawn_delay`.

Counts must be integers in `0..4096`. Delay values are native tick counts and
must be integers in `0..1000000`. Returning `count = 0` produces an ordinary
rewrite that later handlers may increase again. Explicit cancellation is
monotonic: later handlers do not run and the action retires with zero budget.

Handlers execute in stable mod-load order and registration order. Each later
handler sees every earlier valid rewrite. Invalid patches and handler errors
are logged and fail open without discarding earlier changes.

## Native seam and safety

The loader uses the existing `WaveSpawner_Tick (0x0046D000)` owner hook.
Ghidra proves the private 0x44-byte spawner stores its action record at `+0x18`,
remaining budget at `+0x20`, current/base spawn delay at `+0x24/+0x28`, long
delay at `+0x2C`, and random/sequential policy bytes at `+0x30/+0x31`.

The filter claims the live `(spawner, action record)` pair before the stock
tick, so an action is dispatched exactly once even when its timers keep the
object alive across many frames. Immediately after the original tick, the
claim is removed when the object changes identity or its budget reaches zero.
This matters because zero-delay stock actions can drain and retire in one call
and the allocator may reuse their address.

Writes are transactional. A partial write restores the original spawner
fields. If restoration itself fails, the loader sets the remaining budget to
zero so the stock tick retires the inconsistent action. Successful rewrites
are intentionally not restored: these fields belong to this one spawner and
the native tick must consume the modified schedule.

Cancellation writes zero budget and still invokes the original tick. The
stock virtual completion path therefore advances and releases the action; the
loader never strands a timeline object or manually constructs an enemy.
Composition selection, config construction, placement, actor registration,
enemy-count bookkeeping, and replication all remain native.

The filter runs only in an active solo run or on the multiplayer authority.
Transport clients already suppress their authoritative wave spawner and apply
host-authored enemy snapshots, so they never dispatch this filter or roll the
same wave twice.

## Capability and verification

The seam advertises `events.filters.wave_spawn`.

```powershell
py -3 tools/verify_lua_wave_spawn_filter_contract.py
```

The live verifier expects a settled disposable `testrun` staged with
`tests/fixtures/waves/lua_wave_filter_test.txt`. It proves ordered count/pacing
rewrites create the exact extra stock enemies, kills the first wave, then
cancels the second action and proves no additional enemy appears:

```powershell
py -3 tools/verify_lua_wave_spawn_filters.py --pipe SolomonDarkModLoader_LuaExec
```
