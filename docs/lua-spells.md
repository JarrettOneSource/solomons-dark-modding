# Lua scripted spells

`sd.spells` owns deterministic identities, immutable metadata, owner-routed
casting, and bounded replicated scripted effect lifecycles for primary and
secondary spells. Native picker and player-input integration remain separate
work.

## Registration

Registration is allowed only while the owning mod's entry script is loading:

```lua
local gravity_well = sd.spells.register({
  key = "gravity_well",
  slot = "secondary",
  cfg = {
    name = "Gravity Well",
    description = "Draw nearby enemies toward a collapsing field.",
    mana_cost = 30,
    cooldown_ms = 1200,
    duration_ms = 2400,
    tick_interval_ms = 50,
    radius = 180,
  },
  on_cast = function(context)
    return {
      key = "field",
      x = context.aim_x,
      y = context.aim_y,
      radius = context.cfg.radius,
      lifetime_ms = context.cfg.duration_ms,
      data = {hits = 0},
    }
  end,
  on_tick = function(effect)
    return {radius = math.max(0, effect.radius - 1)}
  end,
  on_hit = function(effect, target)
    return {data = {hits = effect.data.hits + 1}}
  end,
})
```

`key` uses the shared `sd.content.v1` identity. `slot` is `primary` or
`secondary`. `on_cast` is required; `on_tick` and `on_hit` are optional. The
loader retains callback references in the owning Lua state and never returns
those functions from `get` or `list`.

`cfg` is copied into the loader's bounded Lua value representation, so later
mutation of the source table cannot change the registered definition. Its
accepted fields are:

| Field | Contract |
|---|---|
| `name` | required, 1–96 text bytes |
| `description` | optional, 1–1024 text bytes |
| `mana_cost` | optional finite number, 0–1,000,000 |
| `cooldown_ms` | optional integer, 0–3,600,000 |
| `duration_ms` | optional integer, 0–3,600,000 |
| `tick_interval_ms` | optional integer, 1–60,000 |
| `radius`, `range`, `speed` | optional finite numbers, 0–1,000,000 |

Unknown registration or config fields fail instead of being ignored. A mod may
register at most 256 spells.

## Lookup

```lua
local own = sd.spells.get("gravity_well")
local any = sd.spells.get(own.id)
local all = sd.spells.list()
```

Descriptors contain `id`, `mod_id`, `key`, `slot`, a fresh `cfg` copy, and
`has_on_cast`/`has_on_tick`/`has_on_hit`. They contain no Lua registry index,
native skill ID, config address, actor address, or function value. The
capabilities are `spells.register`, `spells.read`, and `spells.effects.read`.

## Owner-routed casting

`sd.spells.cast(key_or_id, options)` queues `on_cast` on the selected wizard's
simulation owner. A client may select only itself; the host may also select a
connected remote participant. Offline casts execute locally. Protocol 77 sends
host commands reliably with authority, owner, request, and content identities;
the receiving owner authenticates the host and deduplicates the request.

```lua
local result = sd.spells.cast("gravity_well", {
  participant_id = 123, -- optional; defaults to the local participant
  target_network_actor_id = 456, -- optional semantic target
  origin_x = 100,
  origin_y = 200,
  aim_x = 300,
  aim_y = 400,
})
```

The result contains `request_id`, `content_id`, `owner_participant_id`, and
`local_owner`. The callback receives those identities plus the slot, origin,
aim, normalized direction, optional target network ID, and a fresh `cfg` copy.
The `spells.cast.owner` capability is available with the gameplay pump.

## Scripted effects

`on_cast` returns `nil`, one effect descriptor, or an array of at most 16
descriptors. Each descriptor accepts exactly `key`, `x`, `y`, `velocity_x`,
`velocity_y`, `radius`, `lifetime_ms`, and `data`. Position defaults to the aim
point, radius and timing default to `cfg`, and `data` must fit the 128-byte wire
budget. A mod may own at most 128 live effects.

The owner integrates velocity and invokes `on_tick(effect)` at the configured
interval. When an effect overlaps a live tracked enemy, `on_hit(effect, target)`
fires once for that actor. Effect and target payloads contain semantic IDs and
values, never native addresses. Both callbacks may return `nil`/`true` to keep
the effect, `false` to retire it, or a patch containing `x`, `y`, `velocity_x`,
`velocity_y`, `radius`, `data`, and optional `done = true`. Invalid callbacks
are logged and leave the last valid effect state intact.

## Replicated effect snapshots

`sd.spells.get_effects()` returns the local owner's live effects together with
the latest complete snapshots from remote owners. Every row contains
`effect_id`, `request_id`, `content_id`, `owner_participant_id`, `key`, `x`,
`y`, `velocity_x`, `velocity_y`, `radius`, `age_ms`, `remaining_ms`, `data`,
and `local_owner`. The API is address-free and does not create a native actor;
mods can use the semantic state to present an effect with `sd.draw`.

Protocol 77 carries at most 256 logical effects, four effects per fragment,
with deterministic content and owner identities. The owner publishes the
snapshot; a host authenticates and relays remote-owner fragments. A completed
generation replaces that owner's previous generation atomically, and an empty
retirement snapshot removes its final effects. Incomplete snapshots never
become visible, stale generations are rejected, and a remote snapshot expires
after 1.5 seconds without a refresh. The publishing cadence starts at 50 ms and
is bandwidth-limited to 128 KiB/s of logical snapshot payload.

Only transform, timing, identity, and the bounded 128-byte `data` value cross
the network. `on_cast`, `on_tick`, and `on_hit` callbacks continue to run only
on the simulation owner; remote peers consume presentation state and never
replay gameplay behavior.

## Current boundary

The definition is callable from Lua and its generic content-ID-based effect snapshot channel
is available to every peer, but it is not yet selectable in the native skill
picker or bound to native player input.

The disabled-by-default `sample.lua.spells_registry_lab` mod registers a
`gravity_well` definition and its bounded field lifecycle. It never casts on
its own.
