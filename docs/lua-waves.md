# Lua wave intelligence

`sd.waves` is the read-only semantic view of the active Boneyard wave and the
effective staged `data/wave.txt` schedule. It exposes no spawner, arena, action
record, actor, or other process address.

The namespace is available when these capabilities are present:

- `waves.read`
- `waves.schedule.read`

## Live state

```lua
local wave = assert(sd.waves.get_state())

print(wave.wave)               -- 0 while idle, otherwise 1-based
print(wave.phase)              -- idle, spawning, clearing, or completed
print(wave.planned)
print(wave.remaining_to_spawn)
print(wave.spawned)
print(wave.alive)
print(wave.killed)

for _, row in ipairs(wave.composition) do
  print(
    row.enemy_type,
    row.planned,
    row.spawned,
    row.alive,
    row.killed
  )
end
```

Every composition row has this shape:

```lua
{
  enemy_type = 1001,
  planned = 12,
  spawned = 7,
  alive = 5,
  killed = 2,
}
```

The aggregate `spawned`, `alive`, and `killed` fields are the sums of the same
fields in `composition`. `remaining_to_spawn` is read from the authority's live
native spawner. A wave moves through these phases:

1. `spawning` while the native spawner still has budget.
2. `clearing` once the budget is empty but attributed enemies remain alive.
3. `completed` once the budget and attributed live-enemy count are both zero.

Enemies spawned by the manual test spawner or by unrelated child effects are
not attributed to a wave. Stock enemies created inside `WaveSpawner_Tick` are
attributed to that exact spawner identity, so overlapping spawners do not mix
their counters.

## Schedule preview

`sd.waves.get_schedule(n)` accepts an integer from `1` through `64`. It returns
up to `n` entries after the current wave; while idle, it begins with wave 1.

```lua
for _, entry in ipairs(sd.waves.get_schedule(3)) do
  print(
    entry.wave,
    entry.spawn_budget,
    entry.spawn_delay_min,
    entry.spawn_delay_max,
    entry.wave_delay_min,
    entry.wave_delay_max,
    entry.max_enemies,
    entry.zombie_wave
  )
  for _, row in ipairs(entry.composition) do
    print(row.enemy_type, row.planned)
  end
end
```

The loader parses the effective staged `data/wave.txt`, after mod overlays have
been applied. Missing files, malformed ranges, unknown enemy tokens, empty
waves, and unsupported composition sizes fail Lua-engine initialization with a
line-specific error instead of exposing a partial schedule.

### What `planned` means

`SPAWN` is an exact total budget. Retail random `GROUP` selection does not
define an exact future per-type sequence, and asking the native spawner for one
would consume gameplay RNG. The framework therefore projects the budget across
the configured enemy entries with deterministic largest-remainder rounding.
The projection always sums exactly to `spawn_budget`; ties are ordered by
numeric enemy type. `random_group_projection = true` makes this explicit on
each schedule entry.

If `wave.spawning` changes the authority's initial count, the live wave's
planned composition is rescaled to that effective count. Actual `spawned`,
`alive`, and `killed` values then replace prediction with observation without
rewinding or sampling native RNG.

## Events

`wave.started` now includes the planned aggregate and composition:

```lua
sd.events.on("wave.started", function(event)
  print(event.wave, event.planned)
  for _, row in ipairs(event.composition) do
    print(row.enemy_type, row.planned)
  end
end)
```

`wave.completed` retains its existing `{ event, wave }` payload.

## Multiplayer

Wave simulation remains authority-owned. The host copies the bounded summary
into its authenticated participant frame. A client accepts it only from the
configured authority endpoint and session identity, validates row order and
all aggregate totals, and then replaces its local semantic view. Participant
frames also provide the late-join checkpoint, so `sd.waves.get_state()` returns
the same authority summary on host and clients without requiring a Lua mod to
replicate anything.

The packet carries at most 20 sorted composition rows. The parser recognizes
the eight stock wave-file enemy tokens recovered from the retail schedule; it
does not infer wave syntax from unrelated native object classes. The protocol version is 74;
incompatible peers are rejected during the normal handshake.

## Read-only verification

With an already-running loader instance, this probe checks capabilities,
aggregate invariants, schedule ordering, argument rejection, and the absence
of raw addresses without starting waves or changing the scene:

```powershell
python tools/verify_lua_waves.py
```

Use `--pipe` for a non-default Lua exec pipe.
