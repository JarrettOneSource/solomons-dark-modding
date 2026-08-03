# Native Lua world rendering

`sd.world.sprite` submits mod-owned sprites to Solomon Dark's native world
render queue. `sd.world.marker` submits actor/target labels to the stock-style
native post-scene indicator pass. Use sprites for item drops, world-anchored VFX, and any mod sprite
whose position is part of the 2.5D scene. The stock queue interleaves each
sprite with actors and props by world Y plus `sort_bias`; the stock Puppet
dispatcher also applies scene culling and light tint before the sprite draw.

Screen-space UI remains separate. Top-left HUD rows, `BOT PLAYING`, loading
screens, and other viewport-fixed mod presentation belong to
[`sd.draw` / `sd.hud`](lua-draw.md). The loader-owned Boneyard picker is the
one native exception: it uses stock ExactText and quads at the whole-HUD tail.
Projecting a world point and then using `sd.draw.sprite` still produces an
overlay and is not a substitute for this API.

Actor-attached names, health bars, and target markers are world-anchored but
are not scene sprites. Stock's tutorial loot arrow establishes their native
idiom: project the target and draw after the scene. Use `sd.world.marker` for
that class instead of projecting into `sd.draw`.

## Example

Register the atlas during mod load, then submit its display list from each
`runtime.tick`:

```lua
local atlas = sd.sprites.register(
  "ground_marker",
  "sprites/ground_marker.png",
  "sprites/ground_marker.bundle")

sd.events.on("runtime.tick", function()
  local player = sd.player.get_state()
  if player then
    sd.world.sprite(atlas.id, 0, player.x + 48, player.y, {
      width = 32,
      height = 32,
      offset_y = -16,
      sort_bias = 0,
    })
  end
end)
```

The display list is local presentation state. A completed tick atomically
replaces the previous list, and submitting no commands clears it. Each peer
must submit the sprite from the same semantic replicated state when it should
appear in multiplayer; no native address or render command is transmitted.

## `sd.world.sprite(atlas, record, x, y[, options])`

`atlas` is a stock atlas name or a registered `mod_id:key` atlas ID. `record`
is its zero-based unrotated bundle record. `x` and `y` are gameplay-world
coordinates and form the sprite's sorting anchor.

Options:

- `width`, `height` — logical canvas dimensions; default to the bundle record
  dimensions and must be positive and at most 16,384.
- `offset_x`, `offset_y` — local visual offset from the world anchor; neither
  changes ordering.
- `sort_bias` — added to world Y by the stock queue's ordering calculation;
  use it only when matching a stock actor or prop whose native renderer uses a
  nonzero bias.

The call returns `true` after admission. Coordinates must be finite and within
`-1,000,000..1,000,000`; `sort_bias` is bounded to
`-16,384..16,384`. Rotated bundle records are rejected. The limits are 256
sprites per mod and 2,048 total active sprites per completed tick.

The anchor determines occlusion: an actor at larger world Y normally renders
later and covers the sprite; an actor at smaller world Y renders earlier and
is covered by it. Visual offsets move only the pixels, not the anchor. Lighting
comes from the native scene at the anchor rather than from an authored tint.

## `sd.world.marker(label, x, y[, options])`

Queues a native post-scene cross and half-scale ExactText label at world
coordinates `x`, `y`. The marker follows the stock tutorial indicator: it
draws above the completed scene, stays a constant screen size, and does not
inherit tile lighting. `options.color` uses integer `r`, `g`, `b`, and `a`
channels from 0 through 255.

The label must contain 1 to 64 bytes. Marker and sprite commands share the
same 256-command per-mod and 2,048-command global frame limits. The call is
valid only during `runtime.tick` and returns `true` after admission.

## Compatibility and capabilities

This namespace extends the existing `sd.world` table; existing world-query
methods are unchanged. The advertised capability is `world.render.native`.
`sd.draw` and `sd.hud` retain their existing screen-space behavior and limits.
