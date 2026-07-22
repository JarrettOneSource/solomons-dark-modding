# Lua enemy-spawn filter

`sd.events.filter("enemy.spawning", handler)` runs synchronously before the
retail enemy constructor consumes a completed native config. It can rewrite
the proven common construction fields or cancel the spawn while retaining the
stock arena, placement, registration, and wave bookkeeping paths.

## Minimal example

```lua
sd.events.filter("enemy.spawning", function(event)
  return {
    hp = event.hp * 1.5,
    chase_speed = event.chase_speed * 1.1,
  }
end)
```

The opt-in `sample.lua.enemy_spawn_filter_lab` mod applies that rewrite to
owner-simulated enemies.

## Payload

Each handler receives a fresh table containing the outcome of every earlier
handler:

```lua
{
  event = "enemy.spawning",
  native_type_id = 1001,
  arena_address = 12345678,
  config_address = 23456789,
  wave_spawner_address = 34567890, -- nil outside a wave-spawner tick
  hp = 5.0,
  primary_damage = 2.0,
  secondary_damage = 0.0,
  family_values = {2.0, 0.0, 0.0, 0.0},
  chase_speed = 1.0,
  attack_speed = 1.0,
  scale = 1.0,
}
```

`family_values` maps the completed native config fields at
`+0x5C/+0x60/+0x64/+0x68`. The first two are also named
`primary_damage` and `secondary_damage`. The last two are deliberately left
family-dependent: for example, they can be extra damage, poison duration, or
another family-specific scalar. Authors that use them must branch on
`native_type_id`.

Addresses are process-local diagnostics. They are valid only during the
callback and are not stable multiplayer identities.

## Handler results

A handler may return:

- `nil` or `true` to retain the current outcome;
- `false` or `{cancel = true}` to cancel the spawn;
- a patch table containing `hp`, `family_values`, `primary_damage`,
  `secondary_damage`, `chase_speed`, `attack_speed`, or `scale`.

`family_values` is a partial one-indexed table. Named primary and secondary
damage fields are applied afterward and therefore take precedence. All
numeric construction values must be finite and within `0..1,000,000`; scale
must be within `0.01..1,000`. Invalid patches and handler errors are logged and
fail open without discarding earlier valid rewrites.

Handlers execute in stable mod-load order and registration order. Cancellation
is monotonic: later handlers and the retail constructor do not run.

## Native safety and ownership

The filter does not call `Enemy_Create` itself. It intercepts the already legal
retail `0x00469580` call shape after stock code has selected placement and
built the config. Rewritten fields are written transactionally, consumed by
the constructor, and then the shared config is restored so later spawns start
from stock state.

The fixed retail executable has two callers that write `actor + 0x1D0`
unconditionally after construction. Cancellation therefore returns a
loader-owned writable sentinel instead of `nullptr`; the native caller
completes its one cleanup write without materializing or registering an actor.
The sentinel exists only to satisfy that proven return contract.

Enemy filters run in single-player and on the multiplayer authority. They are
skipped on transport clients, where host-authored enemy snapshots and exact
catch-up materialization already carry the outcome. Loader-owned replicated
catch-up spawns also bypass Lua so a client cannot apply the rule twice.

If Lua is already busy, config capture fails, or a partial native write is
successfully restored, the filter fails open. An unrecoverable partial write
fails closed and suppresses that spawn rather than constructing from a
corrupted config.

## Capability and verification

The seam advertises `events.filters.enemy_spawn`.

The live verifier registers two ordered handlers before waves start. It proves
the second sees the first rewrite, confirms the first native actor receives the
rewritten max HP, then cancels later stock spawn attempts without post-spawn
events:

```powershell
py -3 tools/verify_lua_enemy_spawn_filters.py --pipe SolomonDarkModLoader_LuaExec
```
