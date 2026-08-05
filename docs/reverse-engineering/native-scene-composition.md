# Native scene composition

Status: **G12 closed** for retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

This is the frame-assembly contract for the browser WebGL2 renderer. It answers
which native draw is submitted, which physical pass owns it, how it is ordered,
and how its world geometry becomes screen geometry. The ordered live recordings
are committed as
[`scene-composition-goldens.json`](../../tests/fixtures/webgame/scene-composition-goldens.json).

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

1. establish the Region camera and physical viewport;
2. clear the framebuffer;
3. emit the room's direct underlay draws in native call order;
4. gather every shared world object, compute its native queue key, and flush the
   queue in the order specified below;
5. emit direct overdraw and world-projected indicator draws in native call
   order; and
6. emit screen-overlay feedback.

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
Tree sway, Scrub phase, transient Arena ground effects, marker tint, and some
lighting inputs are documented in
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

1. the framebuffer is cleared;
2. Arena light submissions populate the current light field;
3. each queued world object is culled and samples a local light scalar;
4. that scalar is multiplied into the object's/base renderer color;
5. the sprite/mesh is alpha-blended into the framebuffer; and
6. post-scene overlays may darken or color the completed picture.

The common world dispatcher at `0x00624B40` obtains its scalar through
`0x0057F980`, `0x0057F0E0`, or transformed query `0x0057E490`, stores it at
object `+0xCC`, multiplies the object's tint, installs the resulting renderer
color, calls the object's draw virtual, and restores the prior color. When the
complex-lighting global at `0x00B3BCA8` disables the path, the scalar is forced
to `1`. Direct underlay/overdraw art uses the renderer color installed by its
own caller and does not acquire an invented object-light sample.

Renderer color installation at `0x0041FE50` stores the requested RGBA floats
at renderer offsets `+0x1EC..+0x1F8`; its effective color lanes at
`+0x1FC..+0x208` include the active renderer multipliers. Every golden records
the requested tint/alpha at the actual native submission and, when an object
context exists, the sampled `lighting_scalar` separately.

The ordinary captured blend state is:

```text
enabled     = true
source      = D3DBLEND_SRCALPHA       (5)
destination = D3DBLEND_INVSRCALPHA    (6)
operation   = D3DBLENDOP_ADD           (1)

out.rgb = src.rgb * src.a + dst.rgb * (1 - src.a)
```

Per-sprite tint is therefore applied before source-alpha composition. The
golden records blend state per draw so a call site that changes it does not get
flattened into the ordinary rule.

Arena rendering resets the light list, lets current objects submit lights, and
finalizes the light field before it flushes the shared world queue. The normal
player light submission at `0x005299A0` is anchored 15 world units along the
player heading and uses recovered parameters `radius = 2.6`, `intensity = 1`,
and flag `1`; it is enabled by the corresponding player/drive state predicate.
The level-up lane can submit a temporary presentation light while its timer is
positive. Those sources affect subsequent object samples; they do not create a
separate visible sprite layer.

No volumetric fog equation was found in the reachable gameplay compositor.
What players perceive as Boneyard darkness is accounted for by the clear and
underlay colors, the finalized light field and per-object scalar, tinted art,
and post-scene screen overlays. A renderer must not add distance fog merely
because the scene is dark.

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

## Not Yet Reversed

These limits are explicit so an implementing agent does not fill them with a
guess:

- Three Boneyard `world-sorted` draws in the center capture (`DeadHawg.243` at
  draw orders 503 and 517, and `BadGuys.34` at 512) occur during the proven
  queue flush but are dispatched outside the safe common-object context hook.
  Their physical order is recorded, but their object pointer and queue key are
  `null`. Headless decompilation of `0x0068C1C0` confirms that the flush loops
  its private entry list, invokes vtable slot `+0x0C`, and conditionally appends
  bookkeeping after the draw. Exposing the entry at function entry would
  require reimplementing that loop and its side effects, which is outside the
  additive-probe contract. Do not infer a key from the sprite name.
- The exact state-selection rule for every rare additive spell/effect call site
  was not exercised by the hub/Boneyard captures. Preserve the per-draw blend
  state in the renderer API and add a live witness when G4/G2 supplies that
  effect; do not label all translucent art additive.
- No distinct volumetric-fog kernel was reachable. If a later room or effect
  changes a postprocess state beyond the recorded tint/overlay model, record
  that call site and extend `screen-overlay`; do not invent depth fog now.
- The exact transient screen displacement selected from nonzero camera-shake
  magnitude is not present in these zero-shake goldens. The semantic
  world-to-screen transform above is complete without it; nonzero shake needs
  a separate live presentation witness before pixel-parity claims include it.

Those residuals do not change the five physical passes, the queue formula,
decor placement path, ordinary camera transform, or the recorded draw order.
