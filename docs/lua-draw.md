# Lua immediate-mode drawing

`sd.draw` is the loader-owned, presentation-local drawing API. `sd.hud` is an
exact alias of the same table. A mod submits a display list from its
`runtime.tick` handler, and the loader draws that list over the next D3D9
frames until the mod completes another tick.

Drawing is local and never enters the multiplayer transport. It is therefore
safe to call from the same mod on every peer. Use replicated `sd.state` values
or an `sd.events.broadcast` handler when the information being displayed must
be synchronized.

## Minimal example

```lua
sd.events.on("runtime.tick", function()
  sd.draw.rect(20, 20, 260, 72, {
    color = {r = 12, g = 18, b = 32, a = 220},
  })
  sd.draw.rect(20, 20, 260, 72, {
    filled = false,
    thickness = 2,
    color = {r = 90, g = 190, b = 255, a = 255},
  })
  sd.draw.text("Local Lua HUD", 34, 36, {
    scale = 1.25,
    color = {r = 255, g = 255, b = 255, a = 255},
  })
end)
```

The opt-in `sample.lua.hud_showcase` mod demonstrates text, rectangles, lines,
stock sprites, viewport queries, and a player-anchored marker.

## Frame contract and limits

The command-producing functions may only be called while that mod's
`runtime.tick` handlers are running. Each mod owns an independent pending and
active display list. A completed tick atomically replaces the active list; a
tick that submits no commands clears the old list. One slow mod cannot consume
another mod's allowance, and lists are rendered in stable mod-load order.

- 512 commands per mod per completed runtime tick
- 16 KiB of text bytes per mod per completed runtime tick
- 1,024 bytes per text command
- stock atlas names are limited to the 28 canonical names and 32 bytes;
  registered `mod_id:key` IDs are limited to 257 bytes

`sd.draw.get_limits()` returns these public bounds. Invalid arguments and
limit overruns raise a Lua error in the calling handler. The loader catches
that handler error, logs it with the owning mod ID, and still completes the
mod's display-list swap.

## Coordinates, colors, and text

Screen coordinates are pixels with `(0, 0)` at the viewport's upper-left.
Coordinates must be finite and within `-1,000,000..1,000,000`. Rectangle and
sprite extents must be positive and at most 8,192 pixels. Line and outline
thickness is `1..64` pixels.

Colors use an optional `{r, g, b, a}` table. Each channel is an integer from
0 through 255; omitted channels default to 255. Alpha blending uses source
alpha over the current backbuffer.

The built-in text atlas covers printable ASCII (`32..126`) plus newline and
tab handling. Other bytes render as `?`. `scale` defaults to `1` and accepts
`0.1..16`.

## API

### `sd.draw.text(text, x, y[, options])`

Queues text at the screen position. Options:

- `scale` — glyph scale, default `1`
- `color` — RGBA channel table

Returns `true` after the command is accepted.

### `sd.draw.rect(x, y, width, height[, options])`

Queues a filled or outlined rectangle. Options:

- `filled` — default `true`; set `false` for an outline
- `thickness` — outline thickness, default `1`
- `color` — RGBA channel table

Returns `true` after the command is accepted.

### `sd.draw.line(x1, y1, x2, y2[, options])`

Queues a line segment. Options are `thickness` and `color`. A zero-length
segment renders as a square with the requested thickness.

### `sd.draw.sprite(atlas, record, x, y[, options])`

Queues one zero-based record from a stock `.bundle` atlas or a runtime atlas
registered through [`sd.sprites`](lua-sprites.md). The loader parses the bundle
metadata and uploads the sibling PNG into a managed D3D9 texture on first use.
The default size is the record's logical canvas; trimmed content retains its
native offset within that canvas.

Options:

- `width`, `height` — output logical-canvas size
- `centered` — when `true`, `(x, y)` is the canvas center; default `false`
- `color` — texture tint and alpha

Atlas names are ASCII case-insensitive and canonicalize to one of:
`BadGuys`, `Bonedit`, `Clothes`, `College`, `ControlPanel`, `Controls`,
`Create`, `DeadHawg`, `Demon`, `Faculty`, `Fonts`, `GameOver`, `Golem`,
`Heartmonger`, `Inventory`, `LevelPicker`, `Library`, `Loader`,
`Memoratorium`, `NPCs`, `Office`, `Skills`, `Solomon`, `SolomonRiff`,
`Storage`, `Title`, `UI`, or `Unholy`.

All 10,498 records in the retail 0.72.5 bundles are unrotated. A rotated record
is deliberately rejected rather than rendered with incorrect geometry.
Registered IDs use their exact case-sensitive `mod_id:key` spelling and are
also required to contain only unrotated records.

### `sd.draw.get_sprite_info(atlas, record)`

Returns the decoded metadata table for either a stock or registered atlas, or
`nil, error` for an unknown atlas or out-of-range record:

```lua
{
  atlas = "Title", record = 9,
  atlas_x = 806, atlas_y = 128,
  packed_width = 829, packed_height = 395,
  logical_width = 829, logical_height = 395,
  content_width = 829, content_height = 395,
  center_offset_x = 0, center_offset_y = 0,
  rotated = false,
}
```

The numeric values above illustrate the fields; callers should query them
rather than depending on documentation examples.

### `sd.draw.get_viewport()`

Returns `{width, height}` after the renderer has observed a D3D9 frame. Before
that point it returns `nil, error`.

### `sd.draw.world_to_screen(x, y[, z])`

Projects a gameplay-world point through the live viewport and world/view/
projection state captured from the PlayerWizard scene pass. `z` defaults to
zero. On success it returns:

```lua
{
  x = 640.0,
  y = 360.0,
  visible = true,
  viewport_width = 1280,
  viewport_height = 720,
  generation = 42,
}
```

An offscreen point can still return coordinates with `visible = false`. A
point behind the camera, or a call before a gameplay projection is available,
returns `nil, error`. Mods should treat unavailable projection as an ordinary
presentation state and skip that marker for the tick.

## Capabilities

The renderer advertises:

- `draw.local.immediate`
- `draw.text`
- `draw.primitives`
- `draw.stock_sprites`
- `draw.world_projection`

Loader startup fails instead of advertising these capabilities when the D3D9
frame seam cannot be installed. Renderer resources are local, rebuilt after a
device change, and bracketed by a full D3D9 state capture/restore so Lua draw
commands do not leak state into the game or the debug overlay.

## Verification

Use the disposable pair verifier for presentation-local multiplayer semantics:

```powershell
py tools/verify_lua_draw_multiplayer.py --launch-pair
```

It stages only `sample.lua.hud_showcase`, checks the exact namespace, limits,
viewport, stock sprite metadata, and tick-only submission rule on both peers,
then gives host and client distinct labels and coordinates. Host-only
activation, independent client activation, and independent deactivation prove
that draw handlers and their command production remain local to each process.
Window tiling and global process cleanup are disabled; only the two process IDs
returned by this launch are stopped.

Actual D3D9 output remains a separate rendered-window gate:

```powershell
py tools/verify_lua_draw.py
```

That verifier captures the game backbuffer and requires exact text, primitive,
stock-sprite, and world-projection pixels. Run it only when a normal rendered
game window may be used; the semantic pair verifier does not claim pixel coverage.
