# Lua spell-cast filter

`sd.events.filter("spell.casting", handler)` runs synchronously before an
owner-simulated primary or secondary spell reaches the retail cast handler. It
is a cancellation seam: it can keep or reject the attempted cast, but it does
not rewrite the selected native skill.

```lua
sd.events.filter("spell.casting", function(event)
  if event.kind == "primary" and magazine == 0 then
    return false
  end
end)
```

The opt-in `sample.lua.spell_cast_filter_lab` mod cancels the first local or
Lua-brain primary cast after the mod loads and allows later casts.

## Payload

Each handler receives a new table:

```lua
{
  event = "spell.casting",
  caster_participant_id = 123, -- nil in solo when no stable participant exists
  caster_actor_address = 12345678,
  kind = "primary",           -- "primary" or "secondary"
  skill_id = 1003,
  secondary_slot = nil,       -- zero-based when an owner bot request supplies it
  x = 512.0,                  -- nil when the native field is unreadable
  y = 384.0,
  direction_x = 1.0,
  direction_y = 0.0,
  target_actor_address = nil,
  aim_target_x = 640.0,
  aim_target_y = 384.0,
}
```

Actor addresses are process-local diagnostics. Use `caster_participant_id` for
stable identity and do not persist or broadcast an actor address. Position,
direction, and aim fields are snapshots of the authoritative native actor just
before the cast. Unreadable or implausible native aim coordinates are omitted.
Aim values supplied by a bot request take precedence over stale actor fields.

## Handler results

A handler may return:

- `nil` or `true` to keep the cast;
- `false` to cancel it;
- `{cancel = true}` to cancel it.

Handlers execute in stable mod-load order and registration order. Cancellation
is monotonic: later handlers and the stock cast routine do not run. A handler
error, invalid result, or a busy Lua engine is logged and fails open.

## Cast identity and native behavior

A local primary is filtered at the player-tick input boundary before stock can
consume the left-button cast intent. The decision runs once per physical or
injected press and is cached while that press drives held-cast ticks, so a
canceled continuous spell stays canceled and an allowed one is not repeatedly
charged through Lua. Only the two cast-input bytes are masked around a canceled
stock tick; movement and the rest of the player tick continue, and both bytes
are restored immediately afterward. The dispatcher repeats the cached decision
for primary variants that reach it. Local secondaries filter once at the native
secondary entry.

Lua-brain bot casts filter once when the owning simulation consumes the queued
cast request, before it primes actor state or invokes the dispatcher. A canceled
bot request returns the bot to idle, retires the cast-only facing override,
clears its native control state, and skips the one retail actor tick that could
otherwise turn the already-authored facing vector into a one-shot action. The
actor keeps its current visual heading, and the next frame resumes the ordinary
idle tick. The retail dispatcher remains responsible for all allowed effects,
mana, cooldowns, action state, and existing replication.

## Multiplayer ownership

Only the peer simulating the caster runs this filter. The local player's cast
runs on that player's peer; a Lua-brain bot request runs where that bot is
simulated. Native remote replay is explicitly excluded, so a replicated cast
cannot execute the filter a second time on another peer. Canceling prevents the
native outcome and therefore leaves nothing to replicate.

The capability is `events.filters.spell_cast`. The callback is synchronous and
cannot yield.

## Verification

The static contract verifier checks registration, owner gates, held-cast
deduplication, native call ordering, documentation, and sample coverage:

```powershell
py -3 tools/verify_lua_spell_cast_filter_contract.py
```

Live acceptance uses a settled disposable `testrun` with the combat prelude
enabled:

```powershell
py -3 tools/verify_lua_spell_cast_filters.py `
  --pipe SolomonDarkModLoader_LuaExec_<instance>
```

The verifier registers two ordered handlers and first exercises the local Fire
primary. Cancellation must invoke each handler exactly once, preserve 100 MP
for 1.75 seconds, leave the primary/action latches and native cast/target
handles idle, and create no `0x7D4` Fireball. The allowed local press must invoke
each handler once more and produce native mana or Fireball evidence. It then
repeats the same cancel/allow matrix with fresh Fire bots, including bot request
retirement and cleanup. Both matrices passed on 2026-07-22.
