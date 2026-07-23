# Lua navigation queries

`sd.nav` exposes the loader's player-sized native path and collision probes without the raw
addresses returned by `sd.debug`. It is a read-only gameplay surface for path previews,
placement-aware tactics, and Lua AI planning.

Capability: `nav.read`.

## API

### `sd.nav.get_grid([subdivisions]) -> table|nil`

Requests a gameplay-thread refresh and returns the latest valid grid snapshot. The first
call after a scene load can return `nil`; retry from a later `runtime.tick`. `subdivisions`
defaults to `1` and must be an integer from `1` through `4`.

The loader compares the snapshot's internal world identity with the live local player before
returning it. A snapshot from a scene that is unloading or has just been replaced returns
`nil`; raw identity addresses never cross into Lua.

Snapshots are rebuilt at most once every 500 milliseconds. If an older snapshot is returned
while the requested sampling density is queued, `refresh_pending` is `true`; retry until it
is false.

The returned table contains:

- `width`, `height`, `cell_width`, and `cell_height`;
- `probe_x` and `probe_y`, the local player position used for the snapshot;
- `subdivisions`, `requested_subdivisions`, and `refresh_pending`;
- `cells`, an array of `{grid_x, grid_y, center_x, center_y, traversable,
  path_traversable, samples}`; and
- per-cell `samples`, each containing `{sample_x, sample_y, world_x, world_y,
  traversable}`.

No process, world, controller, actor, or cell-list addresses are part of the public table.

### `sd.nav.test_segment(from_x, from_y, to_x, to_y) -> boolean`

Synchronously tests a world-space segment against the current native path grid and the same
placement rules used by the loader's bot navigation. All coordinates must be finite 32-bit
numbers. The function raises a Lua error when there is no live local player/world or the
native grid cannot be read; an ordinary blocked route returns `false`.

```lua
local player = sd.player.get_state()
if player then
  local can_stand_here = sd.nav.test_segment(
    player.x, player.y,
    player.x, player.y)
  print("native placement accepted", can_stand_here)
end

local grid = sd.nav.get_grid(2)
if grid and not grid.refresh_pending then
  print("cells", #grid.cells)
end
```

## Native behavior and multiplayer

Both calls are read-only and execute locally. Placement samples use the live player's native
collision radius/masks plus the recovered static-circle and participant-obstacle rules;
segment tests use the same grid traversal and placement checks as bot path smoothing. The
result is not replicated because each peer can safely query its local copy of the shared
scene.

## Acceptance

With a loader-started game in a live arena, run:

```powershell
py -3 tools/verify_lua_nav.py
```

The verifier waits for an exact subdivision-2 refresh, checks the cell/sample shape and raw
address exclusion, exercises a native segment query, and confirms invalid densities fail.

For the complete multiplayer-local contract, use a disposable pair:

```powershell
py tools/verify_lua_nav_multiplayer.py --launch-pair --confirm-mutation
```

The pair verifier stages only `sample.lua.nav_lab`, enters one isolated run, and
requires exact host/client capability, namespace, authority, participant, scene,
and recursive address-free schema evidence. Each peer independently rebuilds a
subdivision-2 native snapshot and executes the local player-sized segment path;
the verifier requires identical shared grid geometry without requiring dynamic
local traversal counts to match. Invalid densities and non-finite coordinates
must fail on both peers. Window tiling and global process cleanup are disabled,
and only the two process IDs returned by this launch are stopped.
