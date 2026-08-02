# Native world-render seam

## Status and scope

This design cuts loader-owned world sprites out of the D3D9 `EndScene`
overlay and into the stock Arena render queue recovered in
[`world-sprite-render-pipeline.md`](../re/world-sprite-render-pipeline.md).
It covers:

- registered custom potion icons when rendered as inventory glyphs or ground
  drops;
- a bounded Lua seam for general world-positioned mod sprites; and
- the Invincibility Potion's active world VFX.

It does not move screen UI. `sd.draw` and its exact `sd.hud` alias remain the
screen-pixel display-list API used by HUD indicators, the Boneyard picker,
`BOT PLAYING`, developer UI, and loading-screen presentation. Their command
types, coordinates, render state, batching, and multiplayer-local behavior are
unchanged.

## Goals

1. A custom drop occupies the exact native queue slot of its stock drop
   carrier, including stock Y sorting, prop/actor occlusion, culling, and tint.
2. A general mod world sprite uses the same queue insertion formula and common
   Puppet world-render dispatcher as native actors and scenery.
3. Registered PNG atlases enter the game's native texture/glyph batch; no
   world quad is deferred to `EndScene`.
4. The active potion effect uses only its stock `Anim_SpellGlow` lane.
5. Existing published consumable and sprite registration APIs keep working
   without mod changes. The new world-sprite API is additive.
6. Every process derives presentation from its own replicated world state; no
   process address or renderer handle enters the multiplayer protocol.

## Non-goals

- replacing the native world queue or its two-world-unit bucket behavior;
- imposing a new exact-float total order inside a stock bucket;
- transporting generic presentation commands between peers;
- converting screen-space UI into native actors;
- publishing or flipping the Invincibility Potion listing; or
- adding compatibility rendering through the overlay when the native seam is
  unavailable.

The renderer is required when the Lua engine is enabled. Address, hook, or
texture initialization failure fails loader startup instead of falling back to
incorrect overlay behavior.

## Public Lua contract

The existing `sd.world` table gains one function:

```lua
sd.world.sprite(atlas, record, x, y[, options])
```

It queues one sprite for the next committed `runtime.tick` display list.
`atlas` and zero-based `record` use the same stock and registered atlas lookup
as `sd.draw.sprite`. `x` and `y` are native world coordinates at the logical
canvas center.

Options are deliberately limited to native-world geometry and ordering:

- `width`, `height`: logical canvas size; each defaults to the bundle's
  logical dimension;
- `offset_x`, `offset_y`: local visual offset from the world anchor; each
  defaults to zero; and
- `sort_bias`: value written to the stock Puppet `+0xA0` ordering field;
  defaults to zero.

There is no `color` option. A carrier starts with the stock base Puppet's white
tint and the common dispatcher multiplies it by the live local-light scalar.
PNG alpha remains native texture alpha. A future tint feature must compose at
the native object-tint fields; it must not replace the dispatcher color or add
an overlay pass.

Commands are accepted only while the owning mod's `runtime.tick` handlers or
tick-driven timer callbacks are executing. `BeginLuaWorldRenderFrame` and
`CommitLuaWorldRenderFrame` bracket the same dispatch as the existing Lua draw
frame. An empty completed tick clears the prior world list.

Public bounds:

- 256 world sprites per mod frame;
- 2,048 active world sprites across all mod frames;
- finite world coordinates and offsets in `-1,000,000..1,000,000`;
- finite positive dimensions no greater than 16,384; and
- finite sort bias in `-16,384..16,384`.

Invalid metadata, arguments, rotated bundle records, or limit overruns raise a
Lua error in the calling handler. These limits keep carrier creation and queue
insertion bounded on the render thread.

The capability set gains `world.render.native`. Generic commands are
presentation-local, like `sd.draw`: mods submit them on every peer and anchor
them to replicated semantic state. The capability and documentation explicitly
do not imply command replication.

## Runtime command ownership

`lua_world_render_runtime.h/.cpp` owns a mutex-protected structure parallel to,
but separate from, `lua_draw_runtime`:

```text
mod load order
  mod id
    pending LuaWorldSpriteCommand[]
    active LuaWorldSpriteCommand[]
    generation
    accepting_commands
```

Separating the structures prevents world ownership from leaking into
`LuaDrawCommandKind` or `RenderLuaDrawFrame`. The EndScene renderer never sees
a `LuaWorldSpriteCommand`.

At submit time the runtime verifies the atlas record through the shared sprite
metadata parser and stores only semantic values: atlas ID, record index, world
position, dimensions, offset, and sort bias. It stores no game pointer, native
texture handle, or peer-specific identity. Snapshot refresh preserves stable
mod-load order and reuses unchanged generations, matching the established
immediate-mode frame behavior.

Mod unload calls `ClearLuaWorldRenderFrameForMod` before unregistering its
atlases. Lua-engine reset clears all frames. The native renderer treats an
atlas that disappeared or changed revision as unavailable for that frame and
reconciles its cache on the next native flush.

## Native texture bridge

The existing WIC path in `lua_draw_texture_loader.cpp` is split without
changing its D3D9 behavior:

```text
DecodeLuaDrawTextureBgra(path)
  -> width, height, contiguous WIC 32bpp BGRA pixels

LoadLuaDrawTexture(device, path)
  -> DecodeLuaDrawTextureBgra
  -> existing managed D3D9 texture creation/copy
```

The native world renderer reuses only the decoder. On its first native use of
an atlas revision it:

1. resolves the canonical source and revision through
   `TryGetLuaDrawAtlasSource`;
2. decodes contiguous BGRA pixels;
3. enters the stock page critical section at `0x00B3F9DC`, initializing it via
   the stock flag at `0x00B40205` if necessary;
4. calls the native mode-zero uploader at `0x00440F70`;
5. leaves the critical section; and
6. registers a stable loader page record through `0x0041FFE0` on the renderer
   referenced by global `0x00B401A8`.

The cache key is canonical atlas ID plus source revision. A revision change or
unregister releases the prior handle through native `0x00420760`, using the
stock renderer object as `this`. Shutdown removes the queue hook first and
then releases every remaining native handle. The cache owns native handles;
the D3D9 overlay cache continues to own only its managed
`IDirect3DTexture9*` resources.

Native texture operations execute from the game's render thread inside the
queue hook. WIC decode can occur once per revision there; Lua/runtime threads
never call a native D3D texture allocator.

## Native glyph construction

A loader `NativeWorldGlyph` is an opaque, zero-initialized `0xC4` byte record.
Only fields consumed by `Glyph_Draw` are populated:

- validity byte `+0x04`;
- native page handle `+0x08`;
- four local XY pairs `+0x2C..+0x48`; and
- four UV pairs `+0x4C..+0x68`.

The generic geometry is derived from the same bundle fields already used by
`sd.draw.sprite`. With requested logical size `W,H`, scale is the requested
size divided by bundle logical size. The trimmed rectangle is centered in the
logical canvas, adjusted by the bundle center offset, shifted by the command's
local offset, and stored as four local vertices. UVs use native half-texel
insets:

```text
u0 = (atlas_x + 0.5) / atlas_width
v0 = (atlas_y + 0.5) / atlas_height
u1 = (atlas_x + packed_width  - 0.5) / atlas_width
v1 = (atlas_y + packed_height - 0.5) / atlas_height
```

Rotated records remain rejected, consistent with the registered-atlas
contract. Carrier bounds are the minimum/maximum local vertices, so the stock
common dispatcher culls the same visible rectangle that the glyph draws.

### Custom-potion specialization

The potion hook keeps the current registered-subtype detection for the stock
Inventory and World sprite arrays. For a custom subtype it:

1. copies the corresponding stock health-potion `0xC4` glyph record;
2. replaces only its page handle and UVs with the registered mod atlas record;
3. invokes the original `Glyph_Draw` trampoline immediately with the original
   x/y arguments.

Copying the Inventory health glyph preserves stock inventory size and anchor;
copying the World health glyph preserves stock drop grounding. Most
importantly, a ground-drop interception occurs inside the already-sorted stock
drop carrier's virtual renderer while the common dispatcher tint is active.
No second carrier, screen projection, or late queue is involved.

## Generic native carrier

`lua_world_renderer.cpp` hooks queue flush `0x0068C480`. The hook accepts only:

- render pass `0`; and
- the queue whose address equals the live local player's
  `world_address + 0x17C`.

This excludes unrelated renderer queues and non-world passes. For an accepted
flush it snapshots active world commands, resolves their native glyphs, and
assigns one reusable carrier to every renderable command.

Each carrier owns:

- a stock-sized, aligned Puppet byte buffer constructed once through
  `0x006287D0`;
- a private copy of the stock base Puppet vtable;
- its current native glyph;
- four local bounds floats; and
- no registration in an ActorWorld persistent list.

The private vtable keeps stock slot `+0x0C` (`Puppet_RenderDispatch`) and
replaces final draw slots `+0x1C` and `+0x20` with the loader glyph thunk. For
each flush the loader writes position `+0x18/+0x1C`, owner world `+0x58`, sort
bias `+0xA0`, and bounds pointer `+0xC8`. It then calls stock queue insertion
`0x0068C3B0` with `floor(local_player.y)` and pass zero.

Only after every valid loader carrier is inserted does the hook call the
original queue flush trampoline. The stock queue therefore decides the final
interleave. When it reaches a carrier, stock `Puppet_RenderDispatch` performs
culling and light/tint setup, then the patched final draw thunk calls native
`Glyph_Draw` with the carrier position. There is no copied Y-sort formula or
copied lighting calculation in loader code.

Carriers are render-queue entries for one flush only. They are not registered
with ActorWorld, do not tick, do not serialize, and do not acquire gameplay
slots. Their backing memory remains stable while referenced by the queue and
is reused on a later frame only after the original flush returns.

## Potion active VFX cutover

`LuaConsumableNativeVfxRequest`, replicated use identity, participant target
resolution, the 16 ms pulse cadence, four-second lifetime, native
`Anim_SpellGlow` construction, color, and layer `75.0` all remain.

The following overlay-only structures and functions are deleted:

- `LuaConsumableRenderQuad`;
- `QueueLuaConsumableRenderQuad`;
- `TakeLuaConsumableRenderQuads`;
- `BuildCustomPotionWorldQuad`;
- `AppendConsumableActivationBurstQuads`; and
- `QueueConsumableQuad` plus the consumable drain in `RenderLuaDrawFrame`.

The result is one presentation lane: repeated stock `SpellGlow` actors in the
native animation/world pipeline. Both peer processes continue to create the
effect from the authenticated replicated consumable-use event. No wire schema
or mod definition changes.

## Address contract

The executable-specific values are configured in a new `[lua_world_render]`
section of `config/binary-layout.ini`:

| Key | Retail address / value |
| --- | ---: |
| `arena_render_queue_offset` | `0x17C` |
| `render_queue_flush` | `0x0068C480` |
| `render_queue_insert` | `0x0068C3B0` |
| `puppet_ctor` | `0x006287D0` |
| `glyph_draw_at_position` | `0x004143D0` |
| `native_texture_upload_bgra` | `0x00440F70` |
| `native_texture_release` | `0x00420760` |
| `native_render_page_register` | `0x0041FFE0` |
| `native_renderer_global` | `0x00B401A8` |
| `native_texture_critical_section` | `0x00B3F9DC` |
| `native_texture_critical_section_initialized` | `0x00B40205` |

Code resolves addresses through the repository's binary-layout and image-base
helpers. Missing values, non-executable functions, an unavailable renderer,
or a hook-install failure blocks Lua renderer startup. No retail address is
silently duplicated as a C++ fallback.

## Lifecycle and failure behavior

Startup order when Lua is enabled:

```text
InitializeLuaEngine
  initialize draw assets and world-command runtime
  load mods and registered atlases
InitializeLuaWorldRenderer
  resolve/validate native seams
  construct no carriers or textures yet
  install queue-flush hook
InitializeLuaItemNativeHooks
StartLuaDrawRenderer
```

Shutdown removes the world hook before item hooks, Lua state/atlas teardown,
gameplay seams, or binary-layout teardown. It then releases native atlas
handles and carrier storage. Partial-startup failure follows the same order.

Per-atlas and per-command failures are bounded and logged with semantic atlas,
record, and mod identifiers. A failed generic command is omitted from that
flush; it is never sent to the overlay. A custom potion glyph failure is also
not overlaid: the hook logs it and does not call the incomplete stock custom
slot. This keeps the cutover fail-closed.

## Multiplayer contract

This change adds no packet. The authoritative consumable definition, native
subtype/content ID, replicated drop, replicated pickup, and authenticated
consume-use event remain unchanged. Every peer resolves the same registered
atlas from its mod fingerprint and performs native rendering against its own
Arena, actor list, light grid, and queue.

Generic `sd.world.sprite` follows the existing local-presentation rule: mods
submit on each peer from semantic replicated state. Network actor IDs,
participant IDs, or content IDs may be used by mod logic; native actor,
carrier, queue, renderer, and texture addresses may not cross the protocol.

## Verification contract

Static contracts must prove:

- the RE/design documents and executable addresses are registered;
- world commands have a separate runtime and never enter
  `LuaDrawCommandKind` or `RenderLuaDrawFrame`;
- queue insertion and common Puppet dispatch are reused;
- custom potion draws invoke the native glyph trampoline and no camera
  projection/render-quad queue remains;
- consumable VFX has no EndScene icon lane;
- intentional screen UI owners still use `BeginLuaDrawFrame` /
  `CommitLuaDrawFrame`; and
- the D3D9 overlay keeps its screen-space render-state contract.

Live acceptance requires, in the same scene, a stock potion and the mod potion
with:

1. an actor at larger screen/world Y drawing over both;
2. the actor at smaller screen/world Y drawing under both;
3. both drops responding consistently to local lighting; and
4. the same observations on both local multiplayer peers.

Acceptance captures include the exact loader SHA, pair instance identities,
world coordinates/order state, screenshots from both peers, native-render log
receipts, and the existing wave-boundary plus real-flow E2E gates. The campaign
does not land without those rendered-window observations.

## Compatibility and publication

`sd.items.register`, its `icon` schema, `consume_vfx`, `sd.sprites.register`,
`sd.draw`, and `sd.hud` retain their signatures. The canary mod content needs
no source change: its item drop and active effect move because the loader
runtime beneath those existing APIs changes. `sd.world.sprite` and
`world.render.native` are additive.

Therefore this cutover does not require an Invincibility Potion mod republish.
It requires a loader build containing the seam. No listing or release action
is part of this campaign.
