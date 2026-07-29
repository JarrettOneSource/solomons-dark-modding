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
  discipline = "arcane",
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
- `discipline`: optional native loadout choice `mind`, `body`, or `arcane`;
  omitted values default to `arcane`.

Humans and bots consume the same configured lobby capacity. Solomon Dark has
four native player slots, so `maxParticipants` may be two through four. If
there is no open seat, `spawn` returns `nil, "lobby full"`; it never clamps the
roster or crashes the game. A later despawn or human departure frees the seat
for the next spawn attempt.

The returned handle stores only the participant ID. Every method resolves
current runtime state, so it cannot retain a stale actor pointer across scene
changes or despawn.

### Mutation

`despawn`, `move_to`, `stop`, and `cast` return `true` when accepted or
`false, error` when rejected. They are host-authoritative. A multiplayer
client receives the bot in `list` and may use all read methods, but mutation
returns `false, "only the multiplayer host can control bots"`.

`move_to(x, y)` submits a destination to the stock player movement tick. The
native placement/collision path remains authoritative. If an authority-owned
bot makes neither meaningful target-distance progress nor waypoint progress
for a rolling 30-second window, the loader's stuck failsafe places it at the
nearest valid circle-placement candidate around the target, clears the stock
walk vector, and replicates the correction. Repath revisions and exhausted
waypoint segments do not reset or fake that progress window.

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

## Semantic loadout details

`sd.bots.get_loadout_details(participant_id)` returns the active native spell
semantics needed by a bot brain without exposing process addresses:

```lua
{
  participant_id = 4097,
  primary = {
    entry_id = 8,
    combo_entry_id = 16,
    build_id = 1000,
    build_id_resolved = true,
    mana_cost = 23.383497,
    mana_cost_resolved = true,
    mana_charge_kind = "per_cast", -- "per_second" or "none" when unresolved
    range_min = 0.0,
    range_max = 326.381989,
    range_resolved = true,
    range_source = "native_selection_pursuit_range",
  },
  secondaries = {
    {
      slot = 1,
      entry_id = 15,
      mana_cost = 75.0,
      mana_cost_resolved = true,
      cooldown_seconds = 1.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = true,
    },
    -- exactly eight rows in slot order
  },
  pending_weld_build_id = 0,
  pending_weld_build_id_resolved = false,
}
```

The numeric values above are one live level-4 example; effective costs vary
with the participant's native progression and stat modifiers.

Unknown participant IDs return `nil`. Empty secondary slots have
`entry_id = -1`; all numeric semantic fields remain present, and every value
that can fail native resolution has a corresponding `*_resolved` flag.
Callers must not infer resolution from a zero value.

Base primary build IDs are normalized to their entry IDs
(`8`, `16`, `24`, `32`, or `40`). Welds retain native build IDs
`1000` through `1009`. A pending Spell Welding offer exposes its
generation-captured build only through `pending_weld_build_id`; the active
primary does not change until option `52` is successfully applied. Existing
loaded welds are reconstructed from the live current-primary state.
If the offer-time build cannot be resolved, bot application of option `52`
fails instead of reading a later, generation-ambiguous `+0x844` value.

Primary and secondary mana values are effective native spend costs. The
primary's charge kind is `per_cast` or `per_second`. Primary observation reads
the already-materialized native stat vector when it is valid. On a revision
cache miss with a stale vector, it may invoke the native primary builder once
while preserving the active spell selection; it never invokes that mutating
builder on each 100 ms observation. Static values are cached by the
participant's `loadout_revision`, `spellbook_revision`, `statbook_revision`,
and `derived_stat_revision` tuple. Profile changes, participant lifecycle
changes, skill application, and successful weld promotion invalidate the
cache.

Per-secondary cooldown state is proven only for Phasing (`15`) and Teleport
(`48`). Their native float counters use 100 ticks per second and are converted
to seconds by this API. Every other secondary reports
`cooldown_resolved = false`; bot policy should then use the participant's
global `cast_ready` state as its readiness fallback. Cooldown counters and the
pending weld are overlaid live rather than frozen in the revision cache.

`sd.bots.get_primary_attack_window(participant_id[, element_id])` remains
available for older brains and delegates to the same primary range producer.
The optional `element_id` argument is accepted for compatibility; the active
build is authoritative. Frost Jet uses its progression-dependent native
damage-query range. Other primaries, including Water-containing welds, use
their actor selection's live pursuit range.

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
    bot = sd.bots.spawn({
      name = "Ember",
      class = "fire",
      discipline = "arcane",
    })
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

The opt-in autonomous implementation and its three-run wave-five gate are
documented in [`lua-bot-brain.md`](lua-bot-brain.md).
