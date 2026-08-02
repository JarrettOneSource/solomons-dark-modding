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

### Bot loot pickup

`sd.world.request_loot_pickup(network_drop_id[, participant_id])` keeps its
one-argument local-player form. On a local-transport host, the optional
`participant_id` may name an active Lua-controlled synthetic participant:

```lua
local accepted, sequence_or_error =
  sd.world.request_loot_pickup(network_drop_id, bot:participant_id())
```

The second form is semantic and address-free. It rejects non-bots, inactive
participants, clients, stale run/drop identities, and drops absent from the
host snapshot. An accepted queue request still passes through the existing
host pickup arbitration: the participant's live derived pickup range,
position, drop kind, deactivation, reward credit, result publication, and
run/drop exactly-once ledger remain authoritative. Callers should correlate
the returned request sequence with `last_pickup_result` from
`sd.world.get_replicated_loot()`.

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

## Semantic inventory details

`sd.bots.get_inventory_details(participant_id)` joins replicated inventory,
equipment, stable content identity, the pinned stock item catalog, and live
native consumable timers:

```lua
{
  participant_id = 4097,
  run_nonce = 1234,
  inventory_revision = 7,
  equipment_revision = 2,
  descriptors_resolved = true,
  damage_x4_remaining_seconds = 0.0,
  poison_immunity_remaining_seconds = 0.0,
  all_concentration_remaining_seconds = 0.0,
  timers_resolved = true,
  potions = {
    {
      stock_subtype = 0,
      content_id = 0,
      identity_key = "stock:potion:health",
      count = 3,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = true,
      restores_hp_fraction = 1.0,
      restores_mana_fraction = 0.0,
      damage_multiplier = 1.0,
      cures_poison = false,
      poison_immunity_duration_seconds = 0.0,
      concentrates_all = false,
      effect_duration_seconds = 0.0,
    },
  },
  equipped = {
    -- hat, robe, weapon, ring_1, ring_2, ring_3, amulet
  },
  summary = {
    item_total_count = 0,
    potion_count = 0,
    equipment_count = 0,
    sack_count = 0,
    misc_count = 0,
    perk_count = 0,
    map_count = 0,
    registered_custom_count = 0,
    unknown_count = 0,
    wizard_key_count = 0,
  },
}
```

Potion rows are ranked by count descending, then stable `identity_key`; Lua
policy uses at most the first 12. Stock identity is subtype-based. Custom
identity uses `content_id` and the registered mod/key when locally resolved;
peer-local native subtype and live item UID are never exposed. Every
replicated `inventory_items` row now also carries its stable `content_id`.
`wizard_key_count` counts non-stacking Item_Misc type-7012/subtype-1 rows;
it does not trust or sum their stack values.

Each of the seven equipment rows contains `slot`, `present`, `identity_key`,
`recipe_name`, `catalog_index`, `catalog_resolved`, `rarity_id`, `level`,
`set_complete`, four aggregate effect magnitudes, optional target kind/ID/
magnitude, and `special_feature_present`. Unknown/generated identities stay
present with `catalog_resolved = false`; callers must not infer missing
effects.

Static descriptors are cached by
`(run_nonce, inventory_revision, equipment_revision, derived_stat_revision,
statbook_revision)`. The three live timer fields are overlaid on every call.
They are native 100-Hz counters converted to seconds.

### `sd.bots.use_consumable(participant_id, selector)`

The simulation authority may consume one ranked potion for a living
Lua-controlled synthetic participant:

```lua
local details = assert(sd.bots.get_inventory_details(bot:participant_id()))
local ok, result_or_error = sd.bots.use_consumable(
  bot:participant_id(),
  {
    potion_slot = 1,
    inventory_revision = details.inventory_revision,
  })
```

On success the second result contains `{use_id, inventory_revision,
stock_subtype, content_id}`. The selector is generation-safe: a changed
inventory revision or ranking is rejected. The authority reserves exactly one
stack and advances the revision before routing the native effect; the same
selector cannot apply twice. The revised synthetic inventory snapshot and
custom use event are reliable and peer-coherent. Errors are semantic and never
include addresses or native exception codes.

Synthetic stock action support is deliberately narrower than observation:

| Subtype | Potion | Learned synthetic use |
|---:|---|---|
| 0 | Health | yes, participant-scoped native health delta |
| 1 | Mana | yes, participant-scoped native mana delta |
| 2 | Wizard Chug | no; observation-only |
| 3 | Antidote | no; observation-only |
| 4 | Mind Chug | no; observation-only |
| 5 | Rejuvenation | yes, the two proven native vital paths |

Subtypes 2 through 4 have only local-player or direct-field stock paths in the
recovered binary. They are not emulated. A custom potion is actionable only
when its registration declares nonempty `policy_effects` with
`synthetic_safe = true`; otherwise it remains observable and masked off.

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
