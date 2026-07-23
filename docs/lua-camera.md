# Local camera control with `sd.camera`

`sd.camera` exposes the stock gameplay camera as a bounded, presentation-local
Lua seam. Mods can inspect the active view, hold its center on a world point,
release that focus, and add shake through Solomon Dark's native feedback path.
It is intended for cutscenes, boss introductions, local spectating, and impact
feedback.

The namespace does not replicate. A mod changes only the camera of the peer on
which its Lua state is running; gameplay positions and authority state are not
modified.

## API

```lua
local camera = sd.camera.get_state()
if camera.scene_available then
  sd.camera.set_focus(640, 360)
  sd.camera.shake(0.1)
  sd.camera.clear_focus()
end
```

The functions are:

- `get_state() -> table`
- `set_focus(world_x, world_y) -> true`
- `clear_focus() -> boolean`
- `shake(intensity) -> true`

Coordinates must be finite and within `-1,000,000` through `1,000,000` world
units. Shake intensity must be finite, greater than `0`, and at most `1`.
Mutation calls fail when no supported native gameplay Region is active.

## State

`get_state()` is safe in menus and returns:

```lua
{
  available = true,
  scene_available = true,
  focus_active = true,
  owns_focus = true,
  origin_x = 320,
  origin_y = 180,
  width = 640,
  height = 360,
  center_x = 640,
  center_y = 360,
  scale = 1,
  shake_magnitude = 0.1,
  shake_accumulator = 0.2,
  focus_x = 640, -- present only while a focus request is active
  focus_y = 360,
}
```

`available` reports whether the native hooks and layout fields resolved.
`scene_available` reports whether a readable native Region is active. Numeric
view fields are zero when it is not. `focus_active` covers requests from any
loaded mod, while `owns_focus` tells the caller whether the selected request is
its own.

Focus is owned per mod. The most recently set request wins, up to 64 owners, so
one mod cannot clear another mod's request. Unloading a mod clears its request.
A scene change discards requests tied to the old Region. After the winning
request is cleared, the next native Region tick resumes stock camera ownership.

## Native boundary

Each supported Region subclass writes its stock view rectangle late in its tick.
The loader hooks those six ticks, invokes the original first, and then translates
the primary, expanded, and culling rectangle origins by the same delta. Keeping
the three rectangles aligned preserves native rendering, culling, and input
projection while centering the requested world point. Width, height, scale, and
stock camera policy remain native-owned; this API deliberately does not expose zoom.

`shake` calls the verified native `Region::ApplyCameraShake` routine. That
routine updates the stock magnitude and accumulator, which the Region tick damps
and the renderer consumes. Lua does not write an invented shake approximation.
The reverse-engineering evidence and exact addresses are recorded in
[`reverse-engineering/native-camera-control.md`](reverse-engineering/native-camera-control.md).

The namespace advertises `camera.local.read`, `camera.local.focus`, and
`camera.local.shake`. The disabled `sample.lua.camera_lab` mod supplies manual
helpers, and `tools/verify_lua_camera.py` validates the contract against an
already-running gameplay Region.
