# Lua scripted spells

`sd.spells` owns deterministic identities and immutable metadata for scripted
primary and secondary spells. The catalog checkpoint deliberately establishes
identity and callback ownership before cast routing, picker presentation, and
generic effect replication are attached to it.

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
    -- Owner-side cast dispatch is the next spell checkpoint.
  end,
  on_tick = function(effect)
  end,
  on_hit = function(effect, target)
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
capabilities are `spells.register` and `spells.read`.

## Current boundary

This checkpoint does not yet make the definition selectable or invoke its
callbacks. The remaining spell seam is explicit: owner-routed cast dispatch,
native/player input and skill-picker integration, callback scheduling and
collision, and a generic content-ID-based effect lifecycle replicated to every
peer. Until that lands, the catalog is an identity and authoring contract, not
a cast API.

The disabled-by-default `sample.lua.spells_registry_lab` mod registers a
`gravity_well` definition without performing gameplay mutation.
