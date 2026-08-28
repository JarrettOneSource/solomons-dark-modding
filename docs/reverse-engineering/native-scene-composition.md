# Native scene composition

Status: **G12 frame assembly closed; Arena pixel path corrected 2026-08-27**
for retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

This is the frame-assembly contract for the browser WebGL2 renderer. It answers
which native draw is submitted, which physical pass owns it, how it is ordered,
and how its world geometry becomes screen geometry. The ordered live recordings
are committed as
[`scene-composition-goldens.json`](../../tests/fixtures/webgame/scene-composition-goldens.json).
The selected texture/vertex color then becomes a pixel according to
[`native-arena-render-pipeline.md`](native-arena-render-pipeline.md). That
report supersedes this document's former implication that Arena tint and blend
selectors were the complete color pipeline.

G4 has a deliberately different boundary. The G4 row in
[`browser-rebuild-roadmap.md`](../browser-rebuild-roadmap.md) owns animation
state: state transitions, timing, the selected frame, and attachment points.
The older
[`wizard-render-animation-deep-dive.md`](../wizard-render-animation-deep-dive.md)
is supporting animation evidence. G12 begins after animation or object logic has
selected a concrete native `Sprite *`. This document does not duplicate G4's
state machine; it specifies how that chosen sprite becomes part of one picture.

No gameplay behavior was changed for this investigation. The live recorder is
opt-in through `SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY`, records native calls in
place, refuses an ambiguous sprite lookup, and writes a new JSON file
atomically. Its Lua surface is limited to
`sd.debug.queue_native_scene_capture(label)` and
`sd.debug.get_native_scene_capture_status()`. The capture status distinguishes
busy from broken setup, and initialization proves that the output directory is
writable before a request can be queued.

## The renderer contract in one pass

For each gameplay frame, the browser renderer must do this in order:

1. establish the Region camera and physical viewport; Arena additionally binds
   its exact `0.65` per-fragment saturation shader before any target or draw;
2. clear the framebuffer;
3. emit the room's direct underlay draws in native call order;
4. gather every shared world object, compute its native queue key, and flush the
   queue in the order specified below;
5. emit direct overdraw and world-projected indicator draws in native call
   order; and
6. emit screen-overlay feedback, then restore Arena saturation to identity
   before later HUD/menu rendering.

There is no global depth buffer that can replace those steps. Within the shared
world queue, later draws cover earlier draws. Between physical passes, every
draw in a later pass covers every draw in an earlier pass. Alpha blending then
combines a submitted fragment with the existing framebuffer.

The words **layer** and **role** are not interchangeable in this contract:

- `layer` is one of the five physical passes below and is globally ordered;
- `semantic_role` says what the art depicts; roles may share a pass and may
  interleave in native call order.

That distinction is observable. Boneyard actors and decor share one sorted
queue. In the hub, world-space UI is followed by later overhead art in the same
overdraw pass. A browser implementation that creates independent global
"actor", "decor", or "UI" layers will produce the wrong occlusion.

## Layers: backmost to frontmost

These are the complete gameplay-scene physical layers. The names and order are
also the normative `layer_order` in every golden.

| Rank | Layer | Allowed occupants | Boundary |
| ---: | --- | --- | --- |
| 0 | `framebuffer-clear` | The renderer clear only. The generated Boneyard capture clears to opaque black; the hub capture observed the room's blue clear argument before room art covers it. | Begins the Region frame and precedes every art submission. |
| 1 | `scene-underlay` | Background/backdrop art, terrain base, roads and terrain meshes, direct scenery bases, compact decor, ground marks, shadows, and other pre-queue effects. | Native direct draws after clear and before the shared render-queue flush, retained in call order. |
| 2 | `world-sorted` | Actors, generated scenery objects, ordinary props, drops, projectiles, spell/effect actors, and loader world carriers. These are all `shared-world-object`; there are no actor/decor/projectile sublayers. | Starts with the first object dispatched by the shared queue and ends with the last queue entry. Ordering is the exact queue rule below. |
| 3 | `scene-overdraw` | Foreground/overhead scenery, post-queue effect art, actor-attached art emitted by post passes, and world-space UI such as target markers, arrows, names, and health indicators. | Native direct draws after the queue flush and before screen-overlay feedback, retained in call order. World-space UI projects through the camera but does not acquire a world sort key. |
| 4 | `screen-overlay` | Full-viewport or edge feedback that is authored in screen coordinates, including darkness/fade/damage-style overlays reached after scene overdraw. This is not the general menu/control tree. | Begins after scene-overdraw; its coordinates do not move with the Region camera. |

The semantic occupants requested by the browser roadmap map as follows:

| Semantic content | Physical placement |
| --- | --- |
| Background/backdrop | `scene-underlay`, in the compiled room renderer's direct order. |
| Terrain | `scene-underlay`; generated Arena base tiles precede roads and terrain/detail draws. |
| Decor | Direct ground/base components use `scene-underlay`; materialized scenery objects use `world-sorted`; explicit canopy/foreground components use `scene-overdraw`. The object's render family decides which components exist. |
| Actors | `world-sorted`. |
| Projectiles and effects | Queue-backed effects use `world-sorted`; ground or post-queue components use the direct pass in which native code submits them. The semantic name does not override the submission boundary. |
| Overhead art | `scene-overdraw`. |
| World-space UI | `scene-overdraw`, in direct call order alongside other post-queue art. |

The Arena renderer makes the boundary particularly clear: it emits its base
and compact passes, gathers its three object families, flushes the queue once,
then emits its foreground and indicator passes. Fixed Regions follow the same
pre-queue / shared-queue / post-queue shape. The live hub and generated
Boneyard recordings name every call with both its physical `layer` and its
`semantic_role`.

## Sort rules

The underlying queue and its `sort_bias` field were first recovered in
[`world-sprite-render-pipeline.md`](../re/world-sprite-render-pipeline.md).
Scene-composition capture confirms that this is the sole within-pass ordering
mechanism for `world-sorted`; semantic roles do not add another comparison.

For an accepted object, queue insertion computes these signed integers:

```text
floor_y         = floor(object.world_y)
floor_sort_bias = floor(object.sort_bias)
reference_y     = floor(local_player.world_y)
relative        = floor_y + floor_sort_bias - reference_y
bucket_offset   = trunc_toward_zero(relative / 2)
bucket_index    = queue.origin + bucket_offset
```

The complete sort key is not merely Y. It is the following structured key,
with `insertion_serial` assigned monotonically in gather order:

```text
if bucket_index < 0:
    key = (leading_overflow, object.world_y, insertion_serial)
elif bucket_index >= queue.bucket_count:
    key = (trailing_overflow, object.world_y, insertion_serial)
else:
    key = (normal, bucket_index, insertion_serial)

lane order = leading_overflow, normal, trailing_overflow
```

The flush emits the leading overflow list, normal buckets from index zero
upward, then the trailing overflow list. A normal bucket is append-only, so
everything in the same two-world-unit bucket remains in insertion order. This
includes different effective Y values that happen to land in one bucket;
`sort_bias` does not perform a second comparison there.

Overflow insertion is different: each overflow list is insertion-sorted by the
raw floating `object.world_y`, ascending. Its comparison advances past entries
whose `existing_y <= new_y`, so exact raw-Y ties remain in insertion order.
`sort_bias` chooses the overflow lane but does not refine order inside that
lane.

Arena gather order, and therefore the normal-bucket tie breaker, is:

1. main `PuppetManager` actors;
2. Arena scenery/prop actors;
3. transient world actors; then
4. loader-owned carriers inserted at the recorder/framework seam.

The ordinary base/player bias is `0`. A `Sack`/drop carrier uses `-25`. Larger
effective Y normally draws later and appears in front; the negative drop bias
moves a drop behind where raw Y alone would place it.

Draws outside `world-sorted` have no queue sort key. Their key is simply
`(physical_layer_rank, native_draw_order_within_layer)`. The golden uses JSON
`null` rather than manufacturing queue fields for those draws.

## Atlas and sprite selection

At the composition boundary a sprite is already a concrete native record. The
record is `0xC4` bytes and contains, among other fields, its native texture-slot
handle, UV rectangle, logical geometry, and point/attachment data. Native
`Glyph_Draw` consumes that record and current renderer state; transform/mesh
paths consume the same resolved art through their own geometry calls.

The logical-to-concrete path is:

```text
object type / renderer branch
    -> animation-owned selected frame or renderer-owned variant index
    -> Sprite * in a compiled atlas span
    -> native texture-slot handle + UVs + logical geometry
    -> submitted quad/mesh under the current transform and tint
```

The recorder-generated atlas table covers 28 native atlas roots and 337
contiguous sprite spans. Positional order is ABI: for example, a renderer that
indexes a base address with stride `0xC4` is selecting the Nth sprite record in
that named span. A direct address is resolved first. If only live record
contents are available, the recorder compares atlas handle, UVs, and logical
geometry across all spans and accepts exactly one candidate. Zero candidates
are recorded as unresolved; more than one is an error. It never silently picks
between duplicate candidates.

The generated Boneyard exposes both sides of selection. Compact decoration
types index compiled `DeadHawg` sprite runs directly; materialized scenery
objects select their stored variant before submitting base, overlay, or
foreground art. Tree generation, for example, stores its position and variant
inputs before reload/materialization; Tree's component renderers later resolve
those values to their respective `DeadHawg` spans. The browser should preserve
the typed/variant input and apply the same atlas index, not hash a display name
or choose a visually similar frame.

Random selection is owned by the native RNG streams, not by the renderer. G1's
landed findings in
[`native-movement-and-tick.md`](native-movement-and-tick.md#active-stream-and-seeding-lifecycle)
establish the 55-word additive lagged-Fibonacci stream modulo `2^30`, the
stock level-construction seed idiom `App[+0x28] * 0xEF3` at twelve byte-verified
sites, and the shared/private stream boundaries. Boneyard generation draws
`Integer(999999)` from the active stream, seeds a private stack stream, and
copies all 58 dwords of its final state back to the active object. G12 consumes
those selected variant values; it does not re-derive or replace G1's RNG.

There are also presentation-only random consumers after layout generation:
Tree local occlusion alpha, Scrub phase, transient Arena ground effects,
marker tint, and some lighting inputs are documented in
[`native-default-boneyard-load-seed-and-decor.md`](native-default-boneyard-load-seed-and-decor.md).
They must be modeled as presentation state if pixel-identical replay is
required. They are not permission for the renderer to choose a new static decor
variant.

## Backdrop assembly

The native gameplay renderer has no independent parallax layer in either live
scene. Hub backdrop art is compiled world art in `scene-underlay`. With camera
origin X moved by exactly `+200` world units at scale `1.2`, stable College
sprites move by `-240` screen pixels while their recovered world coordinates
remain fixed. Therefore their parallax rate is exactly the ordinary world rate:

```text
screen_delta = -camera_origin_delta * camera_scale
parallax_factor = 1
```

There is no slower/faster backdrop factor and no screen-anchored backdrop
exception in the captured room.

Fixed rooms submit a finite compiled art list. They do not wrap or repeat the
backdrop when the camera moves; normal camera bounds prevent exposing space
outside the authored world. The room renderer still culls direct art against
its native view/culling rectangles.

The generated Arena separately covers its ground with base tiles before roads,
terrain detail, compact decor, and sorted objects. In the recorded environment
mode the base sprite is `DeadHawg.12`, with logical `350 x 350` tiles placed on
a 350-world-unit grid. This is coverage of a finite generated world, not a
camera-relative infinite scroll: loop bounds come from the Arena/world extent,
and the native view/culling tests decide which submissions survive. Roads,
terrain records, fences, buildings, and decor remain finite seeded world data.

## Decor placement and determinism

The authoritative load and materialization path is recovered in
[`native-default-boneyard-load-seed-and-decor.md`](native-default-boneyard-load-seed-and-decor.md):

```text
main-menu case 3
    -> data\levels\survival.boneyard Gameplay template
    -> Gameplay_SwitchRegion(region 5)
    -> Arena_Create
    -> choose play.boneyard or testrun.boneyard
    -> BoneyardGenerator 0x006388B0
    -> serialize temporary Arena/RegionLayout
    -> read through the ordinary structured loader
    -> RegionLayout materialization 0x006531B0
```

For the recorder-owned deterministic run, the synchronized 30-bit run seed is
reapplied immediately before the stock `Arena_Create` call at the named
`arena_create_pre_stock` boundary. The generator then makes its first
`Integer(999999)` draw, initializes its stack RNG, and copies the resulting 58
dwords back to the active stream. All subsequent Tree, gravestone, Goodie,
building, road, fence, terrain, compact-decoration, recipe, UID-group, trigger,
and timeline choices consume that native path.

The save/reload boundary is part of the algorithm. A browser implementation
must not replace it conceptually with a list of visible Tree coordinates:
serialization and materialization expand fences, replace designated Tree
variants with Scrub, rebuild spatial/bounds state, and resolve object ownership.
For identical generation input, reproduce the complete generated records in
native order, then materialize them with the same typed rules.

The byscript recipe findings in
[`boneyard-scripting.md`](boneyard-scripting.md) define a separate phase.
`MonsterRecipe`, `ItemRecipe`, `NPCRecipe`, `ItemSet`, and UID groups are
definition stores. Post-load relinking at `0x0064BC40` turns serialized UIDs
into live references used by triggers, cooperative script threads, and
TimeLine/Spawner actions. Those recipe actions may create later runtime
objects, but they are not static decor draw entries and are not a second decor
placement seed.

The live seed-`424242` replay comparison pins the boundary precisely. Across
two fresh generated runs, all 477 pre-queue sprite selections, atlas identities,
draw kinds, and submitted positions are identical. One transform matrix, one
inverse-projected quad, and one tint differ, matching documented dynamic
presentation state rather than layout selection. Thus the browser determinism
input is:

```text
layout = f(active RNG state at Arena_Create, generated environment inputs)
pixels = compose(layout, current animation state, current presentation RNG,
                 current lighting state, camera)
```

Identical layout input guarantees identical decor placement/selection. Exact
pixels additionally require a policy for native presentation state; silently
re-rolling decor in the render loop is incorrect.

## Fog, lighting, tint, alpha, and blend

The observed native darkness model is compositional rather than one global
"fog color":

1. the framebuffer is cleared and direct base/underlay/compact lanes paint;
2. Arena light submissions rasterize an offscreen light texture and populate
   the matching analytic source field;
3. with Complex Lighting enabled, the light texture multiplicatively
   composites over the already-painted pre-main lanes;
4. each queued world object is culled, samples a local analytic scalar, and
   builds zero or more complex-shadow records from flagged nearby sources;
5. the object's painter projects authored-normal-visible outline edges away
   from each source as black, alpha-tapered quads immediately before its main
   art;
6. the local scalar is multiplied into the object's renderer color before the
   sprite/mesh is alpha-blended;
7. late proxy/foreground lanes paint after the shared queue; Tree secondary
   art additionally applies its Tree-root analytic scalar explicitly; and
8. post-scene overlays may darken or color the completed picture.

The common world dispatcher at `0x00624B40` obtains its scalar through
`0x0057F980`, `0x0057F0E0`, or transformed query `0x0057E490`, stores it at
object `+0xCC`, multiplies the object's tint, installs the resulting renderer
color, calls the object's draw virtual, and restores the prior color. When the
complex-lighting global at `0x00B3BCA8` disables the path, the scalar is forced
to `1`. Direct underlay/overdraw art uses the renderer color installed by its
own caller and does not acquire an invented object-light sample. Pre-main
direct art is nevertheless affected by the separate Region light-texture
multiply; late proxy/foreground art is not. Tree secondary painter
`0x00608830` is the explicit exception to the generic late-lane rule: after
the multiply boundary it installs RGB from Tree color scalar `+0xD0` times the
already sampled root scalar `+0xCC`, and uses Tree visibility alpha `+0x150`.
Building is the other explicit exception. Its main painter `0x0060E940`
samples the elevated Region query `0x0057E640` at every retained grid vertex;
upper painter `0x0060EC50` reuses the same packed color array for the late roof
glyph. Monument remains on the common root-scalar path.

Renderer color installation at `0x0041FE50` stores the requested RGBA floats
at renderer offsets `+0x1EC..+0x1F8`; its effective color lanes at
`+0x1FC..+0x208` include the active renderer multipliers. Every golden records
the requested tint/alpha at the actual native submission and, when an object
context exists, the sampled `lighting_scalar` separately.

That packed color is an input, not the final Arena RGB. `Arena::Render
0x0046EC80` binds the shader compiled at `0x0043FD80` with saturation `0.65`.
For unpremultiplied texture RGB `T` and vertex RGB `V`, it computes
`lerp(avg(T)*avg(V), T*V, 0.65)` per fragment and preserves
`textureAlpha*vertexAlpha`. This happens before blending for direct underlays,
the shared queue, late art, and Arena-owned screen feedback. It is not
equivalent to desaturating the completed canvas. Exact HLSL, texture upload,
sampler state, blend tables, primitive callers, and the Arena/HUD boundary are
closed in `native-arena-render-pipeline.md` and its generated xref catalog.

The ordinary captured blend state is:

```text
enabled     = true
source      = D3DBLEND_SRCALPHA       (5)
destination = D3DBLEND_INVSRCALPHA    (6)
operation   = D3DBLENDOP_ADD           (1)

out.rgb = src.rgb * src.a + dst.rgb * (1 - src.a)
```

Per-sprite tint and the Arena shader are therefore applied before source-alpha
composition. The golden records requested tint and blend state per draw; the
pipeline report supplies the formerly missing shader state so a call site does
not get flattened into the ordinary rule.

Arena rendering resets the light list, lets current objects submit lights, and
finalizes the offscreen field before it flushes the shared world queue.
`0x0057FE40` both stamps alpha-graded DeadHawg record `18` into that field and
records the source for analytic queries. `0x0057D670` composites the field with
blend factors `ZERO, SRCCOLOR`. At Complex Lighting on callsite `0x0046FAFF`,
that multiply precedes shared queue flush `0x0046FDAF`; at Complex Lighting off
callsite `0x00470107`, it follows the queue and supplies the cheaper flattened
result. The normal player light submission at `0x005299A0` is anchored 15 world
units along the player heading and uses recovered parameters `radius = 2.6`,
`intensity = 1`, and flag `1`; it is enabled by the corresponding player/drive
state predicate. Every provider pass draws DeadHawg record `18` into the
offscreen raster field at scale `2.6 - RandomFloat(0.2)`. While the player's
level-up timer is positive, the analytic source radius separately becomes
`2.6 * (1 + player+0x268) + sin(pi * timer / 180)`; the ordinary constructor
sets `player+0x268` to zero. These sources therefore own both a visible ground
light field and subsequent object samples; they are not merely invisible
scalar records, and the raster jitter must not replace the analytic radius.

### Player-owned level-up beam and sparkle lane

A real level transition reaches `0x00528A20` and writes `180.0` to player
`+0x168`; the same owner requests registry 52 `sounds\levelup` once at gain
`1.0`. `Player::Tick` at `0x0053380E` checks the positive timer, decrements
it first, and, only when the player point is inside the primary view rectangle,
allocates one `Anim_Sparkle` in the actor-owned child list at `+0x16C`. Let `T`
be the post-decrement timer. Spawned values are `179..0`; the final child has
zero alpha. The newly inserted list member is ticked in the same player tick,
so its first rendered state has life `177` and local Y advanced by `-0.1`.
Actor/world pause freezes both the emitter and its children; picker UI or wall
time does not consume either lifetime.

The shared point/rectangle predicate at `0x00403DA0..0x00403DEF` is half-open:
`x >= left && x < right && y >= top && y < bottom`. A point on the left or top
edge emits; a point exactly on the right or bottom edge does not.

The exact local spawn program is:

```text
x = RandomFloat(30, signed=true)       // magnitude [0,30], independent sign
y = -20 - RandomFloat(playerY - primaryViewTop)
angle = RandomFloat(360)
alpha = 0.75 * sin(pi * T / 180) * (1 - abs(x) / 30)
RGB = (1, 1, 1)
```

`Anim_Sparkle` constructor `0x00453980` starts at life `180`. Tick
`0x00453A30` subtracts `3` from life and `0.1` from local Y, retiring the child
at life `<= 0`; a child therefore lasts 60 player ticks and may outlive the
180-tick emitter. Draw `0x00458230` uses the fixed spawn alpha, random angle,
and uniform scale `sin(pi * life / 180)` with BadGuys record `73` (`12 x 13`,
SHA-256 `a8aaa295bc2876d2e446298bbb7bf2a8db61c53cf53937ab0bf58c02a5c0327e`).

Player presentation `0x0052A640` first draws a beam while `T > 0` and the
player remains inside the primary view, then draws the actor-owned sparkle
list. It maps BadGuys record `36` (`27 x 88`, SHA-256
`226c28f84963c74e46ea18abcfddaec71e6e19b18f3e32ec7d20ebe8c70406da`)
onto this world quad:

```text
p0 = (playerX - 35, primaryViewTop - 200)
p1 = (playerX + 35, primaryViewTop - 200)
p2 = (playerX - 40, playerY - 10)
p3 = (playerX + 40, playerY - 10)
RGBA = (1, 1, 0.9, 0.5 * sin(pi * T / 180))
```

The immediate `Arena::Render` caller invokes player vtable slot `+0x24` at
`0x0046FEF6..0x0046FEFE`, after shared world-queue flush `0x0046FDAA` and
before later proxy/foreground banks. Neither this player draw nor
`Anim_Sparkle::Draw` changes renderer blend selector `renderer+0x221`.
Selector zero is the initialized ordinary state
`SRCALPHA, INVSRCALPHA, ADD`; adjacent genuinely additive renderers explicitly
switch to selector one and restore zero. The beam and sparkle lane is therefore
ordinary source-alpha, in beam-then-child order, and is not a Y-sorted actor
body layer or a picker overlay.

Complex-shadow query `0x0057F0E0` uses the same elliptical source field but
accepts only source records whose `+0x18` flag is set. It writes per-object
0x24-byte records containing source direction/position, multi-source base
opacity, one-unit-behind light sample, normalized distance, projection length,
and source radius. When `Game.ComplexShadows` (`0x00B3BCA9`) is enabled, Tree,
Gravestone, Fencepost, and the adjacent scenery/fence painters consume those
records. Shape closer `0x00655570` preserves authored order and stores
`(edge.dy,-edge.dx)` without winding normalization. Shared helper `0x00655970`
keeps strict-positive `dot(normal, midpoint-source)` edges and projects each
endpoint away from the source by
`(145 - RandomFloat()) * radius`; base alpha is the multi-source factor and
the projected alpha is `((1 - behindScalar) * (1 - distanceFraction))^3`.
The ordinary player provider always sets the required flag. Lantern and most
ordinary effect providers instead pass the retail Multiple Shadows byte. Fresh
shipped-Windows initialization defaults that byte on through platform
capability `0x00B3BCAE`; the preserved sandbox settings profile explicitly
overrides it off. Complex Lighting and Complex Shadows both default on. See
[`native-lighting-and-shadow-system.md`](native-lighting-and-shadow-system.md)
for the complete default derivation, source census, and painter programs.

No volumetric fog equation was found in the reachable gameplay compositor.
What players perceive as Boneyard darkness is accounted for by the clear and
underlay colors, the multiplied Region light texture, the per-object scalar,
tinted art, and post-scene screen overlays. A renderer must not add distance
fog merely because the scene is dark.

## Camera and the exact world-to-screen transform

The camera is Region-owned. The field map and stock update phase build on
[`native-camera-control.md`](native-camera-control.md). For frame assembly the
relevant rectangles are:

- world bounds: the legal authored/generated extent;
- primary view: world-space origin and visible width/height;
- expanded view: primary origin minus 50 on each axis, width/height plus 100;
- culling view: the native eligibility rectangle used by object/direct-art
  tests; and
- scale: uniform screen pixels per world unit.

Let the primary view be `(vx, vy, vw, vh)` and scale be `s`. For every world
point `(wx, wy)` the native geometric projection is exactly:

```text
sx = (wx - vx) * s
sy = (wy - vy) * s

wx = sx / s + vx
wy = sy / s + vy

viewport_width_px  = vw * s
viewport_height_px = vh * s
```

For a sprite quad or transformed mesh, first obtain every world-space vertex,
apply that formula to each vertex, and take the axis-aligned min/max to obtain
`resolved_screen_rect = [left, top, right, bottom]`. Do not project only the
object anchor: rotation, scale, atlas origin, and attachment offsets are already
represented by the submitted world quad/matrix and can extend on either side of
it.

The primary origin is the semantic render origin. A centered stock target
starts as:

```text
vx = focus_world_x - vw / 2
vy = focus_world_y - vh / 2
```

and is clamped independently to:

```text
bounds.x <= vx <= bounds.x + bounds.w - vw
bounds.y <= vy <= bounds.y + bounds.h - vh
```

when the world dimension exceeds the view dimension. Fixed-room player
tracking uses the recovered `0.25` interpolation toward its target. Arena
camera update additionally consumes its current base/zoom pulse and player
presentation offset before applying the same visible-world constraint. The
captured hub bounds are `[0, 0, 2000, 1100]`; the generated Boneyard bounds are
`[0, 0, 2795.36011, 3004.63989]`.

Expanded and culling views are not alternate projection origins. Expanded is a
50-world-unit observation margin around primary. Culling is a separate native
eligibility rectangle and may be much wider than primary. Use primary for
projection and culling for whether work is submitted. The moved captures make
that separation observable: the Boneyard shared-queue draw count falls from 40
to 4 while the finite underlay set changes with the culling window.

Camera shake is presentation state downstream of the stored semantic primary
origin. The live goldens intentionally capture `shake_magnitude = 0`, so their
rectangles test the formula without a transient displacement.

### P0 controller aim reach

The native input contract establishes the screen anchor as:

```text
aim_anchor_px = project(player_world) + (0, -25)
```

For default viewport size `(W, H)`, a single direction-independent screen
reach that keeps the synthesized aim point inside the visible play area in
every direction is the largest inscribed radius around that anchor:

```text
reach_px = min(aim_anchor_px.x,
               W - aim_anchor_px.x,
               aim_anchor_px.y,
               H - aim_anchor_px.y)

reach_world = reach_px / camera_scale
aim_world = player_world + (0, -25 / camera_scale)
            + normalize(stick) * reach_world
```

P0 must evaluate this at the documented default zoom/camera placement and
record the resulting number next to the input producer. If the browser instead
wants maximum reach for each direction, intersect the ray from `aim_anchor_px`
with the viewport and divide that directional distance by `camera_scale`; that
is no longer the roadmap's single derived `reach` constant. In either case,
the `-25` is a screen-pixel offset and must be converted by the current scale.

## Live golden set

The committed fixture contains four native ordered draw lists:

| Capture | Camera center | Purpose |
| --- | ---: | --- |
| `hub_camera_1000_375_final` | `(1000, 375)` | Hub layer occupancy, compiled backdrop, world queue, overhead art, and world-space UI. |
| `hub_camera_1200_375_final` | `(1200, 375)` | Same room after a `+200` world-X camera move; proves full-rate backdrop motion and changed culling. |
| `boneyard_seed_424242_camera_1000_1000_final` | `(1000, 1000)` | Fresh stock generated Boneyard with deterministic seed boundary, base/terrain/decor, and shared queue. |
| `boneyard_seed_424242_camera_1500_1500_final` | `(1500, 1500)` | Same generated world after camera movement; exposes finite tile/decor submissions and queue culling. |

Each capture header names the instance, clean source base SHA, exact game and
loader hashes, raw evidence-bundle hash, capture method, camera, scene/seed,
and epsilon justification. Every draw retains physical layer, semantic role,
complete queue key when observed, sprite/atlas resolution, world transform,
tint/alpha, blend state, and resolved screen rectangle. The standalone fixture
SHA-256 is `7bf5adec2f4425e07d42465b7dc3cefbab004dd7133b951a06ebccedeb3885c2`.

The `0.001` screen-pixel/world-unit epsilon is not a visual tolerance. Native
float32 and x87 intermediates are serialized to nine significant digits; the
largest replay error in the four recordings is below `0.000256` pixels. The
declared epsilon sits above representation noise and below one native pixel.

## 2026-08-27 residual closure

The former open rows are now closed by the game-wide pipeline census in
[`native-full-render-pipeline.md`](native-full-render-pipeline.md):

- `DeadHawg.243` at draw orders 503/517 is the Tree overlay member owned by
  `Tree 0x00608830`; its two matrices pair with the captured type-2001 Tree base
  draws and inherit those queue keys. `BadGuys.34` at 512 is the sole art of
  `Lantern::Render 0x005E61D0`, factory type 5010, at its submitted world point.
  The recorder lost a temporary context pointer, not native ownership.
- all 404 renderer-selector writes are instruction-cataloged and joined to
  their class/vtable owners. The rare effect paths now have exact
  normal/additive/multiply dispositions rather than relying on one live frame.
- the complete executable has only the Arena saturation shader and a dormant
  never-requested blur shader. There is no other scene shader or volumetric-fog
  kernel.
- nonzero camera feedback is the already-recovered deterministic uniform
  `1 + magnitude` scale about the local Player's projected point. It is not a
  random screen displacement; see
  [`native-camera-control.md`](native-camera-control.md).
- Teacher release children cross three physical passes rather than inheriting
  the Teacher actor root. Flare is `scene-underlay` through `Region+0x278`;
  column then additive frames are `world-sorted` through `Region+0x8B70` at
  `teacher.y+15`; core is `scene-overdraw` through `Region+0x22C`. Courtyard
  calls those manager painters immediately before and after shared queue flush
  `0x0068C480` at `0x0051FD14..0x0051FD33`.

The five physical passes, queue formula, decor placement, camera transform,
and draw order therefore have no remaining extractable native unknown.
