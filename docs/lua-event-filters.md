# Lua mutable event filters

`sd.events.filter` is the synchronous rules-engine side of the Lua event API.
Unlike `sd.events.on`, which observes a queued notification after simulation,
a filter runs inside the native owner seam before the outcome is committed. A
filter may leave the outcome unchanged, rewrite it, or cancel it.

Implemented filter families are:

- `damage.dealing`
- `damage.taken`
- `enemy.spawning`

Both execute at the stock `PlayerActor::MagicDamage` resolution point. The
loader runs every `damage.dealing` handler first, then every `damage.taken`
handler. This gives source-oriented rules a stable phase before target-oriented
rules without executing the native hit twice.

## Minimal example

```lua
sd.events.filter("damage.taken", function(event)
  local rewritten = {}
  for index, value in ipairs(event.lanes) do
    rewritten[index] = value * 0.75
  end
  return {lanes = rewritten}
end)
```

The opt-in `sample.lua.damage_filter_lab` mod applies that 25 percent reduction
to all nine native damage lanes.

## Registration and ordering

```lua
local registered = sd.events.filter(name, handler)
```

`name` must be one of the supported mutable filter names and `handler` must be
a function. Registration returns `true`. Registrations are permanent for that
mod's current Lua state; hot reload or process restart creates a fresh state.

Handlers execute in stable mod-load order and then registration order. Each
handler receives the result of every preceding rewrite. Cancellation is
monotonic: the loader stops the chain and never invokes the stock damage
handler.

`sd.events.filter` is intentionally separate from `sd.events.on`. Registering a
filter does not register a post-hit notification, and filter callbacks are not
queued.

## Damage payload

Every damage handler receives a new table:

```lua
{
  event = "damage.taken",
  source_participant_id = 123, -- nil when no participant owns the actor
  target_participant_id = 456, -- nil when no participant owns the actor
  source_actor_address = 12345678,
  target_actor_address = 23456789,
  flags = 0,
  projectile_damage = 12.0,
  magic_damage = 4.0,
  total_damage = 16.0,
  lanes = {12.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0},
}
```

The first two entries in `lanes` are the stock projectile and magic lanes. The
remaining seven are preserved because the retail damage context is a
contiguous nine-float record and native modifiers use more than the two named
lanes. `total_damage` is the arithmetic sum of the current nine lanes.

Actor addresses are process-local diagnostics for tooling and comparisons
inside the current callback. They are not stable IDs and must never be stored
in `sd.state` or sent to another peer. Participant IDs are the stable identity
when the actor belongs to a known player or bot.

## Handler results

A handler may return:

- `nil` or `true` — keep the current outcome unchanged;
- `false` — cancel the hit;
- `{cancel = true}` — cancel the hit;
- a patch table containing `projectile_damage`, `magic_damage`, or `lanes`.

`lanes` is a partial one-indexed table. Nil entries retain the current value.
Named `projectile_damage` and `magic_damage` fields are applied after `lanes`,
so they take precedence when both forms target lane 1 or 2.

```lua
sd.events.filter("damage.dealing", function(event)
  return {
    lanes = {[3] = event.lanes[3] + 2},
    magic_damage = event.magic_damage * 1.5,
  }
end)
```

Every replacement must be finite and within `-1,000,000..1,000,000`. The
loader validates a patch transactionally; an invalid field rejects the entire
patch. Handler errors and invalid results are logged with the owning mod ID and
fail open, leaving the outcome from earlier handlers unchanged.

## Owner and multiplayer behavior

Damage filters run only after the existing wizard-damage authority gate. In a
hosted session the host resolves incoming wizard hits; a client runs the seam
only for its explicitly owner-authoritative poison tick. Non-owning client hits
are rejected before Lua executes. The rewritten or canceled outcome therefore
happens once and ordinary participant vitals replication carries the result to
the other peers.

The callback is synchronous native simulation work. It must return promptly
and cannot yield. If the hook re-enters while the Lua engine is already busy,
the loader skips filters and fails open instead of deadlocking. A failed native
context capture also fails open. Native lane writes are transactional; a
partial write is restored before stock simulation continues, and an
unrecoverable restore cancels and resets the context.

## Capability and verification

The damage seam advertises `events.filters.damage`. The enemy construction
seam advertises `events.filters.enemy_spawn`; its payload, owner rules, and
native cancellation contract are documented in
[lua-enemy-spawn-filter.md](lua-enemy-spawn-filter.md). A mod should list the
capabilities it depends on in `runtime.requiredCapabilities`.

The live verifier must run against a disposable game process because filter
registrations last for the life of the Lua state. It invokes the retail damage
handler after Lua returns, proves two ordered rewrites change actual HP loss,
and then proves cancellation leaves HP unchanged:

```powershell
py -3 tools/verify_lua_damage_filters.py --pipe SolomonDarkModLoader_LuaExec
```

Drop and wave filters remain separate roadmap slices; this document does not
promise those names before their owner seams ship.
