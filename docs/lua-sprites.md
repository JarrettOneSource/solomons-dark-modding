# Runtime sprite atlases with `sd.sprites`

`sd.sprites` lets a Lua mod register its own PNG atlas and reversed Solomon
Dark `.bundle` frame stream without replacing a stock atlas. Registration is
presentation-local: the resulting atlas can be passed directly to
`sd.draw.sprite` and `sd.draw.get_sprite_info`, but it never enters simulation
state or the multiplayer protocol.

## Basic use

```lua
local atlas = sd.sprites.register(
  "portraits",
  "sprites/portraits.png",
  "sprites/portraits.bundle")

sd.events.on("runtime.tick", function()
  sd.draw.sprite(atlas.id, 0, 96, 96, {
    centered = true,
    width = 128,
    height = 128,
  })
end)
```

The public ID is always `mod_id:key`; the example might return
`sample.quest:portraits`. Keys use the same lowercase content-identifier rules
as registered spells, items, and enemies. An owner may register or replace its
key at any time. The loader validates the complete replacement before taking
the registry lock, so a failed replacement leaves the prior atlas intact.

## API

### `sd.sprites.register(key, image, bundle)`

Registers a mod-relative PNG and `.bundle`, or atomically replaces the same
key. It returns:

```lua
{
  id = "sample.quest:portraits",
  key = "portraits",
  image = "sprites/portraits.png",
  bundle = "sprites/portraits.bundle",
  frame_count = 12,
  image_width = 512,
  image_height = 256,
  revision = 7,
  local_only = true,
}
```

Each successful registration receives a new revision. The draw renderer checks
the source path and revision before using its cache, releases an older D3D9
texture, and decodes the new PNG on the next draw. PNG signature, IHDR, bounds,
and frame metadata are checked during registration; the renderer's WIC path
performs the full image decode on first use.

### `sd.sprites.unregister(key)`

Removes the caller's key and returns `true`, or `false` when it was absent.
The ID stops resolving immediately. Its cached managed texture is released by
the renderer on the next D3D9 frame, including when no Lua draw list is active.

### `sd.sprites.get(key)` and `sd.sprites.list()`

`get` returns the same descriptor schema as `register`, or `nil` when the
caller's key is absent. `list` returns the caller's registrations in stable ID
order. These ownership-scoped reads do not expose another mod's filesystem
paths. A known public ID may still be drawn by another mod, just as a stock
atlas name may be shared.

### `sd.sprites.get_limits()`

Returns the enforced public limits:

```lua
{
  atlases_per_mod = 32,
  global_atlases = 128,
  frames_per_atlas = 4096,
  global_frames = 32768,
  relative_path_bytes = 512,
  atlas_id_bytes = 257,
  image_bytes = 67108864,
  bundle_bytes = 16777216,
  image_dimension = 4096,
  frame_geometry = 16384,
}
```

Image width and height are each limited to 4,096 pixels. Logical/content
dimensions and center offsets are bounded to 16,384 pixels in magnitude.
Registered records must be unrotated and their packed rectangle must fit
inside the sibling PNG.

## Asset sandbox

Both paths must be valid UTF-8, relative to the owning mod root, and contain no
`.` or `..` component. Absolute paths, alternate extensions, missing files,
directories, and canonical paths that escape through a symlink or junction are
rejected. Images must end in `.png`; metadata must end in `.bundle`. Assets are
opened only after their canonical path is proven to remain under the mod root.

Unloading or hot-reloading a Lua mod removes all of its registrations and its
active draw frame before closing the `lua_State`. Loader shutdown resets the
registry and releases all renderer resources.

## Bundle format and builder

A normal sprite bundle is a headerless concatenation of common frame records.
Each record has this 45-byte little-endian prefix followed by `point_count`
coordinate pairs:

| Offset | Type | Meaning |
|---:|---|---|
| `0x00` | `float32` | atlas x |
| `0x04` | `float32` | atlas y |
| `0x08` | `float32` | packed width |
| `0x0C` | `float32` | packed height |
| `0x10` | `int32` | logical width |
| `0x14` | `uint32` | logical height |
| `0x18` | `float32` | content width |
| `0x1C` | `float32` | content height |
| `0x20` | `float32` | center offset x |
| `0x24` | `float32` | center offset y |
| `0x28` | `uint8` | rotated; must be `0` for runtime atlases |
| `0x29` | `uint32` | point count |
| `0x2D` | repeated `float32 x, y` | optional point tail |

The draw renderer does not currently consume the point tail, but the shared
reversed parser validates it. `tools/build_lua_sprite_bundle.py` produces this
exact stream from JSON:

```powershell
py -3 tools/build_lua_sprite_bundle.py `
  mods/lua_sprites_lab/sprites/atlas.example.json `
  mods/lua_sprites_lab/sprites/lab.bundle
```

`content_width`, `content_height`, center offsets, and points are optional in
the descriptor. Content dimensions default to the packed rectangle; offsets
default to zero. The disabled `sample.lua.sprites_lab` mod contains a two-frame
descriptor, manual register/draw helpers, and a base64-encoded deterministic
acceptance image. The pair verifier materializes the PNG and bundle only while
staging; normal authors replace those fixtures with their own art.

## Multiplayer and verification

The launcher includes every file under each enabled mod root in that mod's
SHA-256 directory identity, and that identity is part of the multiplayer
compatibility fingerprint. Peers therefore enter a session with byte-identical
PNG and bundle files. `sd.sprites` itself sends no packet; edits made after
staging are local authoring changes and are not synchronized.

The namespace advertises `sprites.local.register` and `sprites.local.read`.
The static contract covers ownership, sandboxing, bounds, lifecycle, renderer
revision handling, content hashing, the builder, sample, and verifier. For a
visual acceptance pass, place a PNG and matching bundle in the first loaded
Lua mod, launch normally, then attach without launching or focusing the game:

```powershell
py -3 tools/verify_lua_sprites.py `
  --image sprites/lab.png `
  --bundle sprites/lab.bundle
```

Frame zero should contain visible pixels that are not magenta. The verifier
registers and re-registers the atlas, exercises rejection paths, draws it over
a magenta acceptance panel, captures the live D3D9 backbuffer, checks the
pixels, and unregisters the temporary key.

For the complete multiplayer-local lifecycle, use a disposable pair:

```powershell
py tools/verify_lua_sprites_multiplayer.py --launch-pair --confirm-mutation
```

The pair verifier decodes the checked-in fixture and builds its bundle only
for the staging window, so the exact mod fingerprint covers identical real
asset bytes on both peers. It proves host-only registration is invisible to
the client, then registers and independently replaces the same semantic atlas
on both peers. Exact descriptor, limit, frame, sandbox, address-exclusion,
draw-lookup, revision-isolation, and unregister behavior are required. The
generated PNG/bundle are removed even on failure. Window tiling and global
process cleanup are disabled, and only the two returned process IDs are
stopped.
