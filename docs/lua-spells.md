# Lua scripted spells

`sd.spells` owns deterministic identities, immutable metadata, local input
selection, owner-routed casting, and bounded replicated scripted effect
lifecycles for primary and secondary spells. Mods build their visual catalog
picker from the native-authored `sd.ui` controls.

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
capabilities are `spells.register`, `spells.read`, `spells.effects.read`, and
`spells.select.local`.

## Local selection and native input

Selection is a peer-local input preference. It never writes stock unlock bytes,
skill rows, or belt contents:

```lua
sd.spells.select("custom_primary")
sd.spells.select("gravity_well", 3) -- belt slot 3

local selected = sd.spells.get_selection()
print(selected.primary and selected.primary.cfg.name)
print(selected.secondary[3] and selected.secondary[3].cfg.name)

sd.spells.clear_selection("primary")
sd.spells.clear_selection("secondary", 3)
```

A primary definition accepts no belt slot. A secondary definition requires a
one-based slot from 1 through 8. String keys resolve only within the calling
mod; a positive content ID may select any loaded registered definition so a
shared picker can operate on the complete catalog. `get_selection()` returns a
primary descriptor when selected and a sparse `secondary` array keyed by belt
slot. Selection disappears when its owning mod unloads.

While selected, the loader consumes the stock primary click or exact live belt
binding before stock dispatch. It captures the local actor's semantic origin,
aim, and target, then queues the registered cast through the same owner-routed
path as `sd.spells.cast`. A rejected cast does not fall through to the stock
spell hidden beneath that input slot.

Player-input casts enforce `cfg.cooldown_ms` locally and spend
`cfg.mana_cost` through the native player mana writer. Insufficient mana or an
active cooldown consumes the input without casting. If owner routing rejects
the request after mana was spent, the loader refunds the observed native
delta. `cfg.range` supplies the forward aim distance when neither a semantic
target nor cursor-world placement is available.

The selection itself is not replicated. Every participant selects its own
input bindings, and the resulting cast runs on that participant's simulation
owner. Direct `sd.spells.cast` calls are explicit simulation commands and do
not consult local selection, input cooldowns, or player mana.

## Owner-routed casting

`sd.spells.cast(key_or_id, options)` queues `on_cast` on the selected wizard's
simulation owner. A client may select only itself; the host may also select a
connected remote participant. Offline casts execute locally. Protocol 82 sends
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
This generic content-ID-based effect snapshot channel is shared by every
registered definition.

Protocol 82 carries at most 256 logical effects, four effects per fragment,
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

## Authored picker and native boundary

Registered definitions are selectable and bound to native primary/belt input.
There is deliberately no fixed framework catalog widget: a mod enumerates
`list()`, creates local `sd.ui` buttons, and calls `select()` or
`clear_selection()` from presentation callbacks. The disabled sample implements
that complete picker path for Gravity Well.

The stock `SellSpell` surface headed `Select a Spell` remains an acquisition
dialog for eight fixed native unlock flags, not a runtime loadout picker;
reusing it would couple mod content to permanent stock progression. Its verified
boundary is documented in `spell-picker-re.md`.

The disabled-by-default `sample.lua.spells_registry_lab` mod registers a
`gravity_well` definition and its bounded field lifecycle, then presents a
native-authored local picker that equips or clears belt slot 1. It never casts
on its own.

## Live acceptance

Enable only `sample.lua.spells_registry_lab`, launch through the normal staged
launcher, and run:

```bash
py -3 tools/verify_lua_spells.py
```

The named-pipe exec target is the first loaded Lua mod, so the isolated sample
launch makes the verifier execute in the picker owner's state. It validates the
registry and selection contracts, activates the visible picker's
`equip_gravity_well` and `clear_gravity_well` buttons through `sd.ui.perform`,
waits for both presentation callbacks, and leaves belt slot 1 clear. The
programmatic action is accepted only while that owned authored surface is
visible. Run `tools/verify_lua_ui_authoring.py` in the same rendered session for
pixel-level D3D9 backbuffer evidence of the native-authored renderer.

For the simulation and replication acceptance, use a disposable local pair:

```powershell
py tools/verify_lua_spells_multiplayer.py --launch-pair --confirm-mutation
```

The pair verifier stages only `sample.lua.spells_registry_lab`. It proves that
selection remains peer-local, a client cannot cast for the host, a host-owned
cast runs only on the host, and a host command for the client runs only on that
client owner. Each observer must receive exactly one address-free remote effect
with the same content, request, effect, owner, transform, callback-produced
data, and owner-ticked radius. The verifier witnesses that remote effect near
the end of its lifetime, then requires the explicit empty retirement snapshot
before the 1.5-second stale-snapshot expiry could remove it. Cleanup clears only
the verifier's selection and stops only the exact processes it launched.
