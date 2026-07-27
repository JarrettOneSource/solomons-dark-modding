# Lua multiplayer bot players

`sd.bots` creates host-owned synthetic remote participants. A bot has a
participant identity, persona name, stock gameplay slot, and stock player
actor. It is not a standalone helper actor. The normal multiplayer participant
rail therefore supplies hostile targeting, ally HUD, damage, death/corpse
presentation, and peer replication.

## Handle API

```lua
local bot, err = sd.bots.spawn({
  name = "Ember",
  class = "fire",
})
assert(bot, err)

bot:move_to(900, 500)
bot:stop()
bot:cast(0, 1050, 500)       -- class primary
bot:cast(2, 1050, 500, 250)  -- belt slot 2, 250 ms hold

local x, y = bot:position()
local hp = bot:hp()
local max_hp = bot:max_hp()
local alive = bot:alive()
local slot = bot:slot()
local participant_id = bot:participant_id()

for _, current in ipairs(sd.bots.list()) do
  print(current:participant_id(), current:alive())
end

bot:despawn()
```

`spawn` accepts:

- `name`: a nonempty persona name of at most 31 bytes.
- `class`: `fire`, `water`, `earth`, `air`, or `ether`.

The returned handle stores only the participant ID. Every method resolves
current runtime state, so it cannot retain a stale actor pointer across scene
changes or despawn.

### Mutation

`despawn`, `move_to`, `stop`, and `cast` return `true` when accepted or
`false, error` when rejected. They are host-authoritative. A multiplayer
client receives the bot in `list` and may use all read methods, but mutation
returns `false, "only the multiplayer host can control bots"`.

`move_to(x, y)` submits a destination to the stock player movement tick. The
native placement/collision path remains authoritative; this call does not
teleport.

`stop()` clears the destination and movement intent.

`cast(skill_slot, target_x, target_y[, hold_ms])` uses the replicated
participant-cast ingress:

- slot `0` selects the class primary;
- slots `1` through `8` select belt entries;
- primary casts emit pressed, optional held, and released phases;
- `hold_ms` defaults to 80 and must be between 0 and 5000; and
- the target coordinates become the wire aim/cursor coordinates.

The host derives the participant/session/run identity, origin, heading,
profile, resolved skill, and monotonic cast sequence. The same cast packet is
played on every peer. A dead or unmaterialized bot cannot move or cast.

### Inspection

`position()` returns `x, y` or `nil, error`.

`hp()` and `max_hp()` return the latest authoritative values or `nil, error`.

`alive()` returns true only while the participant is materialized with
positive HP. It returns `false` for the standard death/corpse state.

`slot()` returns the peer-local stock gameplay slot, 1 through 3, or `nil`
while the participant is not materialized. Slot numbers may differ across
peers; the participant ID is the cross-peer identity.

`participant_id()` returns the stable synthetic participant ID as a Lua
integer.

`sd.bots.list()` returns handles for active synthetic participants in
participant-ID order.

## Brain tick

Bot brains use the existing runtime event service. Do not create a native
thread or a second AI pump:

```lua
local bot
local elapsed_ms = 0

sd.events.on("runtime.tick", function(event)
  elapsed_ms = elapsed_ms + (event.delta_ms or 0)
  if elapsed_ms < 250 then
    return
  end
  elapsed_ms = 0

  if not bot then
    bot = sd.bots.spawn({name = "Ember", class = "fire"})
  elseif bot:alive() then
    local x, y = bot:position()
    if x then
      bot:move_to(x + 80, y)
    end
  end
end)
```

The host is the only process that should run simulation decisions. Clients
receive the resulting participant state, transforms, casts, spell effects,
vitals, and death epochs.

## Lifecycle and multiplayer boundary

Each bot is registered as `RemoteParticipant` with controller `LuaBrain`, a
synthetic session nonce, and the transport host as authority. The stock
gameplay-slot actor is materialized through the same participant entity
synchronizer used by real remote peers.

On the host, the stock actor runs movement, collision, cast handlers, damage,
and death. Its state and transform are published on the normal participant
state/frame streams. A client authenticates synthetic participant packets only
from its configured host and runs the ordinary packet-driven remote-player
presentation path.

Despawn publishes a reliable retirement tombstone before removing local state.
Late frames and casts from the retired session epoch are rejected.

The older flat `sd.bots.create/update/cast/...` functions remain available for
mechanics and diagnostic tooling. New player-facing mods should use
`spawn`/`list` and handles.

## Acceptance

`tools/verify_lua_bot_players.py` owns the isolated local-UDP acceptance:

```bash
python3 tools/verify_lua_bot_players.py --phase lifecycle
python3 tools/verify_lua_bot_players.py --phase control
```

It uses the `bot` instance prefix, ports 48811/48812, and audio-disabled
staging. Lifecycle acceptance covers member identity, stock slots, avatars,
ally HUD, native hostile targeting, retirement, and both-peer parity. Control
acceptance covers the complete handle contract, collision-aware move/stop,
Fire cast/effect/damage convergence, native damage into the bot, standard
death epoch/corpse presentation, and hostile retargeting.

